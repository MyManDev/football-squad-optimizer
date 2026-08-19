"""Choose a window plan under a play mode, by scoring candidate plans on joint paths.

The planner (`optimize_transfer_plan`) already produces multi-week plans with transfers,
hits and chips — against a *deterministic* projection, maximising expected points. The play
modes need something else: given several candidate plans, which one best serves the chosen
target — Saf Puan (most expected points, rival-independent), Garantici (do not fall behind
the rival), Agresif (finish strictly ahead), Asiri Agresif (finish clearly ahead)?

Solving the planner *inside* the scenarios would multiply an already large CP-SAT model by
the scenario count. This module deliberately does not. It generates a small menu of
candidate plans deterministically — the planner's own preferred plan, the chip-less plan,
and one plan per forced chip placement in the window — and then scores every candidate on
the same joint scenario paths, where a plan's week-by-week elevens, captaincy, bench boost
and triple captain are all priced per scenario. The mode then picks from the menu.

Chips and the rest of the season: a chip played inside the window cannot be played after
it. The planner's chip holding values price that option cost inside candidate generation,
and every result records, per candidate, which chips it consumed — so a recommendation
"play bench boost in week two" is always read next to what playing it forecloses.

The rival is held fixed across the window (the template does not trade); stated as a limit
rather than hidden. Measurement machinery only: nothing here touches the live path.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final

import numpy as np
import pandas as pd

from squadopt.experiments.config import ExperimentConfigurationError, ExperimentExecutionError
from squadopt.optimization import OptimizationConfig
from squadopt.planning import (
    ChipAvailability,
    InitialSquadState,
    PlanningHorizon,
    TransferPlanningConfig,
    TransferPlanResult,
    optimize_transfer_plan,
)
from squadopt.scenarios.evaluation import RivalSquad
from squadopt.scenarios.paths import ScenarioPathSet

PLAN_SELECTION_CONTRACT_VERSION: Final = "mode_plan_selection_v1"

#: The play modes. ``margin`` is the amount a scenario must be won by; ``level_counts``
#: says whether finishing level is a success. Saf Puan carries no margin because it is
#: rival-independent: it ranks candidates purely by expected window score.
MODES: Final[Mapping[str, Mapping[str, object]]] = {
    "saf_puan": {"rival_aware": False},
    "garantici": {"rival_aware": True, "margin": 0.0, "level_counts": True},
    "agresif": {"rival_aware": True, "margin": 0.0, "level_counts": False},
    "asiri_agresif": {"rival_aware": True, "margin": 5.0, "level_counts": False},
}


@dataclass(frozen=True, slots=True)
class CandidatePlan:
    """One deterministic plan on the menu, and where it came from."""

    label: str
    plan: TransferPlanResult

    @property
    def chips_played(self) -> Mapping[int, str]:
        return self.plan.chips_played


@dataclass(frozen=True, slots=True)
class ModeVerdict:
    """One mode's reading of one candidate on the paths."""

    mode: str
    candidate: str
    expected_window_score: float
    probability_success: float | None
    """P(the mode's target) over scenarios; None for the rival-independent mode."""
    probability_behind: float | None
    expected_rival_gap: float | None
    chips_consumed: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PlanSelection:
    contract_version: str
    candidates: tuple[CandidatePlan, ...]
    verdicts: tuple[ModeVerdict, ...]
    recommended: Mapping[str, str]
    """Per mode, the label of the winning candidate."""
    diagnostics: Mapping[str, object]


