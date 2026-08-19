"""Adapter for a captured pre-deadline snapshot of the live Fantasy endpoints.

This module reads snapshot payloads that are already on disk. It never fetches,
which is what lets every test here run offline: capture is a deliberate step in a
script, and what arrives in this module is bytes.

What it produces is a *player snapshot*, not a canonical panel row. A canonical row
requires ``minutes`` and ``total_points``, and a roster read before kick-off has
neither. Inventing them to satisfy the canonical shape is exactly what the adapter
layer refuses to do, so the target here is the five deadline-known fields the
optimizer projection is assembled from: ``player_id``, ``name``, ``team_id``,
``position`` and ``price_tenths``.

The source publishes no contract and no documentation, so its shape is treated as an
observation rather than a promise. Every field this module depends on is checked and
named in the failure, because a renamed field must stop the run rather than quietly
produce a column of nulls.
"""

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final

import pandas as pd

from squadopt.data.cleaning import normalize_positions, to_price_tenths
from squadopt.data.errors import (
    DataSourceError,
    DuplicateRecordsError,
    InvalidValueError,
    format_examples,
)
from squadopt.data.fixtures import validate_fixture_snapshot
from squadopt.data.schema import FIXTURE_COLUMNS, MIN_GAMEWEEK
from squadopt.data.timestamps import as_instant, normalize_utc_timestamp

# Recorded in a snapshot's metadata as the source of its payloads.
FPL_LIVE_SOURCE: Final = "fpl-live"

# Payload names inside a snapshot. They name the endpoint each document came from so
# a snapshot stays readable without this module.
BOOTSTRAP_PAYLOAD: Final = "bootstrap-static.json"
FIXTURES_PAYLOAD: Final = "fixtures.json"

# The platform encodes position numerically. This is the same encoding the archive's
# `players_raw.csv` carries, but it is declared here rather than shared with the
# archive adapter: each source module is meant to know exactly one source, and
# importing another adapter's constant would couple two of them for four lines.
#
# Codes outside this mapping are not players. From the 2024-25 season the platform
# added manager entries, which are excluded for the same reason the archive adapter
# excludes them: a manager is not a squad-eligible player under the canonical
# contract, not because they are inconvenient.
POSITION_CODES: Mapping[int, str] = MappingProxyType({1: "GK", 2: "DEF", 3: "MID", 4: "FWD"})

# The five deadline-known fields a projection is assembled from, in canonical order.
SNAPSHOT_COLUMNS: Final = ("player_id", "name", "team_id", "position", "price_tenths")

# Element fields this module reads. `code` is the persistent identifier and `id` is
# the per-season one; the canonical contract keys on the former, so `id` is read only
# so a failure can be reported in the source's own terms.
_ELEMENT_FIELDS: Final = (
    "code",
    "id",
    "first_name",
    "second_name",
    "team",
    "element_type",
    "now_cost",
)
_TEAM_FIELDS: Final = ("id", "name")
_AVAILABILITY_FIELDS: Final = (
    "code",
    "element_type",
    "status",
    "chance_of_playing_next_round",
    "news_added",
)
_EVENT_FIELDS: Final = ("id", "deadline_time", "finished")
_FIXTURE_FIELDS: Final = (
    "id",
    "event",
    "team_h",
    "team_a",
    "team_h_difficulty",
    "team_a_difficulty",
    "kickoff_time",
    "finished",
    "provisional_start_time",
)

# Seasons are spelled as the starting year and the two-digit finishing year.
_SEASON_PATTERN: Final = re.compile(r"^\d{4}-\d{2}$")


@dataclass(frozen=True, slots=True)
class GameweekDeadline:
    """One gameweek's published deadline, as the captured payload stated it."""

    gameweek: int
    deadline_utc: str
    finished: bool


def _document(payload: bytes, label: str) -> Mapping[str, object]:
    if not isinstance(payload, bytes):
        raise DataSourceError(f"{label} payload must be raw bytes, got {type(payload).__name__}.")
    try:
        parsed = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise DataSourceError(f"{label} payload is not valid UTF-8 JSON: {error}") from error
    if not isinstance(parsed, dict):
        raise DataSourceError(
            f"{label} payload must be a JSON object, got {type(parsed).__name__}."
        )
    return parsed


