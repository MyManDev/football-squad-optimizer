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


def _positive(value: int, label: str) -> int:
    """An identifier the source only ever publishes as a positive integer."""

    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise InvalidValueError(f"{label} must be a positive integer, got {value!r}.")
    return value


# Per-entry and per-league payloads. Unlike the two above there is one of each per
# registered entry, so the names are built rather than named. They stay inside the
# snapshot's payload-name grammar (lowercase, digits, hyphens and dots) so a capture
# directory remains readable without this module.


def entry_payload(entry_id: int) -> str:
    """Payload name for one entry's summary document."""

    return f"entry-{_positive(entry_id, 'entry id')}.json"


def entry_history_payload(entry_id: int) -> str:
    """Payload name for one entry's season history."""

    return f"entry-{_positive(entry_id, 'entry id')}-history.json"


def entry_picks_payload(entry_id: int, gameweek: int) -> str:
    """Payload name for one entry's picks at one gameweek."""

    return (
        f"entry-{_positive(entry_id, 'entry id')}"
        f"-picks-gw{_positive(gameweek, 'gameweek'):02d}.json"
    )


def league_standings_payload(league_id: int) -> str:
    """Payload name for a classic league's standings page."""

    return f"league-{_positive(league_id, 'league id')}-standings.json"


def live_payload(gameweek: int) -> str:
    """Payload name for one gameweek's live scoring document."""

    return f"event-gw{_positive(gameweek, 'gameweek'):02d}-live.json"


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


# --- season-relative element fields ------------------------------------------
#
# The element records carry cumulative counters -- minutes, total_points, starts and
# the rest -- and the number in them is not a property of the payload alone. Measured
# on the real captures (docs/capture_season_phase.md): in a capture taken before the
# opening deadline, 454 of 461 players carry *the previous season's* totals exactly,
# and after the season's first kick-off the platform resets them and begins the new
# season. Raya reads 3330 minutes and 162 points in the 2026-08-20 capture and 90
# minutes and 6 points afterwards; Saliba, who did not play, drops from 2614 and 137
# to zero.
#
# So the meaning of these fields flips at one instant, nothing in the payload states
# which side of it the capture sits on, and both readings are plausible numbers. That
# is a silent-wrong-answer shape, which is why they are named here and reached through
# one guarded entry point rather than read wherever they are wanted.
SEASON_RELATIVE_ELEMENT_FIELDS: Final = (
    "minutes",
    "total_points",
    "starts",
    "goals_scored",
    "assists",
    "clean_sheets",
    "goals_conceded",
    "saves",
    "bonus",
    "bps",
    "own_goals",
)

# What a capture's cumulative counters describe.
#
# `unobserved_transition` is not squeamishness. The reset happens somewhere between
# the opening deadline and the first kick-off, and no capture exists inside that
# ninety-minute window, so which of the two boundaries triggers it has not been
# observed. Both readings are plausible there and neither is measured, so that window
# refuses instead of guessing.
SEASON_PHASES: Final = ("prior_season", "unobserved_transition", "current_season")


@dataclass(frozen=True, slots=True)
class CaptureSeasonPhase:
    """Which season a capture's cumulative counters belong to, and the evidence."""

    phase: str
    captured_at_utc: str
    opening_deadline_utc: str
    first_kickoff_utc: str

    def __post_init__(self) -> None:
        if self.phase not in SEASON_PHASES:
            raise InvalidValueError(
                f"Unknown capture season phase {self.phase!r}; expected one of "
                f"{list(SEASON_PHASES)!r}."
            )

    @property
    def describes_current_season(self) -> bool:
        """Whether the counters may be read as this season's played history."""

        return self.phase == "current_season"


