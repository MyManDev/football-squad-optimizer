"""The calendar a capture states, and the three things a fixture table cannot say.

``fixture_snapshot`` lists matches, so what it cannot say is anything about a club that
has none. These hold the distinctions that absence collapses: a blank week against an
ordinary one, a blank week against a week the capture does not publish at all, and a
settled calendar against one with fixtures still waiting for a date.
"""

import json
from typing import Any

import pytest

from squadopt.data.errors import InvalidValueError
from squadopt.data.fixture_horizon import DEFAULT_HORIZON_WEEKS, fixture_horizon
from squadopt.data.sources.fpl_live import unscheduled_fixture_count

SNAPSHOT_ID = "fpl-live-20260813T201143Z-55789a780186"
CAPTURED_AT = "2026-08-13T20:11:43Z"

EVENTS: list[dict[str, Any]] = [
    {"id": number, "deadline_time": f"2026-08-{13 + number:02d}T17:30:00Z", "finished": False}
    for number in range(1, 5)
]

#: Four clubs, so a week can hold a match, a double and a blank at once. The persistent
#: code differs from the per-season id on purpose: the horizon speaks codes.
TEAMS: list[dict[str, Any]] = [
    {"id": 1, "code": 3, "name": "Arsenal", "short_name": "ARS"},
    {"id": 2, "code": 7, "name": "Aston Villa", "short_name": "AVL"},
    {"id": 3, "code": 90, "name": "Burnley", "short_name": "BUR"},
    {"id": 14, "code": 14, "name": "Man Utd", "short_name": "MUN"},
]
ARSENAL, VILLA, BURNLEY, UNITED = 3, 7, 90, 14

#: Declared by the capture and named in no fixture it holds.
IDLE_TEAM: dict[str, Any] = {"id": 4, "code": 31, "name": "Crystal Palace", "short_name": "CRY"}
IDLE = 31


def _fixture(
    identifier: int, event: int | None, home: int, away: int, **extra: Any
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "id": identifier,
        "event": event,
        "team_h": home,
        "team_a": away,
        "team_h_difficulty": 2,
        "team_a_difficulty": 5,
        "kickoff_time": f"2026-08-{13 + (event or 1):02d}T19:00:00Z",
        "finished": False,
        "provisional_start_time": False,
    }
    record.update(extra)
    return record


def _bootstrap(teams: list[dict[str, Any]] | None = None) -> bytes:
    return json.dumps(
        {"teams": TEAMS if teams is None else teams, "elements": [], "events": EVENTS}
    ).encode("utf-8")


def _payload(records: list[dict[str, Any]]) -> bytes:
    return json.dumps(records).encode("utf-8")


#: Gameweek 1: everyone plays. Gameweek 2: Arsenal plays twice, United twice, and
#: Villa and Burnley not at all. Gameweek 3: the two who rested play each other.
CALENDAR = [
    _fixture(1, 1, 1, 14),
    _fixture(2, 1, 2, 3),
    _fixture(3, 2, 1, 14),
    _fixture(4, 2, 14, 1),
    _fixture(5, 3, 2, 3),
    _fixture(6, 4, 1, 2),
    _fixture(7, 4, 3, 14),
]


def _horizon(
    records: list[dict[str, Any]] | None = None,
    *,
    first_gameweek: int = 1,
    weeks: int = DEFAULT_HORIZON_WEEKS,
    bootstrap: bytes | None = None,
) -> Any:
    return fixture_horizon(
        _payload(CALENDAR if records is None else records),
        _bootstrap() if bootstrap is None else bootstrap,
        season="2026-27",
        snapshot_id=SNAPSHOT_ID,
        captured_at_utc=CAPTURED_AT,
        first_gameweek=first_gameweek,
        weeks=weeks,
    )


# --- the blank a fixture table cannot state ---------------------------------


def test_a_club_with_no_match_gets_a_week_of_its_own() -> None:
    """The whole reason this reader exists: the fixture table has no row to carry it."""

    horizon = _horizon()

    assert horizon.week(VILLA, 2).fixture_count == 0
    assert horizon.week(VILLA, 2).fixtures == ()


def test_every_club_the_capture_declares_has_a_row_in_every_covered_week() -> None:
    """A complete grid, so a consumer never has to read an absence as a number."""

    horizon = _horizon()

    # Sorted by persistent code, which is not the per-season id order.
    assert horizon.team_ids == (ARSENAL, VILLA, UNITED, BURNLEY)
    assert len(horizon.weeks) == len(horizon.team_ids) * len(horizon.gameweeks)
    assert {(week.team_id, week.gameweek) for week in horizon.weeks} == {
        (team, gameweek) for team in horizon.team_ids for gameweek in horizon.gameweeks
    }


def test_a_week_only_two_clubs_play_in_still_names_the_other_two() -> None:
    """The rule the grid rests on: the club list is the capture's, not the week's.

    A reader that took its clubs from the rows it found would answer this week with two
    entries and be right about both, and a consumer would have no way to ask about the
    two it did not mention. Two clubs playing is not the same statement as two clubs
    existing.
    """

    horizon = _horizon(first_gameweek=3, weeks=1)

    assert len(horizon.weeks) == 4
    assert {week.team_id for week in horizon.blanks} == {ARSENAL, UNITED}


