"""Measure the rank-conditional shrinkage of expected points before the squad decision.

    python -m scripts.measure_rank_conditional_shrinkage \\
        --table artifacts/phase_c_v2/<gbm table>.csv \\
        --roster artifacts/phase_c_v2/<gbm table>.roster.csv \\
        --manifest artifacts/phase_c_v2/<gbm table>.manifest.json

Runs the protocol of ``docs/research/rank_conditional_shrinkage_prereg.md`` once on the Phase C
v2 gradient-boosting out-of-fold table and writes its record under ``docs/research/``, with
the Markdown twin beside it and the per-fold table under ``artifacts/``. The fold loop is the
one ``run_component_squad_calibration.py`` runs under ``development_v2``: the handoff read
through the development reader, the ridge controls built for the direct-control fallback,
``prepare_phase_c_component_folds`` composing one decision frame per fold, and
``evaluate_prepared_folds`` under the measurement solver limits and the official scorer.
The three arms differ in the ``expected_points`` column alone.

``--folds`` runs a pilot on named folds and writes nowhere under ``docs/``. The committed
record is written from a clean tree only and never overwritten. Measurement only: nothing
here promotes anything or changes a product default.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from collections.abc import Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from statistics import fmean, median
from typing import Final

import pandas as pd
from scripts._experiment_cli import (
    DEFAULT_ARCHIVE_ROOT,
    REPOSITORY_ROOT,
    _git_revision,
    artifact_metadata,
    measurement_optimization_config,
    solver_record,
    write_text,
)

from squadopt.backtest import build_walk_forward_folds, make_ridge_projection_builder
from squadopt.data.sources.vaastav import build_panel
from squadopt.evaluation import (
    DEVELOPMENT_OOF_CONTRACT_VERSION,
    EvaluationConfig,
    EvaluationFold,
    EvaluationResult,
    ScoringPolicy,
    complete_optimization_decision,
    evaluate_prepared_folds,
    prepare_phase_c_component_folds,
    read_phase_c_component_handoff,
)
from squadopt.evaluation.component_handoff import PhaseCComponentHandoff
from squadopt.evaluation.promotion import PromotionPolicy
from squadopt.evaluation.scoring import score_frozen_squad_decision
from squadopt.evaluation.statistics import season_aware_moving_block_interval
from squadopt.experiments.rank_conditional_shrinkage import (
    CONTRACT_VERSION,
    MIN_HISTORY_FOLDS,
    POSITIONS,
    RANK_BUCKET_EDGES,
    RANK_BUCKET_LABELS,
    PositionShrinkageTable,
    RankDebiasTable,
    RankShrinkageError,
    apply_position_shrinkage,
    apply_rank_debias,
    fit_position_shrinkage,
    fit_rank_debias,
    history_rows,
    realized_points,
    target_folds,
)
from squadopt.experiments.shadow_report import write_document_once
from squadopt.features import CrossSeasonConfig

RECORD_VERSION: Final = "rank_conditional_shrinkage_measurement_v1"
PROTOCOL: Final = "docs/research/rank_conditional_shrinkage_prereg.md"
DEFAULT_JSON_OUTPUT: Final = (
    REPOSITORY_ROOT / "docs" / "research" / "rank_conditional_shrinkage.json"
)
DEFAULT_ARTIFACT_DIR: Final = REPOSITORY_ROOT / "artifacts" / "rank_conditional_shrinkage"
DOCS_ROOT: Final = REPOSITORY_ROOT / "docs"

#: The GBM table and roster digests the protocol names, from
#: ``docs/research/phase_c_gradient_boosting_comparison.json``; the manifest digest differs
#: between exports because it carries a wall clock, so the record pins the one it read.
EXPECTED_TABLE_SHA256: Final = "eae3e91485098edf01275b24310d2e7449d2d96b53a67cba5173d227b5c80feb"
EXPECTED_ROSTER_SHA256: Final = "01d1111382206a5b2943099aaac2f70063073491b1987ed9a58e3950d8d54044"
EXPECTED_MODEL_VERSION: Final = "phase_c_control_components_gbm_v1"

HISTORY_SEASON: Final = "2020-21"
DEVELOPMENT_SEASONS_V2: Final = ("2021-22", "2022-23", "2023-24", "2024-25", "2025-26")
NOISE_FLOOR_POINTS: Final = 1.5
MAX_NEGATIVE_SEASONS: Final = 1
BOOTSTRAP_POLICY: Final = PromotionPolicy(
    bootstrap_resamples=2_000, moving_block_length=4, deterministic_seed=0
)
PRIMARY_CANDIDATE_ID: Final = CONTRACT_VERSION
SECONDARY_CANDIDATE_ID: Final = f"{CONTRACT_VERSION}_position"

CONTROL: Final = "control"
ARM_A: Final = "rank_debias"
ARM_B: Final = "position_shrinkage"
ARMS: Final = (CONTROL, ARM_A, ARM_B)
ARM_RULES: Final = {
    CONTROL: "the unshrunk projection",
    ARM_A: (
        "max(0, projected + r_b), r_b the mean residual of rank bucket b over the history "
        "folds; buckets 1-5, 6-15, 16-30, 31-60, 61-120, 121 and beyond"
    ),
    ARM_B: (
        "max(0, m_pos + lambda_pos * (projected - m_pos)), lambda_pos the least-squares slope "
        "of realized on projected per position over the history folds, m_pos the target "
        "fold's mean projected points in the position"
    ),
}
NOT_MEASURED: Final = (
    "transfer decisions and multi-week plans",
    "the historical ridge control as an arm",
    "any member's squad",
    "Top100 evidence",
    "2025-26 as a test",
)


def _parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--table", type=Path, required=True)
    parser.add_argument("--roster", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--archive-root", type=Path, default=DEFAULT_ARCHIVE_ROOT)
    parser.add_argument("--json-output", type=Path, default=DEFAULT_JSON_OUTPUT)
    parser.add_argument("--markdown-output", type=Path, default=None)
    parser.add_argument("--artifact-dir", type=Path, default=DEFAULT_ARTIFACT_DIR)
    parser.add_argument(
        "--folds",
        default=None,
        help="Comma-separated fold ids for a pilot; writes nowhere under docs/.",
    )
    return parser.parse_args()


# --- population and frames ----------------------------------------------------


def _population(
    fold_ids: Sequence[str], *, requested: Sequence[str] | None
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """The burn-in and the target folds, refusing a table too short to have a target."""

    burn_in, targets = target_folds(fold_ids)
    if not targets:
        raise RankShrinkageError(
            f"No fold has {MIN_HISTORY_FOLDS} folds of history; the table holds {len(burn_in)}."
        )
    if requested is None:
        return burn_in, targets
    wanted = tuple(dict.fromkeys(str(fold_id) for fold_id in requested))
    unknown = sorted(set(wanted) - set(fold_ids))
    if unknown:
        raise RankShrinkageError(f"--folds names folds outside the table: {unknown!r}.")
    in_burn_in = sorted(set(wanted) & set(burn_in))
    if in_burn_in:
        raise RankShrinkageError(f"--folds names burn-in folds: {in_burn_in!r}.")
    return burn_in, tuple(fold_id for fold_id in targets if fold_id in set(wanted))


def _residual_frame(fold_id: str, projections: pd.DataFrame, rows: pd.DataFrame) -> pd.DataFrame:
    """One fold's residual rows from the harness projection and the handoff outcomes."""

    outcomes = rows.loc[
        rows["fold_id"].astype("string").eq(fold_id),
        ["player_id", "appearance_target", "points_target"],
    ]
    merged = projections.loc[:, ["player_id", "position", "expected_points"]].merge(
        outcomes, on="player_id", how="left", validate="one_to_one"
    )
    if len(merged) != len(outcomes) or bool(merged["appearance_target"].isna().any()):
        raise RankShrinkageError(f"{fold_id}: projections and handoff rows do not align.")
    return pd.DataFrame(
        {
            "fold_id": fold_id,
            "player_id": merged["player_id"].astype("int64"),
            "position": merged["position"].astype("string"),
            "projected": pd.to_numeric(merged["expected_points"], errors="raise").astype("float64"),
            "realized": realized_points(merged["appearance_target"], merged["points_target"]),
        }
    )


