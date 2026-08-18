"""Export the calendar-aware candidate regime's out-of-sample residuals, and pair them.

    python -m scripts.export_candidate_residuals

Builds the `oos_residual_export_v1` residual table for the calendar-aware candidate on
the chronological development folds, writes the CSV and its manifest, validates both
with the artifact preflight, and — unless told not to — rebuilds the calendar-blind
control export in the same process so the pair can be checked end to end.

Rebuilding the control here is deliberate. The pairing rule requires both manifests to
name the same `repository_commit`, and the committed control record was produced on a
pre-squash branch commit that is not an ancestor of `develop`. Regenerating both at one
commit is the only way the pair check can pass; it costs a second run and removes an
entire class of "which tree produced this" question.

Both tables stay local. The repository is not a data store, and these rows are derived
from third-party data; the committed record is the summary document.
"""

import argparse
import json
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

from squadopt.backtest.candidate_residuals import (
    PREDICTED_POINTS_DECIMALS,
    build_candidate_residual_table,
    candidate_residual_manifest,
    round_for_export,
)
from squadopt.backtest.export_precision import write_export_table
from squadopt.backtest.learned_candidate import (
    LEARNED_RATE_TRAINING_CONTRACT_VERSION,
    make_learned_rate_projection_builder,
)
from squadopt.backtest.production import make_production_projection_builder
from squadopt.data.errors import DataError
from squadopt.data.sources.vaastav import (
    ARCHIVE_COMMIT,
    build_fixture_panel,
    build_panel,
    load_team_codes,
)
from squadopt.experiments import (
    ExperimentError,
    PolicyObjectiveConfig,
    build_control_residual_table,
    control_residual_manifest,
)
from squadopt.features import CrossSeasonConfig
from squadopt.prediction.learned_rate import LearnedRateConfig
from squadopt.prediction.minutes import ExpectedMinutesConfig
from squadopt.prediction.production import ProductionProjectionConfig
from squadopt.preflight import (
    PreflightExpectations,
    compute_table_sha256,
    preflight_report_to_markdown,
    run_export_pair_preflight,
    run_residual_export_preflight,
)

CONTROL_LABEL = "calendar_blind_baseline"

# Two calendar-aware regimes can be exported. ``learned`` is the Issue #43 candidate and
# is what the handoff checklist means by the candidate export, because its manifest must
# carry the declaration's own model identity. ``production`` is the already-measured
# two-stage regime, kept because the #38 recalibration CLI names it by default.
CANDIDATE_REGIMES = {
    "learned": "calendar_aware_learned_rate",
    "production": "calendar_aware_production",
}

# Each regime's training contract, named rather than left implicit because the manifest
# must state one. Both refit the opening price prior on an expanding window; the learned
# candidate additionally refits its rate model there.
TRAINING_CONTRACTS = {
    "learned": LEARNED_RATE_TRAINING_CONTRACT_VERSION,
    "production": "expanding_window_opening_price_prior_v1",
}

# The receiving side's agreed development population. Asserted here so a manifest cannot
# quietly redefine what it claims to cover; a run that produces a different population
# fails loudly rather than handing over a smaller table with a confident manifest.
EXPECTED_FOLD_COUNT = 147
EXPECTED_ROW_COUNT = 101_447

# History the development folds may read as carry-over, but never decide on.
HISTORY_SEASON = "2020-21"
DEVELOPMENT_SEASONS = ("2021-22", "2022-23", "2023-24", "2024-25")


def _parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive-root", type=Path, default=DEFAULT_ARCHIVE_ROOT)
    parser.add_argument(
        "--candidate",
        choices=sorted(CANDIDATE_REGIMES),
        default="learned",
        help="which calendar-aware regime to export",
    )
    parser.add_argument("--window", type=int, default=6, help="candidate rate/appearance window")
    parser.add_argument("--ridge-alpha", type=float, default=1.0)
    parser.add_argument("--control-form-window", type=int, default=5)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=REPOSITORY_ROOT / "artifacts" / "residuals",
    )
    parser.add_argument(
        "--summary-output",
        type=Path,
        default=REPOSITORY_ROOT / "docs" / "candidate_residual_export.md",
    )
    parser.add_argument(
        "--skip-control",
        action="store_true",
        help="do not rebuild the control export; the pair check is then not run",
    )
    return parser.parse_args()


