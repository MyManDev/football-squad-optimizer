"""Compatibility command for squadopt.application.player_evidence."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from scripts._experiment_cli import _git_revision

from squadopt.application.player_evidence import (
    _FORBIDDEN_COLUMNS as _FORBIDDEN_COLUMNS,
)
from squadopt.application.player_evidence import (
    EvidenceSummary as EvidenceSummary,
)
from squadopt.application.player_evidence import (
    ExportResult as ExportResult,
)
from squadopt.application.player_evidence import (
    _attr as _attr,
)
from squadopt.application.player_evidence import (
    _canonical as _canonical,
)
from squadopt.application.player_evidence import (
    _publish as _publish,
)
from squadopt.application.player_evidence import (
    _single as _single,
)
from squadopt.application.player_evidence import (
    _temporary as _temporary,
)
from squadopt.application.player_evidence import (
    validate_evidence_table as validate_evidence_table,
)
from squadopt.application.player_evidence import (
    write_evidence_artifact as write_evidence_artifact,
)
from squadopt.data.errors import (
    DataError,
)
from squadopt.data.snapshots import read_snapshot
from squadopt.features.evidence import (
    CONTRACT_VERSION,
    build_player_evidence_table,
)
from squadopt.features.evidence_artifact import ARTIFACT_CONTRACT_VERSION

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SNAPSHOT_ROOT = REPOSITORY_ROOT / "data" / "snapshots"
DEFAULT_OUTPUT_DIR = REPOSITORY_ROOT / "artifacts" / "phase_b"


def _parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season", required=True)
    parser.add_argument("--target-gameweek", type=int, required=True)
    parser.add_argument("--deadline-utc", required=True)
    parser.add_argument("--snapshot-root", type=Path, default=DEFAULT_SNAPSHOT_ROOT)
    parser.add_argument("--cohort-snapshot", required=True, help="where membership is frozen")
    parser.add_argument(
        "--snapshot",
        action="append",
        default=[],
        help="a pre-deadline capture the evidence may read (picks, bootstrap); repeatable. "
        "The cohort snapshot is included automatically.",
    )
    parser.add_argument("--cohort-size", type=int, default=100, choices=(50, 100, 200))
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--table-name", default=None, help="file stem; defaults to the contract")
    return parser.parse_args()


def main() -> int:
    arguments = _parse_arguments()
    table_name = arguments.table_name or (
        f"{CONTRACT_VERSION}_{arguments.season}_gw{arguments.target_gameweek:02d}"
        f"_top{arguments.cohort_size}"
    )
    try:
        revision, dirty = _git_revision()
        if dirty:
            raise DataError(
                "the working tree has uncommitted changes, so the artifact could not be "
                "reproduced from the commit it would record; commit or stash them first."
            )
        cohort_snapshot = read_snapshot(arguments.snapshot_root, arguments.cohort_snapshot)
        snapshot_ids = list(dict.fromkeys(arguments.snapshot))
        if arguments.cohort_snapshot not in snapshot_ids:
            snapshot_ids.append(arguments.cohort_snapshot)
        snapshots = [
            read_snapshot(arguments.snapshot_root, snapshot_id) for snapshot_id in snapshot_ids
        ]
        table = build_player_evidence_table(
            season=arguments.season,
            target_gameweek=arguments.target_gameweek,
            deadline_timestamp_utc=arguments.deadline_utc,
            snapshots=snapshots,
            cohort_snapshot=cohort_snapshot,
            cohort_size=arguments.cohort_size,
        )
        result = write_evidence_artifact(
            table, arguments.output_dir, table_name, repository_commit=revision
        )
    except DataError as error:
        print(f"Evidence export refused: {error}")
        return 1

    summary = result.summary
    print(f"Wrote {result.table_path}")
    print(f"      {result.manifest_path}")
    print(f"  contract          {CONTRACT_VERSION} / {ARTIFACT_CONTRACT_VERSION}")
    print(f"  week              {summary.season} gameweek {summary.target_gameweek}")
    print(f"  rows              {summary.row_count}")
    print(f"  cohort            Top-{summary.cohort_size}")
    print(f"  members observed  {summary.elite_members_observed}")
    print(f"  members missing   {summary.elite_members_missing_picks}")
    print(f"  unmapped elements {len(summary.unmapped_picked_elements)}")
    print(f"  table sha256      {result.table_sha256}")
    print("  identities        none in the table, the manifest or this output")
    return 0


if __name__ == "__main__":
    sys.exit(main())
