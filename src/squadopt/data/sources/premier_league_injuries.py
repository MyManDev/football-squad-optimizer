"""Source-exact official injury-widget facts; neither coach claims nor probabilities.

The official page declares a playlist whose detailed response embeds club playlists.
The editorial row clocks remain separate from the page update and our observation.
SDP player IDs are retained as source identifiers, never assumed to be FPL IDs.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Collection, Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta, timezone
from html.parser import HTMLParser
from typing import Any

from squadopt.data.sources.club_news_readable import extract_readable_text
from squadopt.data.timestamps import as_instant

CONTRACT_VERSION = "official_pl_injuries_v1"
PAGE_URL = "https://www.premierleague.com/en/latest-player-injuries"
API_PREFIX = "https://api.premierleague.com/content/premierleague/playlist/EN/"
MAX_BYTES = 2 * 1024 * 1024
MAX_CLUBS = 20
MAX_ROWS = 200
# Explicit publisher labels, not fuzzy name matching or an assumed season roster.
CLUB_LABELS = {
    "Brighton & Hove Albion": "Brighton",
    "Coventry City": "Coventry",
    "Hull City": "Hull",
    "Ipswich Town": "Ipswich",
    "Leeds United": "Leeds",
    "Manchester City": "Man City",
    "Manchester United": "Man Utd",
    "Newcastle United": "Newcastle",
    "Nottingham Forest": "Nott'm Forest",
    "Tottenham Hotspur": "Spurs",
}


class _Widget(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.ids: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if values.get("data-widget") == "injury-news/injury-news":
            self.ids.append(values.get("data-playlist-id") or "")


def injury_playlist_url(page: bytes) -> str:
    if not page or len(page) > MAX_BYTES:
        raise ValueError("Official injury page is empty or exceeds its byte limit.")
    widget = _Widget()
    widget.feed(page.decode("utf-8"))
    if len(widget.ids) != 1 or re.fullmatch(r"[1-9][0-9]{0,11}", widget.ids[0]) is None:
        raise ValueError("Official injury page must declare one numeric injury playlist.")
    return f"{API_PREFIX}{widget.ids[0]}?detail=DETAILED"


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("Official injury JSON contains duplicate keys.")
        value[key] = item
    return value


def _document(raw: bytes) -> dict[str, Any]:
    if not raw or len(raw) > MAX_BYTES:
        raise ValueError("Official injury payload is empty or exceeds its byte limit.")
    value = json.loads(raw, object_pairs_hook=_object)
    if not isinstance(value, dict):
        raise ValueError("Official injury payload must be an object.")
    return value


def _mapping(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("Official injury item is not an object.")
    return value


def _items(value: Mapping[str, Any]) -> list[Any]:
    items = value.get("items")
    if not isinstance(items, list):
        raise ValueError("Official injury playlist has no item list.")
    return items


def _name(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Official injury item has no name.")
    return " ".join(value.split())


def _id(value: object) -> int:
    if type(value) is not int or value <= 0:
        raise ValueError("Official injury identity must be a positive integer.")
    return value


@dataclass(frozen=True, slots=True)
class SourceSpan:
    sha256: str
    json_pointer: str
    start: int
    end: int


def _span(raw: bytes, path: tuple[str | int, ...]) -> SourceSpan:
    text = raw.decode("utf-8")
    decoder = json.JSONDecoder()

    def space(index: int) -> int:
        while index < len(text) and text[index].isspace():
            index += 1
        return index

    def locate(index: int, remaining: tuple[str | int, ...]) -> tuple[int, int]:
        index = space(index)
        if not remaining:
            return index, decoder.raw_decode(text, index)[1]
        key, *tail = remaining
        cursor = space(index + 1)
        if isinstance(key, str):
            while text[cursor] != "}":
                observed, end = decoder.raw_decode(text, cursor)
                cursor = space(end)
                if text[cursor] != ":":
                    raise ValueError("Invalid JSON object delimiter.")
                cursor = space(cursor + 1)
                if observed == key:
                    return locate(cursor, tuple(tail))
                cursor = space(decoder.raw_decode(text, cursor)[1])
                if text[cursor] == ",":
                    cursor = space(cursor + 1)
        else:
            for ordinal in range(key + 1):
                if ordinal == key:
                    return locate(cursor, tuple(tail))
                cursor = space(decoder.raw_decode(text, cursor)[1])
                if text[cursor] != ",":
                    raise ValueError("Invalid JSON array delimiter.")
                cursor = space(cursor + 1)
        raise ValueError("Source JSON pointer was not found.")

    start, end = locate(0, path)
    pointer = "/" + "/".join(str(part).replace("~", "~0").replace("/", "~1") for part in path)
    return SourceSpan(
        hashlib.sha256(raw).hexdigest(),
        pointer,
        len(text[:start].encode("utf-8")),
        len(text[:end].encode("utf-8")),
    )


def _updated(page: bytes, observed_at: str) -> str | None:
    readable = extract_readable_text(page, "text/html").decode("utf-8")
    values = re.findall(
        r"Last updated:\s*(\d{1,2}:\d{2})\s+(BST|GMT),\s*(\d{1,2} [A-Za-z]+ \d{4})", readable
    )
    if len(values) != 1:
        return None
    clock, zone, day = values[0]
    try:
        parsed = datetime.strptime(f"{day} {clock}", "%d %B %Y %H:%M").replace(
            tzinfo=timezone(timedelta(hours=1 if zone == "BST" else 0))
        )
        result = parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")
        return result if as_instant(result) <= as_instant(observed_at) else None
    except ValueError:
        return None


@dataclass(frozen=True, slots=True)
class OfficialInjuryFact:
    club: str
    source_club: str
    source_player_name: str
    player_id: int | None
    identity_reason: str
    injury: str | None
    source_date: str | None
    source_publish_from: int | None
    source_last_modified: int | None
    details_urls: tuple[str, ...]
    source_span: SourceSpan


def _public_url(value: str) -> bool:
    """Surface only HTTPS DNS-host anchors; transport parsing stays in platform."""
    if re.search(r"[\s\\\x00-\x20\x7f]", value):
        return False
    matched = re.fullmatch(
        r"https://[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?"
        r"(?::(?P<port>[0-9]{1,5}))?(?:/[^\s\\]*)?",
        value,
    )
    return matched is not None and (matched["port"] is None or 1 <= int(matched["port"]) <= 65535)


@dataclass(frozen=True, slots=True)
class OfficialInjuryReport:
    season: str
    observed_at: str
    page_url: str
    playlist_url: str
    page_sha256: str
    playlist_sha256: str
    source_updated_at: str | None
    roster_clubs: tuple[str, ...]
    received_clubs: tuple[str, ...]
    missing_clubs: tuple[str, ...]
    incomplete_clubs: tuple[str, ...]
    unknown_source_clubs: tuple[str, ...]
    facts: tuple[OfficialInjuryFact, ...]
    refusals: tuple[str, ...]
    contract_version: str = CONTRACT_VERSION

    def as_record(self) -> dict[str, Any]:
        return asdict(self)

    def public_record(self, player_ids: Collection[int] = ()) -> dict[str, Any]:
        """Publish coverage and at most fifty explicitly requested player identities.

        Unmapped editorial names remain a count. No source bytes, internal paths,
        spans or inferred participation probabilities enter this public summary.
        """
        requested = set(player_ids)
        if len(requested) > 50 or any(type(value) is not int or value < 1 for value in requested):
            raise ValueError("Public injury facts require at most fifty positive player IDs.")
        selected = [fact for fact in self.facts if fact.player_id in requested]
        return {
            "contract_version": self.contract_version,
            "season": self.season,
            "source_url": self.page_url,
            "source_updated_at": self.source_updated_at,
            "observed_at": self.observed_at,
            "roster_clubs": list(self.roster_clubs),
            "received_clubs": list(self.received_clubs),
            "missing_clubs": list(self.missing_clubs),
            "incomplete_clubs": list(self.incomplete_clubs),
            "unknown_source_clubs": list(self.unknown_source_clubs),
            "listed_rows": len(self.facts),
            "mapped_rows": sum(fact.player_id is not None for fact in self.facts),
            "facts": [
                {
                    "player_id": fact.player_id,
                    "club": fact.club,
                    "injury": fact.injury,
                    "source_date": fact.source_date,
                    "details_urls": [url for url in fact.details_urls if _public_url(url)],
                }
                for fact in selected
            ],
            "limit": "Editorial injury rows do not establish absence, expected minutes, "
            "or complete squad health.",
        }


def read_official_injuries(
    *, page: bytes, playlist: bytes, bootstrap: bytes, observed_at: str, season: str
) -> OfficialInjuryReport:
    """Join literal source labels and exact captured full/short names; refuse ambiguity.

    Empty club sections mean zero rows listed, not a verified healthy squad. The
    source clocks and injury labels are factual text; none authorizes a forecast change.
    """
    as_instant(observed_at)
    url = injury_playlist_url(page)
    readable = extract_readable_text(page, "text/html").decode("utf-8")
    advertised_seasons = set(re.findall(r"(20[0-9]{2}/[0-9]{2}) season", readable))
    if advertised_seasons != {season.replace("-", "/")}:
        raise ValueError("Official injury page does not identify the captured roster season.")
    source = _document(playlist)
    if str(_id(source.get("id"))) != url.split("/")[-1].split("?")[0]:
        raise ValueError("Injury playlist differs from the page-declared identity.")
    if source.get("type") != "playlist":
        raise ValueError("The official injury source is not a playlist.")
    roster = _document(bootstrap)
    teams = roster.get("teams")
    players = roster.get("elements")
    if not isinstance(teams, list) or not isinstance(players, list):
        raise ValueError("A captured bootstrap team and player roster is required.")
    clubs = {_id(t.get("id")): _name(t.get("name")) for t in map(_mapping, teams)}
    if not clubs or len(clubs) != len(teams) or len(set(clubs.values())) != len(clubs):
        raise ValueError("Captured club names and identities must be unique.")
    identities: dict[tuple[str, str], set[int]] = {}
    for player in map(_mapping, players):
        club = clubs[_id(player.get("team"))]
        player_id = _id(player.get("code"))
        names = [player.get("web_name")]
        if isinstance(player.get("first_name"), str) and isinstance(player.get("second_name"), str):
            names.append(player["first_name"] + " " + player["second_name"])
        for name in names:
            if isinstance(name, str) and name.strip():
                identities.setdefault((club, _name(name).casefold()), set()).add(player_id)
    sections = _items(source)
    if len(sections) > MAX_CLUBS:
        raise ValueError("Official injury source exceeds the club-section limit.")
    received: list[str] = []
    incomplete: list[str] = []
    unknown: list[str] = []
    refusals: list[str] = []
    facts: list[OfficialInjuryFact] = []
    seen_players: set[tuple[str, str]] = set()
    rows_seen = 0
    for section_index, entry in enumerate(sections):
        section_club: str | None = None
        try:
            section = _mapping(_mapping(entry).get("response"))
            title = _name(section.get("title"))
            if section.get("type") != "playlist" or not title.startswith("Injury News - "):
                raise ValueError("Unrecognized club injury section.")
            label = title.removeprefix("Injury News - ")
            candidate_club = label if label in clubs.values() else CLUB_LABELS.get(label)
            if candidate_club is None or candidate_club not in clubs.values():
                unknown.append(label)
                continue
            club = candidate_club
            section_club = club
            if club in received:
                raise ValueError("Duplicate club injury section.")
            received.append(club)
            rows = _items(section)
            rows_seen += len(rows)
            if rows_seen > MAX_ROWS:
                raise ValueError("Official injury source exceeds the row limit.")
            page_info = _mapping(section.get("pageInfo"))
            if page_info.get("numPages") != 1 or page_info.get("numEntries") != len(rows):
                incomplete.append(club)
            for row_index, row in enumerate(rows):
                try:
                    fact = _mapping(_mapping(row).get("response"))
                    if fact.get("type") != "promo":
                        raise ValueError("Injury row is not an editorial promo.")
                    name = _name(fact.get("title"))
                    identity = (club, name.casefold())
                    if identity in seen_players:
                        raise ValueError("Duplicate player injury row.")
                    seen_players.add(identity)
                    matches = identities.get(identity, set())
                    matched = next(iter(matches)) if len(matches) == 1 else None
                    links = fact.get("links") or []
                    if not isinstance(links, list) or len(links) > 5:
                        raise ValueError("Injury details links are malformed.")
                    urls = tuple(
                        dict.fromkeys(_name(_mapping(link).get("promoUrl")) for link in links)
                    )
                    description = fact.get("description")
                    if description is not None and not isinstance(description, str):
                        raise ValueError("Injury description is not text.")
                    facts.append(
                        OfficialInjuryFact(
                            club,
                            label,
                            name,
                            matched,
                            "exact_name"
                            if matched is not None
                            else "ambiguous_name"
                            if matches
                            else "unmapped_name",
                            description,
                            fact.get("date") if isinstance(fact.get("date"), str) else None,
                            fact.get("publishFrom")
                            if type(fact.get("publishFrom")) is int
                            else None,
                            fact.get("lastModified")
                            if type(fact.get("lastModified")) is int
                            else None,
                            urls,
                            _span(
                                playlist,
                                (
                                    "items",
                                    section_index,
                                    "response",
                                    "items",
                                    row_index,
                                    "response",
                                ),
                            ),
                        )
                    )
                except ValueError as error:
                    incomplete.append(club)
                    refusals.append(f"{club} row {row_index}: {error}")
        except ValueError as error:
            if section_club is not None:
                incomplete.append(section_club)
            refusals.append(f"Section {section_index}: {error}")
    return OfficialInjuryReport(
        season,
        observed_at,
        PAGE_URL,
        url,
        hashlib.sha256(page).hexdigest(),
        hashlib.sha256(playlist).hexdigest(),
        _updated(page, observed_at),
        tuple(clubs.values()),
        tuple(received),
        tuple(c for c in clubs.values() if c not in received),
        tuple(dict.fromkeys(incomplete)),
        tuple(unknown),
        tuple(facts),
        tuple(refusals),
    )
