"""Chip opportunity and final selection use one explicit official-lineup basis."""

from dataclasses import replace

import pytest
from tests.unit.test_expected_lineup_planning import assert_fresh_score, full_problem

from squadopt.planning import (
    ChipAvailability,
    ChipUseWindow,
    PlanningHorizon,
    TransferPlanningConfig,
)
from squadopt.planning.chip_strategy import EXPECTED_CHIP_LIMIT, optimize_chip_strategy
from squadopt.planning.lineup_utility import expected_week_utility, rescore_expected_week


@pytest.mark.parametrize("chip", ["bboost", "3xc"])
def test_expected_chip_marginal_keeps_autosubs_and_vice_on_the_same_basis(chip, monkeypatch):
    import squadopt.planning.chip_strategy as module

    horizon, initial, config = full_problem(3)
    # Exact held pool: a small legal FPL problem, with no extra squad search needed.
    horizon = PlanningHorizon(
        horizon.table.loc[horizon.table.player_id.isin(initial.squad_player_ids)]
    )
    table = horizon.table.copy()
    uncertain = table.player_id.eq(8)
    table.loc[uncertain, "appearance_probability"] = 0.5
    table.loc[uncertain, "expected_points"] *= 0.5
    horizon = PlanningHorizon(table)
    transfer = TransferPlanningConfig(transfer_hit_cost_points=8, max_transfers_per_gameweek=1)
    captured = []
    original = module.improve_plan_lineups

    def record(*args, **kwargs):
        result = original(*args, **kwargs)
        captured.append(result)
        return result

    monkeypatch.setattr(module, "improve_plan_lineups", record)
    rights = ChipAvailability(
        {chip: frozenset(range(1, 20))},
        use_windows={chip: (ChipUseWindow(frozenset(range(1, 20))),)},
    )
    result = optimize_chip_strategy(
        horizon, initial, config, transfer, rights, expected_lineups=True
    )
    assert result.has_solution and len(result.weeks) == 3
    control = captured[0]
    info = result.diagnostics["chip_strategy"]
    assert info["reference_solver_status"] == "OPTIMAL"
    expected_samples = []
    for week in control.weeks:
        boosted = rescore_expected_week(replace(week, chip=chip))
        expected_samples.append(
            expected_week_utility(boosted, transfer) - expected_week_utility(week, transfer)
        )
    assert info["samples"][chip] == pytest.approx(expected_samples)
    review = info["expected_lineup_comparison"]
    assert review["news_recourse"] is False
    candidates = {item["proposal"]: item["utility"] for item in review["candidates"]}
    assert set(candidates) == {"no_chip_control", "chip_proposal"}
    assert candidates[review["chosen"]] == max(candidates.values())
    assert EXPECTED_CHIP_LIMIT in info["limits"]
    assert result.diagnostics["absolute_optimality_gap"] is None
    for week in result.weeks:
        assert_fresh_score(week)
        assert week.bank_after_tenths == initial.bank_tenths
        assert week.paid_transfer_count == 0


def test_forced_dated_chip_is_not_overridden_by_no_chip_control():
    horizon, initial, config = full_problem(3)
    horizon = PlanningHorizon(
        horizon.table.loc[horizon.table.player_id.isin(initial.squad_player_ids)]
    )
    result = optimize_chip_strategy(
        horizon,
        initial,
        config,
        TransferPlanningConfig(),
        ChipAvailability({"3xc": frozenset({2})}, {2: "3xc"}),
        expected_lineups=True,
    )
    assert result.chips_played == {2: "3xc"}
    review = result.diagnostics["chip_strategy"]["expected_lineup_comparison"]
    assert [p["proposal"] for p in review["candidates"]] == ["chip_proposal"]
    assert_fresh_score(result.weeks[1])


def test_rebuild_opportunity_keeps_the_rebought_players_actual_sale_basis(monkeypatch):
    import squadopt.planning.chip_strategy as module

    horizon, initial, config = full_problem(3)
    table = horizon.table.copy()
    # Player 14's original purchase was cheaper. Selling and buying him back
    # creates a new lot at 50; a later rebuild can recover all 50, not the old 40.
    table.loc[table.player_id.eq(14), "sell_price_tenths"] = 40
    horizon = PlanningHorizon(table)
    initial = replace(initial, bank_tenths=10, free_transfers=2)
    original_ids = initial.squad_player_ids
    away_ids = tuple(13 if player == 14 else player for player in original_ids)
    original = module.optimize_transfer_plan
    control = None
    probes = {}

    def record(horizon, state, optimization, transfer, **kwargs):
        nonlocal control
        if control is None:
            result = original(
                horizon,
                state,
                optimization,
                transfer,
                **kwargs,
                fixed_week_squads={1: away_ids, 2: original_ids, 3: original_ids},
            )
            control = result
            return result
        result = original(horizon, state, optimization, transfer, **kwargs)
        if len(horizon.gameweeks) == 1:
            probes[horizon.gameweeks[0]] = (horizon, state, result)
        return result

    monkeypatch.setattr(module, "optimize_transfer_plan", record)
    result = optimize_chip_strategy(
        horizon,
        initial,
        config,
        TransferPlanningConfig(max_transfers_per_gameweek=1, acquisition_sell_on_fee=0.5),
        ChipAvailability({"wildcard": frozenset({4})}),
        expected_lineups=True,
    )
    assert result.has_solution and control is not None
    assert control.weeks[0].transfers_out.player_id.tolist() == [14]
    assert control.weeks[1].transfers_in.player_id.tolist() == [14]
    for gameweek in (2, 3):
        held = control.weeks[gameweek - 1]
        probe_horizon, probe_state, probe = probes[gameweek]
        assert probe_horizon.table.set_index("player_id").at[14, "sell_price_tenths"] == 50
        assert probe_state.bank_tenths == held.bank_after_tenths
        assert probe_state.squad_player_ids == tuple(held.selected_squad.player_id)
        assert probe.has_solution and probe.total_transfer_hit_points == 0
        assert probe_state.bank_tenths + int(held.selected_squad.sell_price_tenths.sum()) == 750