def _records(
    document: Mapping[str, object], key: str, label: str
) -> tuple[Mapping[str, object], ...]:
    value = document.get(key)
    if not isinstance(value, list) or not value:
        raise DataSourceError(
            f"{label} payload must carry a non-empty {key!r} array, got "
            f"{type(value).__name__}. The source publishes no contract, so a missing "
            "section is treated as a changed payload rather than as an empty league."
        )
    non_objects = [index for index, record in enumerate(value) if not isinstance(record, dict)]
    if non_objects:
        raise DataSourceError(
            f"{label} payload has non-object entries in {key!r} at indexes "
            f"{format_examples(non_objects)}."
        )
    return tuple(record for record in value if isinstance(record, dict))


def _require_fields(
    records: Sequence[Mapping[str, object]], fields: Sequence[str], label: str
) -> None:
    """Reject a payload that no longer carries the fields this module reads."""

    missing = sorted({field for record in records for field in fields if field not in record})
    if missing:
        raise DataSourceError(
            f"{label} records are missing fields {missing!r} that this adapter reads. "
            "The source is undocumented and may have renamed them; the adapter has to "
            "be updated rather than allowed to emit nulls."
        )


def _integer(record: Mapping[str, object], key: str, label: str) -> int:
    value = record.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise InvalidValueError(
            f"{label} field {key!r} must be an integer, got {value!r} ({type(value).__name__})."
        )
    return value


def _text(record: Mapping[str, object], key: str, label: str) -> str:
    value = record.get(key)
    if not isinstance(value, str):
        raise InvalidValueError(
            f"{label} field {key!r} must be text, got {value!r} ({type(value).__name__})."
        )
    return value.strip()


def team_names(bootstrap: bytes) -> Mapping[int, str]:
    """Return the per-season team id to display-name mapping the payload declares.

    The canonical panel identifies a team by the platform's display name, while the
    live payload identifies it by a small integer. Resolving the integer here keeps
    the live snapshot joinable to the existing panel without redefining what
    ``team_id`` means, which is a canonical change and not this module's to make.

    Note that the integer is per-season and shifts with promotion and relegation, so
    it is resolved through the same payload it came from and never cached across
    seasons.
    """

    records = _records(_document(bootstrap, "Bootstrap"), "teams", "Team")
    _require_fields(records, _TEAM_FIELDS, "Team")

    mapping: dict[int, str] = {}
    for record in records:
        identifier = _integer(record, "id", "Team")
        name = _text(record, "name", "Team")
        if not name:
            raise InvalidValueError(f"Team {identifier} declares an empty name.")
        if identifier in mapping:
            raise DuplicateRecordsError(
                f"Bootstrap payload declares team id {identifier} more than once."
            )
        mapping[identifier] = name
    return MappingProxyType(mapping)


def _array_records(payload: bytes, label: str) -> tuple[Mapping[str, object], ...]:
    """Read a payload whose top level is an array rather than an object."""

    if not isinstance(payload, bytes):
        raise DataSourceError(f"{label} payload must be raw bytes, got {type(payload).__name__}.")
    try:
        parsed = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise DataSourceError(f"{label} payload is not valid UTF-8 JSON: {error}") from error
    if not isinstance(parsed, list) or not parsed:
        raise DataSourceError(
            f"{label} payload must be a non-empty JSON array, got {type(parsed).__name__}."
        )
    non_objects = [index for index, record in enumerate(parsed) if not isinstance(record, dict)]
    if non_objects:
        raise DataSourceError(
            f"{label} payload has non-object entries at indexes {format_examples(non_objects)}."
        )
    return tuple(record for record in parsed if isinstance(record, dict))


def _boolean(record: Mapping[str, object], key: str, label: str) -> bool:
    value = record.get(key)
    if not isinstance(value, bool):
        raise InvalidValueError(
            f"{label} field {key!r} must be a boolean, got {value!r} ({type(value).__name__})."
        )
    return value


