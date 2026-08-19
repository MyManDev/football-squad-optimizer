"""Tests for the baseline CP-SAT optimizer."""

from dataclasses import replace

import pandas as pd
import pytest
from ortools.sat.python import cp_model
from pandas.testing import assert_frame_equal

from squadopt import (
    InvalidPlayerDataError,
    OptimizationConfig,
    OptimizationResult,
    SolverExecutionError,
    SolverStatus,
    optimize_squad,
)
from squadopt.optimization.optimizer import (
    _map_solver_status,
    _scale_bench_coefficient,
    _scale_expected_points,
)


def _ids(frame: pd.DataFrame) -> set[object]:
    return set(frame["player_id"].tolist())


def test_selects_exact_squad_size(baseline_result: OptimizationResult) -> None:
    assert len(baseline_result.selected_squad) == 15


def test_respects_squad_position_quotas(baseline_result: OptimizationResult) -> None:
    assert baseline_result.selected_squad["position"].value_counts().to_dict() == {
        "DEF": 5,
        "MID": 5,
        "FWD": 3,
        "GK": 2,
    }


def test_respects_binding_budget_constraint(
    known_optimum_players: pd.DataFrame,
    small_config: OptimizationConfig,
) -> None:
    players = known_optimum_players.copy(deep=True)
    players.loc[players["player_id"] == "MID_A", "price_tenths"] = 100

    result = optimize_squad(players, small_config)

    assert result.total_cost_tenths == 200
    assert "MID_A" not in _ids(result.selected_squad)
    assert "MID_B" in _ids(result.selected_squad)


def test_respects_binding_team_limit(
    known_optimum_players: pd.DataFrame,
    small_config: OptimizationConfig,
) -> None:
    players = known_optimum_players.copy(deep=True)
    players.loc[players["player_id"].str.endswith("_A"), "team_id"] = "DOMINANT"
    config = OptimizationConfig(
        budget_tenths=small_config.budget_tenths,
        squad_size=small_config.squad_size,
        squad_position_limits=small_config.squad_position_limits,
        starting_size=small_config.starting_size,
        starting_position_min=small_config.starting_position_min,
        starting_position_max=small_config.starting_position_max,
        max_players_per_team=3,
    )

    result = optimize_squad(players, config)

    assert int((result.selected_squad["team_id"] == "DOMINANT").sum()) == 3


def test_selects_exact_starting_size(baseline_result: OptimizationResult) -> None:
    assert len(baseline_result.starting_xi) == 11


def test_starting_xi_has_exactly_one_goalkeeper(
    baseline_result: OptimizationResult,
) -> None:
    assert int((baseline_result.starting_xi["position"] == "GK").sum()) == 1


def test_respects_formation_bounds(baseline_result: OptimizationResult) -> None:
    counts = baseline_result.starting_xi["position"].value_counts()

    assert 3 <= counts["DEF"] <= 5
    assert 2 <= counts["MID"] <= 5
    assert 1 <= counts["FWD"] <= 3


def test_selects_exactly_one_captain(baseline_result: OptimizationResult) -> None:
    assert baseline_result.captain is not None


def test_captain_is_in_starting_xi(baseline_result: OptimizationResult) -> None:
    assert baseline_result.captain is not None
    assert baseline_result.captain["player_id"] in _ids(baseline_result.starting_xi)


def test_all_starters_are_in_selected_squad(baseline_result: OptimizationResult) -> None:
    assert _ids(baseline_result.starting_xi) <= _ids(baseline_result.selected_squad)


def test_reports_infeasible_problem(
    known_optimum_players: pd.DataFrame,
    small_config: OptimizationConfig,
) -> None:
    config = OptimizationConfig(
        budget_tenths=0,
        squad_size=small_config.squad_size,
        squad_position_limits=small_config.squad_position_limits,
        starting_size=small_config.starting_size,
        starting_position_min=small_config.starting_position_min,
        starting_position_max=small_config.starting_position_max,
        max_players_per_team=small_config.max_players_per_team,
    )

    result = optimize_squad(known_optimum_players, config)

    assert result.solver_status is SolverStatus.INFEASIBLE
    assert not result.has_solution
    assert result.selected_squad.empty
    assert list(result.selected_squad.columns) == list(known_optimum_players.columns)
    assert result.captain is None
    assert result.total_cost_tenths is None
    assert result.objective_value is None


def test_does_not_mutate_input_dataframe(baseline_players: pd.DataFrame) -> None:
    original = baseline_players.copy(deep=True)

    optimize_squad(baseline_players, OptimizationConfig())

    assert_frame_equal(baseline_players, original)


