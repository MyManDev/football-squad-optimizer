"""Native window acceptance, exact certification, fallback budgets and operator outcomes."""

import ast
import subprocess
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
from squadopt.planning.native_highs import (
    CP_SAT_BACKEND,
    NATIVE_BACKEND,
    NativeWindowOutcome,
    native_window_executor,
    native_window_outcomes,
    solve_window_model,
)
from squadopt.platform import native_windows
from squadopt.platform.native_windows import (
    execute_native_window,
    native_window_version,
    summarize_native_windows,
)


def _model(offset=7):
    model = cp_model.CpModel()
    x = model.new_int_var(0, 5, "x")
    y = model.new_int_var(0, 5, "y")
    model.add(x + y <= 6)
    model.maximize(3 * x + y + offset)
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
    # The certificate's work on the rejected witness is reported, not taken from the
    # fallback's budget.
    assert details["verification_work_before_fallback"] >= 0
    assert result.parameters.max_deterministic_time == 4.0
    assert result.parameters.max_time_in_seconds == 30.0


def test_unsupported_constraint_uses_cp_sat_without_starting_native():
    model, x, y = _model()
    model.add_all_different([x, y])

    def forbidden(packet, seconds):
        pytest.fail("unsupported models must not start the child")

    with native_window_executor(forbidden):
        result, status, details = solve_window_model(model, _solver(), solve, weeks=3)
    assert status == cp_model.OPTIMAL and result.objective_value == 23
    assert "all_diff" in details["fallback_reason"]


def test_a_native_timeout_leaves_the_fallback_its_whole_phase_budget(monkeypatch):
    """The native attempt is a phase bounded by the per-phase wall ceiling, as
    ``optimizer.py`` bounds every phase; the CP-SAT fallback then runs with its own
    unchanged wall ceiling and deterministic budget, as it would have without HiGHS."""

    now = [0.0]
    monkeypatch.setattr(native_highs, "perf_counter", lambda: now[0])
    asked = []

    def timed_out(packet, seconds):
        asked.append(seconds)
        now[0] += seconds  # the child spent the whole of its phase
        raise TimeoutError("ceiling reached")

    model, x, y = _model()
    solver = _solver()
    with native_window_executor(timed_out):
        result, status, details = solve_window_model(model, solver, solve, weeks=3)
    assert asked == [30.0]
    assert result is solver
    assert result.parameters.max_time_in_seconds == 30.0
    assert result.parameters.max_deterministic_time == 4.0
    assert status == cp_model.OPTIMAL and (result.value(x), result.value(y)) == (5, 1)
    assert details["selected"] is False and details["fallback_reason"] == "ceiling reached"


@pytest.mark.parametrize("weeks", [3, 5])
def test_a_fallback_after_a_native_timeout_plans_what_cp_sat_alone_plans(
    known_optimum_players, small_config, monkeypatch, weeks
):
    horizon, initial, config, transfer = _window(known_optimum_players, small_config, weeks)
    expected = optimize_transfer_plan(horizon, initial, config, transfer, protect_hold=True)
    now = [0.0]
    monkeypatch.setattr(native_highs, "perf_counter", lambda: now[0])

    def timed_out(packet, seconds):
        now[0] += seconds
        raise TimeoutError("ceiling reached")

    with native_window_executor(timed_out):
        actual = optimize_transfer_plan(horizon, initial, config, transfer, protect_hold=True)
    assert actual.diagnostics["solver_backend"] == "ortools-cp-sat"
    assert actual.diagnostics["native_window"]["fallback_reason"] == "ceiling reached"
    assert actual.solver_status is expected.solver_status
    for key in (
        "solver_status_name",
        "scaled_model_objective_value",
        "deterministic_time_budget_exhausted",
        "tiebreak_completed",
    ):
        assert actual.diagnostics[key] == expected.diagnostics[key], key
    _assert_same_decisions(actual, expected)


@pytest.mark.parametrize("drift", [6.17e-06, 4e-05, 0.49, -0.49])
def test_a_witness_is_accepted_on_its_exact_integer_objective(drift):
    """HiGHS reports its objective and bound as floats. At the planner's scale the #1147
    record shows them up to 6.17e-06 away from the exact value; on an integer objective
    anything within half a unit names the same integer, so the exact value is what counts."""

    exact = 173_442_000
    model, x, y = _model(offset=exact - 16)
    answer = _answer(objective=exact + drift, bound=exact + drift)
    with native_window_executor(lambda packet, seconds: answer):
        result, status, details = solve_window_model(model, _solver(), solve, weeks=5)
    assert details["selected"] is True, details.get("fallback_reason")
    assert status == cp_model.OPTIMAL
    assert (result.value(x), result.value(y), result.objective_value) == (5, 1, exact)


@pytest.mark.parametrize("drift", [0.5, -0.5, 1.0])
def test_a_bound_half_a_unit_away_does_not_prove_the_witness(drift):
    exact = 173_442_000
    model, _, _ = _model(offset=exact - 16)
    answer = _answer(objective=exact, bound=exact + drift)
    with native_window_executor(lambda packet, seconds: answer):
        result, status, details = solve_window_model(model, _solver(), solve, weeks=3)
    assert details["selected"] is False
    assert "bound" in details["fallback_reason"]
    assert status == cp_model.OPTIMAL and result.objective_value == exact


