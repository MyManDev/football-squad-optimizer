"""Capture the live season's state before a deadline closes.

    python -m scripts.capture_deadline_snapshot           # capture and summarise
    python -m scripts.capture_deadline_snapshot --dry-run # read, report, write nothing
    python -m scripts.capture_deadline_snapshot --list    # list captures already held

This is the only part of the project that touches the network, and it is a deliberate
manual step for two reasons. The obvious one is that no test and no CI job may depend
on an external service. The less obvious one is that *when* the capture happens is
part of the data: prices move daily and availability moves hourly near a deadline, so
a capture taken three days early describes a squad nobody can still enter.

Everything the capture produces stays local. The source permits private use and
forbids redistribution, so the repository holds no snapshot bytes; reproducibility
comes from the snapshot being immutable and checksummed on disk, and from the decision
report naming the snapshot it was made from. See docs/live_data_source_options.md for
the choice and the posture it commits to.
"""

import argparse
import sys
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

from squadopt.data.errors import DataError
from squadopt.data.identity import reconcile_player_identity
from squadopt.data.snapshots import list_snapshot_ids, read_snapshot, write_snapshot
from squadopt.data.sources.fpl_live import (
    BOOTSTRAP_PAYLOAD,
    FIXTURES_PAYLOAD,
    FPL_LIVE_SOURCE,
    gameweek_deadlines,
    next_open_deadline,
    player_snapshot,
)
from squadopt.data.sources.vaastav import build_panel

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT_ROOT = REPOSITORY_ROOT / "data" / "snapshots"
ARCHIVE_ROOT = REPOSITORY_ROOT / "data" / "raw" / "vaastav-fpl"

BASE_URL = "https://fantasy.premierleague.com/api"
ENDPOINTS: dict[str, str] = {
    BOOTSTRAP_PAYLOAD: f"{BASE_URL}/bootstrap-static/",
    FIXTURES_PAYLOAD: f"{BASE_URL}/fixtures/",
}

# The source publishes no rate limit and returns 429 when it decides a caller is
# excessive. Two reads per capture is far below any plausible threshold, and stating a
# contactable identity is basic courtesy toward a service we depend on and do not pay
# for.
USER_AGENT = "squadopt/1.0 (private research; contact via repository owner)"
REQUEST_TIMEOUT_SECONDS = 30


def fetch(url: str) -> bytes:
    """Read one endpoint, returning its raw bytes."""

    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            return bytes(response.read())
    except urllib.error.HTTPError as error:
        raise SystemExit(
            f"{url} returned HTTP {error.code} {error.reason}. A 429 means the source is "
            "rate limiting; wait rather than retrying in a loop."
        ) from error
    except urllib.error.URLError as error:
        raise SystemExit(f"Could not reach {url}: {error.reason}") from error


def summarise(payloads: dict[str, bytes], captured_at: str) -> None:
    """Report what the payloads say, so a capture can be judged before it is trusted."""

    bootstrap = payloads[BOOTSTRAP_PAYLOAD]
    deadlines = gameweek_deadlines(bootstrap)
    target = next_open_deadline(deadlines, as_of_utc=captured_at)
    players = player_snapshot(bootstrap)

    print(f"  captured at      {captured_at}")
    print(f"  gameweeks known  {len(deadlines)}")
    print(f"  next open        gameweek {target.gameweek} at {target.deadline_utc}")
    print(f"  players          {len(players)}")
    print(f"  teams            {players['team_id'].nunique()}")
    by_position = players["position"].value_counts().to_dict()
    print(f"  by position      {ordered_positions(by_position)}")
    prices = players["price_tenths"]
    print(f"  price range      {prices.min() / 10:.1f} to {prices.max() / 10:.1f}")

    if not ARCHIVE_ROOT.is_dir():
        print("  identity         archive not present locally; reconciliation skipped")
        return
    panel = build_panel(ARCHIVE_ROOT)
    report = reconcile_player_identity(players, panel["player_id"].tolist())
    print(
        f"  identity         {report.known_players} of {report.captured_players} players "
        f"have history ({report.known_fraction:.1%}); {report.new_players} are new"
    )


def ordered_positions(counts: dict[str, int]) -> str:
    return ", ".join(
        f"{position} {counts.get(position, 0)}" for position in ("GK", "DEF", "MID", "FWD")
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="read the endpoints and report, without writing a snapshot",
    )
    parser.add_argument(
        "--list", action="store_true", help="list the snapshots already held locally"
    )
    arguments = parser.parse_args()

    if arguments.list:
        identifiers = list_snapshot_ids(SNAPSHOT_ROOT)
        if not identifiers:
            print(f"No snapshots under {SNAPSHOT_ROOT}.")
            return 0
        print(f"{len(identifiers)} snapshot(s) under {SNAPSHOT_ROOT}:")
        for identifier in identifiers:
            metadata = read_snapshot(SNAPSHOT_ROOT, identifier).metadata
            print(f"  {identifier}  captured {metadata.captured_at_utc}")
        return 0

    print(f"Reading {len(ENDPOINTS)} endpoint(s) from {BASE_URL}")
    payloads = {name: fetch(url) for name, url in sorted(ENDPOINTS.items())}
    for name, content in sorted(payloads.items()):
        print(f"  read     {name}  ({len(content):,} bytes)")

    # Stamped once, after every read completes, so both payloads share one capture
    # instant and the pair cannot straddle a deadline.
    captured_at = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    print()
    try:
        summarise(payloads, captured_at)
    except DataError as error:
        print(f"\nThe capture does not satisfy the adapter contract:\n  {error}")
        return 1

    if arguments.dry_run:
        print("\nDry run: nothing written.")
        return 0

    metadata = write_snapshot(
        SNAPSHOT_ROOT,
        source=FPL_LIVE_SOURCE,
        captured_at_utc=captured_at,
        payloads=payloads,
    )
    print(f"\nWrote snapshot {metadata.snapshot_id}")
    print(f"  fingerprint    {metadata.fingerprint}")
    print(f"  directory      {SNAPSHOT_ROOT / metadata.snapshot_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
