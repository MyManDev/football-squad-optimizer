"""Measure a fixture-group axis in the conformal calibration on the control's residuals.

    python -m scripts.run_fixture_group_conformal \\
        --residuals artifacts/residuals-verify/control_residuals.csv \\
        --manifest artifacts/residuals-verify/control_residuals.manifest.json

The operational calibration groups residuals by position and undercovers double
gameweeks (docs/issue38_calibration_decision.md). This runner attaches the published
calendar to the operational control's out-of-sample residual export (the same fixture
bridge the recalibration study uses), fits position-only and position-by-fixture-group
conformal radii on the earlier folds, and scores both on the later folds, overall and per
fixture group. It changes no calibration contract: it is the measurement a declaration
would rest on. The manifest, when given, must describe the residual table (its SHA-256
is checked) so the numbers are tied to a named export.

Measurement only. The locked 2025-26 holdout is refused.
"""

import argparse
import json
import sys
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
from scripts._experiment_cli import REPOSITORY_ROOT, write_json, write_text

from squadopt.data.errors import DataError
from squadopt.data.sources.vaastav import build_fixture_panel, load_team_codes
from squadopt.features import attach_fixture_features
from squadopt.preflight import compute_table_sha256
from squadopt.uncertainty import (
    FIXTURE_GROUPS,
    FixtureGroupConformalConfig,
    FixtureGroupConformalResult,
    UncertaintyError,
    fit_and_evaluate_fixture_group_conformal,
    fixture_group_conformal_to_dict,
)

ARCHIVE_ROOT = REPOSITORY_ROOT / "data" / "raw" / "vaastav-fpl"
LOCKED_HOLDOUT_SEASON = "2025-26"
POSITIONS = ("GK", "DEF", "MID", "FWD")


def _parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--residuals", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, default=None)
    parser.add_argument("--archive-root", type=Path, default=ARCHIVE_ROOT)
    parser.add_argument("--confidence-level", type=float, default=0.90)
    parser.add_argument("--calibration-fold-fraction", type=float, default=0.60)
    parser.add_argument("--min-group-observations", type=int, default=30)
    parser.add_argument(
        "--json-output",
        type=Path,
        default=REPOSITORY_ROOT / "docs" / "fixture_group_conformal.json",
    )
    parser.add_argument(
        "--markdown-output",
        type=Path,
        default=REPOSITORY_ROOT / "docs" / "fixture_group_conformal.md",
    )
    return parser.parse_args()


def _read_residuals(path: Path) -> pd.DataFrame:
    if not path.is_file():
        raise DataError(f"Residual file does not exist: {path}.")
    return pd.read_csv(path)


def _manifest(path: Path | None, table_path: Path) -> dict[str, object]:
    if path is None:
        return {"manifest": None, "table_sha256_checked": False}
    if not path.is_file():
        raise DataError(f"Manifest does not exist: {path}.")
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, Mapping):
        raise DataError("Manifest must be a JSON object.")
    recorded = str(document.get("table_sha256", ""))
    actual = compute_table_sha256(table_path)
    if recorded != actual:
        raise DataError(
            f"Residual table SHA-256 {actual} does not match the manifest's {recorded}; "
            "the export is not the one the manifest describes."
        )
    return {
        "manifest": {
            key: document.get(key)
            for key in (
                "candidate_label",
                "contract_version",
                "model_name",
                "model_version",
                "feature_contract_version",
                "table_sha256",
                "row_count",
                "fold_count",
                "development_seasons",
                "repository_commit",
            )
        },
        "table_sha256_checked": True,
    }


def _fmt(value: float, digits: int = 4) -> str:
    return f"{value:.{digits}f}"


