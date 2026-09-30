"""A certified starting path remains available when bounded search cannot improve it."""

from dataclasses import replace

import pytest
from ortools.sat.python import cp_model
from tests.unit.test_planner_incumbent import problem

import squadopt.planning.optimizer as module
from squadopt.contracts.preferences import DecisionPreferences
from squadopt.optimization import SolverExecutionError, SolverStatus
from squadopt.planning import (
    ChipAvailability,
    InitialSquadState,
    PlanningHorizon,
    TransferPlanningConfig,
    TransferPlanningValidationError,
    optimize_transfer_plan,
)
from squadopt.planning.lookahead import optimize_with_lookahead


def exhaust_after_certification(monkeypatch):
    actual = module._deterministic_time_used
    calls = 0

    def used(solver, status):
        nonlocal calls
        calls += 1
        return 6.0 if calls == 1 else actual(solver, status)

    monkeypatch.setattr(module, "_deterministic_time_used", used)


@pytest.mark.parametrize("window", [3, 5])
@pytest.mark.parametrize("chip", [None, "freehit", "wildcard", "3xc", "bboost"])
def test_exhausted_search_retains_only_rescored_feasible_decisions(
    known_optimum_players, small_config, window, chip, monkeypatch
):
    args = problem(known_optimum_players, small_config, window)
    chips = (
        ChipAvailability()
        if chip is None
        else ChipAvailability(available={chip: frozenset({2})}, forced={2: chip})
    )
    settings = TransferPlanningConfig(acquisition_sell_on_fee=0.5)
    seed = optimize_transfer_plan(*args, settings, chips=chips)
    assert seed.solver_status is SolverStatus.OPTIMAL
    poisoned_weeks = tuple(
        replace(
            w,
            projected_score=1e9,
            discounted_objective_contribution=1e9,
            selected_squad=w.selected_squad.assign(expected_points=1e9),
        )
        for w in seed.weeks
    )
    poisoned = replace(
        seed,
        weeks=poisoned_weeks,
        objective_value=1e9,
        total_projected_score=1e9,
        total_transfer_hit_points=1e9,
    )
    exhaust_after_certification(monkeypatch)
    result = optimize_transfer_plan(
        *args, settings, chips=chips, incumbent_plan=poisoned, protect_incumbent=True
    )
    assert result.solver_status is SolverStatus.FEASIBLE
    assert result.objective_value == pytest.approx(seed.objective_value)
    assert result.total_projected_score == pytest.approx(seed.total_projected_score)
    assert result.total_transfer_hit_points == seed.total_transfer_hit_points
    assert result.chips_played == seed.chips_played
    assert result.diagnostics["incumbent_protection"]["selected"] is True
    assert result.diagnostics["primary_search_status"] == "UNKNOWN"
    assert result.diagnostics["best_objective_bound"] is None
    assert result.diagnostics["absolute_optimality_gap"] is None
    assert result.diagnostics["deterministic_time_budget_exhausted"] is True
    assert result.diagnostics["deterministic_time_used"] >= 6
    for actual, expected in zip(result.weeks, seed.weeks, strict=True):
        assert set(actual.selected_squad.player_id) == set(expected.selected_squad.player_id)
        assert actual.captain.player_id == expected.captain.player_id
        assert actual.bank_after_tenths == expected.bank_after_tenths
        assert actual.free_transfers_for_next_gameweek == expected.free_transfers_for_next_gameweek


@pytest.mark.parametrize("status", [cp_model.FEASIBLE, cp_model.OPTIMAL, cp_model.INFEASIBLE])
def test_worse_feasible_search_retains_seed_but_a_false_proof_raises(
    known_optimum_players, small_config, monkeypatch, status
):
    args = problem(known_optimum_players, small_config)
    seed = optimize_transfer_plan(*args)
    actual_solve = module._solve
    calls = 0

    def restricted_search(model, solver):
        nonlocal calls
        calls += 1
        if calls == 2:
            if status == cp_model.INFEASIBLE:
                return status
            restricted = model.clone()
            # Force a worse feasible primary result with the same variable indices.
            for index, variable in enumerate(restricted.proto.variables):
                if variable.name.startswith("transfer_count_"):
                    restricted.add(restricted.get_int_var_from_proto_index(index) == 0)
            actual_solve(restricted, solver)
            return status
        return actual_solve(model, solver)

    monkeypatch.setattr(module, "_solve", restricted_search)
    if status != cp_model.FEASIBLE:
        with pytest.raises(SolverExecutionError, match="certified incumbent"):
            optimize_transfer_plan(*args, incumbent_plan=seed, protect_incumbent=True)
    else:
        result = optimize_transfer_plan(*args, incumbent_plan=seed, protect_incumbent=True)
        assert result.solver_status is SolverStatus.FEASIBLE
        assert result.objective_value == seed.objective_value
        assert result.diagnostics["incumbent_protection"]["selected"] is True
        assert result.diagnostics["primary_search_status"] == "FEASIBLE"


def test_guard_accepts_a_real_improvement_and_never_trusts_the_claimed_score(
    known_optimum_players, small_config
):
    args = problem(known_optimum_players, small_config)
    seed = optimize_transfer_plan(
        *args, fixed_week_squads={w: args[1].squad_player_ids for w in args[0].gameweeks}
    )
    result = optimize_transfer_plan(
        *args, incumbent_plan=replace(seed, objective_value=1e9), protect_incumbent=True
    )
    assert result.objective_value > seed.objective_value
    assert result.solver_status is SolverStatus.OPTIMAL
    assert result.diagnostics["incumbent_protection"]["selected"] is False


@pytest.mark.parametrize("window", [3, 5])
def test_lookahead_reuses_guard_without_stacking_hold(
    known_optimum_players, small_config, window, monkeypatch
):
    args = problem(known_optimum_players, small_config, window + 1)
    seed = optimize_transfer_plan(*args)
    exhaust_after_certification(monkeypatch)
    result = optimize_with_lookahead(*args, window=window, incumbent_plan=seed)
    assert result.plan.solver_status is SolverStatus.FEASIBLE
    assert "hold_protection" not in result.plan.diagnostics
    assert result.window_net_points + result.tail_net_points == pytest.approx(
        seed.total_projected_score - seed.total_transfer_hit_points
    )
    assert len(result.window) == window


def test_guard_refuses_missing_seed_and_new_preferences_that_forbid_it(
    known_optimum_players, small_config
):
    args = problem(known_optimum_players, small_config)
    ids = {player: i + 1 for i, player in enumerate(known_optimum_players.player_id)}
    args = (
        PlanningHorizon(args[0].table.assign(player_id=args[0].table.player_id.map(ids))),
        InitialSquadState(tuple(ids[p] for p in args[1].squad_player_ids), 0, 1),
        args[2],
    )
    with pytest.raises(TransferPlanningValidationError, match="requires an incumbent"):
        optimize_transfer_plan(*args, protect_incumbent=True)
    seed = optimize_transfer_plan(*args)
    with pytest.raises(TransferPlanningValidationError, match="certified"):
        optimize_transfer_plan(
            *args,
            incumbent_plan=seed,
            protect_incumbent=True,
            preferences=DecisionPreferences(avoid_players=(ids["FWD_B"],)),
        )