def _first_kickoff_utc(fixtures: bytes) -> str:
    """Return the earliest published kick-off, which is when the counters reset."""

    records = _array_records(fixtures, "Fixtures")
    kickoffs = [
        normalize_utc_timestamp(record.get("kickoff_time"), label="Fixture kickoff_time")
        for record in records
        if record.get("kickoff_time") is not None
    ]
    if not kickoffs:
        raise DataSourceError(
            "The fixtures payload publishes no kick-off time, so the instant the "
            "season's cumulative counters reset cannot be established."
        )
    return min(kickoffs)


def capture_season_phase(
    bootstrap: bytes, fixtures: bytes, *, captured_at_utc: str
) -> CaptureSeasonPhase:
    """Decide which season a capture's cumulative counters describe.

    Derived from the capture's own two payloads rather than accepted from the caller.
    A caller that could state the phase could state it wrongly, and the whole point of
    naming these fields is that a wrong answer here is not visible downstream.
    """

    captured = normalize_utc_timestamp(captured_at_utc, label="captured_at_utc")
    deadlines = gameweek_deadlines(bootstrap)
    if not deadlines:
        raise DataSourceError("The bootstrap payload publishes no gameweek deadlines.")
    opening = deadlines[0].deadline_utc
    kickoff = _first_kickoff_utc(fixtures)
    moment = as_instant(captured)
    if moment < as_instant(opening):
        phase = "prior_season"
    elif moment < as_instant(kickoff):
        phase = "unobserved_transition"
    else:
        phase = "current_season"
    return CaptureSeasonPhase(
        phase=phase,
        captured_at_utc=captured,
        opening_deadline_utc=opening,
        first_kickoff_utc=kickoff,
    )


def in_season_totals(bootstrap: bytes, fixtures: bytes, *, captured_at_utc: str) -> pd.DataFrame:
    """Return this season's played history per player, or refuse to guess.

    Keyed on the persistent ``player_id`` so it joins the canonical contract rather
    than the platform's per-season integer. Only squad-eligible players are returned,
    on the same grounds :func:`player_snapshot` uses.

    The refusal is the feature. Before the season's counters reset these numbers are
    the *previous* season's, and returning them as in-season history would put a full
    prior campaign's minutes into a second-gameweek feature without anything looking
    wrong.
    """

    phase = capture_season_phase(bootstrap, fixtures, captured_at_utc=captured_at_utc)
    if not phase.describes_current_season:
        raise DataSourceError(
            f"A capture taken at {phase.captured_at_utc} is {phase.phase!r}: its "
            "cumulative counters do not describe the current season, so it carries no "
            "in-season history. The counters reset between the opening deadline "
            f"({phase.opening_deadline_utc}) and the first kick-off "
            f"({phase.first_kickoff_utc}); capture after the first kick-off."
        )

    records = _records(_document(bootstrap, "Bootstrap"), "elements", "Element")
    _require_fields(records, _ELEMENT_FIELDS, "Element")
    _require_fields(records, SEASON_RELATIVE_ELEMENT_FIELDS, "Element")

    rows: list[dict[str, object]] = []
    for record in records:
        if _integer(record, "element_type", "Element") not in POSITION_CODES:
            continue
        row: dict[str, object] = {"player_id": _integer(record, "code", "Element")}
        for field_name in SEASON_RELATIVE_ELEMENT_FIELDS:
            row[field_name] = _integer(record, field_name, "Element")
        rows.append(row)
    if not rows:
        raise DataSourceError("The bootstrap payload contains no squad-eligible players.")

    table = pd.DataFrame.from_records(rows)
    duplicates = table.loc[table["player_id"].duplicated(), "player_id"].tolist()
    if duplicates:
        raise DuplicateRecordsError(
            f"Bootstrap payload repeats player codes: {format_examples(duplicates)}."
        )
    ordered = ("player_id", *SEASON_RELATIVE_ELEMENT_FIELDS)
    return table.loc[:, list(ordered)].sort_values("player_id").reset_index(drop=True)


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


