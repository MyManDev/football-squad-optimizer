r"""Run the two-part opening projection exactly as its pre-registration fixed it.

    python -m scripts.measure_opening_two_part

Protocol: ``docs/opening_two_part_prereg.md``, committed 2026-08-26 before anything was fitted.
The population, both parts, the fitters, the three clauses and the ordering tolerance are all
its choices and none of them is an argument here: this runner has no flag that can move a gate.

The seasons read are the protocol's five, `2020-21` through `2024-25`, and the earliest is read
so that the one after it has a season behind it. The locked `2025-26` holdout is not read;
``OpeningStudyConfig`` refuses it and the record states that it was not accessed.

The record refuses to overwrite itself: a gate is read once.
"""

import argparse
import logging
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
from scripts._experiment_cli import (
    DEFAULT_ARCHIVE_ROOT,
    REPOSITORY_ROOT,
    artifact_metadata,
    measurement_optimization_config,
    write_json,
    write_text,
)

from squadopt.experiments import ExperimentError
from squadopt.experiments.opening_newcomers import (
    LOCKED_HOLDOUT_SEASON,
    OpeningStudyConfig,
    build_opening_rows,
    control_prediction,
)
from squadopt.experiments.opening_two_part import (
    OPENING_TWO_PART_CONTRACT_VERSION,
    ORDERING_TOLERANCE,
    PART_ONE_DESIGN,
    evaluate_two_part,
    fit_two_part,
    predict_two_part,
    two_part_gate,
)
from squadopt.optimization import optimize_squad

LOGGER = logging.getLogger("opening_two_part")
#: What the first factor's target is, said in the record so a reader cannot take it for more.
PLAY_LABEL_LIMIT = (
    "Part one's target is minutes above zero at the opening gameweek, which is a play label "
    "and not an availability label: the archive carries no status, news or chance-of-playing "
    "column at gameweek one, so no availability label exists to fit. Nothing here says the "
    "factor learned who was available, only who took the field."
)