def _with_projection(
    fold: EvaluationFold, player_ids: pd.Series, projected: pd.Series
) -> EvaluationFold:
    """The same fold with another ``expected_points`` column and nothing else changed."""

    projections = fold.projections.copy(deep=True)
    by_player = dict(
        zip(player_ids.to_numpy(dtype="int64"), projected.to_numpy(dtype="float64"), strict=True)
    )
    projections["expected_points"] = projections["player_id"].map(by_player).astype("float64")
    if bool(projections["expected_points"].isna().any()):
        raise RankShrinkageError(f"{fold.fold_id}: a player lost its candidate projection.")
    return EvaluationFold(
        fold_id=fold.fold_id,
        projections=projections,
        realized_points=fold.realized_points,
        metadata=fold.metadata,
    )


@dataclass(frozen=True, slots=True)
class PreparedArms:
    """The three arms' folds over the same targets, with the fitted tables per target."""

    folds: Mapping[str, tuple[EvaluationFold, ...]]
    debias_tables: Mapping[str, RankDebiasTable]
    shrinkage_tables: Mapping[str, PositionShrinkageTable]
    residuals: pd.DataFrame


def prepare_arms(
    handoff: PhaseCComponentHandoff,
    prepared: Sequence[EvaluationFold],
    targets: Sequence[str],
) -> PreparedArms:
    """Fit each target's tables on its history and compose the three arms' folds."""

    by_id = {fold.fold_id: fold for fold in prepared}
    residuals = pd.concat(
        [_residual_frame(fold.fold_id, fold.projections, handoff.rows) for fold in prepared],
        ignore_index=True,
    )
    control: list[EvaluationFold] = []
    debiased: list[EvaluationFold] = []
    shrunk: list[EvaluationFold] = []
    debias_tables: dict[str, RankDebiasTable] = {}
    shrinkage_tables: dict[str, PositionShrinkageTable] = {}
    for target in targets:
        fold = by_id[target]
        history = history_rows(residuals, target)
        current = residuals.loc[residuals["fold_id"] == target]
        players = current["player_id"]
        debias = fit_rank_debias(history)
        shrinkage = fit_position_shrinkage(history)
        debias_tables[target] = debias
        shrinkage_tables[target] = shrinkage
        control.append(fold)
        debiased.append(_with_projection(fold, players, apply_rank_debias(current, debias)))
        shrunk.append(_with_projection(fold, players, apply_position_shrinkage(current, shrinkage)))
    return PreparedArms(
        folds={CONTROL: tuple(control), ARM_A: tuple(debiased), ARM_B: tuple(shrunk)},
        debias_tables=debias_tables,
        shrinkage_tables=shrinkage_tables,
        residuals=residuals,
    )


