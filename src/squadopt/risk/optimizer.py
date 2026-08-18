"""Conformal lower-bound objective layered over the shared CP-SAT optimizer."""

import math
from decimal import Decimal, InvalidOperation
from numbers import Integral, Real

import pandas as pd

from squadopt.optimization import (
    OptimizationConfig,
    OptimizationResult,
    OptimizationValidationError,
)
from squadopt.optimization.coefficients import objective_coefficients, sort_players_by_id
from squadopt.optimization.optimizer import _optimize_squad_with_objective_points
from squadopt.optimization.validation import validate_players
from squadopt.risk.config import RiskOptimizationConfig
from squadopt.risk.errors import RiskConfigurationError, RiskValidationError
from squadopt.risk.models import RiskAwareOptimizationResult
from squadopt.uncertainty import (
    INTERVAL_LOWER_COLUMN,
    INTERVAL_UPPER_COLUMN,
    UNCERTAINTY_GROUP_COLUMN,
    UNCERTAINTY_OBSERVATIONS_COLUMN,
    UNCERTAINTY_SOURCE_COLUMN,
    UNCERTAINTY_STDDEV_COLUMN,
    CalibratedProjectionResult,
)

RISK_ADJUSTED_POINTS_COLUMN = "risk_adjusted_points"
_ALLOWED_UNCERTAINTY_SOURCES = {
    "player_shrunk",
    "pooled_fallback",
    "position",
    "position_fallback",
    # projection_uncertainty_v2 (position by fixture group) sources:
    "position_fixture_group",
    "blank_zero",
}
_UNCERTAINTY_COLUMNS = (
    INTERVAL_LOWER_COLUMN,
    INTERVAL_UPPER_COLUMN,
    UNCERTAINTY_GROUP_COLUMN,
    UNCERTAINTY_SOURCE_COLUMN,
    UNCERTAINTY_OBSERVATIONS_COLUMN,
    UNCERTAINTY_STDDEV_COLUMN,
)


def _decimal(value: object, label: str) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (Real, Decimal)):
        raise RiskValidationError(f"{label} must be a finite number.")
    try:
        number = Decimal(str(value))
    except (InvalidOperation, OverflowError, ValueError) as error:
        raise RiskValidationError(f"{label} must be a finite number.") from error
    if not number.is_finite():
        raise RiskValidationError(f"{label} must be a finite number.")
    return number


