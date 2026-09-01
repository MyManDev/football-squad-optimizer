"""Baseline player projections and the optimizer-ready projection table.

The baseline is deliberately simple and deterministic. Its purpose is to make the
end-to-end pipeline reproducible and testable, not to claim predictive accuracy.
"""

from squadopt.prediction.baseline import baseline_expected_points
from squadopt.prediction.components import (
    COMPONENT_EVIDENCE_STATUSES,
    COMPONENT_MODEL_ROUTE,
    COMPONENT_PREDICTION_CONTRACT_VERSION,
    COMPONENT_PREDICTION_ROUTES,
    DIRECT_CONTROL_ROUTE,
    EVIDENCE_NOT_REQUESTED,
    START_COMPONENT_UNAVAILABLE,
    ComponentPredictionSnapshot,
    prepare_component_prediction,
)
from squadopt.prediction.config import (
    DEFAULT_OPENING_EXPECTED_POINTS,
    DEFAULT_PROJECTION_CONFIG,
    FITTED_OPENING_PRICE_COEFFICIENT,
    BaselineProjectionConfig,
    PredictionConfigurationError,
    PredictionError,
    required_feature_columns,
)
from squadopt.prediction.factors import (
    BASELINE_FORM_WINDOW,
    FEATURE_GENERATION_CONTRACT_VERSION,
    FormWindowMapping,
)
from squadopt.prediction.integration import (
    PREDICTION_TO_OPTIMIZATION_CONTRACT_VERSION,
    PREDICTION_VALUE_COLUMNS,
    PredictionProvenance,
    PredictionSnapshot,
    prepare_optimizer_projection,
)
from squadopt.prediction.learned import (
    RIDGE_FEATURE_CONTRACT_VERSION,
    RIDGE_MODEL_NAME,
    RIDGE_MODEL_VERSION,
    FittedRidgePredictor,
    RidgeProjectionConfig,
    fit_ridge_predictor,
    predict_ridge_expected_points,
)
from squadopt.prediction.minutes import (
    ExpectedMinutesConfig,
    MinutesProjection,
    appearance_probability,
    expected_minutes,
)
from squadopt.prediction.opening import (
    ROSTER_COLUMN_MAP,
    build_opening_projection_table,
)
from squadopt.prediction.production import (
    ProductionProjection,
    ProductionProjectionConfig,
    expected_points_per_90,
    production_component_prediction,
    production_projection,
)
from squadopt.prediction.projection import build_projection_table

__all__ = [
    "BASELINE_FORM_WINDOW",
    "COMPONENT_EVIDENCE_STATUSES",
    "COMPONENT_MODEL_ROUTE",
    "COMPONENT_PREDICTION_CONTRACT_VERSION",
    "COMPONENT_PREDICTION_ROUTES",
    "DEFAULT_OPENING_EXPECTED_POINTS",
    "DEFAULT_PROJECTION_CONFIG",
    "DIRECT_CONTROL_ROUTE",
    "EVIDENCE_NOT_REQUESTED",
    "FEATURE_GENERATION_CONTRACT_VERSION",
    "FITTED_OPENING_PRICE_COEFFICIENT",
    "PREDICTION_TO_OPTIMIZATION_CONTRACT_VERSION",
    "PREDICTION_VALUE_COLUMNS",
    "RIDGE_FEATURE_CONTRACT_VERSION",
    "RIDGE_MODEL_NAME",
    "RIDGE_MODEL_VERSION",
    "ROSTER_COLUMN_MAP",
    "START_COMPONENT_UNAVAILABLE",
    "BaselineProjectionConfig",
    "ComponentPredictionSnapshot",
    "ExpectedMinutesConfig",
    "FittedRidgePredictor",
    "FormWindowMapping",
    "MinutesProjection",
    "PredictionConfigurationError",
    "PredictionError",
    "PredictionProvenance",
    "PredictionSnapshot",
    "ProductionProjection",
    "ProductionProjectionConfig",
    "RidgeProjectionConfig",
    "appearance_probability",
    "baseline_expected_points",
    "build_opening_projection_table",
    "build_projection_table",
    "expected_minutes",
    "expected_points_per_90",
    "fit_ridge_predictor",
    "predict_ridge_expected_points",
    "prepare_component_prediction",
    "prepare_optimizer_projection",
    "production_component_prediction",
    "production_projection",
    "required_feature_columns",
]
