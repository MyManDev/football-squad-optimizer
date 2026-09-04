"""Measure live calibration from the season ledger's settled gameweeks.

    python -m scripts.run_live_calibration --season 2026-27
    python -m scripts.run_live_calibration --season 2026-27 \
        --residuals artifacts/residuals/control_residuals.csv \
        --residuals-manifest artifacts/residuals/control_residuals.manifest.json

The season ledger is the only out-of-sample series produced under real conditions:
each decision was frozen before kickoff and each outcome read from a later immutable
capture. This report compares that live series against the development references —
the selection-optimism gap per starter, the captain's gap, player-level MAE/bias —
and, when an out-of-sample residual export is supplied (validated by the artifact
preflight), the live coverage of empirical per-position residual intervals.

The report refuses to run before any gameweek has settled: live calibration is
measured on real outcomes or not at all. A few gameweeks is a small sample; the
report says so rather than pretending otherwise.

Measurement only: no projection, control, or ledger entry changes.
"""

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
from scripts._experiment_cli import REPOSITORY_ROOT, _git_revision, write_json, write_text

from squadopt.data.errors import DataError
from squadopt.live import (
    LiveCalibrationResult,
    calibration_markdown,
    measure_live_calibration,
)
from squadopt.preflight import (
    compute_table_sha256,
    preflight_report_to_markdown,
    run_residual_export_preflight,
)

DEFAULT_LEDGER_ROOT = REPOSITORY_ROOT / "data" / "ledger"
DEFAULT_SNAPSHOT_ROOT = REPOSITORY_ROOT / "data" / "snapshots"


def _parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season", required=True)
    parser.add_argument("--ledger-root", type=Path, default=DEFAULT_LEDGER_ROOT)
    parser.add_argument("--snapshot-root", type=Path, default=DEFAULT_SNAPSHOT_ROOT)
    parser.add_argument("--residuals", type=Path, help="OOS residual export CSV (optional)")
    parser.add_argument("--residuals-manifest", type=Path)
    parser.add_argument("--interval-lower-quantile", type=float, default=0.05)
    parser.add_argument("--interval-upper-quantile", type=float, default=0.95)
    parser.add_argument(
        "--json-output",
        type=Path,
        help="default docs/live_calibration_gw<NN>.json for the latest settled gameweek",
    )
    parser.add_argument(
        "--markdown-output",
        type=Path,
        help="default docs/live_calibration_gw<NN>.md for the latest settled gameweek",
    )
    return parser.parse_args()


def _result_document(
    result: LiveCalibrationResult, residual_provenance: dict[str, object] | None
) -> dict[str, object]:
    return {
        "contract_version": result.contract_version,
        "season": result.season,
        "settled_gameweeks": result.settled_gameweeks,
        "historical_references": {
            "xi_optimism_per_starter": result.historical_xi_optimism_per_starter,
            "captain_optimism": result.historical_captain_optimism,
        },
        "aggregate": {
            "mean_xi_error": result.mean_xi_error,
            "mean_xi_optimism_per_starter": result.mean_xi_optimism_per_starter,
            "mean_captain_optimism": result.mean_captain_optimism,
            "roster_mean_error": result.roster_mean_error,
            "roster_mae": result.roster_mae,
            "interval_rule": result.interval_rule,
            "interval_nominal_coverage": result.interval_nominal_coverage,
            "interval_live_coverage": result.interval_live_coverage,
        },
        "residual_input": residual_provenance,
        "recommendation_only": True,
        "locked_holdout_accessed": False,
        "automatic_promotion": False,
        "gameweeks": [
            {
                "gameweek": row.gameweek,
                "source_snapshot_id": row.source_snapshot_id,
                "projected_xi_score": row.projected_xi_score,
                "realized_xi_score": row.realized_xi_score,
                "xi_error": row.xi_error,
                "xi_optimism_per_starter": row.xi_optimism_per_starter,
                "captain_optimism": row.captain_optimism,
                "roster_players_scored": row.roster_players_scored,
                "roster_mean_error": row.roster_mean_error,
                "roster_mae": row.roster_mae,
                "interval_players": row.interval_players,
                "interval_coverage": row.interval_coverage,
            }
            for row in result.rows
        ],
    }


def main() -> int:
    arguments = _parse_arguments()

    residual_history: pd.DataFrame | None = None
    residual_provenance: dict[str, object] | None = None
    if arguments.residuals is not None:
        residuals_path: Path = arguments.residuals
        if not residuals_path.is_file():
            print(f"Residual history not found at {residuals_path}.")
            return 1
        residual_history = pd.read_csv(residuals_path)
        residual_provenance = {
            "path": residuals_path.as_posix(),
            "table_sha256": compute_table_sha256(residuals_path),
            "rows": len(residual_history),
        }
        if arguments.residuals_manifest is not None:
            manifest = json.loads(arguments.residuals_manifest.read_text(encoding="utf-8"))
            if not isinstance(manifest, dict):
                print(f"Manifest {arguments.residuals_manifest} must contain a JSON object.")
                return 1
            report = run_residual_export_preflight(
                residual_history,
                manifest,
                table_sha256=str(residual_provenance["table_sha256"]),
                artifact_label=residuals_path.name,
            )
            print(preflight_report_to_markdown(report))
            if not report.passed:
                print("Residual preflight failed; intervals will not be built on this input.")
                return 1
            residual_provenance["candidate_label"] = manifest.get("candidate_label")
            residual_provenance["preflight_passed"] = True

    try:
        result = measure_live_calibration(
            arguments.ledger_root,
            arguments.season,
            snapshot_root=arguments.snapshot_root,
            residual_history=residual_history,
            interval_lower_quantile=arguments.interval_lower_quantile,
            interval_upper_quantile=arguments.interval_upper_quantile,
        )
    except DataError as error:
        print(f"Live calibration could not be measured:\n  {error}")
        return 1

    latest = result.rows[-1].gameweek
    json_output: Path = arguments.json_output or (
        REPOSITORY_ROOT / "docs" / f"live_calibration_gw{latest:02d}.json"
    )
    markdown_output: Path = arguments.markdown_output or (
        REPOSITORY_ROOT / "docs" / f"live_calibration_gw{latest:02d}.md"
    )
    revision, dirty = _git_revision()
    document = {
        "created_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "provenance": {
            "repository_commit": revision,
            "working_tree_dirty": dirty,
            "ledger_root": arguments.ledger_root.as_posix(),
            "snapshot_root": arguments.snapshot_root.as_posix(),
        },
        **_result_document(result, residual_provenance),
    }
    markdown = calibration_markdown(result)
    write_json(json_output, document)
    write_text(markdown_output, markdown)

    print(markdown)
    print(f"Wrote {json_output}")
    print(f"Wrote {markdown_output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
