"""Tests for canonical type coercion and value normalization."""

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal, assert_series_equal
from tests.fixtures.synthetic_gameweeks import make_canonical_gameweeks

from squadopt.data import (
    InvalidValueError,
    clean_canonical_dataset,
    normalize_positions,
    to_price_tenths,
)


def _series(*values: object) -> pd.Series:
    return pd.Series(list(values), dtype=object)


# --- price conversion -------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("5.5", 55), ("10.0", 100), ("12.5", 125), ("4.0", 40), ("0.0", 0)],
)
def test_documented_unit_prices_convert_exactly(raw: str, expected: int) -> None:
    result = to_price_tenths(_series(raw), unit="units")

    assert result.tolist() == [expected]


@pytest.mark.parametrize(("raw", "expected"), [("4.7", 47), ("5.7", 57), ("8.3", 83)])
def test_conversion_avoids_the_binary_float_trap(raw: str, expected: int) -> None:
    """`int(4.7 * 10)` is 46 in binary floating point; decimal arithmetic is exact."""

    assert to_price_tenths(_series(raw), unit="units").tolist() == [expected]
    assert int(float(raw) * 10) <= expected


@pytest.mark.parametrize(("raw", "expected"), [("5.55", 56), ("5.54", 55), ("5.65", 57)])
def test_sub_tenth_precision_rounds_half_up(raw: str, expected: int) -> None:
    assert to_price_tenths(_series(raw), unit="units").tolist() == [expected]


def test_price_result_is_non_nullable_int64() -> None:
    """A nullable or float price column is rejected by the optimizer element-wise."""

    result = to_price_tenths(_series("5.5", "6.0"), unit="units")

    assert str(result.dtype) == "int64"


def test_tenths_unit_passes_integers_through() -> None:
    assert to_price_tenths(_series("55", 60, "070"), unit="tenths").tolist() == [55, 60, 70]


def test_tenths_unit_refuses_a_fractional_price() -> None:
    """In tenths a fraction means the declared unit is wrong, so rounding would hide a bug."""

    with pytest.raises(InvalidValueError, match="whole numbers"):
        to_price_tenths(_series("5.5"), unit="tenths")


@pytest.mark.parametrize("raw", [None, float("nan"), pd.NA])
def test_missing_price_is_reported_by_column(raw: object) -> None:
    with pytest.raises(InvalidValueError, match="price_tenths"):
        to_price_tenths(_series(raw), unit="units")


@pytest.mark.parametrize("raw", ["abc", "", True, [5]])
def test_unusable_price_values_are_rejected(raw: object) -> None:
    with pytest.raises(InvalidValueError, match="price_tenths"):
        to_price_tenths(_series(raw), unit="units")


def test_infinite_price_is_rejected() -> None:
    with pytest.raises(InvalidValueError, match="finite"):
        to_price_tenths(_series(float("inf")), unit="units")


# --- positions --------------------------------------------------------------


def test_positions_are_normalized_to_the_controlled_vocabulary() -> None:
    result = normalize_positions(_series("gkp", " Defender ", "MID", "forward"))

    assert result.tolist() == ["GK", "DEF", "MID", "FWD"]


def test_unknown_position_is_rejected_rather_than_defaulted() -> None:
    with pytest.raises(InvalidValueError, match="Unsupported position value"):
        normalize_positions(_series("MID", "WING"))


# --- identifiers ------------------------------------------------------------


def test_numeric_identifiers_become_integers() -> None:
    frame = _canonical_text_frame(player_ids=["101", "102"])

    cleaned = clean_canonical_dataset(frame)

    assert str(cleaned["player_id"].dtype) == "int64"
    assert cleaned["player_id"].tolist() == [101, 102]


def test_a_single_leading_zero_keeps_the_whole_column_as_text() -> None:
    """`007` must not become `7` and collide with a genuinely different player."""

    frame = _canonical_text_frame(player_ids=["007", "102"])

    cleaned = clean_canonical_dataset(frame)

    assert str(cleaned["player_id"].dtype) == "string"
    assert cleaned["player_id"].tolist() == ["007", "102"]


def test_non_numeric_identifiers_stay_text() -> None:
    frame = _canonical_text_frame(player_ids=["GK_A", "MID_B"])

    cleaned = clean_canonical_dataset(frame)

    assert cleaned["player_id"].tolist() == ["GK_A", "MID_B"]


def test_mixed_numeric_and_text_identifiers_all_become_text() -> None:
    """One consistent identifier type per column is part of the contract."""

    frame = _canonical_text_frame(player_ids=["101", "GK_A"])

    cleaned = clean_canonical_dataset(frame)

    assert str(cleaned["player_id"].dtype) == "string"
    assert cleaned["player_id"].tolist() == ["101", "GK_A"]


def test_blank_identifier_is_rejected() -> None:
    frame = _canonical_text_frame(player_ids=["101", "   "])

    with pytest.raises(InvalidValueError, match="blank identifiers"):
        clean_canonical_dataset(frame)


# --- quantities and text ----------------------------------------------------


