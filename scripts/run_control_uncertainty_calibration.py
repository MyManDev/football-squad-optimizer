"""Calibrate control-regime uncertainty on real folds, evaluated inside development.

    python -m scripts.run_control_uncertainty_calibration \
        --json-output docs/control_uncertainty_calibration.json \
        --markdown-output docs/control_uncertainty_calibration.md

Fits the position-level conformal calibration and the player-adaptive calibration on
the early development seasons and scores both, frozen, on the last development season
(2024-25). The 2025-26 locked holdout is never read: the point of this run is real
held-out coverage/width evidence for the control regime without spending any holdout.
"""

import argparse
import logging
import sys
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from scripts._experiment_cli import (
    DEFAULT_ARCHIVE_ROOT,
    REPOSITORY_ROOT,
    artifact_metadata,
    write_json,
    write_text,
)

from squadopt.backtest import build_walk_forward_folds, make_baseline_projection_builder
from squadopt.data.sources.vaastav import build_panel
from squadopt.prediction import BASELINE_FORM_WINDOW
from squadopt.uncertainty import (
    PlayerAdaptiveUncertaintyConfig,
    UncertaintyConfig,
    UncertaintyError,
    evaluate_player_adaptive_uncertainty,
    evaluate_projection_uncertainty,
    fit_player_adaptive_uncertainty,
    fit_projection_uncertainty,
)

LOGGER = logging.getLogger(__name__)

DEFAULT_CALIBRATION_SEASONS = "2021-22,2022-23,2023-24"
DEFAULT_EVALUATION_SEASON = "2024-25"


def _parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive-root", type=Path, default=DEFAULT_ARCHIVE_ROOT)
    parser.add_argument("--calibration-seasons", default=DEFAULT_CALIBRATION_SEASONS)
    parser.add_argument("--evaluation-season", default=DEFAULT_EVALUATION_SEASON)
    parser.add_argument("--confidence-level", type=float, default=0.90)
    parser.add_argument("--form-window", type=int, default=BASELINE_FORM_WINDOW)
    parser.add_argument(
        "--json-output",
        type=Path,
        default=REPOSITORY_ROOT / "docs" / "control_uncertainty_calibration.json",
    )
    parser.add_argument(
        "--markdown-output",
        type=Path,
        default=REPOSITORY_ROOT / "docs" / "control_uncertainty_calibration.md",
    )
    return parser.parse_args()


def _metric_rows(label: str, metrics: object, group_metrics: dict[str, object]) -> list[str]:
    rows = [_metric_row(label, "All", metrics)]
    for position in sorted(group_metrics):
        rows.append(_metric_row(label, position, group_metrics[position]))
    return rows


def _metric_row(label: str, population: str, metrics: object) -> str:
    record = asdict(metrics)  # type: ignore[call-overload]
    return (
        f"| {label} | {population} | {record['observations']} "
        f"| {record['empirical_coverage']:.4f} | {record['mean_interval_width']:.4f} "
        f"| {record['mean_absolute_error']:.4f} "
        f"| {record['root_mean_squared_error']:.4f} |"
    )