# --- scoring and statistics ---------------------------------------------------


@dataclass(frozen=True, slots=True)
class FoldReading:
    """One arm's completed decision on one fold, with the diagnostics the protocol names."""

    fold_id: str
    season: str
    score: float
    squad: tuple[int, ...]
    starters: tuple[int, ...]
    captain: int
    own_projected_starters: float
    own_projected_captain: float
    unshrunk_projected_starters: float
    unshrunk_projected_captain: float
    realized_starters: float
    realized_captain: float
    zero_minute_starters: int
    autosub_points: float
    vice_recovered: bool
    solver_status: str


def _column_map(frame: pd.DataFrame, column: str) -> dict[int, float]:
    return {
        int(player): float(value)
        for player, value in zip(frame["player_id"], frame[column], strict=True)
    }


def _readings(
    arm: str,
    result: EvaluationResult,
    arms: PreparedArms,
    control_by_id: Mapping[str, EvaluationFold],
) -> dict[str, FoldReading]:
    folds = {fold.fold_id: fold for fold in arms.folds[arm]}
    readings: dict[str, FoldReading] = {}
    for item in result.folds:
        if not item.optimization_result.has_solution or item.realized_squad_points is None:
            continue
        fold = folds[item.fold_id]
        decision = complete_optimization_decision(item.optimization_result)
        scored = score_frozen_squad_decision(decision, fold.realized_points)
        starters = tuple(int(value) for value in decision.starting_xi)
        captain = int(str(decision.captain_id))
        own = _column_map(fold.projections, "expected_points")
        unshrunk = _column_map(control_by_id[item.fold_id].projections, "expected_points")
        realized = _column_map(fold.realized_points, "total_points")
        minutes = _column_map(fold.realized_points, "minutes")
        readings[item.fold_id] = FoldReading(
            fold_id=item.fold_id,
            season=item.fold_id[:7],
            score=float(item.realized_squad_points),
            squad=tuple(int(value) for value in decision.squad["player_id"]),
            starters=starters,
            captain=captain,
            own_projected_starters=fmean(own[player] for player in starters),
            own_projected_captain=own[captain],
            unshrunk_projected_starters=fmean(unshrunk[player] for player in starters),
            unshrunk_projected_captain=unshrunk[captain],
            realized_starters=fmean(realized[player] for player in starters),
            realized_captain=realized[captain],
            zero_minute_starters=sum(minutes[player] == 0 for player in starters),
            autosub_points=float(scored.autosub_points),
            vice_recovered=bool(
                scored.captain_bonus_player_id == decision.vice_captain_id
                and decision.vice_captain_id != decision.captain_id
            ),
            solver_status=item.optimization_result.solver_status.value,
        )
    return readings


def _paired(
    candidate: Mapping[str, FoldReading],
    control: Mapping[str, FoldReading],
    paired_ids: Sequence[str],
    *,
    candidate_id: str,
) -> dict[str, object]:
    differences = [
        (control[fold_id].season, candidate[fold_id].score - control[fold_id].score)
        for fold_id in paired_ids
    ]
    values = [value for _, value in differences]
    seasons: dict[str, list[float]] = {}
    for season, value in differences:
        seasons.setdefault(season, []).append(value)
    lower, upper = season_aware_moving_block_interval(
        differences, policy=BOOTSTRAP_POLICY, candidate_id=candidate_id
    )
    return {
        "paired_folds": len(values),
        "mean_difference": fmean(values),
        "median_difference": median(values),
        "wins": sum(value > 0 for value in values),
        "ties": sum(value == 0 for value in values),
        "losses": sum(value < 0 for value in values),
        "season_mean_differences": {
            season: fmean(items) for season, items in sorted(seasons.items())
        },
        "season_paired_folds": {season: len(items) for season, items in sorted(seasons.items())},
        "interval_90": [lower, upper],
        "interval": {
            "method": "squadopt.evaluation.statistics.season_aware_moving_block_interval",
            "confidence_level": BOOTSTRAP_POLICY.confidence_level,
            "moving_block_length": BOOTSTRAP_POLICY.moving_block_length,
            "bootstrap_resamples": BOOTSTRAP_POLICY.bootstrap_resamples,
            "deterministic_seed": BOOTSTRAP_POLICY.deterministic_seed,
            "candidate_id": candidate_id,
        },
        "candidate_mean_score": fmean(candidate[fold_id].score for fold_id in paired_ids),
        "control_mean_score": fmean(control[fold_id].score for fold_id in paired_ids),
    }