def _markdown(result: FixtureGroupConformalResult, provenance: Mapping[str, object]) -> str:
    position_only = result.position_metrics
    with_fixture = result.fixture_metrics
    lines = [
        "# Fixture-group conformal calibration on the control's residuals",
        "",
        "Position-only (the operational `projection_uncertainty_v1` grouping) against",
        "position by fixture group (`single`, `double_plus`; pooled fallback per position",
        "under the observation floor), both fitted on the earlier folds and scored on the",
        "later folds of the operational control's out-of-sample residual export. Blank rows",
        "are zero by construction and excluded. Nominal coverage "
        f"{result.config.confidence_level:.2f}. Measurement only; no contract changes here.",
        "",
        f"- Calibration folds: {len(result.calibration_folds)} "
        f"({result.calibration_folds[0]} … {result.calibration_folds[-1]}); "
        f"evaluation folds: {len(result.evaluation_folds)} "
        f"({result.evaluation_folds[0]} … {result.evaluation_folds[-1]}).",
        f"- Rows: {result.diagnostics['calibration_rows']} calibrate, "
        f"{result.diagnostics['evaluation_rows']} evaluate, "
        f"{result.diagnostics['blank_rows_excluded']} blank excluded.",
        f"- Result fingerprint `{result.fingerprint[:16]}…`; "
        f"configuration `{result.config.configuration_fingerprint[:16]}…`.",
        "",
        "## Held-out coverage and width",
        "",
        "| Population | Rows | Position-only coverage | Position-only width "
        "| Fixture-group coverage | Fixture-group width | MAE |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    keys = ["overall", *FIXTURE_GROUPS] + [
        f"{position}/{group}" for group in FIXTURE_GROUPS for position in POSITIONS
    ]
    for key in keys:
        if key not in with_fixture:
            continue
        a = position_only[key]
        b = with_fixture[key]
        lines.append(
            f"| {key} | {b.observations} | {_fmt(a.empirical_coverage)} "
            f"| {a.mean_interval_width:.2f} | {_fmt(b.empirical_coverage)} "
            f"| {b.mean_interval_width:.2f} | {b.mean_absolute_error:.2f} |"
        )
    lines += [
        "",
        "## Calibrated radii",
        "",
        "| Position | Position-only radius (n) | Single radius (n, source) "
        "| Double-plus radius (n, source) |",
        "| --- | ---: | ---: | ---: |",
    ]
    for position in POSITIONS:
        base = result.position_cells[position]
        single = result.fixture_cells[(position, "single")]
        double = result.fixture_cells[(position, "double_plus")]
        lines.append(
            f"| {position} | {base.interval_radius:.2f} ({base.calibration_observations}) "
            f"| {single.interval_radius:.2f} ({single.group_observations}, {single.source}) "
            f"| {double.interval_radius:.2f} ({double.group_observations}, {double.source}) |"
        )
    manifest = provenance.get("manifest")
    lines += ["", "## Provenance", ""]
    if isinstance(manifest, Mapping):
        lines += [
            f"- Residual export: `{manifest.get('candidate_label')}` "
            f"({manifest.get('model_name')}@{manifest.get('model_version')}, "
            f"contract `{manifest.get('contract_version')}`), table SHA-256 "
            f"`{str(manifest.get('table_sha256'))[:16]}…` verified against the file.",
        ]
    else:
        lines += ["- No manifest supplied; the residual table's identity is not verified."]
    lines += [
        "- The 2025-26 holdout was not read.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    arguments = _parse_arguments()
    try:
        table = _read_residuals(arguments.residuals)
        seasons = tuple(sorted({str(value).strip() for value in table["season"].dropna()}))
        if LOCKED_HOLDOUT_SEASON in seasons:
            print(f"{LOCKED_HOLDOUT_SEASON} is the locked holdout and may not be calibrated on.")
            return 1
        provenance = _manifest(arguments.manifest, arguments.residuals)
        fixtures = build_fixture_panel(arguments.archive_root, seasons=seasons)
        team_codes = pd.concat(
            [
                load_team_codes(arguments.archive_root, season).assign(season=season)
                for season in seasons
            ],
            ignore_index=True,
        )
        enriched = attach_fixture_features(table, fixtures, team_codes)
        config = FixtureGroupConformalConfig(
            confidence_level=arguments.confidence_level,
            calibration_fold_fraction=arguments.calibration_fold_fraction,
            min_group_observations=arguments.min_group_observations,
        )
        result = fit_and_evaluate_fixture_group_conformal(enriched, config)
    except (DataError, UncertaintyError) as error:
        print(f"Could not measure the fixture-group conformal calibration:\n  {error}")
        return 1
    document = {
        "created_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "residuals_path": str(arguments.residuals),
        **provenance,
        **fixture_group_conformal_to_dict(result),
        "seasons": list(seasons),
        "measurement_only": True,
        "locked_holdout_accessed": False,
    }
    markdown = _markdown(result, provenance)
    write_json(arguments.json_output, document)
    write_text(arguments.markdown_output, markdown)
    print(markdown)
    print(f"Wrote {arguments.json_output}")
    print(f"Wrote {arguments.markdown_output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
