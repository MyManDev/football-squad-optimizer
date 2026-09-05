"""Outcome-free Phase E runtime, diversity and coverage probe (E2).

This is the E2 probe of ``docs/phase_e_candidate_selection_prereg.md``. It measures what the
candidate generator and the fixed selector cost and how they behave on real decision pools,
and it consults no realized outcome of any probed decision point:

- a live decision point contributes the projection the decide phase itself used;
- a historical fold contributes its full decision roster, rebuilt from the same walk-forward
  control projection the binding Phase D run used, with the decision gameweek's realized
  columns blanked before the projection builder sees them, and the Phase C handoff's
  ``control_expected_points`` on top; the outcome readers the E3 evaluation needs
  (``realized_points_at``, ``prepare_phase_c_component_folds``) are never called here;
- the residual pool the sampler draws from is built from folds strictly before the target,
  so past residual observations are used and target outcomes are not.

The frozen candidate count is decided by the preregistered rule and only when the full E2
pool set was probed under its exact identities; a smaller or partial run reports what it
measured and freezes nothing.

The production calibration pin (``squadopt.application.phase_e.PHASE_E_CALIBRATED_VERSIONS``)
is passed to the selector as it stands. While it is empty every production selection falls
back before any scenario is scored, so that early fallback's runtime is recorded as what it is
and scoring runtime is measured directly. Repeatability and seed sensitivity, which need a
selection that reaches the scenarios, use a probe-only pin equal to the draw's own provenance.
That override is labelled on every record, is not the production pin and claims no calibration.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any, Final

import numpy as np
import pandas as pd
from scripts._experiment_cli import (
    DEFAULT_ARCHIVE_ROOT,
    REPOSITORY_ROOT,
    artifact_metadata,
    write_json,
)
from scripts.run_component_squad_calibration import (
    BINDING_FOLD_COUNT,
    DECISION_SEASONS,
    DIRECT_CONTROL_ABSTENTIONS,
    HISTORY_BURN_IN_FOLDS,
    HISTORY_SEASONS,
)

from squadopt.application.phase_e import PHASE_E_CALIBRATED_VERSIONS
from squadopt.backtest import (
    make_ridge_projection_builder,
    rows_through,
    walk_forward_decision_points,
)
from squadopt.data import DataError
from squadopt.data.snapshots import read_snapshot
from squadopt.data.sources.vaastav import build_panel
from squadopt.evaluation import read_phase_c_component_handoff
from squadopt.evaluation.component_handoff import PhaseCComponentHandoff
from squadopt.features import CrossSeasonConfig
from squadopt.live.recommendation import project, read_inputs, read_projection_handoff
from squadopt.optimization import (
    OptimizationConfig,
    OptimizationResult,
    SolverStatus,
    SquadCandidateSet,
    decision_signature,
    generate_squad_candidates,
)
from squadopt.prediction import (
    PredictionProvenance,
    PredictionSnapshot,
    prepare_optimizer_projection,
)
from squadopt.prediction.components import COMPONENT_MODEL_ROUTE
from squadopt.scenarios import (
    ScenarioConfig,
    ScenarioTarget,
    ScenarioValidationError,
    integer_mean_cvar,
    score_component_scenario_decision,
    select_phase_e_candidate,
)
from squadopt.scenarios.components import (
    ComponentScenarioDraw,
    ComponentScenarioInputs,
    ComponentScenarioProvenance,
    paired_conditional_residuals,
    sample_component_scenarios,
)
from squadopt.scenarios.selection import (
    PHASE_E_CANDIDATE_COUNTS,
    PHASE_E_RISK_WEIGHT,
    PHASE_E_SCENARIO_COUNT,
    PHASE_E_TAIL_COUNT,
    PHASE_E_WEIGHT_SCALE,
)

PROBE_CONTRACT_VERSION: Final = "phase_e_runtime_probe_v1"
PREREGISTRATION: Final = "docs/phase_e_candidate_selection_prereg.md"
SENSITIVITY_SEEDS: Final = (1, 2, 3, 4)
BUDGET_SECONDS: Final = 120.0
E2_LIVE_LABELS: Final = ("2026-27-gw01", "2026-27-gw02", "2026-27-gw03")
E2_FOLD_COUNT: Final = BINDING_FOLD_COUNT
POOL_COLUMNS: Final = (
    "player_id",
    "name",
    "team_id",
    "position",
    "price_tenths",
    "expected_points",
)
COMPONENT_INPUT_COLUMNS: Final = (
    "player_id",
    "team_id",
    "position",
    "fixture_count",
    "appearance_probability",
    "expected_minutes_if_appearance",
    "raw_expected_points_if_appearance",
    "composition_route",
    "evidence_status",
)
REALIZED_COLUMNS: Final = ("total_points", "minutes")
LIVE_DRAW_UNAVAILABLE: Final = (
    "no component scenario inputs exist for a live gameweek: the Phase C component handoff "
    "covers development folds only, so no draw, scoring or selection can be measured here"
)
OUTCOME_POLICY: Final = (
    "live pools are the decide phase's own projections; fold pools are rebuilt from the "
    "walk-forward control projection with the decision gameweek's total_points and minutes "
    "blanked before the builder runs, plus the handoff's control_expected_points; residual "
    "pools use folds strictly before the target; realized_points_at and "
    "prepare_phase_c_component_folds are not called"
)
DEFAULT_SNAPSHOT_ROOT: Final = REPOSITORY_ROOT / "data" / "snapshots"

DrawFactory = Callable[[int], ComponentScenarioDraw]
Record = dict[str, Any]


class ProbeError(ValueError):
    """Raised when a probe input is missing or inconsistent; nothing is invented instead."""


@dataclass(frozen=True, slots=True)
class DecisionPoint:
    """One pool to probe.

    ``draw_factory`` maps a scenario seed to the one shared draw every candidate of this
    decision is scored on; ``None`` means no draw exists here and ``draw_unavailable_reason``
    says why. ``covered_player_ids`` is the set a draw covers, known before drawing, or
    ``None`` when unknown.
    """

    label: str
    kind: str
    pool: pd.DataFrame
    draw_factory: DrawFactory | None = None
    draw_unavailable_reason: str | None = None
    covered_player_ids: frozenset[int] | None = None

    def __post_init__(self) -> None:
        if self.kind not in ("live", "fold"):
            raise ProbeError(f"kind must be 'live' or 'fold', got {self.kind!r}.")
        missing = [name for name in POOL_COLUMNS if name not in self.pool.columns]
        if missing:
            raise ProbeError(f"{self.label}: pool is missing {missing!r}.")
        if (self.draw_factory is None) == (self.draw_unavailable_reason is None):
            raise ProbeError(f"{self.label}: exactly one of draw_factory or its reason is set.")


# --------------------------------------------------------------------------------------
# One decision point
# --------------------------------------------------------------------------------------


def _ids(frame: pd.DataFrame) -> set[object]:
    return set(frame["player_id"].tolist())


def _candidate_record(
    rank: int, candidate: OptimizationResult, control: OptimizationResult
) -> Record:
    squad, eleven, captain = decision_signature(candidate)
    control_squad, control_eleven, control_captain = decision_signature(control)
    diagnostics = candidate.diagnostics
    return {
        "rank": rank,
        "squad_ids": [str(value) for value in squad],
        "eleven_ids": [str(value) for value in eleven],
        "captain_id": str(captain),
        "solver_status": candidate.solver_status.value,
        "tiebreak_attempted": diagnostics.get("tiebreak_attempted"),
        "tiebreak_completed": diagnostics.get("tiebreak_completed"),
        "solve_seconds": diagnostics.get("solve_time_seconds"),
        "objective": candidate.objective_value,
        "deterministic_gap": (
            None
            if control.objective_value is None or candidate.objective_value is None
            else control.objective_value - candidate.objective_value
        ),
        "squad_overlap": len(set(squad) & set(control_squad)),
        "eleven_overlap": len(set(eleven) & set(control_eleven)),
        "same_captain": bool(captain == control_captain),
        "bench_only_difference": bool(
            squad != control_squad and eleven == control_eleven and captain == control_captain
        ),
    }


def _diversity(candidates: Sequence[OptimizationResult], pool_size: int) -> Record:
    signatures = [decision_signature(candidate) for candidate in candidates]
    control = signatures[0]
    union: set[object] = set()
    for squad, _, _ in signatures:
        union.update(squad)
    objectives = [candidate.objective_value for candidate in candidates]
    last = objectives[-1]
    first = objectives[0]
    return {
        "distinct_signatures": len(set(signatures)),
        "distinct_squads": len({squad for squad, _, _ in signatures}),
        "distinct_elevens": len({eleven for _, eleven, _ in signatures}),
        "distinct_captains": len({captain for _, _, captain in signatures}),
        "bench_only_candidates": sum(
            bool(squad != control[0] and eleven == control[1] and captain == control[2])
            for squad, eleven, captain in signatures[1:]
        ),
        "player_union_size": len(union),
        "pool_size": pool_size,
        "delta_k": None if first is None or last is None else first - last,
    }


def _generate(
    pool: pd.DataFrame, config: OptimizationConfig, count: int
) -> tuple[SquadCandidateSet, float]:
    started = perf_counter()
    generated = generate_squad_candidates(pool, config, candidate_count=count)
    return generated, perf_counter() - started


def _same_decisions(first: SquadCandidateSet, second: SquadCandidateSet) -> bool:
    if (
        first.complete != second.complete
        or first.termination_status is not second.termination_status
    ):
        return False
    if len(first.candidates) != len(second.candidates):
        return False
    if not first.control.has_solution:
        return not second.control.has_solution
    return [decision_signature(c) for c in first.candidates] == [
        decision_signature(c) for c in second.candidates
    ] and [c.objective_value for c in first.candidates] == [
        c.objective_value for c in second.candidates
    ]


def _coverage(candidates: Sequence[OptimizationResult], covered: set[object]) -> list[bool]:
    return [_ids(candidate.selected_squad) <= covered for candidate in candidates]


def _score(
    candidates: Sequence[OptimizationResult], draw: ComponentScenarioDraw, covered: Sequence[bool]
) -> tuple[list[Record], float]:
    records: list[Record] = []
    total = 0.0
    for rank, (candidate, is_covered) in enumerate(zip(candidates, covered, strict=True)):
        if not is_covered:
            records.append({"rank": rank, "covered": False})
            continue
        started = perf_counter()
        scored = score_component_scenario_decision(candidate, draw)
        elapsed = perf_counter() - started
        total += elapsed
        utility = integer_mean_cvar(scored.total_points)
        records.append(
            {
                "rank": rank,
                "covered": True,
                "scoring_seconds": elapsed,
                "mean": utility.mean,
                "cvar": utility.cvar,
                "utility_int": utility.utility_int,
            }
        )
    return records, total


def _select(
    candidates: SquadCandidateSet,
    draw: ComponentScenarioDraw,
    pins: tuple[tuple[str, str], ...],
) -> Record:
    started = perf_counter()
    selection = select_phase_e_candidate(
        candidates.candidates,
        draw,
        candidate_count_requested=candidates.candidate_count_requested,
        candidate_set_complete=candidates.complete,
        calibrated_versions=pins,
    )
    return {
        "status": selection.selection_status.value,
        "selected_candidate_rank": selection.selected_candidate_rank,
        "candidate_count_proven": selection.candidate_count_proven,
        "candidate_count_scored": selection.candidate_count_scored,
        "utilities_int": [record.utility_int for record in selection.diagnostics],
        "seconds": perf_counter() - started,
    }


def _draw_identity(draw: ComponentScenarioDraw) -> Record:
    return {
        "scenario_fingerprint": draw.scenarios.scenario_fingerprint,
        "component_fingerprint": draw.component_fingerprint,
        "scenario_count": len(draw.scenarios.scenario_ids),
        "covered_player_count": int(draw.scenarios.scenario_points.shape[1]),
        "deterministic_seed": draw.scenarios.config.deterministic_seed,
    }


def _probe_scoring(
    point: DecisionPoint,
    candidates: SquadCandidateSet,
    *,
    sensitivity_seeds: Sequence[int],
    warnings: list[str],
) -> Record:
    assert point.draw_factory is not None
    started = perf_counter()
    draw = point.draw_factory(0)
    draw_seconds = perf_counter() - started
    draw_columns: set[object] = {int(value) for value in draw.scenarios.scenario_points.columns}
    if point.covered_player_ids is not None and set(point.covered_player_ids) != draw_columns:
        warnings.append(
            f"{point.label}: the draw covers {len(draw_columns)} players but "
            f"{len(point.covered_player_ids)} were expected from the component rows."
        )
    covered = _coverage(candidates.candidates, draw_columns)
    scored, scoring_seconds = _score(candidates.candidates, draw, covered)

    production = _select(candidates, draw, PHASE_E_CALIBRATED_VERSIONS)
    probe_pin = ((draw.inputs.provenance.model_version, draw.inputs.contract_version),)
    diagnostic = _select(candidates, draw, probe_pin)

    repeated_draw = point.draw_factory(0)
    repeated_selection = _select(candidates, repeated_draw, probe_pin)
    draw_repeat_identical = _draw_identity(repeated_draw) == _draw_identity(draw)
    selection_repeat_identical = (
        repeated_selection["status"] == diagnostic["status"]
        and repeated_selection["selected_candidate_rank"] == diagnostic["selected_candidate_rank"]
        and repeated_selection["utilities_int"] == diagnostic["utilities_int"]
    )

    by_seed: dict[str, Record] = {"0": diagnostic}
    changes = 0
    for seed in sensitivity_seeds:
        seeded = _select(candidates, point.draw_factory(seed), probe_pin)
        by_seed[str(seed)] = seeded
        if seeded["selected_candidate_rank"] != diagnostic["selected_candidate_rank"]:
            changes += 1

    return {
        "draw": _draw_identity(draw),
        "draw_seconds": draw_seconds,
        "candidates": scored,
        "candidates_covered": sum(covered),
        "candidates_eliminated": len(covered) - sum(covered),
        "control_covered": covered[0],
        "scoring_seconds_total": scoring_seconds,
        "selector_production": {
            **production,
            "pin": [list(pair) for pair in PHASE_E_CALIBRATED_VERSIONS],
            "note": (
                "production pin as declared; a fallback before scoring is an early return "
                "and its seconds are not scenario scoring time"
            ),
        },
        "selector_probe_pin": {
            **diagnostic,
            "pin": [list(pair) for pair in probe_pin],
            "note": (
                "probe-only pin equal to the draw's own provenance, used to reach the "
                "scenarios for repeatability and seed sensitivity; not the production pin "
                "and no calibration claim"
            ),
        },
        "draw_repeat_identical": draw_repeat_identical,
        "selection_repeat_identical": selection_repeat_identical,
        "seed_sensitivity": {
            "seeds": [0, *sensitivity_seeds],
            "selected_rank_by_seed": {
                seed: record["selected_candidate_rank"] for seed, record in by_seed.items()
            },
            "status_by_seed": {seed: record["status"] for seed, record in by_seed.items()},
            "selected_rank_changes": changes,
        },
    }


def probe_decision_point(
    point: DecisionPoint,
    *,
    candidate_counts: Sequence[int],
    sensitivity_seeds: Sequence[int] = SENSITIVITY_SEEDS,
    config: OptimizationConfig | None = None,
    scoring: bool = True,
) -> Record:
    """Probe one pool for every candidate count and return its JSON-ready record."""

    settings = OptimizationConfig() if config is None else config
    warnings: list[str] = []
    runs: list[Record] = []
    pool = point.pool.loc[:, list(POOL_COLUMNS)].copy(deep=True)
    for count in candidate_counts:
        first, generation_seconds = _generate(pool, settings, count)
        second, repeat_seconds = _generate(pool, settings, count)
        control = first.control
        all_optimal = first.complete and all(
            candidate.solver_status is SolverStatus.OPTIMAL for candidate in first.candidates
        )
        run: Record = {
            "candidate_count": count,
            "generation_seconds": generation_seconds,
            "generation_seconds_repeat": repeat_seconds,
            "generation_repeat_identical": _same_decisions(first, second),
            "complete": first.complete,
            "termination_status": first.termination_status.value,
            "all_optimal": all_optimal,
            "candidates_found": len(first.candidates),
            "candidates": [],
            "diversity": None,
            "scoring": None,
            "scoring_unavailable_reason": None,
            "budget_seconds": None,
            "within_budget": None,
        }
        if not control.has_solution:
            # A named failure, kept in the artifact: the rule reads it as unproven and the
            # budget as not evaluable, and nothing later indexes a missing field.
            run["scoring_unavailable_reason"] = (
                f"the control could not be solved ({control.solver_status.value})"
            )
            runs.append(run)
            continue
        run["candidates"] = [
            _candidate_record(rank, candidate, control)
            for rank, candidate in enumerate(first.candidates)
        ]
        run["diversity"] = _diversity(first.candidates, len(pool))
        if point.covered_player_ids is not None:
            covered = _coverage(first.candidates, set(point.covered_player_ids))
            run["coverage_before_draw"] = {
                "candidates_covered": sum(covered),
                "candidates_eliminated": len(covered) - sum(covered),
                "control_covered": covered[0],
            }
        if not scoring:
            run["scoring_unavailable_reason"] = "scoring was not requested for this run"
        elif point.draw_factory is None:
            run["scoring_unavailable_reason"] = point.draw_unavailable_reason
        else:
            run["scoring"] = _probe_scoring(
                point, first, sensitivity_seeds=sensitivity_seeds, warnings=warnings
            )
            run["budget_seconds"] = generation_seconds + float(
                run["scoring"]["scoring_seconds_total"]
            )
            run["within_budget"] = run["budget_seconds"] <= BUDGET_SECONDS
        runs.append(run)
    return {
        "label": point.label,
        "kind": point.kind,
        "pool_size": len(pool),
        "draw_available": point.draw_factory is not None,
        "draw_unavailable_reason": point.draw_unavailable_reason,
        "runs": runs,
        "warnings": warnings,
    }


# --------------------------------------------------------------------------------------
# The preregistered candidate-count rule
# --------------------------------------------------------------------------------------


def _unique_matches(labels: Sequence[str], expected: Sequence[str] | None) -> bool:
    return (
        expected is not None
        and len(set(labels)) == len(labels)
        and sorted(labels) == sorted(expected)
    )


def candidate_count_rule(
    decision_points: Sequence[Record],
    candidate_counts: Sequence[int],
    *,
    expected_live_labels: Sequence[str] = E2_LIVE_LABELS,
    expected_fold_ids: Sequence[str] | None = None,
) -> Record:
    """Apply the frozen rule: the largest K proven, repeatable and within budget on every pool.

    K is frozen only when the E2 pool set is exactly the three 2026-27 live decision points
    and the binding folds, each label once, with exactly one run for every K in {4, 8, 16}
    on every pool, every run evaluable on all three conditions, and K = 4 passing. A failed
    K = 4 disables Phase E whatever a larger K does. Anything less reports what it saw and
    freezes nothing.
    """

    live_labels = [str(point["label"]) for point in decision_points if point["kind"] == "live"]
    fold_labels = [str(point["label"]) for point in decision_points if point["kind"] == "fold"]
    identities_complete = _unique_matches(live_labels, expected_live_labels) and _unique_matches(
        fold_labels, expected_fold_ids
    )
    counts_complete = sorted(set(candidate_counts)) == sorted(PHASE_E_CANDIDATE_COUNTS) and all(
        sorted(run["candidate_count"] for run in point["runs"]) == sorted(PHASE_E_CANDIDATE_COUNTS)
        for point in decision_points
    )

    per_count: dict[str, Record] = {}
    passing: list[int] = []
    for count in sorted(set(candidate_counts)):
        runs = [
            run
            for point in decision_points
            for run in point["runs"]
            if run["candidate_count"] == count
        ]
        optimal = bool(runs) and all(bool(run.get("all_optimal")) for run in runs)
        repeatable = bool(runs) and all(
            bool(run.get("generation_repeat_identical"))
            and (
                not isinstance(run.get("scoring"), dict)
                or (
                    bool(run["scoring"].get("draw_repeat_identical"))
                    and bool(run["scoring"].get("selection_repeat_identical"))
                )
            )
            for run in runs
        )
        budgets = [run.get("within_budget") for run in runs]
        if runs and all(value is not None for value in budgets):
            budget = "within" if all(bool(value) for value in budgets) else "exceeded"
        else:
            budget = "not_evaluable"
        passes: bool | None = (
            None if budget == "not_evaluable" else optimal and repeatable and budget == "within"
        )
        if passes:
            passing.append(count)
        per_count[str(count)] = {
            "pools": len(runs),
            "all_optimal_and_complete": optimal,
            "repeatable": repeatable,
            "budget": budget,
            "passes": passes,
        }

    smallest = min(PHASE_E_CANDIDATE_COUNTS)
    smallest_passes = per_count.get(str(smallest), {}).get("passes")
    evaluable = bool(decision_points) and all(
        entry["passes"] is not None for entry in per_count.values()
    )
    k_on_probed = None if smallest_passes is not True else max(passing)
    if not identities_complete or not counts_complete:
        frozen = None
        reason = (
            f"E2 pool set incomplete: {len(live_labels)} live decision point(s) against "
            f"{list(expected_live_labels)} and {len(fold_labels)} fold(s) against "
            f"{'unknown' if expected_fold_ids is None else len(expected_fold_ids)} expected, "
            f"candidate counts {sorted(set(candidate_counts))} against "
            f"{list(PHASE_E_CANDIDATE_COUNTS)}; nothing is frozen from a partial probe"
        )
    elif not evaluable:
        frozen = None
        reason = (
            "E2 pool set complete but not evaluable on every pool (scoring or budget "
            "unavailable somewhere); nothing is frozen"
        )
    elif smallest_passes is not True:
        frozen = None
        reason = f"K={smallest} failed the rule on the E2 pool set; Phase E is not enabled"
    else:
        frozen = k_on_probed
        reason = "largest K proven, repeatable and within budget on every E2 pool"
    return {
        "candidate_counts": sorted(set(candidate_counts)),
        "required_candidate_counts": list(PHASE_E_CANDIDATE_COUNTS),
        "per_candidate_count": per_count,
        "live_labels": live_labels,
        "expected_live_labels": list(expected_live_labels),
        "fold_labels": fold_labels,
        "expected_fold_count": None if expected_fold_ids is None else len(expected_fold_ids),
        "pool_set_complete": identities_complete and counts_complete,
        "k_passing_on_probed_pools": k_on_probed,
        "frozen_k": frozen,
        "frozen_k_reason": reason,
    }


# --------------------------------------------------------------------------------------
# Real inputs: historical folds and live decision points
# --------------------------------------------------------------------------------------


def _target(fold_id: str) -> ScenarioTarget:
    season, separator, gameweek = fold_id.rpartition("-gw")
    if not separator:
        raise ProbeError(f"Invalid fold id {fold_id!r}.")
    return ScenarioTarget(season=season, gameweek=int(gameweek))


def outcome_free_control_projection(
    panel: pd.DataFrame,
    decision: Any,
    builder: Callable[[pd.DataFrame, Any], PredictionSnapshot | pd.DataFrame],
) -> pd.DataFrame:
    """The walk-forward control projection with the decision gameweek's outcomes blanked.

    ``rows_through`` is the builder's normal view: rows up to and including the decision
    gameweek, which carries that gameweek's pre-match columns. Its realized columns are set to
    missing here before the builder runs, so the projection cannot read them even by accident,
    and no realized reader is called at all.
    """

    visible = rows_through(panel, decision).copy(deep=True)
    current = (visible["season"].astype("string") == str(decision.season)) & (
        visible["gameweek"] == decision.gameweek
    )
    for column in REALIZED_COLUMNS:
        if column in visible.columns:
            visible.loc[current, column] = np.nan
    built = builder(visible, decision)
    table = built.validated_copy().table if isinstance(built, PredictionSnapshot) else built
    if not isinstance(table, pd.DataFrame):
        raise ProbeError(f"{decision.fold_id}: the projection builder returned no table.")
    return table.loc[:, ["player_id", "expected_points"]].copy(deep=True)


def fold_projection_roster(
    rows: pd.DataFrame, roster: pd.DataFrame, fold_id: str, control_projection: pd.DataFrame
) -> pd.DataFrame:
    """The fold's full decision roster: Phase C component points, control points elsewhere.

    This is the projection half of ``prepare_phase_c_component_folds``, without its realized
    half. A direct-control row has no component prediction and takes the control's expected
    points, exactly as the binding run's pool did; no player is removed.
    """

    current = rows.loc[rows["fold_id"].astype("string") == fold_id]
    names = roster.loc[
        roster["fold_id"].astype("string") == fold_id,
        ["player_id", "name", "team_id", "position", "price_tenths"],
    ].copy(deep=True)
    fallback = control_projection.loc[:, ["player_id", "expected_points"]]
    if fallback.empty or bool(fallback["player_id"].duplicated().any()):
        raise ProbeError(f"{fold_id}: the control projection is empty or duplicated.")
    merged = current.loc[:, ["player_id", "control_expected_points"]].merge(
        fallback, on="player_id", how="left", validate="one_to_one"
    )
    if bool(merged["expected_points"].isna().any()) or len(merged) != len(fallback):
        raise ProbeError(f"{fold_id}: the control projection does not cover the handoff roster.")
    points = merged["control_expected_points"].fillna(merged["expected_points"])
    projections = names.copy(deep=True)
    projections["expected_points"] = projections["player_id"].map(
        dict(zip(merged["player_id"], points, strict=True))
    )
    if bool(projections["expected_points"].isna().any()):
        raise ProbeError(f"{fold_id}: unresolved expected points on the decision roster.")
    return projections.loc[:, list(POOL_COLUMNS)].reset_index(drop=True)


def fold_pool_and_inputs(
    rows: pd.DataFrame, projections: pd.DataFrame, fold_id: str
) -> tuple[pd.DataFrame, pd.DataFrame, frozenset[int]]:
    """Return the fold's full pool, its component-row scenario inputs and the covered ids.

    ``rows`` are the Phase C handoff rows of this fold and ``projections`` the fold's decision
    roster with expected points. Only projection and component columns are read; no target or
    realized column is carried anywhere.
    """

    pool = projections.loc[:, list(POOL_COLUMNS)].copy(deep=True)
    current = rows.loc[rows["fold_id"].astype("string") == fold_id]
    component = current.loc[
        current["composition_route"].astype("string") == COMPONENT_MODEL_ROUTE,
        [
            "player_id",
            "fixture_count",
            "appearance_probability",
            "expected_minutes_if_appearance",
            "raw_expected_points_if_appearance",
            "composition_route",
            "evidence_status",
        ],
    ]
    joined = (
        component.merge(pool, on="player_id", how="inner", validate="one_to_one")
        .sort_values("player_id", kind="stable")
        .reset_index(drop=True)
    )
    if len(joined) != len(component):
        raise ProbeError(
            f"{fold_id}: {len(component) - len(joined)} component row(s) have no roster entry."
        )
    return pool, joined, frozenset(int(value) for value in joined["player_id"])


def _fold_point(
    handoff: PhaseCComponentHandoff, fold_id: str, projections: pd.DataFrame
) -> DecisionPoint:
    pool, joined, covered = fold_pool_and_inputs(handoff.rows, projections, fold_id)
    target = _target(fold_id)
    settings = ScenarioConfig()
    history = handoff.rows.loc[handoff.rows["fold_id"].astype("string") < fold_id]
    try:
        residuals = paired_conditional_residuals(
            history, target=target, min_history_folds=settings.min_history_folds
        )
    except ScenarioValidationError as error:
        return DecisionPoint(
            label=fold_id,
            kind="fold",
            pool=pool,
            draw_unavailable_reason=f"no residual pool: {error}",
            covered_player_ids=covered,
        )
    snapshot = prepare_optimizer_projection(
        joined.loc[:, ["player_id", "name", "team_id", "position", "price_tenths"]],
        joined.loc[:, ["player_id", "expected_points"]],
        PredictionProvenance(
            model_name=handoff.model_version,
            model_version=handoff.model_version,
            feature_contract_version=handoff.feature_contract_version,
            training_cutoff=fold_id,
            training_data_fingerprint=handoff.table_sha256,
        ),
    )
    table = joined.loc[:, list(COMPONENT_INPUT_COLUMNS)]

    def factory(seed: int) -> ComponentScenarioDraw:
        inputs = ComponentScenarioInputs(
            table=table,
            provenance=ComponentScenarioProvenance(
                phase_c_table_sha=handoff.table_sha256,
                roster_sha=handoff.roster_sha256,
                model_version=handoff.model_version,
                feature_contract_version=handoff.feature_contract_version,
                target_contract_version=handoff.target_contract_version,
                dataset_contract_version=handoff.dataset_contract_version,
                season=target.season,
                target_gameweek=target.gameweek,
                deterministic_seed=seed,
            ),
        )
        return sample_component_scenarios(
            inputs, snapshot, residuals, target, ScenarioConfig(deterministic_seed=seed)
        )

    return DecisionPoint(
        label=fold_id, kind="fold", pool=pool, draw_factory=factory, covered_player_ids=covered
    )


def binding_fold_ids(handoff: PhaseCComponentHandoff) -> tuple[str, ...]:
    """The preregistered 137-fold population, derived exactly as the binding runner does."""

    ordered = tuple(str(value) for value in handoff.rows["fold_id"].drop_duplicates())
    eligible = tuple(
        fold_id
        for fold_id in ordered[len(HISTORY_BURN_IN_FOLDS) :]
        if fold_id not in DIRECT_CONTROL_ABSTENTIONS
    )
    if len(eligible) != BINDING_FOLD_COUNT:
        raise ProbeError(
            f"the handoff yields {len(eligible)} binding folds, not {BINDING_FOLD_COUNT}."
        )
    return eligible


def fold_decision_points(
    handoff: PhaseCComponentHandoff, fold_ids: Sequence[str], archive_root: Path
) -> tuple[list[DecisionPoint], int]:
    """Build fold pools from outcome-free control projections and the Phase C handoff."""

    panel = build_panel(archive_root, seasons=HISTORY_SEASONS)
    decisions = {
        decision.fold_id: decision
        for decision in walk_forward_decision_points(panel, seasons=DECISION_SEASONS)
    }
    builder = make_ridge_projection_builder(cross_season=CrossSeasonConfig())
    points: list[DecisionPoint] = []
    for fold_id in fold_ids:
        if fold_id not in decisions:
            raise ProbeError(f"fold {fold_id!r} has no walk-forward decision point.")
        control = outcome_free_control_projection(panel, decisions[fold_id], builder)
        projections = fold_projection_roster(handoff.rows, handoff.roster, fold_id, control)
        points.append(_fold_point(handoff, fold_id, projections))
    return points, len(panel)


def live_point_from_capture(snapshot_root: Path, spec: str) -> DecisionPoint:
    """``SEASON:GAMEWEEK:SNAPSHOT_ID:HANDOFF_PATH``: the decide phase's own projection."""

    parts = spec.split(":", 3)
    if len(parts) != 4:
        raise ProbeError(
            f"--live-decision needs SEASON:GAMEWEEK:SNAPSHOT_ID:HANDOFF, got {spec!r}."
        )
    season, gameweek, snapshot_id, handoff_path = parts
    snapshot = read_snapshot(snapshot_root, snapshot_id)
    inputs = read_inputs(snapshot, season=season, gameweek=int(gameweek))
    handoff = read_projection_handoff(Path(handoff_path))
    table = project(inputs, in_season=handoff).table
    return DecisionPoint(
        label=f"{season}-gw{int(gameweek):02d}",
        kind="live",
        pool=table.loc[:, list(POOL_COLUMNS)].copy(deep=True),
        draw_unavailable_reason=LIVE_DRAW_UNAVAILABLE,
    )


