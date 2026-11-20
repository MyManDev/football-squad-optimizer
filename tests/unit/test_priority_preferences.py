"""Priority layers are compared with an independent enumeration of football packages."""

import json
from dataclasses import replace
from itertools import pairwise, permutations, product
from pathlib import Path

import pytest
from tests.unit.test_transfer_planning import _horizon_table

from squadopt.contracts.preferences import DecisionPreferences
from squadopt.contracts.priority_preferences import (
    PriorityPreference,
    PriorityProgram,
    priority_program_schema,
)
from squadopt.optimization import SolverStatus
from squadopt.optimization.work_budget import WorkBudget, work_budget
from squadopt.planning import (
    ChipAvailability,
    InitialSquadState,
    PlanningHorizon,
    TransferPlanningConfig,
)
from squadopt.planning.optimizer import optimize_priority_preferences, optimize_transfer_plan


def setup_case(players, config):
    players = players.copy()
    players["player_id"] = range(1, 9)
    players["expected_points"] = [5, 4.5, 4, 3.7, 10, 9.5, 6, 5.5]
    horizon = PlanningHorizon(_horizon_table(players, (1,)))
    state = InitialSquadState(squad_player_ids=(1, 3, 5, 7), bank_tenths=0, free_transfers=4)
    settings = TransferPlanningConfig().for_net_points()
    config = replace(config, bench_weight=0, solver_deterministic_time_limit=5)
    main = optimize_transfer_plan(
        horizon, state, config, settings, preferences=DecisionPreferences(net_points_priority=True)
    )
    return horizon, state, config, settings, main


def enumeration(horizon, program):
    # Enumerate all 16 final transfer packages and both legal lineups independently.
    points = dict(zip(horizon.table.player_id, horizon.table.expected_points, strict=True))
    candidates = []
    for squad in product((1, 2), (3, 4), (5, 6), (7, 8)):
        score = max(
            sum(points[p] for p in lineup) + max(points[p] for p in lineup)
            for lineup in ((squad[0], squad[1], squad[3]), (squad[0], squad[2], squad[3]))
        )
        candidates.append((squad, round(score * 10)))
    reference = max(score for _, score in candidates)
    ranked = []
    for squad, score in candidates:
        if score < reference - program.max_total_cost_tenths:
            continue
        satisfied = [
            set(row.rules.include_players) <= set(squad)
            and not set(row.rules.avoid_players) & set(squad)
            for row in program.preferences
        ]
        counts = tuple(
            sum(
                ok
                for row, ok in zip(program.preferences, satisfied, strict=True)
                if row.priority == priority
            )
            for priority in (1, 2, 3)
        )
        ranked.append(((*counts, score), squad))
    best = max(rank for rank, _ in ranked)
    return {squad for rank, squad in ranked if rank == best}, best[-1] / 10


def include(player, priority=2):
    return PriorityPreference(DecisionPreferences(include_players=(player,)), priority)


@pytest.mark.parametrize(
    "rules,total",
    [
        ((include(2), include(8)), 5),  # Individually cheap, jointly outside the total.
        ((include(2), include(8)), 10),  # Exact total boundary.
        ((include(2), PriorityPreference(DecisionPreferences(avoid_players=(2,)))), 0),
        ((include(2, 1), include(6, 2), include(8, 3)), 10),
        ((include(2, 3), include(6, 1), include(8, 2)), 5),
    ],
)
def test_priority_football_matches_all_transfer_packages(
    known_optimum_players, small_config, rules, total
):
    horizon, state, config, settings, main = setup_case(known_optimum_players, small_config)
    program = PriorityProgram(rules, total)
    expected_squads, expected_score = enumeration(horizon, program)
    outcome = optimize_priority_preferences(horizon, state, config, settings, main, program)
    squad = tuple(sorted(outcome.plan.weeks[0].selected_squad.player_id))
    assert squad in expected_squads
    assert outcome.plan.objective_value == pytest.approx(expected_score)
    assert outcome.total_cost == pytest.approx(main.objective_value - expected_score)
    assert outcome.total_cost <= total / 10
    assert set(outcome.satisfied).isdisjoint(outcome.left_out)
    assert set(outcome.satisfied) | set(outcome.left_out) == {
        row.identity for row in program.preferences
    }


def test_equal_priority_order_does_not_select_another_plan(known_optimum_players, small_config):
    horizon, state, config, settings, main = setup_case(known_optimum_players, small_config)
    answers = []
    for rules in permutations((include(2), include(6), include(8))):
        result = optimize_priority_preferences(
            horizon, state, config, settings, main, PriorityProgram(rules, 5)
        )
        answers.append((tuple(result.plan.weeks[0].selected_squad.player_id), result.satisfied))
    assert len(set(answers)) == 1