# --- registered entries and their league ---------------------------------------------
#
# Paths, not URLs. This module never fetches; the platform adapter owns the base URL and
# the transport, so declaring where a payload comes from stays separate from going to get
# it. Everything below reads bytes that are already on disk, like the rest of the module.

_ENTRY_FIELDS: Final = ("id", "name", "current_event")
_PICK_FIELDS: Final = ("element", "position", "is_captain", "is_vice_captain", "multiplier")
_CHIP_FIELDS: Final = ("name", "event")
_STANDING_FIELDS: Final = ("entry", "entry_name", "player_name", "rank")
_LIVE_ELEMENT_FIELDS: Final = ("id", "stats")

# The squad the platform publishes: fifteen picks, the first eleven of which start.
_SQUAD_SIZE: Final = 15
_STARTING_SIZE: Final = 11


def entry_endpoint_paths(entry_ids: Sequence[int], *, gameweek: int) -> Mapping[str, str]:
    """Payload name to API path for every registered entry at one gameweek.

    Three documents per entry, because they answer three different questions and the
    platform publishes them separately: the summary names the team, the history carries
    the chips a planner's windows need, and the picks are the squad itself.

    The gameweek is the one whose picks are *known*. Per the time-of-knowledge rule in
    ``docs/data_contract.md``, the picks for gameweek N are only complete once N has been
    played, so the capture taken before the N+1 deadline reads ``event/N/picks``.
    """

    week = _positive(gameweek, "gameweek")
    identifiers = [_positive(entry_id, "entry id") for entry_id in entry_ids]
    duplicated = sorted({i for i in identifiers if identifiers.count(i) > 1})
    if duplicated:
        raise InvalidValueError(
            f"Entry ids must be distinct; {format_examples(duplicated)} appear more than once."
        )
    paths: dict[str, str] = {}
    for entry_id in identifiers:
        paths[entry_payload(entry_id)] = f"entry/{entry_id}/"
        paths[entry_history_payload(entry_id)] = f"entry/{entry_id}/history/"
        paths[entry_picks_payload(entry_id, week)] = f"entry/{entry_id}/event/{week}/picks/"
    return MappingProxyType(paths)


def league_standings_endpoint_path(league_id: int) -> Mapping[str, str]:
    """Payload name to API path for a classic league's first standings page."""

    identifier = _positive(league_id, "league id")
    return MappingProxyType(
        {league_standings_payload(identifier): f"leagues-classic/{identifier}/standings/"}
    )


def live_endpoint_path(gameweek: int) -> Mapping[str, str]:
    """Payload name to API path for one gameweek's live scoring document."""

    week = _positive(gameweek, "gameweek")
    return MappingProxyType({live_payload(week): f"event/{week}/live/"})


@dataclass(frozen=True, slots=True)
class LiveEventPoints:
    """What a gameweek's players have scored so far, and how far from final it is.

    The points are the platform's own running total per player. They are useful before a
    gameweek closes and they are *not* the settled outcome, so the two facts that decide
    what may be claimed from them travel in the same object rather than in a comment:

    - ``bonus_confirmed`` is false until every one of the gameweek's fixtures is finished.
      The platform adds bonus to a player's total only when his fixture finishes, so a
      score read earlier is short by up to three points per player, and short by different
      amounts for different players. That is not noise that averages out.
    - ``fixtures_finished`` against ``fixtures_total`` says how much of the gameweek is
      actually in the number, which is the difference between "your team scored 41" and
      "your team has scored 41 of what will be a larger figure".
    """

    gameweek: int
    points_by_player: Mapping[int, int]
    bonus_confirmed: bool
    fixtures_finished: int
    fixtures_total: int
    source_snapshot_id: str | None = None

    def __post_init__(self) -> None:
        if not self.points_by_player:
            raise InvalidValueError(
                f"Live payload for gameweek {self.gameweek} carries no player points."
            )
        if self.fixtures_total < 1:
            raise InvalidValueError(
                f"Gameweek {self.gameweek} has no fixtures in the captured fixtures "
                "payload, so a live score for it describes nothing."
            )
        if not 0 <= self.fixtures_finished <= self.fixtures_total:
            raise InvalidValueError(
                f"Gameweek {self.gameweek} reports {self.fixtures_finished} finished "
                f"fixtures of {self.fixtures_total}."
            )
        if self.bonus_confirmed and self.fixtures_finished != self.fixtures_total:
            raise InvalidValueError(
                f"Gameweek {self.gameweek} claims confirmed bonus while "
                f"{self.fixtures_total - self.fixtures_finished} of its fixtures are "
                "unfinished. Bonus is confirmed per fixture, so the claim cannot hold "
                "before all of them are."
            )


