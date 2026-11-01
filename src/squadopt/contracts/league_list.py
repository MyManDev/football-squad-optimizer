"""The leagues a site serves: the operator's list, read by the capture and the weekly run.

``config/leagues.json`` names every classic league the site publishes. The capture reads
each league's standings, the weekly run renders each league's tree and writes the site's
league directory (``squadopt.contracts.league_tree``) with every league it rendered. The
list is the one place the operator says which leagues there are, so no command needs the
number typed twice and no stage can render one league and forget another.

At most one line sets ``legacy_advice_records``: the first league the site published, whose
publications still write the legacy member advice record (``member_advice_record_v2``) and
whose history reads those records first. Every other league reads only the
league-independent baseline records. So the code names no league id, and a list that sets
the flag on no line keeps no legacy records at all.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Final

LEAGUE_LIST_CONTRACT_VERSION: Final = "league_list_v1"
LEAGUE_LIST_FILE: Final = Path("config") / "leagues.json"
#: The line flag naming the league that keeps the legacy member advice records.
LEGACY_ADVICE_RECORDS_FIELD: Final = "legacy_advice_records"


class LeagueListError(ValueError):
    """The list is not the document the contract describes."""


def _league_id(record: object) -> int:
    if not isinstance(record, dict):
        raise LeagueListError("A league list line is an object.")
    league_id = record.get("league_id")
    if isinstance(league_id, bool) or not isinstance(league_id, int) or league_id <= 0:
        raise LeagueListError(f"A league id is a positive integer; got {league_id!r}.")
    return league_id


def parse_league_list(document: Any) -> tuple[int, ...]:
    """The league ids the document lists, in its order."""

    if (
        not isinstance(document, dict)
        or document.get("contract_version") != LEAGUE_LIST_CONTRACT_VERSION
        or not isinstance(document.get("leagues"), list)
    ):
        raise LeagueListError(f"Not a {LEAGUE_LIST_CONTRACT_VERSION} document.")
    ids = tuple(_league_id(record) for record in document["leagues"])
    if not ids:
        raise LeagueListError("A league list names at least one league.")
    if len(set(ids)) != len(ids):
        raise LeagueListError("A league list names a league once.")
    for record in document["leagues"]:
        if record.get("menu", "full") not in ("full", "device"):
            raise LeagueListError("A league menu is full or device.")
        if not isinstance(record.get(LEGACY_ADVICE_RECORDS_FIELD, False), bool):
            raise LeagueListError(f"{LEGACY_ADVICE_RECORDS_FIELD} is true or false.")
    if sum(record.get(LEGACY_ADVICE_RECORDS_FIELD) is True for record in document["leagues"]) > 1:
        raise LeagueListError("At most one league keeps the legacy advice records.")
    return ids


def read_league_list(path: Path) -> tuple[int, ...]:
    """The league ids the file at ``path`` lists."""

    try:
        document = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise LeagueListError(f"No league list at {path}.") from error
    except ValueError as error:
        raise LeagueListError(f"{path} does not parse as JSON.") from error
    return parse_league_list(document)


def parse_league_menus(document: Any) -> dict[int, str]:
    """The publication menus; older documents retain the full menu."""

    parse_league_list(document)
    return {row["league_id"]: row.get("menu", "full") for row in document["leagues"]}


def parse_legacy_record_league(document: Any) -> int | None:
    """The league whose line sets ``legacy_advice_records``, or None when no line does."""

    parse_league_list(document)
    for row in document["leagues"]:
        if row.get(LEGACY_ADVICE_RECORDS_FIELD) is True:
            return int(row["league_id"])
    return None
