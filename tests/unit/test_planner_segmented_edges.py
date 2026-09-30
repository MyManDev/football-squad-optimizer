"""Synthetic edge evidence, never a claim about actual fixtures or injury calibration."""

from dataclasses import replace
from decimal import ROUND_HALF_UP, Decimal
from itertools import product

import pytest
from ortools.sat.python import cp_model
from tests.unit.test_planner_incumbent import problem

import squadopt.planning.optimizer as optimizer
import squadopt.planning.segmented as segmented
from squadopt.application.advice_variants import weighted_horizon
from squadopt.optimization import SolverStatus
from squadopt.optimization.models import InvalidConfigurationError
from squadopt.planning import InitialSquadState, PlanningHorizon, TransferPlanningConfig
from squadopt.planning.horizon import ProjectionHorizon, to_planning_horizon
from squadopt.planning.optimizer import optimize_transfer_plan


def milli(value):
    return int((Decimal(str(value)) * 1000).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


@pytest.mark.parametrize("window", [3, 5])
@pytest.mark.parametrize("weight", [0, 20, 50])
@pytest.mark.parametrize("held", [0, 1])
@pytest.mark.parametrize("scenario", ["blank_double", "delayed_return", "earlier_return"])
def test_synthetic_calendar_and_return_paths_match_full_enumeration(
    known_optimum_players, small_config, window, weight, held, scenario
):
    horizon, _, config = problem(known_optimum_players, small_config, window)
    names = ("GK_A", "DEF_A", "MID_A", "FWD_A", "FWD_B")
    ids = {name: index + 1 for index, name in enumerate(names)}
    table = horizon.table.loc[horizon.table.player_id.isin(names)].copy()
    vectors = {
        "blank_double": ([0, 18, 2, 0, 16], [6, 2, 12, 8, 1]),
        "delayed_return": ([0, 0, 3, 8, 9], [5, 6, 6, 5, 4]),
        "earlier_return": ([0, 4, 8, 8, 9], [5, 6, 6, 5, 4]),
    }
    values = vectors[scenario]
    table["fixture_count"] = 1
    table["home_fixture_count"] = 0
    for player, points in (("GK_A", 7), ("DEF_A", 4), ("MID_A", 5)):
        table.loc[table.player_id.eq(player), "expected_points"] = points
    for index, player in enumerate(("FWD_A", "FWD_B")):
        mask = table.player_id.eq(player)
        table.loc[mask, "expected_points"] = values[index][:window]
        if scenario == "blank_double" and index == 0:
            table.loc[mask, "fixture_count"] = [0, 2, 1, 0, 2][:window]
    table["price_tenths"] = 50
    table.player_id = table.player_id.map(ids)
    projection = ProjectionHorizon(
        table, "synthetic", "synthetic-known-before-decision", "synthetic", "1", "1", "1"
    )
    adjusted = weighted_horizon(projection, {4: 100, 5: 25}, weight)
    base = to_planning_horizon(projection)
    weighted = to_planning_horizon(adjusted)
    state = InitialSquadState((1, 2, 3, 4 + held), 10 * held, held)
    settings = TransferPlanningConfig(acquisition_sell_on_fee=0.5)
    seed = segmented.plan_in_segments(
        weighted, state, config, segment_lengths=(1,) * window, transfer=settings
    )
    solved = optimize_transfer_plan(
        weighted, state, config, settings, incumbent_plan=seed, protect_incumbent=True
    )

    def points(index, chosen, scaled):
        value = values[chosen][index] * (1 + weight / 100 * (1 if chosen == 0 else 0.25))
        return milli(value) if scaled else value

    # Independent complete action enumeration, FT recurrence and integer objective.
    objectives = []
    for actions in product((0, 1), repeat=window):
        current, free, score = held, held, 0
        for index, chosen in enumerate(actions):
            swaps = int(chosen != current)
            hits = 4 * max(0, swaps - free)
            value = points(index, chosen, True)
            score += 12000 + value + max(7000, value) - hits * 1000
            free = min(5, max(0, free - swaps) + 1)
            current = chosen
        objectives.append(score)
    assert solved.solver_status is SolverStatus.OPTIMAL
    assert solved.diagnostics["scaled_model_objective_value"] == max(objectives) / 1000
    assert (
        solved.diagnostics["scaled_model_objective_value"]
        >= solved.diagnostics["incumbent_protection"]["scaled_objective_value"]
    )
    base_total, weighted_total = 0, 0
    for index, week in enumerate(solved.weeks):
        chosen = int(5 in set(week.selected_squad.player_id))
        raw = values[chosen][index]
        base_total += 12 + raw + max(7, raw) - week.transfer_hit_points
        value = points(index, chosen, False)
        weighted_total += 12 + value + max(7, value) - week.transfer_hit_points
        assert week.bank_after_tenths == state.bank_tenths
    assert solved.objective_value == pytest.approx(weighted_total)
    assert weighted_total >= base_total
    assert (base.table.expected_points == projection.table.expected_points).all()
    if scenario == "blank_double":
        assert adjusted.table.loc[adjusted.table.fixture_count.eq(0), "expected_points"].eq(0).all()


def test_ft_cap_and_hit_ledger_across_segment_boundaries(
    known_optimum_players, small_config, monkeypatch
):
    horizon, initial, config = problem(known_optimum_players, small_config, 5)
    original = ("GK_A", "DEF_A", "MID_A", "FWD_A")
    changed = ("GK_A", "DEF_B", "MID_B", "FWD_B")
    desired = {1: original, 2: original, 3: changed, 4: changed, 5: original}
    real = segmented.optimize_transfer_plan

    def prescribed(horizon, *args, **kwargs):
        return real(
            horizon, *args, fixed_week_squads={w: desired[w] for w in horizon.gameweeks}, **kwargs
        )

    monkeypatch.setattr(segmented, "optimize_transfer_plan", prescribed)
    settings = TransferPlanningConfig(max_free_transfers=2, acquisition_sell_on_fee=0.5)
    plan = segmented.plan_in_segments(
        horizon, initial, config, segment_lengths=(2, 1, 2), transfer=settings
    )
    assert [w.free_transfers_before for w in plan.weeks] == [1, 2, 2, 1, 2]
    assert [w.free_transfers_for_next_gameweek for w in plan.weeks] == [2, 2, 1, 2, 1]
    assert [w.paid_transfer_count for w in plan.weeks] == [0, 0, 1, 0, 1]
    assert plan.total_transfer_hit_points == 8
    assert all(w.bank_after_tenths == 0 for w in plan.weeks)
    assert optimize_transfer_plan(
        horizon, initial, config, settings, incumbent_plan=plan, protect_incumbent=True
    ).has_solution


def test_guard_protects_integer_objective_not_submillipoint_raw_order(
    known_optimum_players, small_config, monkeypatch
):
    horizon, initial, config = problem(known_optimum_players, small_config, 3)
    table = horizon.table.copy()
    table.loc[table.player_id.eq("FWD_A"), "expected_points"] = 9.0001
    table.loc[table.player_id.eq("FWD_B"), "expected_points"] = 9.0004
    horizon = PlanningHorizon(table)
    chosen = ("GK_A", "DEF_A", "MID_A", "FWD_B")
    seed = optimize_transfer_plan(
        horizon, initial, config, fixed_week_squads={w: chosen for w in horizon.gameweeks}
    )
    real = optimizer._solve
    calls = 0

    def equal_scaled_search(model, solver):
        nonlocal calls
        calls += 1
        if calls == 2:
            restricted = model.clone()
            for index, variable in enumerate(restricted.proto.variables):
                if variable.name.startswith("transfer_count_"):
                    restricted.add(restricted.get_int_var_from_proto_index(index) == 0)
            assert real(restricted, solver) == cp_model.OPTIMAL
            return cp_model.FEASIBLE
        return real(model, solver)

    monkeypatch.setattr(optimizer, "_solve", equal_scaled_search)
    result = optimize_transfer_plan(
        horizon, initial, config, incumbent_plan=seed, protect_incumbent=True
    )
    assert not result.diagnostics["incumbent_protection"]["selected"]
    assert (
        result.diagnostics["scaled_model_objective_value"]
        == seed.diagnostics["scaled_model_objective_value"]
    )
    assert 0 < seed.objective_value - result.objective_value < 0.01


def test_zero_configured_budget_is_rejected_before_segment_search(small_config):
    with pytest.raises(InvalidConfigurationError, match="positive"):
        replace(small_config, solver_deterministic_time_limit=0)