def gameweek_deadlines(bootstrap: bytes) -> tuple[GameweekDeadline, ...]:
    """Return every gameweek deadline the payload publishes, in gameweek order."""

    records = _records(_document(bootstrap, "Bootstrap"), "events", "Event")
    _require_fields(records, _EVENT_FIELDS, "Event")

    deadlines: dict[int, GameweekDeadline] = {}
    for record in records:
        gameweek = _integer(record, "id", "Event")
        if gameweek < MIN_GAMEWEEK:
            raise InvalidValueError(
                f"Event declares gameweek {gameweek}, below the minimum {MIN_GAMEWEEK}."
            )
        if gameweek in deadlines:
            raise DuplicateRecordsError(
                f"Bootstrap payload declares gameweek {gameweek} more than once."
            )
        deadlines[gameweek] = GameweekDeadline(
            gameweek=gameweek,
            deadline_utc=normalize_utc_timestamp(
                record.get("deadline_time"), label=f"Event {gameweek} deadline_time"
            ),
            finished=_boolean(record, "finished", "Event"),
        )
    return tuple(deadlines[gameweek] for gameweek in sorted(deadlines))


def next_open_deadline(
    deadlines: Sequence[GameweekDeadline], *, as_of_utc: str
) -> GameweekDeadline:
    """Return the earliest gameweek whose deadline has not passed at ``as_of_utc``.

    The payload also carries its own ``is_next`` flag, and this deliberately ignores
    it. That flag is state the source maintains on its own schedule, and we cannot
    establish when it was last updated; comparing a published deadline against the
    instant we captured the payload is something we can show. Replay depends on that
    distinction, because the whole claim being replayed is "this was still open when
    we looked".

    A deadline exactly equal to ``as_of_utc`` counts as closed. The boundary has to
    fall one way, and treating the instant of the deadline as still open would let a
    capture taken at the moment of closing produce a squad that could not be entered.
    """

    if not deadlines:
        raise DataSourceError("No gameweek deadlines were parsed from the payload.")
    moment = as_instant(normalize_utc_timestamp(as_of_utc, label="as_of_utc"))
    for deadline in sorted(deadlines, key=lambda entry: entry.gameweek):
        if as_instant(deadline.deadline_utc) > moment:
            return deadline
    latest = max(deadlines, key=lambda entry: entry.gameweek)
    raise DataSourceError(
        f"Every published deadline had closed by {moment.isoformat()}; the last one was "
        f"gameweek {latest.gameweek} at {latest.deadline_utc}. The season is over, or the "
        "capture is older than the payload it claims to describe."
    )


def availability_snapshot(bootstrap: bytes) -> pd.DataFrame:
    """Read what the source says about each player's availability, as captured.

    Deliberately a separate table from the player snapshot. These fields never enter a
    model matrix: the archive records them after the fact and their as-of time cannot be
    recovered, so a coefficient fitted on them would rest on information nobody held at
    the deadline. What makes them usable at all is that *we* captured them, at an instant
    we stamped ourselves, before the deadline they apply to.

    Observed in the 2026-27 pre-season capture: 584 players carry statuses `a` (514),
    `i` (35), `u` (18), `d` (14) and `s` (3), and the chance-of-playing field is quantised
    to 0, 75 and 100 or absent. The vocabulary is not documented anywhere, so a status
    this adapter has not seen is surfaced rather than mapped to a guess.
    """

    records = _records(_document(bootstrap, "Bootstrap"), "elements", "Element")
    _require_fields(records, _AVAILABILITY_FIELDS, "Element")

    rows: list[dict[str, object]] = []
    for record in records:
        if _integer(record, "element_type", "Element") not in POSITION_CODES:
            continue
        chance = record.get("chance_of_playing_next_round")
        if chance is not None and (isinstance(chance, bool) or not isinstance(chance, int)):
            raise InvalidValueError(
                f"chance_of_playing_next_round must be an integer or absent, got {chance!r}."
            )
        rows.append(
            {
                "player_id": _integer(record, "code", "Element"),
                "status": _text(record, "status", "Element"),
                "chance_of_playing": pd.NA if chance is None else int(chance),
                "news_added_utc": (
                    pd.NA
                    if record.get("news_added") is None
                    else normalize_utc_timestamp(
                        record.get("news_added"), label="Element news_added"
                    )
                ),
            }
        )

    if not rows:
        raise DataSourceError("Bootstrap payload declares no squad-eligible players.")

    frame = pd.DataFrame(
        rows, columns=["player_id", "status", "chance_of_playing", "news_added_utc"]
    )
    frame["player_id"] = frame["player_id"].astype("int64")
    frame["status"] = frame["status"].astype("string")
    frame["chance_of_playing"] = frame["chance_of_playing"].astype("Int64")
    frame["news_added_utc"] = frame["news_added_utc"].astype("string")
    return frame.sort_values("player_id", kind="stable").reset_index(drop=True)