def _write(table: pd.DataFrame, directory: Path, name: str) -> tuple[Path, str]:
    path = directory / f"{name}.csv"
    write_export_table(table, path)
    return path, compute_table_sha256(path)


def main() -> int:
    arguments = _parse_arguments()
    archive_root: Path = arguments.archive_root
    if not archive_root.is_dir():
        print(
            f"Archive not found at {archive_root}.\n"
            "Run 'python -m scripts.fetch_historical_data' first."
        )
        return 1

    created_utc = datetime.now(UTC).isoformat(timespec="seconds")
    loaded = (HISTORY_SEASON, *DEVELOPMENT_SEASONS)
    output_dir: Path = arguments.output_dir

    try:
        panel = build_panel(archive_root, seasons=list(loaded))
        fixtures = build_fixture_panel(archive_root, seasons=list(loaded))
        team_codes = pd.concat(
            [load_team_codes(archive_root, season).assign(season=season) for season in loaded],
            ignore_index=True,
        )
    except DataError as error:
        print(f"Could not read the archive:\n  {error}")
        return 1

    metadata = artifact_metadata(panel_rows=len(panel), created_utc=created_utc)
    provenance = metadata["provenance"]
    assert isinstance(provenance, dict)
    repository_commit = str(provenance["repository_commit"])
    dataset_snapshot_id = f"vaastav-fpl@{ARCHIVE_COMMIT}"

    regime = str(arguments.candidate)
    candidate_label = CANDIDATE_REGIMES[regime]
    window = int(arguments.window)
    projection_config = ProductionProjectionConfig(
        rate_window=window, minutes=ExpectedMinutesConfig(window=window)
    )
    if regime == "learned":
        builder = make_learned_rate_projection_builder(
            fixtures=fixtures,
            team_codes=team_codes,
            config=projection_config,
            learned_config=LearnedRateConfig(
                window=window, ridge_alpha=float(arguments.ridge_alpha)
            ),
            cross_season=CrossSeasonConfig(),
        )
    else:
        builder = make_production_projection_builder(
            fixtures=fixtures,
            team_codes=team_codes,
            config=projection_config,
            cross_season=CrossSeasonConfig(),
        )

    print(f"Building the {candidate_label!r} export over {len(DEVELOPMENT_SEASONS)} seasons...")
    try:
        candidate_table, identity = build_candidate_residual_table(
            panel, builder, seasons=DEVELOPMENT_SEASONS
        )
    except DataError as error:
        print(f"Could not build the candidate residual export:\n  {error}")
        return 1

    table_stem = f"{regime}_candidate_residuals"
    candidate_path, candidate_sha256 = _write(candidate_table, output_dir, table_stem)
    candidate_manifest = candidate_residual_manifest(
        candidate_table,
        identity,
        candidate_label=candidate_label,
        training_contract_version=TRAINING_CONTRACTS[regime],
        repository_commit=repository_commit,
        dataset_snapshot_id=dataset_snapshot_id,
        table_sha256=candidate_sha256,
        created_at_utc=created_utc,
    )
    candidate_manifest = {
        **dict(candidate_manifest),
        "predicted_points_decimals": PREDICTED_POINTS_DECIMALS,
    }
    candidate_manifest_path = output_dir / f"{table_stem}.manifest.json"
    write_json(candidate_manifest_path, dict(candidate_manifest))

    expectations = PreflightExpectations(
        fold_count=EXPECTED_FOLD_COUNT,
        row_count=EXPECTED_ROW_COUNT,
        development_seasons=DEVELOPMENT_SEASONS,
        evaluation_objective="single_gameweek_realized_squad_points_v1",
        repository_commit=repository_commit,
        dataset_snapshot_id=dataset_snapshot_id,
        opening_gameweeks_included=False,
    )
    candidate_report = run_residual_export_preflight(
        candidate_table,
        candidate_manifest,
        table_sha256=candidate_sha256,
        expectations=expectations,
        artifact_label=candidate_path.name,
    )
    print(preflight_report_to_markdown(candidate_report))

    sections = [
        "# Candidate Residual Export",
        "",
        "Out-of-sample residuals of the calendar-aware candidate on the chronological "
        "development folds, produced from this repository and validated by the artifact "
        "preflight. The tables stay local; this document is the committed record.",
        "",
        "This is the candidate half of the recalibration pair. The control half is "
        "rebuilt by the same command so both manifests name one `repository_commit`.",
        "",
        "## Candidate manifest",
        "",
        "```json",
        json.dumps(dict(candidate_manifest), indent=2, sort_keys=True),
        "```",
        "",
        "## Candidate preflight",
        "",
        f"- Verdict: {'PASSED' if candidate_report.passed else 'FAILED'} "
        f"({len(candidate_report.findings)} checks)",
        f"- Table file: `{candidate_path.as_posix()}` (local, not committed)",
        f"- Manifest file: `{candidate_manifest_path.as_posix()}` (local, not committed)",
    ]

    pair_passed = True
    if not arguments.skip_control:
        print(f"Building the {CONTROL_LABEL!r} export at the same commit...")
        try:
            control_table = round_for_export(
                build_control_residual_table(
                    panel,
                    PolicyObjectiveConfig(development_seasons=DEVELOPMENT_SEASONS),
                    form_window=int(arguments.control_form_window),
                )
            )
        except ExperimentError as error:
            print(f"Could not build the control residual export:\n  {error}")
            return 1

        control_path, control_sha256 = _write(control_table, output_dir, "control_residuals")
        control_manifest = control_residual_manifest(
            control_table,
            form_window=int(arguments.control_form_window),
            repository_commit=repository_commit,
            dataset_snapshot_id=dataset_snapshot_id,
            table_sha256=control_sha256,
            created_at_utc=created_utc,
            candidate_label=CONTROL_LABEL,
        )
        control_manifest = {
            **dict(control_manifest),
            "predicted_points_decimals": PREDICTED_POINTS_DECIMALS,
        }
        control_manifest_path = output_dir / "control_residuals.manifest.json"
        write_json(control_manifest_path, dict(control_manifest))

        control_report = run_residual_export_preflight(
            control_table,
            control_manifest,
            table_sha256=control_sha256,
            expectations=expectations,
            artifact_label=control_path.name,
        )
        print(preflight_report_to_markdown(control_report))

        pair_report = run_export_pair_preflight(
            control_table,
            control_manifest,
            candidate_table,
            candidate_manifest,
        )
        print(preflight_report_to_markdown(pair_report))
        pair_passed = control_report.passed and pair_report.passed

        sections += [
            "",
            "## Control manifest (rebuilt at this commit)",
            "",
            "```json",
            json.dumps(dict(control_manifest), indent=2, sort_keys=True),
            "```",
            "",
            "## Control preflight",
            "",
            f"- Verdict: {'PASSED' if control_report.passed else 'FAILED'} "
            f"({len(control_report.findings)} checks)",
            "",
            "## Pair preflight",
            "",
            f"- Verdict: {'PASSED' if pair_report.passed else 'FAILED'} "
            f"({len(pair_report.findings)} checks)",
            f"- Reference table: `{control_path.as_posix()}` (local, not committed)",
            f"- Reference manifest: `{control_manifest_path.as_posix()}` (local, not committed)",
        ]

    sections += [
        "",
        "## Reproduction",
        "",
        "```powershell",
        ".venv\\Scripts\\python -m scripts.export_candidate_residuals",
        "```",
        "",
        f"Recorded at commit `{repository_commit}` on {created_utc}.",
    ]
    write_text(arguments.summary_output, "\n".join(sections) + "\n")

    print(f"Wrote {candidate_path}")
    print(f"Wrote {candidate_manifest_path}")
    print(f"Wrote {arguments.summary_output}")
    if not candidate_report.passed or not pair_passed:
        print("Preflight failed; the export does not satisfy its own contract.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
