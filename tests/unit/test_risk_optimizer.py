"""Synthetic acceptance tests for conformal lower-bound squad optimization."""

from dataclasses import replace

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

from squadopt.optimization import OptimizationConfig, SolverStatus, optimize_squad
from squadopt.risk import (
    RISK_ADJUSTED_POINTS_COLUMN,
    RiskOptimizationConfig,
    RiskValidationError,
    optimize_risk_aware_squad,
)
from squadopt.uncertainty import (
    INTERVAL_LOWER_COLUMN,
    INTERVAL_UPPER_COLUMN,
    UNCERTAINTY_GROUP_COLUMN,
    UNCERTAINTY_OBSERVATIONS_COLUMN,
    UNCERTAINTY_SOURCE_COLUMN,
    UNCERTAINTY_STDDEV_COLUMN,
    CalibratedProjectionResult,
)


def _calibrated(players: pd.DataFrame) -> CalibratedProjectionResult:
    radii = {"GK": 1.0, "DEF": 1.0, "MID": 10.0, "FWD": 1.0}
    table = players.copy(deep=True)
    radius = table["position"].map(radii).astype("float64")
    table[UNCERTAINTY_STDDEV_COLUMN] = radius / 2.0
    table[INTERVAL_LOWER_COLUMN] = table["expected_points"] - radius
    table[INTERVAL_UPPER_COLUMN] = table["expected_points"] + radius
    table[UNCERTAINTY_GROUP_COLUMN] = table["position"]
    table[UNCERTAINTY_SOURCE_COLUMN] = "position"
    table[UNCERTAINTY_OBSERVATIONS_COLUMN] = 100
    return CalibratedProjectionResult(
        table=table,
        calibration_fingerprint="a" * 64,
        diagnostics={"point_projection_changed": False},
    )


