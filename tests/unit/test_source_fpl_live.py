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
    player_snapshot,
    team_names,
)

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
    **overrides: Any,
) -> bytes:
    document: dict[str, Any] = {
        "teams": TEAMS if teams is None else teams,
        "elements": [_element()] if elements is None else elements,
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
