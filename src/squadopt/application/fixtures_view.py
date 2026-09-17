"""The season's schedule and results, as one capture stated them.

``data/fixtures.json`` is the whole fixture list by gameweek: who plays whom, when, and
the score where the capture has one. It carries no projection and no difficulty figure.
All source bytes come from the one capture supplied to the site builder; nothing is
backfilled from an older one.

Absent is not zero. A fixture the payload gives no score for publishes null scores, a
fixture with no kickoff publishes a null kickoff, and a fixture with no gameweek (a
postponement awaiting a new date) is counted and not listed, since no gameweek holds it.

The page reads ``current_gameweek`` for the week about to be played, the one after it for
next week, and everything before it as the archive. Nothing here keeps state between
publishes: a later capture names a later ``current_gameweek`` and the three shift.
"""

import json
from collections.abc import Mapping
from dataclasses import dataclass

from squadopt.application.views import JsonValue, _View
from squadopt.data.errors import DataSourceError, InvalidValueError
from squadopt.data.snapshots import CapturedSnapshot
from squadopt.data.sources.fpl_live import (
    BOOTSTRAP_PAYLOAD,
    FIXTURES_PAYLOAD,
    gameweek_deadlines,
    next_open_deadline,
)
from squadopt.data.timestamps import normalize_utc_timestamp
from squadopt.live import season_from_bootstrap

FIXTURES_CONTRACT_VERSION = "fixtures_v1"
FIXTURES_RELATIVE_PATH = "fixtures.json"


def fixtures_schema() -> dict[str, JsonValue]:
    """The separate, closed wire contract, also shipped with each site build."""

    def closed(properties: dict[str, JsonValue]) -> dict[str, JsonValue]:
        return {
            "type": "object",
            "additionalProperties": False,
            "required": list(properties),
            "properties": properties,
        }

    team = closed(
        {
            "team_id": {"type": "integer", "minimum": 1},
            "name": {"type": "string", "minLength": 1},
            "short_name": {"type": "string", "minLength": 1},
        }
    )
    score: JsonValue = {"type": ["integer", "null"], "minimum": 0}
    fixture = closed(
        {
            "fixture_id": {"type": "integer", "minimum": 1},
            "kickoff_utc": {"type": ["string", "null"], "format": "date-time"},
            "home": team,
            "away": team,
            "finished": {"type": "boolean"},
            "home_score": score,
            "away_score": score,
        }
    )
    gameweek = closed(
        {
            "gameweek": {"type": "integer", "minimum": 1},
            "deadline_utc": {"type": "string", "format": "date-time"},
            "fixtures": {"type": "array", "items": fixture},
        }
    )
    payload = closed(
        {
            "season": {"type": "string", "pattern": r"^\d{4}-\d{2}$"},
            "source_snapshot_id": {"type": "string"},
            "captured_at_utc": {"type": "string", "format": "date-time"},
            "current_gameweek": {"type": ["integer", "null"], "minimum": 1},
            "unscheduled_count": {"type": "integer", "minimum": 0},
            "gameweeks": {"type": "array", "items": gameweek},
        }
    )
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": FIXTURES_CONTRACT_VERSION,
        **closed(
            {
                "contract_version": {"const": FIXTURES_CONTRACT_VERSION},
                "generated_at_utc": {"type": "string", "format": "date-time"},
                "payload": payload,
            }
        ),
    }


@dataclass(frozen=True, slots=True)
class FixtureTeamView(_View):
    team_id: int
    """The payload's per-season team number, resolved through the same capture."""
    name: str
    short_name: str


@dataclass(frozen=True, slots=True)
class FixtureView(_View):
    fixture_id: int
    kickoff_utc: str | None
    home: FixtureTeamView
    away: FixtureTeamView
    finished: bool
    home_score: int | None
    """Null unless the payload states both scores. Before full time it is the score at the
    capture, which is why a page shows one only beside ``finished``."""
    away_score: int | None


@dataclass(frozen=True, slots=True)
class FixtureGameweekView(_View):
    gameweek: int
    deadline_utc: str
    fixtures: tuple[FixtureView, ...]
    """Sorted by kickoff, then fixture id; a fixture with no kickoff sorts last."""


@dataclass(frozen=True, slots=True)
class FixturesView(_View):
    season: str
    source_snapshot_id: str
    captured_at_utc: str
    current_gameweek: int | None
    """The gameweek whose deadline was still open at the capture; null once none is."""
    unscheduled_count: int
    gameweeks: tuple[FixtureGameweekView, ...]


def _integer(record: Mapping[str, object], key: str, label: str) -> int:
    value = record.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise InvalidValueError(f"{label} field {key!r} must be an integer, got {value!r}.")
    return value


def _parsed(payload: bytes, label: str) -> object:
    try:
        return json.loads(payload.decode("utf-8"))
    except ValueError as error:
        raise DataSourceError(f"{label} payload is not valid UTF-8 JSON: {error}") from error


