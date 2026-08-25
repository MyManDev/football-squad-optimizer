"""Joint-scenario CP-SAT optimization with an empirical lower-tail CVaR objective."""

import math
from decimal import ROUND_HALF_UP, Decimal
from time import perf_counter

import pandas as pd
from ortools.sat.python import cp_model

from squadopt.optimization import (
    OptimizationConfig,
    OptimizationResult,
    SolverExecutionError,
    SolverStatus,
)
from squadopt.optimization.coefficients import scale_expected_points, sort_players_by_id
from squadopt.optimization.optimizer import (
    CP_SAT_SAFE_INTEGER_MAX,
    MIN_TIEBREAK_DETERMINISTIC_TIME,
    MIN_TIEBREAK_TIME_SECONDS,
    _add_decision_constraints,
    _add_tiebreak_objective,
    _deterministic_time_used,
    _empty_result,
    _map_solver_status,
    _raw_status_name,
    _remaining_deterministic_time,
    _selected_indices,
    _solve,
    _verify_solution,
    configure_solver,
)
from squadopt.optimization.validation import validate_players
from squadopt.scenarios.evaluation import evaluate_fixed_decision
from squadopt.scenarios.models import (
    ScenarioConfigurationError,
    ScenarioEvaluationConfig,
    ScenarioOptimizationConfig,
    ScenarioOptimizationResult,
    ScenarioSet,
    ScenarioValidationError,
)


def _scaled_weight(value: float, scale: int) -> int:
    return int(
        (Decimal(str(value)) * scale).quantize(
            Decimal("1"),
            rounding=ROUND_HALF_UP,
        )
    )


def _scenario_expressions(
    model: cp_model.CpModel,
    scaled_rows: list[list[int]],
    starter_vars: list[cp_model.IntVar],
    captain_vars: list[cp_model.IntVar],
    squad_vars: list[cp_model.IntVar],
    *,
    risk_weight: int,
) -> tuple[
    list[cp_model.LinearExpr],
    list[cp_model.LinearExpr],
    cp_model.IntVar | None,
    list[cp_model.IntVar],
]:
    actual_scores: list[cp_model.LinearExpr] = []
    bench_scores: list[cp_model.LinearExpr] = []
    for row in scaled_rows:
        actual_terms: list[cp_model.LinearExpr] = []
        bench_terms: list[cp_model.LinearExpr] = []
        for player_index, points in enumerate(row):
            actual_terms.extend(
                (
                    points * starter_vars[player_index],
                    points * captain_vars[player_index],
                )
            )
            bench_terms.extend(
                (
                    points * squad_vars[player_index],
                    -points * starter_vars[player_index],
                )
            )
        actual_scores.append(cp_model.LinearExpr.sum(actual_terms))
        bench_scores.append(cp_model.LinearExpr.sum(bench_terms))

    if risk_weight == 0:
        return actual_scores, bench_scores, None, []

    score_bound = max((2 * sum(abs(points) for points in row) for row in scaled_rows), default=0)
    eta = model.new_int_var(-score_bound, score_bound, "cvar_eta")
    shortfalls: list[cp_model.IntVar] = []
    for scenario_index, score in enumerate(actual_scores):
        shortfall = model.new_int_var(0, 2 * score_bound, f"cvar_shortfall_{scenario_index}")
        model.add(shortfall >= eta - score)
        shortfalls.append(shortfall)
    return actual_scores, bench_scores, eta, shortfalls


def _validate_objective_bound(
    scaled_rows: list[list[int]],
    *,
    scenario_count: int,
    tail_count: int,
    weight_scale: int,
    risk_weight: int,
    bench_weight: int,
) -> None:
    """Reject an unsafe model before constructing CP-SAT integer expressions."""

    actual_bounds = [2 * sum(abs(points) for points in row) for row in scaled_rows]
    bench_bounds = [sum(abs(points) for points in row) for row in scaled_rows]
    score_bound = max(actual_bounds, default=0)
    expected_weight = weight_scale - risk_weight
    conservative_bound = (
        expected_weight * tail_count * sum(actual_bounds)
        + bench_weight * tail_count * sum(bench_bounds)
        + risk_weight * scenario_count * tail_count * score_bound
        + risk_weight * scenario_count * scenario_count * 2 * score_bound
    )
    if conservative_bound > CP_SAT_SAFE_INTEGER_MAX:
        raise SolverExecutionError(
            "Scenario objective exceeds the safe CP-SAT integer range; reduce the scenario "
            "count, expected_points_scale, or objective_weight_scale."
        )