def fpl_live_event_points(
    live: bytes,
    fixtures: bytes,
    *,
    gameweek: int,
    source_snapshot_id: str | None = None,
) -> LiveEventPoints:
    """Return one gameweek's running player points from its captured live document.

    Both documents are required, and the second one is the point. The live payload is a
    bare ``{"elements": [...]}`` with **no gameweek of its own** -- the platform identifies
    it only by the URL it was fetched from. So this module cannot verify that a payload
    named for gameweek N describes gameweek N, and pretending otherwise would be worse
    than saying it. What the fixtures payload does give is the gameweek's own progress,
    which is the caveat a reader of these points actually needs.

    Auto-substitutions are deliberately not modelled here. This returns points per player;
    which eleven those points are counted for is a decision the ledger owns, and it scores
    the eleven that were named because that is what the projection was for.
    """

    week = _positive(gameweek, "gameweek")
    records = _records(_document(live, "Live"), "elements", "Live element")
    _require_fields(records, _LIVE_ELEMENT_FIELDS, "Live element")

    points: dict[int, int] = {}
    for record in records:
        player = _integer(record, "id", "Live element")
        stats = record.get("stats")
        if not isinstance(stats, dict):
            raise DataSourceError(
                f"Live element {player} carries a {type(stats).__name__} 'stats' section "
                "rather than an object; the adapter reads its total_points."
            )
        if player in points:
            raise DuplicateRecordsError(
                f"Live payload for gameweek {week} declares player {player} more than once."
            )
        points[player] = _integer(stats, "total_points", f"Live element {player} stats")

    finished, total = _gameweek_fixture_progress(fixtures, gameweek=week)
    return LiveEventPoints(
        gameweek=week,
        points_by_player=MappingProxyType(dict(sorted(points.items()))),
        bonus_confirmed=finished == total,
        fixtures_finished=finished,
        fixtures_total=total,
        source_snapshot_id=source_snapshot_id,
    )


def _gameweek_fixture_progress(fixtures: bytes, *, gameweek: int) -> tuple[int, int]:
    """How many of one gameweek's fixtures are finished, and how many there are."""

    records = _array_records(fixtures, "Fixture")
    _require_fields(records, ("event", "finished"), "Fixture")
    mine = [record for record in records if record.get("event") == gameweek]
    finished = sum(1 for record in mine if _boolean(record, "finished", "Fixture"))
    return finished, len(mine)


@dataclass(frozen=True, slots=True)
class LeagueStanding:
    """One member of a classic league, as the standings page reports them."""

    entry_id: int
    entry_name: str
    player_name: str
    rank: int


