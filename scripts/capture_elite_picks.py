"""Capture a frozen elite cohort's gameweek N-1 picks, before the gameweek N deadline.

The cohort itself comes from an earlier standings capture. This command reads that capture,
fetches each member's picks for the *previous* gameweek, and writes them into one snapshot.

Why N-1. A gameweek's picks become public only after its own deadline, so gameweek N picks
can never inform a gameweek N feature. N-1 picks are complete the moment N-1's deadline
passes, which is before N's -- that is the whole reason the lag rule is N-1 rather than N.

Raw entry ids stay in the git-ignored snapshot store. The command prints counts.
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

from squadopt.data.cohorts import nested_cohorts, ranked_entries_from_pages
from squadopt.data.errors import DataError, DataSourceError
from squadopt.data.snapshots import read_snapshot, write_snapshot
from squadopt.data.sources.fpl_live import (
    entry_picks_payload,
    fpl_league_standings_page,
    league_standings_page_payload,
)
from squadopt.platform.fpl_capture import BASE_URL, fetch

OVERALL_LEAGUE_ID = 314
SNAPSHOT_SOURCE = "fpl-elite-picks"
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cohort-snapshot", required=True)
    parser.add_argument("--target-gameweek", type=int, required=True)
    parser.add_argument("--deadline-utc", required=True)
    parser.add_argument("--cohort-size", type=int, default=100, choices=(50, 100, 200))
    parser.add_argument(
        "--snapshot-root", type=Path, default=REPOSITORY_ROOT / "data" / "snapshots"
    )
    return parser.parse_args()


def main() -> int:
    arguments = _parse_arguments()
    lag = arguments.target_gameweek - 1
    if lag < 1:
        print("A gameweek 1 decision has no previous gameweek to read picks from.")
        return 1
    try:
        cohort_snapshot = read_snapshot(arguments.snapshot_root, arguments.cohort_snapshot)
        pages = []
        page_number = 1
        while True:
            name = league_standings_page_payload(OVERALL_LEAGUE_ID, page_number)
            if name not in cohort_snapshot.payloads:
                break
            pages.append(
                fpl_league_standings_page(
                    cohort_snapshot.payloads[name],
                    league_id=OVERALL_LEAGUE_ID,
                    expected_page=page_number,
                )
            )
            page_number += 1
        if not pages:
            raise DataSourceError(
                f"Snapshot {arguments.cohort_snapshot} carries no Overall standings pages."
            )
        ordered = ranked_entries_from_pages(pages, expected_ranks=arguments.cohort_size)
        cohort = nested_cohorts(
            ordered,
            target_gameweek=arguments.target_gameweek,
            captured_at_utc=cohort_snapshot.metadata.captured_at_utc,
            deadline_timestamp_utc=arguments.deadline_utc,
            source_snapshot_id=cohort_snapshot.metadata.snapshot_id,
            sizes=[arguments.cohort_size],
        )[arguments.cohort_size]

        payloads: dict[str, bytes] = {}
        unreadable: list[int] = []
        for entry_id in cohort.entry_ids:
            try:
                content = fetch(f"{BASE_URL}/entry/{entry_id}/event/{lag}/picks/")
            except Exception:  # one unreadable member is not a failed capture
                # A member whose picks cannot be read lowers the observed denominator in the
                # evidence table. It is recorded as unobserved rather than as a zero holding.
                unreadable.append(entry_id)
                continue
            payloads[entry_picks_payload(entry_id, lag)] = content
        if not payloads:
            raise DataSourceError(
                f"No member of the Top-{arguments.cohort_size} cohort returned readable "
                f"gameweek {lag} picks."
            )
        captured_at = _utc_now()
        if captured_at >= arguments.deadline_utc:
            raise DataSourceError(
                f"Capture finished at {captured_at}, at or after the "
                f"{arguments.deadline_utc} deadline; this is not pre-deadline evidence."
            )
        metadata = write_snapshot(
            arguments.snapshot_root,
            source=SNAPSHOT_SOURCE,
            captured_at_utc=captured_at,
            payloads=payloads,
        )
    except DataError as error:
        print(f"Elite picks capture refused: {error}")
        return 1

    print(f"Wrote snapshot {metadata.snapshot_id}")
    print(f"  cohort            Top-{cohort.size} from {cohort.source_snapshot_id}")
    print(f"  picks gameweek    {lag} (for a gameweek {arguments.target_gameweek} decision)")
    print(f"  members readable  {len(payloads)}/{cohort.size}")
    print(f"  members missing   {len(unreadable)} (recorded as unobserved, not as zero)")
    print(f"  captured          {metadata.captured_at_utc}")
    print("  raw identities    local snapshot only; not committed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
