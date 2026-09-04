"""Measure calendar-blind and calendar-aware residual regimes on matched rows.

    python -m scripts.run_calendar_recalibration \
        --reference-residuals artifacts/calendar_blind.csv \
        --candidate-residuals artifacts/calendar_aware.csv \
        --json-output artifacts/calendar_recalibration.json \
        --markdown-output artifacts/calendar_recalibration.md

The default mode preserves the residual-measurement artifact. ``--time-aware`` adds a
chronological scale/conformal/evaluation split, held-out interval coverage, player-adaptive
scales, and scenario-component comparisons. Neither mode infers opening-gameweek uncertainty.

Passing ``--reference-manifest`` and ``--candidate-manifest`` runs the artifact preflight
(``artifact_preflight_v1``) before anything is measured: both exports and their pairing are
checked against ``oos_residual_export_v1``, and a single failed finding refuses the
measurement instead of producing a report from an artifact that violates its contract.
"""

import argparse
import json
import sys
from collections.abc import Mapping
from pathlib import Path

import pandas as pd

from squadopt.data.errors import DataError
from squadopt.data.sources.vaastav import build_fixture_panel, load_team_codes
from squadopt.preflight import (
    PreflightReport,
    compute_table_sha256,
    preflight_report_to_markdown,
    run_export_pair_preflight,
    run_residual_export_preflight,
)
from squadopt.recalibration import (
    RecalibrationConfig,
    TimeAwareRecalibrationConfig,
    measure_calendar_recalibration,
    recalibration_to_dict,
    recalibration_to_markdown,
    run_time_aware_recalibration,
    time_aware_recalibration_to_dict,
    time_aware_recalibration_to_markdown,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
ARCHIVE_ROOT = REPOSITORY_ROOT / "data" / "raw" / "vaastav-fpl"


def _read_table(path: Path) -> pd.DataFrame:
    if not path.is_file():
        raise DataError(f"Residual file does not exist: {path}.")
    suffix = path.suffix.lower()
    try:
        if suffix == ".csv":
            return pd.read_csv(path)
        if suffix in {".parquet", ".pq"}:
            return pd.read_parquet(path)
    except (OSError, ValueError, ImportError) as error:
        raise DataError(f"Could not read residual file {path}: {error}") from error
    raise DataError(f"Residual file {path} must be CSV or Parquet.")


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


def _preflight_gate(
    reference_table: pd.DataFrame,
    reference_path: Path,
    reference_manifest: Mapping[str, object],
    candidate_table: pd.DataFrame,
    candidate_path: Path,
    candidate_manifest: Mapping[str, object],
) -> bool:
    """Print every preflight report and return whether measurement may proceed."""

    reports: tuple[PreflightReport, ...] = (
        run_residual_export_preflight(
            reference_table,
            reference_manifest,
            table_sha256=compute_table_sha256(reference_path),
            artifact_label=reference_path.name,
        ),
        run_residual_export_preflight(
            candidate_table,
            candidate_manifest,
            table_sha256=compute_table_sha256(candidate_path),
            artifact_label=candidate_path.name,
        ),
        run_export_pair_preflight(
            reference_table,
            reference_manifest,
            candidate_table,
            candidate_manifest,
            artifact_label=f"{reference_path.name} vs {candidate_path.name}",
        ),
    )
    for report in reports:
        print(preflight_report_to_markdown(report))
    return all(report.passed for report in reports)


def _seasons(frame: pd.DataFrame) -> tuple[str, ...]:
    if "season" not in frame.columns:
        raise DataError("Residual files must carry a 'season' column.")
    seasons = tuple(sorted({str(value).strip() for value in frame["season"].dropna()}))
    if not seasons or any(not season for season in seasons):
        raise DataError("Residual files must carry non-empty season values.")
    return seasons


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Measure matched calendar-blind and calendar-aware residual regimes, with "
            "an optional chronological recalibration study."
        )
    )
    parser.add_argument("--reference-residuals", required=True)
    parser.add_argument("--candidate-residuals", required=True)
    parser.add_argument("--reference-manifest")
    parser.add_argument("--candidate-manifest")
    parser.add_argument("--reference-label", default="calendar_blind_baseline")
    parser.add_argument("--candidate-label", default="calendar_aware_production")
    parser.add_argument("--archive-root", default=str(ARCHIVE_ROOT))
    parser.add_argument("--time-aware", action="store_true")
    parser.add_argument("--confidence-level", type=float, default=0.90)
    parser.add_argument("--scale-training-fraction", type=float, default=0.40)
    parser.add_argument("--conformal-calibration-fraction", type=float, default=0.30)
    parser.add_argument("--min-position-observations", type=int, default=30)
    parser.add_argument("--min-player-observations", type=int, default=5)
    parser.add_argument("--shrinkage-observations", type=float, default=10.0)
    parser.add_argument("--minimum-scale", type=float, default=0.25)
    parser.add_argument("--json-output")
    parser.add_argument("--markdown-output")
    arguments = parser.parse_args()

    manifest_inputs = (arguments.reference_manifest, arguments.candidate_manifest)
    if any(manifest_inputs) and not all(manifest_inputs):
        print("Provide both --reference-manifest and --candidate-manifest, or neither.")
        return 2

    try:
        settings = RecalibrationConfig(
            reference_candidate=arguments.reference_label,
            candidate=arguments.candidate_label,
        )
        reference_path = Path(arguments.reference_residuals)
        candidate_path = Path(arguments.candidate_residuals)
        reference_table = _read_table(reference_path)
        candidate_table = _read_table(candidate_path)
        if all(manifest_inputs):
            gate_passed = _preflight_gate(
                reference_table,
                reference_path,
                _read_manifest(Path(arguments.reference_manifest)),
                candidate_table,
                candidate_path,
                _read_manifest(Path(arguments.candidate_manifest)),
            )
            if not gate_passed:
                print(
                    "Artifact preflight failed; the residual exports were not measured. "
                    "Fix the artifacts and rerun."
                )
                return 1
        reference = reference_table.assign(candidate=settings.reference_candidate)
        candidate = candidate_table.assign(candidate=settings.candidate)
        residuals = pd.concat([reference, candidate], ignore_index=True)
        seasons = _seasons(residuals)
        fixtures = build_fixture_panel(arguments.archive_root, seasons=seasons)
        team_codes = pd.concat(
            [
                load_team_codes(arguments.archive_root, season).assign(season=season)
                for season in seasons
            ],
            ignore_index=True,
        )
        if arguments.time_aware:
            study_config = TimeAwareRecalibrationConfig(
                residual_config=settings,
                confidence_level=arguments.confidence_level,
                scale_training_fraction=arguments.scale_training_fraction,
                conformal_calibration_fraction=(arguments.conformal_calibration_fraction),
                min_position_observations=arguments.min_position_observations,
                min_player_observations=arguments.min_player_observations,
                shrinkage_observations=arguments.shrinkage_observations,
                minimum_scale=arguments.minimum_scale,
            )
            study = run_time_aware_recalibration(
                residuals,
                fixtures,
                team_codes,
                study_config,
            )
            document = time_aware_recalibration_to_dict(study)
            markdown = time_aware_recalibration_to_markdown(study)
        else:
            measurement = measure_calendar_recalibration(
                residuals,
                fixtures,
                team_codes,
                settings,
            )
            document = recalibration_to_dict(measurement)
            markdown = recalibration_to_markdown(measurement)
    except DataError as error:
        print(f"Could not measure calendar recalibration:\n  {error}")
        return 1

    print(markdown)
    if arguments.json_output:
        destination = Path(arguments.json_output)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(
            json.dumps(document, indent=2, sort_keys=True, allow_nan=False) + "\n",
            encoding="utf-8",
        )
        print(f"Wrote {destination}")
    if arguments.markdown_output:
        destination = Path(arguments.markdown_output)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(markdown, encoding="utf-8")
        print(f"Wrote {destination}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