def generate_candidate_plans(
    horizon: PlanningHorizon,
    initial_state: InitialSquadState,
    optimization_config: OptimizationConfig,
    *,
    transfer_config: TransferPlanningConfig | None = None,
    chip_names: Sequence[str] = ("bboost", "3xc"),
    gameweeks: Sequence[int] | None = None,
) -> tuple[CandidatePlan, ...]:
    """A deterministic menu: the planner's preference, no chips, and each forced placement.

    Every candidate is one planner solve, so the menu costs ``2 + chips x weeks`` solves.
    Infeasible placements are dropped rather than failing the menu: a chip that cannot be
    forced into a week is not a candidate, and the diagnostics of the selection record how
    many placements survived.
    """

    weeks = tuple(
        int(value) for value in (gameweeks or sorted(set(horizon.table["gameweek"].tolist())))
    )
    if not weeks:
        raise ExperimentConfigurationError("The horizon carries no gameweeks.")
    unknown = [name for name in chip_names if name not in ("bboost", "3xc", "wildcard", "freehit")]
    if unknown:
        raise ExperimentConfigurationError(f"Unknown chips {unknown!r}.")
    menu: list[CandidatePlan] = []

    def _solve(label: str, chips: ChipAvailability | None) -> None:
        result = optimize_transfer_plan(
            horizon, initial_state, optimization_config, transfer_config, chips
        )
        if result.has_solution:
            menu.append(CandidatePlan(label=label, plan=result))

    _solve("no_chips", None)
    if chip_names:
        _solve(
            "planner_choice",
            ChipAvailability(available={name: frozenset(weeks) for name in chip_names}),
        )
        for name in chip_names:
            for week in weeks:
                _solve(
                    f"{name}_gw{week:02d}",
                    ChipAvailability(available={name: frozenset({week})}, forced={week: name}),
                )
    if not menu:
        raise ExperimentExecutionError("No candidate plan was feasible.")
    return tuple(menu)


def _week_scores(
    week_matrix: pd.DataFrame,
    starters: Sequence[object],
    captain: object,
    *,
    bench: Sequence[object] = (),
    triple_captain: bool = False,
) -> np.ndarray:
    """One week's per-scenario score for one plan week, chips applied.

    The captain scores double (triple under the chip); a bench boost adds the bench. This
    is the same arithmetic the realized scorer uses, applied per scenario column.
    """

    matrix = week_matrix.loc[:, list(starters)].to_numpy(dtype="float64").sum(axis=1)
    captain_points = week_matrix[captain].to_numpy(dtype="float64")
    matrix = matrix + captain_points * (2.0 if triple_captain else 1.0)
    if bench:
        matrix = matrix + week_matrix.loc[:, list(bench)].to_numpy(dtype="float64").sum(axis=1)
    return np.asarray(matrix, dtype="float64")


def score_candidate_on_paths(candidate: CandidatePlan, paths: ScenarioPathSet) -> np.ndarray:
    """A candidate's window score per scenario: each week's eleven on that week of the path."""

    weeks = {week.gameweek: week for week in candidate.plan.weeks}
    missing = [gameweek for gameweek in paths.target.gameweeks if gameweek not in weeks]
    if missing:
        raise ExperimentExecutionError(f"The plan carries no week for gameweeks {missing!r}.")
    total: np.ndarray | None = None
    for gameweek in paths.target.gameweeks:
        week = weeks[gameweek]
        chip = candidate.chips_played.get(gameweek)
        scores = _week_scores(
            paths.week(gameweek),
            week.starting_xi["player_id"].tolist(),
            week.captain["player_id"],
            bench=(week.bench["player_id"].tolist() if chip == "bboost" else ()),
            triple_captain=chip == "3xc",
        )
        scores = scores - float(week.transfer_hit_points)
        total = scores if total is None else total + scores
    assert total is not None
    return total


def rival_window_scores(rival: RivalSquad, paths: ScenarioPathSet) -> np.ndarray:
    """The fixed rival's window score per scenario, captain doubled, no chips."""

    total: np.ndarray | None = None
    for gameweek in paths.target.gameweeks:
        scores = _week_scores(paths.week(gameweek), list(rival.starter_ids), rival.captain_id)
        total = scores if total is None else total + scores
    assert total is not None
    return total