def main() -> int:
    arguments = _parse_arguments()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    if not arguments.archive_root.is_dir():
        print(f"Archive not found at {arguments.archive_root}.")
        return 1

    calibration_seasons = tuple(
        season.strip() for season in str(arguments.calibration_seasons).split(",")
    )
    evaluation_season = str(arguments.evaluation_season).strip()
    if evaluation_season == "2025-26" or "2025-26" in calibration_seasons:
        print(
            "The 2025-26 locked holdout may not be read by this development-internal "
            "calibration run."
        )
        return 1

    created_utc = datetime.now(UTC).isoformat(timespec="seconds")
    panel = build_panel(arguments.archive_root)
    builder = make_baseline_projection_builder(form_window=arguments.form_window)

    try:
        position_config = UncertaintyConfig(
            confidence_level=arguments.confidence_level,
            development_seasons=calibration_seasons,
            holdout_season=evaluation_season,
        )
        adaptive_config = PlayerAdaptiveUncertaintyConfig(
            confidence_level=arguments.confidence_level,
            development_seasons=calibration_seasons,
            holdout_season=evaluation_season,
        )
        LOGGER.info("Building calibration folds for %s", ", ".join(calibration_seasons))
        calibration_folds = build_walk_forward_folds(
            panel,
            seasons=calibration_seasons,
            min_prior_gameweeks_in_season=1,
            projection_builder=builder,
        )
        LOGGER.info("Building evaluation folds for %s", evaluation_season)
        evaluation_folds = build_walk_forward_folds(
            panel,
            seasons=(evaluation_season,),
            min_prior_gameweeks_in_season=1,
            projection_builder=builder,
        )
        position_calibration = fit_projection_uncertainty(calibration_folds, position_config)
        position_result = evaluate_projection_uncertainty(evaluation_folds, position_calibration)
        adaptive_calibration = fit_player_adaptive_uncertainty(calibration_folds, adaptive_config)
        adaptive_result = evaluate_player_adaptive_uncertainty(
            evaluation_folds, adaptive_calibration
        )
    except UncertaintyError as error:
        print(f"Could not calibrate control uncertainty:\n  {error}")
        return 1

    document = {
        **artifact_metadata(panel_rows=len(panel), created_utc=created_utc),
        "calibration_seasons": list(calibration_seasons),
        "evaluation_season": evaluation_season,
        "locked_holdout_accessed": False,
        "confidence_level": arguments.confidence_level,
        "form_window": arguments.form_window,
        "calibration_fold_count": len(calibration_folds),
        "evaluation_fold_count": len(evaluation_folds),
        "position_level": {
            "configuration_fingerprint": (position_config.configuration_fingerprint),
            "calibration_fingerprint": (position_calibration.calibration_fingerprint),
            "metrics": asdict(position_result.metrics),
            "group_metrics": {
                position: asdict(metrics)
                for position, metrics in position_result.group_metrics.items()
            },
        },
        "player_adaptive": {
            "configuration_fingerprint": (adaptive_config.configuration_fingerprint),
            "calibration_fingerprint": (adaptive_calibration.calibration_fingerprint),
            "metrics": asdict(adaptive_result.metrics),
            "group_metrics": {
                position: asdict(metrics)
                for position, metrics in adaptive_result.group_metrics.items()
            },
        },
        "note": (
            "Development-internal evaluation: both calibrations are fit on the early "
            "development seasons and scored frozen on the last development season. "
            "The 2025-26 locked holdout was not read."
        ),
    }

    markdown_lines = [
        "# Control uncertainty calibration (development-internal)",
        "",
        f"- Calibration seasons: {', '.join(calibration_seasons)} ({len(calibration_folds)} folds)",
        f"- Evaluation season: {evaluation_season} ({len(evaluation_folds)} folds, "
        "frozen calibrations, no refit)",
        f"- Confidence level: {arguments.confidence_level}",
        f"- Baseline form window: {arguments.form_window}",
        "- The 2025-26 locked holdout was **not** read.",
        "",
        "| Calibration | Population | Observations | Coverage | Mean width | MAE | RMSE |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: |",
        *_metric_rows(
            "Position-level",
            position_result.metrics,
            dict(position_result.group_metrics),
        ),
        *_metric_rows(
            "Player-adaptive",
            adaptive_result.metrics,
            dict(adaptive_result.group_metrics),
        ),
        "",
        "The comparison to read: at the same confidence level, does the player-adaptive",
        "calibration hold coverage while narrowing the mean interval width?",
    ]
    markdown = "\n".join(markdown_lines) + "\n"

    write_json(arguments.json_output, document)
    write_text(arguments.markdown_output, markdown)
    print(markdown)
    print(f"Wrote {arguments.json_output}")
    print(f"Wrote {arguments.markdown_output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
