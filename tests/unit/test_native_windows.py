"""Native window acceptance, exact certification and bounded fallback."""

import ast
from dataclasses import replace
from pathlib import Path

import pandas as pd
import pytest
from ortools.sat.python import cp_model

from squadopt.optimization import OptimizationConfig
from squadopt.optimization.cpsat import configure_solver, solve
from squadopt.planning import (
    ChipAvailability,
    InitialSquadState,
    PlanningHorizon,
    TransferPlanningConfig,
    native_highs,
    optimize_transfer_plan,
)
from squadopt.planning.native_highs import native_window_executor, solve_window_model
from squadopt.platform.native_windows import execute_native_window


def _model():
    model = cp_model.CpModel()
    x = model.new_int_var(0, 5, "x")
    y = model.new_int_var(0, 5, "y")
    model.add(x + y <= 6)
    model.maximize(3 * x + y + 7)
    return model, x, y


def _solver():
    solver = cp_model.CpSolver()
    configure_solver(solver, OptimizationConfig(), 30.0, 4.0)
    return solver


def _answer(**changes):
    return (
        dict(
            version="1.15.1", threads=1, optimal=True, values=[5.0, 1.0], objective=23.0, bound=23.0
        )
        | changes
    )


@pytest.mark.parametrize("weeks", [3, 5])
def test_actual_native_process_proves_and_certifies_original_model(weeks):
    model, x, y = _model()
    with native_window_executor(execute_native_window):
        result, status, details = solve_window_model(model, _solver(), solve, weeks=weeks)
    assert status == cp_model.OPTIMAL
    assert (result.value(x), result.value(y), result.objective_value) == (5, 1, 23)
    assert details["selected"] is True
    assert details["version"] == "1.15.1"


def test_context_and_one_week_do_not_invoke_native():
    calls = []

    def execute(packet, seconds):
        calls.append(seconds)
        return _answer()

    model, _, _ = _model()
    with native_window_executor(execute):
        _, status, details = solve_window_model(model, _solver(), solve, weeks=1)
        assert status == cp_model.OPTIMAL and details == {}
        assert calls == []
        solve_window_model(model, _solver(), solve, weeks=3)
    _, _, details = solve_window_model(model, _solver(), solve, weeks=3)
    assert len(calls) == 1 and details == {}


@pytest.mark.parametrize(
    "changes",
    [
        {"version": "1.15.0"},
        {"threads": 2},
        {"optimal": False},
        {"values": [5]},
        {"values": [4.5, 1]},
        {"values": [float("nan"), 1]},
        {"values": [6, 0]},
        {"values": [5, 2]},
        {"objective": 22},
        {"bound": 23.5},
        {"bound": float("inf")},
    ],
)
def test_unproved_or_invalid_native_witness_falls_back(changes):
    model, x, y = _model()
    with native_window_executor(lambda packet, seconds: _answer(**changes)):
        result, status, details = solve_window_model(model, _solver(), solve, weeks=3)
    assert status == cp_model.OPTIMAL
    assert (result.value(x), result.value(y)) == (5, 1)
    assert details["selected"] is False
    assert details["fallback_reason"]


def test_native_failure_preserves_cp_sat_fallback():
    def unavailable(packet, seconds):
        raise RuntimeError("native unavailable")

    model, x, y = _model()
    with native_window_executor(unavailable):
        result, status, details = solve_window_model(model, _solver(), solve, weeks=5)
    assert status == cp_model.OPTIMAL and (result.value(x), result.value(y)) == (5, 1)
    assert details["fallback_reason"] == "native unavailable"


def test_original_cp_model_catches_a_bad_exporter(monkeypatch):
    original = native_highs.export_milp

    def broken(proto):
        model = original(proto)
        model.rows.clear()
        return model

    monkeypatch.setattr(native_highs, "export_milp", broken)
    model, x, y = _model()
    with native_window_executor(
        lambda packet, seconds: _answer(values=[5, 5], objective=27, bound=27)
    ):
        result, status, details = solve_window_model(model, _solver(), solve, weeks=3)
    assert status == cp_model.OPTIMAL and (result.value(x), result.value(y)) == (5, 1)
    assert "verification" in details["fallback_reason"]