def _objective_expression(
    actual_scores: list[cp_model.LinearExpr],
    bench_scores: list[cp_model.LinearExpr],
    eta: cp_model.IntVar | None,
    shortfalls: list[cp_model.IntVar],
    *,
    scenario_count: int,
    tail_count: int,
    weight_scale: int,
    risk_weight: int,
    bench_weight: int,
) -> cp_model.LinearExpr:
    expected_weight = weight_scale - risk_weight
    terms: list[cp_model.LinearExpr] = [
        expected_weight * tail_count * score for score in actual_scores
    ]
    terms.extend(bench_weight * tail_count * score for score in bench_scores)
    if risk_weight:
        if eta is None or len(shortfalls) != scenario_count:
            raise SolverExecutionError("The CVaR auxiliary variables do not align with scenarios.")
        terms.append(risk_weight * scenario_count * tail_count * eta)
        terms.extend(-risk_weight * scenario_count * value for value in shortfalls)

    return cp_model.LinearExpr.sum(terms)


def _empty_scenario_result(
    players: pd.DataFrame,
    status: SolverStatus,
    scenarios: ScenarioSet,
    scenario_config: ScenarioOptimizationConfig,
    diagnostics: dict[str, object],
) -> ScenarioOptimizationResult:
    return ScenarioOptimizationResult(
        optimization_result=_empty_result(players, status, diagnostics.copy()),
        scenario_config=scenario_config,
        scenario_fingerprint=scenarios.scenario_fingerprint,
        scenario_evaluation=None,
        mean_scenario_score=None,
        cvar_score=None,
        mean_bench_score=None,
        scenario_objective_value=None,
        risk_penalty_value=None,
        diagnostics=diagnostics,
    )


