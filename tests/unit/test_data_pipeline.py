"""Tests for end-to-end canonical dataset construction."""

from pathlib import Path

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal
from tests.fixtures.synthetic_gameweeks import (
    GAMEWEEK_COUNT,
    RAW_COLUMN_MAP,
    RAW_POSITION_CODES,
    SAMPLE_ADAPTER,
    SEASON,
    make_canonical_gameweeks,
    make_raw_gameweeks,
)

from squadopt.data import (
    CANONICAL_SORT_COLUMNS,
    REQUIRED_COLUMNS,
    DuplicateRecordsError,
    InvalidValueError,
    MissingColumnsError,
    SourceAdapter,
    build_canonical_dataset,
    load_csv,
)

SAMPLE_FILE = Path(__file__).resolve().parents[2] / "data" / "sample" / "raw_player_gameweeks.csv"


def _build(raw: pd.DataFrame | None = None, **kwargs: object) -> pd.DataFrame:
    source = make_raw_gameweeks() if raw is None else raw
    return build_canonical_dataset(source, adapter=SAMPLE_ADAPTER, **kwargs)  # type: ignore[arg-type]


def test_raw_text_becomes_the_expected_canonical_dataset() -> None:
    """The whole path is pinned to an independently constructed expected panel."""

    assert_frame_equal(_build(), make_canonical_gameweeks())


def test_runs_from_the_committed_sample_file() -> None:
    result = build_canonical_dataset(load_csv(SAMPLE_FILE), adapter=SAMPLE_ADAPTER)

    assert_frame_equal(result, make_canonical_gameweeks())


def test_output_is_deterministic() -> None:
    assert_frame_equal(_build(), _build())


def test_output_does_not_depend_on_input_row_order() -> None:
    """Row order is an accident of the source; the result must not inherit it."""

    raw = make_raw_gameweeks()
    reversed_rows = raw.iloc[::-1].reset_index(drop=True)
    rotated = pd.concat([raw.iloc[100:], raw.iloc[:100]], ignore_index=True)

    baseline = _build(raw)

    assert_frame_equal(_build(reversed_rows), baseline)
    assert_frame_equal(_build(rotated), baseline)


def test_output_does_not_depend_on_input_index() -> None:
    raw = make_raw_gameweeks()
    reindexed = raw.set_axis(range(1000, 1000 + len(raw)), axis=0)

    assert_frame_equal(_build(reindexed), _build(raw))


def test_input_frame_is_not_mutated() -> None:
    raw = make_raw_gameweeks()
    original = raw.copy(deep=True)

    result = _build(raw)
    result.loc[0, "name"] = "Changed"

    assert_frame_equal(raw, original)


def test_output_is_sorted_canonically_with_a_reset_index() -> None:
    result = _build()
    keys = result.loc[:, list(CANONICAL_SORT_COLUMNS)]

    assert_frame_equal(keys, keys.sort_values(list(CANONICAL_SORT_COLUMNS)))
    assert result.index.tolist() == list(range(len(result)))


def test_output_carries_exactly_the_canonical_columns() -> None:
    assert list(_build().columns) == list(REQUIRED_COLUMNS)


def test_prices_arrive_as_integer_tenths() -> None:
    """The adapter declared whole units, so conversion must have happened."""

    result = _build()

    assert str(result["price_tenths"].dtype) == "int64"
    assert result["price_tenths"].min() >= 40


def test_positions_are_decoded_from_source_codes() -> None:
    result = _build()

    assert set(result["position"].unique()) == set(RAW_POSITION_CODES.values())


def test_duplicate_source_records_are_rejected_with_their_key() -> None:
    raw = make_raw_gameweeks()
    duplicated = pd.concat([raw, raw.iloc[[0]]], ignore_index=True)

    with pytest.raises(DuplicateRecordsError, match="Duplicate player-gameweek records"):
        _build(duplicated)


def test_gameweek_upper_bound_is_enforced_when_requested() -> None:
    with pytest.raises(InvalidValueError, match="at most"):
        _build(max_gameweek=GAMEWEEK_COUNT - 1)


def test_invalid_source_values_are_rejected_with_context() -> None:
    raw = make_raw_gameweeks()
    raw.loc[0, "minutes_played"] = "-5"

    with pytest.raises(InvalidValueError, match="minutes"):
        _build(raw)


# --- declared season --------------------------------------------------------


def _seasonless_adapter() -> SourceAdapter:
    return SourceAdapter(
        name="seasonless",
        column_map={
            raw: canonical for raw, canonical in RAW_COLUMN_MAP.items() if raw != "season_label"
        },
        position_codes=RAW_POSITION_CODES,
        price_unit="units",
    )


def test_a_single_season_extract_may_have_its_season_declared() -> None:
    """A per-season file legitimately omits the label, so the caller supplies it."""

    raw = make_raw_gameweeks().drop(columns=["season_label"])

    result = build_canonical_dataset(raw, adapter=_seasonless_adapter(), season=SEASON)

    assert_frame_equal(result, make_canonical_gameweeks())


def test_a_missing_season_without_a_declaration_is_reported() -> None:
    raw = make_raw_gameweeks().drop(columns=["season_label"])

    with pytest.raises(MissingColumnsError, match="season"):
        build_canonical_dataset(raw, adapter=_seasonless_adapter())


def test_declaring_a_season_that_contradicts_the_data_is_refused() -> None:
    """Relabelling would silently merge two seasons into one rolling-window group."""

    with pytest.raises(InvalidValueError, match="relabelling would merge separate seasons"):
        _build(season="2024-25")


def test_declaring_the_matching_season_is_accepted() -> None:
    assert_frame_equal(_build(season=SEASON), _build())


@pytest.mark.parametrize("season", ["", "   ", 2025])
def test_a_blank_or_non_text_season_declaration_is_refused(season: object) -> None:
    with pytest.raises(InvalidValueError, match="season must be a non-empty string"):
        _build(season=season)


def test_non_dataframe_input_is_rejected() -> None:
    with pytest.raises(InvalidValueError, match="expects a pandas DataFrame"):
        build_canonical_dataset([{"gw": "1"}], adapter=SAMPLE_ADAPTER)  # type: ignore[arg-type]