def test_unproved_reference_uses_certified_decisions_not_claimed_value(
    known_optimum_players, small_config
):
    horizon, state, config, settings, main = setup_case(known_optimum_players, small_config)
    forged_number = replace(main, solver_status=SolverStatus.FEASIBLE, objective_value=123456.0)
    result = optimize_priority_preferences(
        horizon, state, config, settings, forged_number, PriorityProgram((include(2),), 5)
    )
    assert result.reference_proved is False
    assert result.total_cost == pytest.approx(0.5)
    assert result.plan.objective_value == pytest.approx(main.objective_value - 0.5)


@pytest.mark.parametrize(("chip", "bonus"), [("3xc", 10), ("bboost", 4)])
def test_chip_bonus_binds_reference_floor_during_count_search(
    known_optimum_players, small_config, chip, bonus
):
    horizon, state, config, settings, plain = setup_case(known_optimum_players, small_config)
    rights = ChipAvailability(available={chip: {1}}, forced={1: chip})
    reference = optimize_transfer_plan(horizon, state, config, settings, chips=rights)
    assert reference.chips_played == {1: chip}
    # The starting keeper scores 5, the requested keeper 4.5. The captain scores
    # 10 and the bench scores 4. With a zero allowance, the keeper cannot change.
    expected = 5 + 10 + 6 + 10 + bonus
    assert reference.objective_value == expected == plain.objective_value + bonus
    rule = include(2)
    outcome = optimize_priority_preferences(
        horizon, state, config, settings, reference, PriorityProgram((rule,), 0), chips=rights
    )
    assert outcome.completed_priorities == (2,)
    assert outcome.left_out == (rule.identity,)
    assert outcome.plan.objective_value == expected
    assert outcome.total_cost == 0


def test_better_preference_plan_has_the_signed_difference_from_a_weak_reference(
    known_optimum_players, small_config
):
    horizon, state, config, settings, _ = setup_case(known_optimum_players, small_config)
    weak = optimize_transfer_plan(
        horizon,
        state,
        config,
        settings,
        preferences=DecisionPreferences(include_players=(2,), net_points_priority=True),
        protect_hold=False,
    )
    weak = replace(weak, solver_status=SolverStatus.FEASIBLE)
    program = PriorityProgram((include(1, 1),), 0)
    expected_squads, expected_score = enumeration(horizon, program)
    result = optimize_priority_preferences(horizon, state, config, settings, weak, program)
    assert tuple(sorted(result.plan.weeks[0].selected_squad.player_id)) in expected_squads
    assert result.plan.objective_value == pytest.approx(expected_score)
    assert result.total_cost == pytest.approx(weak.objective_value - expected_score)
    assert result.total_cost < 0
    assert result.reference_proved is False


def test_hard_rule_survives_conflicting_soft_rule(known_optimum_players, small_config):
    horizon, state, config, settings, main = setup_case(known_optimum_players, small_config)
    result = optimize_priority_preferences(
        horizon,
        state,
        config,
        settings,
        main,
        PriorityProgram((include(2),), 100),
        hard=DecisionPreferences(keep_players=(1,)),
    )
    assert 1 in set(result.plan.weeks[0].selected_squad.player_id)
    assert result.satisfied == ()
    assert len(result.left_out) == 1


def test_existing_worker_budget_is_not_reset(known_optimum_players, small_config):
    horizon, state, config, settings, main = setup_case(known_optimum_players, small_config)
    budget = WorkBudget(1)
    with work_budget(budget):
        result = optimize_priority_preferences(
            horizon,
            state,
            config,
            settings,
            main,
            PriorityProgram((include(2),), 5),
            work_limit=100,
        )
    assert budget.calls >= 2
    assert budget.cp_used > 0
    assert result.plan.has_solution


@pytest.mark.parametrize("priority", [True, 0, 4, 1.0, None])
def test_invalid_priority_is_not_coerced(priority):
    with pytest.raises(ValueError):
        PriorityPreference(DecisionPreferences(no_hits=True), priority)


@pytest.mark.parametrize("total", [True, -1, 1001, 1.5, None])
def test_invalid_total_is_not_coerced(total):
    with pytest.raises(ValueError):
        PriorityProgram((include(1),), total)


def test_program_schema_is_committed():
    path = Path(__file__).parents[2] / "docs/contracts/llmopt_priority_program_v1.schema.json"
    assert json.loads(path.read_text(encoding="utf-8")) == priority_program_schema()


