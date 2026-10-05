"""Chip continuation arithmetic and forecast-only allocation checks."""

from dataclasses import replace

import pytest
from tests.unit.test_chip_tail import for_decision
from tests.unit.test_transfer_planning import OPTIMAL_INITIAL, _horizon_table

from squadopt.optimization import SolverStatus
from squadopt.planning import (
    ChipAvailability,
    ChipUseWindow,
    PlanningHorizon,
    TransferPlanningConfig,
)
from squadopt.planning.chip_strategy import optimize_chip_strategy


@pytest.mark.parametrize("chip", ["3xc", "bboost"])
@pytest.mark.parametrize("future_value,held", [(1000, True), (0, False)])
def test_h3_uses_explicit_future_value_not_the_number_of_weeks_left(
    known_optimum_players, small_config, chip, future_value, held
):
    # GW7 is marginally best now. Eleven future dates alone say nothing about value.
    table = _horizon_table(known_optimum_players, (6, 7, 8))
    table.loc[table.gameweek.eq(7), "expected_points"] *= 1.02
    horizon = PlanningHorizon(table)
    chips = ChipAvailability({chip: frozenset(range(6, 20))})
    transfer = TransferPlanningConfig()
    result = optimize_chip_strategy(
        horizon,
        OPTIMAL_INITIAL,
        small_config,
        transfer,
        chips,
        tail_forecast=for_decision(
            horizon, OPTIMAL_INITIAL, small_config, transfer, chips, future_value
        ),
    )
    assert result.solver_status is SolverStatus.OPTIMAL
    assert result.chips_played == ({} if held else {7: chip})
    assert result.diagnostics["chip_strategy"]["joint_tail"]["value"] == (
        future_value if held else 0
    )


def test_missing_future_tail_refuses_before_any_solver(
    known_optimum_players, small_config, monkeypatch
):
    import squadopt.planning.chip_strategy as module

    monkeypatch.setattr(
        module, "optimize_transfer_plan", lambda *a, **k: pytest.fail("unexpected solve")
    )
    with pytest.raises(ValueError, match="validated dated"):
        optimize_chip_strategy(
            PlanningHorizon(_horizon_table(known_optimum_players)),
            OPTIMAL_INITIAL,
            small_config,
            TransferPlanningConfig(),
            ChipAvailability({"3xc": frozenset(range(1, 20))}),
        )


def test_chip_strategy_exercises_expiring_right_and_keeps_renewed_right(
    known_optimum_players, small_config
):
    horizon = PlanningHorizon(_horizon_table(known_optimum_players, (19, 20)))
    chips = ChipAvailability(
        {"3xc": frozenset(range(19, 39))},
        use_windows={
            "3xc": (ChipUseWindow(frozenset({19})), ChipUseWindow(frozenset(range(20, 39))))
        },
    )
    transfer = TransferPlanningConfig()
    result = optimize_chip_strategy(
        horizon,
        OPTIMAL_INITIAL,
        small_config,
        transfer,
        chips,
        tail_forecast=for_decision(horizon, OPTIMAL_INITIAL, small_config, transfer, chips, 1000),
    )
    assert result.chips_played == {19: "3xc"}
    assert result.diagnostics["terminal_chip_holding_value"] == 1000


def test_old_calibration_is_not_silently_reused(known_optimum_players, small_config):
    with pytest.raises(ValueError, match="explicit dated"):
        optimize_chip_strategy(
            PlanningHorizon(_horizon_table(known_optimum_players)),
            OPTIMAL_INITIAL,
            small_config,
            replace(TransferPlanningConfig(), chip_holding_value_points={"3xc": 18}),
            ChipAvailability(),
        )


def test_current_chip_can_use_a_right_that_would_lose_the_same_future_date(
    known_optimum_players, small_config
):
    horizon = PlanningHorizon(_horizon_table(known_optimum_players, (1,)))
    chips = ChipAvailability({"3xc": frozenset({1, 2}), "bboost": frozenset({1, 2})})
    transfer = TransferPlanningConfig()
    result = optimize_chip_strategy(
        horizon,
        OPTIMAL_INITIAL,
        small_config,
        transfer,
        chips,
        tail_forecast=for_decision(horizon, OPTIMAL_INITIAL, small_config, transfer, chips, 1000),
    )
    # Two scalar reserves of 1000 would incorrectly prevent either chip now.
    assert len(result.chips_played) == 1
    assert result.diagnostics["terminal_chip_holding_value"] == 1000


