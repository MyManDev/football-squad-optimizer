"""Capture the official Overall Top-100 before a target gameweek deadline.

Raw public entry ids and names remain in the git-ignored snapshot store. The command
prints only aggregate validation facts and the immutable snapshot id.
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

from squadopt.data.errors import DataError, DataSourceError
from squadopt.data.snapshots import write_snapshot
from squadopt.data.sources.fpl_live import (
    BOOTSTRAP_PAYLOAD,
    fpl_league_standings_page,
    gameweek_deadlines,
    league_standings_page_endpoint_path,
    next_open_deadline,
)
from squadopt.evaluation import RankedManager, select_as_of_top_100
from squadopt.platform.fpl_capture import BASE_URL, fetch

OVERALL_LEAGUE_ID = 314
TOP100_PAGES = (1, 2)
SNAPSHOT_SOURCE = "fpl-top100"
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target-gameweek", type=int, required=True)
    parser.add_argument(
        "--snapshot-root",
        type=Path,
        default=REPOSITORY_ROOT / "data" / "snapshots",
    )
    return parser.parse_args()


def main() -> int:
    arguments = _parse_arguments()
    if arguments.target_gameweek < 2:
        print("A prospective Top-100 cohort requires target gameweek 2 or later.")
        return 1
    try:
        bootstrap = fetch(f"{BASE_URL}/bootstrap-static/")
        provisional_time = _utc_now()
        target = next_open_deadline(gameweek_deadlines(bootstrap), as_of_utc=provisional_time)
        if target.gameweek != arguments.target_gameweek:
            raise DataSourceError(
                f"The next open deadline is gameweek {target.gameweek}, not requested "
                f"gameweek {arguments.target_gameweek}."
            )

        payloads: dict[str, bytes] = {BOOTSTRAP_PAYLOAD: bootstrap}
        rankings: list[RankedManager] = []
        source_updates: set[str] = set()
        for page_number in TOP100_PAGES:
            endpoints = league_standings_page_endpoint_path(OVERALL_LEAGUE_ID, page_number)
            payload_name, path = next(iter(endpoints.items()))
            content = fetch(f"{BASE_URL}/{path}")
            page = fpl_league_standings_page(
                content,
                league_id=OVERALL_LEAGUE_ID,
                expected_page=page_number,
            )
            payloads[payload_name] = content
            source_updates.add(page.last_updated_data)
            rankings.extend(
                RankedManager(entry_id=member.entry_id, rank=int(member.rank_sort))
                for member in page.members
                if member.rank_sort is not None and member.rank_sort <= 100
            )

        if len(rankings) != 100 or {record.rank for record in rankings} != set(range(1, 101)):
            raise DataSourceError(
                "The first two Overall standings pages do not contain exactly the "
                "rank_sort values 1 through 100."
            )
        captured_at = _utc_now()
        metadata = write_snapshot(
            arguments.snapshot_root,
            source=SNAPSHOT_SOURCE,
            captured_at_utc=captured_at,
            payloads=payloads,
        )
        cohort = select_as_of_top_100(
            rankings,
            target_gameweek=target.gameweek,
            captured_at_utc=metadata.captured_at_utc,
            deadline_timestamp_utc=target.deadline_utc,
            source_snapshot_id=metadata.snapshot_id,
        )
    except DataError as error:
        print(f"Top-100 capture refused: {error}")
        return 1

    print(f"Wrote snapshot {metadata.snapshot_id}")
    print(f"  target gameweek   {cohort.target_gameweek}")
    print(f"  deadline          {cohort.deadline_timestamp_utc}")
    print(f"  captured          {cohort.captured_at_utc}")
    print(f"  members           {len(cohort.entry_ids)}")
    print(f"  source updates    {len(source_updates)} timestamp(s) across two pages")
    print("  raw identities    local snapshot only; not committed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
