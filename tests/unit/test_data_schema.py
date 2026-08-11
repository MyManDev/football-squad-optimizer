"""Tests for the canonical data-layer schema and controlled vocabularies."""

import pytest

from squadopt.data import (
    AMBIGUOUS_TIMING_COLUMNS,
    CANONICAL_SORT_COLUMNS,
    KEY_COLUMNS,
    MIN_GAMEWEEK,
    OPTIONAL_COLUMNS,
    OUTCOME_COLUMNS,
    PLAYER_GROUP_COLUMNS,
    PLAYER_TIME_SORT_COLUMNS,
    POSITION_ALIASES,
    POSITIONS,
    PRE_MATCH_COLUMNS,
    PRICE_TENTHS_PER_UNIT,
    PROJECTION_REQUIRED_COLUMNS,
    REQUIRED_COLUMNS,
    DataError,
    DataSourceError,
    DataValidationError,
    DuplicateRecordsError,
    InvalidValueError,
    MissingColumnsError,
    is_outcome_column,
    normalize_position,
)


@pytest.mark.parametrize("position", POSITIONS)
def test_canonical_positions_normalize_to_themselves(position: str) -> None:
    assert normalize_position(position) == position


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("GKP", "GK"),
        ("Goalkeeper", "GK"),
        ("Defender", "DEF"),
        ("Midfielder", "MID"),
        ("Forward", "FWD"),
    ],
)
def test_normalizes_known_aliases(raw: str, expected: str) -> None:
    assert normalize_position(raw) == expected


@pytest.mark.parametrize("raw", ["  mid  ", "MiD", "mid", "\tMID\n"])
def test_normalization_ignores_case_and_surrounding_whitespace(raw: str) -> None:
    assert normalize_position(raw) == "MID"


@pytest.mark.parametrize("raw", ["WING", "", "   ", "GK DEF", "keeper"])
def test_rejects_unknown_position_labels(raw: str) -> None:
    with pytest.raises(InvalidValueError, match="Unsupported position value"):
        normalize_position(raw)


@pytest.mark.parametrize("raw", [None, 1, 1.0, True, ["MID"]])
def test_rejects_non_string_position_values(raw: object) -> None:
    with pytest.raises(InvalidValueError, match="Unsupported position value"):
        normalize_position(raw)


def test_rejection_message_identifies_the_offending_value() -> None:
    with pytest.raises(InvalidValueError) as error:
        normalize_position("WING")

    message = str(error.value)
    assert "'WING'" in message
    for position in POSITIONS:
        assert position in message


def test_alias_table_covers_every_canonical_position() -> None:
    assert set(POSITION_ALIASES.values()) == set(POSITIONS)
    assert all(position in POSITION_ALIASES for position in POSITIONS)


def test_alias_table_is_read_only() -> None:
    with pytest.raises(TypeError):
        POSITION_ALIASES["WING"] = "MID"  # type: ignore[index]


def test_alias_keys_are_upper_case_and_stripped() -> None:
    assert all(alias == alias.strip().upper() for alias in POSITION_ALIASES)


def test_key_columns_are_part_of_the_required_schema() -> None:
    assert set(KEY_COLUMNS) <= set(REQUIRED_COLUMNS)


@pytest.mark.parametrize(
    "columns",
    [REQUIRED_COLUMNS, OPTIONAL_COLUMNS, KEY_COLUMNS, PROJECTION_REQUIRED_COLUMNS],
)
def test_column_tuples_contain_no_duplicates(columns: tuple[str, ...]) -> None:
    assert len(columns) == len(set(columns))


def test_optional_columns_do_not_overlap_required_columns() -> None:
    assert not set(OPTIONAL_COLUMNS) & set(REQUIRED_COLUMNS)


@pytest.mark.parametrize(
    "columns",
    [CANONICAL_SORT_COLUMNS, PLAYER_TIME_SORT_COLUMNS, PLAYER_GROUP_COLUMNS],
)
def test_ordering_keys_reference_required_columns(columns: tuple[str, ...]) -> None:
    assert set(columns) <= set(REQUIRED_COLUMNS)


