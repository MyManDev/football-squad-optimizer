"""The public CP-SAT driver, and the private names its consumers keep bound to it.

ADR 0011 (decision 5) moved the driver out of `optimization.optimizer` into
`optimization.cpsat`, the tie-break objective into `optimization.decisions` and the empty
result into `optimization.models`, bodies unchanged. Each consumer binds the public names to
the module-level private names it had, so the test files that patch `_solve`,
`_deterministic_time_used` or `configure_solver` on `planning.optimizer`,
`scenarios.optimization` or `optimization.optimizer` keep their seams. The identity checks
here hold that binding; the rest pins the driver's own answers at its new address.
"""

from types import ModuleType

import pandas as pd
import pytest
from ortools.sat.python import cp_model

from squadopt.evaluation import benchmarks
from squadopt.optimization import (
    OptimizationConfig,
    SolverExecutionError,
    SolverStatus,
    cpsat,
    decisions,
    models,
)
from squadopt.optimization import optimizer as squad_optimizer
from squadopt.planning import optimizer as planning_optimizer
from squadopt.scenarios import optimization as scenario_optimization
from squadopt.scenarios import rank as scenario_rank

DRIVER_CONSUMERS = (squad_optimizer, planning_optimizer, scenario_optimization, scenario_rank)
TIEBREAK_CONSUMERS = (squad_optimizer, scenario_optimization, scenario_rank)


def _name(module: ModuleType) -> str:
    return module.__name__.removeprefix("squadopt.")


@pytest.mark.parametrize("consumer", DRIVER_CONSUMERS, ids=_name)
def test_each_consumer_binds_its_private_driver_names_to_the_public_driver(
    consumer: ModuleType,
) -> None:
    assert consumer._solve is cpsat.solve
    assert consumer._map_solver_status is cpsat.map_solver_status
    assert consumer._raw_status_name is cpsat.raw_status_name
    assert consumer._deterministic_time_used is cpsat.deterministic_time_used
    assert consumer._remaining_deterministic_time is cpsat.remaining_deterministic_time
    assert consumer.configure_solver is cpsat.configure_solver
    assert consumer.CP_SAT_SAFE_INTEGER_MAX is cpsat.CP_SAT_SAFE_INTEGER_MAX
    assert consumer.MIN_TIEBREAK_DETERMINISTIC_TIME is cpsat.MIN_TIEBREAK_DETERMINISTIC_TIME


@pytest.mark.parametrize("consumer", TIEBREAK_CONSUMERS, ids=_name)
def test_the_tie_break_and_the_empty_result_are_the_shared_ones(consumer: ModuleType) -> None:
    assert consumer._add_tiebreak_objective is decisions.add_tiebreak_objective
    assert consumer._empty_result is models.empty_result
    assert consumer.MIN_TIEBREAK_TIME_SECONDS is cpsat.MIN_TIEBREAK_TIME_SECONDS


def test_the_optimizer_keeps_the_names_the_benchmarks_scripts_and_protocols_read() -> None:
    assert benchmarks.configure_solver is cpsat.configure_solver
    assert squad_optimizer.wall_clock_stopped_the_search.__module__ == squad_optimizer.__name__
    assert cpsat.CP_SAT_SAFE_INTEGER_MAX == (1 << 62) - 1
    assert cpsat.MIN_TIEBREAK_TIME_SECONDS == 0.001
    assert cpsat.MIN_TIEBREAK_DETERMINISTIC_TIME == 1e-9


@pytest.mark.parametrize(
    ("raw_status", "name"),
    [
        (cp_model.OPTIMAL, "OPTIMAL"),
        (cp_model.FEASIBLE, "FEASIBLE"),
        (cp_model.INFEASIBLE, "INFEASIBLE"),
        (cp_model.UNKNOWN, "UNKNOWN"),
        (cp_model.MODEL_INVALID, "MODEL_INVALID"),
        (999, "UNRECOGNIZED(999)"),
    ],
)
def test_raw_status_names(raw_status: int, name: str) -> None:
    assert cpsat.raw_status_name(int(raw_status)) == name