def test_finds_known_small_optimum(
    known_optimum_players: pd.DataFrame,
    small_config: OptimizationConfig,
) -> None:
    result = optimize_squad(known_optimum_players, small_config)

    assert result.solver_status is SolverStatus.OPTIMAL
    assert _ids(result.selected_squad) == {"GK_A", "DEF_A", "MID_A", "FWD_A"}
    assert _ids(result.starting_xi) == {"GK_A", "MID_A", "FWD_A"}
    assert _ids(result.bench) == {"DEF_A"}
    assert result.captain is not None
    assert result.captain["player_id"] == "MID_A"
    assert result.total_cost_tenths == 200
    assert result.projected_score == pytest.approx(31.0)
    assert result.objective_value == pytest.approx(31.4)


def test_tie_breaking_is_deterministic(
    tied_players: pd.DataFrame,
    small_config: OptimizationConfig,
) -> None:
    first = optimize_squad(tied_players.sample(frac=1, random_state=11), small_config)
    second = optimize_squad(tied_players.sample(frac=1, random_state=42), small_config)

    assert first.diagnostics["tiebreak_completed"] is True
    assert _ids(first.selected_squad) == _ids(second.selected_squad)
    assert _ids(first.starting_xi) == _ids(second.starting_xi)
    assert first.captain is not None and second.captain is not None
    assert first.captain["player_id"] == second.captain["player_id"]


def test_deterministic_work_budget_is_shared_by_primary_and_tiebreak(
    tied_players: pd.DataFrame,
    small_config: OptimizationConfig,
) -> None:
    config = replace(
        small_config,
        solver_time_limit_seconds=5.0,
        solver_deterministic_time_limit=0.1,
    )

    first = optimize_squad(tied_players.sample(frac=1, random_state=11), config)
    second = optimize_squad(tied_players.sample(frac=1, random_state=42), config)

    assert first.solver_status is SolverStatus.OPTIMAL
    assert first.diagnostics["solver_deterministic_time_limit"] == 0.1
    primary = float(first.diagnostics["primary_deterministic_time"])
    tiebreak_limit = float(first.diagnostics["tiebreak_deterministic_time_limit"])
    tiebreak = float(first.diagnostics["tiebreak_deterministic_time"])
    total = float(first.diagnostics["deterministic_time_used"])
    assert tiebreak_limit == pytest.approx(max(0.0, 0.1 - primary))
    assert total == pytest.approx(primary + tiebreak)
    assert total > 0.0
    assert _ids(first.selected_squad) == _ids(second.selected_squad)
    assert _ids(first.starting_xi) == _ids(second.starting_xi)
    assert first.captain is not None and second.captain is not None
    assert first.captain["player_id"] == second.captain["player_id"]


def test_integer_price_handling(
    known_optimum_players: pd.DataFrame,
    small_config: OptimizationConfig,
) -> None:
    result = optimize_squad(known_optimum_players, small_config)
    assert isinstance(result.total_cost_tenths, int)

    invalid = known_optimum_players.copy(deep=True)
    invalid["price_tenths"] = invalid["price_tenths"].astype(float)
    with pytest.raises(InvalidPlayerDataError):
        optimize_squad(invalid, small_config)


@pytest.mark.parametrize(
    ("value", "scale", "expected"),
    [
        (6.2374, 1000, 6237),
        (6.2375, 1000, 6238),
        (6.2376, 1000, 6238),
        (0.0005, 1000, 1),
        (2.675, 100, 268),
        (5.12345, 10_000, 51_235),
    ],
)
def test_expected_points_scaling_precision(value: float, scale: int, expected: int) -> None:
    assert _scale_expected_points(value, scale) == expected


def test_bench_coefficient_uses_round_half_up() -> None:
    assert _scale_bench_coefficient(6238, 0.1) == 624


@pytest.mark.parametrize(
    ("raw_status", "expected"),
    [
        (cp_model.OPTIMAL, SolverStatus.OPTIMAL),
        (cp_model.FEASIBLE, SolverStatus.FEASIBLE),
        (cp_model.INFEASIBLE, SolverStatus.INFEASIBLE),
        (cp_model.UNKNOWN, SolverStatus.UNKNOWN),
    ],
)
def test_maps_solver_statuses(raw_status: int, expected: SolverStatus) -> None:
    assert _map_solver_status(raw_status) is expected


def test_model_invalid_status_is_an_execution_error() -> None:
    with pytest.raises(SolverExecutionError):
        _map_solver_status(cp_model.MODEL_INVALID)


def test_preserves_extra_input_columns(
    known_optimum_players: pd.DataFrame,
    small_config: OptimizationConfig,
) -> None:
    known_optimum_players["source_note"] = "synthetic"

    result = optimize_squad(known_optimum_players, small_config)

    assert "source_note" in result.selected_squad.columns
    assert set(result.selected_squad["source_note"]) == {"synthetic"}