def test_the_version_is_the_one_the_child_reported():
    model, _, _ = _model()
    with native_window_executor(lambda packet, seconds: _answer(version="1.14.0")):
        _, _, details = solve_window_model(model, _solver(), solve, weeks=3)
    assert details["version"] == "1.14.0" and details["selected"] is False
    assert "1.14.0" in details["fallback_reason"] and "1.15.1" in details["fallback_reason"]

    def unavailable(packet, seconds):
        raise RuntimeError("native unavailable")

    with native_window_executor(unavailable):
        _, _, details = solve_window_model(model, _solver(), solve, weeks=3)
    assert details["version"] is None


def test_an_unproved_answer_names_the_status_highs_gave():
    model, _, _ = _model()
    answer = _answer(optimal=False, status="Time limit reached")
    with native_window_executor(lambda packet, seconds: answer):
        _, _, details = solve_window_model(model, _solver(), solve, weeks=5)
    assert details["fallback_reason"] == (
        "The native solve did not prove an optimum (HiGHS status: Time limit reached)."
    )


def test_outcomes_name_each_window_search_backend_version_and_reason():
    replies = iter([_answer(), RuntimeError("native unavailable"), _answer()])

    def execute(packet, seconds):
        reply = next(replies)
        if isinstance(reply, Exception):
            raise reply
        return reply

    model, _, _ = _model()
    with native_window_executor(execute), native_window_outcomes() as outcomes:
        solve_window_model(model, _solver(), solve, weeks=1)
        solve_window_model(model, _solver(), solve, weeks=3)
        solve_window_model(model, _solver(), solve, weeks=5)
        solve_window_model(model, _solver(), solve, weeks=5)
    assert outcomes == [
        NativeWindowOutcome(3, NATIVE_BACKEND, "1.15.1", ""),
        NativeWindowOutcome(5, CP_SAT_BACKEND, None, "native unavailable"),
        NativeWindowOutcome(5, NATIVE_BACKEND, "1.15.1", ""),
    ]
    assert summarize_native_windows(outcomes) == [
        {
            "weeks": 3,
            "solves": 1,
            "native": 1,
            "fallback": 0,
            "backends": [NATIVE_BACKEND],
            "native_versions": ["1.15.1"],
            "fallback_reasons": {},
        },
        {
            "weeks": 5,
            "solves": 2,
            "native": 1,
            "fallback": 1,
            "backends": [NATIVE_BACKEND, CP_SAT_BACKEND],
            "native_versions": ["1.15.1"],
            "fallback_reasons": {"native unavailable": 1},
        },
    ]
    # Outside the context nothing is collected, and the search is unchanged.
    with native_window_executor(lambda packet, seconds: _answer()):
        _, status, details = solve_window_model(model, _solver(), solve, weeks=3)
    assert status == cp_model.OPTIMAL and details["selected"] is True
    assert len(outcomes) == 3


def test_a_failed_child_names_the_tail_of_its_standard_error():
    # A packet without bounds makes the real child raise after it has loaded HiGHS.
    with pytest.raises(RuntimeError) as caught:
        execute_native_window({"seed": 0}, 60.0)
    message = str(caught.value)
    assert message.startswith("The isolated native window solver failed with exit code 1.")
    assert message.endswith("KeyError: 'bounds'")
    assert len(message) <= 200 + native_windows.STDERR_TAIL_CHARACTERS


def test_a_timed_out_child_names_its_ceiling_and_standard_error(monkeypatch):
    def expire(command, **kwargs):
        raise subprocess.TimeoutExpired(
            command, kwargs["timeout"], stderr=b"noise " * 500 + b"last words"
        )

    monkeypatch.setattr(native_windows.subprocess, "run", expire)
    with pytest.raises(TimeoutError) as caught:
        execute_native_window({}, 12.5)
    message = str(caught.value)
    assert message.startswith("The native window reached its wall ceiling of 12.5s.")
    assert message.endswith("noise last words")
    assert len(message) <= 200 + native_windows.STDERR_TAIL_CHARACTERS


def test_the_probe_reports_the_highs_this_environment_loads():
    assert native_window_version() == "1.15.1"


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


def _window(players, small_config, weeks):
    table = pd.concat(
        [players.assign(gameweek=week) for week in range(1, weeks + 1)],
        ignore_index=True,
    )
    table["buy_price_tenths"] = table["price_tenths"]
    table["sell_price_tenths"] = table["price_tenths"]
    horizon = PlanningHorizon(table)
    initial = InitialSquadState(("GK_A", "DEF_A", "MID_A", "FWD_A"), 0, 1)
    config = replace(small_config, solver_time_limit_seconds=30, solver_deterministic_time_limit=4)
    return horizon, initial, config, TransferPlanningConfig(acquisition_sell_on_fee=0.5)


def _assert_same_decisions(actual, expected):
    for left, right in zip(actual.weeks, expected.weeks, strict=True):
        assert set(left.selected_squad.player_id) == set(right.selected_squad.player_id)
        assert set(left.starting_xi.player_id) == set(right.starting_xi.player_id)
        assert left.captain["player_id"] == right.captain["player_id"]
        assert left.bench.player_id.tolist() == right.bench.player_id.tolist()


@pytest.mark.parametrize("weeks", [3, 5])
@pytest.mark.parametrize("chip", [False, True])
def test_complete_window_keeps_cp_sat_tiebreak_and_decisions(
    known_optimum_players, small_config, weeks, chip
):
    horizon, initial, config, transfer = _window(known_optimum_players, small_config, weeks)
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
    _assert_same_decisions(actual, expected)
