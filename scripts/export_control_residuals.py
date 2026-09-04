"""Export the deterministic control regime's out-of-sample residuals.

    python -m scripts.export_control_residuals \
        --output-dir artifacts/residuals \
        --summary-output docs/control_residual_export.md

Builds the `oos_residual_export_v1` residual table for the operational control
(deterministic baseline) on the chronological development folds, writes the CSV and
its manifest, and validates both with the artifact preflight before reporting success.
The table itself stays local (the repository is not a data store); the committed
record is the summary document carrying the manifest and the preflight verdict.

This export is control-regime evidence for the uncertainty/scenario/risk layers. It is
not the #43 candidate export, which remains the prediction side's deliverable.
"""

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from scripts._experiment_cli import (
    DEFAULT_ARCHIVE_ROOT,
    REPOSITORY_ROOT,
    artifact_metadata,
    write_json,
    write_text,
)

from squadopt.backtest.export_precision import write_export_table
from squadopt.data.sources.vaastav import ARCHIVE_COMMIT, build_panel
from squadopt.experiments import (
    ExperimentError,
    PolicyObjectiveConfig,
    build_control_residual_table,
    control_residual_manifest,
)
from squadopt.preflight import (
    compute_table_sha256,
    preflight_report_to_markdown,
    run_residual_export_preflight,
)


def _parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive-root", type=Path, default=DEFAULT_ARCHIVE_ROOT)
    parser.add_argument("--form-window", type=int, default=5)
    parser.add_argument("--candidate-label", default=None)
    parser.add_argument("--table-name", default="control_residuals")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=REPOSITORY_ROOT / "artifacts" / "residuals",
    )
    parser.add_argument(
        "--summary-output",
        type=Path,
        default=REPOSITORY_ROOT / "docs" / "control_residual_export.md",
    )
    return parser.parse_args()


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
    panel = build_panel(archive_root)
    metadata = artifact_metadata(panel_rows=len(panel), created_utc=created_utc)
    provenance = metadata["provenance"]
    assert isinstance(provenance, dict)

    try:
        table = build_control_residual_table(
            panel,
            PolicyObjectiveConfig(),
            form_window=arguments.form_window,
        )
    except ExperimentError as error:
        print(f"Could not build the control residual export:\n  {error}")
        return 1

    output_dir: Path = arguments.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    table_name = str(arguments.table_name)
    table_path = output_dir / f"{table_name}.csv"
    write_export_table(table, table_path)
    table_sha256 = compute_table_sha256(table_path)
    label_override: dict[str, str] = (
        {"candidate_label": str(arguments.candidate_label)}
        if arguments.candidate_label is not None
        else {}
    )
    manifest = control_residual_manifest(
        table,
        form_window=arguments.form_window,
        repository_commit=str(provenance["repository_commit"]),
        dataset_snapshot_id=f"vaastav-fpl@{ARCHIVE_COMMIT}",
        table_sha256=table_sha256,
        created_at_utc=created_utc,
        **label_override,
    )
    manifest_path = output_dir / f"{table_name}.manifest.json"
    write_json(manifest_path, dict(manifest))

    report = run_residual_export_preflight(
        table,
        manifest,
        table_sha256=table_sha256,
        artifact_label=table_path.name,
    )
    print(preflight_report_to_markdown(report))
    if not report.passed:
        print("Preflight failed; the export does not satisfy its own contract.")
        return 1

    summary = "\n".join(
        [
            "# Control Residual Export",
            "",
            "Out-of-sample residuals of the operational control (deterministic "
            "baseline) on the chronological development folds, produced from this "
            "repository and validated by the artifact preflight. The table stays "
            "local; this document is the committed record.",
            "",
            "This is control-regime evidence for the uncertainty/scenario/risk "
            "layers. It is **not** the #43 candidate export, which remains the "
            "prediction side's deliverable.",
            "",
            "## Manifest",
            "",
            "```json",
            json.dumps(dict(manifest), indent=2, sort_keys=True),
            "```",
            "",
            "## Preflight",
            "",
            f"- Verdict: {'PASSED' if report.passed else 'FAILED'} ({len(report.findings)} checks)",
            f"- Table file: `{table_path.as_posix()}` (local, not committed)",
            f"- Manifest file: `{manifest_path.as_posix()}` (local, not committed)",
            "",
            "## Reproduction",
            "",
            "```powershell",
            ".venv\\Scripts\\python -m scripts.export_control_residuals",
            "```",
            "",
            f"Recorded at commit `{provenance['repository_commit']}` on {created_utc}.",
        ]
    )
    write_text(arguments.summary_output, summary + "\n")

    print(f"Wrote {table_path}")
    print(f"Wrote {manifest_path}")
    print(f"Wrote {arguments.summary_output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
