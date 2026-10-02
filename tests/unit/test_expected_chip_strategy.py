"""Chip opportunity and final selection use one explicit official-lineup basis."""

import pytest
from tests.unit.test_chip_tail import for_decision
from tests.unit.test_expected_lineup_planning import assert_fresh_score, full_problem

from squadopt.planning import (
    ChipAvailability,
    ChipUseWindow,
    PlanningHorizon,
    TransferPlanningConfig,
)
from squadopt.planning.chip_strategy import EXPECTED_CHIP_LIMIT, optimize_chip_strategy
from squadopt.planning.lineup_utility import expected_week_utility


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
        horizon,
        initial,
        config,
        transfer,
        rights,
        expected_lineups=True,
        tail_forecast=for_decision(horizon, initial, config, transfer, rights, 10, expected=True),
    )
    assert result.has_solution and len(result.weeks) == 3
    info = result.diagnostics["chip_strategy"]
    # Both complete candidates are rescored independently on the common official basis.
    expected_scores = [
        sum(expected_week_utility(w, transfer) for w in p.weeks)
        + float(p.diagnostics["terminal_chip_holding_value"])
        for p in captured
    ]
    review = info["expected_lineup_comparison"]
    assert review["news_recourse"] is False
    candidates = {item["proposal"]: item["utility"] for item in review["candidates"]}
    assert set(candidates) == {"no_chip_control", "chip_proposal"}
    assert list(candidates.values()) == pytest.approx(expected_scores)
    assert candidates[review["chosen"]] == max(candidates.values())
    assert info["actual_total"] <= info["configured_total"] + 1e-5
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


def test_no_rebuild_probes_or_population_tail_are_inferred(monkeypatch):
    import squadopt.planning.chip_strategy as module

    horizon, initial, config = full_problem(3)
    original = module.optimize_transfer_plan
    calls = []

    def record(*args, **kwargs):
        calls.append((args[0].gameweeks, args[1], args[2].solver_deterministic_time_limit))
        return original(*args, **kwargs)

    monkeypatch.setattr(module, "optimize_transfer_plan", record)
    rights = ChipAvailability({"wildcard": frozenset({4})})
    transfer = TransferPlanningConfig(acquisition_sell_on_fee=0.5)
    result = optimize_chip_strategy(
        horizon,
        initial,
        config,
        transfer,
        rights,
        expected_lineups=True,
        tail_forecast=for_decision(horizon, initial, config, transfer, rights, 10, expected=True),
    )
    assert result.has_solution and len(calls) == 2
    assert all(weeks == horizon.gameweeks and state == initial for weeks, state, _ in calls)
    assert sum(budget for _, _, budget in calls) == pytest.approx(
        result.diagnostics["chip_strategy"]["configured_total"]
    )
    assert result.diagnostics["chip_strategy"]["joint_tail"]["value"] == 10
