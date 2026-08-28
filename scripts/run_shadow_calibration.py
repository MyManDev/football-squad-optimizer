"""Run the Phase 2A player-level shadow calibration against one bound export.

    python -m scripts.run_shadow_calibration \
        --residual-table artifacts/residuals/in_season_residuals.csv \
        --residual-manifest artifacts/residuals/in_season_residuals.manifest.json

Internal measurement only. The result is a ``shadow_calibration_report_v1`` document;
nothing it can say publishes a probability, a percentage or a ``P(...)`` to any
member-facing surface, and the writer refuses a destination under ``web/public``.

The run is create-once: writing the same measurement twice is a replay and is
accepted, while different content at an occupied path is refused rather than
overwritten, so a recorded result cannot be quietly replaced by a later one.
"""

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

import pandas as pd
from scripts._experiment_cli import DEFAULT_ARCHIVE_ROOT, REPOSITORY_ROOT, _git_revision

from squadopt.experiments.residual_manifest import load_residual_source_manifest
from squadopt.experiments.shadow_calibration import (
    ShadowCalibrationConfig,
    replay_identity,
    run_shadow_calibration,
)
from squadopt.experiments.shadow_report import report_to_dict, write_shadow_report
from squadopt.uncertainty.fixture_folds import calendar_from_archive

#: The model this protocol calibrates, named in the pre-registration. It is a
#: constant rather than an argument: a run that could point at another model's
#: residuals is exactly what the #45 rule forbids.
MODEL_NAME: Final = "squadopt-deterministic-baseline"
MODEL_VERSION: Final = "in-season-carry-over-v1"
FEATURE_CONTRACT_VERSION: Final = "in-season-carry-over-features-v1"

#: The prereg's split: fit on 2021-22..2023-24, score 2024-25 frozen.
DEFAULT_CUTOFF_FOLD_ID: Final = "2023-24-gw38"
DEFAULT_OUTPUT: Final = REPOSITORY_ROOT / "docs" / "shadow_calibration_in_season.json"


def _write_once(document: dict[str, object], path: Path) -> str:
    """Write the report, or accept an identical replay, or refuse a conflict."""

    if path.is_file():
        existing = json.loads(path.read_text(encoding="utf-8"))
        if replay_identity(existing) == replay_identity(document):
            return "replay"
        raise SystemExit(
            f"{path} already holds a different measurement. A recorded result is not "
            "overwritten; move or delete it deliberately if it is genuinely superseded."
        )
    return "written"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--residual-table", type=Path, required=True)
    parser.add_argument("--residual-manifest", type=Path, required=True)
    parser.add_argument("--archive-root", type=Path, default=DEFAULT_ARCHIVE_ROOT)
    parser.add_argument("--cutoff-fold-id", default=DEFAULT_CUTOFF_FOLD_ID)
    parser.add_argument("--json-output", type=Path, default=DEFAULT_OUTPUT)
    arguments = parser.parse_args()

    started = datetime.now(UTC)
    manifest = load_residual_source_manifest(
        arguments.residual_table,
        arguments.residual_manifest,
        expect_model_name=MODEL_NAME,
        expect_model_version=MODEL_VERSION,
        expect_feature_contract_version=FEATURE_CONTRACT_VERSION,
    )
    table = pd.read_csv(arguments.residual_table)
    calendar = calendar_from_archive(arguments.archive_root, manifest.source_seasons)
    revision, dirty = _git_revision()

    report = run_shadow_calibration(
        manifest,
        table,
        calendar,
        config=ShadowCalibrationConfig(cutoff_fold_id=arguments.cutoff_fold_id),
        generated_at_utc=started.isoformat(timespec="seconds"),
        provenance_fingerprints={
            "repository_commit": revision,
            "working_tree_dirty": str(dirty).lower(),
            "dataset_snapshot_id": manifest.dataset_snapshot_id,
            "residual_generation_commit": manifest.generation_commit,
        },
    )
    document = report_to_dict(report)
    outcome = _write_once(document, arguments.json_output)
    if outcome == "written":
        write_shadow_report(report, arguments.json_output)

    elapsed = (datetime.now(UTC) - started).total_seconds()
    print(f"Status      {report.shadow_status} ({outcome})")
    print(f"Identity    {MODEL_NAME} / {MODEL_VERSION}")
    print(f"Cutoff      {arguments.cutoff_fold_id}")
    print(f"Eval folds  {report.sample_size}")
    for gate in report.gate_results:
        verdict = "pass" if gate.passes else "FAIL"
        print(f"Gate        {gate.gate}: {verdict} (observed {gate.observed})")
    for reason in report.reasons:
        print(f"Reason      {reason}")
    print(f"Elapsed     {elapsed:.1f}s")
    print(f"Wrote       {arguments.json_output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