def test_unsupported_constraint_uses_cp_sat_without_starting_native():
    model, x, y = _model()
    model.add_all_different([x, y])

    def forbidden(packet, seconds):
        pytest.fail("unsupported models must not start the child")

    with native_window_executor(forbidden):
        result, status, details = solve_window_model(model, _solver(), solve, weeks=3)
    assert status == cp_model.OPTIMAL and result.objective_value == 23
    assert "all_diff" in details["fallback_reason"]


def test_native_timeout_cannot_add_another_full_wall_budget(monkeypatch):
    now = [0.0]
    monkeypatch.setattr(native_highs, "perf_counter", lambda: now[0])

    def timed_out(packet, seconds):
        assert seconds == 30
        now[0] = 30.0
        raise TimeoutError("ceiling reached")

    model, _, _ = _model()
    with native_window_executor(timed_out):
        result, status, details = solve_window_model(model, _solver(), solve, weeks=3)
    assert result.parameters.max_time_in_seconds == 0
    assert status == cp_model.UNKNOWN
    assert details["selected"] is False


def test_native_translation_handles_enforcement_maximum_and_element():
    model = cp_model.CpModel()
    x = model.new_int_var(0, 3, "x")
    y = model.new_int_var(0, 9, "y")
    maximum = model.new_int_var(0, 9, "max")
    active = model.new_bool_var("active")
    model.add_element(x, [3, 5, 9, 7], y)
    model.add_max_equality(maximum, [x, y])
    model.add(x <= 2).only_enforce_if(active)
    model.add_bool_or([active])
    model.maximize(10 * maximum - x)
    with native_window_executor(execute_native_window):
        result, status, details = solve_window_model(model, _solver(), solve, weeks=3)
    assert status == cp_model.OPTIMAL and result.objective_value == 88
    assert (result.value(x), result.value(y), result.value(maximum)) == (2, 9, 9)
    assert details["selected"] is True


def test_only_the_planning_driver_imports_highspy():
    root = Path(__file__).resolve().parents[2] / "src" / "squadopt"
    importers = set()
    for path in root.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            names = (
                [node.module]
                if isinstance(node, ast.ImportFrom)
                else [alias.name for alias in node.names]
                if isinstance(node, ast.Import)
                else []
            )
            if any(name and name.split(".")[0] == "highspy" for name in names):
                importers.add(path.relative_to(root).as_posix())
    assert importers == {"planning/native_highs.py"}


@pytest.mark.parametrize("weeks", [3, 5])
@pytest.mark.parametrize("chip", [False, True])
def test_complete_window_keeps_cp_sat_tiebreak_and_decisions(
    known_optimum_players, small_config, weeks, chip
):
    table = pd.concat(
        [known_optimum_players.assign(gameweek=week) for week in range(1, weeks + 1)],
        ignore_index=True,
    )
    table["buy_price_tenths"] = table["price_tenths"]
    table["sell_price_tenths"] = table["price_tenths"]
    horizon = PlanningHorizon(table)
    initial = InitialSquadState(("GK_A", "DEF_A", "MID_A", "FWD_A"), 0, 1)
    config = replace(small_config, solver_time_limit_seconds=30, solver_deterministic_time_limit=4)
    transfer = TransferPlanningConfig(acquisition_sell_on_fee=0.5)
    rights = ChipAvailability({"wildcard": {1, 2}}) if chip else ChipAvailability()
    expected = optimize_transfer_plan(
        horizon, initial, config, transfer, chips=rights, protect_hold=True
    )
    with native_window_executor(execute_native_window):
        actual = optimize_transfer_plan(
            horizon, initial, config, transfer, chips=rights, protect_hold=True
        )
    assert actual.diagnostics["solver_backend"] == "highs-native"
    assert actual.diagnostics["native_window"]["selected"] is True
    assert actual.diagnostics["tiebreak_backend"] == "ortools-cp-sat"
    assert actual.diagnostics["tiebreak_completed"] is True
    assert (
        actual.diagnostics["scaled_model_objective_value"]
        == expected.diagnostics["scaled_model_objective_value"]
    )
    for left, right in zip(actual.weeks, expected.weeks, strict=True):
        assert set(left.selected_squad.player_id) == set(right.selected_squad.player_id)
        assert set(left.starting_xi.player_id) == set(right.starting_xi.player_id)
        assert left.captain["player_id"] == right.captain["player_id"]
        assert left.bench.player_id.tolist() == right.bench.player_id.tolist()
