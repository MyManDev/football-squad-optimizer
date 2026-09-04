"""Fit Sprint 3 uncertainty calibration and score the locked real-data holdout.

    python -m scripts.run_uncertainty_benchmark
    python -m scripts.run_uncertainty_benchmark --confidence-level 0.9

The pinned archive must first be fetched with:

    python -m scripts.fetch_historical_data
"""

import argparse
import hashlib
import json
import platform
import subprocess
import sys
from dataclasses import asdict
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path

import pandas as pd

from squadopt.backtest import build_walk_forward_folds, make_baseline_projection_builder
from squadopt.data.sources.vaastav import (
    ARCHIVE_COMMIT,
    ARCHIVE_REPOSITORY,
    build_panel,
)
from squadopt.prediction import BASELINE_FORM_WINDOW, FEATURE_GENERATION_CONTRACT_VERSION
from squadopt.uncertainty import (
    ProjectionUncertaintyCalibration,
    UncertaintyConfig,
    UncertaintyEvaluationResult,
    UncertaintyMetrics,
    evaluate_projection_uncertainty,
    fit_projection_uncertainty,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ARCHIVE_ROOT = REPOSITORY_ROOT / "data" / "raw" / "vaastav-fpl"
DEFAULT_OUTPUT_ROOT = REPOSITORY_ROOT / "artifacts" / "sprint3"
MANIFEST_PATH = REPOSITORY_ROOT / "data" / "sources" / "vaastav_fpl_manifest.json"


def _parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive-root", type=Path, default=DEFAULT_ARCHIVE_ROOT)
    parser.add_argument("--confidence-level", type=float, default=0.9)
    parser.add_argument("--min-pooled-observations", type=int, default=30)
    parser.add_argument("--min-group-observations", type=int, default=30)
    parser.add_argument(
        "--json-output",
        type=Path,
        default=DEFAULT_OUTPUT_ROOT / "uncertainty_benchmark.json",
    )
    parser.add_argument(
        "--markdown-output",
        type=Path,
        default=DEFAULT_OUTPUT_ROOT / "uncertainty_benchmark.md",
    )
    return parser.parse_args()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1 << 20):
            digest.update(chunk)
    return digest.hexdigest()


def _git_revision() -> tuple[str, bool]:
    try:
        revision = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPOSITORY_ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        dirty = bool(
            subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=REPOSITORY_ROOT,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
        )
    except (OSError, subprocess.CalledProcessError) as error:
        raise SystemExit(f"Cannot record repository revision: {error}") from error
    return revision, dirty


def _metric_record(metrics: UncertaintyMetrics) -> dict[str, int | float]:
    return asdict(metrics)


def _build_report(
    result: UncertaintyEvaluationResult,
    *,
    panel_rows: int,
    created_utc: str,
) -> dict[str, object]:
    revision, dirty = _git_revision()
    calibration: ProjectionUncertaintyCalibration = result.calibration
    return {
        "created_utc": created_utc,
        "provenance": {
            "repository_commit": revision,
            "working_tree_dirty": dirty,
            "archive_repository": ARCHIVE_REPOSITORY,
            "archive_commit": ARCHIVE_COMMIT,
            "archive_manifest_sha256": _sha256(MANIFEST_PATH),
            "panel_rows": panel_rows,
            "feature_generation_contract_version": FEATURE_GENERATION_CONTRACT_VERSION,
            "baseline_form_window": BASELINE_FORM_WINDOW,
            "uncertainty_contract_version": calibration.config.contract_version,
            "configuration_fingerprint": calibration.config.configuration_fingerprint,
            "calibration_fingerprint": calibration.calibration_fingerprint,
        },
        "configuration": asdict(calibration.config),
        "calibration": {
            "pooled_observations": calibration.pooled_observations,
            "groups": {position: asdict(group) for position, group in calibration.groups.items()},
            "diagnostics": dict(calibration.diagnostics),
        },
        "holdout": {
            "metrics": _metric_record(result.metrics),
            "group_metrics": {
                position: _metric_record(metrics)
                for position, metrics in result.group_metrics.items()
            },
            "folds": [
                {
                    "fold_id": fold.fold_id,
                    "season": fold.metadata["season"],
                    "gameweek": fold.metadata["gameweek"],
                    "metrics": _metric_record(fold.metrics),
                }
                for fold in result.folds
            ],
            "diagnostics": dict(result.diagnostics),
        },
        "environment": {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "pandas": pd.__version__,
            "ortools": version("ortools"),
        },
        "limitations": [
            "Intervals describe marginal player-level realized-points uncertainty.",
            "Intervals are symmetric around an unchanged deterministic point projection.",
            "Position groups use pooled fallback when their calibration sample is too small.",
            "Player dependence and cross-player correlation are not modeled.",
            "No Monte Carlo scenarios or risk-aware optimization objective are produced.",
            "Opening gameweeks use their separate carry-over and fitted-price-prior workflow.",
            "The 2025-26 season was used by earlier sprint benchmarks and is not a pristine "
            "final test set; this run must not tune the uncertainty contract from its outcomes.",
        ],
    }