def fpl_league_standings(standings: bytes, *, league_id: int) -> tuple[LeagueStanding, ...]:
    """Return a classic league's members, in the order the page ranks them.

    Refuses a truncated league rather than returning part of one. The standings page is
    paginated and a capture holds its first page; a league large enough to spill over
    would otherwise seed a registry that silently omits members, which is the kind of gap
    that surfaces weeks later as a missing recommendation.
    """

    identifier = _positive(league_id, "league id")
    document = _document(standings, "League standings")
    league = document.get("league")
    if isinstance(league, dict):
        declared = league.get("id")
        if isinstance(declared, int) and not isinstance(declared, bool) and declared != identifier:
            raise DataSourceError(
                f"League standings payload declares league {declared}, not {identifier}. "
                "A payload named for one league and describing another would seed the "
                "wrong registry."
            )
    section = document.get("standings")
    if not isinstance(section, dict):
        raise DataSourceError(
            "League standings payload must carry a 'standings' object, got "
            f"{type(section).__name__}."
        )
    if section.get("has_next") is True:
        raise DataSourceError(
            f"League {identifier} has more standings pages than this capture holds. Only "
            "the first page is captured, so seeding from it would omit members; capture "
            "the remaining pages before reading this league."
        )
    records = _records(section, "results", "League standing")
    _require_fields(records, _STANDING_FIELDS, "League standing")

    members: list[LeagueStanding] = []
    seen: set[int] = set()
    for record in records:
        entry_id = _positive(_integer(record, "entry", "League standing"), "entry id")
        if entry_id in seen:
            raise DuplicateRecordsError(
                f"League {identifier} standings list entry {entry_id} more than once."
            )
        seen.add(entry_id)
        members.append(
            LeagueStanding(
                entry_id=entry_id,
                entry_name=_text(record, "entry_name", "League standing"),
                player_name=_text(record, "player_name", "League standing"),
                rank=_integer(record, "rank", "League standing"),
            )
        )
    return tuple(members)


def entry_label(entry: bytes, *, entry_id: int) -> str:
    """Return the team name the entry summary publishes, for the registry's label."""

    identifier = _positive(entry_id, "entry id")
    document = _document(entry, "Entry")
    _require_fields((document,), _ENTRY_FIELDS, "Entry")
    declared = _integer(document, "id", "Entry")
    if declared != identifier:
        raise DataSourceError(f"Entry payload declares entry {declared}, not {identifier}.")
    name = _text(document, "name", "Entry")
    if not name:
        raise InvalidValueError(f"Entry {identifier} declares an empty team name.")
    return name


def _chips_used(history: bytes, *, entry_id: int) -> Mapping[str, tuple[int, ...]]:
    """Chip name to the gameweeks it was played, from the entry's season history."""

    document = _document(history, "Entry history")
    chips = document.get("chips")
    if not isinstance(chips, list):
        raise DataSourceError(
            f"Entry {entry_id} history must carry a 'chips' array, got "
            f"{type(chips).__name__}. An entry that has played no chip publishes an empty "
            "array, so a missing section is a changed payload rather than an unused chip."
        )
    records = tuple(record for record in chips if isinstance(record, dict))
    if len(records) != len(chips):
        raise DataSourceError(f"Entry {entry_id} history has non-object entries in 'chips'.")
    _require_fields(records, _CHIP_FIELDS, "Entry chip")
    played: dict[str, list[int]] = {}
    for record in records:
        name = _text(record, "name", "Entry chip")
        if not name:
            raise InvalidValueError(f"Entry {entry_id} played a chip with an empty name.")
        played.setdefault(name, []).append(_integer(record, "event", "Entry chip"))
    return MappingProxyType({name: tuple(sorted(events)) for name, events in played.items()})