def _gate(primary: Mapping[str, object]) -> dict[str, object]:
    mean = float(str(primary["mean_difference"]))
    interval = primary["interval_90"]
    assert isinstance(interval, Sequence)
    lower = float(str(interval[0]))
    seasons = primary["season_mean_differences"]
    assert isinstance(seasons, Mapping)
    negative = sum(1 for value in seasons.values() if float(str(value)) < 0)
    passes_floor = mean >= NOISE_FLOOR_POINTS
    passes_interval = lower > 0.0
    passes_seasons = negative <= MAX_NEGATIVE_SEASONS
    certified = passes_floor and passes_interval and passes_seasons
    return {
        "noise_floor_points_per_gameweek": NOISE_FLOOR_POINTS,
        "max_negative_seasons": MAX_NEGATIVE_SEASONS,
        "mean_gain_at_or_above_floor": passes_floor,
        "interval_excludes_zero": passes_interval,
        "negative_seasons": negative,
        "negative_seasons_within_limit": passes_seasons,
        "certified": certified,
        "verdict": "certified" if certified else "measured, not certified",
    }


def _selection_gap(
    readings: Mapping[str, FoldReading], paired_ids: Sequence[str]
) -> dict[str, float]:
    rows = [readings[fold_id] for fold_id in paired_ids]
    return {
        "own_projected_minus_realized_starters": fmean(
            row.own_projected_starters - row.realized_starters for row in rows
        ),
        "own_projected_minus_realized_captain": fmean(
            row.own_projected_captain - row.realized_captain for row in rows
        ),
        "unshrunk_projected_minus_realized_starters": fmean(
            row.unshrunk_projected_starters - row.realized_starters for row in rows
        ),
        "unshrunk_projected_minus_realized_captain": fmean(
            row.unshrunk_projected_captain - row.realized_captain for row in rows
        ),
        "mean_realized_starter_points": fmean(row.realized_starters for row in rows),
    }


def _overlap(
    candidate: Mapping[str, FoldReading],
    control: Mapping[str, FoldReading],
    paired_ids: Sequence[str],
) -> dict[str, float]:
    return {
        "mean_shared_of_fifteen": fmean(
            len(set(candidate[fold_id].squad) & set(control[fold_id].squad))
            for fold_id in paired_ids
        ),
        "mean_shared_of_eleven": fmean(
            len(set(candidate[fold_id].starters) & set(control[fold_id].starters))
            for fold_id in paired_ids
        ),
        "same_captain_rate": fmean(
            float(candidate[fold_id].captain == control[fold_id].captain) for fold_id in paired_ids
        ),
    }


def _blanks(readings: Mapping[str, FoldReading], paired_ids: Sequence[str]) -> dict[str, object]:
    rows = [readings[fold_id] for fold_id in paired_ids]
    statuses = sorted({row.solver_status for row in rows})
    return {
        "zero_minute_starters": sum(row.zero_minute_starters for row in rows),
        "autosub_points": sum(row.autosub_points for row in rows),
        "vice_captain_recoveries": sum(row.vice_recovered for row in rows),
        "solver_status_counts": {
            status: sum(row.solver_status == status for row in rows) for status in statuses
        },
    }


def _correction_summary(arms: PreparedArms, targets: Sequence[str]) -> dict[str, object]:
    first = arms.debias_tables[targets[0]]
    last = arms.debias_tables[targets[-1]]
    last_shrinkage = arms.shrinkage_tables[targets[-1]]
    return {
        "bucket_edges": list(RANK_BUCKET_EDGES),
        "mean_over_target_folds": {
            label: fmean(arms.debias_tables[target].corrections[label] for target in targets)
            for label in RANK_BUCKET_LABELS
        },
        "first_target_fold": {"fold_id": targets[0], **dict(first.corrections)},
        "last_target_fold": {"fold_id": targets[-1], **dict(last.corrections)},
        "history_rows_per_bucket_at_last_target": dict(last.rows_per_bucket),
        "position_slope_mean_over_target_folds": {
            position: fmean(arms.shrinkage_tables[target].slopes[position] for target in targets)
            for position in POSITIONS
        },
        "position_slope_at_last_target": dict(last_shrinkage.slopes),
        "position_intercept_at_last_target": dict(last_shrinkage.intercepts),
    }


def _fold_table(
    readings: Mapping[str, Mapping[str, FoldReading]],
    arms: PreparedArms,
    targets: Sequence[str],
    paired_ids: Sequence[str],
) -> pd.DataFrame:
    paired = set(paired_ids)
    rows: list[dict[str, object]] = []
    for target in targets:
        row: dict[str, object] = {
            "fold_id": target,
            "season": target[:7],
            "paired": target in paired,
        }
        for arm in ARMS:
            reading = readings[arm].get(target)
            row[f"{arm}_score"] = None if reading is None else reading.score
            row[f"{arm}_captain"] = None if reading is None else reading.captain
            row[f"{arm}_solver_status"] = None if reading is None else reading.solver_status
            row[f"{arm}_zero_minute_starters"] = (
                None if reading is None else reading.zero_minute_starters
            )
        for label, value in arms.debias_tables[target].corrections.items():
            row[f"correction_{label}"] = value
        for position, value in arms.shrinkage_tables[target].slopes.items():
            row[f"slope_{position}"] = value
        rows.append(row)
    return pd.DataFrame(rows)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _repository_relative(path: Path) -> str:
    resolved = path.resolve()
    root = REPOSITORY_ROOT.resolve()
    return (
        resolved.relative_to(root).as_posix()
        if resolved.is_relative_to(root)
        else resolved.as_posix()
    )


