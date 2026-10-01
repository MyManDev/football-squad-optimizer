"""Product composition keeps certified complete plans and bounded fallback behavior."""

from dataclasses import replace

import pytest
from tests.unit.test_planner_incumbent import problem

import squadopt.planning.guarded as module
from squadopt.contracts.preferences import DecisionPreferences
from squadopt.optimization import SolverExecutionError
from squadopt.planning import (
    ChipAvailability,
    TransferPlanningConfig,
    TransferPlanningValidationError,
)
from squadopt.planning.segmented import SegmentConstructionError


@pytest.mark.parametrize("window", [3, 5])
@pytest.mark.parametrize("freehit", [False, True])
def test_product_window_keeps_full_state_and_certifies_seed(
    known_optimum_players, small_config, window, freehit
):
    args = problem(known_optimum_players, small_config, window)
    rights = (
        ChipAvailability({"freehit": frozenset({2})}, {2: "freehit"})
        if freehit
        else ChipAvailability()
    )
    plan = module.optimize_guarded_window(
        *args,
        TransferPlanningConfig(acquisition_sell_on_fee=0.5),
        chips=rights,
        preferences=DecisionPreferences(no_hits=True),
    )
    assert plan.has_solution
    assert len(plan.weeks) == window
    assert all(w.paid_transfer_count == 0 for w in plan.weeks)
    assert all(w.bank_after_tenths >= 0 for w in plan.weeks)
    assert [w.gameweek for w in plan.weeks if w.chip] == ([2] if freehit else [])
    assert plan.diagnostics["incumbent_protection"]["version"] == "certified_fallback_v1"
    cost = plan.diagnostics["sequential_incumbent"]
    assert cost["seed_completed"] is True
    assert cost["seed_cap"] + cost["final_cap_including_hold"] == cost["configured_total"]
    assert cost["actual_total"] == pytest.approx(
        cost["seed_work"] + cost["final_work_including_hold"]
    )
    assert cost["actual_total"] <= 5.01


def test_incomplete_construction_uses_remaining_budget_and_honest_cost(
    known_optimum_players, small_config, monkeypatch
):
    args = problem(known_optimum_players, small_config)

    def failed(*args, **kwargs):
        raise SegmentConstructionError("incomplete", actual_work=0.2, clock_stopped=False)

    monkeypatch.setattr(module, "plan_in_segments", failed)
    original = module.optimize_transfer_plan
    calls = []

    def record(*args, **kwargs):
        calls.append((args[2], kwargs))
        return original(*args, **kwargs)

    monkeypatch.setattr(module, "optimize_transfer_plan", record)
    result = module.optimize_guarded_window(*args, TransferPlanningConfig())
    assert result.has_solution and len(result.weeks) == 3
    assert len(calls) == 1
    config, flags = calls[0]
    assert config.solver_deterministic_time_limit == 3.5
    assert config.solver_time_limit_seconds == 4.5
    assert flags["protect_hold"] is True
    assert flags["protect_incumbent"] is False
    cost = result.diagnostics["sequential_incumbent"]
    assert cost["seed_completed"] is False and cost["seed_work"] == 0.2
    assert cost["final_work_including_hold"] == pytest.approx(
        result.diagnostics["deterministic_time_used"]
        + result.diagnostics["hold_protection"]["deterministic_time"]
    )


@pytest.mark.parametrize("clock", [False, True])
def test_invalid_contract_or_wall_stop_never_becomes_partial_answer(
    known_optimum_players, small_config, monkeypatch, clock
):
    def failed(*args, **kwargs):
        if clock:
            raise SegmentConstructionError("wall", actual_work=0.01, clock_stopped=True)
        raise TransferPlanningValidationError("invalid state")

    monkeypatch.setattr(module, "plan_in_segments", failed)

    def unexpected(*args, **kwargs):
        pytest.fail("must not retry invalid or clock-truncated construction")

    monkeypatch.setattr(module, "optimize_transfer_plan", unexpected)
    with pytest.raises(SolverExecutionError if clock else TransferPlanningValidationError):
        module.optimize_guarded_window(
            *problem(known_optimum_players, small_config), TransferPlanningConfig()
        )


def test_certification_failure_is_not_hidden(known_optimum_players, small_config, monkeypatch):
    def refuse(*args, **kwargs):
        raise TransferPlanningValidationError("certification failed")

    monkeypatch.setattr(module, "optimize_transfer_plan", refuse)
    with pytest.raises(TransferPlanningValidationError, match="certification failed"):
        module.optimize_guarded_window(
            *problem(known_optimum_players, small_config), TransferPlanningConfig()
        )


@pytest.mark.parametrize("budget", [None, 1.0])
def test_missing_or_too_small_budget_refused(known_optimum_players, small_config, budget):
    horizon, initial, config = problem(known_optimum_players, small_config)
    with pytest.raises(TransferPlanningValidationError, match="budget"):
        module.optimize_guarded_window(
            horizon,
            initial,
            replace(config, solver_deterministic_time_limit=budget),
            TransferPlanningConfig(),
        )


@pytest.mark.parametrize(
    "route", ["football", "current", "one_week", "overlap", "automatic", "unbudgeted"]
)
def test_guarded_live_routing_leaves_other_methods_unchanged(tmp_path, monkeypatch, route):
    from tests.unit.test_live_horizon_planning import _inputs

    from squadopt.live import transfers as live
    from squadopt.optimization import OptimizationConfig
    from squadopt.planning import FirstWeekOverlap

    weeks = (2,) if route == "one_week" else (2, 3, 4)
    inputs, horizon, held, rules = _inputs(tmp_path, weeks)
    if route != "current":
        horizon = replace(horizon, model_name="fixture_football_candidate")
    seen = []

    class Routed(Exception):
        pass

    def mark(name):
        def called(*args, **kwargs):
            seen.append(name)
            raise Routed

        return called

    monkeypatch.setattr(live, "optimize_guarded_window", mark("guarded"))
    monkeypatch.setattr(live, "optimize_transfer_plan", mark("standard"))
    monkeypatch.setattr(live, "optimize_chip_strategy", mark("automatic"))
    kwargs = {"chip_strategy": route == "automatic"}
    if route == "overlap":
        kwargs["first_week_overlap"] = FirstWeekOverlap(frozenset(held.squad_player_ids), 1, 15)
    with pytest.raises(Routed):
        live.plan_transfer_horizon(
            inputs,
            horizon,
            held,
            rules,
            optimization=OptimizationConfig(
                solver_deterministic_time_limit=None if route == "unbudgeted" else 60
            ),
            **kwargs,
        )
    assert seen == [
        "guarded" if route == "football" else "automatic" if route == "automatic" else "standard"
    ]
