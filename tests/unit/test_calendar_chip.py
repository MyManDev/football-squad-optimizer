"""Dated opportunities, expiry and missing evidence govern chip timing."""

from dataclasses import replace

import pytest
from tests.unit.test_transfer_planning import OPTIMAL_INITIAL, _horizon_table

from squadopt.experiments.calendar_chip import optimize_calendar_chip
from squadopt.planning import ChipAvailability, PlanningHorizon


@pytest.mark.parametrize("chip", ["3xc", "bboost"])
@pytest.mark.parametrize("window", [1, 3, 5])
def test_known_better_future_is_held_but_expiry_is_respected(
    known_optimum_players, small_config, chip, window
):
    table = _horizon_table(known_optimum_players, tuple(range(6, 13)))
    table.loc[table.gameweek.eq(12), "expected_points"] *= 2
    forecast = PlanningHorizon(table)
    config = replace(small_config, bench_weight=0)
    rights = ChipAvailability({chip: frozenset(range(6, 13))})
    held = optimize_calendar_chip(forecast, OPTIMAL_INITIAL, config, rights, window=window)
    assert held.chips_played == {}
    assert held.diagnostics["calendar_chip"]["tail_best_week"] == 12
    expiring = ChipAvailability({chip: frozenset(range(6, 6 + window))})
    spent = optimize_calendar_chip(forecast, OPTIMAL_INITIAL, config, expiring, window=window)
    assert list(spent.chips_played.values()) == [chip]
    assert spent.diagnostics["calendar_chip"]["holding_value"] == 0
    assert all(w.transfers_in.empty for w in spent.weeks)


@pytest.mark.parametrize("chip", ["3xc", "bboost"])
def test_missing_future_is_unknown_not_zero(known_optimum_players, small_config, chip):
    forecast = PlanningHorizon(_horizon_table(known_optimum_players, (6, 7, 8)))
    with pytest.raises(ValueError, match="every eligible"):
        optimize_calendar_chip(
            forecast,
            OPTIMAL_INITIAL,
            replace(small_config, bench_weight=0),
            ChipAvailability({chip: frozenset(range(6, 20))}),
            window=3,
        )


def test_known_blank_tail_does_not_force_saving(known_optimum_players, small_config):
    table = _horizon_table(known_optimum_players, (6, 7, 8))
    table.loc[table.gameweek.gt(6), "expected_points"] = 0
    result = optimize_calendar_chip(
        PlanningHorizon(table),
        OPTIMAL_INITIAL,
        replace(small_config, bench_weight=0),
        ChipAvailability({"3xc": frozenset({6, 7, 8})}),
        window=1,
    )
    assert result.chips_played == {6: "3xc"}
    assert result.diagnostics["calendar_chip"]["holding_value"] == 0


def test_multiple_chips_cannot_double_count_one_future_week(known_optimum_players, small_config):
    forecast = PlanningHorizon(_horizon_table(known_optimum_players))
    with pytest.raises(ValueError, match="exactly one"):
        optimize_calendar_chip(
            forecast,
            OPTIMAL_INITIAL,
            replace(small_config, bench_weight=0),
            ChipAvailability({"3xc": frozenset({1, 2}), "bboost": frozenset({1, 2})}),
            window=1,
        )
