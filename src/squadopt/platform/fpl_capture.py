"""Network adapter for one immutable FPL deadline capture.

The application tick receives capture as an injected operation.  Keeping the concrete
HTTP adapter here lets installed CLI entry points provide it without importing a private
module under ``scripts``.
"""

import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path

from squadopt.application.entries import EntryRegistry
from squadopt.data.errors import DataSourceError
from squadopt.data.identity import reconcile_player_identity
from squadopt.data.snapshots import SnapshotMetadata, write_snapshot
from squadopt.data.sources.fpl_live import (
    BOOTSTRAP_PAYLOAD,
    FIXTURES_PAYLOAD,
    FPL_LIVE_SOURCE,
    entry_endpoint_paths,
    gameweek_deadlines,
    league_standings_endpoint_path,
    next_open_deadline,
    player_snapshot,
)
from squadopt.data.sources.vaastav import build_panel

BASE_URL = "https://fantasy.premierleague.com/api"
ENDPOINTS: dict[str, str] = {
    BOOTSTRAP_PAYLOAD: f"{BASE_URL}/bootstrap-static/",
    FIXTURES_PAYLOAD: f"{BASE_URL}/fixtures/",
}
USER_AGENT = "squadopt/1.0 (private research; contact via repository owner)"
REQUEST_TIMEOUT_SECONDS = 30
RETRY_ATTEMPTS = 4
RETRY_INITIAL_SECONDS = 2.0
RETRY_MAX_SECONDS = 16.0


def _read(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
        return bytes(response.read())


def fetch(
    url: str,
    *,
    attempts: int = RETRY_ATTEMPTS,
    sleeper: Callable[[float], None] = time.sleep,
) -> bytes:
    """Read one endpoint, translating network failures into the data error contract.

    A capture used to be two requests, where a rate limit was best left to the operator.
    It is now two plus three per registered entry, so the same polite pause the old error
    message told a human to take is taken here instead: 429 and 5xx are retried with a
    bounded backoff, because they say "later", while every other 4xx says "never" and is
    raised immediately. The last failure is reported rather than swallowed.
    """

    delay = RETRY_INITIAL_SECONDS
    for attempt in range(1, max(1, attempts) + 1):
        try:
            return _read(url)
        except urllib.error.HTTPError as error:
            retriable = error.code == 429 or 500 <= error.code < 600
            if not retriable or attempt == attempts:
                raise DataSourceError(
                    f"{url} returned HTTP {error.code} {error.reason}"
                    + (f" on all {attempts} attempts." if retriable else ".")
                ) from error
            print(f"  waiting  HTTP {error.code} from {url}; retrying in {delay:.0f}s")
        except urllib.error.URLError as error:
            raise DataSourceError(f"Could not reach {url}: {error.reason}") from error
        sleeper(delay)
        delay = min(delay * 2, RETRY_MAX_SECONDS)
    raise DataSourceError(f"{url} was never read.")  # pragma: no cover - loop always returns


def _ordered_positions(counts: dict[str, int]) -> str:
    return ", ".join(
        f"{position} {counts.get(position, 0)}" for position in ("GK", "DEF", "MID", "FWD")
    )


def summarise(payloads: dict[str, bytes], captured_at: str, *, archive_root: Path | None) -> None:
    """Report enough of a capture for an operator to judge it before trusting it."""

    bootstrap = payloads[BOOTSTRAP_PAYLOAD]
    target = next_open_deadline(gameweek_deadlines(bootstrap), as_of_utc=captured_at)
    players = player_snapshot(bootstrap)
    print(f"  captured at      {captured_at}")
    print(f"  next open        gameweek {target.gameweek} at {target.deadline_utc}")
    print(f"  players          {len(players)}")
    print(f"  teams            {players['team_id'].nunique()}")
    counts = {str(key): int(value) for key, value in players["position"].value_counts().items()}
    print(f"  by position      {_ordered_positions(counts)}")
    prices = players["price_tenths"]
    print(f"  price range      {prices.min() / 10:.1f} to {prices.max() / 10:.1f}")

    if archive_root is None or not archive_root.is_dir():
        print("  identity         archive not present locally; reconciliation skipped")
        return
    panel = build_panel(archive_root)
    report = reconcile_player_identity(players, panel["player_id"].tolist())
    print(
        f"  identity         {report.known_players} of {report.captured_players} players "
        f"have history ({report.known_fraction:.1%}); {report.new_players} are new"
    )


def registered_endpoints(
    bootstrap: bytes,
    *,
    as_of_utc: str,
    entry_registry: Path | None,
    league_id: int | None,
) -> Mapping[str, str]:
    """Payload name to URL for the registered entries and their league, if asked for.

    The paths come from the data adapter; only the base URL is joined here. The gameweek
    is the one before the deadline this capture is open for, because that is the last
    gameweek whose picks are published -- picks are frozen at their own deadline, so this
    does not depend on the fixtures having been played. Before the opening deadline there
    is no such gameweek and no picks are read.
    """

    if entry_registry is None and league_id is None:
        return {}
    paths: dict[str, str] = {}
    if league_id is not None:
        paths.update(league_standings_endpoint_path(league_id))
    if entry_registry is not None:
        identifiers = EntryRegistry.load(entry_registry).ids()
        target = next_open_deadline(gameweek_deadlines(bootstrap), as_of_utc=as_of_utc).gameweek
        if identifiers and target > 1:
            paths.update(entry_endpoint_paths(identifiers, gameweek=target - 1))
    return {name: f"{BASE_URL}/{path}" for name, path in sorted(paths.items())}


def capture(
    snapshot_root: Path,
    *,
    archive_root: Path | None = None,
    dry_run: bool = False,
    entry_registry: Path | None = None,
    league_id: int | None = None,
) -> SnapshotMetadata | None:
    """Fetch, describe and optionally persist one immutable snapshot.

    The two season endpoints are always read. Passing ``entry_registry`` adds the three
    documents each registered entry publishes, and ``league_id`` adds the league standings
    page, so a capture can record who was in the league when a recommendation was made.

    ``captured_at`` is stamped after the season endpoints and before the per-entry ones, so
    a capture with entries claims an instant marginally *earlier* than its last read. That
    is the safe direction: the metadata under-claims freshness rather than over-claiming
    it, and the extra documents describe squads already frozen at a past deadline.
    """

    print(f"Reading {len(ENDPOINTS)} endpoint(s) from {BASE_URL}")
    payloads = {name: fetch(url) for name, url in sorted(ENDPOINTS.items())}
    for name, content in sorted(payloads.items()):
        print(f"  read     {name}  ({len(content):,} bytes)")
    captured_at = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    extra = registered_endpoints(
        payloads[BOOTSTRAP_PAYLOAD],
        as_of_utc=captured_at,
        entry_registry=entry_registry,
        league_id=league_id,
    )
    if extra:
        print(f"Reading {len(extra)} registered-entry endpoint(s)")
        for name, url in extra.items():
            payloads[name] = fetch(url)
            print(f"  read     {name}  ({len(payloads[name]):,} bytes)")

    print()
    summarise(payloads, captured_at, archive_root=archive_root)
    if extra:
        print(f"  registered       {len(extra)} extra payload(s)")
    if dry_run:
        return None
    return write_snapshot(
        snapshot_root,
        source=FPL_LIVE_SOURCE,
        captured_at_utc=captured_at,
        payloads=payloads,
    )
