"""Rank-probability optimization: the squad most likely to finish ahead of a rival.

Expected points is the wrong objective for a mini-league. What decides a league is
finishing ahead of named rivals, and the squad that maximises the *probability* of that
is not the squad that maximises expected points: behind, it seeks variance and
differentials; ahead, it hedges by holding what the rival holds. Both behaviours fall
out of one objective — the share of joint scenarios in which my score beats the rival's
— without writing either as a rule.

The model is the deterministic squad model (15 / 11 / captain, budget, club limit) with
one Boolean per scenario, ``ahead_s``, forced to zero unless my score in that scenario
exceeds the rival's fixed score by more than the margin (a big-M indicator on the
scenario's linear score). The primary objective is the number of scenarios ahead; a
secondary term (scaled below one scenario's weight) prefers, among equally likely
squads, the higher expected score, and the ordinary rank tie-break makes the answer
deterministic. An optional constraint keeps expected points within a stated budget of a
reference (the risk-neutral squad's), so a menu can be swept: "60% for -0.8 xP, 75% for
-4.3 xP".

Rival and self are scored in the same scenarios, so shared players cancel exactly and
only the differential is uncertain. The selection-optimism shift is not applied to
either side — both squads were selected; it cancels in the difference. Everything here
is a measurement instrument until the goal-menu report is verified against a ledger.
"""

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from time import perf_counter
from types import MappingProxyType
from typing import Final

import numpy as np
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
    _configure_solver,
    _deterministic_time_used,
    _empty_result,
    _map_solver_status,
    _raw_status_name,
    _remaining_deterministic_time,
    _selected_indices,
    _solve,
    _verify_solution,
)
from squadopt.optimization.validation import validate_players
from squadopt.scenarios.evaluation import (
    RivalSquad,
    ScenarioComparisonResult,
    compare_fixed_decisions,
    wilson_interval,
)
from squadopt.scenarios.models import (
    ScenarioConfigurationError,
    ScenarioSet,
    ScenarioValidationError,
)

RANK_OBJECTIVE_CONTRACT_VERSION: Final = "rank_probability_objective_v1"


@dataclass(frozen=True, slots=True)
class RankObjectiveConfig:
    """Controls for the rank-probability objective."""

    margin_points: float = 0.0
    """Be ahead by more than this many points to count a scenario as won."""
    expected_points_budget: float | None = None
    """When set with a reference, the squad's scenario-mean score may fall at most this
    far below the reference (the risk-neutral squad's mean): the price of the goal."""
    objective_weight_scale: int = 1_000
    contract_version: str = RANK_OBJECTIVE_CONTRACT_VERSION

    def __post_init__(self) -> None:
        if self.contract_version != RANK_OBJECTIVE_CONTRACT_VERSION:
            raise ScenarioConfigurationError("Unsupported rank objective contract_version.")
        margin = self.margin_points
        if (
            isinstance(margin, bool)
            or not isinstance(margin, int | float)
            or not math.isfinite(margin)
        ):
            raise ScenarioConfigurationError("margin_points must be a finite number.")
        object.__setattr__(self, "margin_points", float(margin))
        budget = self.expected_points_budget
        if budget is not None:
            if isinstance(budget, bool) or not isinstance(budget, int | float):
                raise ScenarioConfigurationError("expected_points_budget must be a number or None.")
            if not math.isfinite(budget) or budget < 0.0:
                raise ScenarioConfigurationError("expected_points_budget must be finite and >= 0.")
            object.__setattr__(self, "expected_points_budget", float(budget))
        scale = self.objective_weight_scale
        if isinstance(scale, bool) or not isinstance(scale, int) or scale < 1:
            raise ScenarioConfigurationError("objective_weight_scale must be a positive integer.")


@dataclass(frozen=True, slots=True)
class RankOptimizationResult:
    """The squad most likely ahead of the rival, with the probability it buys."""

    optimization_result: OptimizationResult
    rival_label: str
    probability_ahead: float | None
    probability_ahead_interval: tuple[float, float] | None
    scenario_mean_score: float | None
    reference_expected_points: float | None
    expected_points_budget: float | None
    comparison: ScenarioComparisonResult | None
    diagnostics: Mapping[str, object] = field(default_factory=dict)
    contract_version: str = RANK_OBJECTIVE_CONTRACT_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "diagnostics", MappingProxyType(dict(self.diagnostics)))

    @property
    def has_solution(self) -> bool:
        return self.optimization_result.has_solution


def _rival_scores(
    matrix: np.ndarray, column: Mapping[object, int], rival: RivalSquad
) -> np.ndarray:
    missing = [p for p in [*rival.starter_ids, rival.captain_id] if p not in column]
    if missing:
        raise ScenarioValidationError(
            f"Scenario players must cover the rival squad; missing={missing[:10]!r}."
        )
    starters = [column[p] for p in rival.starter_ids]
    scores: np.ndarray = matrix[:, starters].sum(axis=1) + matrix[:, column[rival.captain_id]]
    return scores