def optimize_scenario_aware_squad(
    scenarios: ScenarioSet,
    optimization_config: OptimizationConfig,
    scenario_config: ScenarioOptimizationConfig | None = None,
) -> ScenarioOptimizationResult:
    """Optimize one squad against a joint scenario matrix and empirical lower tail."""

    if not isinstance(scenarios, ScenarioSet):
        raise ScenarioValidationError("scenarios must be a ScenarioSet.")
    if not isinstance(optimization_config, OptimizationConfig):
        raise ScenarioConfigurationError(
            "optimization_config must be an OptimizationConfig instance."
        )
    settings = ScenarioOptimizationConfig() if scenario_config is None else scenario_config
    if not isinstance(settings, ScenarioOptimizationConfig):
        raise ScenarioConfigurationError(
            "scenario_config must be a ScenarioOptimizationConfig instance."
        )

    verified = scenarios.validated_copy()
    players = sort_players_by_id(validate_players(verified.projections.table, optimization_config))
    player_ids = players["player_id"].tolist()
    matrix = verified.scenario_points.loc[:, player_ids]
    scaled_rows = [
        [scale_expected_points(value, optimization_config.expected_points_scale) for value in row]
        for row in matrix.to_numpy(dtype="float64", copy=True).tolist()
    ]
    scenario_count = len(scaled_rows)
    tail_count = max(1, math.ceil(settings.tail_fraction * scenario_count))
    weight_scale = settings.objective_weight_scale
    risk_weight = _scaled_weight(settings.risk_aversion, weight_scale)
    bench_weight = _scaled_weight(optimization_config.bench_weight, weight_scale)
    _validate_objective_bound(
        scaled_rows,
        scenario_count=scenario_count,
        tail_count=tail_count,
        weight_scale=weight_scale,
        risk_weight=risk_weight,
        bench_weight=bench_weight,
    )

    model = cp_model.CpModel()
    squad_vars = [model.new_bool_var(f"squad_{index}") for index in range(len(players))]
    starter_vars = [model.new_bool_var(f"starter_{index}") for index in range(len(players))]
    captain_vars = [model.new_bool_var(f"captain_{index}") for index in range(len(players))]
    _add_decision_constraints(
        model,
        players,
        optimization_config,
        squad_vars,
        starter_vars,
        captain_vars,
    )
    actual_scores, bench_scores, eta, shortfalls = _scenario_expressions(
        model,
        scaled_rows,
        starter_vars,
        captain_vars,
        squad_vars,
        risk_weight=risk_weight,
    )
    primary_objective = _objective_expression(
        actual_scores,
        bench_scores,
        eta,
        shortfalls,
        scenario_count=scenario_count,
        tail_count=tail_count,
        weight_scale=weight_scale,
        risk_weight=risk_weight,
        bench_weight=bench_weight,
    )
    model.maximize(primary_objective)

    started_at = perf_counter()
    deadline = started_at + optimization_config.solver_time_limit_seconds
    primary_solver = cp_model.CpSolver()
    configure_solver(
        primary_solver,
        optimization_config,
        optimization_config.solver_time_limit_seconds,
        optimization_config.solver_deterministic_time_limit,
    )
    raw_primary_status = _solve(model, primary_solver)
    primary_status = _map_solver_status(raw_primary_status)
    primary_deterministic_time = _deterministic_time_used(primary_solver, raw_primary_status)
    divisor = weight_scale * scenario_count * tail_count * optimization_config.expected_points_scale
    diagnostics: dict[str, object] = {
        "solver_backend": "ortools-cp-sat",
        "solver_status_name": _raw_status_name(raw_primary_status),
        "solve_time_seconds": perf_counter() - started_at,
        "best_objective_bound": None,
        "absolute_optimality_gap": None,
        "relative_optimality_gap": None,
        "objective_contract": settings.contract_version,
        "configuration_fingerprint": settings.configuration_fingerprint,
        "scenario_fingerprint": verified.scenario_fingerprint,
        "scenario_count": scenario_count,
        "tail_fraction": settings.tail_fraction,
        "tail_count": tail_count,
        "effective_tail_fraction": tail_count / scenario_count,
        "risk_aversion": settings.risk_aversion,
        "risk_weight": risk_weight,
        "bench_weight": optimization_config.bench_weight,
        "bench_weight_integer": bench_weight,
        "objective_weight_scale": weight_scale,
        "expected_points_scale": optimization_config.expected_points_scale,
        "rounding_mode": "ROUND_HALF_UP",
        "deterministic_seed": optimization_config.deterministic_seed,
        "num_search_workers": primary_solver.parameters.num_search_workers,
        "solver_time_limit_seconds": optimization_config.solver_time_limit_seconds,
        "solver_deterministic_time_limit": (optimization_config.solver_deterministic_time_limit),
        "primary_deterministic_time": primary_deterministic_time,
        "tiebreak_deterministic_time_limit": None,
        "tiebreak_deterministic_time": None,
        "deterministic_time_used": primary_deterministic_time,
        "deterministic_time_budget_exhausted": (
            optimization_config.solver_deterministic_time_limit is not None
            and primary_status is not SolverStatus.OPTIMAL
            and primary_deterministic_time
            >= (
                optimization_config.solver_deterministic_time_limit
                - MIN_TIEBREAK_DETERMINISTIC_TIME
            )
        ),
        "tiebreak_attempted": False,
        "tiebreak_status": None,
        "tiebreak_completed": False,
        "decision_reoptimized_per_scenario": False,
        "cvar_applies_to": "starting_xi_plus_captain_double",
        "bench_term": "expected_bench_points",
    }
    if primary_status in {SolverStatus.INFEASIBLE, SolverStatus.UNKNOWN}:
        return _empty_scenario_result(
            players,
            primary_status,
            verified,
            settings,
            diagnostics,
        )

    primary_value = int(primary_solver.value(primary_objective))
    model_objective_value = primary_value / divisor
    best_bound = float(primary_solver.best_objective_bound) / divisor
    if primary_status is SolverStatus.OPTIMAL:
        absolute_gap = 0.0
        relative_gap = 0.0
    else:
        absolute_gap = max(0.0, best_bound - model_objective_value)
        relative_gap = absolute_gap / max(1.0, abs(model_objective_value))

    result_solver = primary_solver
    remaining_time = deadline - perf_counter()
    remaining_deterministic_time = _remaining_deterministic_time(
        optimization_config.solver_deterministic_time_limit,
        primary_deterministic_time,
    )
    deterministic_budget_available = (
        remaining_deterministic_time is None
        or remaining_deterministic_time > MIN_TIEBREAK_DETERMINISTIC_TIME
    )
    if (
        primary_status is SolverStatus.OPTIMAL
        and remaining_time > MIN_TIEBREAK_TIME_SECONDS
        and deterministic_budget_available
    ):
        diagnostics["tiebreak_attempted"] = True
        _add_tiebreak_objective(
            model,
            squad_vars,
            starter_vars,
            captain_vars,
            primary_objective,
            optimization_config,
            primary_value,
        )
        tiebreak_solver = cp_model.CpSolver()
        diagnostics["tiebreak_deterministic_time_limit"] = remaining_deterministic_time
        configure_solver(
            tiebreak_solver,
            optimization_config,
            remaining_time,
            remaining_deterministic_time,
        )
        raw_tiebreak_status = _solve(model, tiebreak_solver)
        tiebreak_status = _map_solver_status(raw_tiebreak_status)
        tiebreak_deterministic_time = _deterministic_time_used(
            tiebreak_solver,
            raw_tiebreak_status,
        )
        diagnostics["tiebreak_status"] = _raw_status_name(raw_tiebreak_status)
        diagnostics["tiebreak_deterministic_time"] = tiebreak_deterministic_time
        diagnostics["deterministic_time_used"] = (
            primary_deterministic_time + tiebreak_deterministic_time
        )
        diagnostics["deterministic_time_budget_exhausted"] = (
            remaining_deterministic_time is not None
            and tiebreak_status is not SolverStatus.OPTIMAL
            and tiebreak_deterministic_time
            >= remaining_deterministic_time - MIN_TIEBREAK_DETERMINISTIC_TIME
        )
        if tiebreak_status in {SolverStatus.OPTIMAL, SolverStatus.FEASIBLE}:
            result_solver = tiebreak_solver
            diagnostics["tiebreak_completed"] = tiebreak_status is SolverStatus.OPTIMAL
        elif tiebreak_status is SolverStatus.INFEASIBLE:
            raise SolverExecutionError(
                "The scenario tie-break became infeasible after fixing the primary optimum."
            )

    squad_indices = _selected_indices(result_solver, squad_vars)
    starter_indices = _selected_indices(result_solver, starter_vars)
    captain_indices = _selected_indices(result_solver, captain_vars)
    _verify_solution(
        players,
        optimization_config,
        squad_indices,
        starter_indices,
        captain_indices,
    )
    squad_set = set(squad_indices)
    starter_set = set(starter_indices)
    bench_indices = sorted(squad_set - starter_set)
    selected_squad = players.iloc[squad_indices].reset_index(drop=True).copy(deep=True)
    starting_xi = players.iloc[starter_indices].reset_index(drop=True).copy(deep=True)
    bench = players.iloc[bench_indices].reset_index(drop=True).copy(deep=True)
    captain = players.iloc[captain_indices[0]].copy(deep=True)
    captain.name = None
    total_cost = sum(int(players.iloc[index]["price_tenths"]) for index in squad_indices)
    point_projection_score = float(
        starting_xi["expected_points"].sum() + captain["expected_points"]
    )
    diagnostics.update(
        {
            "solve_time_seconds": perf_counter() - started_at,
            "best_objective_bound": best_bound,
            "absolute_optimality_gap": absolute_gap,
            "relative_optimality_gap": relative_gap,
            "scaled_model_objective_value": model_objective_value,
        }
    )
    optimization_result = OptimizationResult(
        solver_status=primary_status,
        selected_squad=selected_squad,
        starting_xi=starting_xi,
        bench=bench,
        captain=captain,
        total_cost_tenths=total_cost,
        projected_score=point_projection_score,
        objective_value=model_objective_value,
        diagnostics=diagnostics,
    )
    evaluation = evaluate_fixed_decision(
        optimization_result,
        verified,
        ScenarioEvaluationConfig(
            lower_quantile=settings.tail_fraction,
            worst_fraction=settings.tail_fraction,
        ),
    )
    mean_score = evaluation.metrics.mean_score
    cvar_score = evaluation.metrics.mean_worst_fraction_score
    bench_ids = bench["player_id"].tolist()
    mean_bench_score = float(verified.scenario_points.loc[:, bench_ids].sum(axis=1).mean())
    objective_value = (
        (1.0 - settings.risk_aversion) * mean_score
        + settings.risk_aversion * cvar_score
        + optimization_config.bench_weight * mean_bench_score
    )
    risk_penalty = max(0.0, settings.risk_aversion * (mean_score - cvar_score))
    return ScenarioOptimizationResult(
        optimization_result=optimization_result,
        scenario_config=settings,
        scenario_fingerprint=verified.scenario_fingerprint,
        scenario_evaluation=evaluation,
        mean_scenario_score=mean_score,
        cvar_score=cvar_score,
        mean_bench_score=mean_bench_score,
        scenario_objective_value=objective_value,
        risk_penalty_value=risk_penalty,
        diagnostics={
            **diagnostics,
            "scenario_mean_score": mean_score,
            "scenario_cvar_score": cvar_score,
            "scenario_mean_bench_score": mean_bench_score,
            "scenario_objective_value": objective_value,
            "risk_penalty_value": risk_penalty,
            "point_projection_changed": False,
        },
    )
