"""OR-Tools CP-SAT implementation of the baseline squad optimizer."""

from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from numbers import Real
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
MIN_TIEBREAK_DETERMINISTIC_TIME = 1e-9


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


def _build_model(
    players: pd.DataFrame,
    config: OptimizationConfig,
    objective_points: Sequence[object],
) -> _ModelArtifacts:
    model = cp_model.CpModel()
    player_count = len(players)
    squad_vars = [model.new_bool_var(f"squad_{index}") for index in range(player_count)]
    starter_vars = [model.new_bool_var(f"starter_{index}") for index in range(player_count)]
    captain_vars = [model.new_bool_var(f"captain_{index}") for index in range(player_count)]

    _add_decision_constraints(
        model,
        players,
        config,
        squad_vars,
        starter_vars,
        captain_vars,
    )

    coefficients = objective_coefficients(objective_points, config)
    bench_coefficients = [coefficient[0] for coefficient in coefficients]
    scaled_points = [coefficient[2] for coefficient in coefficients]
    conservative_objective_bound = sum(
        2 * abs(points) + abs(bench)
        for points, bench in zip(scaled_points, bench_coefficients, strict=True)
    )
    if conservative_objective_bound > CP_SAT_SAFE_INTEGER_MAX:
        raise SolverExecutionError(
            "Scaled expected-points coefficients exceed the safe CP-SAT integer range; "
            "reduce expected_points_scale or inspect projection magnitudes."
        )

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


def _add_decision_constraints(
    model: cp_model.CpModel,
    players: pd.DataFrame,
    config: OptimizationConfig,
    squad_vars: list[cp_model.IntVar],
    starter_vars: list[cp_model.IntVar],
    captain_vars: list[cp_model.IntVar],
    *,
    enforce_budget: bool = True,
) -> None:
    """Add shared squad constraints, optionally leaving affordability to state accounting."""

    player_count = len(players)
    if not (len(squad_vars) == len(starter_vars) == len(captain_vars) == player_count):
        raise SolverExecutionError("Decision variables must align with validated players.")

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

    if enforce_budget:
        prices = [int(value) for value in players["price_tenths"].tolist()]
        model.add(cp_model.LinearExpr.weighted_sum(squad_vars, prices) <= config.budget_tenths)


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


def configure_solver(
    solver: cp_model.CpSolver,
    config: OptimizationConfig,
    time_limit_seconds: float,
    deterministic_time_limit: float | None,
) -> None:
    """Apply this repository's solver settings; the single place they are decided.

    Public because three packages outside this one call it — `planning`, and both
    `scenarios` solvers — and a name that three packages consume is not private.

    Single search worker: CP-SAT's parallel search is nondeterministic, so a repeated
    solve would not be a repeated answer. Callers that record what produced a result read
    the value back from the configured solver rather than writing `1` beside it, so a
    provenance record cannot go on claiming a property this function has stopped providing.
    """

    solver.parameters.max_time_in_seconds = time_limit_seconds
    if deterministic_time_limit is not None:
        solver.parameters.max_deterministic_time = deterministic_time_limit
    solver.parameters.num_search_workers = 1
    solver.parameters.random_seed = config.deterministic_seed


def _deterministic_time_used(solver: cp_model.CpSolver, raw_status: int) -> float:
    """Return CP-SAT deterministic work consumed by a completed solve."""

    try:
        return float(solver.response_proto.deterministic_time)
    except RuntimeError as error:
        # An UNKNOWN result can be injected by a solver boundary test before a response
        # exists. Real CP-SAT calls always attach a response, including UNKNOWN ones.
        if raw_status == cp_model.UNKNOWN:
            return 0.0
        raise SolverExecutionError(
            "CP-SAT returned a status without response diagnostics."
        ) from error