def test_zero_risk_aversion_is_exactly_the_baseline(
    known_optimum_players: pd.DataFrame,
    small_config: OptimizationConfig,
) -> None:
    baseline = optimize_squad(known_optimum_players, small_config)
    result = optimize_risk_aware_squad(
        _calibrated(known_optimum_players),
        small_config,
        RiskOptimizationConfig(0.0),
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
    assert result.expected_points_objective_value == baseline.objective_value
    assert result.risk_adjusted_objective_value == baseline.objective_value
    assert result.risk_penalty_value == 0.0
    assert result.risk_adjusted_projected_score == baseline.projected_score


def test_full_risk_aversion_changes_the_known_formation_and_captain(
    known_optimum_players: pd.DataFrame,
    small_config: OptimizationConfig,
) -> None:
    result = optimize_risk_aware_squad(
        _calibrated(known_optimum_players),
        small_config,
        RiskOptimizationConfig(1.0),
    )

    decision = result.optimization_result
    assert set(decision.starting_xi["player_id"]) == {"GK_A", "DEF_A", "FWD_A"}
    assert decision.captain is not None
    assert decision.captain["player_id"] == "FWD_A"
    assert (
        decision.selected_squad.loc[
            decision.selected_squad["player_id"].eq("MID_A"),
            RISK_ADJUSTED_POINTS_COLUMN,
        ].item()
        == 0.0
    )
    assert result.expected_points_objective_value is not None
    assert result.risk_adjusted_objective_value is not None
    assert result.risk_penalty_value == pytest.approx(
        result.expected_points_objective_value - result.risk_adjusted_objective_value
    )


def test_decimal_half_up_rule_is_used_for_risk_coefficients(
    known_optimum_players: pd.DataFrame,
    small_config: OptimizationConfig,
) -> None:
    calibrated = _calibrated(known_optimum_players)
    table = calibrated.table.copy(deep=True)
    table.loc[table["player_id"].eq("MID_A"), "expected_points"] = 1.001
    table.loc[table["player_id"].eq("MID_A"), INTERVAL_LOWER_COLUMN] = 0.0
    table.loc[table["player_id"].eq("MID_A"), INTERVAL_UPPER_COLUMN] = 2.002
    calibrated = replace(calibrated, table=table)

    full_bench_weight = replace(small_config, bench_weight=1.0)
    result = optimize_risk_aware_squad(
        calibrated,
        full_bench_weight,
        RiskOptimizationConfig(0.5),
    )

    adjusted = result.optimization_result.selected_squad.loc[
        result.optimization_result.selected_squad["player_id"].eq("MID_A"),
        RISK_ADJUSTED_POINTS_COLUMN,
    ].item()
    assert adjusted == pytest.approx(0.5005)
    assert result.risk_adjusted_objective_value == 19.501


def test_negative_conformal_lower_bounds_are_valid_objective_values(
    known_optimum_players: pd.DataFrame,
    small_config: OptimizationConfig,
) -> None:
    calibrated = _calibrated(known_optimum_players)
    table = calibrated.table.copy(deep=True)
    table.loc[table["player_id"].eq("MID_A"), INTERVAL_LOWER_COLUMN] = -20.0
    table.loc[table["player_id"].eq("MID_A"), INTERVAL_UPPER_COLUMN] = 30.0

    result = optimize_risk_aware_squad(
        replace(calibrated, table=table),
        small_config,
        RiskOptimizationConfig(1.0),
    )

    selected_mid = result.optimization_result.selected_squad.loc[
        result.optimization_result.selected_squad["position"].eq("MID"),
        RISK_ADJUSTED_POINTS_COLUMN,
    ].item()
    assert result.solver_status is SolverStatus.OPTIMAL
    assert selected_mid == -9.0
    assert result.risk_penalty_value is not None
    assert result.risk_penalty_value > 0.0


def test_inputs_are_not_mutated_and_results_are_deterministic(
    known_optimum_players: pd.DataFrame,
    small_config: OptimizationConfig,
) -> None:
    calibrated = _calibrated(known_optimum_players)
    before = calibrated.table.copy(deep=True)

    first = optimize_risk_aware_squad(
        calibrated,
        small_config,
        RiskOptimizationConfig(0.5),
    )
    second = optimize_risk_aware_squad(
        calibrated,
        small_config,
        RiskOptimizationConfig(0.5),
    )

    assert_frame_equal(calibrated.table, before)
    assert (
        first.optimization_result.selected_squad["player_id"].tolist()
        == second.optimization_result.selected_squad["player_id"].tolist()
    )
    assert (
        first.optimization_result.starting_xi["player_id"].tolist()
        == second.optimization_result.starting_xi["player_id"].tolist()
    )
    assert first.optimization_result.captain is not None
    assert second.optimization_result.captain is not None
    assert (
        first.optimization_result.captain["player_id"]
        == second.optimization_result.captain["player_id"]
    )


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda frame: frame.drop(columns=[INTERVAL_LOWER_COLUMN]), "missing columns"),
        (
            lambda frame: frame.assign(**{INTERVAL_LOWER_COLUMN: frame["expected_points"] + 1}),
            "must contain expected_points",
        ),
        (
            lambda frame: frame.assign(**{UNCERTAINTY_GROUP_COLUMN: "MID"}),
            "must match",
        ),
        (
            lambda frame: frame.assign(**{UNCERTAINTY_OBSERVATIONS_COLUMN: 1}),
            "at least 2",
        ),
        (
            lambda frame: frame.assign(**{INTERVAL_UPPER_COLUMN: float("inf")}),
            "finite number",
        ),
        (
            lambda frame: frame.assign(**{UNCERTAINTY_STDDEV_COLUMN: -1.0}),
            "non-negative",
        ),
        (
            lambda frame: frame.assign(**{UNCERTAINTY_SOURCE_COLUMN: "invented"}),
            "must be 'position'",
        ),
        (
            lambda frame: frame.assign(**{UNCERTAINTY_OBSERVATIONS_COLUMN: 2.5}),
            "must be an integer",
        ),
    ],
)
def test_invalid_uncertainty_contract_is_rejected(
    known_optimum_players: pd.DataFrame,
    small_config: OptimizationConfig,
    mutation: object,
    message: str,
) -> None:
    calibrated = _calibrated(known_optimum_players)
    mutate = mutation
    assert callable(mutate)
    broken = replace(calibrated, table=mutate(calibrated.table))

    with pytest.raises(RiskValidationError, match=message):
        optimize_risk_aware_squad(broken, small_config, RiskOptimizationConfig())


def test_invalid_fingerprint_is_rejected(
    known_optimum_players: pd.DataFrame,
    small_config: OptimizationConfig,
) -> None:
    calibrated = replace(_calibrated(known_optimum_players), calibration_fingerprint="bad")

    with pytest.raises(RiskValidationError, match="SHA-256"):
        optimize_risk_aware_squad(calibrated, small_config, RiskOptimizationConfig())


def test_reserved_output_column_is_rejected(
    known_optimum_players: pd.DataFrame,
    small_config: OptimizationConfig,
) -> None:
    calibrated = _calibrated(known_optimum_players)
    table = calibrated.table.assign(**{RISK_ADJUSTED_POINTS_COLUMN: 999.0})

    with pytest.raises(RiskValidationError, match="reserved output column"):
        optimize_risk_aware_squad(
            replace(calibrated, table=table),
            small_config,
            RiskOptimizationConfig(),
        )


def test_valid_but_budget_infeasible_problem_is_structured(
    known_optimum_players: pd.DataFrame,
    small_config: OptimizationConfig,
) -> None:
    impossible = replace(small_config, budget_tenths=0)

    result = optimize_risk_aware_squad(
        _calibrated(known_optimum_players),
        impossible,
        RiskOptimizationConfig(1.0),
    )

    assert result.solver_status is SolverStatus.INFEASIBLE
    assert result.expected_points_objective_value is None
    assert result.risk_adjusted_objective_value is None
    assert result.risk_penalty_value is None