def _markdown(report: dict[str, object]) -> str:
    provenance = report["provenance"]
    configuration = report["configuration"]
    calibration = report["calibration"]
    holdout = report["holdout"]
    assert isinstance(provenance, dict)
    assert isinstance(configuration, dict)
    assert isinstance(calibration, dict)
    assert isinstance(holdout, dict)
    groups = calibration["groups"]
    metrics = holdout["metrics"]
    group_metrics = holdout["group_metrics"]
    assert isinstance(groups, dict)
    assert isinstance(metrics, dict)
    assert isinstance(group_metrics, dict)

    lines = [
        "# Projection uncertainty benchmark",
        "",
        f"Generated at `{report['created_utc']}` by `python -m scripts.run_uncertainty_benchmark`.",
        "",
        "## Provenance",
        "",
        f"- Repository commit: `{provenance['repository_commit']}`",
        f"- Working tree dirty: `{str(provenance['working_tree_dirty']).lower()}`",
        f"- Archive: `{provenance['archive_repository']}@{provenance['archive_commit']}`",
        f"- Manifest SHA-256: `{provenance['archive_manifest_sha256']}`",
        f"- Feature contract: `{provenance['feature_generation_contract_version']}`",
        f"- Baseline form window: `{provenance['baseline_form_window']}` completed matches",
        f"- Uncertainty contract: `{provenance['uncertainty_contract_version']}`",
        f"- Calibration fingerprint: `{provenance['calibration_fingerprint']}`",
        "",
        "## Configuration",
        "",
        f"- Development seasons: `{', '.join(configuration['development_seasons'])}`",
        f"- Locked holdout: `{configuration['holdout_season']}`",
        f"- Confidence level: `{configuration['confidence_level']}`",
        f"- Minimum pooled observations: `{configuration['min_pooled_observations']}`",
        f"- Minimum group observations: `{configuration['min_group_observations']}`",
        f"- Pooled calibration observations: `{calibration['pooled_observations']}`",
        "",
        "## Holdout metrics",
        "",
        "| Population | Observations | Coverage | Mean width | MAE | RMSE | Mean error |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
        (
            f"| All | {metrics['observations']} | {float(metrics['empirical_coverage']):.6f} | "
            f"{float(metrics['mean_interval_width']):.6f} | "
            f"{float(metrics['mean_absolute_error']):.6f} | "
            f"{float(metrics['root_mean_squared_error']):.6f} | "
            f"{float(metrics['mean_error']):.6f} |"
        ),
    ]
    for position in sorted(group_metrics):
        item = group_metrics[position]
        assert isinstance(item, dict)
        lines.append(
            f"| {position} | {item['observations']} | "
            f"{float(item['empirical_coverage']):.6f} | "
            f"{float(item['mean_interval_width']):.6f} | "
            f"{float(item['mean_absolute_error']):.6f} | "
            f"{float(item['root_mean_squared_error']):.6f} | "
            f"{float(item['mean_error']):.6f} |"
        )

    lines.extend(
        [
            "",
            "## Calibration groups",
            "",
            "| Position | Source | Group n | Effective n | Stddev | Radius | Rank |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for position in sorted(groups):
        group = groups[position]
        assert isinstance(group, dict)
        lines.append(
            f"| {position} | {group['source']} | {group['group_observations']} | "
            f"{group['calibration_observations']} | "
            f"{float(group['residual_stddev']):.6f} | "
            f"{float(group['interval_radius']):.6f} | {group['conformal_rank']} |"
        )

    lines.extend(["", "## Limitations", ""])
    lines.extend(f"- {item}" for item in report["limitations"])
    return "\n".join(lines) + "\n"


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def main() -> int:
    """Run the development fit and locked holdout without any holdout refit."""

    arguments = _parse_arguments()
    if not arguments.archive_root.is_dir():
        print(
            f"Archive not found at {arguments.archive_root}.\n"
            "Run 'python -m scripts.fetch_historical_data' first."
        )
        return 1

    config = UncertaintyConfig(
        confidence_level=arguments.confidence_level,
        min_pooled_observations=arguments.min_pooled_observations,
        min_group_observations=arguments.min_group_observations,
    )
    panel = build_panel(arguments.archive_root)
    development_folds = build_walk_forward_folds(
        panel,
        seasons=config.development_seasons,
        min_prior_gameweeks_in_season=1,
        projection_builder=make_baseline_projection_builder(form_window=BASELINE_FORM_WINDOW),
    )
    calibration = fit_projection_uncertainty(development_folds, config)
    holdout_folds = build_walk_forward_folds(
        panel,
        seasons=(config.holdout_season,),
        min_prior_gameweeks_in_season=1,
        projection_builder=make_baseline_projection_builder(form_window=BASELINE_FORM_WINDOW),
    )
    result = evaluate_projection_uncertainty(holdout_folds, calibration)

    created_utc = datetime.now(UTC).isoformat(timespec="seconds")
    report = _build_report(result, panel_rows=len(panel), created_utc=created_utc)
    markdown = _markdown(report)
    _write(arguments.json_output, json.dumps(report, indent=2, sort_keys=True) + "\n")
    _write(arguments.markdown_output, markdown)
    print(markdown)
    print(f"JSON: {arguments.json_output}")
    print(f"Markdown: {arguments.markdown_output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
