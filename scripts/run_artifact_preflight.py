"""Validate residual-export artifacts before any measurement run consumes them.

    python -m scripts.run_artifact_preflight \
        --table artifacts/candidate.csv \
        --manifest artifacts/candidate.manifest.json \
        --reference-table artifacts/reference.csv \
        --reference-manifest artifacts/reference.manifest.json \
        --json-output artifacts/preflight.json

A run with only ``--table``/``--manifest`` validates one export. Adding both
``--reference-table`` and ``--reference-manifest`` also validates the reference export
and the pairing rule between the two. The exit code is 0 only when every check in
every report passed, so the command can gate an automated handoff.
"""

import argparse
import json
import sys
from collections.abc import Mapping
from pathlib import Path

import pandas as pd

from squadopt.data.errors import DataError
from squadopt.preflight import (
    PreflightExpectations,
    PreflightReport,
    compute_table_sha256,
    preflight_report_to_dict,
    preflight_report_to_markdown,
    run_export_pair_preflight,
    run_residual_export_preflight,
)


def _read_table(path: Path) -> pd.DataFrame:
    if not path.is_file():
        raise DataError(f"Residual table file does not exist: {path}.")
    suffix = path.suffix.lower()
    try:
        if suffix == ".csv":
            return pd.read_csv(path)
        if suffix in {".parquet", ".pq"}:
            return pd.read_parquet(path)
    except (OSError, ValueError, ImportError) as error:
        raise DataError(f"Could not read residual table {path}: {error}") from error
    raise DataError(f"Residual table {path} must be CSV or Parquet.")


def _read_manifest(path: Path) -> Mapping[str, object]:
    if not path.is_file():
        raise DataError(f"Manifest file does not exist: {path}.")
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise DataError(f"Could not read manifest {path}: {error}") from error
    if not isinstance(document, dict):
        raise DataError(f"Manifest {path} must contain a JSON object.")
    return document


def _expectations(arguments: argparse.Namespace) -> PreflightExpectations | None:
    seasons: tuple[str, ...] | None = None
    if arguments.expect_seasons:
        seasons = tuple(season.strip() for season in str(arguments.expect_seasons).split(","))
    opening: bool | None = None
    if arguments.expect_opening is not None:
        opening = arguments.expect_opening == "true"
    values = (
        arguments.expect_fold_count,
        arguments.expect_row_count,
        seasons,
        arguments.expect_objective,
        arguments.expect_commit,
        arguments.expect_snapshot,
        opening,
    )
    if all(value is None for value in values):
        return None
    return PreflightExpectations(
        fold_count=arguments.expect_fold_count,
        row_count=arguments.expect_row_count,
        development_seasons=seasons,
        evaluation_objective=arguments.expect_objective,
        repository_commit=arguments.expect_commit,
        dataset_snapshot_id=arguments.expect_snapshot,
        opening_gameweeks_included=opening,
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Validate residual-export tables and manifests against the "
            "oos_residual_export_v1 contract before a measurement run."
        )
    )
    parser.add_argument("--table", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--reference-table")
    parser.add_argument("--reference-manifest")
    parser.add_argument("--expect-fold-count", type=int)
    parser.add_argument("--expect-row-count", type=int)
    parser.add_argument("--expect-seasons", help="Comma-separated season names.")
    parser.add_argument("--expect-objective")
    parser.add_argument("--expect-commit")
    parser.add_argument("--expect-snapshot")
    parser.add_argument("--expect-opening", choices=("true", "false"))
    parser.add_argument("--json-output")
    arguments = parser.parse_args()

    pair_inputs = (arguments.reference_table, arguments.reference_manifest)
    if any(pair_inputs) and not all(pair_inputs):
        print("Provide both --reference-table and --reference-manifest, or neither.")
        return 2

    try:
        expectations = _expectations(arguments)
        table_path = Path(arguments.table)
        table = _read_table(table_path)
        manifest = _read_manifest(Path(arguments.manifest))
        reports: list[PreflightReport] = [
            run_residual_export_preflight(
                table,
                manifest,
                table_sha256=compute_table_sha256(table_path),
                expectations=expectations,
                artifact_label=table_path.name,
            )
        ]
        if all(pair_inputs):
            reference_path = Path(arguments.reference_table)
            reference_table = _read_table(reference_path)
            reference_manifest = _read_manifest(Path(arguments.reference_manifest))
            reports.insert(
                0,
                run_residual_export_preflight(
                    reference_table,
                    reference_manifest,
                    table_sha256=compute_table_sha256(reference_path),
                    expectations=expectations,
                    artifact_label=reference_path.name,
                ),
            )
            reports.append(
                run_export_pair_preflight(
                    reference_table,
                    reference_manifest,
                    table,
                    manifest,
                    artifact_label=f"{reference_path.name} vs {table_path.name}",
                )
            )
    except DataError as error:
        print(f"Could not run artifact preflight:\n  {error}")
        return 1

    for report in reports:
        print(preflight_report_to_markdown(report))

    if arguments.json_output:
        destination = Path(arguments.json_output)
        destination.parent.mkdir(parents=True, exist_ok=True)
        document = {
            "reports": [preflight_report_to_dict(report) for report in reports],
            "passed": all(report.passed for report in reports),
        }
        destination.write_text(
            json.dumps(document, indent=2, sort_keys=True, allow_nan=False) + "\n",
            encoding="utf-8",
        )
        print(f"Wrote {destination}")

    return 0 if all(report.passed for report in reports) else 1


if __name__ == "__main__":
    sys.exit(main())
