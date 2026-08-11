"""Tests for the committed synthetic sample dataset and its fixtures."""

from collections import Counter
from pathlib import Path

import pytest
from pandas.testing import assert_frame_equal
from tests.fixtures.synthetic_gameweeks import (
    GAMEWEEK_COUNT,
    SAMPLE_ADAPTER,
    TEAM_COUNT,
    make_canonical_gameweeks,
    make_raw_gameweeks,
)

from squadopt.data import REQUIRED_COLUMNS, apply_adapter, load_csv

SAMPLE_FILE = Path(__file__).resolve().parents[2] / "data" / "sample" / "raw_player_gameweeks.csv"

# Optimizer defaults the pool must be able to satisfy.
DEFAULT_SQUAD_QUOTAS = {"GK": 2, "DEF": 5, "MID": 5, "FWD": 3}
DEFAULT_MAX_PER_TEAM = 3
DEFAULT_SQUAD_SIZE = 15


def test_sample_file_is_committed() -> None:
    assert SAMPLE_FILE.is_file()


def test_committed_sample_matches_its_generator() -> None:
    """Guards against the committed file drifting away from the code that makes it."""

    assert_frame_equal(load_csv(SAMPLE_FILE), make_raw_gameweeks())


def test_generator_is_deterministic_across_calls() -> None:
    assert_frame_equal(make_raw_gameweeks(), make_raw_gameweeks())
    assert_frame_equal(make_canonical_gameweeks(), make_canonical_gameweeks())


def test_sample_adapts_to_the_canonical_schema() -> None:
    adapted = apply_adapter(load_csv(SAMPLE_FILE), SAMPLE_ADAPTER)

    assert list(adapted.columns) == list(REQUIRED_COLUMNS)
    assert len(adapted) == len(make_canonical_gameweeks())


def test_panel_is_complete_and_balanced() -> None:
    canonical = make_canonical_gameweeks()
    players = canonical["player_id"].nunique()

    assert canonical["gameweek"].nunique() == GAMEWEEK_COUNT
    assert canonical["team_id"].nunique() == TEAM_COUNT
    assert len(canonical) == players * GAMEWEEK_COUNT
    assert not canonical.duplicated(subset=["season", "gameweek", "player_id"]).any()


def test_pool_can_satisfy_the_default_optimizer_configuration() -> None:
    """A pool that cannot form a legal squad makes an end-to-end test meaningless."""

    one_gameweek = make_canonical_gameweeks().query("gameweek == 1")
    by_position = Counter(one_gameweek["position"])

    for position, required in DEFAULT_SQUAD_QUOTAS.items():
        assert by_position[position] >= required

    assert len(one_gameweek) >= DEFAULT_SQUAD_SIZE
    # Enough clubs that the three-per-team limit still permits a full squad.
    assert TEAM_COUNT * DEFAULT_MAX_PER_TEAM >= DEFAULT_SQUAD_SIZE


def test_raw_sample_is_deliberately_not_in_canonical_order() -> None:
    """Otherwise the ordering guarantees downstream would be untested by accident."""

    raw = make_raw_gameweeks()
    keys = list(zip(raw["gw"], raw["player_ref"], strict=True))

    assert keys != sorted(keys)


def test_raw_sample_is_text_with_decimal_prices_and_coded_positions() -> None:
    raw = make_raw_gameweeks()

    assert {str(dtype) for dtype in raw.dtypes} == {"str"}
    assert set(raw["pos_code"].unique()) == {"1", "2", "3", "4"}
    assert all("." in price for price in raw["price"])


@pytest.mark.parametrize("column", ["minutes", "total_points", "price_tenths"])
def test_values_vary_within_a_player_across_gameweeks(column: str) -> None:
    """Constant series make shifted and unshifted rolling features indistinguishable."""

    canonical = make_canonical_gameweeks()
    variation = canonical.groupby("player_id")[column].nunique()

    assert (variation > 1).all(), f"{column} is constant for at least one player"


def test_players_are_out_of_phase_with_each_other() -> None:
    """Identical series across players would hide grouping mistakes."""

    canonical = make_canonical_gameweeks().sort_values(["player_id", "gameweek"])
    series = canonical.groupby("player_id")["total_points"].apply(tuple)

    assert series.nunique() > 1


def test_sample_contains_blank_gameweeks_and_negative_scores() -> None:
    canonical = make_canonical_gameweeks()

    assert (canonical["minutes"] == 0).any(), "no benched gameweeks"
    assert (canonical["total_points"] < 0).any(), "no negative scores to prove no clamping"


def test_realized_points_are_zero_whenever_no_minutes_were_played() -> None:
    canonical = make_canonical_gameweeks()
    benched = canonical.loc[canonical["minutes"] == 0, "total_points"]

    assert (benched == 0).all()


def test_prices_are_integer_tenths() -> None:
    canonical = make_canonical_gameweeks()

    assert str(canonical["price_tenths"].dtype) == "int64"
    assert (canonical["price_tenths"] > 0).all()
