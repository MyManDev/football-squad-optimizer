"""Tests for the fitted, leakage-safe opening-gameweek price prior."""

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

from squadopt.backtest import (
    BacktestConfigurationError,
    OpeningPriorBacktestConfig,
    fit_opening_price_coefficient,
    run_opening_prior_backtest,
)
from squadopt.features import CrossSeasonConfig


def _panel() -> pd.DataFrame:
    rows = [
        ("2020-21", 1, 1, "Known", "MID", 50, 90, 1),
        ("2020-21", 1, 2, "Past", "FWD", 100, 90, 4),
        ("2020-21", 2, 1, "Known", "MID", 50, 90, 9),
        ("2020-21", 2, 2, "Past", "FWD", 100, 90, 0),
        ("2021-22", 1, 1, "Known", "MID", 60, 90, 3),
        ("2021-22", 1, 3, "New", "DEF", 40, 0, 0),
    ]
    return pd.DataFrame(
        {
            "season": pd.Series([row[0] for row in rows], dtype="string"),
            "gameweek": pd.Series([row[1] for row in rows], dtype="int64"),
            "player_id": pd.Series([row[2] for row in rows], dtype="int64"),
            "name": pd.Series([row[3] for row in rows], dtype="string"),
            "team_id": pd.Series([1, 2, 1, 2, 1, 3], dtype="int64"),
            "position": pd.Series([row[4] for row in rows], dtype="string"),
            "price_tenths": pd.Series([row[5] for row in rows], dtype="int64"),
            "minutes": pd.Series([row[6] for row in rows], dtype="int64"),
            "total_points": pd.Series([row[7] for row in rows], dtype="int64"),
        }
    )


CONFIG = OpeningPriorBacktestConfig(
    training_seasons=("2020-21",),
    holdout_season="2021-22",
    cross_season_config=CrossSeasonConfig(min_minutes=0),
)


def test_coefficient_matches_the_hand_computed_origin_fit() -> None:
    # Prices are 5 and 10; outcomes are 1 and 4:
    # (5*1 + 10*4) / (5**2 + 10**2) = 45/125 = 0.36.
    coefficient = fit_opening_price_coefficient(_panel(), seasons=("2020-21",))

    assert coefficient == pytest.approx(0.36)


def test_non_opening_outcomes_do_not_enter_the_fit() -> None:
    panel = _panel()
    baseline = fit_opening_price_coefficient(panel, seasons=("2020-21",))
    panel.loc[(panel["season"] == "2020-21") & (panel["gameweek"] == 2), "total_points"] = 999

    assert fit_opening_price_coefficient(panel, seasons=("2020-21",)) == baseline


def test_holdout_outcomes_cannot_move_the_fitted_coefficient() -> None:
    baseline = run_opening_prior_backtest(_panel(), CONFIG)
    mutated = _panel()
    mutated.loc[mutated["season"] == "2021-22", "total_points"] = 999

    rebuilt = run_opening_prior_backtest(mutated, CONFIG)

    assert rebuilt.fitted_coefficient == baseline.fitted_coefficient


def test_result_compares_price_carry_over_and_the_hybrid() -> None:
    result = run_opening_prior_backtest(_panel(), CONFIG)

    assert result.training_observations == 2
    assert result.holdout_observations == 2
    assert result.carry_over_observations == 1
    assert result.carry_over_coverage == 0.5
    assert result.price_only.root_mean_squared_error >= 0
    assert result.carry_over_with_constant.root_mean_squared_error >= 0
    assert result.carry_over_with_price.root_mean_squared_error >= 0


def test_backtest_does_not_mutate_the_panel() -> None:
    panel = _panel()
    before = panel.copy(deep=True)

    run_opening_prior_backtest(panel, CONFIG)

    assert_frame_equal(panel, before)


def test_holdout_cannot_be_a_training_season() -> None:
    with pytest.raises(BacktestConfigurationError, match="must not appear"):
        OpeningPriorBacktestConfig(
            training_seasons=("2020-21",),
            holdout_season="2020-21",
        )
