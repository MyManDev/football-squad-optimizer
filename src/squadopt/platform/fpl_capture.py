"""Network adapter for one immutable FPL deadline capture.

The application tick receives capture as an injected operation.  Keeping the concrete
HTTP adapter here lets installed CLI entry points provide it without importing a private
module under ``scripts``.
"""

import http.client
import re
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path

from squadopt.application.entries import EntryRegistry
from squadopt.data.errors import DataError, DataSourceError
from squadopt.data.identity import reconcile_player_identity
from squadopt.data.snapshots import SnapshotMetadata, write_snapshot
from squadopt.data.sources.football_history import captured_history_weeks
from squadopt.data.sources.fpl_live import (
    BOOTSTRAP_PAYLOAD,
    FIXTURES_PAYLOAD,
    FPL_LIVE_SOURCE,
    FREE_HIT_CHIP,
    entry_active_chip,
    entry_endpoint_paths,
    entry_picks_endpoint_path,
    entry_picks_payload,
    entry_transfer_history,
    entry_transfers_endpoint_path,
    entry_transfers_payload,
    gameweek_deadlines,
    league_standings_endpoint_path,
    live_endpoint_path,
    next_open_deadline,
    player_snapshot,
)
from squadopt.data.sources.vaastav import build_panel
from squadopt.live.free_hit import FIRST_GAMEWEEK
from squadopt.prediction.component_dataset import COMPONENT_HISTORY_WINDOW

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
    It is now two plus up to five per registered entry, so the same polite pause the old
    error message told a human to take is taken here instead: 429 and 5xx are retried with a
    bounded backoff, because they say "later", while every other 4xx says "never" and is
    raised immediately. A response that times out, is dropped or ends short once the host
    has been reached says "later" too. The last failure is reported rather than swallowed.
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
        except (OSError, http.client.HTTPException) as error:
            # urllib wraps only the sending of the request in URLError. A read that times
            # out, a host that hangs up and a body cut short arrive raw (TimeoutError,
            # RemoteDisconnected, IncompleteRead). These used to leave after one try and not
            # as a DataError: cohort_capture catches only DataError, so it passed them on as
            # a traceback, and elite_capture, which catches everything, recorded the member
            # as unobserved. The host was reached, so like a 503 this says "later" and is
            # retried; in elite_capture that is up to RETRY_ATTEMPTS tries per member.
            if attempt == attempts:
                raise DataSourceError(
                    f"{url} was not read on all {attempts} attempts: {error!r}"
                ) from error
            print(f"  waiting  {type(error).__name__} from {url}; retrying in {delay:.0f}s")
        sleeper(delay)
        delay = min(delay * 2, RETRY_MAX_SECONDS)
    raise DataSourceError(f"{url} was never read.")  # pragma: no cover - loop always returns


def _utc_now() -> str:
    # Preserve the precision the clock supplies. Truncating a 12:00:00.900 read to
    # 12:00:00 would recreate the early time-of-knowledge claim this stamp prevents.
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


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
    league_ids: Sequence[int] = (),
) -> Mapping[str, str]:
    """Payload name to URL for the registered entries and their leagues, if asked for.

    The paths come from the data adapter; only the base URL is joined here. The gameweek
    is the one before the deadline this capture is open for, because that is the last
    gameweek whose picks are published -- picks are frozen at their own deadline, so this
    does not depend on the fixtures having been played. Before the opening deadline there
    is no such gameweek and no picks are read.
    """

    if entry_registry is None and not league_ids:
        return {}
    paths: dict[str, str] = {}
    for league_id in league_ids:
        paths.update(league_standings_endpoint_path(league_id))
    if entry_registry is not None:
        identifiers = registered_entry_ids(entry_registry)
        target = next_open_deadline(gameweek_deadlines(bootstrap), as_of_utc=as_of_utc).gameweek
        if identifiers and target > 1:
            paths.update(entry_endpoint_paths(identifiers, gameweek=target - 1))
    return {name: f"{BASE_URL}/{path}" for name, path in sorted(paths.items())}