def team_codes(bootstrap: bytes) -> Mapping[int, int]:
    """Return the per-season team id to persistent team code mapping.

    The fixture table identifies a club by its persistent code, because the integer
    the payload uses is assigned per season and denotes different clubs in different
    seasons.
    """

    records = _records(_document(bootstrap, "Bootstrap"), "teams", "Team")
    _require_fields(records, ("id", "code"), "Team")

    mapping: dict[int, int] = {}
    for record in records:
        identifier = _integer(record, "id", "Team")
        if identifier in mapping:
            raise DuplicateRecordsError(
                f"Bootstrap payload declares team id {identifier} more than once."
            )
        mapping[identifier] = _integer(record, "code", "Team")
    return MappingProxyType(mapping)


def _require_season(season: object) -> str:
    if not isinstance(season, str) or not _SEASON_PATTERN.match(season):
        raise InvalidValueError(f"season must be spelled like '2026-27', got {season!r}.")
    return season


def _fixture_status(record: Mapping[str, object], label: str) -> str:
    if _boolean(record, "finished", label):
        return "final"
    return "provisional" if _boolean(record, "provisional_start_time", label) else "scheduled"


def fixture_snapshot(
    fixtures: bytes,
    bootstrap: bytes,
    *,
    season: str,
    snapshot_id: str,
    captured_at_utc: str,
) -> pd.DataFrame:
    """Build the fixture table from a captured pair of payloads.

    Unlike an archive backfill, a live capture can fill both provenance fields: the
    capture instant is ours, and the deadline comes from the payload's own event list.
    That is the difference the fixture table's nullable columns exist to record, and it
    is visible per row rather than inferred from which source a table came from.

    ``season`` is supplied rather than guessed. The payload does not state it in a
    field this adapter is willing to depend on, so the caller declares it and the
    declaration is checked against the first gameweek's deadline year — a typo that
    would file a capture under the wrong season is caught rather than stored.

    Fixtures with no gameweek are excluded, exactly as in the archive path: that is how
    a postponement awaiting refixturing appears, and a club whose match was postponed
    genuinely has no fixture that gameweek.
    """

    declared_season = _require_season(season)
    codes = team_codes(bootstrap)
    deadlines = {entry.gameweek: entry.deadline_utc for entry in gameweek_deadlines(bootstrap)}
    captured_at = normalize_utc_timestamp(captured_at_utc, label="captured_at_utc")

    first_gameweek = min(deadlines)
    deadline_year = as_instant(deadlines[first_gameweek]).year
    if str(deadline_year) != declared_season[:4]:
        raise InvalidValueError(
            f"season {declared_season!r} does not match the payload, whose earliest "
            f"deadline falls in {deadline_year}."
        )

    records = _array_records(fixtures, "Fixture")
    _require_fields(records, _FIXTURE_FIELDS, "Fixture")

    rows: list[dict[str, object]] = []
    unknown_teams: list[int] = []
    unknown_gameweeks: list[int] = []
    for record in records:
        event = record.get("event")
        if event is None:
            continue
        gameweek = _integer(record, "event", "Fixture")
        if gameweek not in deadlines:
            unknown_gameweeks.append(gameweek)
            continue
        home = _integer(record, "team_h", "Fixture")
        away = _integer(record, "team_a", "Fixture")
        missing_teams = [side for side in (home, away) if side not in codes]
        if missing_teams:
            unknown_teams.extend(missing_teams)
            continue
        label = f"Fixture {_integer(record, 'id', 'Fixture')}"
        kickoff = record.get("kickoff_time")
        shared: dict[str, object] = {
            "snapshot_id": snapshot_id,
            "captured_at_utc": captured_at,
            "season": declared_season,
            "gameweek": gameweek,
            "fixture_id": _integer(record, "id", "Fixture"),
            "kickoff_time_utc": (
                pd.NA
                if kickoff is None
                else normalize_utc_timestamp(kickoff, label=f"{label} kickoff_time")
            ),
            "deadline_timestamp_utc": deadlines[gameweek],
            "status": _fixture_status(record, label),
        }
        rows.append(
            {
                **shared,
                "team_id": codes[home],
                "opponent_team_id": codes[away],
                "is_home": True,
                "fixture_difficulty": record.get("team_h_difficulty"),
            }
        )
        rows.append(
            {
                **shared,
                "team_id": codes[away],
                "opponent_team_id": codes[home],
                "is_home": False,
                "fixture_difficulty": record.get("team_a_difficulty"),
            }
        )

    if unknown_teams:
        raise InvalidValueError(
            "Fixture payload references teams the bootstrap payload does not declare: "
            f"{format_examples(sorted(set(unknown_teams)))}."
        )
    if unknown_gameweeks:
        raise InvalidValueError(
            "Fixture payload references gameweeks the bootstrap payload does not "
            f"publish: {format_examples(sorted(set(unknown_gameweeks)))}."
        )
    if not rows:
        raise DataSourceError("Fixture payload produced no rows; every fixture lacked a gameweek.")

    frame = pd.DataFrame(rows, columns=list(FIXTURE_COLUMNS))
    for column in ("gameweek", "fixture_id", "team_id", "opponent_team_id"):
        frame[column] = frame[column].astype("int64")
    frame["is_home"] = frame["is_home"].astype("boolean")
    frame["fixture_difficulty"] = pd.to_numeric(
        frame["fixture_difficulty"], errors="coerce"
    ).astype("Int64")
    for column in (
        "snapshot_id",
        "season",
        "kickoff_time_utc",
        "status",
        "captured_at_utc",
        "deadline_timestamp_utc",
    ):
        frame[column] = frame[column].astype("string")
    return validate_fixture_snapshot(frame)


