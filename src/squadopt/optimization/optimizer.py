"""OR-Tools CP-SAT implementation of the baseline squad optimizer."""

from collections import Counter, defaultdict
from dataclasses import dataclass
from decimal import Decimal
from time import perf_counter

import pandas as pd
from ortools.sat.python import cp_model

from squadopt.optimization.coefficients import (
    objective_coefficients,
    scale_bench_coefficient,
    scale_expected_points,
    sort_players_by_id,
)
from squadopt.optimization.config import POSITIONS, OptimizationConfig
from squadopt.optimization.models import (
    InvalidConfigurationError,
    OptimizationResult,
    SolverExecutionError,
    SolverStatus,
)
from squadopt.optimization.validation import validate_players

CP_SAT_SAFE_INTEGER_MAX = (1 << 62) - 1
MIN_TIEBREAK_TIME_SECONDS = 0.001


def _scale_expected_points(value: object, scale: int) -> int:
    """Backward-compatible private alias for the shared scaling contract."""

    return scale_expected_points(value, scale)


def _scale_bench_coefficient(scaled_points: int, bench_weight: float) -> int:
    """Backward-compatible private alias for the shared scaling contract."""

    return scale_bench_coefficient(scaled_points, bench_weight)


@dataclass(frozen=True, slots=True)
class _ModelArtifacts:
    model: cp_model.CpModel
    squad_vars: list[cp_model.IntVar]
    starter_vars: list[cp_model.IntVar]
    captain_vars: list[cp_model.IntVar]
    primary_objective: cp_model.LinearExpr
    scaled_points: list[int]
    bench_coefficients: list[int]


def _build_model(players: pd.DataFrame, config: OptimizationConfig) -> _ModelArtifacts:
    model = cp_model.CpModel()
    player_count = len(players)
    squad_vars = [model.new_bool_var(f"squad_{index}") for index in range(player_count)]
    starter_vars = [model.new_bool_var(f"starter_{index}") for index in range(player_count)]
    captain_vars = [model.new_bool_var(f"captain_{index}") for index in range(player_count)]

    coefficients = objective_coefficients(players["expected_points"].tolist(), config)
    bench_coefficients = [coefficient[0] for coefficient in coefficients]
    scaled_points = [coefficient[2] for coefficient in coefficients]
    conservative_objective_bound = sum(
        2 * points + bench for points, bench in zip(scaled_points, bench_coefficients, strict=True)
    )
    if conservative_objective_bound > CP_SAT_SAFE_INTEGER_MAX:
        raise SolverExecutionError(
            "Scaled expected-points coefficients exceed the safe CP-SAT integer range; "
            "reduce expected_points_scale or inspect projection magnitudes."
        )

    model.add(cp_model.LinearExpr.sum(squad_vars) == config.squad_size)
    model.add(cp_model.LinearExpr.sum(starter_vars) == config.starting_size)
    model.add(cp_model.LinearExpr.sum(captain_vars) == 1)

    for index in range(player_count):
        model.add(starter_vars[index] <= squad_vars[index])
        model.add(captain_vars[index] <= starter_vars[index])

    positions = players["position"].tolist()
    for position in POSITIONS:
        indices = [index for index, value in enumerate(positions) if value == position]
        squad_expression = cp_model.LinearExpr.sum([squad_vars[index] for index in indices])
        starter_expression = cp_model.LinearExpr.sum([starter_vars[index] for index in indices])
        model.add(squad_expression == config.squad_position_limits[position])
        model.add(starter_expression >= config.starting_position_min[position])
        model.add(starter_expression <= config.starting_position_max[position])

    team_indices: defaultdict[object, list[int]] = defaultdict(list)
    for index, team_id in enumerate(players["team_id"].tolist()):
        team_indices[team_id].append(index)
    for indices in team_indices.values():
        model.add(
            cp_model.LinearExpr.sum([squad_vars[index] for index in indices])
            <= config.max_players_per_team
        )

    prices = [int(value) for value in players["price_tenths"].tolist()]
    model.add(cp_model.LinearExpr.weighted_sum(squad_vars, prices) <= config.budget_tenths)

    primary_terms: list[cp_model.LinearExpr] = []
    for index, (points, bench) in enumerate(zip(scaled_points, bench_coefficients, strict=True)):
        primary_terms.extend(
            (
                bench * squad_vars[index],
                (points - bench) * starter_vars[index],
                points * captain_vars[index],
            )
        )
    primary_objective = cp_model.LinearExpr.sum(primary_terms)
    model.maximize(primary_objective)

    return _ModelArtifacts(
        model=model,
        squad_vars=squad_vars,
        starter_vars=starter_vars,
        captain_vars=captain_vars,
        primary_objective=primary_objective,
        scaled_points=scaled_points,
        bench_coefficients=bench_coefficients,
    )


