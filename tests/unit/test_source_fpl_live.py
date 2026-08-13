"""Tests for the live-endpoint snapshot adapter.

Every payload here is hand-built. The adapter reads bytes that are already on disk,
so nothing in this file needs a network or a captured snapshot.
"""

import json
from typing import Any

import pytest

from squadopt.data.errors import (
    DataSourceError,
    DuplicateRecordsError,
    InvalidValueError,
)
from squadopt.data.sources.fpl_live import (
    POSITION_CODES,
    SNAPSHOT_COLUMNS,
    GameweekDeadline,
    gameweek_deadlines,
    next_open_deadline,
    player_snapshot,
    team_names,
)

EVENTS: list[dict[str, Any]] = [
    {"id": 1, "deadline_time": "2026-08-21T17:30:00Z", "finished": False, "is_next": True},
    {"id": 2, "deadline_time": "2026-08-28T17:30:00Z", "finished": False, "is_next": False},
    {"id": 3, "deadline_time": "2026-09-11T17:30:00Z", "finished": False, "is_next": False},
]

TEAMS: list[dict[str, Any]] = [
    {"id": 1, "name": "Arsenal", "short_name": "ARS"},
    {"id": 14, "name": "Man Utd", "short_name": "MUN"},
]


def _element(**overrides: Any) -> dict[str, Any]:
    """Return one element record carrying the fields the adapter reads."""

    record: dict[str, Any] = {
        "code": 118748,
        "id": 5,
        "first_name": "Bukayo",
        "second_name": "Saka",
        "team": 1,
        "element_type": 3,
        "now_cost": 100,
        # Present in the real payload and deliberately never read as a column.
        "status": "a",
        "chance_of_playing_next_round": 100,
        "news": "",
        "selected_by_percent": "41.2",
    }
    record.update(overrides)
    return record


def _payload(
    elements: list[dict[str, Any]] | None = None,
    teams: list[dict[str, Any]] | None = None,
    events: list[dict[str, Any]] | None = None,
    **overrides: Any,
) -> bytes:
    document: dict[str, Any] = {
        "teams": TEAMS if teams is None else teams,
        "elements": [_element()] if elements is None else elements,
        "events": EVENTS if events is None else events,
    }
    document.update(overrides)
    return json.dumps(document).encode("utf-8")


# --- shape ------------------------------------------------------------------


def test_the_snapshot_carries_exactly_the_deadline_known_columns() -> None:
    frame = player_snapshot(_payload())

    assert tuple(frame.columns) == SNAPSHOT_COLUMNS


def test_availability_fields_are_not_promoted_to_columns() -> None:
    """They stay in the captured payload and are applied later as a rule."""

    frame = player_snapshot(_payload())

    assert "status" not in frame.columns
    assert "chance_of_playing_next_round" not in frame.columns


def test_identity_is_the_persistent_code_not_the_per_season_id() -> None:
    frame = player_snapshot(_payload([_element(code=118748, id=5)]))

    assert frame["player_id"].tolist() == [118748]


def test_the_team_integer_resolves_to_the_name_the_panel_uses() -> None:
    frame = player_snapshot(_payload([_element(team=14)]))

    assert frame["team_id"].tolist() == ["Man Utd"]


def test_the_name_is_assembled_from_both_parts() -> None:
    frame = player_snapshot(_payload([_element(first_name="Cole", second_name="Palmer")]))

    assert frame["name"].tolist() == ["Cole Palmer"]


def test_price_stays_an_integer_number_of_tenths() -> None:
    frame = player_snapshot(_payload([_element(now_cost=45)]))

    assert frame["price_tenths"].tolist() == [45]
    assert frame["price_tenths"].dtype.kind == "i"


@pytest.mark.parametrize(("code", "expected"), sorted(POSITION_CODES.items()))
def test_every_declared_position_code_maps_to_its_canonical_label(code: int, expected: str) -> None:
    frame = player_snapshot(_payload([_element(element_type=code)]))

    assert frame["position"].tolist() == [expected]


# --- exclusions -------------------------------------------------------------


def test_non_player_entries_are_excluded() -> None:
    """The platform lists managers as their own element type."""

    frame = player_snapshot(
        _payload(
            [
                _element(code=1, element_type=3),
                _element(code=2, element_type=5, first_name="Mikel", second_name="Arteta"),
            ]
        )
    )

    assert frame["player_id"].tolist() == [1]


def test_a_payload_with_no_eligible_players_is_an_error_not_an_empty_table() -> None:
    with pytest.raises(DataSourceError, match="position encoding has changed"):
        player_snapshot(_payload([_element(element_type=5)]))