def _parse_arguments(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--archive-root", type=Path, default=DEFAULT_ARCHIVE_ROOT)
    parser.add_argument(
        "--json-output", type=Path, default=REPOSITORY_ROOT / "docs" / "opening_two_part.json"
    )
    parser.add_argument(
        "--markdown-output", type=Path, default=REPOSITORY_ROOT / "docs" / "opening_two_part.md"
    )
    return parser.parse_args(argv)


def compare_decisions(
    rows: Any, config: OpeningStudyConfig
) -> tuple[list[dict[str, Any]], tuple[float, ...]]:
    """Build the opening squad both ways and score it on what actually happened.

    The same shape as the predecessor's comparison, with the two-part prediction in place of
    an additive candidate: a player with a prior record keeps his carried projection under
    both arms, so the only thing that differs between the squads is how the newcomers are
    priced.
    """

    newcomers = rows.loc[~rows["has_prior_record"]]
    # The protocol's decision clause is the predecessor's, unchanged. Its solver budget is not
    # the predecessor's: #590 landed after this protocol was written and a committed record may
    # not rest on a wall clock, which is the machine's as much as the run's. Both arms get the
    # same named budget, so what the clause compares is untouched.
    optimization = measurement_optimization_config()
    comparisons: list[dict[str, Any]] = []
    differences: list[float] = []
    for season in config.evaluated_seasons:
        training = newcomers.loc[newcomers["season"] < season]
        block = rows.loc[rows["season"] == season].copy()
        if len(training) < config.minimum_training_rows or block.empty:
            continue
        coefficients = fit_two_part(training)
        candidate_new = predict_two_part(block, coefficients)
        control_new = control_prediction(block)
        carried = block["carried_projection"].to_numpy(dtype="float64")
        has_record = block["has_prior_record"].to_numpy(dtype="bool")
        pool = block.loc[:, ["player_id", "name", "team_id", "position", "price_tenths"]].copy()
        realized = block.set_index("player_id")["total_points"].astype("float64")
        newcomer_ids = set(block.loc[~block["has_prior_record"], "player_id"].tolist())
        squads: dict[str, tuple[float, int, tuple[int, ...]]] = {}
        for label, fallback in (("control", control_new), ("candidate", candidate_new)):
            projection = pool.copy()
            projection["expected_points"] = np.where(has_record, carried, fallback)
            projection["expected_points"] = np.nan_to_num(
                projection["expected_points"].to_numpy(dtype="float64"), nan=0.0
            ).clip(min=0.0)
            result = optimize_squad(projection, optimization)
            if not result.has_solution or result.captain is None:
                raise ExperimentError(f"{season}: the {label} opening squad could not be built.")
            starters = tuple(int(value) for value in result.starting_xi["player_id"])
            captain = int(result.captain["player_id"])
            score = float(sum(realized.get(player, 0.0) for player in starters))
            score += float(realized.get(captain, 0.0))
            squads[label] = (
                score,
                sum(1 for player in starters if player in newcomer_ids),
                starters,
            )
        control_score, control_new_count, control_starters = squads["control"]
        candidate_score, candidate_new_count, candidate_starters = squads["candidate"]
        differences.append(candidate_score - control_score)
        comparisons.append(
            {
                "season": season,
                "control_realized_points": control_score,
                "candidate_realized_points": candidate_score,
                "difference": candidate_score - control_score,
                "control_newcomers_selected": control_new_count,
                "candidate_newcomers_selected": candidate_new_count,
                "changed_starters": len(set(candidate_starters) - set(control_starters)),
            }
        )
    return comparisons, tuple(differences)


def _markdown(record: dict[str, Any]) -> str:
    gate = record["gate"]
    lines = [
        "# The two-part opening projection",
        "",
        f"Contract `{record['contract_version']}`. Protocol: "
        "`docs/opening_two_part_prereg.md`, committed 2026-08-26 before anything was fitted. "
        f"**Verdict: {'passes' if gate['passes'] else 'fails'}.**",
        "",
        "The shape: expected points = P(plays | ownership, price, position) times "
        "E[points | plays, price, position]. Seasons read "
        f"{', '.join(record['config']['seasons'])}, judged "
        f"{', '.join(record['config']['evaluated_seasons'])}. Locked holdout accessed: "
        f"{record['locked_holdout_accessed']}.",
        "",
        "## The gate, as the protocol fixed it",
        "",
        "| Clause | Reading | Passes |",
        "| --- | --- | --- |",
        f"| 1 accuracy | pooled improvement {record['summary']['pooled_mae_improvement']:+.4f}, "
        f"90% interval [{record['summary']['interval_90'][0]:+.4f}, "
        f"{record['summary']['interval_90'][1]:+.4f}], improves every season "
        f"{record['summary']['improves_every_season']} | "
        f"{'yes' if gate['accuracy_passes'] else 'no'} |",
        f"| 2 ordering | worst season shortfall {gate['worst_season_rank_shortfall']:+.4f}, "
        f"pooled {gate['pooled_rank_shortfall']:+.4f}, tolerance "
        f"{gate['ordering_tolerance']:.3f} | {'yes' if gate['ordering_passes'] else 'no'} |",
        f"| 3 decision | mean {gate['mean_decision_difference']:+.3f} points, "
        f"{gate['decision_losses']} losing season(s) | "
        f"{'yes' if gate['decision_passes'] else 'no'} |",
        "",
        "## Per judged season",
        "",
        "| Season | Rows | Control MAE | Candidate MAE | Improvement | Control rank | "
        "Candidate rank | Shortfall |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for season in record["seasons"]:
        lines.append(
            f"| {season['season']} | {season['rows']} | {season['control_mae']:.4f} | "
            f"{season['candidate_mae']:.4f} | {season['mae_improvement']:+.4f} | "
            f"{season['control_rank']:.4f} | {season['candidate_rank']:.4f} | "
            f"{season['rank_shortfall']:+.4f} |"
        )
    lines += [
        "",
        "## Reported, not gated",
        "",
        "Calibration of part one, predicted against realized play rate by decile:",
        "",
        "| Season | Decile | Rows | Predicted | Realized |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for season in record["seasons"]:
        for cell in season["calibration"]:
            lines.append(
                f"| {season['season']} | {cell['decile']} | {cell['rows']} | "
                f"{cell['mean_predicted']:.4f} | {cell['realized_play_rate']:.4f} |"
            )
    lines += [
        "",
        "| Season | Played rows | Bias on played | MAE on played | Rows with no published "
        "ownership |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for season in record["seasons"]:
        lines.append(
            f"| {season['season']} | {season['played_rows']} | "
            f"{season['candidate_bias_on_played']:+.4f} | "
            f"{season['candidate_mae_on_played']:.4f} | "
            f"{season['rows_without_published_ownership']} |"
        )
    lines += ["", "## What this measurement cannot conclude", "", PLAY_LABEL_LIMIT, ""]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    arguments = _parse_arguments(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    if arguments.json_output.exists():
        print(f"{arguments.json_output} exists; a gate is read once.")
        return 1
    if not arguments.archive_root.is_dir():
        print(f"Archive not found at {arguments.archive_root}.")
        return 1
    created_utc = datetime.now(UTC).isoformat(timespec="seconds")
    started = datetime.now(UTC)
    try:
        config = OpeningStudyConfig()
        LOGGER.info(
            "Reading %s, judging %s",
            ", ".join(config.seasons),
            ", ".join(config.evaluated_seasons),
        )
        rows = build_opening_rows(arguments.archive_root, config)
        readings, summary = evaluate_two_part(rows, config)
        if not readings:
            print("No judged season had enough training rows.")
            return 1
        comparisons, differences = compare_decisions(rows, config)
    except ExperimentError as error:
        print(f"Could not run the two-part opening study:\n  {error}")
        return 1

    judged = [reading.season for reading in readings]
    pooled_rows = rows.loc[(~rows["has_prior_record"]) & (rows["season"].isin(judged))]
    # The pooled ordering of the candidate needs one fit per season, so it is read as the mean
    # of the judged seasons' own within-position correlations rather than over a pool whose
    # rows were priced by different fits.
    pooled_candidate_rank = float(np.mean([reading.candidate_rank for reading in readings]))
    pooled_control_rank = float(np.mean([reading.control_rank for reading in readings]))
    gate = two_part_gate(
        readings, summary, pooled_control_rank - pooled_candidate_rank, differences
    )
    seasons_record = []
    for reading in readings:
        entry = asdict(reading)
        entry["mae_improvement"] = reading.mae_improvement
        entry["rank_shortfall"] = reading.rank_shortfall
        entry["calibration"] = [dict(cell) for cell in reading.calibration]
        seasons_record.append(entry)
    record: dict[str, Any] = {
        **artifact_metadata(panel_rows=len(rows), created_utc=created_utc),
        "contract_version": OPENING_TWO_PART_CONTRACT_VERSION,
        "prereg": "docs/opening_two_part_prereg.md",
        "config": asdict(config),
        "locked_holdout_accessed": LOCKED_HOLDOUT_SEASON
        in set(str(value) for value in rows["season"].unique()),
        "part_one_design": list(PART_ONE_DESIGN),
        "ordering_tolerance": ORDERING_TOLERANCE,
        "population": {
            "opening_rows": len(rows),
            "newcomer_rows": int((~rows["has_prior_record"]).sum()),
            "pooled_judged_rows": len(pooled_rows),
        },
        "summary": {
            **summary,
            "pooled_candidate_rank": pooled_candidate_rank,
            "pooled_control_rank_over_judged_seasons": pooled_control_rank,
        },
        "seasons": seasons_record,
        "decisions": comparisons,
        "gate": gate,
        "play_label_limit": PLAY_LABEL_LIMIT,
        "solver": {
            "deterministic_time_limit": (
                measurement_optimization_config().solver_deterministic_time_limit
            ),
            "wall_time_limit_seconds": (
                measurement_optimization_config().solver_time_limit_seconds
            ),
            "binding_limit": "deterministic_time",
            "clause_affected": "only the decision clause solves; accuracy and ordering do not",
        },
        "elapsed_seconds": (datetime.now(UTC) - started).total_seconds(),
    }
    if record["locked_holdout_accessed"]:
        print("The locked holdout was read; the record is not written.")
        return 1
    write_json(arguments.json_output, record)
    write_text(arguments.markdown_output, _markdown(record))
    print(_markdown(record))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