def _remaining_deterministic_time(
    configured_limit: float | None,
    consumed: float,
) -> float | None:
    """Return the deterministic budget left for a secondary solve."""

    if configured_limit is None:
        return None
    return max(0.0, configured_limit - consumed)


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
    model: cp_model.CpModel,
    squad_vars: list[cp_model.IntVar],
    starter_vars: list[cp_model.IntVar],
    captain_vars: list[cp_model.IntVar],
    primary_objective: cp_model.LinearExpr,
    config: OptimizationConfig,
    primary_value: int,
) -> None:
    player_count = len(squad_vars)
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

    model.add(primary_objective == primary_value)
    tiebreak_terms: list[cp_model.LinearExpr] = []
    for rank in range(player_count):
        tiebreak_terms.extend(
            (
                rank * squad_vars[rank],
                starter_weight * rank * starter_vars[rank],
                captain_weight * rank * captain_vars[rank],
            )
        )
    model.minimize(cp_model.LinearExpr.sum(tiebreak_terms))


def _add_decision_exclusions(
    artifacts: _ModelArtifacts,
    players: pd.DataFrame,
    config: OptimizationConfig,
    excluded_decisions: Sequence[OptimizationResult],
) -> None:
    """Cut each complete decision out of the feasible set, and nothing else.

    A legal decision selects exactly ``squad_size`` squad players, ``starting_size``
    starters and one captain, so an excluded decision's own indicator sum reaches
    ``squad_size + starting_size + 1`` only when squad, eleven and captain all match.
    Bounding that sum one lower removes that one complete decision; a decision that
    differs only on the bench is a different decision and stays feasible.
    """

    if isinstance(excluded_decisions, (str, bytes)) or not isinstance(excluded_decisions, Sequence):
        raise InvalidConfigurationError("excluded_decisions must be a sequence of results.")
    index_by_id = {
        player_id: index for index, player_id in enumerate(players["player_id"].tolist())
    }
    bound = config.squad_size + config.starting_size
    for position, decision in enumerate(excluded_decisions):
        if (
            not isinstance(decision, OptimizationResult)
            or not decision.has_solution
            or decision.captain is None
        ):
            raise InvalidConfigurationError(
                f"excluded_decisions[{position}] must be a solved result with a captain."
            )
        squad_ids = decision.selected_squad["player_id"].tolist()
        starter_ids = decision.starting_xi["player_id"].tolist()
        captain_id = decision.captain["player_id"]
        if (
            len(squad_ids) != config.squad_size
            or len(set(squad_ids)) != len(squad_ids)
            or len(starter_ids) != config.starting_size
            or not set(starter_ids) <= set(squad_ids)
            or captain_id not in starter_ids
        ):
            raise InvalidConfigurationError(
                f"excluded_decisions[{position}] is not a complete decision under this "
                "configuration."
            )
        unknown = sorted({str(value) for value in squad_ids if value not in index_by_id})
        if unknown:
            raise InvalidConfigurationError(
                f"excluded_decisions[{position}] names players outside the pool: {unknown[:10]!r}."
            )
        terms = [artifacts.squad_vars[index_by_id[player_id]] for player_id in squad_ids]
        terms.extend(artifacts.starter_vars[index_by_id[player_id]] for player_id in starter_ids)
        terms.append(artifacts.captain_vars[index_by_id[captain_id]])
        artifacts.model.add(cp_model.LinearExpr.sum(terms) <= bound)


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
    *,
    enforce_budget: bool = True,
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

    if enforce_budget:
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


def _validated_objective_points(
    players: pd.DataFrame,
    objective_points: Mapping[object, object] | None,
) -> list[object]:
    if objective_points is None:
        return players["expected_points"].tolist()
    if not isinstance(objective_points, Mapping):
        raise InvalidConfigurationError("objective_points must be a player_id-to-number mapping.")

    expected_ids = set(players["player_id"].tolist())
    observed_ids = set(objective_points)
    if observed_ids != expected_ids:
        missing = sorted(expected_ids - observed_ids, key=str)
        extra = sorted(observed_ids - expected_ids, key=str)
        raise InvalidConfigurationError(
            "objective_points must align exactly with validated player_id values; "
            f"missing={missing[:10]!r}, extra={extra[:10]!r}."
        )

    validated: list[object] = []
    invalid: list[object] = []
    for player_id in players["player_id"].tolist():
        value = objective_points[player_id]
        if isinstance(value, bool) or not isinstance(value, (Real, Decimal)):
            invalid.append(value)
            continue
        try:
            decimal_value = Decimal(str(value))
        except (InvalidOperation, OverflowError, ValueError):
            invalid.append(value)
            continue
        if not decimal_value.is_finite():
            invalid.append(value)
            continue
        validated.append(decimal_value)
    if invalid:
        raise InvalidConfigurationError(
            f"objective_points values must be finite numbers; invalid examples: {invalid[:10]!r}."
        )
    return validated


