"""Capture the official Overall elite cohort before a target gameweek deadline.

Raw public entry ids and names remain in the git-ignored snapshot store. The command
prints only aggregate validation facts and the immutable snapshot id.

``--cohort-size`` defaults to 100, which is the original behaviour unchanged: two
standings pages, frozen through ``evaluation.select_as_of_top_100``, and that path still
produces the primary benchmark cohort. ``--cohort-size 200`` captures four pages in the
same atomic snapshot and derives the nested Top-50/100/200 from it -- a sensitivity and
evidence source that does **not** replace the frozen primary Top-100.
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

from squadopt.data.cohorts import (
    NESTED_COHORT_SIZES,
    nested_cohorts,
    pages_for_cohort_size,
    ranked_entries_from_pages,
)
from squadopt.data.errors import DataError, DataSourceError
from squadopt.data.snapshots import write_snapshot
from squadopt.data.sources.fpl_live import (
    BOOTSTRAP_PAYLOAD,
    LeagueStandingsPage,
    fpl_league_standings_page,
    gameweek_deadlines,
    league_standings_page_endpoint_path,
    next_open_deadline,
)
from squadopt.evaluation import RankedManager, select_as_of_top_100
from squadopt.platform.fpl_capture import BASE_URL, fetch

OVERALL_LEAGUE_ID = 314
TOP100_PAGES = (1, 2)
PRIMARY_COHORT_SIZE = 100
# The primary Top-100 keeps its original source label so its ids stay comparable. A
# 200-rank capture gets its own label: an id that reads "top100" while carrying two
# hundred ranks is the kind of quiet mislabel this repository refuses elsewhere, and rule
# 7 freezes the primary cohort -- so the two kinds must not be confusable at a glance.
SNAPSHOT_SOURCES = {100: "fpl-top100", 200: "fpl-top200"}
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target-gameweek", type=int, required=True)
    parser.add_argument(
        "--cohort-size",
        type=int,
        default=PRIMARY_COHORT_SIZE,
        choices=(100, 200),
        help=(
            "100 keeps the original two-page primary capture; 200 captures four pages "
            "and derives the nested Top-50/100/200 sensitivity cohorts from it."
        ),
    )
    parser.add_argument(
        "--snapshot-root",
        type=Path,
        default=REPOSITORY_ROOT / "data" / "snapshots",
    )
    return parser.parse_args()


def main() -> int:
    arguments = _parse_arguments()
    if arguments.target_gameweek < 2:
        print("A prospective elite cohort requires target gameweek 2 or later.")
        return 1
    size = int(arguments.cohort_size)
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
        pages: list[LeagueStandingsPage] = []
        source_updates: set[str] = set()
        for page_number in pages_for_cohort_size(size):
            endpoints = league_standings_page_endpoint_path(OVERALL_LEAGUE_ID, page_number)
            payload_name, path = next(iter(endpoints.items()))
            content = fetch(f"{BASE_URL}/{path}")
            page = fpl_league_standings_page(
                content,
                league_id=OVERALL_LEAGUE_ID,
                expected_page=page_number,
            )
            payloads[payload_name] = content
            pages.append(page)
            source_updates.add(page.last_updated_data)
            rankings.extend(
                RankedManager(entry_id=member.entry_id, rank=int(member.rank_sort))
                for member in page.members
                if member.rank_sort is not None and member.rank_sort <= PRIMARY_COHORT_SIZE
            )

        # The primary path's own check, unchanged: ranks 1..100 exactly, from the pages
        # that carry them. Kept even at size 200, where the first hundred ranks are the
        # same hundred and a gap in them would invalidate the nested reading too.
        if len(rankings) != PRIMARY_COHORT_SIZE or {record.rank for record in rankings} != set(
            range(1, PRIMARY_COHORT_SIZE + 1)
        ):
            raise DataSourceError(
                "The captured Overall standings pages do not contain exactly the "
                f"rank_sort values 1 through {PRIMARY_COHORT_SIZE}."
            )
        # Refuses on a missing or repeated rank rather than returning a shorter ordering.
        ordered_entry_ids = ranked_entries_from_pages(pages, expected_ranks=size)
        captured_at = _utc_now()
        metadata = write_snapshot(
            arguments.snapshot_root,
            source=SNAPSHOT_SOURCES[size],
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
        derived = nested_cohorts(
            ordered_entry_ids,
            target_gameweek=target.gameweek,
            captured_at_utc=metadata.captured_at_utc,
            deadline_timestamp_utc=target.deadline_utc,
            source_snapshot_id=metadata.snapshot_id,
            sizes=[cut for cut in NESTED_COHORT_SIZES if cut <= size],
        )
    except DataError as error:
        print(f"Top-100 capture refused: {error}")
        return 1

    print(f"Wrote snapshot {metadata.snapshot_id}")
    print(f"  target gameweek   {cohort.target_gameweek}")
    print(f"  deadline          {cohort.deadline_timestamp_utc}")
    print(f"  captured          {cohort.captured_at_utc}")
    print(f"  members           {len(cohort.entry_ids)}")
    print(f"  ranks covered     1..{len(ordered_entry_ids)} complete, no duplicates")
    for cut in sorted(derived):
        print(f"  nested Top-{cut:<7} {len(derived[cut].entry_ids)} members")
    print(f"  source updates    {len(source_updates)} timestamp(s) across {len(pages)} page(s)")
    print("  raw identities    local snapshot only; not committed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
