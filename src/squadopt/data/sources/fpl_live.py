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


class IncompleteLiveHistoryError(DataSourceError):
    """A prior gameweek is present but not yet a final component-model outcome."""


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


def league_standings_page_payload(league_id: int, page: int) -> str:
    """Payload name for one explicitly numbered classic-league standings page."""

    return (
        f"league-{_positive(league_id, 'league id')}-standings-"
        f"page-{_positive(page, 'standings page'):02d}.json"
    )


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


def player_codes(bootstrap: bytes) -> Mapping[int, int]:
    """Return the per-season element id to persistent player code mapping.

    The same problem as :func:`team_codes` and the same shape, one level down. The
    per-entry endpoints name a player by his **element** id, which is assigned per season;
    the canonical panel, the prices, the projection and the ledger all name him by
    ``code``, which survives a transfer window. Both are plain integers, so handing one
    where the other is meant does not raise -- it **matches nothing**, and the caller sees
    a full squad of players it cannot price. That is the failure
    :func:`squadopt.data.identity.reconcile_player_identity` was written to turn into a
    stated one, and its refusal message names this exact confusion.

    Two things this deliberately is not.

    It is **not a roster**. Unlike :func:`player_snapshot` it does not drop entries whose
    ``element_type`` is outside :data:`POSITION_CODES`, because it is a translation table:
    every element the payload names can appear in a document that needs translating, and
    silently omitting one would surface downstream as "the capture does not name element
    N" -- blaming a player for a filter applied here.

    It is **not tolerant of a thinner payload**. A missing or renamed field stops the run
    and names itself, rather than yielding a shorter mapping: a translation table that is
    quietly incomplete is worse than none, because the lookups that survive it look
    correct. For the same reason a repeated ``code`` is refused as well as a repeated
    ``id`` -- a duplicate key makes the mapping ambiguous, and a duplicate value silently
    merges two people into one identity, which is the more expensive half.
    """

    records = _records(_document(bootstrap, "Bootstrap"), "elements", "Element")
    _require_fields(records, ("id", "code"), "Element")

    mapping: dict[int, int] = {}
    owner: dict[int, int] = {}
    for record in records:
        identifier = _integer(record, "id", "Element")
        if identifier in mapping:
            raise DuplicateRecordsError(
                f"Bootstrap payload declares element id {identifier} more than once."
            )
        code = _integer(record, "code", "Element")
        if code in owner:
            raise DuplicateRecordsError(
                f"Bootstrap payload gives player code {code} to element ids "
                f"{owner[code]} and {identifier}; one code is one player, so a repeated "
                "code would merge two of them into one identity."
            )
        mapping[identifier] = code
        owner[code] = identifier
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
_HISTORY_EVENT_FIELDS: Final = ("event", "points", "total_points")
# The two flags that together mean "this week's points are final". `finished` alone is what
# the ledger gates realized outcomes on; `data_checked` is the one that flips when bonus is
# added, and gameweek 1 sat finished-but-unchecked for eight and a half hours with every
# fixture already played. Both live in the same captured document, so the stricter reading
# costs one key.
_SCORED_EVENT_FIELDS: Final = ("id", "finished", "data_checked")

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