def _raw_status_name(raw_status: int) -> str:
    names: dict[int, str] = {
        int(cp_model.OPTIMAL): "OPTIMAL",
        int(cp_model.FEASIBLE): "FEASIBLE",
        int(cp_model.INFEASIBLE): "INFEASIBLE",
        int(cp_model.UNKNOWN): "UNKNOWN",
        int(cp_model.MODEL_INVALID): "MODEL_INVALID",
    }
    return names.get(raw_status, f"UNRECOGNIZED({raw_status})")


def _map_solver_status(raw_status: int) -> SolverStatus:
    """Map a CP-SAT status to the solver-independent public status."""

    if raw_status == cp_model.OPTIMAL:
        return SolverStatus.OPTIMAL
    if raw_status == cp_model.FEASIBLE:
        return SolverStatus.FEASIBLE
    if raw_status == cp_model.INFEASIBLE:
        return SolverStatus.INFEASIBLE
    if raw_status == cp_model.UNKNOWN:
        return SolverStatus.UNKNOWN
    if raw_status == cp_model.MODEL_INVALID:
        raise SolverExecutionError("CP-SAT rejected the generated model as invalid.")
    raise SolverExecutionError(f"CP-SAT returned an unrecognized status: {raw_status!r}.")


def _configure_solver(
    solver: cp_model.CpSolver,
    config: OptimizationConfig,
    time_limit_seconds: float,
) -> None:
    solver.parameters.max_time_in_seconds = time_limit_seconds
    solver.parameters.num_search_workers = 1
    solver.parameters.random_seed = config.deterministic_seed


def _solve(model: cp_model.CpModel, solver: cp_model.CpSolver) -> int:
    validation_message = model.validate()
    if validation_message:
        raise SolverExecutionError(f"CP-SAT rejected the generated model: {validation_message}")
    try:
        return int(solver.solve(model))
    except Exception as error:
        raise SolverExecutionError("CP-SAT failed while solving the squad model.") from error


def _evaluate_primary(
    solver: cp_model.CpSolver,
    artifacts: _ModelArtifacts,
) -> int:
    return sum(
        points
        * (
            solver.value(artifacts.starter_vars[index])
            + solver.value(artifacts.captain_vars[index])
        )
        + bench
        * (solver.value(artifacts.squad_vars[index]) - solver.value(artifacts.starter_vars[index]))
        for index, (points, bench) in enumerate(
            zip(artifacts.scaled_points, artifacts.bench_coefficients, strict=True)
        )
    )


def _add_tiebreak_objective(
    artifacts: _ModelArtifacts,
    config: OptimizationConfig,
    primary_value: int,
) -> None:
    player_count = len(artifacts.squad_vars)
    largest_rank = max(0, player_count - 1)
    max_squad_rank_sum = config.squad_size * largest_rank
    max_starter_rank_sum = config.starting_size * largest_rank
    starter_weight = max_squad_rank_sum + 1
    captain_weight = starter_weight * (max_starter_rank_sum + 1)
    conservative_tiebreak_bound = (
        captain_weight * largest_rank + starter_weight * max_starter_rank_sum + max_squad_rank_sum
    )
    if conservative_tiebreak_bound > CP_SAT_SAFE_INTEGER_MAX:
        raise SolverExecutionError(
            "Deterministic tie-break coefficients exceed the safe CP-SAT integer range."
        )

    artifacts.model.add(artifacts.primary_objective == primary_value)
    tiebreak_terms: list[cp_model.LinearExpr] = []
    for rank in range(player_count):
        tiebreak_terms.extend(
            (
                rank * artifacts.squad_vars[rank],
                starter_weight * rank * artifacts.starter_vars[rank],
                captain_weight * rank * artifacts.captain_vars[rank],
            )
        )
    artifacts.model.minimize(cp_model.LinearExpr.sum(tiebreak_terms))