def live_point_from_csv(spec: str) -> DecisionPoint:
    """``LABEL=PATH``: a recorded decision pool, such as a ledger's ``projections.csv``."""

    label, separator, path = spec.partition("=")
    if not separator or not label.strip() or not path.strip():
        raise ProbeError(f"--live-pool needs LABEL=PATH, got {spec!r}.")
    frame = pd.read_csv(path)
    missing = [name for name in POOL_COLUMNS if name not in frame.columns]
    if missing:
        raise ProbeError(f"{path}: pool is missing {missing!r}.")
    return DecisionPoint(
        label=label.strip(),
        kind="live",
        pool=frame.loc[:, list(POOL_COLUMNS)].copy(deep=True),
        draw_unavailable_reason=LIVE_DRAW_UNAVAILABLE,
    )


# --------------------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------------------


def _parse_arguments(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--table", type=Path, help="Phase C component OOF table")
    parser.add_argument("--roster", type=Path, help="Phase C decision roster")
    parser.add_argument("--manifest", type=Path, help="Phase C component manifest")
    parser.add_argument("--archive-root", type=Path, default=DEFAULT_ARCHIVE_ROOT)
    parser.add_argument("--fold", action="append", default=[], help="fold id to probe; repeatable")
    parser.add_argument(
        "--all-binding-folds", action="store_true", help="probe the 137-fold population"
    )
    parser.add_argument("--snapshot-root", type=Path, default=DEFAULT_SNAPSHOT_ROOT)
    parser.add_argument(
        "--live-decision",
        action="append",
        default=[],
        help="SEASON:GAMEWEEK:SNAPSHOT_ID:HANDOFF_PATH",
    )
    parser.add_argument("--live-pool", action="append", default=[], help="LABEL=PATH to a pool CSV")
    parser.add_argument(
        "--candidate-counts", type=int, nargs="+", default=list(PHASE_E_CANDIDATE_COUNTS)
    )
    parser.add_argument("--sensitivity-seeds", type=int, nargs="*", default=list(SENSITIVITY_SEEDS))
    parser.add_argument("--skip-scoring", action="store_true", help="generation and coverage only")
    parser.add_argument("--json-output", type=Path, required=True)
    return parser.parse_args(argv)


def _validate(arguments: argparse.Namespace) -> None:
    unsupported = sorted(set(arguments.candidate_counts) - set(PHASE_E_CANDIDATE_COUNTS))
    if unsupported or not arguments.candidate_counts:
        raise ProbeError(
            f"candidate counts must be drawn from {list(PHASE_E_CANDIDATE_COUNTS)}, got "
            f"{arguments.candidate_counts!r}."
        )
    bad_seeds = sorted(set(arguments.sensitivity_seeds) - set(SENSITIVITY_SEEDS))
    if bad_seeds:
        raise ProbeError(f"sensitivity seeds must be drawn from {list(SENSITIVITY_SEEDS)}.")
    wants_folds = bool(arguments.fold) or arguments.all_binding_folds
    handoff_given = all(
        value is not None for value in (arguments.table, arguments.roster, arguments.manifest)
    )
    if wants_folds and not handoff_given:
        raise ProbeError("--fold and --all-binding-folds need --table, --roster and --manifest.")
    if not (wants_folds or arguments.live_decision or arguments.live_pool):
        raise ProbeError(
            "nothing to probe: give --fold, --all-binding-folds, --live-decision or --live-pool."
        )


def _summary_line(point: Record) -> str:
    parts = [f"{point['label']} ({point['kind']}, pool {point['pool_size']})"]
    for run in point["runs"]:
        scoring = run.get("scoring")
        scored = (
            "scoring n/a"
            if not isinstance(scoring, dict)
            else (
                f"scoring {float(scoring['scoring_seconds_total']):.1f}s, "
                f"production {scoring['selector_production']['status']}, "
                f"probe-pin {scoring['selector_probe_pin']['status']} "
                f"rank {scoring['selector_probe_pin']['selected_candidate_rank']}, "
                f"seed changes {scoring['seed_sensitivity']['selected_rank_changes']}"
            )
        )
        diversity = run.get("diversity") or {}
        parts.append(
            f"  K={run['candidate_count']}: {run['candidates_found']} found, "
            f"{run['termination_status']}, gen {float(run['generation_seconds']):.1f}s, "
            f"distinct {diversity.get('distinct_signatures')}, "
            f"bench-only {diversity.get('bench_only_candidates')}, {scored}"
        )
    return "\n".join(parts)


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parse_arguments(argv)
    try:
        _validate(arguments)
        points: list[DecisionPoint] = []
        panel_rows = 0
        expected_fold_ids: tuple[str, ...] | None = None
        for spec in arguments.live_pool:
            points.append(live_point_from_csv(spec))
        for spec in arguments.live_decision:
            points.append(live_point_from_capture(arguments.snapshot_root, spec))
        if arguments.fold or arguments.all_binding_folds:
            handoff = read_phase_c_component_handoff(
                arguments.table, arguments.roster, arguments.manifest
            )
            expected_fold_ids = binding_fold_ids(handoff)
            fold_ids = (
                list(expected_fold_ids) if arguments.all_binding_folds else list(arguments.fold)
            )
            fold_points, panel_rows = fold_decision_points(
                handoff, fold_ids, arguments.archive_root
            )
            points.extend(fold_points)

        records: list[Record] = []
        for point in points:
            record = probe_decision_point(
                point,
                candidate_counts=arguments.candidate_counts,
                sensitivity_seeds=arguments.sensitivity_seeds,
                scoring=not arguments.skip_scoring,
            )
            print(_summary_line(record))
            records.append(record)
        rule = candidate_count_rule(
            records, arguments.candidate_counts, expected_fold_ids=expected_fold_ids
        )
        document: Record = {
            "contract_version": PROBE_CONTRACT_VERSION,
            "preregistration": PREREGISTRATION,
            "generated_at_utc": datetime.now(UTC).isoformat(timespec="seconds"),
            "diagnostic_only": True,
            "promotes_anything": False,
            "reads_realized_outcomes": False,
            "outcome_policy": OUTCOME_POLICY,
            "constants": {
                "candidate_counts": sorted(set(arguments.candidate_counts)),
                "sensitivity_seeds": list(arguments.sensitivity_seeds),
                "budget_seconds": BUDGET_SECONDS,
                "scenario_count": PHASE_E_SCENARIO_COUNT,
                "risk_weight": PHASE_E_RISK_WEIGHT / PHASE_E_WEIGHT_SCALE,
                "tail_fraction": PHASE_E_TAIL_COUNT / PHASE_E_SCENARIO_COUNT,
            },
            "production_pin": [list(pair) for pair in PHASE_E_CALIBRATED_VERSIONS],
            "production_pin_empty": not PHASE_E_CALIBRATED_VERSIONS,
            "scoring_requested": not arguments.skip_scoring,
            "decision_points": records,
            "candidate_count_rule": rule,
            "frozen_k": rule["frozen_k"],
            "frozen_k_reason": rule["frozen_k_reason"],
            "warnings": [warning for record in records for warning in record["warnings"]],
            **artifact_metadata(panel_rows=panel_rows, history_seasons=HISTORY_SEASONS),
        }
        write_json(arguments.json_output, document)
    except (ProbeError, DataError, ScenarioValidationError, ValueError, OSError) as error:
        print(f"probe refused: {error}", file=sys.stderr)
        return 1
    print(f"frozen_k: {rule['frozen_k']} ({rule['frozen_k_reason']})")
    print(f"wrote {arguments.json_output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
