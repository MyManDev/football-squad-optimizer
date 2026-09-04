"""Tests for raw-to-canonical source adapters."""

import dataclasses

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal
from tests.fixtures.synthetic_gameweeks import (
    RAW_UNMAPPED_COLUMN,
    SAMPLE_ADAPTER,
    make_canonical_gameweeks,
    make_raw_gameweeks,
)

from squadopt.data import (
    IDENTITY_ADAPTER,
    REQUIRED_COLUMNS,
    InvalidValueError,
    MissingColumnsError,
    SourceAdapter,
    apply_adapter,
)

MINIMAL_COLUMN_MAP = {raw: raw for raw in REQUIRED_COLUMNS}


def _minimal_adapter(**overrides: object) -> SourceAdapter:
    kwargs: dict[str, object] = {"name": "minimal", "column_map": dict(MINIMAL_COLUMN_MAP)}
    kwargs.update(overrides)
    return SourceAdapter(**kwargs)  # type: ignore[arg-type]


# --- construction -----------------------------------------------------------


def test_rejects_mapping_to_an_unknown_canonical_column() -> None:
    with pytest.raises(InvalidValueError, match="unknown canonical column"):
        _minimal_adapter(column_map={**MINIMAL_COLUMN_MAP, "extra": "not_a_real_column"})


def test_rejects_two_raw_columns_mapped_to_one_canonical_column() -> None:
    with pytest.raises(InvalidValueError, match="maps both"):
        _minimal_adapter(column_map={**MINIMAL_COLUMN_MAP, "alt_minutes": "minutes"})


def test_rejects_an_adapter_that_cannot_produce_the_required_schema() -> None:
    partial = {raw: raw for raw in REQUIRED_COLUMNS if raw != "total_points"}

    with pytest.raises(MissingColumnsError, match="total_points"):
        _minimal_adapter(column_map=partial)


def test_rejects_an_empty_column_map() -> None:
    with pytest.raises(InvalidValueError, match="non-empty raw-to-canonical column_map"):
        _minimal_adapter(column_map={})


@pytest.mark.parametrize("name", ["", "   "])
def test_rejects_a_blank_adapter_name(name: str) -> None:
    with pytest.raises(InvalidValueError, match="non-empty string"):
        _minimal_adapter(name=name)


def test_rejects_an_unsupported_price_unit() -> None:
    with pytest.raises(InvalidValueError, match="unsupported price_unit"):
        _minimal_adapter(price_unit="pounds")


def test_rejects_a_position_code_that_maps_to_no_real_position() -> None:
    with pytest.raises(InvalidValueError, match="Unsupported position value"):
        _minimal_adapter(position_codes={"9": "WING"})


def test_rejects_duplicate_position_codes_differing_only_in_case() -> None:
    with pytest.raises(InvalidValueError, match="more than once"):
        _minimal_adapter(position_codes={"gk": "GK", "GK": "GK"})


def test_position_codes_are_normalized_at_construction() -> None:
    adapter = _minimal_adapter(position_codes={" 1 ": "goalkeeper"})

    assert adapter.position_codes == {"1": "GK"}


def test_adapter_is_frozen_and_its_mappings_are_read_only() -> None:
    adapter = _minimal_adapter()

    with pytest.raises(dataclasses.FrozenInstanceError):
        adapter.name = "changed"  # type: ignore[misc]
    with pytest.raises(TypeError):
        adapter.column_map["minutes"] = "total_points"  # type: ignore[index]


def test_declared_column_map_is_copied_so_later_edits_cannot_leak_in() -> None:
    source = dict(MINIMAL_COLUMN_MAP)
    adapter = _minimal_adapter(column_map=source)

    source["minutes"] = "total_points"

    assert adapter.column_map["minutes"] == "minutes"


# --- application ------------------------------------------------------------


def test_renames_to_canonical_names_and_drops_unmapped_columns() -> None:
    adapted = apply_adapter(make_raw_gameweeks(), SAMPLE_ADAPTER)

    assert set(REQUIRED_COLUMNS) <= set(adapted.columns)
    assert RAW_UNMAPPED_COLUMN not in adapted.columns
    assert not {"gw", "player_ref", "pos_code", "price"} & set(adapted.columns)


def test_input_frame_is_not_mutated() -> None:
    raw = make_raw_gameweeks()
    original = raw.copy(deep=True)

    adapted = apply_adapter(raw, SAMPLE_ADAPTER)
    adapted.loc[0, "name"] = "Changed"

    assert_frame_equal(raw, original)


def test_declared_position_codes_are_translated() -> None:
    adapted = apply_adapter(make_raw_gameweeks(), SAMPLE_ADAPTER)

    assert set(adapted["position"].unique()) == {"GK", "DEF", "MID", "FWD"}


def test_undeclared_position_values_pass_through_for_later_normalization() -> None:
    """The adapter only translates encodings it declares; labels are cleaning's job."""

    raw = pd.DataFrame(
        [["2025-26", "1", "1", "A", "1", "Goalkeeper", "5.5", "90", "6"]],
        columns=list(REQUIRED_COLUMNS),
    )
    adapter = _minimal_adapter(position_codes={"1": "GK"})

    adapted = apply_adapter(raw, adapter)

    assert adapted["position"].tolist() == ["Goalkeeper"]


def test_canonical_column_order_is_imposed_regardless_of_source_order() -> None:
    raw = make_raw_gameweeks()
    reversed_source = raw.loc[:, list(reversed(raw.columns))]

    adapted = apply_adapter(reversed_source, SAMPLE_ADAPTER)

    assert list(adapted.columns) == list(REQUIRED_COLUMNS)


def test_row_order_is_left_untouched_by_the_adapter() -> None:
    raw = make_raw_gameweeks()

    adapted = apply_adapter(raw, SAMPLE_ADAPTER)

    assert adapted["gameweek"].tolist() == raw["gw"].tolist()


def test_missing_required_raw_column_is_reported_with_context() -> None:
    raw = make_raw_gameweeks().drop(columns=["points"])

    with pytest.raises(MissingColumnsError) as error:
        apply_adapter(raw, SAMPLE_ADAPTER)

    message = str(error.value)
    assert "points" in message
    assert "synthetic-sample" in message


def test_absent_optional_column_is_skipped_rather_than_invented() -> None:
    canonical = make_canonical_gameweeks()

    adapted = apply_adapter(canonical, IDENTITY_ADAPTER)

    assert list(adapted.columns) == list(REQUIRED_COLUMNS)
    assert "expected_goals" not in adapted.columns


def test_optional_column_is_carried_through_when_present() -> None:
    canonical = make_canonical_gameweeks().assign(is_home=True)

    adapted = apply_adapter(canonical, IDENTITY_ADAPTER)

    assert "is_home" in adapted.columns


def test_duplicate_source_columns_are_rejected() -> None:
    raw = make_raw_gameweeks()
    duplicated = pd.concat([raw, raw[["gw"]]], axis=1)

    with pytest.raises(InvalidValueError, match="duplicate columns"):
        apply_adapter(duplicated, SAMPLE_ADAPTER)


def test_non_dataframe_input_is_rejected() -> None:
    with pytest.raises(InvalidValueError, match="expects a pandas DataFrame"):
        apply_adapter([{"gw": "1"}], SAMPLE_ADAPTER)  # type: ignore[arg-type]


def test_adapting_is_idempotent_through_the_identity_adapter() -> None:
    once = apply_adapter(make_raw_gameweeks(), SAMPLE_ADAPTER)

    twice = apply_adapter(once, IDENTITY_ADAPTER)

    assert_frame_equal(once, twice)
