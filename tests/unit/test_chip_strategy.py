"""Chip continuation arithmetic and forecast-only allocation checks."""

from dataclasses import replace

import pytest
from tests.unit.test_transfer_planning import OPTIMAL_INITIAL, _horizon_table

from squadopt.optimization import SolverStatus
from squadopt.planning import (
    ChipAvailability,
    ChipUseWindow,
    PlanningHorizon,
    TransferPlanningConfig,
)
from squadopt.planning.chip_strategy import continuation_value, optimize_chip_strategy


def test_stopping_value_matches_exact_two_outcome_tree():
    # Observe either zero or ten, equiprobably. At n=2 wait after zero and take ten.
    assert continuation_value([0.0, 10.0], 0) == 0
    assert continuation_value([0.0, 10.0], 1) == 5
    assert continuation_value([0.0, 10.0], 2) == 7.5
    assert continuation_value([0.0, 10.0], 3) == 8.75


def test_stopping_value_is_bounded_monotone_and_scale_equivariant():
    values = [continuation_value([2, 4, 12], n) for n in range(39)]
    assert values == sorted(values)
    assert all(0 <= x <= 12 for x in values)
    assert continuation_value([4, 8, 24], 8) == pytest.approx(2 * values[8])
    assert continuation_value([7], 38) == 7


@pytest.mark.parametrize(
    "samples,n", [([], 2), ([float("nan")], 2), ([-1], 2), ([1], True), ([1], 39)]
)
def test_invalid_tail_inputs_are_refused(samples, n):
    with pytest.raises(ValueError):
        continuation_value(samples, n)


def test_chip_strategy_exercises_expiring_right_and_keeps_new_one(
    known_optimum_players, small_config
):
    horizon = PlanningHorizon(_horizon_table(known_optimum_players, (19, 20)))
    chips = ChipAvailability(
        available={"3xc": frozenset(range(19, 39))},
        use_windows={
            "3xc": (ChipUseWindow(frozenset({19})), ChipUseWindow(frozenset(range(20, 39))))
        },
    )
    result = optimize_chip_strategy(
        horizon, OPTIMAL_INITIAL, small_config, TransferPlanningConfig(), chips
    )
    assert result.solver_status is SolverStatus.OPTIMAL
    assert result.chips_played == {19: "3xc"}
    info = result.diagnostics["chip_strategy"]
    assert info["reservations"][0]["holding_value"] == 0
    assert info["reservations"][1]["holding_value"] > 0
    assert info["experimental"] is True
    assert info["basis"] == "selection_utility"


def _long_right_near_equal_weeks(players, config, chip):
    """A window GW6-8 whose three weeks differ by at most 3%, the right open to GW19.

    Eleven opportunities remain after the window. GW7 is the best week, by 2%.
    """

    table = _horizon_table(players, (6, 7, 8))
    for gameweek, scale in ((7, 1.02), (8, 0.99)):
        table.loc[table.gameweek.eq(gameweek), "expected_points"] *= scale
    return optimize_chip_strategy(
        PlanningHorizon(table),
        OPTIMAL_INITIAL,
        config,
        TransferPlanningConfig(),
        ChipAvailability(available={chip: frozenset(range(6, 20))}),
    )


@pytest.mark.parametrize("chip", ["3xc", "bboost"])
def test_today_a_right_with_many_opportunities_left_is_spent_in_the_windows_best_week(
    known_optimum_players, small_config, chip
):
    """What the planner does now, pinned: the defect of audit 2026-09-25, H3.

    The holding value is built from the window's own weeks, so it stays below the best of
    them however many opportunities remain, and the chip is played in that week. This
    changes together with the expected failure below once the tail values the season.
    """

    result = _long_right_near_equal_weeks(known_optimum_players, small_config, chip)
    assert result.solver_status is SolverStatus.OPTIMAL
    (reservation,) = result.diagnostics["chip_strategy"]["reservations"]
    assert reservation["remaining_opportunities"] == 11
    assert reservation["sample_max"] - reservation["sample_min"] < 0.04 * reservation["sample_max"]
    assert reservation["holding_value"] < reservation["sample_max"]
    assert result.chips_played == {7: chip}


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "Audit 2026-09-25, H3: the tail value comes from the window's own weeks, so it can "
        "never beat the window's best week and a right with 11 opportunities left is spent "
        "inside the window. Passes once the tail values the captured season calendar."
    ),
)
@pytest.mark.parametrize("chip", ["3xc", "bboost"])
def test_a_right_with_many_opportunities_left_and_near_equal_weeks_is_held(
    known_optimum_players, small_config, chip
):
    result = _long_right_near_equal_weeks(known_optimum_players, small_config, chip)
    assert result.solver_status is SolverStatus.OPTIMAL
    assert result.chips_played == {}


def test_old_calibration_is_not_silently_reused(known_optimum_players, small_config):
    horizon = PlanningHorizon(_horizon_table(known_optimum_players))
    with pytest.raises(ValueError, match="own continuation"):
        optimize_chip_strategy(
            horizon,
            OPTIMAL_INITIAL,
            small_config,
            replace(TransferPlanningConfig(), chip_holding_value_points={"3xc": 18}),
            ChipAvailability(),
        )


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


def test_reference_has_fixed_budget_and_unproved_reference_is_refused(
    known_optimum_players, small_config, monkeypatch
):
    import squadopt.planning.chip_strategy as strategy
    from squadopt.optimization import SolverExecutionError

    actual = strategy.optimize_transfer_plan
    budgets = []

    def unproved(*args, **kwargs):
        budgets.append(args[2].solver_deterministic_time_limit)
        return replace(actual(*args, **kwargs), solver_status=SolverStatus.FEASIBLE)

    monkeypatch.setattr(strategy, "optimize_transfer_plan", unproved)
    with pytest.raises(SolverExecutionError, match="proved optimal"):
        optimize_chip_strategy(
            PlanningHorizon(_horizon_table(known_optimum_players)),
            OPTIMAL_INITIAL,
            replace(small_config, solver_deterministic_time_limit=20),
            TransferPlanningConfig(),
            ChipAvailability(available={"3xc": frozenset({1})}),
        )
    assert budgets == [60]


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