def test_a_club_the_capture_declares_and_never_schedules_is_still_a_club() -> None:
    """The same rule one step further out, where taking the clubs from the season's own
    fixture list would also be wrong rather than merely narrow."""

    horizon = _horizon(bootstrap=_bootstrap([*TEAMS, IDLE_TEAM]))

    assert IDLE in horizon.team_ids
    assert [week.fixture_count for week in horizon.weeks if week.team_id == IDLE] == [0, 0, 0, 0]


def test_blanks_and_doubles_are_named_together_and_agree_with_the_counts() -> None:
    horizon = _horizon()

    assert {(week.team_id, week.gameweek) for week in horizon.blanks} == {
        (VILLA, 2),
        (BURNLEY, 2),
        (ARSENAL, 3),
        (UNITED, 3),
    }
    assert {(week.team_id, week.gameweek) for week in horizon.doubles} == {
        (ARSENAL, 2),
        (UNITED, 2),
    }
    assert all(week.fixture_count == 0 for week in horizon.blanks)
    assert all(week.fixture_count > 1 for week in horizon.doubles)


# --- a week the capture does not publish is not a week off ------------------


def test_a_horizon_running_past_the_season_is_shorter_rather_than_empty() -> None:
    """Four published gameweeks and a horizon of five from the third: two, not five.

    A reader that filled the range would answer "every club is idle in gameweek 6",
    which is a statement about a week nobody has scheduled anything in.
    """

    horizon = _horizon(first_gameweek=3)

    assert horizon.gameweeks == (3, 4)
    assert len(horizon.weeks) == 8


def test_a_first_gameweek_the_capture_never_published_is_refused() -> None:
    with pytest.raises(InvalidValueError, match="publishes no gameweek 9"):
        _horizon(first_gameweek=9)


def test_a_horizon_of_no_weeks_is_refused() -> None:
    with pytest.raises(InvalidValueError, match="at least one gameweek"):
        _horizon(weeks=0)


def test_a_week_outside_the_horizon_is_unknown_rather_than_blank() -> None:
    """The refusal that keeps the grid honest: it is complete over what it covers."""

    horizon = _horizon(first_gameweek=1, weeks=2)

    assert horizon.week(ARSENAL, 2).fixture_count == 2
    with pytest.raises(InvalidValueError, match="not blank"):
        horizon.week(ARSENAL, 3)
    with pytest.raises(InvalidValueError, match="not blank"):
        horizon.week(999, 1)


# --- the fixture facts the projection needs ---------------------------------


def test_a_match_carries_the_opponent_the_side_and_the_platform_figure() -> None:
    horizon = _horizon()
    home = horizon.week(ARSENAL, 1).fixtures[0]
    away = horizon.week(UNITED, 1).fixtures[0]

    assert (home.fixture_id, home.opponent_team_id, home.is_home) == (1, UNITED, True)
    assert (away.fixture_id, away.opponent_team_id, away.is_home) == (1, ARSENAL, False)
    assert (home.fixture_difficulty, away.fixture_difficulty) == (2, 5)
    assert home.kickoff_utc == "2026-08-14T19:00:00Z"


def test_a_missing_kickoff_or_difficulty_arrives_as_absent_rather_than_zero() -> None:
    """A fixture can hold a gameweek and no time, and a zero difficulty is a figure."""

    records = [
        _fixture(1, 1, 1, 14, kickoff_time=None, team_h_difficulty=None, team_a_difficulty=None)
    ]
    match = _horizon(records, weeks=1).week(ARSENAL, 1).fixtures[0]

    assert match.kickoff_utc is None
    assert match.fixture_difficulty is None


def test_a_double_is_ordered_by_kickoff_so_two_reads_agree() -> None:
    records = [
        _fixture(3, 2, 1, 14, kickoff_time="2026-08-17T19:00:00Z"),
        _fixture(4, 2, 14, 1, kickoff_time="2026-08-15T19:00:00Z"),
    ]
    horizon = _horizon(records, first_gameweek=2, weeks=1)

    assert [match.fixture_id for match in horizon.week(ARSENAL, 2).fixtures] == [4, 3]


# --- what the capture could not say -----------------------------------------


def test_a_fixture_awaiting_a_date_is_counted_rather_than_placed() -> None:
    """The reschedule statement, in the one number that carries it.

    The postponed match is not put in any gameweek, because no gameweek holds it, and
    Villa's week 3 becomes a stated blank. What stops that blank being read as settled
    is the count beside it: one fixture is still looking for a week, and week 3 is a
    week it can land in.
    """

    records = [record for record in CALENDAR if record["id"] != 5]
    records.append(_fixture(5, None, 2, 3))
    horizon = _horizon(records)

    assert horizon.unscheduled_count == 1
    assert horizon.week(VILLA, 3).fixture_count == 0
    assert all(match.fixture_id != 5 for week in horizon.weeks for match in week.fixtures)


def test_a_settled_calendar_says_so() -> None:
    assert _horizon().unscheduled_count == 0


def test_the_count_reads_the_same_field_the_exclusion_does() -> None:
    """Counted off the payload, so it cannot drift from what ``fixture_snapshot`` drops."""

    records = [*CALENDAR, _fixture(8, None, 1, 3), _fixture(9, None, 2, 14)]

    assert unscheduled_fixture_count(_payload(records)) == 2
    assert _horizon(records).unscheduled_count == 2


def test_the_horizon_reports_the_capture_it_read() -> None:
    horizon = _horizon()

    assert horizon.season == "2026-27"
    assert horizon.source_snapshot_id == SNAPSHOT_ID
    assert horizon.captured_at_utc == CAPTURED_AT
