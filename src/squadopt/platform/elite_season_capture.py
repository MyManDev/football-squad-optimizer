"""Keep the season of every manager an elite cohort capture has held.

The weekly elite capture stores one thing: the previous gameweek's picks of that week's
Top-100. That is what a pre-deadline feature may read, and it is all a decision needs. It
is not enough to study the cohort afterwards. A manager's other gameweeks, the transfers
made and the chips played are served only while the season runs, so what is not read
before the season closes cannot be read again.

This command reads the standings pages of every stored cohort capture, takes the union of
their managers, and for each one fetches the season history, the transfer list and the
picks of every scored gameweek the store does not hold yet. A gameweek is scored when it is
finished and checked (``scored_gameweeks``), so a stored week is final. The result is one
immutable snapshot per run. Earlier snapshots of this source are read by their payload
names only, so a run adds what is missing and repeats nothing a previous run stored.

A run is bounded by ``--request-budget``. Managers with the fewest stored gameweeks go
first, so a backfill that needs several runs moves on to new managers each time. A manager
or a gameweek that cannot be read is counted and left for the next run.

Raw entry ids stay in the git-ignored snapshot store. The command prints counts.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from squadopt.data.errors import DataError, DataSourceError
from squadopt.data.snapshots import (
    METADATA_FILENAME,
    list_snapshot_ids,
    read_snapshot,
    write_snapshot,
)
from squadopt.data.sources.fpl_live import (
    entry_history_payload,
    entry_picks_endpoint_path,
    entry_picks_payload,
    entry_transfers_endpoint_path,
    entry_transfers_payload,
    fpl_league_standings_page,
    league_standings_page_payload,
    scored_gameweeks,
)
from squadopt.platform.fpl_capture import BASE_URL, fetch

OVERALL_LEAGUE_ID = 314
CONTRACT = "elite_season_capture_v1"
SNAPSHOT_SOURCE = "fpl-elite-season"
COHORT_SOURCES = ("fpl-top100", "fpl-top200")
MANIFEST_PAYLOAD = "elite-season-manifest.json"
DEFAULT_REQUEST_BUDGET = 8000
DEFAULT_PAUSE_SECONDS = 0.2
REPOSITORY_ROOT = Path.cwd()

_PICKS_PAYLOAD = re.compile(r"^entry-(\d+)-picks-gw(\d+)\.json$")

Fetcher = Callable[[str], bytes]


@dataclass(frozen=True)
class Cohorts:
    """The managers every stored cohort capture names, and how many captures said so."""

    entry_ids: frozenset[int]
    captures_read: int
    captures_unreadable: int


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def stored_cohorts(root: Path) -> Cohorts:
    """Union the managers of every cohort capture under ``root``.

    A capture that does not read as verified standings pages is counted and skipped: one
    damaged week must not stop the other weeks' managers from being kept.
    """

    entry_ids: set[int] = set()
    read = 0
    unreadable = 0
    for source in COHORT_SOURCES:
        for snapshot_id in list_snapshot_ids(root, source=source):
            try:
                snapshot = read_snapshot(root, snapshot_id)
                members: set[int] = set()
                page_number = 1
                while True:
                    name = league_standings_page_payload(OVERALL_LEAGUE_ID, page_number)
                    if name not in snapshot.payloads:
                        break
                    page = fpl_league_standings_page(
                        snapshot.payloads[name],
                        league_id=OVERALL_LEAGUE_ID,
                        expected_page=page_number,
                    )
                    members.update(member.entry_id for member in page.members)
                    page_number += 1
            except DataError:
                unreadable += 1
                continue
            if not members:
                unreadable += 1
                continue
            entry_ids.update(members)
            read += 1
    return Cohorts(frozenset(entry_ids), read, unreadable)


def stored_picks(root: Path) -> dict[int, set[int]]:
    """Entry id to the gameweeks whose picks an earlier run of this command stored.

    Only the payload names in each snapshot's metadata are read. Opening the payloads would
    verify every stored document on every run, and the names are all this needs.
    """

    held: dict[int, set[int]] = {}
    for snapshot_id in list_snapshot_ids(root, source=SNAPSHOT_SOURCE):
        document = json.loads((root / snapshot_id / METADATA_FILENAME).read_text("utf-8"))
        checksums = document.get("checksums")
        if not isinstance(checksums, dict):
            continue
        for name in checksums:
            match = _PICKS_PAYLOAD.match(str(name))
            if match is not None:
                held.setdefault(int(match.group(1)), set()).add(int(match.group(2)))
    return held


def played_gameweeks(history: bytes) -> frozenset[int]:
    """The gameweeks an entry's season history has a row for."""

    try:
        document = json.loads(history)
    except ValueError as error:
        raise DataSourceError("Entry history is not a JSON document.") from error
    rows = document.get("current") if isinstance(document, dict) else None
    if not isinstance(rows, list):
        raise DataSourceError("Entry history must carry a 'current' list.")
    weeks: set[int] = set()
    for row in rows:
        event = row.get("event") if isinstance(row, dict) else None
        if isinstance(event, bool) or not isinstance(event, int) or event < 1:
            raise DataSourceError("Entry history rows must name a positive gameweek.")
        weeks.add(event)
    return frozenset(weeks)


