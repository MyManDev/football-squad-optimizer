"""Feasible synthetic and real-manager baselines for decision evaluation."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from numbers import Integral
from types import MappingProxyType
from typing import Final

import pandas as pd
from ortools.sat.python import cp_model

from squadopt.evaluation.models import EvaluationValidationError, FrozenSquadDecision
from squadopt.optimization import OptimizationConfig, SquadOptimizationError
from squadopt.optimization.coefficients import scale_expected_points, sort_players_by_id
from squadopt.optimization.config import POSITIONS
from squadopt.optimization.optimizer import configure_solver
from squadopt.optimization.validation import validate_players

OWNERSHIP_TEMPLATE_V2: Final = "ownership_template_v2"
OWNERSHIP_COLUMN: Final = "ownership"


@dataclass(frozen=True, slots=True)
class OwnershipTemplateResult:
    """A full feasible ownership template and the facts needed to audit it."""

    decision: FrozenSquadDecision
    total_cost_tenths: int
    total_ownership: float
    diagnostics: Mapping[str, object]

    def __post_init__(self) -> None:
        object.__setattr__(self, "diagnostics", MappingProxyType(dict(self.diagnostics)))


def _validated_ownership_pool(
    pool: pd.DataFrame,
    config: OptimizationConfig,
) -> pd.DataFrame:
    if not isinstance(pool, pd.DataFrame):
        raise EvaluationValidationError("pool must be a pandas DataFrame.")
    duplicate_columns = pool.columns[pool.columns.duplicated()].tolist()
    if duplicate_columns:
        raise EvaluationValidationError(
            f"Duplicate ownership-pool columns are not allowed: {duplicate_columns!r}."
        )
    required = ("player_id", "name", "team_id", "position", "price_tenths", OWNERSHIP_COLUMN)
    missing = [column for column in required if column not in pool.columns]
    if missing:
        raise EvaluationValidationError(f"Ownership pool is missing columns: {missing!r}.")

    prepared = pool.copy(deep=True)
    prepared[OWNERSHIP_COLUMN] = pd.to_numeric(prepared[OWNERSHIP_COLUMN], errors="coerce")
    prepared["expected_points"] = prepared[OWNERSHIP_COLUMN]
    try:
        validated = validate_players(prepared, config)
    except SquadOptimizationError as error:
        raise EvaluationValidationError(f"Invalid ownership pool: {error}") from error
    return sort_players_by_id(validated)


def _new_solver(config: OptimizationConfig) -> cp_model.CpSolver:
    solver = cp_model.CpSolver()
    configure_solver(
        solver,
        config,
        config.solver_time_limit_seconds,
        config.solver_deterministic_time_limit,
    )
    return solver


def _solve_lexicographic_selection(
    model: cp_model.CpModel,
    variables: list[cp_model.IntVar],
    coefficients: list[int],
    config: OptimizationConfig,
    *,
    label: str,
) -> list[int]:
    primary = cp_model.LinearExpr.weighted_sum(variables, coefficients)
    model.maximize(primary)
    solver = _new_solver(config)
    status = solver.solve(model)
    if status != cp_model.OPTIMAL:
        status_name = solver.status_name(status)
        raise EvaluationValidationError(
            f"The {label} requires a proven optimum; CP-SAT returned {status_name}."
        )
    primary_value = round(solver.objective_value)

    model.add(primary == primary_value)
    model.minimize(cp_model.LinearExpr.weighted_sum(variables, list(range(len(variables)))))
    tiebreak_solver = _new_solver(config)
    tiebreak_status = tiebreak_solver.solve(model)
    if tiebreak_status != cp_model.OPTIMAL:
        raise EvaluationValidationError(
            f"The {label} deterministic tie-break was not proven optimal."
        )
    return [index for index, variable in enumerate(variables) if tiebreak_solver.value(variable)]


def _select_squad(
    players: pd.DataFrame,
    coefficients: list[int],
    config: OptimizationConfig,
) -> list[int]:
    model = cp_model.CpModel()
    variables = [model.new_bool_var(f"template_squad_{index}") for index in range(len(players))]
    model.add(cp_model.LinearExpr.sum(variables) == config.squad_size)

    for position in POSITIONS:
        indices = players.index[players["position"] == position].tolist()
        model.add(
            cp_model.LinearExpr.sum([variables[index] for index in indices])
            == config.squad_position_limits[position]
        )
    team_indices: defaultdict[object, list[int]] = defaultdict(list)
    for index, team_id in enumerate(players["team_id"].tolist()):
        team_indices[team_id].append(index)
    for indices in team_indices.values():
        model.add(
            cp_model.LinearExpr.sum([variables[index] for index in indices])
            <= config.max_players_per_team
        )
    model.add(
        cp_model.LinearExpr.weighted_sum(
            variables, [int(value) for value in players["price_tenths"].tolist()]
        )
        <= config.budget_tenths
    )
    return _solve_lexicographic_selection(
        model, variables, coefficients, config, label="ownership-template squad"
    )


def _select_lineup(
    squad: pd.DataFrame,
    coefficients: list[int],
    config: OptimizationConfig,
) -> list[int]:
    model = cp_model.CpModel()
    variables = [model.new_bool_var(f"template_starter_{index}") for index in range(len(squad))]
    model.add(cp_model.LinearExpr.sum(variables) == config.starting_size)
    for position in POSITIONS:
        indices = squad.index[squad["position"] == position].tolist()
        expression = cp_model.LinearExpr.sum([variables[index] for index in indices])
        model.add(expression >= config.starting_position_min[position])
        model.add(expression <= config.starting_position_max[position])
    return _solve_lexicographic_selection(
        model, variables, coefficients, config, label="ownership-template starting XI"
    )


def _ownership_order(frame: pd.DataFrame) -> list[object]:
    records = [
        (player_id, float(str(ownership)))
        for player_id, ownership in frame.loc[:, ["player_id", OWNERSHIP_COLUMN]].itertuples(
            index=False, name=None
        )
    ]

    def key(record: tuple[object, float]) -> tuple[float, str]:
        value, ownership = record
        if isinstance(value, Integral) and not isinstance(value, bool):
            identifier = f"{int(value):+030d}"
        else:
            identifier = str(value)
        return (-ownership, identifier)

    return [player_id for player_id, _ in sorted(records, key=key)]


def build_constrained_ownership_template(
    pool: pd.DataFrame,
    config: OptimizationConfig | None = None,
) -> OwnershipTemplateResult:
    """Build the ownership-maximizing legal squad, XI, bench and armband pair."""

    settings = OptimizationConfig() if config is None else config
    if not isinstance(settings, OptimizationConfig):
        raise EvaluationValidationError("config must be an OptimizationConfig instance.")
    players = _validated_ownership_pool(pool, settings)
    coefficients = [
        scale_expected_points(value, settings.expected_points_scale)
        for value in players[OWNERSHIP_COLUMN].tolist()
    ]
    squad_indices = _select_squad(players, coefficients, settings)
    squad = players.iloc[squad_indices].reset_index(drop=True).copy(deep=True)
    squad_coefficients = [
        scale_expected_points(value, settings.expected_points_scale)
        for value in squad[OWNERSHIP_COLUMN].tolist()
    ]
    starter_indices = _select_lineup(squad, squad_coefficients, settings)
    starters = squad.iloc[starter_indices].copy(deep=True)
    starter_ids = tuple(_ownership_order(starters))
    armband_order = _ownership_order(starters)
    bench_frame = squad.loc[~squad["player_id"].isin(starter_ids)].copy(deep=True)
    goalkeeper = bench_frame.loc[bench_frame["position"] == "GK"]
    outfield = bench_frame.loc[bench_frame["position"] != "GK"]
    if len(goalkeeper) != 1 or len(outfield) != 3:
        raise EvaluationValidationError("The ownership-template bench is not 1 GK plus 3 outfield.")
    bench = (goalkeeper.iloc[0]["player_id"], *_ownership_order(outfield))
    decision = FrozenSquadDecision(
        squad=squad,
        starting_xi=starter_ids,
        bench=bench,
        captain_id=armband_order[0],
        vice_captain_id=armband_order[1],
        completion_policy=OWNERSHIP_TEMPLATE_V2,
    )
    return OwnershipTemplateResult(
        decision=decision,
        total_cost_tenths=int(squad["price_tenths"].sum()),
        total_ownership=float(squad[OWNERSHIP_COLUMN].sum()),
        diagnostics={
            "contract_version": OWNERSHIP_TEMPLATE_V2,
            "ownership_scale": settings.expected_points_scale,
            "squad_objective": "maximize_total_ownership",
            "lineup_objective": "maximize_starter_ownership",
            "captain_rule": "most_owned_starter",
            "vice_captain_rule": "second_most_owned_starter",
            "bench_rule": "goalkeeper_then_outfield_ownership_desc",
            "solver_status": "OPTIMAL",
        },
    )


def audit_unconstrained_template_v1(
    pool: pd.DataFrame,
    starter_ids: Sequence[object],
    config: OptimizationConfig | None = None,
) -> Mapping[str, object]:
    """Report what V1 can prove about its XI without inventing a missing bench."""

    settings = OptimizationConfig() if config is None else config
    players = _validated_ownership_pool(pool, settings).set_index("player_id")
    starters = tuple(starter_ids)
    if len(starters) != settings.starting_size or len(starters) != len(set(starters)):
        raise EvaluationValidationError(
            f"V1 starter_ids must contain {settings.starting_size} distinct players."
        )
    missing = [player_id for player_id in starters if player_id not in players.index]
    if missing:
        raise EvaluationValidationError(
            f"Ownership pool does not cover V1 starters: {missing[:10]!r}."
        )
    xi = players.loc[list(starters)]
    team_counts = xi["team_id"].value_counts()
    xi_cost = int(xi["price_tenths"].sum())
    return MappingProxyType(
        {
            "contract_version": "ownership_template_v1_feasibility_audit",
            "starter_count": len(starters),
            "xi_cost_tenths": xi_cost,
            "xi_exceeds_full_squad_budget": xi_cost > settings.budget_tenths,
            "max_players_from_one_team": int(team_counts.max()),
            "team_limit_violated": bool((team_counts > settings.max_players_per_team).any()),
            "full_squad_feasibility": "not_verifiable_v1_has_no_squad_or_bench",
        }
    )


__all__ = [
    "OWNERSHIP_TEMPLATE_V2",
    "OwnershipTemplateResult",
    "audit_unconstrained_template_v1",
    "build_constrained_ownership_template",
]