def player_snapshot(bootstrap: bytes) -> pd.DataFrame:
    """Build the deadline-known player table from a captured bootstrap payload.

    Rows are the squad-eligible players the platform is currently offering. Managers
    and any other non-player entry are excluded. The result is sorted by
    ``player_id`` so the output does not depend on the order the source happened to
    serialise, and prices pass through the same integer-tenths conversion the
    canonical layer uses, so a fractional or missing price is rejected here rather
    than turning the column to float further downstream.

    Availability is deliberately absent. ``status`` and the chance-of-playing fields
    are in the captured payload and stay there: they are applied later as an explicit
    inference rule, never as a column of this table.
    """

    names = team_names(bootstrap)
    records = _records(_document(bootstrap, "Bootstrap"), "elements", "Element")
    _require_fields(records, _ELEMENT_FIELDS, "Element")

    rows: list[dict[str, object]] = []
    unknown_teams: list[int] = []
    for record in records:
        element_type = _integer(record, "element_type", "Element")
        if element_type not in POSITION_CODES:
            continue
        team = _integer(record, "team", "Element")
        if team not in names:
            unknown_teams.append(team)
            continue
        first = _text(record, "first_name", "Element")
        second = _text(record, "second_name", "Element")
        full_name = f"{first} {second}".strip()
        if not full_name:
            raise InvalidValueError(
                f"Element with code {_integer(record, 'code', 'Element')} has no name."
            )
        rows.append(
            {
                "player_id": _integer(record, "code", "Element"),
                "name": full_name,
                "team_id": names[team],
                "position": POSITION_CODES[element_type],
                "price_tenths": _integer(record, "now_cost", "Element"),
            }
        )

    if unknown_teams:
        raise InvalidValueError(
            "Bootstrap payload has players on teams it does not declare: "
            f"{format_examples(sorted(set(unknown_teams)))}. A player whose club is "
            "unknown cannot be placed in a squad or joined to a fixture."
        )
    if not rows:
        raise DataSourceError(
            "Bootstrap payload declares no squad-eligible players. Position codes "
            f"{sorted(POSITION_CODES)} produced no rows, which means the platform's "
            "position encoding has changed."
        )

    frame = pd.DataFrame(rows, columns=list(SNAPSHOT_COLUMNS))
    duplicated = frame.loc[frame["player_id"].duplicated(), "player_id"].tolist()
    if duplicated:
        raise DuplicateRecordsError(
            "Bootstrap payload declares the same persistent player code more than "
            f"once: {format_examples(duplicated)}."
        )

    frame["position"] = normalize_positions(frame["position"])
    frame["price_tenths"] = to_price_tenths(frame["price_tenths"], unit="tenths")
    frame["name"] = frame["name"].astype("string")
    frame["team_id"] = frame["team_id"].astype("string")
    return frame.sort_values("player_id", kind="stable").reset_index(drop=True)
