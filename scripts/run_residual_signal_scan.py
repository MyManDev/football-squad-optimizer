"""Scan the control's residuals for enrichment signals the archive holds but no model reads.

    python -m scripts.run_residual_signal_scan \
        --residuals artifacts/residuals-verify/control_residuals.csv

Reads the raw archive's enrichment columns (expected goal involvement, goals and assists,
ownership, the source's own point expectation) for the development seasons, builds
strictly lagged covariates, joins them to the control's out-of-sample residual export, and
reports how the residual moves across quartiles of each covariate — the same question the
opponent-strength signal measurement asked, for the signals a data enrichment would add.

Measurement only: no feature is added, no contract changes, no model is promoted, and the
locked holdout is never read. The result is evidence for the prediction side's feature
queue, not a feature.
"""

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
from scripts._experiment_cli import (
    DEFAULT_ARCHIVE_ROOT,
    REPOSITORY_ROOT,
    artifact_metadata,
    write_json,
    write_text,
)

from squadopt.data.sources.vaastav import build_panel
from squadopt.experiments import ExperimentError
from squadopt.experiments.residual_signal_scan import (
    ResidualSignalScan,
    build_lagged_covariates,
    load_enrichment_rows,
    scan_residual_signals,
    scan_to_markdown,
)
from squadopt.preflight import compute_table_sha256

DEFAULT_SEASONS = "2021-22,2022-23,2023-24,2024-25"


def _parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--residuals", type=Path, required=True)
    parser.add_argument("--archive-root", type=Path, default=DEFAULT_ARCHIVE_ROOT)
    parser.add_argument("--seasons", default=DEFAULT_SEASONS)
    parser.add_argument("--window", type=int, default=6)
    parser.add_argument("--min-rows", type=int, default=1_000)
    parser.add_argument(
        "--json-output",
        type=Path,
        default=REPOSITORY_ROOT / "docs" / "residual_signal_scan.json",
    )
    parser.add_argument(
        "--markdown-output",
        type=Path,
        default=REPOSITORY_ROOT / "docs" / "residual_signal_scan.md",
    )
    return parser.parse_args()


def _document(scan: ResidualSignalScan) -> dict[str, object]:
    return {
        "contract_version": scan.contract_version,
        "window": scan.window,
        "diagnostics": dict(scan.diagnostics),
        "signals": [
            {
                "covariate": signal.covariate,
                "description": signal.description,
                "seasons_present": list(signal.seasons_present),
                "rows": signal.rows,
                "residual_spread": signal.residual_spread,
                "realized_spread": signal.realized_spread,
                "surviving_ratio": signal.surviving_ratio,
                "monotone_residual": signal.monotone_residual,
                "bins": [
                    {
                        "label": entry.label,
                        "observations": entry.observations,
                        "mean_covariate": entry.mean_covariate,
                        "mean_realized_points": entry.mean_realized_points,
                        "mean_residual": entry.mean_residual,
                    }
                    for entry in signal.bins
                ],
            }
            for signal in scan.signals
        ],
        "measurement_only": True,
        "locked_holdout_accessed": False,
        "automatic_promotion": False,
    }


def main() -> int:
    arguments = _parse_arguments()
    if not arguments.residuals.is_file():
        print(f"Residual export not found at {arguments.residuals}.")
        return 1
    if not arguments.archive_root.is_dir():
        print(f"Archive not found at {arguments.archive_root}.")
        return 1
    seasons = tuple(value.strip() for value in str(arguments.seasons).split(","))
    if "2025-26" in seasons:
        print("2025-26 is the locked holdout and may not be scanned.")
        return 1

    created_utc = datetime.now(UTC).isoformat(timespec="seconds")
    residuals = pd.read_csv(arguments.residuals)
    residual_seasons = sorted({str(value) for value in residuals["season"].tolist()})
    if any(season not in seasons for season in residual_seasons):
        print(f"Residual export covers {residual_seasons}, outside --seasons {list(seasons)}.")
        return 1
    panel = build_panel(arguments.archive_root)
    panel = panel.loc[panel["season"].isin(seasons)].copy()
    try:
        raw = load_enrichment_rows(arguments.archive_root, seasons)
        covariates = build_lagged_covariates(raw, panel, window=arguments.window)
        scan = scan_residual_signals(
            residuals, covariates, window=arguments.window, min_rows=arguments.min_rows
        )
    except ExperimentError as error:
        print(f"Could not scan residual signals:\n  {error}")
        return 1

    document = {
        **artifact_metadata(panel_rows=len(panel), created_utc=created_utc),
        **_document(scan),
        "residual_input": {
            "path": arguments.residuals.as_posix(),
            "table_sha256": compute_table_sha256(arguments.residuals),
            "rows": len(residuals),
        },
    }
    markdown = scan_to_markdown(scan)
    write_json(arguments.json_output, document)
    write_text(arguments.markdown_output, markdown)
    print(markdown)
    print(f"Wrote {arguments.json_output}")
    print(f"Wrote {arguments.markdown_output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