def _valid_digest(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _risk_adjusted_table(
    calibrated: CalibratedProjectionResult,
    optimization_config: OptimizationConfig,
    risk_config: RiskOptimizationConfig,
) -> tuple[pd.DataFrame, dict[object, Decimal]]:
    if not isinstance(calibrated, CalibratedProjectionResult):
        raise RiskValidationError("calibrated must be a CalibratedProjectionResult instance.")
    if not _valid_digest(calibrated.calibration_fingerprint):
        raise RiskValidationError("calibration_fingerprint must be a 64-character SHA-256 digest.")

    table = calibrated.table.copy(deep=True)
    duplicate_columns = table.columns[table.columns.duplicated()].tolist()
    if duplicate_columns:
        raise RiskValidationError(
            f"Calibrated projections contain duplicate columns: {duplicate_columns!r}."
        )
    if RISK_ADJUSTED_POINTS_COLUMN in table.columns:
        raise RiskValidationError(
            f"Calibrated projections already contain reserved output column "
            f"{RISK_ADJUSTED_POINTS_COLUMN!r}."
        )
    try:
        table = validate_players(table, optimization_config)
    except OptimizationValidationError as error:
        raise RiskValidationError(str(error)) from error
    missing = [column for column in _UNCERTAINTY_COLUMNS if column not in table.columns]
    if missing:
        raise RiskValidationError(f"Calibrated projections are missing columns: {missing!r}.")
    if bool(table.loc[:, list(_UNCERTAINTY_COLUMNS)].isna().any().any()):
        raise RiskValidationError("Calibrated uncertainty columns contain missing values.")

    adjusted: list[float] = []
    exact_by_player: dict[object, Decimal] = {}
    weight = Decimal(str(risk_config.risk_aversion))
    columns = (
        table["player_id"].tolist(),
        table["position"].tolist(),
        table["expected_points"].tolist(),
        table[INTERVAL_LOWER_COLUMN].tolist(),
        table[INTERVAL_UPPER_COLUMN].tolist(),
        table[UNCERTAINTY_STDDEV_COLUMN].tolist(),
        table[UNCERTAINTY_GROUP_COLUMN].tolist(),
        table[UNCERTAINTY_SOURCE_COLUMN].tolist(),
        table[UNCERTAINTY_OBSERVATIONS_COLUMN].tolist(),
    )
    for (
        player_id,
        position,
        expected_value,
        lower_value,
        upper_value,
        stddev_value,
        group,
        source,
        observations,
    ) in zip(*columns, strict=True):
        expected = _decimal(expected_value, "expected_points")
        lower = _decimal(lower_value, INTERVAL_LOWER_COLUMN)
        upper = _decimal(upper_value, INTERVAL_UPPER_COLUMN)
        stddev = _decimal(stddev_value, UNCERTAINTY_STDDEV_COLUMN)
        if lower > expected or upper < expected:
            raise RiskValidationError(
                "Prediction intervals must contain expected_points inclusively."
            )
        if stddev < 0:
            raise RiskValidationError("expected_points_stddev must be non-negative.")
        # v1 labels the group by position; v2 by "<position>/<fixture group>". Either
        # way the label must name this row's position.
        group_position = str(group).split("/", 1)[0]
        if group_position != position:
            raise RiskValidationError("uncertainty_group must match the canonical position.")
        if source not in _ALLOWED_UNCERTAINTY_SOURCES:
            raise RiskValidationError("uncertainty_source must be a supported calibrated source.")
        blank_row = source == "blank_zero"
        if (
            isinstance(observations, bool)
            or not isinstance(observations, Integral)
            or int(observations) < (0 if blank_row else 2)
        ):
            raise RiskValidationError("uncertainty_observations must be an integer of at least 2.")

        value = expected - weight * (expected - lower)
        if not value.is_finite():
            raise RiskValidationError("Risk-adjusted points must remain finite.")
        try:
            display_value = float(value)
        except (OverflowError, ValueError) as error:
            raise RiskValidationError("Risk-adjusted points exceed the supported range.") from error
        if not math.isfinite(display_value):
            raise RiskValidationError("Risk-adjusted points exceed the supported range.")
        if player_id in exact_by_player:
            raise RiskValidationError("Calibrated projections contain duplicate player_id values.")
        exact_by_player[player_id] = value
        adjusted.append(display_value)

    result = table.copy(deep=True)
    result[RISK_ADJUSTED_POINTS_COLUMN] = adjusted
    return result, exact_by_player


def _expected_objective_value(
    players: pd.DataFrame,
    result: OptimizationResult,
    optimization_config: OptimizationConfig,
) -> float | None:
    if not result.has_solution:
        return None
    ordered = sort_players_by_id(players)
    coefficients = objective_coefficients(ordered["expected_points"].tolist(), optimization_config)
    squad_ids = set(result.selected_squad["player_id"].tolist())
    starter_ids = set(result.starting_xi["player_id"].tolist())
    captain_id = result.captain["player_id"] if result.captain is not None else None
    value = 0
    for player_id, (squad, starter, captain) in zip(
        ordered["player_id"].tolist(),
        coefficients,
        strict=True,
    ):
        if player_id in squad_ids:
            value += squad
        if player_id in starter_ids:
            value += starter
        if player_id == captain_id:
            value += captain
    return value / optimization_config.expected_points_scale


def optimize_risk_aware_squad(
    calibrated: CalibratedProjectionResult,
    optimization_config: OptimizationConfig,
    risk_config: RiskOptimizationConfig,
) -> RiskAwareOptimizationResult:
    """Optimize one squad using a convex blend of point and conformal lower bounds."""

    if not isinstance(optimization_config, OptimizationConfig):
        raise RiskConfigurationError("optimization_config must be an OptimizationConfig instance.")
    if not isinstance(risk_config, RiskOptimizationConfig):
        raise RiskConfigurationError("risk_config must be a RiskOptimizationConfig instance.")

    adjusted_table, exact_by_player = _risk_adjusted_table(
        calibrated,
        optimization_config,
        risk_config,
    )
    try:
        optimization_result = _optimize_squad_with_objective_points(
            adjusted_table,
            optimization_config,
            objective_points=exact_by_player,
            objective_contract=risk_config.contract_version,
        )
    except OptimizationValidationError as error:
        raise RiskValidationError(str(error)) from error

    expected_objective = _expected_objective_value(
        adjusted_table,
        optimization_result,
        optimization_config,
    )
    risk_projected_score: float | None = None
    penalty: float | None = None
    if optimization_result.has_solution:
        if optimization_result.captain is None or optimization_result.objective_value is None:
            raise RiskValidationError("A feasible risk decision must contain objective data.")
        projected = sum(
            (
                exact_by_player[player_id]
                for player_id in optimization_result.starting_xi["player_id"].tolist()
            ),
            start=Decimal(0),
        )
        projected += exact_by_player[optimization_result.captain["player_id"]]
        risk_projected_score = float(projected)
        if not math.isfinite(risk_projected_score):
            raise RiskValidationError("Risk-adjusted projected score must be finite.")
        if expected_objective is None:
            raise RiskValidationError("A feasible risk decision must have an expected objective.")
        penalty = expected_objective - optimization_result.objective_value
        if penalty < -1.0 / optimization_config.expected_points_scale:
            raise RiskValidationError("Risk penalty cannot increase the expected-points objective.")
        penalty = max(0.0, penalty)

    return RiskAwareOptimizationResult(
        optimization_result=optimization_result,
        risk_config=risk_config,
        calibration_fingerprint=calibrated.calibration_fingerprint,
        expected_points_objective_value=expected_objective,
        risk_adjusted_projected_score=risk_projected_score,
        risk_penalty_value=penalty,
        diagnostics={
            "contract_version": risk_config.contract_version,
            "configuration_fingerprint": risk_config.configuration_fingerprint,
            "calibration_fingerprint": calibrated.calibration_fingerprint,
            "uncertainty_contract_version": calibrated.diagnostics.get("contract_version"),
            "risk_aversion": risk_config.risk_aversion,
            "adjustment_formula": "mu-lambda*(mu-lower)",
            "point_projection_changed": False,
            "player_dependence_modeled": False,
        },
    )