def live_history_endpoints(bootstrap: bytes, *, as_of_utc: str) -> Mapping[str, str]:
    """Return the already-played live endpoints this capture's readers need.

    Two readers take these documents, and each keeps its own window. The Phase C component
    model reads the ``COMPONENT_HISTORY_WINDOW`` weeks before the target and selects them
    by name itself, so a longer history changes nothing it computes. The football history
    reads every played week from gameweek 1 and refuses a capture that lacks one. The
    capture keeps the union of the two, which is every played week: one request per week,
    37 at most in a 38-week season.
    """

    target = next_open_deadline(gameweek_deadlines(bootstrap), as_of_utc=as_of_utc).gameweek
    component = range(max(1, target - COMPONENT_HISTORY_WINDOW), target)
    paths: dict[str, str] = {}
    for gameweek in sorted({*component, *captured_history_weeks(target)}):
        paths.update(live_endpoint_path(gameweek))
    return {name: f"{BASE_URL}/{path}" for name, path in sorted(paths.items())}


_PICKS_PAYLOAD = re.compile(r"^entry-(\d+)-picks-gw(\d+)\.json$")


def free_hit_basis_endpoints(payloads: Mapping[str, bytes]) -> Mapping[str, str]:
    """Payload name to URL for the picks a Free Hit week hides.

    A Free Hit squad lasts one gameweek: at the next deadline the member holds the
    squad from *before* the chip, which is the previous gameweek's picks document. A
    capture that reads only the played week's picks therefore has no record of the
    squad the advice must stand on, so for every captured picks document whose
    ``active_chip`` is the Free Hit this names the previous week's document too --
    walking back once more if that week was also a Free Hit (two chip sets a season
    make it possible), and never below gameweek 1. A Wildcard squad persists and needs
    nothing earlier; Bench Boost and Triple Captain change no squad.

    Documents already present are not re-read, and a picks document this cannot read
    is left to the consumer that will refuse it with its own reason: the capture's job
    is to keep bytes, not to validate them.
    """

    urls: dict[str, str] = {}
    for name in sorted(payloads):
        match = _PICKS_PAYLOAD.match(name)
        if match is None:
            continue
        entry_id, week = int(match.group(1)), int(match.group(2))
        try:
            chip = entry_active_chip(payloads[name], entry_id=entry_id, gameweek=week)
        except DataError:
            continue
        if chip == FREE_HIT_CHIP and week > 1:
            earlier = entry_picks_payload(entry_id, week - 1)
            if earlier not in payloads:
                urls[earlier] = f"{BASE_URL}/{entry_picks_endpoint_path(entry_id, week - 1)}"
    return urls


_HISTORY_PAYLOAD = re.compile(r"^entry-(\d+)-history\.json$")


def purchase_price_endpoints(payloads: Mapping[str, bytes]) -> Mapping[str, str]:
    """Payload name to URL for the documents a member's purchase prices are rebuilt from.

    For every entry whose history the capture holds: its transfers list, and, when that
    history starts at gameweek 1, its gameweek 1 picks, the fifteen it opened the season
    with (``squadopt.live.purchase_prices`` replays the one over the other). A late joiner
    gets no opening picks: that squad was bought at a later deadline's prices, which no
    document states. A document already present is not read again, because a gameweek 2
    capture's picks are the gameweek 1 picks and a Free Hit walk-back may already have read
    them. A history this cannot read is skipped and left to the consumer that will refuse
    it: the capture's job is to keep bytes, not to validate them.
    """

    urls: dict[str, str] = {}
    for name in sorted(payloads):
        match = _HISTORY_PAYLOAD.match(name)
        if match is None:
            continue
        entry_id = int(match.group(1))
        transfers = entry_transfers_payload(entry_id)
        if transfers not in payloads:
            urls[transfers] = f"{BASE_URL}/{entry_transfers_endpoint_path(entry_id)}"
        try:
            history = entry_transfer_history(payloads[name], entry_id=entry_id)
        except DataError:
            continue
        opening = entry_picks_payload(entry_id, FIRST_GAMEWEEK)
        if history.weeks and min(history.weeks) == FIRST_GAMEWEEK and opening not in payloads:
            urls[opening] = f"{BASE_URL}/{entry_picks_endpoint_path(entry_id, FIRST_GAMEWEEK)}"
    return urls