def league_standings_page_endpoint_path(league_id: int, page: int) -> Mapping[str, str]:
    """Payload name to API path for one numbered classic-league standings page."""

    identifier = _positive(league_id, "league id")
    page_number = _positive(page, "standings page")
    return MappingProxyType(
        {
            league_standings_page_payload(identifier, page_number): (
                f"leagues-classic/{identifier}/standings/?page_standings={page_number}"
            )
        }
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

    ``minutes_by_player`` travels here rather than in an object of its own because the two
    come out of one ``stats`` blob and because neither is sufficient alone: the platform's
    own score replaces a starter who played no minutes with a bench player, so a caller
    holding the points and not the minutes cannot say which eleven the points belong to.
    Which is why the key sets must match exactly -- a player whose minutes were dropped
    would read as "did not play", and the rule would field a substitute for a man who was
    on the pitch. This object supplies that rule's inputs; it does not apply it.
    """

    gameweek: int
    points_by_player: Mapping[int, int]
    minutes_by_player: Mapping[int, int]
    bonus_confirmed: bool
    fixtures_finished: int
    fixtures_total: int
    source_snapshot_id: str | None = None

    def __post_init__(self) -> None:
        if not self.points_by_player:
            raise InvalidValueError(
                f"Live payload for gameweek {self.gameweek} carries no player points."
            )
        if set(self.minutes_by_player) != set(self.points_by_player):
            scored = set(self.points_by_player) - set(self.minutes_by_player)
            timed = set(self.minutes_by_player) - set(self.points_by_player)
            raise InvalidValueError(
                f"Gameweek {self.gameweek} reports points and minutes for different "
                f"players: {len(scored)} with points and no minutes "
                f"({format_examples(sorted(scored))}), {len(timed)} the other way "
                f"({format_examples(sorted(timed))}). A missing minute count reads as "
                "'did not play', which is how a substitution gets fabricated."
            )
        negative = sorted(player for player, played in self.minutes_by_player.items() if played < 0)
        if negative:
            raise InvalidValueError(
                f"Gameweek {self.gameweek} reports negative minutes for "
                f"{format_examples(negative)}."
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
    """Return one gameweek's running player points and minutes from its captured live document.

    Both documents are required, and the second one is the point. The live payload is a
    bare ``{"elements": [...]}`` with **no gameweek of its own** -- the platform identifies
    it only by the URL it was fetched from. So this module cannot verify that a payload
    named for gameweek N describes gameweek N, and pretending otherwise would be worse
    than saying it. What the fixtures payload does give is the gameweek's own progress,
    which is the caveat a reader of these points actually needs.

    Auto-substitutions are deliberately not modelled here, and the minutes do not change
    that. This returns points *and* minutes per player, which is what a substitution rule
    needs; which eleven those points are counted for stays a decision the ledger owns.
    Supplying an input is not the same as applying a rule, and keeping the two apart is
    what lets one caller score the named eleven and another the platform's, from one
    reading of one payload.

    ``minutes`` comes from the live document rather than from ``bootstrap-static`` because
    the bootstrap's counter is season-cumulative. It equals the gameweek's minutes for
    gameweek one and for no other, and a rule built on that coincidence would be silently
    wrong from gameweek two onward.
    """

    week = _positive(gameweek, "gameweek")
    records = _records(_document(live, "Live"), "elements", "Live element")
    _require_fields(records, _LIVE_ELEMENT_FIELDS, "Live element")

    points: dict[int, int] = {}
    minutes: dict[int, int] = {}
    for record in records:
        player = _integer(record, "id", "Live element")
        stats = record.get("stats")
        if not isinstance(stats, dict):
            raise DataSourceError(
                f"Live element {player} carries a {type(stats).__name__} 'stats' section "
                "rather than an object; the adapter reads its total_points and minutes."
            )
        if player in points:
            raise DuplicateRecordsError(
                f"Live payload for gameweek {week} declares player {player} more than once."
            )
        points[player] = _integer(stats, "total_points", f"Live element {player} stats")
        # Read rather than defaulted when absent. A player silently given zero minutes
        # reads as "did not play", and the substitution rule downstream would field a
        # bench player for someone who was on the pitch -- a wrong eleven, not a gap.
        minutes[player] = _integer(stats, "minutes", f"Live element {player} stats")

    finished, total = _gameweek_fixture_progress(fixtures, gameweek=week)
    return LiveEventPoints(
        gameweek=week,
        points_by_player=MappingProxyType(dict(sorted(points.items()))),
        minutes_by_player=MappingProxyType(dict(sorted(minutes.items()))),
        bonus_confirmed=finished == total,
        fixtures_finished=finished,
        fixtures_total=total,
        source_snapshot_id=source_snapshot_id,
    )


def build_live_player_history(
    bootstrap: bytes,
    fixtures: bytes,
    event_payloads: Mapping[int, bytes],
    *,
    season: str,
    target_gameweek: int,
    source_snapshot_id: str | None = None,
) -> tuple[pd.DataFrame, tuple[int, ...]]:
    """Build canonical prior-outcome rows plus an empty target row for live scoring.

    Only players present in every supplied historical live payload receive history. If a
    player is absent from one payload, their whole history is omitted and the prediction
    layer must use its explicit fallback for that player; treating a missing row as zero
    minutes would manufacture an appearance outcome. The target rows carry zeros solely
    as placeholders: shifted feature builders cannot read a target row's own outcome.
    """

    target = _positive(target_gameweek, "target_gameweek")
    declared_season = _require_season(season)
    weeks = tuple(sorted(event_payloads))
    if not weeks:
        raise DataSourceError("Live component history requires at least one completed gameweek.")
    if any(
        isinstance(week, bool) or not isinstance(week, int) or not 1 <= week < target
        for week in weeks
    ):
        raise InvalidValueError(
            f"Live component history weeks must be positive and earlier than GW{target}: "
            f"{list(weeks)!r}."
        )

    roster = player_snapshot(bootstrap)
    roster_by_code = {int(record["player_id"]): record for record in roster.to_dict("records")}
    element_to_code = player_codes(bootstrap)
    live_by_week: dict[int, LiveEventPoints] = {}
    complete_codes = set(int(value) for value in roster["player_id"].tolist())
    for week in weeks:
        live = fpl_live_event_points(
            event_payloads[week],
            fixtures,
            gameweek=week,
            source_snapshot_id=source_snapshot_id,
        )
        if not live.bonus_confirmed:
            raise IncompleteLiveHistoryError(
                f"Gameweek {week} is not fully settled in capture {source_snapshot_id!r}; "
                "component history cannot treat provisional points as outcomes."
            )
        unknown = sorted(set(live.points_by_player) - set(element_to_code))
        if unknown:
            raise DataSourceError(
                f"Gameweek {week} live points name element ids absent from bootstrap: "
                f"{format_examples(unknown)}."
            )
        available = {
            element_to_code[element]
            for element in live.points_by_player
            if element_to_code[element] in roster_by_code
        }
        complete_codes &= available
        live_by_week[week] = live

    roster_codes = set(int(value) for value in roster["player_id"].tolist())
    incomplete = tuple(sorted(roster_codes - complete_codes))
    rows: list[dict[str, object]] = []
    code_to_element = {code: element for element, code in element_to_code.items()}
    for week in weeks:
        live = live_by_week[week]
        for code in sorted(complete_codes):
            player = roster_by_code[code]
            element = code_to_element[code]
            rows.append(
                {
                    "season": declared_season,
                    "gameweek": week,
                    "player_id": code,
                    "name": player["name"],
                    "team_id": player["team_id"],
                    "position": player["position"],
                    "price_tenths": int(player["price_tenths"]),
                    "minutes": int(live.minutes_by_player[element]),
                    "total_points": int(live.points_by_player[element]),
                }
            )
    for player in roster.to_dict("records"):
        rows.append(
            {
                "season": declared_season,
                "gameweek": target,
                "player_id": int(player["player_id"]),
                "name": player["name"],
                "team_id": player["team_id"],
                "position": player["position"],
                "price_tenths": int(player["price_tenths"]),
                "minutes": 0,
                "total_points": 0,
            }
        )
    frame = pd.DataFrame(rows)
    frame["season"] = frame["season"].astype("string")
    frame["gameweek"] = frame["gameweek"].astype("int64")
    frame["player_id"] = frame["player_id"].astype("int64")
    frame["name"] = frame["name"].astype("string")
    frame["team_id"] = frame["team_id"].astype("string")
    frame["position"] = frame["position"].astype("string")
    for column in ("price_tenths", "minutes", "total_points"):
        frame[column] = frame[column].astype("int64")
    return (
        frame.sort_values(["season", "gameweek", "player_id"], kind="stable").reset_index(
            drop=True
        ),
        incomplete,
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
    rank_sort: int | None = None


@dataclass(frozen=True, slots=True)
class LeagueStandingsPage:
    """One verified page of a classic league's ordered standings."""

    page: int
    has_next: bool
    members: tuple[LeagueStanding, ...]
    last_updated_data: str


def fpl_league_standings_page(
    standings: bytes,
    *,
    league_id: int,
    expected_page: int,
) -> LeagueStandingsPage:
    """Read one numbered standings page while preserving the source's total order."""

    identifier = _positive(league_id, "league id")
    requested_page = _positive(expected_page, "standings page")
    document = _document(standings, "League standings")
    league = document.get("league")
    if not isinstance(league, dict) or league.get("id") != identifier:
        raise DataSourceError(f"League standings page must declare league {identifier}.")
    section = document.get("standings")
    if not isinstance(section, dict):
        raise DataSourceError("League standings payload must carry a 'standings' object.")
    page = _integer(section, "page", "League standings")
    if page != requested_page:
        raise DataSourceError(
            f"League standings payload is page {page}, not requested page {requested_page}."
        )
    has_next = _boolean(section, "has_next", "League standings")
    records = _records(section, "results", "League standing")
    _require_fields(records, (*_STANDING_FIELDS, "rank_sort"), "League standing")

    members: list[LeagueStanding] = []
    seen_entries: set[int] = set()
    seen_order: set[int] = set()
    for record in records:
        entry_id = _positive(_integer(record, "entry", "League standing"), "entry id")
        rank_sort = _positive(_integer(record, "rank_sort", "League standing"), "rank_sort")
        if entry_id in seen_entries:
            raise DuplicateRecordsError(
                f"League {identifier} page {page} lists entry {entry_id} more than once."
            )
        if rank_sort in seen_order:
            raise DuplicateRecordsError(
                f"League {identifier} page {page} repeats rank_sort {rank_sort}."
            )
        seen_entries.add(entry_id)
        seen_order.add(rank_sort)
        members.append(
            LeagueStanding(
                entry_id=entry_id,
                entry_name=_text(record, "entry_name", "League standing"),
                player_name=_text(record, "player_name", "League standing"),
                rank=_positive(_integer(record, "rank", "League standing"), "rank"),
                rank_sort=rank_sort,
            )
        )
    updated = document.get("last_updated_data")
    if not isinstance(updated, str) or not updated.strip():
        raise DataSourceError(
            "League standings payload must carry a non-empty last_updated_data timestamp."
        )
    return LeagueStandingsPage(
        page=page,
        has_next=has_next,
        members=tuple(members),
        last_updated_data=updated.strip(),
    )


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


@dataclass(frozen=True, slots=True)
class EntryGameweekPoints:
    """One entry's score for one played gameweek, as that entry's own history states it.

    Read from ``entry/{id}/history/`` rather than from the league standings for two
    reasons that are properties of the documents rather than preferences. The history row
    **names the gameweek it belongs to**, while the standings' ``event_total`` names none
    and would have to be assumed to mean the current week — and the published members view
    is labelled with the *upcoming* gameweek, so an unlabelled score lands under the wrong
    week's heading. And the standings table carries ``last_updated_data``, which in the
    capture this was built against was thirteen hours older than the capture itself; the
    entry documents are fetched in the same pass as the picks.

    ``points`` is net of the week's transfer cost, as the source publishes it, and may be
    negative after a hit — refusing a negative week would be the same class of error as
    inventing a positive one.
    """

    entry_id: int
    gameweek: int
    points: int
    total_points: int


def fpl_entry_history_points(history: bytes, *, entry_id: int) -> tuple[EntryGameweekPoints, ...]:
    """Return one entry's played gameweeks, in gameweek order.

    Only weeks the source has actually played appear in ``current``; an unplayed week is
    absent rather than zero, and this function preserves that — a caller asking for a week
    that is not here gets nothing back, which is the honest answer.
    """

    identifier = _positive(entry_id, "entry id")
    document = _document(history, "Entry history")
    records = _records(document, "current", "Entry history")
    _require_fields(records, _HISTORY_EVENT_FIELDS, "Entry history")
    weeks: list[EntryGameweekPoints] = []
    seen: set[int] = set()
    for record in records:
        gameweek = _positive(_integer(record, "event", "Entry history"), "gameweek")
        if gameweek in seen:
            raise DuplicateRecordsError(
                f"Entry {identifier} history lists gameweek {gameweek} more than once."
            )
        seen.add(gameweek)
        weeks.append(
            EntryGameweekPoints(
                entry_id=identifier,
                gameweek=gameweek,
                points=_integer(record, "points", "Entry history"),
                total_points=_integer(record, "total_points", "Entry history"),
            )
        )
    return tuple(sorted(weeks, key=lambda week: week.gameweek))


def scored_gameweeks(bootstrap: bytes) -> frozenset[int]:
    """Return the gameweeks whose points are final: finished **and** checked.

    ``finished`` alone is what ``live/ledger.py`` gates our own realized outcome on, and it
    is not enough for a score published to a reader. Bonus is added per fixture, so a score
    read before it lands is short by up to three points per player and short by *different*
    amounts for different players — biased rather than noisy, and it does not average out
    across a squad. Gameweek 1 was measured sitting at ``finished: false, data_checked:
    false`` eight and a half hours after its last kick-off with every fixture at ninety
    minutes, so the gap this guards against is hours wide rather than minutes.
    """

    document = _document(bootstrap, "Bootstrap")
    records = _records(document, "events", "Bootstrap event")
    _require_fields(records, _SCORED_EVENT_FIELDS, "Bootstrap event")
    scored: set[int] = set()
    for record in records:
        if _boolean(record, "finished", "Bootstrap event") and _boolean(
            record, "data_checked", "Bootstrap event"
        ):
            scored.add(_positive(_integer(record, "id", "Bootstrap event"), "gameweek"))
    return frozenset(scored)


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
    """The fifteen picks in the platform's own order: positions 1 to 15.

    The order is load-bearing, not incidental. ``squad[:11]`` is the named eleven and
    ``squad[11:]`` is the bench **in substitution order** — the sequence the platform walks
    when it replaces a starter who played no minutes (#262). Sorting this tuple would keep
    every member and destroy the rule.
    """
    starting_xi: tuple[int, ...]
    captain: int
    vice_captain: int
    """Who inherits the multiplier when the captain plays no minutes.

    Required rather than defaulted: there is no value that can stand in for it. Guessing
    the vice would not fail loudly, it would hand the armband to the wrong player in exactly
    the weeks the captain blanked, which is when it matters most.

    The adapter requires the vice to be in the squad and to differ from the captain, and
    deliberately does **not** require him to be in the starting eleven. Six real entries
    were checked and all six named both inside the eleven, but six is not a rule, and an
    adapter that refuses a real capture is worse than one that accepts a bench vice.
    """
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
        if self.vice_captain not in self.squad:
            raise InvalidValueError(
                f"Entry {self.entry_id} gameweek {self.gameweek} names a vice-captain who "
                "is not in the squad."
            )
        if self.vice_captain == self.captain:
            raise InvalidValueError(
                f"Entry {self.entry_id} gameweek {self.gameweek} names the same player as "
                "captain and vice-captain, which would leave the multiplier nowhere to go "
                "when he plays no minutes."
            )
        if self.bank_tenths < 0:
            raise InvalidValueError(
                f"Entry {self.entry_id} reports a negative bank of {self.bank_tenths}."
            )


@dataclass(frozen=True, slots=True)
class EntrySquad:
    """One entry's fifteen picks at one gameweek: who, in what order, and who wore what.

    The part of a picks document that needs no season history. It exists so a consumer that
    only wants squad membership -- counting how many of an elite cohort held a player -- does
    not have to capture the history payload it will never read, and so that consumer and
    ``fpl_entry_picks`` share one parser instead of two copies that drift.
    """

    entry_id: int
    gameweek: int
    squad: tuple[int, ...]
    starting_xi: tuple[int, ...]
    captain: int
    vice_captain: int


def entry_squad_from_picks(picks: bytes, *, entry_id: int, gameweek: int) -> EntrySquad:
    """Parse one ``event/{gw}/picks`` document into its squad, order and armbands."""

    identifier = _positive(entry_id, "entry id")
    week = _positive(gameweek, "gameweek")
    document = _document(picks, "Entry picks")
    records = _records(document, "picks", "Entry pick")
    _require_fields(records, _PICK_FIELDS, "Entry pick")

    by_position: dict[int, int] = {}
    captains: list[int] = []
    vice_captains: list[int] = []
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
        if _boolean(record, "is_vice_captain", "Entry pick"):
            vice_captains.append(element)

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
    if len(vice_captains) != 1:
        raise DataSourceError(
            f"Entry {identifier} gameweek {week} names {len(vice_captains)} vice-captains; "
            "the platform names exactly one."
        )

    squad = tuple(by_position[position] for position in sorted(by_position))
    return EntrySquad(
        entry_id=identifier,
        gameweek=week,
        squad=squad,
        starting_xi=squad[:_STARTING_SIZE],
        captain=captains[0],
        vice_captain=vice_captains[0],
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

    named = entry_squad_from_picks(picks, entry_id=entry_id, gameweek=gameweek)
    identifier = named.entry_id
    week = named.gameweek
    squad = named.squad
    document = _document(picks, "Entry picks")
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
        starting_xi=named.starting_xi,
        captain=named.captain,
        vice_captain=named.vice_captain,
        bank_tenths=_integer(entry_history, "bank", "Entry history"),
        free_transfers=1,
        free_transfers_known=False,
        chips_used=_chips_used(history, entry_id=identifier),
        purchase_prices=MappingProxyType({}),
        purchase_prices_known=False,
        source_snapshot_id=source_snapshot_id,
    )