# --- the run ------------------------------------------------------------------


def _read_handoff(arguments: argparse.Namespace) -> PhaseCComponentHandoff:
    handoff = read_phase_c_component_handoff(
        arguments.table,
        arguments.roster,
        arguments.manifest,
        development_contract=DEVELOPMENT_OOF_CONTRACT_VERSION,
    )
    if handoff.model_version != EXPECTED_MODEL_VERSION:
        raise RankShrinkageError(
            f"The protocol measures the {EXPECTED_MODEL_VERSION} table; got "
            f"{handoff.model_version!r}."
        )
    return handoff


def _prepared_folds(
    handoff: PhaseCComponentHandoff, archive_root: Path
) -> tuple[tuple[EvaluationFold, ...], int]:
    seasons = {str(value) for value in handoff.rows["season"].dropna().unique()}
    outside = sorted(seasons - set(DEVELOPMENT_SEASONS_V2))
    if outside:
        raise RankShrinkageError(f"The handoff carries seasons outside the v2 scope: {outside!r}.")
    decision_seasons = tuple(season for season in DEVELOPMENT_SEASONS_V2 if season in seasons)
    panel = build_panel(archive_root, seasons=(HISTORY_SEASON, *decision_seasons))
    controls = build_walk_forward_folds(
        panel,
        seasons=decision_seasons,
        projection_builder=make_ridge_projection_builder(cross_season=CrossSeasonConfig()),
    )
    prepared = prepare_phase_c_component_folds(
        handoff, controls, development_contract=DEVELOPMENT_OOF_CONTRACT_VERSION
    )
    return prepared, len(panel)


def _evaluate_arms(arms: PreparedArms, config: EvaluationConfig) -> dict[str, EvaluationResult]:
    """Solve the three arms concurrently; each solve is deterministic in its own budget."""

    with ThreadPoolExecutor(max_workers=len(ARMS)) as pool:
        futures = {
            arm: pool.submit(evaluate_prepared_folds, arms.folds[arm], config) for arm in ARMS
        }
        return {arm: future.result() for arm, future in futures.items()}


def _excluded(
    results: Mapping[str, EvaluationResult],
    readings: Mapping[str, Mapping[str, FoldReading]],
    targets: Sequence[str],
) -> tuple[list[dict[str, str]], list[str]]:
    status_by_arm = {
        arm: {item.fold_id: item.optimization_result.solver_status.value for item in result.folds}
        for arm, result in results.items()
    }
    excluded: list[dict[str, str]] = []
    paired: list[str] = []
    for target in targets:
        reasons = [
            f"{arm}: {status_by_arm[arm].get(target, 'missing')}"
            for arm in ARMS
            if target not in readings[arm]
        ]
        if reasons:
            excluded.append({"fold_id": target, "reason": "; ".join(reasons)})
        else:
            paired.append(target)
    return excluded, paired


