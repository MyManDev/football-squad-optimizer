"""Priority layers are compared with an independent enumeration of football packages."""

import json
from dataclasses import replace
from itertools import permutations, product
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
from squadopt.planning import InitialSquadState, PlanningHorizon, TransferPlanningConfig
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
    assert outcome.total_cost == pytest.approx(max(0, main.objective_value - expected_score))
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
    first, second = include(2, 1), include(6, 2)
    result = optimize_priority_preferences(
        horizon, state, config, settings, main, PriorityProgram((first, second), 15)
    )
    assert result.completed_priorities == (1,)
    assert result.budget_exhausted
    assert first.identity in result.satisfied
    assert result.plan.has_solution


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
