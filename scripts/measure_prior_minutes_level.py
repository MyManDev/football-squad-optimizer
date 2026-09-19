r"""Measure a level correction by this season's minutes against the forecast as it stands.

    python -m scripts.measure_prior_minutes_level \
        --table artifacts/phase_c/phase_c_component_oof_v1.csv \
        --roster artifacts/phase_c/phase_c_component_oof_v1.roster.csv \
        --manifest artifacts/phase_c/phase_c_component_oof_v1.manifest.json

Protocol: ``docs/prior_minutes_level_prereg.md``, whose two gates and three verdicts are fixed
and are only read here. The base arm is the component forecast over the 147 development
decisions; the candidate arm is the same forecast times a factor per bucket of prior minutes,
fitted at every decision on the decisions before it. Both are solved under
``measurement_optimization_config()`` and scored with the official autosub policy. The locked
holdout is refused before anything is read, and the record is never overwritten.
"""

import argparse
from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd
from scripts._experiment_cli import (
    DEFAULT_ARCHIVE_ROOT,
    REPOSITORY_ROOT,
    measurement_optimization_config,
    write_json,
    write_text,
)
from scripts.measure_projection_level_audit import prior_minutes_per_week

from squadopt.backtest import build_walk_forward_folds, make_ridge_projection_builder
from squadopt.data.sources.vaastav import build_panel
from squadopt.evaluation import (
    EvaluationConfig,
    ScoringPolicy,
    evaluate_phase_c_component_decisions,
    read_phase_c_component_handoff,
)
from squadopt.evaluation.component_decisions import prepare_phase_c_component_folds
from squadopt.evaluation.component_handoff import LOCKED_HOLDOUT_SEASON
from squadopt.evaluation.live_projection_audit import PRIOR_MINUTES_BUCKETS
from squadopt.evaluation.prior_minutes_level import (
    FACTOR_BOUNDS,
    MINIMUM_EARLIER_DECISIONS,
    PRIOR_MINUTES_LEVEL_CONTRACT_VERSION,
    corrected_forecast,
    online_factors,
    prior_bucket,
    row_factors,
)
from squadopt.evaluation.promotion import PromotionPolicy
from squadopt.experiments.statistics import season_aware_moving_block_interval
from squadopt.features import CrossSeasonConfig
from squadopt.optimization.models import SolverStatus

DEFAULT_JSON_OUTPUT = REPOSITORY_ROOT / "docs" / "prior_minutes_level.json"
DEFAULT_MARKDOWN_OUTPUT = REPOSITORY_ROOT / "docs" / "prior_minutes_level.md"
HISTORY_SEASONS = ("2020-21", "2021-22", "2022-23", "2023-24", "2024-25")
DECISION_SEASONS = HISTORY_SEASONS[1:]
#: Gate 1: the corrected bias of a bucket is at most this share of the uncorrected one.
LEVEL_GATE_SHARE = 0.5
#: Gate 2's floor for `level_only`: the mean paired difference, points a gameweek.
NO_HARM_FLOOR = -0.25
BOOTSTRAP_RESAMPLES = 2000
BLOCK_LENGTH = 4