def _parse_arguments(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--snapshot-root", type=Path, default=REPOSITORY_ROOT / "data" / "snapshots"
    )
    parser.add_argument(
        "--through-gameweek",
        type=int,
        help="the last gameweek to keep; default is the last scored gameweek",
    )
    parser.add_argument("--request-budget", type=int, default=DEFAULT_REQUEST_BUDGET)
    parser.add_argument("--pause-seconds", type=float, default=DEFAULT_PAUSE_SECONDS)
    parser.add_argument(
        "--plan-only",
        action="store_true",
        help="read the gameweek calendar and the store, print the plan, request no manager",
    )
    return parser.parse_args(argv)


def _manifest(facts: Mapping[str, object]) -> bytes:
    return json.dumps({"contract": CONTRACT, **facts}, indent=2, sort_keys=True).encode("utf-8")


def main(
    argv: list[str] | None = None,
    *,
    fetcher: Fetcher = fetch,
    sleeper: Callable[[float], None] = time.sleep,
    now: Callable[[], str] = _utc_now,
) -> int:
    arguments = _parse_arguments(argv)
    root: Path = arguments.snapshot_root
    if arguments.request_budget < 1 or arguments.pause_seconds < 0:
        print("Elite season capture refused: the budget must be positive, the pause not negative.")
        return 1
    try:
        scored = scored_gameweeks(fetcher(f"{BASE_URL}/bootstrap-static/"))
        through = max(scored, default=0)
        if arguments.through_gameweek is not None:
            through = min(through, arguments.through_gameweek)
        wanted = frozenset(week for week in scored if week <= through)
        cohorts = stored_cohorts(root)
        if not cohorts.entry_ids:
            raise DataSourceError(f"No cohort capture under {root} names a manager.")
        held = stored_picks(root)
    except DataError as error:
        print(f"Elite season capture refused: {error}")
        return 1

    # Fewest stored gameweeks first: after a run that spent its budget, the managers it did
    # not reach are the ones the next run starts with.
    order = sorted(cohorts.entry_ids, key=lambda entry: (len(held.get(entry, ())), entry))
    pending = [entry for entry in order if wanted - held.get(entry, set())]
    missing_weeks = sum(len(wanted - held.get(entry, set())) for entry in pending)

    print(
        f"  cohort captures   {cohorts.captures_read} read, "
        f"{cohorts.captures_unreadable} unreadable"
    )
    print(f"  managers known    {len(cohorts.entry_ids)}")
    print(f"  scored gameweeks  {len(wanted)} (through gameweek {through})")
    print(f"  managers pending  {len(pending)}")
    print(f"  requests at most  {missing_weeks + 2 * len(pending)}")
    if arguments.plan_only:
        print("  plan only         no manager was requested and nothing was written")
        return 0
    if not pending:
        print("Nothing to add: every known manager's scored gameweeks are stored.")
        return 0

    payloads: dict[str, bytes] = {}
    spent = 0
    managers_read = managers_unreadable = managers_deferred = 0
    picks_added = picks_unreadable = transfers_unreadable = 0

    def request(path: str) -> bytes:
        nonlocal spent
        if spent:
            sleeper(arguments.pause_seconds)
        spent += 1
        return fetcher(f"{BASE_URL}/{path}")

    for entry in pending:
        missing = sorted(wanted - held.get(entry, set()))
        if spent + 2 + len(missing) > arguments.request_budget:
            managers_deferred += 1
            continue
        try:
            history = request(f"entry/{entry}/history/")
            played = played_gameweeks(history)
        except DataError:
            managers_unreadable += 1
            continue
        new_weeks = [week for week in missing if week in played]
        if not new_weeks:
            # Every week the store lacks is one this manager did not play, so there is
            # nothing new to keep and no reason to store the same history again.
            continue
        managers_read += 1
        payloads[entry_history_payload(entry)] = history
        try:
            payloads[entry_transfers_payload(entry)] = request(entry_transfers_endpoint_path(entry))
        except DataError:
            transfers_unreadable += 1
        for week in new_weeks:
            try:
                payloads[entry_picks_payload(entry, week)] = request(
                    entry_picks_endpoint_path(entry, week)
                )
            except DataError:
                picks_unreadable += 1
                continue
            picks_added += 1

    if not payloads:
        if managers_unreadable or managers_deferred:
            print("Elite season capture refused: no pending manager could be read.")
            return 1
        print("Nothing to add: the weeks the store lacks are weeks their managers did not play.")
        return 0
    payloads[MANIFEST_PAYLOAD] = _manifest(
        {
            "through_gameweek": through,
            "scored_gameweeks": sorted(wanted),
            "cohort_captures_read": cohorts.captures_read,
            "cohort_captures_unreadable": cohorts.captures_unreadable,
            "managers_known": len(cohorts.entry_ids),
            "managers_read": managers_read,
            "managers_unreadable": managers_unreadable,
            "managers_deferred": managers_deferred,
            "picks_added": picks_added,
            "picks_unreadable": picks_unreadable,
            "transfers_unreadable": transfers_unreadable,
            "requests": spent,
        }
    )
    try:
        metadata = write_snapshot(
            root, source=SNAPSHOT_SOURCE, captured_at_utc=now(), payloads=payloads
        )
    except DataError as error:
        print(f"Elite season capture refused: {error}")
        return 1

    print(f"Wrote snapshot {metadata.snapshot_id}")
    print(f"  managers read     {managers_read}")
    print(f"  managers missing  {managers_unreadable} (left for the next run)")
    print(f"  managers deferred {managers_deferred} (request budget {arguments.request_budget})")
    print(f"  picks added       {picks_added}")
    print(f"  picks missing     {picks_unreadable} (left for the next run)")
    print(f"  transfers missing {transfers_unreadable}")
    print(f"  requests          {spent}")
    print("  raw identities    local snapshot only; not committed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
