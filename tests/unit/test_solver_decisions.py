"""The common squad boundary preserves affordability ownership and model ordering."""

from dataclasses import replace

import pandas as pd
import pytest
from ortools.sat.python import cp_model

from squadopt.optimization import OptimizationConfig, SolverExecutionError
from squadopt.optimization import optimizer as baseline
from squadopt.optimization.decisions import (
    add_decision_constraints,
    selected_indices,
    verify_solution,
)
from squadopt.planning import optimizer as planning


def test_legacy_private_imports_and_planner_share_the_same_helpers() -> None:
    assert (
        baseline._add_decision_constraints
        is planning._add_decision_constraints
        is (add_decision_constraints)
    )
    assert baseline._selected_indices is planning._selected_indices is selected_indices
    assert baseline._verify_solution is planning._verify_solution is verify_solution


@pytest.mark.parametrize("enforce_budget", [False, True])
def test_static_budget_is_optional_but_other_squad_constraints_remain(
    known_optimum_players: pd.DataFrame,
    small_config: OptimizationConfig,
    enforce_budget: bool,
) -> None:
    players = known_optimum_players
    config = replace(small_config, budget_tenths=1)
    model = cp_model.CpModel()
    variables = [
        [model.new_bool_var(f"{role}_{index}") for index in range(len(players))]
        for role in ("squad", "starter", "captain")
    ]
    roles = (
        {"GK_A", "DEF_A", "MID_A", "FWD_A"},
        {"GK_A", "MID_A", "FWD_A"},
        {"MID_A"},
    )
    for role_vars, chosen in zip(variables, roles, strict=True):
        for variable, player_id in zip(role_vars, players.player_id, strict=True):
            model.add(variable == int(player_id in chosen))
    add_decision_constraints(model, players, config, *variables, enforce_budget=enforce_budget)
    solver = cp_model.CpSolver()

    status = solver.solve(model)

    if enforce_budget:
        assert status == cp_model.INFEASIBLE
    else:
        assert status == cp_model.OPTIMAL
        indices = [selected_indices(solver, role_vars) for role_vars in variables]
        verify_solution(players, config, *indices, enforce_budget=False)
        with pytest.raises(SolverExecutionError, match="internal verification: budget\\."):
            verify_solution(players, config, *indices)
        captain_outside_xi = [players.player_id.tolist().index("DEF_A")]
        with pytest.raises(SolverExecutionError, match="captain/starter relation"):
            verify_solution(
                players, config, indices[0], indices[1], captain_outside_xi, enforce_budget=False
            )


def test_misaligned_variables_are_refused_before_any_constraint_is_added(
    known_optimum_players: pd.DataFrame,
    small_config: OptimizationConfig,
) -> None:
    model = cp_model.CpModel()
    with pytest.raises(SolverExecutionError, match="align with validated players"):
        add_decision_constraints(model, known_optimum_players, small_config, [], [], [])

    assert len(model.proto.constraints) == 0


def test_selected_indices_keep_model_order() -> None:
    model = cp_model.CpModel()
    variables = [model.new_bool_var(name) for name in ("z", "a", "m")]
    for variable, chosen in zip(variables, (1, 0, 1), strict=True):
        model.add(variable == chosen)
    solver = cp_model.CpSolver()
    assert solver.solve(model) == cp_model.OPTIMAL

    assert selected_indices(solver, variables) == [0, 2]