def select_plan(
    candidates: Sequence[CandidatePlan],
    paths: ScenarioPathSet,
    rival: RivalSquad | None,
    *,
    modes: Mapping[str, Mapping[str, object]] = MODES,
) -> PlanSelection:
    """Score every candidate under every mode and name each mode's winner.

    The rival-aware modes need ``rival``; without one they are skipped rather than faked.
    Ties break toward the candidate that consumes fewer chips, then by label, so a chip is
    never recommended when not playing it does as well.
    """

    if not candidates:
        raise ExperimentConfigurationError("At least one candidate plan is required.")
    candidate_scores = {
        candidate.label: score_candidate_on_paths(candidate, paths) for candidate in candidates
    }
    rival_scores = rival_window_scores(rival, paths) if rival is not None else None
    verdicts: list[ModeVerdict] = []
    recommended: dict[str, str] = {}
    for mode_name, mode in modes.items():
        rival_aware = bool(mode.get("rival_aware"))
        if rival_aware and rival_scores is None:
            continue
        mode_rows: list[ModeVerdict] = []
        for candidate in candidates:
            scores = candidate_scores[candidate.label]
            chips = tuple(sorted(set(candidate.chips_played.values())))
            if rival_aware and rival_scores is not None:
                margin = float(str(mode.get("margin", 0.0)))
                level_counts = bool(mode.get("level_counts"))
                gap = scores - rival_scores
                # Level counting ignores the margin by construction: "do not fall behind"
                # has exactly one reading, and a margin would silently change it.
                success = (
                    float(np.mean(gap >= 0.0)) if level_counts else float(np.mean(gap > margin))
                )
                mode_rows.append(
                    ModeVerdict(
                        mode=mode_name,
                        candidate=candidate.label,
                        expected_window_score=float(scores.mean()),
                        probability_success=success,
                        probability_behind=float(np.mean(gap < 0.0)),
                        expected_rival_gap=float(gap.mean()),
                        chips_consumed=chips,
                    )
                )
            else:
                mode_rows.append(
                    ModeVerdict(
                        mode=mode_name,
                        candidate=candidate.label,
                        expected_window_score=float(scores.mean()),
                        probability_success=None,
                        probability_behind=None,
                        expected_rival_gap=None,
                        chips_consumed=chips,
                    )
                )

        def _key(verdict: ModeVerdict) -> tuple[float, int, str]:
            primary = (
                verdict.expected_window_score
                if verdict.probability_success is None
                else verdict.probability_success
            )
            return (-primary, len(verdict.chips_consumed), verdict.candidate)

        winner = min(mode_rows, key=_key)
        recommended[mode_name] = winner.candidate
        verdicts.extend(mode_rows)
    return PlanSelection(
        contract_version=PLAN_SELECTION_CONTRACT_VERSION,
        candidates=tuple(candidates),
        verdicts=tuple(verdicts),
        recommended=recommended,
        diagnostics={
            "window_id": paths.target.window_id,
            "horizon": paths.target.horizon,
            "scenario_count": paths.config.scenario_count,
            "candidates": [candidate.label for candidate in candidates],
            "rival_label": rival.label if rival is not None else None,
            "rival_held_fixed": True,
            "chips_note": (
                "A chip consumed inside the window is unavailable after it; candidates "
                "record their consumption so the recommendation is read next to its cost."
            ),
        },
    )


def selection_to_dict(selection: PlanSelection) -> dict[str, object]:
    """JSON-native form of a selection, for artifacts."""

    return {
        "contract_version": selection.contract_version,
        "recommended": dict(selection.recommended),
        "verdicts": [
            {
                "mode": verdict.mode,
                "candidate": verdict.candidate,
                "expected_window_score": verdict.expected_window_score,
                "probability_success": verdict.probability_success,
                "probability_behind": verdict.probability_behind,
                "expected_rival_gap": verdict.expected_rival_gap,
                "chips_consumed": list(verdict.chips_consumed),
            }
            for verdict in selection.verdicts
        ],
        "candidates": [
            {
                "label": candidate.label,
                "chips_played": {str(k): v for k, v in candidate.chips_played.items()},
                "total_projected_score": candidate.plan.total_projected_score,
                "total_transfer_hit_points": candidate.plan.total_transfer_hit_points,
                "solver_status": candidate.plan.solver_status.name,
            }
            for candidate in selection.candidates
        ],
        "diagnostics": dict(selection.diagnostics),
    }


__all__ = [
    "MODES",
    "PLAN_SELECTION_CONTRACT_VERSION",
    "CandidatePlan",
    "ModeVerdict",
    "PlanSelection",
    "generate_candidate_plans",
    "rival_window_scores",
    "score_candidate_on_paths",
    "select_plan",
    "selection_to_dict",
]