def _parse_arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--table", type=Path, required=True)
    parser.add_argument("--roster", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--archive-root", type=Path, default=DEFAULT_ARCHIVE_ROOT)
    parser.add_argument("--json-output", type=Path, default=DEFAULT_JSON_OUTPUT)
    parser.add_argument("--markdown-output", type=Path, default=DEFAULT_MARKDOWN_OUTPUT)
    return parser.parse_args(argv)


def factor_table(rows: pd.DataFrame, panel: pd.DataFrame) -> pd.DataFrame:
    """The handoff's rows as the factor reads them; the outcome as the evaluation reads it."""

    appeared = rows["appearance_target"].astype(float) == 1.0
    return pd.DataFrame(
        {
            "fold_id": rows["fold_id"].astype(str),
            "target_gameweek": rows["target_gameweek"].astype(int),
            "player_id": rows["player_id"].astype("int64"),
            # A blank gameweek has nothing to forecast and teaches the factor nothing.
            "forecast": rows["control_expected_points"]
            .astype(float)
            .where(rows["fixture_count"] > 0),
            "realized": rows["points_target"].astype(float).where(appeared, 0.0),
            "prior_minutes_per_week": prior_minutes_per_week(panel, rows),
        },
        index=rows.index,
    )


def level_gate(table: pd.DataFrame, corrected: pd.Series, factors: pd.DataFrame) -> dict[str, Any]:
    """Gate 1, over the rows a factor other than 1 applied to.

    The rows are taken from the correction itself (`row_factors`), never from the factor table
    alone: a row before the first gameweek read sits in a decision whose factors are not 1 and
    is still not corrected, and reading it here would score an untouched forecast as a
    corrected one.
    """

    bucket = prior_bucket(table["prior_minutes_per_week"])
    touched = row_factors(table, factors) != 1.0
    rows = table.loc[touched & table["forecast"].notna()]
    buckets: dict[str, Any] = {}
    passed = True
    for label, _, _ in PRIOR_MINUTES_BUCKETS:
        held = rows.loc[bucket.loc[rows.index] == label]
        if held.empty:
            buckets[label] = {"rows": 0}
            passed = False
            continue
        before = float((held["realized"] - held["forecast"]).mean())
        after = float((held["realized"] - corrected.loc[held.index]).mean())
        ok = abs(after) <= LEVEL_GATE_SHARE * abs(before)
        passed = passed and ok
        buckets[label] = {
            "rows": len(held),
            "bias_uncorrected": before,
            "bias_corrected": after,
            "passes": ok,
        }
    mae_before = float((rows["realized"] - rows["forecast"]).abs().mean())
    mae_after = float((rows["realized"] - corrected.loc[rows.index]).abs().mean())
    return {
        "rows": len(rows),
        "buckets": buckets,
        "mean_absolute_error_uncorrected": mae_before,
        "mean_absolute_error_corrected": mae_after,
        "mean_absolute_error_not_worse": mae_after <= mae_before,
        "passes": bool(passed and mae_after <= mae_before),
    }


def verdict(level_passes: bool, mean: float, interval: tuple[float, float] | None) -> str:
    """The protocol's three verdicts, read and never moved."""

    if not level_passes or interval is None:
        return "failed"
    if interval[0] > 0:
        return "decisions"
    if interval[0] <= 0 <= interval[1] and mean >= NO_HARM_FLOOR:
        return "level_only"
    return "failed"


def _markdown(record: Mapping[str, Any]) -> str:
    gate = record["level_gate"]
    paired = record["decision_gate"]
    interval = paired["interval"]
    lines = [
        "# A level correction by this season's minutes",
        "",
        f"Contract `{record['contract_version']}`. Protocol: `docs/prior_minutes_level_prereg.md`. "
        f"Verdict: **`{record['verdict']}`**.",
        "",
        "## Gate 1: level, out of sample",
        "",
        "| prior minutes a gameweek | rows | bias as it stands | bias corrected | passes |",
        "| --- | ---: | ---: | ---: | --- |",
    ]
    for label, block in gate["buckets"].items():
        if not block.get("rows"):
            lines.append(f"| {label} | 0 | | | no |")
            continue
        lines.append(
            f"| {label} | {block['rows']} | {block['bias_uncorrected']:+.3f} | "
            f"{block['bias_corrected']:+.3f} | {'yes' if block['passes'] else 'no'} |"
        )
    lines += [
        "",
        f"Points MAE {gate['mean_absolute_error_uncorrected']:.4f} as it stands, "
        f"{gate['mean_absolute_error_corrected']:.4f} corrected. Gate 1 "
        f"{'passes' if gate['passes'] else 'fails'}.",
        "",
        "## Gate 2: realized squad points, candidate minus the forecast as it stands",
        "",
        f"Mean {paired['mean_difference']:+.3f} a gameweek over {paired['paired_decisions']} "
        "decisions, 90% block bootstrap interval "
        + ("n/a" if interval is None else f"[{interval[0]:+.3f}, {interval[1]:+.3f}]")
        + f"; wins/ties/losses {paired['wins']}/{paired['ties']}/{paired['losses']}; "
        f"{paired['decisions_with_a_different_squad']} decisions chose a different squad.",
        "",
        "| season | mean difference |",
        "| --- | ---: |",
    ]
    lines += [f"| {season} | {value:+.3f} |" for season, value in paired["by_season"].items()]
    lines += [
        "",
        "| arm | mean realized | proven optimal | starters with zero minutes |",
        "| --- | ---: | ---: | ---: |",
    ]
    for arm, block in record["arms"].items():
        lines.append(
            f"| {arm} | {block['mean_realized_points']:.3f} | {block['proven_share']:.2f} | "
            f"{block['zero_minute_starters']} |"
        )
    lines += ["", "## The factors at the last decision", ""]
    lines += [
        f"- {row['bucket']}: {row['factor']:.3f} "
        f"(from {row['earlier_decisions']} earlier decisions)"
        for row in record["final_factors"]
    ]
    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parse_arguments(argv)
    if arguments.json_output.exists():
        print(f"{arguments.json_output} exists; retire it in its own commit before re-running.")
        return 1
    handoff = read_phase_c_component_handoff(arguments.table, arguments.roster, arguments.manifest)
    seasons = {str(value) for value in handoff.rows["season"].unique()}
    if LOCKED_HOLDOUT_SEASON in seasons or handoff.development_contract is not None:
        print("Only the frozen v1 development handoff is read.")
        return 1

    started = datetime.now(UTC)
    panel = build_panel(arguments.archive_root, seasons=HISTORY_SEASONS)
    table = factor_table(handoff.rows, panel)
    order = handoff.rows["fold_id"].astype(str).drop_duplicates().tolist()
    factors = online_factors(table, order)
    corrected = corrected_forecast(table, factors)
    gate_one = level_gate(table, corrected, factors)

    ridge = build_walk_forward_folds(
        panel,
        seasons=DECISION_SEASONS,
        projection_builder=make_ridge_projection_builder(cross_season=CrossSeasonConfig()),
    )
    base_folds = prepare_phase_c_component_folds(handoff, ridge)
    # Only rows that had a component forecast are touched; a thin-history row stays absent
    # here and is filled from the same fallback in both arms.
    candidate = replace(
        handoff,
        rows=handoff.rows.assign(
            control_expected_points=corrected.where(handoff.rows["control_expected_points"].notna())
        ),
    )
    config = EvaluationConfig(
        optimization_config=measurement_optimization_config(),
        scoring_policy=ScoringPolicy.OFFICIAL_AUTOSUB_CAPTAIN_V2,
        run_metadata={"study": PRIOR_MINUTES_LEVEL_CONTRACT_VERSION},
    )
    comparison = evaluate_phase_c_component_decisions(candidate, base_folds, config)

    def scores(result: Any) -> dict[str, float]:
        return {
            item.fold_id: float(item.realized_squad_points)
            for item in result.folds
            if item.realized_squad_points is not None
        }

    def squads(result: Any) -> dict[str, frozenset[int]]:
        return {
            item.fold_id: frozenset(
                int(value) for value in item.optimization_result.selected_squad["player_id"]
            )
            for item in result.folds
            if item.optimization_result.has_solution
        }

    base_scores = scores(comparison.control)
    candidate_scores = scores(comparison.component_base)
    paired_ids = [fold for fold in order if fold in base_scores and fold in candidate_scores]
    differences = [candidate_scores[fold] - base_scores[fold] for fold in paired_ids]
    pairs = [(fold[:7], value) for fold, value in zip(paired_ids, differences, strict=True)]
    interval = (
        season_aware_moving_block_interval(
            pairs,
            policy=PromotionPolicy(
                bootstrap_resamples=BOOTSTRAP_RESAMPLES, moving_block_length=BLOCK_LENGTH
            ),
            candidate_id=PRIOR_MINUTES_LEVEL_CONTRACT_VERSION,
        )
        if len(pairs) >= 2
        else None
    )
    mean = sum(differences) / len(differences)
    by_season: dict[str, list[float]] = {}
    for season, value in pairs:
        by_season.setdefault(season, []).append(value)
    base_squads, candidate_squads = (
        squads(comparison.control),
        squads(comparison.component_base),
    )
    diagnostics = comparison.diagnostics

    def arm(result: Any, zero_minute: int) -> dict[str, Any]:
        solved = [item for item in result.folds if item.optimization_result.has_solution]
        proven = sum(
            1 for item in solved if item.optimization_result.solver_status is SolverStatus.OPTIMAL
        )
        values = list(scores(result).values())
        return {
            "mean_realized_points": sum(values) / len(values),
            "scored_decisions": len(values),
            "proven_share": proven / len(solved) if solved else 0.0,
            "zero_minute_starters": zero_minute,
        }

    final = factors.loc[factors["fold_id"] == order[-1]]
    optimization = config.optimization_config
    record: dict[str, Any] = {
        "contract_version": PRIOR_MINUTES_LEVEL_CONTRACT_VERSION,
        "prereg": "docs/prior_minutes_level_prereg.md",
        "generated_at_utc": started.replace(microsecond=0).isoformat(),
        "elapsed_seconds": (datetime.now(UTC) - started).total_seconds(),
        "operational_control_changed": False,
        "locked_holdout_accessed": False,
        "table_sha256": handoff.table_sha256,
        "roster_sha256": handoff.roster_sha256,
        "manifest_sha256": handoff.manifest_sha256,
        "producer_repository_commit": handoff.repository_commit,
        "candidate": {
            "minimum_earlier_decisions": MINIMUM_EARLIER_DECISIONS,
            "factor_bounds": list(FACTOR_BOUNDS),
            "buckets": [label for label, _, _ in PRIOR_MINUTES_BUCKETS],
        },
        "solver": {
            "deterministic_time_limit": optimization.solver_deterministic_time_limit,
            "wall_time_limit_seconds": optimization.solver_time_limit_seconds,
        },
        "level_gate": gate_one,
        "decision_gate": {
            "paired_decisions": len(differences),
            "mean_difference": mean,
            "interval": None if interval is None else [float(interval[0]), float(interval[1])],
            "interval_level": 0.90,
            "block_length": BLOCK_LENGTH,
            "resamples": BOOTSTRAP_RESAMPLES,
            "wins": sum(value > 0 for value in differences),
            "ties": sum(value == 0 for value in differences),
            "losses": sum(value < 0 for value in differences),
            "by_season": {
                season: sum(values) / len(values) for season, values in sorted(by_season.items())
            },
            "decisions_with_a_different_squad": sum(
                1 for fold in paired_ids if base_squads.get(fold) != candidate_squads.get(fold)
            ),
            "no_harm_floor": NO_HARM_FLOOR,
        },
        "arms": {
            "as_it_stands": arm(comparison.control, diagnostics.control_zero_minute_starters),
            "corrected": arm(comparison.component_base, diagnostics.candidate_zero_minute_starters),
        },
        "final_factors": final.to_dict("records"),
        "factor_paths": factors.to_dict("records"),
    }
    record["verdict"] = verdict(bool(gate_one["passes"]), mean, interval)
    write_json(arguments.json_output, record)
    write_text(arguments.markdown_output, _markdown(record))
    print(_markdown(record))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