def run(arguments: argparse.Namespace, *, json_name: str) -> dict[str, object]:
    started = datetime.now(UTC)
    pilot = arguments.folds is not None
    requested = (
        None
        if arguments.folds is None
        else tuple(item.strip() for item in str(arguments.folds).split(",") if item.strip())
    )
    revision, dirty = _git_revision()
    handoff = _read_handoff(arguments)
    prepared, panel_rows = _prepared_folds(handoff, arguments.archive_root)
    all_ids = tuple(fold.fold_id for fold in prepared)
    burn_in, targets = _population(all_ids, requested=requested)
    arms = prepare_arms(handoff, prepared, targets)
    config = EvaluationConfig(
        optimization_config=measurement_optimization_config(),
        scoring_policy=ScoringPolicy.OFFICIAL_AUTOSUB_CAPTAIN_V2,
        run_metadata={"study": RECORD_VERSION},
    )
    results = _evaluate_arms(arms, config)
    control_by_id = {fold.fold_id: fold for fold in arms.folds[CONTROL]}
    readings = {arm: _readings(arm, results[arm], arms, control_by_id) for arm in ARMS}
    excluded, paired_ids = _excluded(results, readings, targets)
    if not paired_ids:
        raise RankShrinkageError("No fold was solved in every arm.")

    primary = _paired(
        readings[ARM_A], readings[CONTROL], paired_ids, candidate_id=PRIMARY_CANDIDATE_ID
    )
    secondary = _paired(
        readings[ARM_B], readings[CONTROL], paired_ids, candidate_id=SECONDARY_CANDIDATE_ID
    )
    gate = _gate(primary)
    table = _fold_table(readings, arms, targets, paired_ids)

    artifact_dir: Path = arguments.artifact_dir
    artifact_dir.mkdir(parents=True, exist_ok=True)
    table_path = artifact_dir / f"{Path(json_name).stem}_folds.csv"
    table.to_csv(table_path, index=False, lineterminator="\n")
    finished = datetime.now(UTC)
    stamp = finished.strftime("%Y-%m-%dT%H:%M:%SZ")
    metadata = artifact_metadata(
        panel_rows=panel_rows,
        created_utc=stamp,
        history_seasons=[HISTORY_SEASON, *DEVELOPMENT_SEASONS_V2],
    )
    seasons_present = sorted({fold_id[:7] for fold_id in paired_ids})
    return {
        "contract_version": RECORD_VERSION,
        "candidate_contract_version": CONTRACT_VERSION,
        "protocol": PROTOCOL,
        "json_name": json_name,
        "pilot": pilot,
        "promotes_anything": False,
        "measurement_only": True,
        "development_scope": "v2",
        "locked_holdout_accessed": True,
        "locked_holdout_note": (
            "2025-26 is read as development data under the Phase C v2 development scope, as "
            "the protocol declares; it is not an unseen test and the locked holdout was not "
            "spent."
        ),
        "repository_commit": revision,
        "working_tree_dirty": dirty,
        "started_at_utc": started.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "finished_at_utc": stamp,
        "generated_at_utc": stamp,
        "provenance": metadata["provenance"],
        "environment": metadata["environment"],
        "inputs": {
            "table": _repository_relative(arguments.table),
            "roster": _repository_relative(arguments.roster),
            "manifest": _repository_relative(arguments.manifest),
            "table_sha256": handoff.table_sha256,
            "roster_sha256": handoff.roster_sha256,
            "manifest_sha256": handoff.manifest_sha256,
            "expected_table_sha256": EXPECTED_TABLE_SHA256,
            "expected_roster_sha256": EXPECTED_ROSTER_SHA256,
            "table_matches_expected": handoff.table_sha256 == EXPECTED_TABLE_SHA256,
            "roster_matches_expected": handoff.roster_sha256 == EXPECTED_ROSTER_SHA256,
            "table_repository_commit": handoff.repository_commit,
            "model_version": handoff.model_version,
            "feature_contract_version": handoff.feature_contract_version,
            "target_contract_version": handoff.target_contract_version,
            "development_contract": handoff.development_contract,
            "weighting": handoff.weighting,
            "rows": len(handoff.rows),
        },
        "harness": {
            "composition": (
                "prepare_phase_c_component_folds: control_expected_points on the component "
                "route, the walk-forward ridge control's expected_points on the direct-control "
                "route"
            ),
            "scoring_policy": ScoringPolicy.OFFICIAL_AUTOSUB_CAPTAIN_V2.value,
            "arms_solved_concurrently": (
                "the three arms ran in three threads; every solve is bound by its own "
                "deterministic budget, so the numbers do not depend on the scheduling"
            ),
            "solver": solver_record(*results.values()),
            "solver_by_arm": {arm: solver_record(results[arm]) for arm in ARMS},
        },
        "population": {
            "table_folds": len(all_ids),
            "burn_in_folds": list(burn_in),
            "target_folds": len(targets),
            "first_target_fold": targets[0],
            "last_target_fold": targets[-1],
            "requested_folds": None if requested is None else list(requested),
            "excluded": excluded,
            "paired_folds": len(paired_ids),
            "paired_folds_by_season": primary["season_paired_folds"],
            "min_history_folds": MIN_HISTORY_FOLDS,
        },
        "arms": dict(ARM_RULES),
        "primary_comparison": {"arm": ARM_A, "against": CONTROL, **primary},
        "secondary_comparison": {"arm": ARM_B, "against": CONTROL, "gated": False, **secondary},
        "gate": gate,
        "verdict": gate["verdict"],
        "diagnostics": {
            "selection_gap": {arm: _selection_gap(readings[arm], paired_ids) for arm in ARMS},
            "overlap_with_control": {
                arm: _overlap(readings[arm], readings[CONTROL], paired_ids)
                for arm in (ARM_A, ARM_B)
            },
            "blanks": {arm: _blanks(readings[arm], paired_ids) for arm in ARMS},
            "corrections": _correction_summary(arms, targets),
            "mean_score_by_arm": {
                arm: fmean(readings[arm][fold_id].score for fold_id in paired_ids) for arm in ARMS
            },
            "season_mean_score_by_arm": {
                arm: {
                    season: fmean(
                        readings[arm][fold_id].score
                        for fold_id in paired_ids
                        if fold_id[:7] == season
                    )
                    for season in seasons_present
                }
                for arm in ARMS
            },
        },
        "per_fold_differences": {
            arm: {
                fold_id: readings[arm][fold_id].score - readings[CONTROL][fold_id].score
                for fold_id in paired_ids
            }
            for arm in (ARM_A, ARM_B)
        },
        "artifacts": {
            "fold_table": _repository_relative(table_path),
            "fold_table_sha256": _sha256(table_path),
            "fold_table_rows": len(table),
        },
        "not_measured": list(NOT_MEASURED),
    }


# --- the Markdown twin --------------------------------------------------------


def _signed(value: object, digits: int = 3) -> str:
    return f"{float(str(value)):+.{digits}f}"


def _plain(value: object, digits: int = 3) -> str:
    return f"{float(str(value)):.{digits}f}"


def _mapping(value: object) -> Mapping[str, object]:
    assert isinstance(value, Mapping)
    return value