def _optimize_squad_with_objective_points(
    players: pd.DataFrame,
    config: OptimizationConfig,
    *,
    objective_points: Mapping[object, object] | None,
    objective_contract: str,
    required_player_ids: tuple[int, ...] = (),
    excluded_decisions: Sequence[OptimizationResult] = (),
) -> OptimizationResult:
    """Solve the shared squad model with a validated private objective override."""

    if not isinstance(config, OptimizationConfig):
        raise InvalidConfigurationError("config must be an OptimizationConfig instance.")
    if not isinstance(objective_contract, str) or not objective_contract.strip():
        raise InvalidConfigurationError("objective_contract must be a non-empty string.")
    if not isinstance(required_player_ids, tuple) or any(
        isinstance(v, bool) or not isinstance(v, int) for v in required_player_ids
    ):
        raise InvalidConfigurationError("required_player_ids must be a tuple of integers.")

    validated = validate_players(players, config)
    ordered_players = sort_players_by_id(validated)
    if required_player_ids:
        known = {int(v) for v in ordered_players["player_id"].tolist()}
        unknown = sorted(set(required_player_ids) - known)
        if unknown:
            raise InvalidConfigurationError(
                f"required_player_ids not in the pool: {unknown[:10]!r}."
            )
    ordered_objective_points = _validated_objective_points(ordered_players, objective_points)
    artifacts = _build_model(ordered_players, config, ordered_objective_points)
    if required_player_ids:
        required = set(required_player_ids)
        for index, player_id in enumerate(ordered_players["player_id"].tolist()):
            if int(player_id) in required:
                artifacts.model.add(artifacts.squad_vars[index] == 1)
    if excluded_decisions:
        _add_decision_exclusions(artifacts, ordered_players, config, excluded_decisions)
    started_at = perf_counter()
    deadline = started_at + config.solver_time_limit_seconds

    primary_solver = cp_model.CpSolver()
    configure_solver(
        primary_solver,
        config,
        config.solver_time_limit_seconds,
        config.solver_deterministic_time_limit,
    )
    raw_primary_status = _solve(artifacts.model, primary_solver)
    primary_status = _map_solver_status(raw_primary_status)
    elapsed_after_primary = perf_counter() - started_at
    primary_deterministic_time = _deterministic_time_used(primary_solver, raw_primary_status)

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
        "num_search_workers": primary_solver.parameters.num_search_workers,
        "solver_time_limit_seconds": config.solver_time_limit_seconds,
        "solver_deterministic_time_limit": config.solver_deterministic_time_limit,
        "primary_deterministic_time": primary_deterministic_time,
        "tiebreak_deterministic_time_limit": None,
        "tiebreak_deterministic_time": None,
        "deterministic_time_used": primary_deterministic_time,
        "deterministic_time_budget_exhausted": (
            config.solver_deterministic_time_limit is not None
            and primary_status is not SolverStatus.OPTIMAL
            and primary_deterministic_time
            >= config.solver_deterministic_time_limit - MIN_TIEBREAK_DETERMINISTIC_TIME
        ),
        "rounding_mode": "ROUND_HALF_UP",
        "objective_contract": objective_contract.strip(),
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
    # The tie-break gets at least the primary's own declared budget rather than only
    # its leftover: a secondary solve cut off mid-search returns a FEASIBLE-but-arbitrary
    # optimum, which is the machine-load nondeterminism #192 measured. Reusing the
    # existing budget field adds no configuration surface, so the frozen declaration
    # fingerprints (#43, Route A) are untouched.
    remaining_time = max(deadline - perf_counter(), config.solver_time_limit_seconds)
    remaining_deterministic_time = _remaining_deterministic_time(
        config.solver_deterministic_time_limit,
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
        base_diagnostics["tiebreak_attempted"] = True
        # Hint the secondary solve with the primary's solution: a known-feasible,
        # objective-optimal start turns most tie-break solves into a fast proof
        # instead of a fresh search that the budget then cuts off arbitrarily (#192).
        for variables in (artifacts.squad_vars, artifacts.starter_vars, artifacts.captain_vars):
            for variable in variables:
                artifacts.model.add_hint(variable, primary_solver.value(variable))
        _add_tiebreak_objective(
            artifacts.model,
            artifacts.squad_vars,
            artifacts.starter_vars,
            artifacts.captain_vars,
            artifacts.primary_objective,
            config,
            primary_value,
        )
        tiebreak_solver = cp_model.CpSolver()
        base_diagnostics["tiebreak_deterministic_time_limit"] = remaining_deterministic_time
        configure_solver(
            tiebreak_solver,
            config,
            remaining_time,
            remaining_deterministic_time,
        )
        raw_tiebreak_status = _solve(artifacts.model, tiebreak_solver)
        tiebreak_status = _map_solver_status(raw_tiebreak_status)
        tiebreak_deterministic_time = _deterministic_time_used(
            tiebreak_solver,
            raw_tiebreak_status,
        )
        base_diagnostics["tiebreak_status"] = _raw_status_name(raw_tiebreak_status)
        base_diagnostics["tiebreak_deterministic_time"] = tiebreak_deterministic_time
        base_diagnostics["deterministic_time_used"] = (
            primary_deterministic_time + tiebreak_deterministic_time
        )
        base_diagnostics["deterministic_time_budget_exhausted"] = (
            remaining_deterministic_time is not None
            and tiebreak_status is not SolverStatus.OPTIMAL
            and tiebreak_deterministic_time
            >= remaining_deterministic_time - MIN_TIEBREAK_DETERMINISTIC_TIME
        )
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
    # The bench is an ordered decision, not a set: on an automatic substitution the game
    # walks it top to bottom, so the goalkeeper takes the fixed first slot and the
    # outfield players follow by descending expectation (player id breaks ties, keeping
    # the output deterministic). Index order alone would order them by player id — an
    # accident of determinism, not a choice.
    bench_frame = ordered_players.iloc[bench_indices]
    keeper_rows = bench_frame.loc[bench_frame["position"] == "GK"]
    outfield_rows = bench_frame.loc[bench_frame["position"] != "GK"].sort_values(
        ["expected_points", "player_id"], ascending=[False, True], kind="mergesort"
    )
    bench = pd.concat([keeper_rows, outfield_rows]).reset_index(drop=True).copy(deep=True)
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


def optimize_squad(
    players: pd.DataFrame,
    config: OptimizationConfig,
    *,
    required_player_ids: tuple[int, ...] = (),
    excluded_decisions: Sequence[OptimizationResult] = (),
) -> OptimizationResult:
    """Select a squad, starting XI, bench, and captain for one gameweek.

    ``required_player_ids`` forces those players into the selected squad (not
    necessarily the eleven): the constraint a candidate like "highest projection with
    the crowd's core held" needs. Unknown ids are refused; an infeasible requirement
    is reported by the solver as any other infeasibility.

    ``excluded_decisions`` removes each given complete decision (its squad, starting
    eleven and captain together) from the feasible set, which is how the next-best
    decision after a known optimum is asked for. Only that exact decision is cut, so
    the answer is the best remaining decision under the unchanged objective and
    tie-break. Both empty (the default) is the historical model, bit for bit.
    """

    return _optimize_squad_with_objective_points(
        players,
        config,
        objective_points=None,
        objective_contract="expected_points_v1",
        required_player_ids=required_player_ids,
        excluded_decisions=excluded_decisions,
    )
