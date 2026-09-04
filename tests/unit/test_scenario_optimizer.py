"""Synthetic acceptance tests for joint-scenario CVaR optimization."""

import math
from dataclasses import replace
from itertools import combinations

import pandas as pd
import pytest
from ortools.sat.python import cp_model
from pandas.testing import assert_frame_equal

import squadopt.scenarios.optimization as scenario_optimization
from squadopt.optimization import (
    OptimizationConfig,
    SolverExecutionError,
    SolverStatus,
    optimize_squad,
)
from squadopt.prediction import PredictionProvenance, prepare_optimizer_projection
from squadopt.scenarios import (
    ScenarioConfig,
    ScenarioConfigurationError,
    ScenarioOptimizationConfig,
    ScenarioSet,
    ScenarioTarget,
    ScenarioValidationError,
    optimize_scenario_aware_squad,
)
from squadopt.scenarios.models import _scenario_fingerprint

TARGET = ScenarioTarget("2026-27", 1)


def _scenario_set(players: pd.DataFrame, points: pd.DataFrame) -> ScenarioSet:
    provenance = PredictionProvenance(
        model_name="synthetic-scenario-optimizer",
        model_version="1.0.0",
        feature_contract_version="synthetic-features-v1",
        training_cutoff="2025-26:GW38",
        training_data_fingerprint="a" * 64,
    )
    snapshot = prepare_optimizer_projection(
        players.drop(columns="expected_points"),
        players.loc[:, ["player_id", "expected_points"]],
        provenance,
    )
    scenario_count = len(points)
    config = ScenarioConfig(
        scenario_count=scenario_count,
        min_history_folds=2,
        min_player_observations=2,
    )
    scenario_ids = tuple(f"scenario-{index:06d}" for index in range(scenario_count))
    aligned = points.loc[:, snapshot.table["player_id"].tolist()].copy(deep=True)
    aligned.index = pd.Index(scenario_ids, name="scenario_id")
    source_fold_ids = tuple(f"2025-26-gw{(index % 2) + 1:02d}" for index in range(scenario_count))
    fingerprint = _scenario_fingerprint(
        snapshot,
        TARGET,
        config,
        scenario_ids,
        source_fold_ids,
        aligned,
    )
    return ScenarioSet(
        projections=snapshot,
        target=TARGET,
        config=config,
        scenario_ids=scenario_ids,
        source_fold_ids=source_fold_ids,
        scenario_points=aligned,
        scenario_fingerprint=fingerprint,
        diagnostics={"synthetic": True},
    )


def _degenerate_points(players: pd.DataFrame, scenario_count: int = 10) -> pd.DataFrame:
    values = {
        row.player_id: [float(row.expected_points)] * scenario_count
        for row in players.itertuples(index=False)
    }
    return pd.DataFrame(values)


def _downside_points(players: pd.DataFrame) -> pd.DataFrame:
    points = _degenerate_points(players)
    points["MID_A"] = [12.0] * 9 + [-30.0]
    return points


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"risk_aversion": -0.1}, r"in \[0, 1\]"),
        ({"risk_aversion": 1.1}, r"in \[0, 1\]"),
        ({"tail_fraction": 0.0}, "strictly between"),
        ({"objective_weight_scale": 0}, "at least 1"),
        ({"contract_version": "future"}, "contract_version"),
    ],
)
def test_invalid_scenario_optimization_config_is_rejected(
    change: dict[str, object], message: str
) -> None:
    with pytest.raises(ScenarioConfigurationError, match=message):
        ScenarioOptimizationConfig(**change)  # type: ignore[arg-type]


def test_risk_weight_uses_round_half_up() -> None:
    config = ScenarioOptimizationConfig(risk_aversion=0.3335, objective_weight_scale=1_000)

    assert config.risk_aversion == 0.334


