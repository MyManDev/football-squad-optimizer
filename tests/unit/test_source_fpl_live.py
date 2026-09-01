"""Tests for the live-endpoint snapshot adapter.

Every payload here is hand-built. The adapter reads bytes that are already on disk,
so nothing in this file needs a network or a captured snapshot.
"""

import dataclasses
import json
import re
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
    EntryPicksRecord,
    GameweekDeadline,
    LeagueStanding,
    LiveEventPoints,
    availability_snapshot,
    entry_endpoint_paths,
    entry_history_payload,
    entry_label,
    entry_payload,
    entry_picks_payload,
    fixture_snapshot,
    fpl_entry_picks,
    fpl_league_standings,
    fpl_league_standings_page,
    fpl_live_event_points,
    gameweek_deadlines,
    league_standings_endpoint_path,
    league_standings_page_endpoint_path,
    league_standings_page_payload,
    league_standings_payload,
    live_endpoint_path,
    live_payload,
    next_open_deadline,
    player_codes,
    player_snapshot,
    team_codes,
    team_names,
)

EVENTS: list[dict[str, Any]] = [
    {"id": 1, "deadline_time": "2026-08-21T17:30:00Z", "finished": False, "is_next": True},
    {"id": 2, "deadline_time": "2026-08-28T17:30:00Z", "finished": False, "is_next": False},
    {"id": 3, "deadline_time": "2026-09-11T17:30:00Z", "finished": False, "is_next": False},
]