def _selected_indices(
    solver: cp_model.CpSolver,
    variables: list[cp_model.IntVar],
) -> list[int]:
    return [index for index, variable in enumerate(variables) if solver.value(variable) == 1]


def _verify_solution(
    players: pd.DataFrame,
    config: OptimizationConfig,
    squad_indices: list[int],
    starter_indices: list[int],
    captain_indices: list[int],
) -> None:
    squad_set = set(squad_indices)
    starter_set = set(starter_indices)
    captain_set = set(captain_indices)

    failures: list[str] = []
    if len(squad_indices) != config.squad_size:
        failures.append("squad size")
    if len(starter_indices) != config.starting_size:
        failures.append("starting size")
    if len(captain_indices) != 1:
        failures.append("captain count")
    if not starter_set <= squad_set:
        failures.append("starter/squad relation")
    if not captain_set <= starter_set:
        failures.append("captain/starter relation")

    for position in POSITIONS:
        squad_count = sum(players.iloc[index]["position"] == position for index in squad_indices)
        starter_count = sum(
            players.iloc[index]["position"] == position for index in starter_indices
        )
        if squad_count != config.squad_position_limits[position]:
            failures.append(f"{position} squad quota")
        if not (
            config.starting_position_min[position]
            <= starter_count
            <= config.starting_position_max[position]
        ):
            failures.append(f"{position} starting bounds")

    total_cost = sum(int(players.iloc[index]["price_tenths"]) for index in squad_indices)
    if total_cost > config.budget_tenths:
        failures.append("budget")

    team_counts = Counter(players.iloc[index]["team_id"] for index in squad_indices)
    if any(count > config.max_players_per_team for count in team_counts.values()):
        failures.append("team limit")

    if failures:
        raise SolverExecutionError(
            "CP-SAT returned a solution that failed internal verification: "
            + ", ".join(failures)
            + "."
        )


def _empty_result(
    players: pd.DataFrame,
    status: SolverStatus,
    diagnostics: dict[str, object],
) -> OptimizationResult:
    empty = players.iloc[0:0].reset_index(drop=True).copy(deep=True)
    return OptimizationResult(
        solver_status=status,
        selected_squad=empty.copy(deep=True),
        starting_xi=empty.copy(deep=True),
        bench=empty.copy(deep=True),
        captain=None,
        total_cost_tenths=None,
        projected_score=None,
        objective_value=None,
        diagnostics=diagnostics,
    )


