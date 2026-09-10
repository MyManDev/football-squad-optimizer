"""Shared squad/lineup constraints and verification for CP-SAT consumers.

Transfer planning owns bank accounting and opts out of static budget enforcement.
Objectives, solver settings and output ordering remain with the caller.
"""

from collections import Counter, defaultdict

import pandas as pd
from ortools.sat.python import cp_model

from squadopt.optimization.config import POSITIONS, OptimizationConfig
from squadopt.optimization.models import SolverExecutionError


def add_decision_constraints(
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


def selected_indices(
    solver: cp_model.CpSolver,
    variables: list[cp_model.IntVar],
) -> list[int]:
    return [index for index, variable in enumerate(variables) if solver.value(variable) == 1]


def verify_solution(
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