def test_rolling_group_key_isolates_seasons_and_players() -> None:
    """Season must stay in the group key, otherwise rolling windows leak across seasons."""

    assert PLAYER_GROUP_COLUMNS == ("season", "player_id")


def test_time_sort_orders_each_player_history_by_gameweek() -> None:
    assert PLAYER_TIME_SORT_COLUMNS == ("season", "player_id", "gameweek")
    assert PLAYER_TIME_SORT_COLUMNS[:2] == PLAYER_GROUP_COLUMNS


def test_projection_contract_matches_the_agreed_optimizer_columns() -> None:
    """Locks the cross-team contract; an upstream change must fail loudly here."""

    assert PROJECTION_REQUIRED_COLUMNS == (
        "player_id",
        "name",
        "team_id",
        "position",
        "price_tenths",
        "expected_points",
    )


def test_projection_columns_are_derivable_from_the_canonical_schema() -> None:
    derived = set(PROJECTION_REQUIRED_COLUMNS) - {"expected_points"}
    assert derived <= set(REQUIRED_COLUMNS)


def test_timing_classes_partition_the_canonical_schema_exactly() -> None:
    """Every canonical column must be classified exactly once, or leakage rules have a hole."""

    canonical = set(REQUIRED_COLUMNS) | set(OPTIONAL_COLUMNS)
    classified = [*PRE_MATCH_COLUMNS, *OUTCOME_COLUMNS, *AMBIGUOUS_TIMING_COLUMNS]

    assert len(classified) == len(set(classified)), "a column is classified twice"
    assert set(classified) == canonical


def test_required_outcome_and_pre_match_columns_are_as_agreed() -> None:
    assert set(REQUIRED_COLUMNS) & set(OUTCOME_COLUMNS) == {"minutes", "total_points"}
    assert "price_tenths" in PRE_MATCH_COLUMNS
    assert "total_points" in OUTCOME_COLUMNS


def test_key_and_ordering_columns_are_never_outcome_columns() -> None:
    for column in {*KEY_COLUMNS, *PLAYER_GROUP_COLUMNS, *CANONICAL_SORT_COLUMNS}:
        assert not is_outcome_column(column)


@pytest.mark.parametrize("column", ["minutes", "total_points", "goals_scored", "starts"])
def test_outcome_columns_are_reported_as_outcome(column: str) -> None:
    assert is_outcome_column(column) is True


@pytest.mark.parametrize("column", ["price_tenths", "position", "team_id", "is_home"])
def test_pre_match_columns_are_reported_as_known(column: str) -> None:
    assert is_outcome_column(column) is False


@pytest.mark.parametrize("column", AMBIGUOUS_TIMING_COLUMNS)
def test_unverified_timing_is_treated_conservatively(column: str) -> None:
    assert is_outcome_column(column) is True


def test_unclassified_column_raises_instead_of_guessing() -> None:
    with pytest.raises(InvalidValueError, match="no time-of-knowledge classification"):
        is_outcome_column("some_new_column")


def test_scalar_schema_constants() -> None:
    assert MIN_GAMEWEEK == 1
    assert PRICE_TENTHS_PER_UNIT == 10


@pytest.mark.parametrize(
    "error_type",
    [MissingColumnsError, DuplicateRecordsError, InvalidValueError],
)
def test_validation_errors_share_a_common_base(error_type: type[Exception]) -> None:
    assert issubclass(error_type, DataValidationError)
    assert issubclass(error_type, DataError)


def test_source_errors_are_not_validation_errors() -> None:
    assert issubclass(DataSourceError, DataError)
    assert not issubclass(DataSourceError, DataValidationError)


def test_data_errors_are_not_optimization_errors() -> None:
    """Data problems must stay distinguishable from optimizer input problems."""

    from squadopt import SquadOptimizationError

    assert not issubclass(DataError, SquadOptimizationError)
    assert not issubclass(SquadOptimizationError, DataError)