def optimize_rank_probability_squad(
    scenarios: ScenarioSet,
    rival: RivalSquad,
    optimization_config: OptimizationConfig,
    config: RankObjectiveConfig | None = None,
    *,
    reference_expected_points: float | None = None,
) -> RankOptimizationResult:
    """Choose the squad that is ahead of ``rival`` in the most scenarios.

    ``reference_expected_points`` is the scenario-mean score of the reference squad
    (normally the risk-neutral one); with ``config.expected_points_budget`` it bounds
    how much expected score the goal may cost. Without either, expected score is only
    the secondary tie-break.
    """

    if not isinstance(scenarios, ScenarioSet):
        raise ScenarioValidationError("scenarios must be a ScenarioSet.")
    if not isinstance(rival, RivalSquad):
        raise ScenarioValidationError("rival must be a RivalSquad.")
    if not isinstance(optimization_config, OptimizationConfig):
        raise ScenarioConfigurationError("optimization_config must be an OptimizationConfig.")
    settings = RankObjectiveConfig() if config is None else config
    if not isinstance(settings, RankObjectiveConfig):
        raise ScenarioConfigurationError("config must be a RankObjectiveConfig.")
    if settings.expected_points_budget is not None and reference_expected_points is None:
        raise ScenarioConfigurationError(
            "expected_points_budget needs reference_expected_points to be relative to."
        )

    verified = scenarios.validated_copy()
    players = sort_players_by_id(validate_players(verified.projections.table, optimization_config))
    player_ids = players["player_id"].tolist()
    column = {player_id: index for index, player_id in enumerate(player_ids)}
    matrix = verified.scenario_points.loc[:, player_ids].to_numpy(dtype="float64", copy=True)
    scale = optimization_config.expected_points_scale
    scaled_rows = [[scale_expected_points(v, scale) for v in row] for row in matrix.tolist()]
    rival_raw = _rival_scores(matrix, column, rival)
    # The rival's scenario scores are summed from the same per-player scaled integers as
    # mine, so an identical squad scores identically to the last unit; scaling the float
    # sum instead would let rounding noise decide "ahead".
    rival_columns = [column[p] for p in rival.starter_ids]
    rival_captain_column = column[rival.captain_id]
    rival_scaled = [
        sum(row[i] for i in rival_columns) + row[rival_captain_column] for row in scaled_rows
    ]
    margin_scaled = scale_expected_points(settings.margin_points, scale)
    scenario_count = len(scaled_rows)

    row_bounds = [2 * sum(abs(v) for v in row) for row in scaled_rows]
    big_m = max(row_bounds, default=0) + max((abs(v) for v in rival_scaled), default=0)
    big_m += abs(margin_scaled) + 1
    # Objective weights: one scenario ahead outweighs any expected-score difference.
    expected_bound = sum(row_bounds)
    ahead_weight = expected_bound + 1
    if ahead_weight * scenario_count + expected_bound > CP_SAT_SAFE_INTEGER_MAX:
        raise SolverExecutionError(
            "Rank objective exceeds the safe CP-SAT integer range; reduce the scenario count "
            "or expected_points_scale."
        )

    model = cp_model.CpModel()
    squad_vars = [model.new_bool_var(f"squad_{i}") for i in range(len(players))]
    starter_vars = [model.new_bool_var(f"starter_{i}") for i in range(len(players))]
    captain_vars = [model.new_bool_var(f"captain_{i}") for i in range(len(players))]
    _add_decision_constraints(
        model, players, optimization_config, squad_vars, starter_vars, captain_vars
    )
    my_scores: list[cp_model.LinearExpr] = []
    ahead_vars: list[cp_model.IntVar] = []
    for s, row in enumerate(scaled_rows):
        terms: list[cp_model.LinearExpr] = []
        for i, points in enumerate(row):
            terms.append(points * starter_vars[i])
            terms.append(points * captain_vars[i])
        score = cp_model.LinearExpr.sum(terms)
        my_scores.append(score)
        ahead = model.new_bool_var(f"ahead_{s}")
        # ahead_s = 1 only if score_s >= rival_s + margin + 1 (strictly more than margin).
        model.add(score >= rival_scaled[s] + margin_scaled + 1 - big_m * (1 - ahead))
        model.add(score <= rival_scaled[s] + margin_scaled + big_m * ahead)
        ahead_vars.append(ahead)
    total_score = cp_model.LinearExpr.sum(my_scores)
    if settings.expected_points_budget is not None and reference_expected_points is not None:
        floor_points = reference_expected_points - settings.expected_points_budget
        model.add(total_score >= scale_expected_points(floor_points, scale) * scenario_count)
    primary_objective = ahead_weight * cp_model.LinearExpr.sum(ahead_vars) + total_score
    model.maximize(primary_objective)

    started_at = perf_counter()
    deadline = started_at + optimization_config.solver_time_limit_seconds
    solver = cp_model.CpSolver()
    _configure_solver(
        solver,
        optimization_config,
        optimization_config.solver_time_limit_seconds,
        optimization_config.solver_deterministic_time_limit,
    )
    raw_status = _solve(model, solver)
    status = _map_solver_status(raw_status)
    primary_deterministic_time = _deterministic_time_used(solver, raw_status)
    diagnostics: dict[str, object] = {
        "solver_backend": "ortools-cp-sat",
        "solver_status_name": _raw_status_name(raw_status),
        "objective_contract": settings.contract_version,
        "scenario_fingerprint": verified.scenario_fingerprint,
        "scenario_count": scenario_count,
        "margin_points": settings.margin_points,
        "expected_points_budget": settings.expected_points_budget,
        "reference_expected_points": reference_expected_points,
        "rival_label": rival.label,
        "rival_scenario_mean_score": float(rival_raw.mean()),
        "big_m": big_m,
        "ahead_weight": ahead_weight,
        "num_search_workers": 1,
        "primary_deterministic_time": primary_deterministic_time,
        "tiebreak_attempted": False,
        "tiebreak_completed": False,
        "location_shift_applied": False,
        "scoring_policy": "starting_xi_plus_captain_double_v1",
    }
    if status in {SolverStatus.INFEASIBLE, SolverStatus.UNKNOWN}:
        diagnostics["solve_time_seconds"] = perf_counter() - started_at
        return RankOptimizationResult(
            optimization_result=_empty_result(players, status, diagnostics.copy()),
            rival_label=rival.label,
            probability_ahead=None,
            probability_ahead_interval=None,
            scenario_mean_score=None,
            reference_expected_points=reference_expected_points,
            expected_points_budget=settings.expected_points_budget,
            comparison=None,
            diagnostics=diagnostics,
        )

    primary_value = int(solver.value(primary_objective))
    primary_ahead_count = int(sum(solver.value(v) for v in ahead_vars))
    best_bound = float(solver.best_objective_bound)
    diagnostics["best_objective_bound"] = best_bound
    diagnostics["absolute_optimality_gap"] = (
        0.0 if status is SolverStatus.OPTIMAL else max(0.0, best_bound - primary_value)
    )
    diagnostics["relative_optimality_gap"] = (
        0.0
        if status is SolverStatus.OPTIMAL
        else max(0.0, best_bound - primary_value) / max(1.0, abs(primary_value))
    )
    result_solver = solver
    remaining_time = deadline - perf_counter()
    remaining_deterministic = _remaining_deterministic_time(
        optimization_config.solver_deterministic_time_limit, primary_deterministic_time
    )
    if (
        status is SolverStatus.OPTIMAL
        and remaining_time > MIN_TIEBREAK_TIME_SECONDS
        and (
            remaining_deterministic is None
            or remaining_deterministic > MIN_TIEBREAK_DETERMINISTIC_TIME
        )
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
        _configure_solver(
            tiebreak_solver, optimization_config, remaining_time, remaining_deterministic
        )
        raw_tiebreak = _solve(model, tiebreak_solver)
        tiebreak_status = _map_solver_status(raw_tiebreak)
        if tiebreak_status in {SolverStatus.OPTIMAL, SolverStatus.FEASIBLE}:
            result_solver = tiebreak_solver
            diagnostics["tiebreak_completed"] = tiebreak_status is SolverStatus.OPTIMAL
        elif tiebreak_status is SolverStatus.INFEASIBLE:
            raise SolverExecutionError(
                "The rank tie-break became infeasible after fixing the primary optimum."
            )

    squad_indices = _selected_indices(result_solver, squad_vars)
    starter_indices = _selected_indices(result_solver, starter_vars)
    captain_indices = _selected_indices(result_solver, captain_vars)
    _verify_solution(players, optimization_config, squad_indices, starter_indices, captain_indices)
    bench_indices = sorted(set(squad_indices) - set(starter_indices))
    selected_squad = players.iloc[squad_indices].reset_index(drop=True).copy(deep=True)
    starting_xi = players.iloc[starter_indices].reset_index(drop=True).copy(deep=True)
    bench = players.iloc[bench_indices].reset_index(drop=True).copy(deep=True)
    captain = players.iloc[captain_indices[0]].copy(deep=True)
    captain.name = None
    total_cost = sum(int(players.iloc[i]["price_tenths"]) for i in squad_indices)
    projected = float(starting_xi["expected_points"].sum() + captain["expected_points"])
    diagnostics["solve_time_seconds"] = perf_counter() - started_at
    optimization_result = OptimizationResult(
        solver_status=status,
        selected_squad=selected_squad,
        starting_xi=starting_xi,
        bench=bench,
        captain=captain,
        total_cost_tenths=total_cost,
        projected_score=projected,
        objective_value=float(primary_ahead_count),
        diagnostics=diagnostics.copy(),
    )
    # Read the probability off the chosen squad's actual scenario scores (the model's
    # indicators agree by construction, and this is the same code path a report uses).
    comparison = compare_fixed_decisions(optimization_result, rival, verified)
    my_scaled = np.asarray(
        [sum(row[i] for i in starter_indices) + row[captain_indices[0]] for row in scaled_rows],
        dtype="int64",
    )
    rival_array = np.asarray(rival_scaled, dtype="int64")
    ahead_count = int((my_scaled >= rival_array + margin_scaled + 1).sum())
    my_mean = float((matrix[:, starter_indices].sum(axis=1) + matrix[:, captain_indices[0]]).mean())
    diagnostics["ahead_count"] = ahead_count
    diagnostics["ahead_count_from_indicators"] = int(
        sum(result_solver.value(v) for v in ahead_vars)
    )
    return RankOptimizationResult(
        optimization_result=optimization_result,
        rival_label=rival.label,
        probability_ahead=ahead_count / scenario_count,
        probability_ahead_interval=wilson_interval(ahead_count, scenario_count),
        scenario_mean_score=my_mean,
        reference_expected_points=reference_expected_points,
        expected_points_budget=settings.expected_points_budget,
        comparison=comparison,
        diagnostics=diagnostics,
    )


@dataclass(frozen=True, slots=True)
class GoalMenuEntry:
    """One line of the goal menu: a budget, and what it buys against the rival."""

    expected_points_budget: float | None
    probability_ahead: float | None
    probability_ahead_interval: tuple[float, float] | None
    scenario_mean_score: float | None
    expected_points_cost: float | None
    starters_changed: int | None
    captain_changed: bool | None
    solver_status: str


def goal_menu(
    scenarios: ScenarioSet,
    rival: RivalSquad,
    reference: OptimizationResult,
    optimization_config: OptimizationConfig,
    budgets: Sequence[float | None] = (0.0, 1.0, 2.0, 4.0, 8.0, None),
    *,
    margin_points: float = 0.0,
) -> tuple[tuple[GoalMenuEntry, RankOptimizationResult], ...]:
    """Sweep the expected-points budget and return the menu against one rival.

    ``reference`` is the risk-neutral decision; its scenario-mean score anchors the
    budgets and its eleven anchors "starters changed". A budget of None is unconstrained.
    """

    if not isinstance(reference, OptimizationResult) or not reference.has_solution:
        raise ScenarioValidationError("reference must be a feasible OptimizationResult.")
    verified = scenarios.validated_copy()
    player_ids = verified.projections.table["player_id"].tolist()
    column = {p: i for i, p in enumerate(player_ids)}
    matrix = verified.scenario_points.to_numpy(dtype="float64", copy=False)
    reference_starters = reference.starting_xi["player_id"].tolist()
    assert reference.captain is not None
    reference_captain = reference.captain["player_id"]
    reference_mean = float(
        (
            matrix[:, [column[p] for p in reference_starters]].sum(axis=1)
            + matrix[:, column[reference_captain]]
        ).mean()
    )
    entries: list[tuple[GoalMenuEntry, RankOptimizationResult]] = []
    for budget in budgets:
        result = optimize_rank_probability_squad(
            verified,
            rival,
            optimization_config,
            RankObjectiveConfig(margin_points=margin_points, expected_points_budget=budget),
            reference_expected_points=reference_mean,
        )
        if result.has_solution:
            chosen = result.optimization_result
            assert chosen.captain is not None
            changed = len(set(chosen.starting_xi["player_id"]) - set(reference_starters))
            entry = GoalMenuEntry(
                expected_points_budget=budget,
                probability_ahead=result.probability_ahead,
                probability_ahead_interval=result.probability_ahead_interval,
                scenario_mean_score=result.scenario_mean_score,
                expected_points_cost=(
                    None
                    if result.scenario_mean_score is None
                    else reference_mean - result.scenario_mean_score
                ),
                starters_changed=changed,
                captain_changed=chosen.captain["player_id"] != reference_captain,
                solver_status=chosen.solver_status.name,
            )
        else:
            entry = GoalMenuEntry(
                budget,
                None,
                None,
                None,
                None,
                None,
                None,
                result.optimization_result.solver_status.name,
            )
        entries.append((entry, result))
    return tuple(entries)