def _teams(bootstrap: bytes) -> dict[int, FixtureTeamView]:
    document = _parsed(bootstrap, "Bootstrap")
    records = document.get("teams") if isinstance(document, dict) else None
    if not isinstance(records, list) or not records:
        raise DataSourceError("Bootstrap payload must carry a non-empty 'teams' array.")
    teams: dict[int, FixtureTeamView] = {}
    for record in records:
        if not isinstance(record, dict):
            raise DataSourceError("Bootstrap payload has a non-object entry in 'teams'.")
        identifier = _integer(record, "id", "Team")
        name, short_name = record.get("name"), record.get("short_name")
        if not isinstance(name, str) or not name.strip():
            raise InvalidValueError(f"Team {identifier} declares no name.")
        if not isinstance(short_name, str) or not short_name.strip():
            raise InvalidValueError(f"Team {identifier} declares no short_name.")
        teams[identifier] = FixtureTeamView(identifier, name.strip(), short_name.strip())
    return teams


def _score(record: Mapping[str, object], key: str) -> int | None:
    value = record.get(key)
    if value is None:
        return None
    score = _integer(record, key, "Fixture")
    if score < 0:
        raise InvalidValueError(f"Fixture field {key!r} must not be negative, got {score}.")
    return score


def fixtures_view(snapshot: CapturedSnapshot) -> FixturesView | None:
    """Every gameweek's fixtures from one capture; ``None`` when it holds no fixture list.

    A capture without both payloads publishes nothing rather than an empty season. A
    payload that is present and unreadable raises: the source publishes no contract, so a
    changed shape is reported, not rendered as blanks.
    """

    bootstrap = snapshot.payloads.get(BOOTSTRAP_PAYLOAD)
    fixtures = snapshot.payloads.get(FIXTURES_PAYLOAD)
    if bootstrap is None or fixtures is None:
        return None
    metadata = snapshot.metadata
    deadlines = gameweek_deadlines(bootstrap)
    teams = _teams(bootstrap)
    try:
        # The same rule the league views target a week by: the first deadline the
        # capture instant had not reached.
        current: int | None = next_open_deadline(
            deadlines, as_of_utc=metadata.captured_at_utc
        ).gameweek
    except DataSourceError:
        current = None

    records = _parsed(fixtures, "Fixture")
    if not isinstance(records, list):
        raise DataSourceError("Fixture payload must be a JSON array.")
    by_gameweek: dict[int, list[FixtureView]] = {entry.gameweek: [] for entry in deadlines}
    unscheduled = 0
    for record in records:
        if not isinstance(record, dict):
            raise DataSourceError("Fixture payload has a non-object entry.")
        if record.get("event") is None:
            unscheduled += 1
            continue
        identifier = _integer(record, "id", "Fixture")
        gameweek = _integer(record, "event", "Fixture")
        if gameweek not in by_gameweek:
            raise InvalidValueError(
                f"Fixture {identifier} names gameweek {gameweek}, which the capture's own "
                "event list does not publish."
            )
        home, away = _integer(record, "team_h", "Fixture"), _integer(record, "team_a", "Fixture")
        if home not in teams or away not in teams:
            raise InvalidValueError(
                f"Fixture {identifier} names a team the capture's own team list does not."
            )
        finished = record.get("finished")
        if not isinstance(finished, bool):
            raise InvalidValueError(f"Fixture {identifier} field 'finished' must be a boolean.")
        kickoff = record.get("kickoff_time")
        home_score, away_score = _score(record, "team_h_score"), _score(record, "team_a_score")
        both = home_score is not None and away_score is not None
        by_gameweek[gameweek].append(
            FixtureView(
                fixture_id=identifier,
                kickoff_utc=(
                    None
                    if kickoff is None
                    else normalize_utc_timestamp(
                        kickoff, label=f"Fixture {identifier} kickoff_time"
                    )
                ),
                home=teams[home],
                away=teams[away],
                finished=finished,
                home_score=home_score if both else None,
                away_score=away_score if both else None,
            )
        )
    return FixturesView(
        season=season_from_bootstrap(bootstrap),
        source_snapshot_id=metadata.snapshot_id,
        captured_at_utc=normalize_utc_timestamp(metadata.captured_at_utc, label="captured_at_utc"),
        current_gameweek=current,
        unscheduled_count=unscheduled,
        gameweeks=tuple(
            FixtureGameweekView(
                gameweek=entry.gameweek,
                deadline_utc=entry.deadline_utc,
                fixtures=tuple(
                    sorted(
                        by_gameweek[entry.gameweek],
                        key=lambda row: (
                            row.kickoff_utc is None,
                            row.kickoff_utc or "",
                            row.fixture_id,
                        ),
                    )
                ),
            )
            for entry in deadlines
        ),
    )