def test_leading_zeros_are_only_formatting_for_quantities() -> None:
    """The opposite of the identifier rule: `01` is just a padded number."""

    frame = _canonical_text_frame(gameweeks=["01", "2"])

    cleaned = clean_canonical_dataset(frame)

    assert cleaned["gameweek"].tolist() == [1, 2]


@pytest.mark.parametrize("raw", ["1.5", "abc", ""])
def test_unusable_quantities_are_rejected(raw: str) -> None:
    frame = _canonical_text_frame(gameweeks=[raw, "2"])

    with pytest.raises(InvalidValueError, match="gameweek"):
        clean_canonical_dataset(frame)


def test_text_columns_are_stripped() -> None:
    frame = _canonical_text_frame(names=["  Player A  ", "Player B"])

    cleaned = clean_canonical_dataset(frame)

    assert cleaned["name"].tolist() == ["Player A", "Player B"]


def test_blank_text_is_rejected() -> None:
    frame = _canonical_text_frame(names=["   ", "Player B"])

    with pytest.raises(InvalidValueError, match="blank text"):
        clean_canonical_dataset(frame)


def test_optional_float_and_boolean_columns_are_coerced() -> None:
    frame = _canonical_text_frame().assign(
        expected_goals=["0.35", "1.0"],
        is_home=["true", "0"],
    )

    cleaned = clean_canonical_dataset(frame)

    assert str(cleaned["expected_goals"].dtype) == "float64"
    assert cleaned["expected_goals"].tolist() == [0.35, 1.0]
    assert str(cleaned["is_home"].dtype) == "bool"
    assert cleaned["is_home"].tolist() == [True, False]


def test_realized_points_may_be_negative() -> None:
    frame = _canonical_text_frame(total_points=["-1", "6"])

    cleaned = clean_canonical_dataset(frame)

    assert cleaned["total_points"].tolist() == [-1, 6]


# --- frame-level behaviour --------------------------------------------------


def test_input_frame_is_not_mutated() -> None:
    frame = _canonical_text_frame()
    original = frame.copy(deep=True)

    cleaned = clean_canonical_dataset(frame)
    cleaned.loc[0, "name"] = "Changed"

    assert_frame_equal(frame, original)


def test_canonical_column_order_is_imposed() -> None:
    frame = _canonical_text_frame()
    shuffled = frame.loc[:, list(reversed(frame.columns))]

    cleaned = clean_canonical_dataset(shuffled)

    assert list(cleaned.columns) == list(frame.columns)


def test_row_order_is_preserved_by_cleaning() -> None:
    """Ordering is the pipeline's responsibility, so cleaning must not reorder."""

    frame = _canonical_text_frame(gameweeks=["5", "1"])

    cleaned = clean_canonical_dataset(frame)

    assert cleaned["gameweek"].tolist() == [5, 1]


def test_unrecognized_columns_are_carried_through_untouched() -> None:
    frame = _canonical_text_frame().assign(vendor_note=["a", "b"])

    cleaned = clean_canonical_dataset(frame)

    assert cleaned["vendor_note"].tolist() == ["a", "b"]
    assert list(cleaned.columns)[-1] == "vendor_note"


def test_duplicate_columns_are_rejected() -> None:
    frame = _canonical_text_frame()
    duplicated = pd.concat([frame, frame[["name"]]], axis=1)

    with pytest.raises(InvalidValueError, match="Duplicate columns"):
        clean_canonical_dataset(duplicated)


def test_non_dataframe_input_is_rejected() -> None:
    with pytest.raises(InvalidValueError, match="expects a pandas DataFrame"):
        clean_canonical_dataset([{"season": "2025-26"}])  # type: ignore[arg-type]


def test_cleaning_is_idempotent() -> None:
    once = clean_canonical_dataset(_canonical_text_frame())

    twice = clean_canonical_dataset(once)

    assert_frame_equal(once, twice)


def test_cleaning_an_already_canonical_frame_changes_nothing() -> None:
    canonical = make_canonical_gameweeks()

    cleaned = clean_canonical_dataset(canonical)

    assert_frame_equal(cleaned, canonical)


def test_result_index_is_inherited_not_reset() -> None:
    """Index handling belongs to the pipeline; cleaning stays alignment-safe."""

    frame = _canonical_text_frame()
    reindexed = frame.set_axis([10, 11], axis=0)

    cleaned = clean_canonical_dataset(reindexed)

    assert_series_equal(
        pd.Series(cleaned.index),
        pd.Series(reindexed.index),
        check_names=False,
    )


def _canonical_text_frame(
    *,
    player_ids: list[str] | None = None,
    gameweeks: list[str] | None = None,
    names: list[str] | None = None,
    total_points: list[str] | None = None,
) -> pd.DataFrame:
    """Two-row, all-text canonical frame, as it looks straight after adaptation."""

    return pd.DataFrame(
        {
            "season": ["2025-26", "2025-26"],
            "gameweek": gameweeks or ["1", "2"],
            "player_id": player_ids or ["101", "102"],
            "name": names or ["Player A", "Player B"],
            "team_id": ["1", "2"],
            "position": ["GK", "MID"],
            "price_tenths": ["45", "80"],
            "minutes": ["90", "72"],
            "total_points": total_points or ["6", "3"],
        },
        dtype=object,
    )
