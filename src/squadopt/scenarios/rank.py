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
    rival_edge_draws,
    wilson_interval,
)
from squadopt.scenarios.models import (
    ScenarioConfigurationError,
    ScenarioSet,
    ScenarioValidationError,
)

RANK_OBJECTIVE_CONTRACT_VERSION: Final = "rank_probability_objective_v1"
CLAIM_SCENARIO_MODES: Final = ("in_sample", "held_out_half")
# Share of the solver's limits spent proving the ahead count; the rest goes to the
# expected-score phase and the deterministic rank tie-break.
_PRIMARY_PHASE_SHARE: Final = 0.6
_SECONDARY_PHASE_SHARE: Final = 0.3


@dataclass(frozen=True, slots=True)
class RankObjectiveConfig:
    """Controls for the rank-probability objective."""

    margin_points: float = 0.0
    """Be ahead by more than this many points to count a scenario as won."""
    rival_edge_points: float = 0.0
    """Points added to the rival's score in every scenario before comparison.

    The scenario generator centres every player on the projection, so a rival who
    systematically outscores the projection - the ownership template does, by a measured
    +7.19 a week - is under-priced and P(ahead) inflates. This constant restores the
    rival's measured edge. Zero (the default) is the historical behaviour, bit for bit."""
    rival_edge_samples: tuple[float, ...] = ()
    """Measured weekly edges to resample instead of the constant (empty = constant only).

    A constant fixes the rival's location and leaves its spread at zero; the measured
    weekly edge has a standard deviation of ~18 points, and over a window that missing
    spread is what made claimed probabilities fiction (rival_scenario_prereg). The
    samples carry the measured location, so combining them with a non-zero
    ``rival_edge_points`` is refused as double counting."""
    rival_edge_weeks: int = 1
    """How many weekly draws sum into one scenario's edge (the window's horizon)."""
    rival_edge_seed: int = 0
    """Deterministic seed for the resampling; recorded in diagnostics."""
    expected_points_budget: float | None = None
    """When set with a reference, the squad's scenario-mean score may fall at most this
    far below the reference (the risk-neutral squad's mean): the price of the goal."""
    claim_scenarios: str = "in_sample"
    """Which scenarios the reported probability is read from. ``in_sample``: the same
    scenarios the squad was chosen on (optimistic: the squad was picked to win them).
    ``held_out_half``: the squad is chosen on the first half of the scenario sample and
    the probability is read from the second half it never saw - the scenario-level
    analogue of the selection-optimism shift."""
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
        edge = self.rival_edge_points
        if isinstance(edge, bool) or not isinstance(edge, int | float) or not math.isfinite(edge):
            raise ScenarioConfigurationError("rival_edge_points must be a finite number.")
        object.__setattr__(self, "rival_edge_points", float(edge))
        samples = self.rival_edge_samples
        if not isinstance(samples, tuple) or any(
            isinstance(v, bool) or not isinstance(v, int | float) or not math.isfinite(v)
            for v in samples
        ):
            raise ScenarioConfigurationError(
                "rival_edge_samples must be a tuple of finite numbers."
            )
        object.__setattr__(self, "rival_edge_samples", tuple(float(v) for v in samples))
        if samples and float(edge) != 0.0:
            raise ScenarioConfigurationError(
                "rival_edge_samples carry the measured location already; a non-zero "
                "rival_edge_points on top would count the edge twice."
            )
        weeks = self.rival_edge_weeks
        if isinstance(weeks, bool) or not isinstance(weeks, int) or weeks < 1:
            raise ScenarioConfigurationError("rival_edge_weeks must be a positive integer.")
        seed = self.rival_edge_seed
        if isinstance(seed, bool) or not isinstance(seed, int):
            raise ScenarioConfigurationError("rival_edge_seed must be an integer.")
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
        if self.claim_scenarios not in CLAIM_SCENARIO_MODES:
            raise ScenarioConfigurationError(
                f"claim_scenarios must be one of {CLAIM_SCENARIO_MODES!r}."
            )


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
    if settings.rival_edge_samples:
        edge_vector = rival_edge_draws(
            settings.rival_edge_samples,
            scenarios=matrix.shape[0],
            weeks=settings.rival_edge_weeks,
            seed=settings.rival_edge_seed,
        )
    else:
        edge_vector = np.full(matrix.shape[0], settings.rival_edge_points)
    rival_raw = _rival_scores(matrix, column, rival) + edge_vector
    # The rival's scenario scores are summed from the same per-player scaled integers as
    # mine, so an identical squad scores identically to the last unit; scaling the float
    # sum instead would let rounding noise decide "ahead".
    rival_columns = [column[p] for p in rival.starter_ids]
    rival_captain_column = column[rival.captain_id]
    edge_scaled_rows = [scale_expected_points(float(v), scale) for v in edge_vector]
    rival_scaled = [
        sum(row[i] for i in rival_columns) + row[rival_captain_column] + edge_scaled_rows[r]
        for r, row in enumerate(scaled_rows)
    ]
    margin_scaled = scale_expected_points(settings.margin_points, scale)
    total_scenarios = len(scaled_rows)
    if settings.claim_scenarios == "held_out_half":
        if total_scenarios < 4:
            raise ScenarioValidationError("held_out_half needs at least four scenarios.")
        selection_rows = list(range(total_scenarios // 2))
        claim_rows = list(range(total_scenarios // 2, total_scenarios))
    else:
        selection_rows = list(range(total_scenarios))
        claim_rows = list(range(total_scenarios))
    scenario_count = len(selection_rows)

    starting_size = optimization_config.starting_size
    # Per-scenario score bounds: at most the largest value twice (captain) plus the next
    # starting_size - 1 largest; at least the smallest twice plus the next smallest.
    # Tight per-scenario big-Ms keep the relaxation informative.
    upper_by_row: list[int] = []
    lower_by_row: list[int] = []
    for row in scaled_rows:
        ordered = sorted(row)
        upper_by_row.append(2 * ordered[-1] + sum(ordered[-starting_size:-1]))
        lower_by_row.append(2 * ordered[0] + sum(ordered[1:starting_size]))
    expected_bound = sum(max(abs(upper_by_row[s]), abs(lower_by_row[s])) for s in selection_rows)
    if scenario_count + expected_bound > CP_SAT_SAFE_INTEGER_MAX:
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
    for s in selection_rows:
        row = scaled_rows[s]
        terms: list[cp_model.LinearExpr] = []
        for i, points in enumerate(row):
            terms.append(points * starter_vars[i])
            terms.append(points * captain_vars[i])
        score = cp_model.LinearExpr.sum(terms)
        my_scores.append(score)
        threshold = rival_scaled[s] + margin_scaled + 1
        ahead = model.new_bool_var(f"ahead_{s}")
        # ahead_s = 1 only if score_s >= rival_s + margin + 1 (strictly more than margin),
        # pinned both ways with a big-M sized to this scenario's own score range.
        big_m_low = max(0, threshold - lower_by_row[s])
        big_m_high = max(0, upper_by_row[s] - threshold + 1)
        model.add(score >= threshold - big_m_low * (1 - ahead))
        model.add(score <= threshold - 1 + big_m_high * ahead)
        ahead_vars.append(ahead)
    total_score = cp_model.LinearExpr.sum(my_scores)
    if settings.expected_points_budget is not None and reference_expected_points is not None:
        floor_points = reference_expected_points - settings.expected_points_budget
        model.add(total_score >= scale_expected_points(floor_points, scale) * scenario_count)
    ahead_total = cp_model.LinearExpr.sum(ahead_vars)
    # The rival's own eleven is a feasible start (it wins no scenario against itself, but
    # it is a squad): the solver has an incumbent from the first node.
    rival_squad_columns = set(rival_columns)
    for i in range(len(players)):
        model.add_hint(starter_vars[i], int(i in rival_squad_columns))
        model.add_hint(captain_vars[i], int(i == rival_captain_column))

    started_at = perf_counter()
    wall_limit = optimization_config.solver_time_limit_seconds
    deterministic_limit = optimization_config.solver_deterministic_time_limit
    deadline = started_at + wall_limit

    # Phase 1: the ahead count alone (small integers; a bound the solver can prove).
    model.maximize(ahead_total)
    solver = cp_model.CpSolver()
    _configure_solver(
        solver,
        optimization_config,
        wall_limit * _PRIMARY_PHASE_SHARE,
        None if deterministic_limit is None else deterministic_limit * _PRIMARY_PHASE_SHARE,
    )
    raw_status = _solve(model, solver)
    status = _map_solver_status(raw_status)
    primary_deterministic_time = _deterministic_time_used(solver, raw_status)
    diagnostics: dict[str, object] = {
        "solver_backend": "ortools-cp-sat",
        "solver_status_name": _raw_status_name(raw_status),
        "objective_contract": settings.contract_version,
        "scenario_fingerprint": verified.scenario_fingerprint,
        "scenario_count": total_scenarios,
        "selection_scenario_count": scenario_count,
        "claim_scenario_count": len(claim_rows),
        "claim_scenarios": settings.claim_scenarios,
        "margin_points": settings.margin_points,
        "rival_edge_points": settings.rival_edge_points,
        "rival_edge_samples": len(settings.rival_edge_samples),
        "rival_edge_weeks": settings.rival_edge_weeks,
        "rival_edge_seed": settings.rival_edge_seed,
        "rival_edge_drawn_mean": float(np.mean(edge_vector)),
        "rival_edge_drawn_sd": float(np.std(edge_vector)),
        "expected_points_budget": settings.expected_points_budget,
        "reference_expected_points": reference_expected_points,
        "rival_label": rival.label,
        "rival_scenario_mean_score": float(rival_raw.mean()),
        "num_search_workers": 1,
        "primary_deterministic_time": primary_deterministic_time,
        "secondary_attempted": False,
        "secondary_completed": False,
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

    primary_value = int(solver.value(ahead_total))
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

    # Phase 2: keep at least that many scenarios and maximise expected score. Runs even
    # after a FEASIBLE phase 1 (it can only keep or improve the incumbent).
    remaining_time = deadline - perf_counter()
    remaining_deterministic = _remaining_deterministic_time(
        deterministic_limit, primary_deterministic_time
    )
    secondary_deterministic_time = 0.0
    if remaining_time > MIN_TIEBREAK_TIME_SECONDS and (
        remaining_deterministic is None or remaining_deterministic > MIN_TIEBREAK_DETERMINISTIC_TIME
    ):
        diagnostics["secondary_attempted"] = True
        model.add(ahead_total >= primary_value)
        model.maximize(total_score)
        model.clear_hints()  # type: ignore[no-untyped-call]
        for variables in (squad_vars, starter_vars, captain_vars):
            for variable in variables:
                model.add_hint(variable, int(solver.value(variable)))
        secondary_share = _SECONDARY_PHASE_SHARE / (1.0 - _PRIMARY_PHASE_SHARE)
        secondary_solver = cp_model.CpSolver()
        _configure_solver(
            secondary_solver,
            optimization_config,
            remaining_time * secondary_share,
            None if remaining_deterministic is None else remaining_deterministic * secondary_share,
        )
        raw_secondary = _solve(model, secondary_solver)
        secondary_status = _map_solver_status(raw_secondary)
        secondary_deterministic_time = _deterministic_time_used(secondary_solver, raw_secondary)
        if secondary_status in {SolverStatus.OPTIMAL, SolverStatus.FEASIBLE}:
            result_solver = secondary_solver
            diagnostics["secondary_completed"] = secondary_status is SolverStatus.OPTIMAL
        elif secondary_status is SolverStatus.INFEASIBLE:
            raise SolverExecutionError(
                "The expected-score phase became infeasible after fixing the ahead count."
            )

    # Phase 3: the ordinary deterministic rank tie-break, once both objectives are proven.
    remaining_time = deadline - perf_counter()
    remaining_deterministic = _remaining_deterministic_time(
        deterministic_limit, primary_deterministic_time + secondary_deterministic_time
    )
    if (
        status is SolverStatus.OPTIMAL
        and diagnostics["secondary_completed"] is True
        and remaining_time > MIN_TIEBREAK_TIME_SECONDS
        and (
            remaining_deterministic is None
            or remaining_deterministic > MIN_TIEBREAK_DETERMINISTIC_TIME
        )
    ):
        diagnostics["tiebreak_attempted"] = True
        secondary_value = int(result_solver.value(total_score))
        _add_tiebreak_objective(
            model,
            squad_vars,
            starter_vars,
            captain_vars,
            total_score,
            optimization_config,
            secondary_value,
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

    # Probabilities are read off the chosen squad's actual scenario scores: on the
    # selection scenarios (what the model optimised; its indicators agree by
    # construction) and on the claim scenarios (what is reported).
    my_scaled = np.asarray(
        [sum(row[i] for i in starter_indices) + row[captain_indices[0]] for row in scaled_rows],
        dtype="int64",
    )
    rival_array = np.asarray(rival_scaled, dtype="int64")
    ahead_all = my_scaled >= rival_array + margin_scaled + 1
    selection_ahead = int(ahead_all[selection_rows].sum())
    claim_ahead = int(ahead_all[claim_rows].sum())
    my_means = matrix[:, starter_indices].sum(axis=1) + matrix[:, captain_indices[0]]
    diagnostics["ahead_count"] = selection_ahead
    diagnostics["ahead_count_from_indicators"] = int(
        sum(result_solver.value(v) for v in ahead_vars)
    )
    diagnostics["selection_probability_ahead"] = selection_ahead / scenario_count
    diagnostics["claim_ahead_count"] = claim_ahead
    diagnostics["selection_mean_score"] = float(my_means[selection_rows].mean())
    optimization_result = OptimizationResult(
        solver_status=status,
        selected_squad=selected_squad,
        starting_xi=starting_xi,
        bench=bench,
        captain=captain,
        total_cost_tenths=total_cost,
        projected_score=projected,
        objective_value=float(selection_ahead),
        diagnostics=diagnostics.copy(),
    )
    comparison = (
        compare_fixed_decisions(
            optimization_result,
            rival,
            verified,
            rival_edge_points=settings.rival_edge_points,
            rival_edge_samples=settings.rival_edge_samples,
            rival_edge_weeks=settings.rival_edge_weeks,
            rival_edge_seed=settings.rival_edge_seed,
        )
        if settings.claim_scenarios == "in_sample"
        else None
    )
    return RankOptimizationResult(
        optimization_result=optimization_result,
        rival_label=rival.label,
        probability_ahead=claim_ahead / len(claim_rows),
        probability_ahead_interval=wilson_interval(claim_ahead, len(claim_rows)),
        scenario_mean_score=float(my_means[claim_rows].mean()),
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
    rival_edge_points: float = 0.0,
    rival_edge_samples: tuple[float, ...] = (),
    rival_edge_weeks: int = 1,
    rival_edge_seed: int = 0,
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
            RankObjectiveConfig(
                margin_points=margin_points,
                expected_points_budget=budget,
                rival_edge_points=rival_edge_points,
                rival_edge_samples=rival_edge_samples,
                rival_edge_weeks=rival_edge_weeks,
                rival_edge_seed=rival_edge_seed,
            ),
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
