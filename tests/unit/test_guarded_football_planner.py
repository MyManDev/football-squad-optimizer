"""Product composition keeps certified complete plans and bounded fallback behavior."""

from dataclasses import replace

import pytest
from tests.unit.test_expected_swap import world
from tests.unit.test_planner_incumbent import problem

import squadopt.planning.expected_window as expected_window
import squadopt.planning.guarded as module
import squadopt.planning.optimizer as optimizer
import squadopt.planning.segmented as segmented
from squadopt.contracts.preferences import DecisionPreferences
from squadopt.optimization import SolverExecutionError
from squadopt.planning import (
    ChipAvailability,
    TransferPlanningConfig,
    TransferPlanningValidationError,
)
from squadopt.planning.segmented import SegmentConstructionError


def test_protected_receipt_from_a_different_phase_cannot_authorize_an_overrun(monkeypatch):
    horizon, initial, config, transfer, _ = world()
    config = replace(config, solver_deterministic_time_limit=60)
    initial = replace(initial, free_transfers=5)
    transfer = replace(transfer, banked_transfer_value_points=0)
    caps = []

    def wrong_phase(horizon, state, settings, policy, **kwargs):
        caps.append(settings.solver_deterministic_time_limit)
        plan = module.optimize_guarded_window(horizon, state, settings, policy, **kwargs)
        work = plan.diagnostics["sequential_incumbent"]
        assert plan.has_solution and plan.diagnostics["incumbent_protection"]
        report = {
            **work,
            "configured_total": 36,
            "actual_total": 24.06,
            "final_work_including_hold": 24.06 - work["seed_work"],
        }
        return replace(plan, diagnostics={**plan.diagnostics, "sequential_incumbent": report})

    monkeypatch.setattr(expected_window, "optimize_guarded_window", wrong_phase)
    with pytest.raises(ValueError, match="Invalid deterministic-work accounting"):
        expected_window.optimize_expected_window(horizon, initial, config, transfer)
    assert caps == [24.0]


@pytest.mark.parametrize("first", [0.95, 2.4])
def test_next_segment_can_use_only_the_measured_construction_balance(
    known_optimum_players, small_config, monkeypatch, first
):
    horizon, initial, config = problem(known_optimum_players, small_config)
    config = replace(config, solver_deterministic_time_limit=2.4)
    original = segmented.optimize_transfer_plan
    limits = []

    def measured(horizon, state, settings, *args, **kwargs):
        limits.append(settings.solver_deterministic_time_limit)
        plan = original(horizon, state, settings, *args, **kwargs)
        used = [first, 0.9, 0.1][len(limits) - 1]
        return replace(plan, diagnostics={**plan.diagnostics, "deterministic_time_used": used})

    monkeypatch.setattr(segmented, "optimize_transfer_plan", measured)
    if first == 2.4:
        with pytest.raises(SegmentConstructionError) as error:
            segmented.plan_in_segments(
                horizon, initial, config, segment_lengths=(1, 1, 1), limit_remaining_work=True
            )
        assert error.value.actual_work == 2.4
        assert limits == pytest.approx([0.8])
    else:
        plan = segmented.plan_in_segments(
            horizon, initial, config, segment_lengths=(1, 1, 1), limit_remaining_work=True
        )
        assert plan.has_solution and plan.diagnostics["deterministic_time_used"] == pytest.approx(
            1.95
        )
        assert limits == pytest.approx([0.8, 0.8, 0.55])


def test_guarded_final_cannot_spend_the_seed_overrun_again(
    known_optimum_players, small_config, monkeypatch
):
    horizon, initial, config = problem(known_optimum_players, small_config)
    config = replace(config, solver_deterministic_time_limit=24)
    segments, full = module.plan_in_segments, module.optimize_transfer_plan
    caps = []

    def costly_seed(*args, **kwargs):
        plan = segments(*args, **kwargs)
        return replace(plan, diagnostics={**plan.diagnostics, "deterministic_time_used": 2.62})

    def measured(horizon, state, settings, *args, **kwargs):
        caps.append(settings.solver_deterministic_time_limit)
        return full(horizon, state, settings, *args, **kwargs)

    monkeypatch.setattr(module, "plan_in_segments", costly_seed)
    monkeypatch.setattr(module, "optimize_transfer_plan", measured)
    result = module.optimize_guarded_window(
        horizon, initial, config, TransferPlanningConfig(), limit_remaining_work=True
    )
    assert result.has_solution and caps == pytest.approx([21.38])
    assert result.diagnostics["sequential_incumbent"]["final_cap_including_hold"] == pytest.approx(
        21.38
    )


@pytest.mark.parametrize("probe_used", [0.4, 0.75])
def test_hold_debits_its_actual_work_before_primary_admission(
    known_optimum_players, small_config, monkeypatch, probe_used
):
    args = problem(known_optimum_players, small_config)
    solve, read_work = optimizer._solve, optimizer._deterministic_time_used
    calls = []

    def track(model, solver):
        calls.append(solver)
        return solve(model, solver)

    def work(solver, raw_status):
        return probe_used if solver is calls[0] else read_work(solver, raw_status)

    monkeypatch.setattr(optimizer, "_solve", track)
    monkeypatch.setattr(optimizer, "_deterministic_time_used", work)
    plan = optimizer.optimize_transfer_plan(
        *args, TransferPlanningConfig(), protect_hold=True, phase_remaining=0.75
    )
    assert plan.has_solution and len(plan.weeks) == 3
    assert calls[0].parameters.max_deterministic_time == 0.75
    if probe_used == 0.75:
        assert len(calls) == 1
        assert plan.diagnostics["hold_protection"]["selected"] is True
    else:
        assert calls[1].parameters.max_deterministic_time == pytest.approx(0.35)
        assert all(s.parameters.max_deterministic_time <= 0.35 for s in calls[1:])


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
    policies = []

    class Routed(Exception):
        pass

    def mark(name):
        def called(*args, **kwargs):
            seen.append(name)
            policies.append(args[3])
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
    assert policies[0].allow_two_free_transfers is (route in {"football", "automatic"})
    assert policies[0].max_transfers_per_gameweek == (None if route == "one_week" else 1)