def optimize_squad(
    players: pd.DataFrame,
    config: OptimizationConfig,
) -> OptimizationResult:
    """Select a squad, starting XI, bench, and captain for one gameweek."""

    if not isinstance(config, OptimizationConfig):
        raise InvalidConfigurationError("config must be an OptimizationConfig instance.")

    validated = validate_players(players, config)
    ordered_players = sort_players_by_id(validated)
    artifacts = _build_model(ordered_players, config)
    started_at = perf_counter()
    deadline = started_at + config.solver_time_limit_seconds

    primary_solver = cp_model.CpSolver()
    _configure_solver(primary_solver, config, config.solver_time_limit_seconds)
    raw_primary_status = _solve(artifacts.model, primary_solver)
    primary_status = _map_solver_status(raw_primary_status)
    elapsed_after_primary = perf_counter() - started_at

    base_diagnostics: dict[str, object] = {
        "solver_backend": "ortools-cp-sat",
        "solver_status_name": _raw_status_name(raw_primary_status),
        "solve_time_seconds": elapsed_after_primary,
        "best_objective_bound": None,
        "absolute_optimality_gap": None,
        "relative_optimality_gap": None,
        "expected_points_scale": config.expected_points_scale,
        "bench_weight": config.bench_weight,
        "input_player_count": len(ordered_players),
        "deterministic_seed": config.deterministic_seed,
        "num_search_workers": 1,
        "rounding_mode": "ROUND_HALF_UP",
        "tiebreak_attempted": False,
        "tiebreak_status": None,
        "tiebreak_completed": False,
    }

    if primary_status in {SolverStatus.INFEASIBLE, SolverStatus.UNKNOWN}:
        return _empty_result(ordered_players, primary_status, base_diagnostics)

    primary_value = _evaluate_primary(primary_solver, artifacts)
    objective_value = primary_value / config.expected_points_scale
    raw_best_bound = float(primary_solver.best_objective_bound)
    best_bound = raw_best_bound / config.expected_points_scale
    if primary_status is SolverStatus.OPTIMAL:
        absolute_gap = 0.0
        relative_gap = 0.0
    else:
        absolute_gap = max(0.0, best_bound - objective_value)
        relative_gap = absolute_gap / max(1.0, abs(objective_value))

    result_solver = primary_solver
    remaining_time = deadline - perf_counter()
    if primary_status is SolverStatus.OPTIMAL and remaining_time > MIN_TIEBREAK_TIME_SECONDS:
        base_diagnostics["tiebreak_attempted"] = True
        _add_tiebreak_objective(artifacts, config, primary_value)
        tiebreak_solver = cp_model.CpSolver()
        _configure_solver(tiebreak_solver, config, remaining_time)
        raw_tiebreak_status = _solve(artifacts.model, tiebreak_solver)
        tiebreak_status = _map_solver_status(raw_tiebreak_status)
        base_diagnostics["tiebreak_status"] = _raw_status_name(raw_tiebreak_status)
        if tiebreak_status in {SolverStatus.OPTIMAL, SolverStatus.FEASIBLE}:
            result_solver = tiebreak_solver
            base_diagnostics["tiebreak_completed"] = tiebreak_status is SolverStatus.OPTIMAL
        elif tiebreak_status is SolverStatus.INFEASIBLE:
            raise SolverExecutionError(
                "The tie-break model became infeasible after fixing the proven primary optimum."
            )

    squad_indices = _selected_indices(result_solver, artifacts.squad_vars)
    starter_indices = _selected_indices(result_solver, artifacts.starter_vars)
    captain_indices = _selected_indices(result_solver, artifacts.captain_vars)
    _verify_solution(
        ordered_players,
        config,
        squad_indices,
        starter_indices,
        captain_indices,
    )

    squad_set = set(squad_indices)
    starter_set = set(starter_indices)
    bench_indices = sorted(squad_set - starter_set)
    selected_squad = ordered_players.iloc[squad_indices].reset_index(drop=True).copy(deep=True)
    starting_xi = ordered_players.iloc[starter_indices].reset_index(drop=True).copy(deep=True)
    bench = ordered_players.iloc[bench_indices].reset_index(drop=True).copy(deep=True)
    captain = ordered_players.iloc[captain_indices[0]].copy(deep=True)
    captain.name = None

    total_cost = sum(int(ordered_players.iloc[index]["price_tenths"]) for index in squad_indices)
    projected_score_decimal = Decimal(0)
    for index in starter_indices:
        projected_score_decimal += Decimal(str(ordered_players.iloc[index]["expected_points"]))
    projected_score_decimal += Decimal(
        str(ordered_players.iloc[captain_indices[0]]["expected_points"])
    )

    base_diagnostics.update(
        {
            "solve_time_seconds": perf_counter() - started_at,
            "best_objective_bound": best_bound,
            "absolute_optimality_gap": absolute_gap,
            "relative_optimality_gap": relative_gap,
        }
    )
    return OptimizationResult(
        solver_status=primary_status,
        selected_squad=selected_squad,
        starting_xi=starting_xi,
        bench=bench,
        captain=captain,
        total_cost_tenths=total_cost,
        projected_score=float(projected_score_decimal),
        objective_value=objective_value,
        diagnostics=base_diagnostics,
    )