def test_exhausted_layer_keeps_last_completed_priority(
    known_optimum_players, small_config, monkeypatch
):
    import squadopt.planning.optimizer as optimizer

    horizon, state, config, settings, main = setup_case(known_optimum_players, small_config)
    original = optimizer._solve
    calls = 0

    def stop_after_first_layer(model, solver):
        nonlocal calls
        calls += 1
        if calls == 3:
            return optimizer.cp_model.UNKNOWN
        return original(model, solver)

    monkeypatch.setattr(optimizer, "_solve", stop_after_first_layer)
    first, second, incidental = include(2, 1), include(6, 2), include(5, 3)
    result = optimize_priority_preferences(
        horizon, state, config, settings, main, PriorityProgram((first, second, incidental), 15)
    )
    assert result.completed_priorities == (1,)
    assert result.budget_exhausted
    assert result.satisfied == (first.identity,)
    assert result.left_out == ()
    assert set(result.unsearched) == {second.identity, incidental.identity}
    assert 5 in set(result.plan.weeks[0].selected_squad.player_id)
    assert [
        (p["priority"], p["status"]) for p in result.plan.diagnostics["priority_search_phases"]
    ] == [(1, "OPTIMAL"), (2, "UNKNOWN"), (0, "OPTIMAL")]
    _, score = enumeration(horizon, PriorityProgram((first,), 15))
    assert result.plan.objective_value == score


def test_earlier_points_witness_survives_weaker_count_and_interrupted_points(
    known_optimum_players, small_config, monkeypatch
):
    import squadopt.planning.optimizer as optimizer

    horizon, state, config, settings, main = setup_case(known_optimum_players, small_config)
    original = optimizer._solve
    calls = 0

    def cut_search(model, solver):
        nonlocal calls
        calls += 1
        if calls in (2, 3):
            # Both counts have many optimum witnesses. Make the first retain the
            # better captain and forward, then visit a worse midfielder on tier two.
            alternative = model.clone()
            required = {"captain_gw1_4", "squad_gw1_6"} if calls == 2 else {"squad_gw1_5"}
            found = set()
            for i, variable in enumerate(alternative.proto.variables):
                if variable.name in required:
                    alternative.add(alternative.get_int_var_from_proto_index(i) == 1)
                    found.add(variable.name)
            assert found == required
            return original(alternative, solver)
        if calls == 4:
            return optimizer.cp_model.UNKNOWN
        return original(model, solver)

    monkeypatch.setattr(optimizer, "_solve", cut_search)
    first, second = include(2, 1), include(7, 2)
    result = optimize_priority_preferences(
        horizon, state, config, settings, main, PriorityProgram((first, second), 15)
    )
    assert result.completed_priorities == (1, 2)
    assert {first.identity, second.identity} == set(result.satisfied)
    assert result.unsearched == ()
    assert result.budget_exhausted
    assert calls == 4
    assert result.plan.objective_value == 30.5
    assert result.total_cost == 0.5


@pytest.mark.parametrize("limited_call", ["first_count", "points"])
def test_real_solver_cutoff_resumes_only_the_granted_points_tail(
    known_optimum_players, small_config, monkeypatch, limited_call
):
    import squadopt.planning.optimizer as optimizer

    horizon, state, config, settings, main = setup_case(known_optimum_players, small_config)
    original = optimizer._solve
    calls = 0

    def admit(model, solver):
        nonlocal calls
        calls += 1
        if calls == (2 if limited_call == "first_count" else 3):
            # CP-SAT itself reports the stop at this effective grant.
            solver.parameters.max_deterministic_time = 1e-10
        return original(model, solver)

    monkeypatch.setattr(optimizer, "_solve", admit)
    first = include(2)
    result = optimize_priority_preferences(
        horizon, state, config, settings, main, PriorityProgram((first,), 15)
    )
    phases = result.plan.diagnostics["priority_search_phases"]
    if limited_call == "first_count":
        assert [(p["priority"], p["status"]) for p in phases] == [(2, "UNKNOWN")]
        assert result.budget_exhausted and result.completed_priorities == ()
        assert result.satisfied == result.left_out == ()
        assert result.unsearched == (first.identity,)
        assert result.plan.objective_value == main.objective_value
    else:
        assert [(p["priority"], p["status"]) for p in phases] == [
            (2, "OPTIMAL"),
            (0, "UNKNOWN"),
            (0, "OPTIMAL"),
        ]
        assert phases[1]["work_limit"] == 1e-10 and phases[1]["deterministic_stop"]
        assert result.satisfied == (first.identity,) and result.unsearched == ()
        assert not result.budget_exhausted
        assert result.plan.objective_value == 30.5 and result.total_cost == 0.5