def registered_entry_ids(path: Path) -> tuple[int, ...]:
    """Read the registry, reporting a bad one in the data error contract.

    ``EntryRegistry.load`` raises parser and shape errors from its own layer. None is a
    ``DataError``, so malformed JSON, a malformed document shape, a bad contract value or an
    unusable file would otherwise reach the operator as a traceback. A capture that cannot read
    its registry has to say which file and why, in the same vocabulary as every other capture
    failure.
    """

    if not path.is_file():
        raise DataSourceError(f"{path} is not a usable entry registry: not a readable file")

    try:
        return EntryRegistry.load(path).ids()
    except (ValueError, TypeError, KeyError, AttributeError) as error:
        raise DataSourceError(f"{path} is not a usable entry registry: {error}") from error
    except OSError as error:
        raise DataSourceError(f"{path} could not be read: {error}") from error


def capture(
    snapshot_root: Path,
    *,
    archive_root: Path | None = None,
    dry_run: bool = False,
    entry_registry: Path | None = None,
    league_ids: Sequence[int] = (),
) -> SnapshotMetadata | None:
    """Fetch, describe and optionally persist one immutable snapshot.

    The two season endpoints and every already-played live-score document are always read.
    The last five supply the exact shifted minutes and points used by the operational
    Phase C component model; the football history needs all of them. Passing
    ``entry_registry`` adds the three documents each registered entry publishes, and
    ``league_ids`` adds each league's standings page, so a capture can record who was in
    the league when a recommendation was made. Each entry's transfers list and opening
    picks follow (``purchase_price_endpoints``); they sharpen a budget rather than make
    one, so a document the source still refuses after the retries is left out with a line
    saying so, and that member's budget stays the stated worth.

    ``captured_at`` is stamped **after every read**, so no payload in the snapshot was fetched
    later than the instant the snapshot claims. Stamping it earlier would have been wrong in a
    way that is easy to talk yourself into: a document read afterwards can contain events from
    after the stamp, so the snapshot would assert knowledge at a time that knowledge did not
    exist. The resolution of which gameweek's picks to read uses a separate provisional clock,
    which only chooses a URL and is never recorded.
    """

    print(f"Reading {len(ENDPOINTS)} endpoint(s) from {BASE_URL}")
    payloads = {name: fetch(url) for name, url in sorted(ENDPOINTS.items())}
    for name, content in sorted(payloads.items()):
        print(f"  read     {name}  ({len(content):,} bytes)")

    resolution_at = _utc_now()
    history = live_history_endpoints(
        payloads[BOOTSTRAP_PAYLOAD],
        as_of_utc=resolution_at,
    )
    if history:
        print(f"Reading {len(history)} live-history endpoint(s)")
        for name, url in history.items():
            payloads[name] = fetch(url)
            print(f"  read     {name}  ({len(payloads[name]):,} bytes)")

    extra = dict(
        registered_endpoints(
            payloads[BOOTSTRAP_PAYLOAD],
            as_of_utc=resolution_at,
            entry_registry=entry_registry,
            league_ids=league_ids,
        )
    )
    if extra:
        print(f"Reading {len(extra)} registered-entry endpoint(s)")
        for name, url in extra.items():
            payloads[name] = fetch(url)
            print(f"  read     {name}  ({len(payloads[name]):,} bytes)")
        # A Free Hit week's picks are not the squad the member holds next; read the
        # week before, and keep reading back while that week was a Free Hit as well.
        while earlier := free_hit_basis_endpoints(payloads):
            print(f"Reading {len(earlier)} pre-Free-Hit picks endpoint(s)")
            for name, url in earlier.items():
                payloads[name] = fetch(url)
                extra[name] = url
                print(f"  read     {name}  ({len(payloads[name]):,} bytes)")
        # The purchase prices are rebuilt from these, and a member without them keeps the
        # stated worth as the budget, as every member did before. So unlike the documents
        # above a final failure here does not fail the capture: the document is left out.
        rebuild = purchase_price_endpoints(payloads)
        if rebuild:
            print(f"Reading {len(rebuild)} purchase-price endpoint(s)")
            for name, url in rebuild.items():
                try:
                    payloads[name] = fetch(url)
                except DataSourceError as error:
                    print(f"  missed   {name}  ({error})")
                    continue
                extra[name] = url
                print(f"  read     {name}  ({len(payloads[name]):,} bytes)")

    captured_at = _utc_now()
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