@dataclass(frozen=True, slots=True)
class EntryPicksRecord:
    """One entry's squad at one gameweek, as the public endpoints report it.

    The twin of ``squadopt.application.entries.EntryPicks``, declared here so the layer
    direction stays application to data. The field names match so the application side
    maps it without a translation table.
    """

    entry_id: int
    season: str
    gameweek: int
    squad: tuple[int, ...]
    starting_xi: tuple[int, ...]
    captain: int
    bank_tenths: int
    free_transfers: int
    free_transfers_known: bool
    chips_used: Mapping[str, tuple[int, ...]]
    purchase_prices: Mapping[int, int]
    purchase_prices_known: bool
    source_snapshot_id: str | None = None

    def __post_init__(self) -> None:
        if len(self.squad) != _SQUAD_SIZE or len(set(self.squad)) != _SQUAD_SIZE:
            raise InvalidValueError(
                f"Entry {self.entry_id} gameweek {self.gameweek} must hold {_SQUAD_SIZE} "
                f"distinct players, got {len(self.squad)} ({len(set(self.squad))} distinct)."
            )
        if len(self.starting_xi) != _STARTING_SIZE or not set(self.starting_xi) <= set(self.squad):
            raise InvalidValueError(
                f"Entry {self.entry_id} gameweek {self.gameweek} must start "
                f"{_STARTING_SIZE} of its own squad."
            )
        if self.captain not in self.starting_xi:
            raise InvalidValueError(
                f"Entry {self.entry_id} gameweek {self.gameweek} names a captain who is "
                "not in the starting eleven."
            )
        if self.bank_tenths < 0:
            raise InvalidValueError(
                f"Entry {self.entry_id} reports a negative bank of {self.bank_tenths}."
            )


def fpl_entry_picks(
    picks: bytes,
    history: bytes,
    *,
    entry_id: int,
    season: str,
    gameweek: int,
    source_snapshot_id: str | None = None,
) -> EntryPicksRecord:
    """Return one entry's squad at one gameweek from its two captured documents.

    Two limits are recorded rather than papered over, because both change what a consumer
    may claim.

    ``purchase_prices`` is empty and flagged unknown: the public endpoints publish no
    purchase price, so a squad built from this values every player at his current price,
    which overstates the budget for anyone who has risen since he was bought.

    ``free_transfers`` is the rule-implied floor of one, flagged unknown. The endpoints
    never state the banked count. It is *derivable* from the history's per-event transfers
    and costs, but only through a model of the banking rules -- which changed in 2024-25 --
    and of the chip weeks that consume no transfer. That model is a reviewed decision with
    its own tests, not a side effect of parsing a capture, so this adapter reports the
    honest unknown instead of a plausible number.
    """

    identifier = _positive(entry_id, "entry id")
    week = _positive(gameweek, "gameweek")
    document = _document(picks, "Entry picks")
    records = _records(document, "picks", "Entry pick")
    _require_fields(records, _PICK_FIELDS, "Entry pick")

    by_position: dict[int, int] = {}
    captains: list[int] = []
    for record in records:
        position = _integer(record, "position", "Entry pick")
        element = _positive(_integer(record, "element", "Entry pick"), "element id")
        if position in by_position:
            raise DuplicateRecordsError(
                f"Entry {identifier} gameweek {week} lists squad position {position} twice."
            )
        by_position[position] = element
        if _boolean(record, "is_captain", "Entry pick"):
            captains.append(element)

    if set(by_position) != set(range(1, _SQUAD_SIZE + 1)):
        raise DataSourceError(
            f"Entry {identifier} gameweek {week} must list squad positions 1 to "
            f"{_SQUAD_SIZE}; got {sorted(by_position)}."
        )
    if len(captains) != 1:
        raise DataSourceError(
            f"Entry {identifier} gameweek {week} names {len(captains)} captains; the "
            "platform names exactly one."
        )

    squad = tuple(by_position[position] for position in sorted(by_position))
    entry_history = document.get("entry_history")
    if not isinstance(entry_history, dict):
        raise DataSourceError(
            f"Entry {identifier} gameweek {week} picks must carry an 'entry_history' "
            f"object, got {type(entry_history).__name__}."
        )

    return EntryPicksRecord(
        entry_id=identifier,
        season=_require_season(season),
        gameweek=week,
        squad=squad,
        starting_xi=squad[:_STARTING_SIZE],
        captain=captains[0],
        bank_tenths=_integer(entry_history, "bank", "Entry history"),
        free_transfers=1,
        free_transfers_known=False,
        chips_used=_chips_used(history, entry_id=identifier),
        purchase_prices=MappingProxyType({}),
        purchase_prices_known=False,
        source_snapshot_id=source_snapshot_id,
    )