TEAMS: list[dict[str, Any]] = [
    {"id": 1, "code": 3, "name": "Arsenal", "short_name": "ARS"},
    {"id": 14, "code": 14, "name": "Man Utd", "short_name": "MUN"},
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
        "news_added": None,
        "selected_by_percent": "41.2",
        # Cumulative counters. Present in the real payload, and season-relative: before
        # the opening kick-off they carry the previous season's totals. Included here so
        # the builder matches what the source actually serves.
        "minutes": 2700,
        "total_points": 180,
        "starts": 30,
        "goals_scored": 12,
        "assists": 9,
        "clean_sheets": 11,
        "goals_conceded": 28,
        "saves": 0,
        "bonus": 21,
        "bps": 640,
        "own_goals": 0,
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


# --- live fixtures ----------------------------------------------------------

SNAPSHOT_ID = "fpl-live-20260813T201143Z-55789a780186"
CAPTURED_AT = "2026-08-13T20:11:43Z"


def _fixture(**overrides: Any) -> dict[str, Any]:
    record: dict[str, Any] = {
        "id": 1,
        "event": 1,
        "team_h": 1,
        "team_a": 14,
        "team_h_difficulty": 2,
        "team_a_difficulty": 5,
        "kickoff_time": "2026-08-21T19:00:00Z",
        "finished": False,
        "provisional_start_time": False,
    }
    record.update(overrides)
    return record


def _fixtures_payload(records: list[dict[str, Any]] | None = None) -> bytes:
    return json.dumps([_fixture()] if records is None else records).encode("utf-8")


def _build(
    fixtures: list[dict[str, Any]] | None = None,
    *,
    bootstrap: bytes | None = None,
    season: str = "2026-27",
) -> Any:
    return fixture_snapshot(
        _fixtures_payload(fixtures),
        _payload() if bootstrap is None else bootstrap,
        season=season,
        snapshot_id=SNAPSHOT_ID,
        captured_at_utc=CAPTURED_AT,
    )


def test_a_live_fixture_becomes_one_row_per_team_keyed_on_the_code() -> None:
    """Team 1 has code 3 and team 14 has code 14, so ids cannot pass as codes."""

    frame = _build()

    assert len(frame) == 2
    assert sorted(frame["team_id"].tolist()) == [3, 14]


def test_a_live_capture_fills_both_provenance_fields() -> None:
    """This is what a live row has and an archive backfill cannot."""

    frame = _build()

    assert frame["captured_at_utc"].unique().tolist() == [CAPTURED_AT]
    assert frame["deadline_timestamp_utc"].unique().tolist() == ["2026-08-21T17:30:00Z"]
    assert frame["snapshot_id"].unique().tolist() == [SNAPSHOT_ID]


def test_the_deadline_comes_from_the_fixtures_own_gameweek() -> None:
    frame = _build([_fixture(event=2)])

    assert frame["deadline_timestamp_utc"].unique().tolist() == ["2026-08-28T17:30:00Z"]


@pytest.mark.parametrize(
    ("finished", "provisional", "expected"),
    [(True, False, "final"), (False, True, "provisional"), (False, False, "scheduled")],
)
def test_live_status_is_derived_from_the_published_flags(
    finished: bool, provisional: bool, expected: str
) -> None:
    frame = _build([_fixture(finished=finished, provisional_start_time=provisional)])

    assert frame["status"].unique().tolist() == [expected]


def test_a_fixture_without_a_gameweek_is_excluded() -> None:
    frame = _build([_fixture(id=1, event=1), _fixture(id=2, event=None)])

    assert frame["fixture_id"].unique().tolist() == [1]


def test_a_fixture_awaiting_a_kickoff_time_is_kept_with_an_empty_one() -> None:
    """No feature reads the kickoff time, so the row is worth more than the field."""

    frame = _build([_fixture(kickoff_time=None)])

    assert len(frame) == 2
    assert frame["kickoff_time_utc"].isna().all()


def test_every_fixture_lacking_a_gameweek_is_an_error() -> None:
    with pytest.raises(DataSourceError, match="every fixture lacked a gameweek"):
        _build([_fixture(event=None)])


def test_a_fixture_on_an_undeclared_team_is_rejected() -> None:
    with pytest.raises(InvalidValueError, match="does not declare"):
        _build([_fixture(team_a=99)])


def test_a_fixture_in_an_unpublished_gameweek_is_rejected() -> None:
    with pytest.raises(InvalidValueError, match="does not publish"):
        _build([_fixture(event=38)])


def test_a_malformed_season_is_rejected() -> None:
    with pytest.raises(InvalidValueError, match="spelled like"):
        _build(season="2026/27")


def test_a_season_that_contradicts_the_payload_is_rejected() -> None:
    """A typo would otherwise file a capture under the wrong season."""

    with pytest.raises(InvalidValueError, match="earliest deadline falls in 2026"):
        _build(season="2025-26")


def test_a_fixtures_payload_that_is_not_an_array_is_rejected() -> None:
    with pytest.raises(DataSourceError, match="must be a non-empty JSON array"):
        fixture_snapshot(
            b"{}",
            _payload(),
            season="2026-27",
            snapshot_id=SNAPSHOT_ID,
            captured_at_utc=CAPTURED_AT,
        )


def test_a_non_object_fixture_entry_is_rejected() -> None:
    with pytest.raises(DataSourceError, match="non-object entries"):
        fixture_snapshot(
            json.dumps([_fixture(), 7]).encode("utf-8"),
            _payload(),
            season="2026-27",
            snapshot_id=SNAPSHOT_ID,
            captured_at_utc=CAPTURED_AT,
        )


@pytest.mark.parametrize("field", ["id", "team_h", "team_h_difficulty", "kickoff_time"])
def test_a_renamed_fixture_field_stops_the_run(field: str) -> None:
    record = _fixture()
    del record[field]

    with pytest.raises(DataSourceError, match=field):
        _build([record])


def test_a_local_time_capture_instant_is_rejected() -> None:
    with pytest.raises(DataSourceError, match="captured_at_utc must be expressed in UTC"):
        fixture_snapshot(
            _fixtures_payload(),
            _payload(),
            season="2026-27",
            snapshot_id=SNAPSHOT_ID,
            captured_at_utc="2026-08-13T23:11:43+03:00",
        )


def test_team_codes_map_the_per_season_integer_to_the_persistent_code() -> None:
    assert dict(team_codes(_payload())) == {1: 3, 14: 14}


# --- player codes -----------------------------------------------------------
#
# The same problem one level down, and the one that actually bit: the entry endpoints
# name a player by his per-season element id while everything downstream of a capture
# names him by code. Both are integers, so a mismatch matches nothing instead of raising
# (#265). What these tests pin is that the translation cannot be quietly incomplete —
# every way of losing a row here produces lookups that still *look* correct.


def test_player_codes_map_the_per_season_element_id_to_the_persistent_code() -> None:
    payload = _payload([_element(id=5, code=118748), _element(id=9, code=154043)])

    assert dict(player_codes(payload)) == {5: 118748, 9: 154043}


def test_player_codes_agree_with_the_snapshot_on_the_same_payload() -> None:
    """Two readings of one document must not drift into different identity spaces."""

    payload = _payload([_element(id=5, code=118748), _element(id=9, code=154043)])

    mapping = player_codes(payload)
    snapshot = player_snapshot(payload)

    assert sorted(mapping.values()) == sorted(snapshot["player_id"].tolist())


def test_an_element_without_a_code_stops_the_run_rather_than_shrinking_the_map() -> None:
    """The regression this function exists for.

    A translation table built by skipping the rows it cannot read comes back shorter, and
    the failure then surfaces as "the capture does not name element 9" — blaming one
    player for a renamed field. A missing field is a changed payload and has to say so.
    """

    element = _element(id=9, code=154043)
    del element["code"]

    with pytest.raises(DataSourceError, match="missing fields"):
        player_codes(_payload([_element(id=5, code=118748), element]))


def test_a_repeated_element_id_is_refused_because_the_mapping_would_be_ambiguous() -> None:
    payload = _payload([_element(id=5, code=118748), _element(id=5, code=154043)])

    with pytest.raises(DuplicateRecordsError, match="element id 5"):
        player_codes(payload)


def test_a_repeated_code_is_refused_because_it_would_merge_two_players() -> None:
    """The more expensive duplicate: the key stays unique and two people become one."""

    payload = _payload([_element(id=5, code=118748), _element(id=9, code=118748)])

    with pytest.raises(DuplicateRecordsError, match="merge two of them"):
        player_codes(payload)


def test_a_manager_element_is_translated_rather_than_filtered_out() -> None:
    """A translation table, not a roster.

    `player_snapshot` drops non-players deliberately. Doing the same here would surface
    downstream as "the capture does not name element N" for a document that legitimately
    contains one — blaming the payload for a filter applied on this side.
    """

    payload = _payload(
        [_element(id=5, code=118748, element_type=3), _element(id=7, code=99, element_type=5)]
    )

    assert dict(player_codes(payload)) == {5: 118748, 7: 99}
    assert 99 not in player_snapshot(payload)["player_id"].tolist()


# --- availability -----------------------------------------------------------


def test_availability_is_a_separate_table_from_the_player_snapshot() -> None:
    """These fields never enter a model matrix, so they never become snapshot columns."""

    availability = availability_snapshot(_payload())

    assert tuple(availability.columns) == (
        "player_id",
        "status",
        "chance_of_playing",
        "news_added_utc",
    )


def test_availability_keys_on_the_persistent_code() -> None:
    availability = availability_snapshot(_payload([_element(code=118748)]))

    assert availability["player_id"].tolist() == [118748]


def test_an_absent_chance_of_playing_stays_absent() -> None:
    """Most of a roster carries no chance at all, and that is not a zero."""

    availability = availability_snapshot(_payload([_element(chance_of_playing_next_round=None)]))

    assert availability["chance_of_playing"].isna().all()


def test_a_stated_chance_is_kept_as_an_integer() -> None:
    availability = availability_snapshot(_payload([_element(chance_of_playing_next_round=75)]))

    assert availability["chance_of_playing"].tolist() == [75]


def test_news_timestamps_are_normalised_to_utc() -> None:
    availability = availability_snapshot(
        _payload([_element(news_added="2026-08-09T09:30:07.136250Z")])
    )

    assert availability["news_added_utc"].tolist() == ["2026-08-09T09:30:07.136250Z"]


def test_a_missing_news_timestamp_stays_absent() -> None:
    availability = availability_snapshot(_payload([_element(news_added=None)]))

    assert availability["news_added_utc"].isna().all()


def test_non_players_are_excluded_from_availability_too() -> None:
    availability = availability_snapshot(
        _payload([_element(code=1, element_type=3), _element(code=2, element_type=5)])
    )

    assert availability["player_id"].tolist() == [1]


def test_a_non_integer_chance_is_rejected() -> None:
    with pytest.raises(InvalidValueError, match="chance_of_playing_next_round"):
        availability_snapshot(_payload([_element(chance_of_playing_next_round="75")]))


@pytest.mark.parametrize("field", ["status", "chance_of_playing_next_round", "news_added"])
def test_a_renamed_availability_field_stops_the_run(field: str) -> None:
    record = _element()
    record.pop(field, None)

    with pytest.raises(DataSourceError, match=field):
        availability_snapshot(_payload([record]))


# --- registered entries and their league ----------------------------------------------
#
# Same rule as the rest of this file: every payload is hand-built, nothing reaches a
# network, and a renamed source field has to stop the run rather than emit a null.

_PAYLOAD_NAME = re.compile(r"^[a-z0-9]+(?:[-_.][a-z0-9]+)*$")


def _picks_payload(
    *,
    squad: list[int] | None = None,
    captain_position: int | None = 1,
    vice_position: int | None = 2,
    bank: int = 5,
    positions: list[int] | None = None,
) -> bytes:
    """Return one ``event/{gw}/picks`` document carrying the fields the adapter reads."""

    elements = squad if squad is not None else list(range(101, 116))
    slots = positions if positions is not None else list(range(1, len(elements) + 1))
    picks = [
        {
            "element": element,
            "position": position,
            "is_captain": position == captain_position,
            "is_vice_captain": position == vice_position,
            "multiplier": 2 if position == captain_position else (1 if position <= 11 else 0),
        }
        for element, position in zip(elements, slots, strict=True)
    ]
    document = {
        "picks": picks,
        "active_chip": None,
        "entry_history": {"bank": bank, "event_transfers": 0, "event_transfers_cost": 0},
    }
    return json.dumps(document).encode("utf-8")


def _history_payload(
    *,
    chips: list[dict[str, Any]] | None = None,
    current: list[dict[str, Any]] | None = None,
) -> bytes:
    document = {
        "chips": [] if chips is None else chips,
        "current": (
            current
            if current is not None
            else [
                {
                    "event": 1,
                    "points": 64,
                    "total_points": 64,
                    "event_transfers": 0,
                    "points_on_bench": 3,
                    "bank": 5,
                }
            ]
        ),
    }
    return json.dumps(document).encode("utf-8")


def _standings_payload(
    *,
    results: list[dict[str, Any]] | None = None,
    has_next: bool = False,
    league_id: int = 352490,
) -> bytes:
    rows = (
        results
        if results is not None
        else [
            {"entry": 11, "entry_name": "First XI", "player_name": "A Manager", "rank": 1},
            {"entry": 22, "entry_name": "Second XI", "player_name": "B Manager", "rank": 2},
        ]
    )
    document = {
        "league": {"id": league_id, "name": "The Mini League"},
        "standings": {"has_next": has_next, "page": 1, "results": rows},
    }
    return json.dumps(document).encode("utf-8")


def _paged_standings_payload(*, page: int = 1, start_rank: int = 1, has_next: bool = True) -> bytes:
    rows = [
        {
            "entry": 1000 + rank_sort,
            "entry_name": f"Entry {rank_sort}",
            "player_name": f"Manager {rank_sort}",
            "rank": start_rank,
            "rank_sort": rank_sort,
        }
        for rank_sort in range(start_rank, start_rank + 50)
    ]
    return json.dumps(
        {
            "league": {"id": 314, "name": "Overall"},
            "standings": {"has_next": has_next, "page": page, "results": rows},
            "last_updated_data": "2026-09-01T03:34:24Z",
        }
    ).encode("utf-8")


def _entry_payload(*, entry_id: int = 11, name: str = "First XI") -> bytes:
    return json.dumps({"id": entry_id, "name": name, "current_event": 1}).encode("utf-8")


def test_every_built_payload_name_stays_inside_the_snapshot_grammar() -> None:
    names = [
        entry_payload(11),
        entry_history_payload(11),
        entry_picks_payload(11, 2),
        league_standings_payload(352490),
        league_standings_page_payload(314, 2),
        live_payload(2),
    ]
    assert names == [
        "entry-11.json",
        "entry-11-history.json",
        "entry-11-picks-gw02.json",
        "league-352490-standings.json",
        "league-314-standings-page-02.json",
        "event-gw02-live.json",
    ]
    for name in names:
        assert _PAYLOAD_NAME.match(name), name


@pytest.mark.parametrize("identifier", [0, -1, True])
def test_a_payload_name_refuses_an_identifier_the_source_never_publishes(identifier: Any) -> None:
    with pytest.raises(InvalidValueError):
        entry_payload(identifier)


def test_each_entry_contributes_three_documents_with_the_gameweek_in_its_picks() -> None:
    paths = entry_endpoint_paths([11, 22], gameweek=1)
    assert dict(paths) == {
        "entry-11.json": "entry/11/",
        "entry-11-history.json": "entry/11/history/",
        "entry-11-picks-gw01.json": "entry/11/event/1/picks/",
        "entry-22.json": "entry/22/",
        "entry-22-history.json": "entry/22/history/",
        "entry-22-picks-gw01.json": "entry/22/event/1/picks/",
    }


def test_the_endpoint_map_carries_paths_rather_than_urls() -> None:
    """The base URL and the transport stay with the platform adapter, not here."""

    paths = list(entry_endpoint_paths([11], gameweek=2).values())
    paths += list(league_standings_endpoint_path(352490).values())
    paths += list(league_standings_page_endpoint_path(314, 2).values())
    assert not any(path.startswith("http") for path in paths)


def test_a_numbered_standings_page_preserves_the_sources_total_order() -> None:
    page = fpl_league_standings_page(
        _paged_standings_payload(page=2, start_rank=51),
        league_id=314,
        expected_page=2,
    )

    assert page.page == 2
    assert page.has_next is True
    assert page.last_updated_data == "2026-09-01T03:34:24Z"
    assert [member.rank_sort for member in page.members] == list(range(51, 101))


def test_a_numbered_standings_page_rejects_the_wrong_page_or_repeated_order() -> None:
    with pytest.raises(DataSourceError, match="not requested page"):
        fpl_league_standings_page(
            _paged_standings_payload(page=2, start_rank=51),
            league_id=314,
            expected_page=1,
        )

    document = json.loads(_paged_standings_payload().decode("utf-8"))
    document["standings"]["results"][1]["rank_sort"] = 1
    with pytest.raises(DuplicateRecordsError, match="rank_sort 1"):
        fpl_league_standings_page(
            json.dumps(document).encode("utf-8"),
            league_id=314,
            expected_page=1,
        )


def test_a_registry_that_lists_an_entry_twice_is_rejected() -> None:
    with pytest.raises(InvalidValueError, match="distinct"):
        entry_endpoint_paths([11, 22, 11], gameweek=1)


def test_the_league_page_yields_its_members_in_rank_order() -> None:
    members = fpl_league_standings(_standings_payload(), league_id=352490)
    assert [member.entry_id for member in members] == [11, 22]
    assert members[0] == LeagueStanding(
        entry_id=11, entry_name="First XI", player_name="A Manager", rank=1
    )


def test_a_league_with_further_pages_is_refused_rather_than_truncated() -> None:
    with pytest.raises(DataSourceError, match="more standings pages"):
        fpl_league_standings(_standings_payload(has_next=True), league_id=352490)


def test_a_standings_payload_describing_another_league_is_rejected() -> None:
    with pytest.raises(DataSourceError, match="declares league 999"):
        fpl_league_standings(_standings_payload(league_id=999), league_id=352490)


def test_a_league_listing_the_same_entry_twice_is_rejected() -> None:
    rows = [
        {"entry": 11, "entry_name": "First XI", "player_name": "A Manager", "rank": 1},
        {"entry": 11, "entry_name": "First XI", "player_name": "A Manager", "rank": 2},
    ]
    with pytest.raises(DuplicateRecordsError):
        fpl_league_standings(_standings_payload(results=rows), league_id=352490)


def test_a_standings_payload_without_its_standings_object_is_rejected() -> None:
    document = {"league": {"id": 352490}, "standings": []}
    with pytest.raises(DataSourceError, match="'standings' object"):
        fpl_league_standings(json.dumps(document).encode("utf-8"), league_id=352490)


@pytest.mark.parametrize("field", ["entry", "entry_name", "player_name", "rank"])
def test_a_renamed_standings_field_stops_the_run_and_names_itself(field: str) -> None:
    row = {"entry": 11, "entry_name": "First XI", "player_name": "A Manager", "rank": 1}
    del row[field]
    with pytest.raises(DataSourceError, match=field):
        fpl_league_standings(_standings_payload(results=[row]), league_id=352490)


def test_the_entry_summary_supplies_the_registry_label() -> None:
    assert entry_label(_entry_payload(), entry_id=11) == "First XI"


def test_an_entry_payload_describing_another_entry_is_rejected() -> None:
    with pytest.raises(DataSourceError, match="declares entry 99"):
        entry_label(_entry_payload(entry_id=99), entry_id=11)


def test_a_nameless_entry_is_rejected() -> None:
    with pytest.raises(InvalidValueError, match="empty team name"):
        entry_label(_entry_payload(name="  "), entry_id=11)


def test_the_picks_document_becomes_a_fifteen_player_squad_starting_eleven() -> None:
    record = fpl_entry_picks(
        _picks_payload(),
        _history_payload(),
        entry_id=11,
        season="2026-27",
        gameweek=1,
        source_snapshot_id="fpl-live-20260825T000000Z-abc",
    )
    assert record.squad == tuple(range(101, 116))
    assert record.starting_xi == tuple(range(101, 112))
    assert record.captain == 101
    assert record.bank_tenths == 5
    assert record.gameweek == 1
    assert record.season == "2026-27"
    assert record.source_snapshot_id == "fpl-live-20260825T000000Z-abc"


def test_the_two_limits_the_public_endpoints_impose_are_flagged_not_guessed() -> None:
    record = fpl_entry_picks(
        _picks_payload(), _history_payload(), entry_id=11, season="2026-27", gameweek=1
    )
    assert record.free_transfers == 1
    assert record.free_transfers_known is False
    assert dict(record.purchase_prices) == {}
    assert record.purchase_prices_known is False


def test_chips_are_read_from_the_history_and_grouped_by_name() -> None:
    chips = [
        {"name": "bboost", "event": 3},
        {"name": "3xc", "event": 7},
        {"name": "bboost", "event": 2},
    ]
    record = fpl_entry_picks(
        _picks_payload(),
        _history_payload(chips=chips),
        entry_id=11,
        season="2026-27",
        gameweek=1,
    )
    assert dict(record.chips_used) == {"bboost": (2, 3), "3xc": (7,)}


def test_an_entry_that_has_played_no_chip_reports_no_chips() -> None:
    record = fpl_entry_picks(
        _picks_payload(), _history_payload(), entry_id=11, season="2026-27", gameweek=1
    )
    assert dict(record.chips_used) == {}


def test_a_history_without_its_chips_array_is_a_changed_payload() -> None:
    document = {"current": []}
    with pytest.raises(DataSourceError, match="'chips' array"):
        fpl_entry_picks(
            _picks_payload(),
            json.dumps(document).encode("utf-8"),
            entry_id=11,
            season="2026-27",
            gameweek=1,
        )


def test_a_squad_missing_a_position_is_rejected_rather_than_padded() -> None:
    with pytest.raises(DataSourceError, match="squad positions 1 to 15"):
        fpl_entry_picks(
            _picks_payload(squad=list(range(101, 115)), positions=list(range(1, 15))),
            _history_payload(),
            entry_id=11,
            season="2026-27",
            gameweek=1,
        )


def test_a_repeated_squad_position_is_rejected() -> None:
    with pytest.raises(DuplicateRecordsError, match="position 1 twice"):
        fpl_entry_picks(
            _picks_payload(squad=list(range(101, 116)), positions=[1] * 15),
            _history_payload(),
            entry_id=11,
            season="2026-27",
            gameweek=1,
        )


@pytest.mark.parametrize(("captain_position", "count"), [(None, 0), (16, 0)])
def test_a_squad_without_exactly_one_captain_is_rejected(
    captain_position: int | None, count: int
) -> None:
    with pytest.raises(DataSourceError, match=f"names {count} captains"):
        fpl_entry_picks(
            _picks_payload(captain_position=captain_position),
            _history_payload(),
            entry_id=11,
            season="2026-27",
            gameweek=1,
        )


def test_a_captain_outside_the_starting_eleven_is_rejected() -> None:
    with pytest.raises(InvalidValueError, match="not in the starting eleven"):
        fpl_entry_picks(
            _picks_payload(captain_position=12),
            _history_payload(),
            entry_id=11,
            season="2026-27",
            gameweek=1,
        )


def test_picks_without_their_entry_history_are_rejected() -> None:
    document = json.loads(_picks_payload().decode("utf-8"))
    del document["entry_history"]
    with pytest.raises(DataSourceError, match="'entry_history'"):
        fpl_entry_picks(
            json.dumps(document).encode("utf-8"),
            _history_payload(),
            entry_id=11,
            season="2026-27",
            gameweek=1,
        )


@pytest.mark.parametrize("field", ["element", "position", "is_captain"])
def test_a_renamed_pick_field_stops_the_run_and_names_itself(field: str) -> None:
    document = json.loads(_picks_payload().decode("utf-8"))
    for pick in document["picks"]:
        del pick[field]
    with pytest.raises(DataSourceError, match=field):
        fpl_entry_picks(
            json.dumps(document).encode("utf-8"),
            _history_payload(),
            entry_id=11,
            season="2026-27",
            gameweek=1,
        )


def test_the_twin_carries_exactly_the_application_seams_fields() -> None:
    """The twin exists so ``data`` never imports ``application``; drift defeats the point.

    A field added on either side without the other is the failure this pins: the
    application maps the twin by name, so a mismatch is a silent dropped field.
    """

    from squadopt.application.entries import EntryPicks

    assert {field.name for field in dataclasses.fields(EntryPicksRecord)} == {
        field.name for field in dataclasses.fields(EntryPicks)
    }


# --- live gameweek points -----------------------------------------------------------
#
# These points exist to be shown while a gameweek is still being played, so every test
# below is really about one question: can a reader tell how finished the number is?


def _live_element(player: int, points: int, **stats: Any) -> dict[str, Any]:
    record: dict[str, Any] = {
        "minutes": 90,
        "bonus": 0,
        "bps": 20,
        "total_points": points,
    }
    record.update(stats)
    return {"id": player, "stats": record, "explain": [], "modified": True}


def _live_payload(elements: list[dict[str, Any]] | None = None) -> bytes:
    records = [_live_element(1, 6), _live_element(2, 2)] if elements is None else elements
    return json.dumps({"elements": records}).encode("utf-8")


def _gameweek_fixtures(finished: int, total: int, *, event: int = 1) -> bytes:
    records = [
        _fixture(id=index + 1, event=event, finished=index < finished) for index in range(total)
    ]
    return json.dumps(records).encode("utf-8")


def test_the_live_payload_name_maps_to_its_endpoint() -> None:
    """The grammar itself is asserted with the other built names, in one place."""

    assert live_endpoint_path(2) == {"event-gw02-live.json": "event/2/live/"}


@pytest.mark.parametrize("gameweek", [0, -1, True])
def test_a_live_payload_name_refuses_a_gameweek_that_is_not_one(gameweek: Any) -> None:
    with pytest.raises(InvalidValueError, match="gameweek"):
        live_payload(gameweek)


def test_points_are_read_per_player_with_the_gameweeks_progress_beside_them() -> None:
    result = fpl_live_event_points(
        _live_payload(),
        _gameweek_fixtures(finished=6, total=10),
        gameweek=1,
        source_snapshot_id="fpl-live-20260822T140000Z-abc",
    )

    assert result.points_by_player == {1: 6, 2: 2}
    assert result.minutes_by_player == {1: 90, 2: 90}
    assert (result.fixtures_finished, result.fixtures_total) == (6, 10)
    assert result.bonus_confirmed is False
    assert result.source_snapshot_id == "fpl-live-20260822T140000Z-abc"


def test_bonus_is_confirmed_only_when_every_fixture_of_the_gameweek_is_finished() -> None:
    """The distinction the whole record exists for.

    The platform adds bonus to a player's total when *his* fixture finishes, so a score
    read earlier is short by up to three points per player and short by different amounts
    for different players. Nine of ten finished is not "basically final".
    """

    nearly = fpl_live_event_points(_live_payload(), _gameweek_fixtures(9, 10), gameweek=1)
    complete = fpl_live_event_points(_live_payload(), _gameweek_fixtures(10, 10), gameweek=1)

    assert nearly.bonus_confirmed is False
    assert complete.bonus_confirmed is True


def test_progress_is_counted_for_the_asked_gameweek_only() -> None:
    """The live document names no gameweek, so the fixtures decide which one this is."""

    fixtures = json.dumps(
        [
            _fixture(id=1, event=1, finished=True),
            _fixture(id=2, event=1, finished=True),
            _fixture(id=3, event=2, finished=False),
        ]
    ).encode("utf-8")

    result = fpl_live_event_points(_live_payload(), fixtures, gameweek=1)

    assert (result.fixtures_finished, result.fixtures_total) == (2, 2)
    assert result.bonus_confirmed is True


def test_a_gameweek_with_no_fixtures_is_refused_rather_than_scored() -> None:
    """A live score for a gameweek the fixtures do not mention describes nothing."""

    with pytest.raises(InvalidValueError, match="no fixtures"):
        fpl_live_event_points(_live_payload(), _gameweek_fixtures(1, 1, event=1), gameweek=7)


def test_a_stats_section_that_is_not_an_object_stops_the_read() -> None:
    payload = json.dumps({"elements": [{"id": 1, "stats": [], "explain": []}]}).encode("utf-8")

    with pytest.raises(DataSourceError, match="stats"):
        fpl_live_event_points(payload, _gameweek_fixtures(1, 1), gameweek=1)


def test_a_missing_stats_section_names_the_field_rather_than_emitting_a_null() -> None:
    payload = json.dumps({"elements": [{"id": 1, "explain": []}]}).encode("utf-8")

    with pytest.raises(DataSourceError, match="stats"):
        fpl_live_event_points(payload, _gameweek_fixtures(1, 1), gameweek=1)


def test_non_integer_points_are_refused() -> None:
    payload = _live_payload([_live_element(1, 6), _live_element(2, 0, total_points="4")])

    with pytest.raises(InvalidValueError, match="total_points"):
        fpl_live_event_points(payload, _gameweek_fixtures(1, 1), gameweek=1)


def test_a_repeated_player_is_a_changed_payload_not_a_last_one_wins() -> None:
    payload = _live_payload([_live_element(1, 6), _live_element(1, 2)])

    with pytest.raises(DuplicateRecordsError, match="more than once"):
        fpl_live_event_points(payload, _gameweek_fixtures(1, 1), gameweek=1)


def test_an_empty_elements_array_is_refused() -> None:
    payload = json.dumps({"elements": []}).encode("utf-8")

    with pytest.raises(DataSourceError, match="elements"):
        fpl_live_event_points(payload, _gameweek_fixtures(1, 1), gameweek=1)


def test_the_record_refuses_to_claim_confirmed_bonus_while_fixtures_are_unfinished() -> None:
    """The guard is on the record itself, so no future caller can assemble the lie."""

    with pytest.raises(InvalidValueError, match="cannot hold"):
        LiveEventPoints(
            gameweek=1,
            points_by_player={1: 6},
            minutes_by_player={1: 90},
            bonus_confirmed=True,
            fixtures_finished=9,
            fixtures_total=10,
        )


# --- the entry's own history as the source of a member's score ------------------------
#
# The league page's points come from here rather than from the standings table: a history
# row names the gameweek it belongs to, and the standings' event_total does not.


def test_the_history_returns_each_played_gameweek_in_order() -> None:
    from squadopt.data.sources.fpl_live import fpl_entry_history_points

    payload = _history_payload(
        current=[
            {"event": 2, "points": 51, "total_points": 115},
            {"event": 1, "points": 64, "total_points": 64},
        ]
    )

    weeks = fpl_entry_history_points(payload, entry_id=11)

    assert [(week.gameweek, week.points, week.total_points) for week in weeks] == [
        (1, 64, 64),
        (2, 51, 115),
    ]
    assert {week.entry_id for week in weeks} == {11}


def test_a_week_that_ended_negative_after_a_hit_is_read_rather_than_refused() -> None:
    """A minus four is a real score; refusing it would invent data as surely as a zero."""

    from squadopt.data.sources.fpl_live import fpl_entry_history_points

    payload = _history_payload(current=[{"event": 7, "points": -2, "total_points": 300}])

    assert fpl_entry_history_points(payload, entry_id=11)[0].points == -2


@pytest.mark.parametrize("field", ["event", "points", "total_points"])
def test_a_renamed_history_field_is_refused_by_name(field: str) -> None:
    from squadopt.data.sources.fpl_live import fpl_entry_history_points

    row = {"event": 1, "points": 64, "total_points": 64}
    del row[field]

    with pytest.raises(DataSourceError, match=field):
        fpl_entry_history_points(_history_payload(current=[row]), entry_id=11)


def test_a_gameweek_listed_twice_is_refused() -> None:
    from squadopt.data.sources.fpl_live import fpl_entry_history_points

    payload = _history_payload(
        current=[
            {"event": 1, "points": 64, "total_points": 64},
            {"event": 1, "points": 51, "total_points": 115},
        ]
    )

    with pytest.raises(DuplicateRecordsError, match="gameweek 1"):
        fpl_entry_history_points(payload, entry_id=11)


def test_a_history_with_no_played_weeks_is_refused_rather_than_read_as_empty() -> None:
    from squadopt.data.sources.fpl_live import fpl_entry_history_points

    with pytest.raises(DataSourceError, match="current"):
        fpl_entry_history_points(_history_payload(current=[]), entry_id=11)


def test_non_integer_history_points_are_refused() -> None:
    from squadopt.data.sources.fpl_live import fpl_entry_history_points

    payload = _history_payload(current=[{"event": 1, "points": "64", "total_points": 64}])

    with pytest.raises(InvalidValueError, match="points"):
        fpl_entry_history_points(payload, entry_id=11)


# --- which weeks may be published at all ----------------------------------------------


def _events_payload(events: list[dict[str, Any]]) -> bytes:
    return json.dumps({"events": events}).encode("utf-8")


@pytest.mark.parametrize(
    ("finished", "data_checked", "scored"),
    [(True, True, True), (True, False, False), (False, False, False)],
)
def test_a_week_counts_as_scored_only_when_finished_and_checked(
    finished: bool, data_checked: bool, scored: bool
) -> None:
    """finished alone is the ledger's gate; bonus lands with data_checked.

    Gameweek 1 sat finished-but-unchecked for eight and a half hours with every fixture
    played, so this is the difference between a member's real score and one short by up to
    three points per player.
    """

    from squadopt.data.sources.fpl_live import scored_gameweeks

    payload = _events_payload([{"id": 1, "finished": finished, "data_checked": data_checked}])

    assert (1 in scored_gameweeks(payload)) is scored


def test_a_bootstrap_without_the_checked_flag_is_refused_by_name() -> None:
    from squadopt.data.sources.fpl_live import scored_gameweeks

    with pytest.raises(DataSourceError, match="data_checked"):
        scored_gameweeks(_events_payload([{"id": 1, "finished": True}]))


# --- minutes, because points alone cannot say which eleven they belong to ------------
#
# The platform's own score replaces a starter who played no minutes with a bench player
# (#262). That rule lives in the ledger; what these tests pin is that its input arrives
# intact, because every way of losing it produces a *wrong eleven* rather than a gap.


def test_minutes_are_read_beside_the_points_and_sorted_with_them() -> None:
    payload = _live_payload([_live_element(2, 2, minutes=45), _live_element(1, 6, minutes=90)])

    result = fpl_live_event_points(payload, _gameweek_fixtures(1, 1), gameweek=1)

    assert result.minutes_by_player == {1: 90, 2: 45}
    assert list(result.minutes_by_player) == sorted(result.minutes_by_player)
    assert set(result.minutes_by_player) == set(result.points_by_player)


def test_a_stats_object_without_minutes_is_refused_rather_than_defaulted_to_zero() -> None:
    """Zero is the one value that must never be guessed: it means 'substitute him'."""

    element = _live_element(1, 6)
    del element["stats"]["minutes"]

    # Absent and non-integer land on the same guard as `total_points` does, and the
    # message names the field rather than the record, so the payload change is legible.
    with pytest.raises(InvalidValueError, match="'minutes' must be an integer"):
        fpl_live_event_points(_live_payload([element]), _gameweek_fixtures(1, 1), gameweek=1)


def test_non_integer_minutes_are_refused() -> None:
    payload = _live_payload([_live_element(1, 6), _live_element(2, 2, minutes="90")])

    with pytest.raises(InvalidValueError, match="minutes"):
        fpl_live_event_points(payload, _gameweek_fixtures(1, 1), gameweek=1)


def test_a_double_gameweek_player_may_exceed_ninety_minutes() -> None:
    """No upper bound, deliberately: 180 is legal and a cap would encode a false rule."""

    payload = _live_payload([_live_element(1, 12, minutes=180)])

    result = fpl_live_event_points(payload, _gameweek_fixtures(2, 2), gameweek=1)

    assert result.minutes_by_player == {1: 180}


def test_negative_minutes_are_refused() -> None:
    with pytest.raises(InvalidValueError, match="negative minutes"):
        LiveEventPoints(
            gameweek=1,
            points_by_player={1: 6},
            minutes_by_player={1: -1},
            bonus_confirmed=False,
            fixtures_finished=0,
            fixtures_total=1,
        )


def test_points_and_minutes_must_describe_the_same_players() -> None:
    """A player with points and no minutes reads as 'did not play' downstream.

    That is not a missing value a caller can route around: the substitution rule would
    field a bench player for someone who was on the pitch, and the resulting eleven looks
    entirely plausible. So the record refuses to exist rather than let a caller assemble it.
    """

    with pytest.raises(InvalidValueError, match="different players"):
        LiveEventPoints(
            gameweek=1,
            points_by_player={1: 6, 2: 2},
            minutes_by_player={1: 90},
            bonus_confirmed=False,
            fixtures_finished=0,
            fixtures_total=1,
        )


# --- the vice-captain, and the order the bench is walked in ---------------------------
#
# Both exist for the same rule (#262): when a starter plays no minutes the platform fields
# a bench player, and when the *captain* plays no minutes the multiplier moves to the vice.
# The adapter's job is to deliver those two inputs unguessed.


def test_the_vice_captain_is_read_beside_the_captain() -> None:
    record = fpl_entry_picks(
        _picks_payload(captain_position=1, vice_position=2),
        _history_payload(),
        entry_id=11,
        season="2026-27",
        gameweek=1,
    )

    assert record.captain == 101
    assert record.vice_captain == 102


def test_a_vice_captain_on_the_bench_is_accepted() -> None:
    """Six real entries named theirs inside the eleven; six is not a rule.

    Refusing a bench vice would reject a real capture, which is a worse failure for an
    adapter than carrying one. The record only requires him to be in the squad.
    """

    record = fpl_entry_picks(
        _picks_payload(captain_position=1, vice_position=13),
        _history_payload(),
        entry_id=11,
        season="2026-27",
        gameweek=1,
    )

    assert record.vice_captain == 113
    assert record.vice_captain not in record.starting_xi


@pytest.mark.parametrize("vice_position", [None, 1])
def test_a_payload_without_exactly_one_vice_captain_is_refused(vice_position: int | None) -> None:
    """None named, or the captain named twice: both leave the multiplier undecided."""

    with pytest.raises((DataSourceError, InvalidValueError)):
        fpl_entry_picks(
            _picks_payload(captain_position=1, vice_position=vice_position),
            _history_payload(),
            entry_id=11,
            season="2026-27",
            gameweek=1,
        )


def test_the_same_player_cannot_be_captain_and_vice() -> None:
    """The one case the platform's own flags could express and the rule cannot use."""

    with pytest.raises(InvalidValueError, match="captain and vice-captain"):
        EntryPicksRecord(
            entry_id=11,
            season="2026-27",
            gameweek=1,
            squad=tuple(range(101, 116)),
            starting_xi=tuple(range(101, 112)),
            captain=101,
            vice_captain=101,
            bank_tenths=0,
            free_transfers=1,
            free_transfers_known=False,
            chips_used={},
            purchase_prices={},
            purchase_prices_known=False,
        )


def test_the_bench_is_the_squad_tail_in_substitution_order() -> None:
    """The property the substitution rule rests on, pinned because it is implicit.

    ``squad`` is built from the platform's pick positions 1 to 15 in order, so the tail is
    the bench in the sequence the platform walks. Nothing in the type says so, and sorting
    the tuple would keep every member while destroying the rule -- a change that would pass
    every other test in this module.
    """

    shuffled = [105, 101, 110, 103, 108, 102, 112, 104, 115, 106, 113, 107, 114, 109, 111]
    record = fpl_entry_picks(
        _picks_payload(squad=shuffled),
        _history_payload(),
        entry_id=11,
        season="2026-27",
        gameweek=1,
    )

    assert record.squad == tuple(shuffled)  # pick order, not sorted
    assert record.starting_xi == tuple(shuffled[:11])
    assert record.squad[11:] == tuple(shuffled[11:])
    assert sorted(record.squad) != list(record.squad)  # the shuffle really was one
