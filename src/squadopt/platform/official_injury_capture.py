"""Bounded immutable capture of the official league injury widget, without an LLM."""

from __future__ import annotations

import argparse
import json
import re
import time
import urllib.parse
import urllib.request
import urllib.robotparser
from collections.abc import Callable, Sequence
from datetime import UTC, date, datetime
from pathlib import Path

from squadopt.data.snapshots import (
    CapturedSnapshot,
    SnapshotMetadata,
    read_snapshot,
    write_snapshot,
)
from squadopt.data.sources.fpl_live import BOOTSTRAP_PAYLOAD
from squadopt.data.sources.premier_league_injuries import (
    API_PREFIX,
    MAX_BYTES,
    PAGE_URL,
    OfficialInjuryReport,
    injury_playlist_url,
    read_official_injuries,
)
from squadopt.live.recommendation import season_from_bootstrap
from squadopt.platform.club_news_fetch import (
    TERMS_READING_VALID_DAYS,
    ClubSource,
    registered_article_url,
)
from squadopt.platform.fpl_capture import REQUEST_TIMEOUT_SECONDS, USER_AGENT

SOURCE = "official-pl-injuries"
PAGE_PAYLOAD = "injury-page.html"
PLAYLIST_PAYLOAD = "injury-playlist.json"
REPORT_PAYLOAD = "report.json"


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self, req: object, fp: object, code: int, msg: str, headers: object, newurl: str
    ) -> None:
        return None