# --- determinism ------------------------------------------------------------


def test_output_is_sorted_by_player_id_regardless_of_source_order() -> None:
    ascending = player_snapshot(_payload([_element(code=10), _element(code=20), _element(code=30)]))
    shuffled = player_snapshot(_payload([_element(code=30), _element(code=10), _element(code=20)]))

    assert ascending.equals(shuffled)
    assert ascending["player_id"].tolist() == [10, 20, 30]


# --- payload integrity ------------------------------------------------------


def test_text_in_place_of_bytes_is_rejected() -> None:
    with pytest.raises(DataSourceError, match="must be raw bytes"):
        player_snapshot(json.dumps({"teams": TEAMS, "elements": []}))  # type: ignore[arg-type]


def test_malformed_json_is_rejected() -> None:
    with pytest.raises(DataSourceError, match="not valid UTF-8 JSON"):
        player_snapshot(b"{not json")


def test_a_json_array_payload_is_rejected() -> None:
    with pytest.raises(DataSourceError, match="must be a JSON object"):
        player_snapshot(b"[]")


@pytest.mark.parametrize("section", ["teams", "elements"])
def test_a_missing_section_is_treated_as_a_changed_payload(section: str) -> None:
    document = json.loads(_payload())
    del document[section]

    with pytest.raises(DataSourceError, match="non-empty"):
        player_snapshot(json.dumps(document).encode("utf-8"))


@pytest.mark.parametrize("section", ["teams", "elements"])
def test_an_empty_section_is_rejected(section: str) -> None:
    document = json.loads(_payload())
    document[section] = []

    with pytest.raises(DataSourceError, match="non-empty"):
        player_snapshot(json.dumps(document).encode("utf-8"))


def test_non_object_entries_are_rejected() -> None:
    document = json.loads(_payload())
    document["elements"] = [_element(), 42]

    with pytest.raises(DataSourceError, match="non-object entries"):
        player_snapshot(json.dumps(document).encode("utf-8"))


@pytest.mark.parametrize("field", ["code", "first_name", "team", "element_type", "now_cost"])
def test_a_renamed_field_stops_the_run_and_names_itself(field: str) -> None:
    """The source is undocumented, so a rename must not degrade into null columns."""

    record = _element()
    del record[field]

    with pytest.raises(DataSourceError, match=field):
        player_snapshot(_payload([record]))


# --- value validation -------------------------------------------------------


def test_a_player_on_an_undeclared_team_is_rejected() -> None:
    with pytest.raises(InvalidValueError, match="does not declare"):
        player_snapshot(_payload([_element(team=99)]))


def test_a_repeated_persistent_code_is_rejected() -> None:
    with pytest.raises(DuplicateRecordsError, match="more than once"):
        player_snapshot(_payload([_element(code=7), _element(code=7, id=8)]))


def test_a_repeated_team_id_is_rejected() -> None:
    teams = [*TEAMS, {"id": 1, "name": "Arsenal Reserves"}]

    with pytest.raises(DuplicateRecordsError, match="team id 1 more than once"):
        player_snapshot(_payload(teams=teams))


def test_a_fractional_price_is_rejected_rather_than_rounded() -> None:
    with pytest.raises(InvalidValueError):
        player_snapshot(_payload([_element(now_cost=45.5)]))


def test_a_boolean_is_not_accepted_where_an_integer_is_required() -> None:
    with pytest.raises(InvalidValueError, match="must be an integer"):
        player_snapshot(_payload([_element(now_cost=True)]))


def test_text_where_an_integer_is_required_is_rejected() -> None:
    with pytest.raises(InvalidValueError, match="must be an integer"):
        player_snapshot(_payload([_element(code="118748")]))


def test_a_nameless_element_is_rejected() -> None:
    with pytest.raises(InvalidValueError, match="has no name"):
        player_snapshot(_payload([_element(first_name=" ", second_name="")]))


def test_an_empty_team_name_is_rejected() -> None:
    with pytest.raises(InvalidValueError, match="empty name"):
        player_snapshot(_payload(teams=[{"id": 1, "name": "  "}]))


# --- team mapping -----------------------------------------------------------


def test_team_names_are_read_from_the_same_payload_they_describe() -> None:
    assert dict(team_names(_payload())) == {1: "Arsenal", 14: "Man Utd"}


def test_the_team_mapping_is_read_only() -> None:
    mapping = team_names(_payload())

    with pytest.raises(TypeError):
        mapping[2] = "Aston Villa"  # type: ignore[index]


# --- deadlines --------------------------------------------------------------