def test_zero_risk_degenerate_scenarios_equal_the_baseline(
    known_optimum_players: pd.DataFrame,
    small_config: OptimizationConfig,
) -> None:
    baseline = optimize_squad(known_optimum_players, small_config)
    scenarios = _scenario_set(
        known_optimum_players,
        _degenerate_points(known_optimum_players),
    )

    result = optimize_scenario_aware_squad(
        scenarios,
        small_config,
        ScenarioOptimizationConfig(risk_aversion=0.0),
    )

    assert result.solver_status is SolverStatus.OPTIMAL
    assert (
        result.optimization_result.selected_squad["player_id"].tolist()
        == baseline.selected_squad["player_id"].tolist()
    )
    assert (
        result.optimization_result.starting_xi["player_id"].tolist()
        == baseline.starting_xi["player_id"].tolist()
    )
    assert result.optimization_result.captain is not None
    assert baseline.captain is not None
    assert result.optimization_result.captain["player_id"] == baseline.captain["player_id"]
    assert result.scenario_objective_value == pytest.approx(baseline.objective_value)
    assert result.risk_penalty_value == 0.0


def test_full_cvar_aversion_avoids_a_known_downside_player(
    known_optimum_players: pd.DataFrame,
    small_config: OptimizationConfig,
) -> None:
    scenarios = _scenario_set(known_optimum_players, _downside_points(known_optimum_players))

    expected = optimize_scenario_aware_squad(
        scenarios,
        small_config,
        ScenarioOptimizationConfig(risk_aversion=0.0),
    )
    cautious = optimize_scenario_aware_squad(
        scenarios,
        small_config,
        ScenarioOptimizationConfig(risk_aversion=1.0, tail_fraction=0.1),
    )

    assert "MID_A" in set(expected.optimization_result.starting_xi["player_id"])
    assert "MID_A" not in set(cautious.optimization_result.starting_xi["player_id"])
    assert "DEF_A" in set(cautious.optimization_result.starting_xi["player_id"])
    assert cautious.optimization_result.captain is not None
    assert cautious.optimization_result.captain["player_id"] == "FWD_A"
    assert cautious.cvar_score is not None
    assert expected.cvar_score is not None
    assert cautious.cvar_score > expected.cvar_score


def test_reported_objective_matches_the_declared_formula(
    known_optimum_players: pd.DataFrame,
    small_config: OptimizationConfig,
) -> None:
    scenarios = _scenario_set(known_optimum_players, _downside_points(known_optimum_players))
    settings = ScenarioOptimizationConfig(risk_aversion=0.4, tail_fraction=0.15)

    result = optimize_scenario_aware_squad(scenarios, small_config, settings)

    assert result.mean_scenario_score is not None
    assert result.cvar_score is not None
    assert result.mean_bench_score is not None
    expected = (
        0.6 * result.mean_scenario_score
        + 0.4 * result.cvar_score
        + small_config.bench_weight * result.mean_bench_score
    )
    assert result.scenario_objective_value == pytest.approx(expected)
    assert result.risk_penalty_value == pytest.approx(
        0.4 * (result.mean_scenario_score - result.cvar_score)
    )
    assert result.diagnostics["tail_count"] == 2
    assert result.scenario_evaluation is not None
    assert result.scenario_evaluation.metrics.worst_fraction_count == 2


@pytest.mark.parametrize(
    ("risk_aversion", "tail_fraction"),
    [(0.0, 0.1), (0.4, 0.2), (1.0, 0.3)],
)
def test_cvar_model_matches_exhaustive_enumeration(
    known_optimum_players: pd.DataFrame,
    small_config: OptimizationConfig,
    risk_aversion: float,
    tail_fraction: float,
) -> None:
    scenarios = _scenario_set(known_optimum_players, _downside_points(known_optimum_players))
    settings = ScenarioOptimizationConfig(
        risk_aversion=risk_aversion,
        tail_fraction=tail_fraction,
    )

    result = optimize_scenario_aware_squad(scenarios, small_config, settings)

    points = scenarios.scenario_points
    best_objective = -math.inf
    positions = {
        position: known_optimum_players.loc[
            known_optimum_players["position"] == position, "player_id"
        ].tolist()
        for position in ("GK", "DEF", "MID", "FWD")
    }
    for goalkeeper in positions["GK"]:
        for defender in positions["DEF"]:
            for midfielder in positions["MID"]:
                for forward in positions["FWD"]:
                    squad = (goalkeeper, defender, midfielder, forward)
                    for starters in combinations(squad, small_config.starting_size):
                        if goalkeeper not in starters or forward not in starters:
                            continue
                        bench_player = next(player for player in squad if player not in starters)
                        for captain in starters:
                            scores = points.loc[:, list(starters)].sum(axis=1) + points[captain]
                            tail_count = math.ceil(settings.tail_fraction * len(scores))
                            cvar = float(scores.sort_values().iloc[:tail_count].mean())
                            objective = (
                                (1.0 - settings.risk_aversion) * float(scores.mean())
                                + settings.risk_aversion * cvar
                                + small_config.bench_weight * float(points[bench_player].mean())
                            )
                            best_objective = max(best_objective, objective)

    assert result.scenario_objective_value == pytest.approx(best_objective)


