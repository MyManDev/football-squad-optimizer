"""Tests for canonical dataset integrity validation."""

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal
from tests.fixtures.synthetic_gameweeks import GAMEWEEK_COUNT, make_canonical_gameweeks

from squadopt.data import (
    DuplicateRecordsError,
    InvalidValueError,
    MissingColumnsError,
    validate_canonical_dataset,
)


def test_accepts_the_synthetic_canonical_panel() -> None:
    canonical = make_canonical_gameweeks()

    validated = validate_canonical_dataset(canonical)

    assert_frame_equal(validated, canonical)


def test_returns_an_independent_copy() -> None:
    canonical = make_canonical_gameweeks()
    original = canonical.copy(deep=True)

    validated = validate_canonical_dataset(canonical)
    validated.loc[0, "name"] = "Changed"

    assert_frame_equal(canonical, original)


def test_missing_required_columns_are_all_reported() -> None:
    canonical = make_canonical_gameweeks().drop(columns=["price_tenths", "total_points"])

    with pytest.raises(MissingColumnsError) as error:
        validate_canonical_dataset(canonical)

    message = str(error.value)
    assert "price_tenths" in message
    assert "total_points" in message


def test_duplicate_key_error_identifies_the_exact_record() -> None:
    """A generic 'invalid data' message would force the reader into a debugger."""

    canonical = make_canonical_gameweeks()
    duplicated = pd.concat([canonical, canonical.iloc[[3]]], ignore_index=True)
    offender = canonical.iloc[3]

    with pytest.raises(DuplicateRecordsError) as error:
        validate_canonical_dataset(duplicated)

    message = str(error.value)
    assert "Duplicate player-gameweek records found" in message
    assert f"season={str(offender['season'])!r}" in message
    assert f"gameweek={int(offender['gameweek'])!r}" in message
    assert f"player_id={int(offender['player_id'])!r}" in message
    # Native scalars, not numpy reprs leaking into a user-facing message.
    assert "np.int64" not in message


def test_missing_values_in_required_columns_are_rejected() -> None:
    canonical = make_canonical_gameweeks()
    canonical.loc[0, "name"] = None

    with pytest.raises(InvalidValueError, match="missing values"):
        validate_canonical_dataset(canonical)


def test_negative_price_is_rejected() -> None:
    canonical = make_canonical_gameweeks()
    canonical.loc[0, "price_tenths"] = -5

    with pytest.raises(InvalidValueError, match="price_tenths"):
        validate_canonical_dataset(canonical)


def test_negative_minutes_are_rejected() -> None:
    canonical = make_canonical_gameweeks()
    canonical.loc[0, "minutes"] = -1

    with pytest.raises(InvalidValueError, match="minutes"):
        validate_canonical_dataset(canonical)


def test_negative_realized_points_are_accepted() -> None:
    """Cards and own goals produce genuinely negative scores; clamping would corrupt history."""

    canonical = make_canonical_gameweeks()
    canonical.loc[0, "total_points"] = -3

    validated = validate_canonical_dataset(canonical)

    assert validated.loc[0, "total_points"] == -3


def test_fractional_price_is_rejected() -> None:
    canonical = make_canonical_gameweeks().astype({"price_tenths": "float64"})
    canonical.loc[0, "price_tenths"] = 55.5

    with pytest.raises(InvalidValueError, match="price_tenths"):
        validate_canonical_dataset(canonical)


@pytest.mark.parametrize("gameweek", [0, -1])
def test_gameweek_below_the_minimum_is_rejected(gameweek: int) -> None:
    canonical = make_canonical_gameweeks()
    canonical.loc[0, "gameweek"] = gameweek

    with pytest.raises(InvalidValueError, match="gameweek"):
        validate_canonical_dataset(canonical)


def test_gameweek_upper_bound_is_only_enforced_when_supplied() -> None:
    canonical = make_canonical_gameweeks()

    validate_canonical_dataset(canonical, max_gameweek=GAMEWEEK_COUNT)

    with pytest.raises(InvalidValueError, match="at most"):
        validate_canonical_dataset(canonical, max_gameweek=GAMEWEEK_COUNT - 1)


def test_no_upper_bound_is_assumed_by_default() -> None:
    """A competition length is not a schema fact, so it is never hard-coded."""

    canonical = make_canonical_gameweeks()
    canonical.loc[0, "gameweek"] = 500

    validate_canonical_dataset(canonical)


def test_invalid_position_is_rejected() -> None:
    canonical = make_canonical_gameweeks()
    canonical.loc[0, "position"] = "WING"

    with pytest.raises(InvalidValueError, match="position"):
        validate_canonical_dataset(canonical)


def test_mixed_identifier_types_are_rejected() -> None:
    canonical = make_canonical_gameweeks().astype({"player_id": object})
    canonical.loc[0, "player_id"] = "GK_A"

    with pytest.raises(InvalidValueError, match="mixes identifier types"):
        validate_canonical_dataset(canonical)


def test_blank_display_name_is_rejected() -> None:
    canonical = make_canonical_gameweeks()
    canonical.loc[0, "name"] = "   "

    with pytest.raises(InvalidValueError, match="non-empty text"):
        validate_canonical_dataset(canonical)


def test_blank_season_is_rejected() -> None:
    canonical = make_canonical_gameweeks()
    canonical.loc[0, "season"] = ""

    with pytest.raises(InvalidValueError, match="non-empty text"):
        validate_canonical_dataset(canonical)


def test_duplicate_columns_are_rejected() -> None:
    canonical = make_canonical_gameweeks()
    duplicated = pd.concat([canonical, canonical[["name"]]], axis=1)

    with pytest.raises(InvalidValueError, match="Duplicate columns"):
        validate_canonical_dataset(duplicated)


def test_non_dataframe_input_is_rejected() -> None:
    with pytest.raises(InvalidValueError, match="expects a pandas DataFrame"):
        validate_canonical_dataset([{"season": "2025-26"}])  # type: ignore[arg-type]


def test_row_order_is_not_changed_by_validation() -> None:
    canonical = make_canonical_gameweeks().iloc[::-1].reset_index(drop=True)

    validated = validate_canonical_dataset(canonical)

    assert validated["gameweek"].tolist() == canonical["gameweek"].tolist()