def test_optimizer_tail_preserves_free_hit_boundary(known_optimum_players, small_config):
    horizon = PlanningHorizon(_horizon_table(known_optimum_players, (1,)))
    chips = ChipAvailability(
        {"freehit": frozenset({1, 2, 3})},
        {1: "freehit"},
        use_windows={"freehit": tuple(ChipUseWindow(frozenset({gw})) for gw in (1, 2, 3))},
    )
    transfer = TransferPlanningConfig()
    result = optimize_chip_strategy(
        horizon,
        OPTIMAL_INITIAL,
        small_config,
        transfer,
        chips,
        tail_forecast=for_decision(
            horizon,
            OPTIMAL_INITIAL,
            small_config,
            transfer,
            chips,
            {("freehit", 2): 1000, ("freehit", 3): 7},
        ),
    )
    assert result.chips_played == {1: "freehit"}
    assert result.diagnostics["terminal_chip_holding_value"] == 7


@pytest.mark.parametrize("reserve", [0, 6, 30])
def test_joint_allocation_matches_exhaustive_legal_schedules(
    known_optimum_players, small_config, reserve
):
    from itertools import product

    from squadopt.planning import optimize_transfer_plan

    horizon = PlanningHorizon(_horizon_table(known_optimum_players, (18, 19, 20)))
    rights = {
        "3xc": (ChipUseWindow(frozenset({18, 19}), reserve), ChipUseWindow(frozenset({20}), 4)),
        "bboost": (ChipUseWindow(frozenset({18, 19, 20}), 2),),
    }
    available = {n: frozenset().union(*(p.gameweeks for p in ps)) for n, ps in rights.items()}
    chips = ChipAvailability(available=available, use_windows=rights)
    joint = optimize_transfer_plan(
        horizon, OPTIMAL_INITIAL, small_config, TransferPlanningConfig(), chips=chips
    )
    best = float("-inf")
    for schedule in product((None, "3xc", "bboost"), repeat=3):
        forced = {gw: n for gw, n in zip((18, 19, 20), schedule, strict=True) if n}
        if any(
            sum(forced.get(gw) == n for gw in p.gameweeks) > 1
            for n, ps in rights.items()
            for p in ps
        ):
            continue
        # Enumeration prohibits unselected chips/dates and separately adds unused rights.
        selected = {n: frozenset(gw for gw, c in forced.items() if c == n) for n in available}
        periods = {
            n: tuple(
                ChipUseWindow(frozenset(gw for gw in p.gameweeks if forced.get(gw) == n), 0)
                for p in rights[n]
                if any(forced.get(gw) == n for gw in p.gameweeks)
            )
            for n in available
            if selected[n]
        }
        solved = optimize_transfer_plan(
            horizon,
            OPTIMAL_INITIAL,
            small_config,
            TransferPlanningConfig(),
            chips=ChipAvailability(available=selected, forced=forced, use_windows=periods),
        )
        terminal = sum(
            p.holding_value_points
            for n, ps in rights.items()
            for p in ps
            if not any(forced.get(gw) == n for gw in p.gameweeks)
        )
        best = max(best, solved.objective_value + terminal)
    assert joint.objective_value == pytest.approx(best)


def test_feasible_proposal_uses_one_declared_budget_without_reference_probes(
    known_optimum_players, small_config, monkeypatch
):
    import squadopt.planning.chip_strategy as strategy

    actual = strategy.optimize_transfer_plan
    budgets = []

    def feasible(*args, **kwargs):
        budgets.append(args[2].solver_deterministic_time_limit)
        return replace(actual(*args, **kwargs), solver_status=SolverStatus.FEASIBLE)

    monkeypatch.setattr(strategy, "optimize_transfer_plan", feasible)
    result = optimize_chip_strategy(
        PlanningHorizon(_horizon_table(known_optimum_players)),
        OPTIMAL_INITIAL,
        replace(small_config, solver_deterministic_time_limit=20),
        TransferPlanningConfig(),
        ChipAvailability({"3xc": frozenset({1})}),
    )
    assert budgets == [20]
    assert result.has_solution
    assert result.diagnostics["chip_strategy"]["actual_total"] <= 20.00001


def test_no_rights_reuses_feasible_plain_plan_without_pricing_it(
    known_optimum_players, small_config, monkeypatch
):
    import squadopt.planning.chip_strategy as strategy

    actual = strategy.optimize_transfer_plan
    calls = []

    def unproved(*args, **kwargs):
        calls.append(args[2].solver_deterministic_time_limit)
        solved = actual(*args, **kwargs)
        return replace(
            solved,
            solver_status=SolverStatus.FEASIBLE,
            diagnostics={**solved.diagnostics, "absolute_optimality_gap": 2.0},
        )

    monkeypatch.setattr(strategy, "optimize_transfer_plan", unproved)
    result = optimize_chip_strategy(
        PlanningHorizon(_horizon_table(known_optimum_players)),
        OPTIMAL_INITIAL,
        replace(small_config, solver_deterministic_time_limit=20),
        TransferPlanningConfig(),
        ChipAvailability(),
    )
    assert calls == [20]
    assert result.solver_status is SolverStatus.FEASIBLE
    assert result.diagnostics["absolute_optimality_gap"] == 2.0
    assert result.diagnostics["chip_strategy"]["reservations"] == []