def test_negative_scenario_points_are_valid_objective_coefficients(
    known_optimum_players: pd.DataFrame,
    small_config: OptimizationConfig,
) -> None:
    scenarios = _scenario_set(known_optimum_players, _downside_points(known_optimum_players))

    result = optimize_scenario_aware_squad(
        scenarios,
        small_config,
        ScenarioOptimizationConfig(risk_aversion=0.5),
    )

    assert result.solver_status is SolverStatus.OPTIMAL
    assert result.scenario_evaluation is not None
    assert float(scenarios.scenario_points.min().min()) < 0.0
    assert all(math.isfinite(value) for value in result.scenario_evaluation.scenario_scores)


def test_inputs_are_not_mutated_and_result_is_deterministic(
    known_optimum_players: pd.DataFrame,
    small_config: OptimizationConfig,
) -> None:
    scenarios = _scenario_set(known_optimum_players, _downside_points(known_optimum_players))
    before_players = scenarios.projections.table.copy(deep=True)
    before_points = scenarios.scenario_points.copy(deep=True)
    settings = ScenarioOptimizationConfig(risk_aversion=0.5)

    first = optimize_scenario_aware_squad(scenarios, small_config, settings)
    second = optimize_scenario_aware_squad(scenarios, small_config, settings)

    assert_frame_equal(scenarios.projections.table, before_players)
    assert_frame_equal(scenarios.scenario_points, before_points)
    assert (
        first.optimization_result.selected_squad["player_id"].tolist()
        == second.optimization_result.selected_squad["player_id"].tolist()
    )
    assert (
        first.optimization_result.starting_xi["player_id"].tolist()
        == second.optimization_result.starting_xi["player_id"].tolist()
    )
    assert first.scenario_objective_value == second.scenario_objective_value


def test_result_rejects_an_evaluation_from_another_scenario_set(
    known_optimum_players: pd.DataFrame,
    small_config: OptimizationConfig,
) -> None:
    scenarios = _scenario_set(
        known_optimum_players,
        _degenerate_points(known_optimum_players),
    )
    result = optimize_scenario_aware_squad(scenarios, small_config)

    with pytest.raises(ScenarioValidationError, match="optimized scenario_fingerprint"):
        replace(result, scenario_fingerprint="b" * 64)


def test_valid_but_budget_infeasible_problem_is_structured(
    known_optimum_players: pd.DataFrame,
    small_config: OptimizationConfig,
) -> None:
    scenarios = _scenario_set(
        known_optimum_players,
        _degenerate_points(known_optimum_players),
    )

    result = optimize_scenario_aware_squad(
        scenarios,
        replace(small_config, budget_tenths=0),
        ScenarioOptimizationConfig(risk_aversion=0.5),
    )

    assert result.solver_status is SolverStatus.INFEASIBLE
    assert result.scenario_evaluation is None
    assert result.scenario_objective_value is None
    assert result.cvar_score is None


def test_unknown_solver_status_is_structured(
    known_optimum_players: pd.DataFrame,
    small_config: OptimizationConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scenarios = _scenario_set(
        known_optimum_players,
        _degenerate_points(known_optimum_players),
    )
    monkeypatch.setattr(scenario_optimization, "_solve", lambda model, solver: cp_model.UNKNOWN)

    result = optimize_scenario_aware_squad(scenarios, small_config)

    assert result.solver_status is SolverStatus.UNKNOWN
    assert result.scenario_evaluation is None
    assert result.scenario_objective_value is None


def test_unsafe_integer_range_is_rejected_before_model_construction(
    known_optimum_players: pd.DataFrame,
    small_config: OptimizationConfig,
) -> None:
    points = _degenerate_points(known_optimum_players, scenario_count=2)
    points.loc[:, "MID_A"] = 5.0e15
    scenarios = _scenario_set(known_optimum_players, points)

    with pytest.raises(SolverExecutionError, match="safe CP-SAT integer range"):
        optimize_scenario_aware_squad(scenarios, small_config)