def _read_once(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT}, method="GET")
    opener = urllib.request.build_opener(_NoRedirect())
    with opener.open(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
        if response.status != 200 or response.geturl() != url:
            raise ValueError("Official injury source did not return its exact HTTP 200 URL.")
        raw = bytes(response.read(MAX_BYTES + 1))
        length = response.headers.get("Content-Length")
        if not raw or len(raw) > MAX_BYTES or (length is not None and int(length) != len(raw)):
            raise ValueError("Official injury payload is empty, incomplete or over its byte limit.")
        return raw


def _now() -> datetime:
    return datetime.now(UTC)


def capture_official_injuries(
    *,
    roster_snapshot: CapturedSnapshot,
    capture_root: Path,
    terms_read_on: date,
    fetch: Callable[[str], bytes] = _read_once,
    now: Callable[[], datetime] = _now,
    sleeper: Callable[[float], None] = time.sleep,
) -> tuple[SnapshotMetadata, OfficialInjuryReport]:
    """At most four GETs: each fixed host's robots, one page and its declared playlist.

    The supplied terms reading covers both official hosts. Unknown robots, redirects,
    repeated widgets and unbounded/paginated responses refuse rather than crawl.
    """
    today = now().date()
    if not 0 <= (today - terms_read_on).days <= TERMS_READING_VALID_DAYS:
        raise ValueError("A current dated reading for both official hosts is required.")
    records: dict[str, bytes] = {}

    def allowed_read(url: str, label: str) -> bytes:
        if (
            url != PAGE_URL
            and re.fullmatch(re.escape(API_PREFIX) + r"[1-9][0-9]{0,11}\?detail=DETAILED", url)
            is None
        ):
            raise ValueError("Official injury request is outside its exact URL allowlist.")
        parts = urllib.parse.urlsplit(url)
        robots_url = f"{parts.scheme}://{parts.netloc}/robots.txt"
        robots_raw = fetch(robots_url)
        if not robots_raw or len(robots_raw) > MAX_BYTES:
            raise ValueError("Official injury robots response is empty or too large.")
        parser = urllib.robotparser.RobotFileParser(robots_url)
        parser.parse(robots_raw.decode("utf-8").splitlines())
        if not parser.can_fetch(USER_AGENT, url):
            raise ValueError("Official injury source robots disallows the requested path.")
        records[f"{label}-robots.txt"] = robots_raw
        sleeper(1.0)
        raw = fetch(url)
        if not raw or len(raw) > MAX_BYTES:
            raise ValueError("Official injury payload exceeds its byte bound.")
        return raw

    page = allowed_read(PAGE_URL, "page")
    playlist_url = injury_playlist_url(page)
    playlist = allowed_read(playlist_url, "playlist")
    observed_at = now().astimezone(UTC).isoformat().replace("+00:00", "Z")
    bootstrap = roster_snapshot.payloads[BOOTSTRAP_PAYLOAD]
    report = read_official_injuries(
        page=page,
        playlist=playlist,
        bootstrap=bootstrap,
        observed_at=observed_at,
        season=season_from_bootstrap(bootstrap),
    )
    record = {
        **report.as_record(),
        "roster_snapshot_id": roster_snapshot.metadata.snapshot_id,
        "roster_fingerprint": roster_snapshot.metadata.fingerprint,
        "terms_read_on": terms_read_on.isoformat(),
        "model_calls": 0,
    }
    metadata = write_snapshot(
        capture_root,
        source=SOURCE,
        captured_at_utc=observed_at,
        payloads={
            **records,
            PAGE_PAYLOAD: page,
            PLAYLIST_PAYLOAD: playlist,
            BOOTSTRAP_PAYLOAD: bootstrap,
            REPORT_PAYLOAD: json.dumps(record, sort_keys=True, allow_nan=False).encode("utf-8"),
        },
    )
    return metadata, report


def read_official_injury_capture(snapshot: CapturedSnapshot) -> OfficialInjuryReport:
    if snapshot.metadata.source != SOURCE:
        raise ValueError("The supplied snapshot is not an official injury capture.")
    bootstrap = snapshot.payloads[BOOTSTRAP_PAYLOAD]
    report = read_official_injuries(
        page=snapshot.payloads[PAGE_PAYLOAD],
        playlist=snapshot.payloads[PLAYLIST_PAYLOAD],
        bootstrap=bootstrap,
        observed_at=snapshot.metadata.captured_at_utc,
        season=season_from_bootstrap(bootstrap),
    )
    recorded = json.loads(snapshot.payloads[REPORT_PAYLOAD])
    for key, value in report.as_record().items():
        if json.loads(json.dumps(value)) != recorded.get(key):
            raise ValueError("Official injury capture report differs from its held source.")
    return report


def registered_details_links(
    report: OfficialInjuryReport, sources: Sequence[ClubSource]
) -> dict[str, tuple[str, ...]]:
    """Return official referrals only inside already registered club origins and paths."""
    links: dict[str, list[str]] = {source.url: [] for source in sources}
    for fact in report.facts:
        for source in sources:
            if source.club != fact.club:
                continue
            for url in fact.details_urls:
                valid = registered_article_url(source, url)
                if valid is not None and valid not in links[source.url]:
                    links[source.url].append(valid)
    return {url: tuple(values) for url, values in links.items()}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot-root", required=True, type=Path)
    parser.add_argument("--roster-snapshot", required=True)
    parser.add_argument("--capture-root", required=True, type=Path)
    parser.add_argument("--terms-read-on", required=True, type=date.fromisoformat)
    args = parser.parse_args(argv)
    try:
        snapshot, report = capture_official_injuries(
            roster_snapshot=read_snapshot(args.snapshot_root, args.roster_snapshot),
            capture_root=args.capture_root,
            terms_read_on=args.terms_read_on,
        )
    except (OSError, ValueError, KeyError) as error:
        print(f"Refused: {error}")
        return 1
    print(
        json.dumps(
            {
                "capture_id": snapshot.snapshot_id,
                "received_clubs": report.received_clubs,
                "missing_clubs": report.missing_clubs,
                "incomplete_clubs": report.incomplete_clubs,
                "unknown_source_clubs": report.unknown_source_clubs,
                "listed_rows": len(report.facts),
                "mapped_rows": sum(f.player_id is not None for f in report.facts),
                "source_updated_at": report.source_updated_at,
                "observed_at": report.observed_at,
                "model_calls": 0,
                "refusals": report.refusals,
                "limit": "Editorial injury rows are not verified coach absences "
                "or complete squad health.",
            },
            ensure_ascii=False,
        )
    )
    return 0