@pytest.mark.parametrize(("window", "bundle_units"), [(1, 63), (3, 366)])
def test_count_search_and_points_share_remaining_bundle_capacity(
    known_optimum_players, small_config, window, bundle_units
):
    import pandas as pd

    horizon, state, config, settings, _ = setup_case(known_optimum_players, small_config)
    horizon = PlanningHorizon(
        pd.concat([horizon.table.assign(gameweek=week) for week in range(1, window + 1)])
    )
    main = optimize_transfer_plan(horizon, state, config, settings)
    meter = WorkBudget(bundle_units, cp_used=1)
    with work_budget(meter):
        result = optimize_priority_preferences(
            horizon, state, config, settings, main, PriorityProgram((include(2),), 50)
        )
    count, points = result.plan.diagnostics["priority_search_phases"]
    assert count["status"] == points["status"] == "OPTIMAL"
    assert (count["priority"], points["priority"]) == (2, 0)
    certified_remaining = (
        bundle_units
        - 1
        - (
            result.plan.diagnostics["deterministic_time_used"]
            - count["work_used"]
            - points["work_used"]
        )
    )
    assert count["work_limit"] == pytest.approx(0.75 * certified_remaining)
    assert points["work_limit"] == pytest.approx(certified_remaining - count["work_used"])
    assert meter.remaining == pytest.approx(points["work_limit"] - points["work_used"])


def test_three_week_rules_preserve_hard_constraints(known_optimum_players, small_config):
    horizon, state, config, settings, _ = setup_case(known_optimum_players, small_config)
    table = horizon.table
    import pandas as pd

    horizon = PlanningHorizon(pd.concat([table.assign(gameweek=week) for week in (1, 2, 3)]))
    main = optimize_transfer_plan(
        horizon, state, config, settings, preferences=DecisionPreferences(net_points_priority=True)
    )
    result = optimize_priority_preferences(
        horizon,
        state,
        config,
        settings,
        main,
        PriorityProgram((include(2),), 15),
        hard=DecisionPreferences(no_hits=True),
    )
    assert result.total_cost == pytest.approx(1.5)
    assert all(2 in set(week.selected_squad.player_id) for week in result.plan.weeks)
    assert all(week.paid_transfer_count == 0 for week in result.plan.weeks)


def test_clock_cut_points_tie_keeps_completed_count_witness(
    known_optimum_players, small_config, monkeypatch
):
    import squadopt.planning.optimizer as optimizer

    horizon, state, config, settings, main = setup_case(known_optimum_players, small_config)
    original = optimizer._solve
    solvers = []

    def stop_points_tie(model, solver):
        status = original(model, solver)
        solvers.append(solver)
        return optimizer.cp_model.FEASIBLE if len(solvers) == 3 else status

    monkeypatch.setattr(optimizer, "_solve", stop_points_tie)
    result = optimize_priority_preferences(
        horizon, state, config, settings, main, PriorityProgram((include(2),), 10)
    )
    assert len(solvers) == 3
    assert result.completed_priorities == (2,)
    assert result.budget_exhausted
    assert result.plan.solver_status is SolverStatus.FEASIBLE
    assert result.plan.diagnostics["primary_search_status"] == "OPTIMAL"
    assert result.plan.diagnostics["priority_search_phases"][-1]["status"] == "FEASIBLE"
    assert include(2).identity in result.satisfied


def test_layers_share_one_wall_ceiling(known_optimum_players, small_config, monkeypatch):
    import squadopt.planning.optimizer as optimizer

    horizon, state, config, settings, main = setup_case(known_optimum_players, small_config)
    original = optimizer.configure_solver
    limits = []
    elapsed = 0.0

    def advancing_clock():
        nonlocal elapsed
        elapsed += 0.001
        return elapsed

    def record_limit(solver, config, wall_limit, deterministic_limit):
        limits.append((elapsed, wall_limit))
        return original(solver, config, wall_limit, deterministic_limit)

    monkeypatch.setattr(optimizer, "perf_counter", advancing_clock)
    monkeypatch.setattr(optimizer, "configure_solver", record_limit)
    result = optimize_priority_preferences(
        horizon,
        state,
        config,
        settings,
        main,
        PriorityProgram((include(2, 1), include(6, 2), include(8, 3)), 15),
    )
    assert result.plan.has_solution
    certificate, *counts, points = limits
    assert len(counts) == 3
    deadline = sum(certificate)
    assert sum(points) == pytest.approx(deadline)
    assert all(sum(count) == pytest.approx(sum(counts[0])) for count in counts)
    assert sum(counts[-1]) < sum(points)
    assert all(left[1] > right[1] for left, right in pairwise([certificate, *counts]))
    assert all(wall < certificate[1] for _, wall in [*counts, points])
