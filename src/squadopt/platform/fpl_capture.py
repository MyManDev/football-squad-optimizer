"""Network adapter for one immutable FPL deadline capture.

The application tick receives capture as an injected operation.  Keeping the concrete
HTTP adapter here lets installed CLI entry points provide it without importing a private
module under ``scripts``.
"""

import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

from squadopt.data.errors import DataSourceError
from squadopt.data.identity import reconcile_player_identity
from squadopt.data.snapshots import SnapshotMetadata, write_snapshot
from squadopt.data.sources.fpl_live import (
    BOOTSTRAP_PAYLOAD,
    FIXTURES_PAYLOAD,
    FPL_LIVE_SOURCE,
    gameweek_deadlines,
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


def fetch(url: str) -> bytes:
    """Read one endpoint, translating network failures into the data error contract."""

    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            return bytes(response.read())
    except urllib.error.HTTPError as error:
        raise DataSourceError(
            f"{url} returned HTTP {error.code} {error.reason}. A 429 means the source is "
            "rate limiting; wait rather than retrying in a loop."
        ) from error
    except urllib.error.URLError as error:
        raise DataSourceError(f"Could not reach {url}: {error.reason}") from error


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


def capture(
    snapshot_root: Path,
    *,
    archive_root: Path | None = None,
    dry_run: bool = False,
) -> SnapshotMetadata | None:
    """Fetch, describe and optionally persist one immutable two-endpoint snapshot."""

    print(f"Reading {len(ENDPOINTS)} endpoint(s) from {BASE_URL}")
    payloads = {name: fetch(url) for name, url in sorted(ENDPOINTS.items())}
    for name, content in sorted(payloads.items()):
        print(f"  read     {name}  ({len(content):,} bytes)")
    captured_at = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    print()
    summarise(payloads, captured_at, archive_root=archive_root)
    if dry_run:
        return None
    return write_snapshot(
        snapshot_root,
        source=FPL_LIVE_SOURCE,
        captured_at_utc=captured_at,
        payloads=payloads,
    )