def test_an_unrecognized_status_is_an_execution_error() -> None:
    with pytest.raises(SolverExecutionError, match="unrecognized status: 999"):
        cpsat.map_solver_status(999)


@pytest.mark.parametrize(
    ("configured_limit", "consumed", "remaining"),
    [(None, 3.0, None), (2.0, 0.5, 1.5), (1.0, 2.0, 0.0)],
)
def test_the_remaining_deterministic_budget_never_goes_below_zero(
    configured_limit: float | None,
    consumed: float,
    remaining: float | None,
) -> None:
    assert cpsat.remaining_deterministic_time(configured_limit, consumed) == remaining


def test_work_before_any_response_is_zero_only_for_an_unknown_status() -> None:
    solver = cp_model.CpSolver()

    assert cpsat.deterministic_time_used(solver, cp_model.UNKNOWN) == 0.0
    with pytest.raises(SolverExecutionError, match="without response diagnostics"):
        cpsat.deterministic_time_used(solver, cp_model.OPTIMAL)


def test_solve_refuses_a_model_cp_sat_rejects() -> None:
    model = cp_model.CpModel()
    model.new_int_var(5, 1, "empty_domain")

    with pytest.raises(SolverExecutionError, match="rejected the generated model"):
        cpsat.solve(model, cp_model.CpSolver())


def test_a_configured_solver_runs_one_seeded_worker_within_both_budgets(
    small_config: OptimizationConfig,
) -> None:
    model = cp_model.CpModel()
    chosen = model.new_bool_var("chosen")
    model.maximize(chosen)
    solver = cp_model.CpSolver()

    cpsat.configure_solver(solver, small_config, 1.5, 0.25)
    raw_status = cpsat.solve(model, solver)

    assert solver.parameters.num_search_workers == 1
    assert solver.parameters.random_seed == small_config.deterministic_seed
    assert solver.parameters.max_time_in_seconds == 1.5
    assert solver.parameters.max_deterministic_time == 0.25
    assert cpsat.map_solver_status(raw_status) is SolverStatus.OPTIMAL
    assert cpsat.deterministic_time_used(solver, raw_status) >= 0.0


def test_the_tie_break_pins_the_primary_value_and_prefers_the_lowest_ranks(
    small_config: OptimizationConfig,
) -> None:
    model = cp_model.CpModel()
    squad_vars = [model.new_bool_var(f"squad_{index}") for index in range(4)]
    starter_vars = [model.new_bool_var(f"starter_{index}") for index in range(4)]
    captain_vars = [model.new_bool_var(f"captain_{index}") for index in range(4)]
    primary_objective = cp_model.LinearExpr.sum(squad_vars)
    model.maximize(primary_objective)

    decisions.add_tiebreak_objective(
        model, squad_vars, starter_vars, captain_vars, primary_objective, small_config, 2
    )
    solver = cp_model.CpSolver()

    assert cpsat.map_solver_status(cpsat.solve(model, solver)) is SolverStatus.OPTIMAL
    assert [solver.value(variable) for variable in squad_vars] == [1, 1, 0, 0]
    assert sum(solver.value(variable) for variable in starter_vars + captain_vars) == 0


def test_the_empty_result_has_no_solution_and_keeps_the_pool_columns(
    known_optimum_players: pd.DataFrame,
) -> None:
    result = models.empty_result(known_optimum_players, SolverStatus.INFEASIBLE, {"why": "test"})

    assert not result.has_solution
    assert result.solver_status is SolverStatus.INFEASIBLE
    for frame in (result.selected_squad, result.starting_xi, result.bench):
        assert frame.empty
        assert list(frame.columns) == list(known_optimum_players.columns)
    assert result.captain is None
    assert result.total_cost_tenths is None
    assert result.projected_score is None
    assert result.objective_value is None
    assert dict(result.diagnostics) == {"why": "test"}