def _markdown(document: Mapping[str, object]) -> str:
    primary = _mapping(document["primary_comparison"])
    secondary = _mapping(document["secondary_comparison"])
    gate = _mapping(document["gate"])
    population = _mapping(document["population"])
    diagnostics = _mapping(document["diagnostics"])
    inputs = _mapping(document["inputs"])
    harness = _mapping(document["harness"])
    solver_by_arm = _mapping(harness["solver_by_arm"])
    artifacts = _mapping(document["artifacts"])
    seasons = _mapping(primary["season_mean_differences"])
    secondary_seasons = _mapping(secondary["season_mean_differences"])
    paired_by_season = _mapping(primary["season_paired_folds"])
    selection = _mapping(diagnostics["selection_gap"])
    overlap = _mapping(diagnostics["overlap_with_control"])
    blanks = _mapping(diagnostics["blanks"])
    corrections = _mapping(diagnostics["corrections"])
    mean_corrections = _mapping(corrections["mean_over_target_folds"])
    slopes = _mapping(corrections["position_slope_mean_over_target_folds"])
    interval = primary["interval_90"]
    secondary_interval = secondary["interval_90"]
    assert isinstance(interval, Sequence) and isinstance(secondary_interval, Sequence)
    excluded = population["excluded"]
    burn_in = population["burn_in_folds"]
    assert isinstance(excluded, Sequence) and isinstance(burn_in, Sequence)

    digests_match = bool(inputs["table_matches_expected"]) and bool(
        inputs["roster_matches_expected"]
    )
    digest_note = (
        "equal to the digests the protocol names"
        if digests_match
        else "which differ from the digests the protocol names"
    )
    verdict = str(document["verdict"])
    first_sentence = (
        "**Certified under the pre-registered gate.**"
        if verdict == "certified"
        else "**Measured, not certified** under the pre-registered gate."
    )
    tree_note = (
        "on a tree with uncommitted changes"
        if document["working_tree_dirty"]
        else "on a clean tree"
    )
    exclusion_note = (
        "Excluded: "
        + "; ".join(
            f"{_mapping(item)['fold_id']} ({_mapping(item)['reason']})" for item in excluded
        )
        + "."
        if excluded
        else "No fold was excluded."
    )
    season_rows = [
        f"| {season} | {_signed(value)} | {_signed(secondary_seasons[season])} | "
        f"{paired_by_season[season]} |"
        for season, value in seasons.items()
    ]
    diagnostic_rows = []
    for arm in ARMS:
        gap = _mapping(selection[arm])
        blank = _mapping(blanks[arm])
        counts = _mapping(_mapping(solver_by_arm[arm])["solver_status_counts"])
        diagnostic_rows.append(
            f"| {arm} | {_signed(gap['own_projected_minus_realized_starters'])} | "
            f"{_signed(gap['own_projected_minus_realized_captain'])} | "
            f"{_signed(gap['unshrunk_projected_minus_realized_starters'])} | "
            f"{_signed(gap['unshrunk_projected_minus_realized_captain'])} | "
            f"{blank['zero_minute_starters']} | {_plain(blank['autosub_points'], 0)} | "
            f"{blank['vice_captain_recoveries']} | "
            f"{counts.get('OPTIMAL', 0)} / {counts.get('FEASIBLE', 0)} |"
        )
    overlap_rows = []
    for arm in (ARM_A, ARM_B):
        item = _mapping(overlap[arm])
        overlap_rows.append(
            f"| {arm} | {_plain(item['mean_shared_of_fifteen'], 2)} | "
            f"{_plain(item['mean_shared_of_eleven'], 2)} | {_plain(item['same_captain_rate'], 2)} |"
        )
    licence = (
        "A pass licenses a second pull request pinning Arm A's rule behind a flag that "
        "defaults off; the owner opens it after reviewing this record."
        if gate["certified"]
        else "The verdict licenses nothing but this record."
    )
    pilot_lines = (
        ["**Pilot run on named folds; not the committed record.**", ""] if document["pilot"] else []
    )

    lines = [
        "# Rank-conditional shrinkage of expected points before the squad decision",
        "",
        f"Record of the measurement pre-registered in [the protocol]({Path(PROTOCOL).name}). "
        f"JSON twin: `{document['json_name']}`. Run at commit "
        f"`{str(document['repository_commit'])[:8]}` {tree_note}, "
        f"{document['started_at_utc']} to {document['finished_at_utc']}, on the Phase C v2 "
        f"gradient-boosting out-of-fold table (`{inputs['model_version']}`, table digest "
        f"`{str(inputs['table_sha256'])[:12]}…`, roster `{str(inputs['roster_sha256'])[:12]}…`, "
        f"{digest_note}). 2025-26 was read as development data under the v2 scope; it is not "
        "an unseen test. Measurement only, nothing promoted.",
        "",
        *pilot_lines,
        f"{first_sentence} Arm A (rank-conditional additive debias) minus the unshrunk "
        f"control, paired on {primary['paired_folds']} folds: mean "
        f"{_signed(primary['mean_difference'])} points a gameweek, median "
        f"{_signed(primary['median_difference'], 1)}, 90% season-aware moving-block interval "
        f"[{_signed(interval[0])}, {_signed(interval[1])}], wins / ties / losses "
        f"{primary['wins']} / {primary['ties']} / {primary['losses']}. The noise floor is "
        f"{NOISE_FLOOR_POINTS} points a gameweek; certification needs the mean at or above it, "
        "the interval above zero and at most one negative season.",
        "",
        "## The numbers that decide",
        "",
        "| Quantity | Arm A minus control | Arm B minus control (reported, not gated) |",
        "| --- | ---: | ---: |",
        f"| Paired folds | {primary['paired_folds']} | {secondary['paired_folds']} |",
        f"| Mean difference, points a gameweek | {_signed(primary['mean_difference'])} | "
        f"{_signed(secondary['mean_difference'])} |",
        f"| Median difference | {_signed(primary['median_difference'], 1)} | "
        f"{_signed(secondary['median_difference'], 1)} |",
        f"| 90% interval | [{_signed(interval[0])}, {_signed(interval[1])}] | "
        f"[{_signed(secondary_interval[0])}, {_signed(secondary_interval[1])}] |",
        f"| Wins / ties / losses | {primary['wins']} / {primary['ties']} / {primary['losses']} | "
        f"{secondary['wins']} / {secondary['ties']} / {secondary['losses']} |",
        f"| Mean realized score (control {_plain(primary['control_mean_score'])}) | "
        f"{_plain(primary['candidate_mean_score'])} | "
        f"{_plain(secondary['candidate_mean_score'])} |",
        "",
        "| Season | Arm A minus control | Arm B minus control | Paired folds |",
        "| --- | ---: | ---: | ---: |",
        *season_rows,
        "",
        "| Gate clause | Holds |",
        "| --- | --- |",
        f"| Mean gain at or above +{NOISE_FLOOR_POINTS} | {gate['mean_gain_at_or_above_floor']} |",
        f"| 90% interval excludes zero | {gate['interval_excludes_zero']} |",
        f"| Negative seasons at most {MAX_NEGATIVE_SEASONS} (found {gate['negative_seasons']}) | "
        f"{gate['negative_seasons_within_limit']} |",
        "",
        f"Population: {population['table_folds']} folds in the table, {len(burn_in)} burn-in, "
        f"{population['target_folds']} targets ({population['first_target_fold']} to "
        f"{population['last_target_fold']}), {len(excluded)} excluded, "
        f"{population['paired_folds']} paired. {exclusion_note}",
        "",
        "## Diagnostics, reported not gated",
        "",
        "| Arm | Own projected minus realized, starters | Captain | "
        "Unshrunk projected minus realized, starters | Captain | Zero-minute starters | "
        "Autosub points | Vice recoveries | Proved / incumbent |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
        *diagnostic_rows,
        "",
        "| Arm | Shared of fifteen with control | Shared of eleven | Same captain rate |",
        "| --- | ---: | ---: | ---: |",
        *overlap_rows,
        "",
        "Mean bucket correction `r_b` over the target folds (Arm A): "
        + ", ".join(f"{label} {_signed(value)}" for label, value in mean_corrections.items())
        + ". Mean position slope `lambda_pos` over the target folds (Arm B): "
        + ", ".join(f"{position} {_plain(value)}" for position, value in slopes.items())
        + ".",
        "",
        "## What this is and is not",
        "",
        "- One paired measurement of the single-gameweek squad decision: the same roster, "
        "prices, realized outcomes, solver limits (deterministic budget 5.0) and official "
        "autosub and captain scorer in every arm; only the `expected_points` column differs.",
        "- The projection is the harness's own composition on the gradient-boosting v2 table; "
        "the fit of every target fold reads only the folds before it.",
        "- Arm B is a shape control, reported and not gated.",
        "- Not measured: " + ", ".join(NOT_MEASURED) + ".",
        f"- Nothing is promoted and no product default changes. {licence}",
        "",
        f"Per-fold table: `{artifacts['fold_table']}` (sha256 `{artifacts['fold_table_sha256']}`).",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    arguments = _parse_arguments()
    pilot = arguments.folds is not None
    json_output: Path = arguments.json_output
    if pilot and json_output == DEFAULT_JSON_OUTPUT:
        json_output = DEFAULT_ARTIFACT_DIR / "pilot" / "rank_conditional_shrinkage_pilot.json"
    markdown_output: Path = (
        arguments.markdown_output
        if arguments.markdown_output is not None
        else json_output.with_suffix(".md")
    )
    if pilot:
        for path in (json_output, markdown_output):
            if path.resolve().is_relative_to(DOCS_ROOT.resolve()):
                print(f"A pilot writes nowhere under docs/; refusing {path}.")
                return 1
    else:
        _, dirty = _git_revision()
        if dirty:
            print(
                "The working tree has uncommitted changes, so the recorded commit would not "
                "reproduce this record. Commit or stash them first."
            )
            return 1
    for path in (json_output, markdown_output):
        if path.exists():
            print(f"{path} already exists; a record is written once and never replaced.")
            return 1
    if not arguments.archive_root.is_dir():
        print(f"Archive not found at {arguments.archive_root}.")
        return 1
    try:
        document = run(arguments, json_name=json_output.name)
    except RankShrinkageError as error:
        print(f"Rank-conditional shrinkage measurement refused: {error}")
        return 1
    json_output.parent.mkdir(parents=True, exist_ok=True)
    outcome = write_document_once(document, json_output)
    write_text(markdown_output, _markdown(document))
    primary = _mapping(document["primary_comparison"])
    print(f"Wrote {json_output} ({outcome})")
    print(f"      {markdown_output}")
    print(f"  verdict           {document['verdict']}")
    print(f"  paired folds      {primary['paired_folds']}")
    print(f"  mean gain (A)     {_signed(primary['mean_difference'])}")
    print(f"  interval (A)      {primary['interval_90']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
