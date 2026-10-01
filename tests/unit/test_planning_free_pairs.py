"""A bounded free financing pair preserves the actual squad resource equations."""

from dataclasses import replace

import pytest
from tests.unit.test_planner_incumbent import problem

from squadopt.contracts.preferences import DecisionPreferences
from squadopt.planning import (
    ChipAvailability,
    PlanningHorizon,
    TransferPlanningConfig,
    TransferPlanningConfigurationError,
    optimize_transfer_plan,
)
from squadopt.planning.guarded import optimize_guarded_window


def financing_problem(players, config, window=3):
    horizon, initial, optimization = problem(players, config, window)
    table = horizon.table.copy()
    for player, buy, sell, points in (
        ("DEF_A", 70, 60, 4),
        ("DEF_B", 40, 40, 1),
        ("MID_A", 70, 70, 20),
        ("MID_B", 50, 50, 1),
        ("FWD_A", 50, 50, 8),
        ("FWD_B", 50, 50, 0),
    ):
        mask = table.player_id.eq(player)
        table.loc[mask, ["buy_price_tenths", "sell_price_tenths", "expected_points"]] = (
            buy,
            sell,
            points,
        )
    initial = replace(
        initial,
        squad_player_ids=("GK_A", "DEF_A", "MID_B", "FWD_A"),
        free_transfers=2,
    )
    return PlanningHorizon(table), initial, replace(optimization, solver_time_limit_seconds=60)


@pytest.mark.parametrize("window", [3, 5])
def test_two_free_moves_can_finance_the_upgrade_today(known_optimum_players, small_config, window):
    args = financing_problem(known_optimum_players, small_config, window)
    old = TransferPlanningConfig(max_transfers_per_gameweek=1, acquisition_sell_on_fee=0.5)
    pair = replace(old, allow_two_free_transfers=True)
    baseline = optimize_transfer_plan(*args, old, preferences=DecisionPreferences(no_hits=True))
    result = optimize_guarded_window(*args, pair, preferences=DecisionPreferences(no_hits=True))
    assert result.has_solution and len(result.weeks) == window
    first = result.weeks[0]
    assert set(first.transfers_out.player_id) == {"DEF_A", "MID_B"}
    assert set(first.transfers_in.player_id) == {"DEF_B", "MID_A"}
    assert first.bank_after_tenths == 0
    assert first.free_transfers_before == 2
    assert first.free_transfers_for_next_gameweek == 1
    assert result.total_transfer_hit_points == 0
    assert result.objective_value > baseline.objective_value
    assert result.diagnostics["incumbent_protection"]["version"] == "certified_fallback_v1"
    assert result.diagnostics["allow_two_free_transfers"] is True


@pytest.mark.parametrize("free_transfers", [0, 1, 2, 5])
def test_second_move_requires_two_actual_free_transfers(
    known_optimum_players, small_config, free_transfers
):
    horizon, initial, config = financing_problem(known_optimum_players, small_config)
    result = optimize_transfer_plan(
        horizon,
        replace(initial, free_transfers=free_transfers),
        config,
        TransferPlanningConfig(max_transfers_per_gameweek=1, allow_two_free_transfers=True),
        fixed_week_squads={1: ("GK_A", "DEF_B", "MID_A", "FWD_A")},
    )
    assert result.has_solution is (free_transfers >= 2)
    if result.has_solution:
        assert result.weeks[0].paid_transfer_count == 0
        assert result.weeks[0].free_transfers_for_next_gameweek == free_transfers - 1


def test_pair_sale_uses_new_purchase_basis_and_bank(known_optimum_players, small_config):
    horizon, initial, config = financing_problem(known_optimum_players, small_config)
    table = horizon.table.copy()
    later = table.gameweek.eq(3)
    table.loc[later & table.player_id.eq("MID_A"), ["buy_price_tenths", "sell_price_tenths"]] = 80
    table.loc[later & table.player_id.eq("DEF_A"), ["buy_price_tenths", "sell_price_tenths"]] = 60
    pair = ("GK_A", "DEF_B", "MID_A", "FWD_A")
    result = optimize_transfer_plan(
        PlanningHorizon(table),
        replace(initial, bank_tenths=20),
        config,
        TransferPlanningConfig(
            max_transfers_per_gameweek=1,
            allow_two_free_transfers=True,
            acquisition_sell_on_fee=0.5,
        ),
        fixed_week_squads={1: pair, 2: pair, 3: initial.squad_player_ids},
    )
    assert result.has_solution and result.total_transfer_hit_points == 0
    assert [w.free_transfers_for_next_gameweek for w in result.weeks] == [1, 2, 1]
    assert [w.bank_after_tenths for w in result.weeks] == [20, 20, 25]
    # MID_A was bought for 70: the 80 market price releases only 75 after the gain fee.
    assert (
        result.weeks[2].transfers_out.set_index("player_id").loc["MID_A", "sell_price_tenths"] == 75
    )


@pytest.mark.parametrize("chip", ["wildcard", "freehit"])
def test_dated_rebuild_right_still_lifts_pair_cap(known_optimum_players, small_config, chip):
    horizon, initial, config = financing_problem(known_optimum_players, small_config)
    result = optimize_transfer_plan(
        horizon,
        replace(initial, free_transfers=0, bank_tenths=100),
        config,
        TransferPlanningConfig(max_transfers_per_gameweek=1, allow_two_free_transfers=True),
        chips=ChipAvailability({chip: frozenset({1})}, {1: chip}),
        fixed_week_squads={1: ("GK_B", "DEF_B", "MID_A", "FWD_A")},
    )
    assert result.has_solution
    assert result.weeks[0].transfer_count == 3
    assert result.weeks[0].paid_transfer_count == 0
    assert result.weeks[0].free_transfers_for_next_gameweek == 0
    assert result.chips_played == {1: chip}


def test_pair_flag_is_explicit_and_enters_identity():
    original = TransferPlanningConfig(max_transfers_per_gameweek=1)
    assert (
        original.configuration_fingerprint
        == replace(original, allow_two_free_transfers=False).configuration_fingerprint
    )
    assert (
        original.configuration_fingerprint
        != replace(original, allow_two_free_transfers=True).configuration_fingerprint
    )
    with pytest.raises(TransferPlanningConfigurationError, match="must be a boolean"):
        replace(original, allow_two_free_transfers=1)
