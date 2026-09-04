"""Tests for the horizon decay measurement.

The measurement's whole value is that offset zero is comparable to the ordinary residual
population and every later offset is measured the same way. So most of the effort here goes
on the two things that would quietly break that comparability: the fixture scaling, and
which players survive into the compared gameweek.
"""

from typing import Any

import pandas as pd
import pytest
from tests.unit.test_backtest_production import TEAM_CODES, _fixtures, _panel

from squadopt.backtest.horizon_decay import (
    HORIZON_DECAY_CONTRACT_VERSION,
    measure_horizon_decay,
)
from squadopt.backtest.splits import BacktestConfigurationError

SEASONS = ("2025-26",)
WINDOW = 3


def _codes() -> pd.DataFrame:
    return TEAM_CODES


def _measure(**kwargs: Any) -> Any:
    return measure_horizon_decay(
        kwargs.pop("panel", _panel()),
        kwargs.pop("fixtures", _fixtures()),
        _codes(),
        seasons=kwargs.pop("seasons", SEASONS),
        form_window=kwargs.pop("form_window", WINDOW),
        **kwargs,
    )


# --- the shape of the result ------------------------------------------------


def test_the_result_names_its_contract_and_population() -> None:
    result = _measure(max_offset=2)

    assert result.contract_version == HORIZON_DECAY_CONTRACT_VERSION
    assert result.seasons == SEASONS
    assert result.max_offset == 2


def test_one_row_per_offset_is_reported() -> None:
    result = _measure(max_offset=2)

    assert [entry.offset for entry in result.offsets] == [0, 1, 2]


def test_every_offset_reports_the_population_behind_it() -> None:
    """An error without its row count cannot be compared against another offset's."""

    for entry in _measure(max_offset=2).offsets:
        assert entry.observations > 0
        assert entry.dropped_players >= 0


def test_offset_zero_drops_nobody() -> None:
    """A player projected at the decision point is by construction present there."""

    assert _measure(max_offset=2).offsets[0].dropped_players == 0


# --- the scaling, which must match what the horizon ships -------------------


def test_a_single_fixture_row_is_scaled_by_one() -> None:
    """This identity is what ties offset zero back to the ordinary residual history."""

    residuals = _measure(max_offset=0).residuals
    single = residuals.loc[residuals["fixture_count"] == 1]

    assert not single.empty
    assert bool((single["predicted_points"] >= 0).all())


def test_a_double_gameweek_row_is_scaled_by_two() -> None:
    residuals = _measure(max_offset=0, fixtures=_fixtures(doubles=(4,))).residuals
    doubled = residuals.loc[residuals["fixture_count"] == 2]

    assert not doubled.empty


def test_the_fixture_group_split_uses_the_compared_gameweek_s_calendar() -> None:
    """A double at t+2 is a property of t+2, not of the decision point."""

    result = _measure(max_offset=2, fixtures=_fixtures(doubles=(6,)))

    groups = {entry.offset: set(entry.by_fixture_group) for entry in result.offsets}
    assert all(group <= {"blank", "single", "double_plus"} for group in groups.values())


def test_the_residual_is_realized_minus_predicted() -> None:
    residuals = _measure(max_offset=1).residuals

    difference = (
        residuals["realized_points"] - residuals["predicted_points"] - residuals["residual"]
    )

    assert float(difference.abs().max()) == pytest.approx(0.0)


# --- who is compared --------------------------------------------------------


def test_a_player_absent_at_the_later_gameweek_is_dropped_and_counted() -> None:
    """A transfer is an absence from the data, not a bad projection."""

    panel = _panel()
    later = (panel["gameweek"] == 5) & (panel["player_id"] == 3)
    reduced = panel.loc[~later]

    result = measure_horizon_decay(
        reduced,
        _fixtures(),
        _codes(),
        seasons=SEASONS,
        form_window=WINDOW,
        max_offset=1,
    )

    assert sum(entry.dropped_players for entry in result.offsets) > 0


def test_each_player_appears_once_per_fold_and_offset() -> None:
    residuals = _measure(max_offset=2).residuals

    duplicated = residuals.duplicated(subset=["fold_id", "offset", "player_id"])

    assert not bool(duplicated.any())


def test_a_gameweek_past_the_end_of_the_season_is_not_a_drop() -> None:
    """There is no question to ask, which is different from failing to answer one."""

    result = _measure(max_offset=3)

    last = result.offsets[-1]
    assert last.observations > 0


# --- configuration ----------------------------------------------------------


def test_a_season_absent_from_the_panel_is_refused() -> None:
    with pytest.raises(BacktestConfigurationError, match="absent from the panel"):
        _measure(seasons=("1999-00",))


@pytest.mark.parametrize("max_offset", [-1, True])
def test_an_invalid_offset_is_refused(max_offset: object) -> None:
    with pytest.raises(BacktestConfigurationError, match="max_offset"):
        _measure(max_offset=max_offset)


def test_a_team_code_table_missing_columns_is_refused() -> None:
    with pytest.raises(BacktestConfigurationError, match="missing columns"):
        measure_horizon_decay(
            _panel(),
            _fixtures(),
            TEAM_CODES.drop(columns=["code"]),
            seasons=SEASONS,
            form_window=WINDOW,
        )