def test_deadlines_are_returned_in_gameweek_order() -> None:
    parsed = gameweek_deadlines(_payload(events=list(reversed(EVENTS))))

    assert [entry.gameweek for entry in parsed] == [1, 2, 3]
    assert parsed[0].deadline_utc == "2026-08-21T17:30:00Z"


def test_the_next_open_deadline_is_the_earliest_one_still_ahead() -> None:
    parsed = gameweek_deadlines(_payload())

    resolved = next_open_deadline(parsed, as_of_utc="2026-08-21T16:00:00Z")

    assert resolved.gameweek == 1


def test_a_closed_deadline_is_skipped() -> None:
    parsed = gameweek_deadlines(_payload())

    resolved = next_open_deadline(parsed, as_of_utc="2026-08-22T09:00:00Z")

    assert resolved.gameweek == 2


def test_the_deadline_instant_itself_counts_as_closed() -> None:
    """A squad decided at the moment of closing could not actually be entered."""

    parsed = gameweek_deadlines(_payload())

    resolved = next_open_deadline(parsed, as_of_utc="2026-08-21T17:30:00Z")

    assert resolved.gameweek == 2


def test_the_sources_own_next_flag_is_not_trusted() -> None:
    """We cannot establish when the source last updated that flag; a deadline we can."""

    events = [
        {"id": 1, "deadline_time": "2026-08-21T17:30:00Z", "finished": True, "is_next": True},
        {"id": 2, "deadline_time": "2026-08-28T17:30:00Z", "finished": False, "is_next": False},
    ]
    parsed = gameweek_deadlines(_payload(events=events))

    resolved = next_open_deadline(parsed, as_of_utc="2026-08-25T12:00:00Z")

    assert resolved.gameweek == 2


def test_a_capture_after_every_deadline_is_an_error() -> None:
    parsed = gameweek_deadlines(_payload())

    with pytest.raises(DataSourceError, match="Every published deadline had closed"):
        next_open_deadline(parsed, as_of_utc="2027-06-01T00:00:00Z")


def test_an_empty_deadline_sequence_is_an_error() -> None:
    with pytest.raises(DataSourceError, match="No gameweek deadlines"):
        next_open_deadline((), as_of_utc="2026-08-21T16:00:00Z")


def test_a_local_time_as_of_is_rejected() -> None:
    parsed = gameweek_deadlines(_payload())

    with pytest.raises(DataSourceError, match="as_of_utc must be expressed in UTC"):
        next_open_deadline(parsed, as_of_utc="2026-08-21T19:00:00+03:00")


def test_a_deadline_without_a_timezone_is_rejected() -> None:
    events = [{"id": 1, "deadline_time": "2026-08-21T17:30:00", "finished": False}]

    with pytest.raises(DataSourceError, match="Event 1 deadline_time must state a timezone"):
        gameweek_deadlines(_payload(events=events))


def test_a_repeated_gameweek_is_rejected() -> None:
    events = [
        {"id": 1, "deadline_time": "2026-08-21T17:30:00Z", "finished": False},
        {"id": 1, "deadline_time": "2026-08-22T17:30:00Z", "finished": False},
    ]

    with pytest.raises(DuplicateRecordsError, match="gameweek 1 more than once"):
        gameweek_deadlines(_payload(events=events))


def test_a_non_positive_gameweek_is_rejected() -> None:
    events = [{"id": 0, "deadline_time": "2026-08-21T17:30:00Z", "finished": False}]

    with pytest.raises(InvalidValueError, match="below the minimum"):
        gameweek_deadlines(_payload(events=events))


def test_a_non_boolean_finished_flag_is_rejected() -> None:
    events = [{"id": 1, "deadline_time": "2026-08-21T17:30:00Z", "finished": "no"}]

    with pytest.raises(InvalidValueError, match="must be a boolean"):
        gameweek_deadlines(_payload(events=events))


def test_a_missing_events_section_is_treated_as_a_changed_payload() -> None:
    document = json.loads(_payload())
    del document["events"]

    with pytest.raises(DataSourceError, match="non-empty"):
        gameweek_deadlines(json.dumps(document).encode("utf-8"))


def test_a_deadline_record_is_immutable() -> None:
    entry = gameweek_deadlines(_payload())[0]

    with pytest.raises(AttributeError):
        entry.gameweek = 5  # type: ignore[misc]


def test_the_parsed_deadline_reports_whether_the_gameweek_finished() -> None:
    events = [{"id": 1, "deadline_time": "2026-08-21T17:30:00Z", "finished": True}]

    assert gameweek_deadlines(_payload(events=events)) == (
        GameweekDeadline(gameweek=1, deadline_utc="2026-08-21T17:30:00Z", finished=True),
    )
