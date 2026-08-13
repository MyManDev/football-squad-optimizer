"""Baseline player projections and the optimizer-ready projection table.

The baseline is deliberately simple and deterministic. Its purpose is to make the
end-to-end pipeline reproducible and testable, not to claim predictive accuracy.
"""

from squadopt.prediction.baseline import baseline_expected_points
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
from squadopt.prediction.opening import (
    ROSTER_COLUMN_MAP,
    build_opening_projection_table,
)
from squadopt.prediction.projection import build_projection_table

__all__ = [
    "BASELINE_FORM_WINDOW",
    "DEFAULT_OPENING_EXPECTED_POINTS",
    "DEFAULT_PROJECTION_CONFIG",
    "FEATURE_GENERATION_CONTRACT_VERSION",
    "FITTED_OPENING_PRICE_COEFFICIENT",
    "PREDICTION_TO_OPTIMIZATION_CONTRACT_VERSION",
    "PREDICTION_VALUE_COLUMNS",
    "RIDGE_FEATURE_CONTRACT_VERSION",
    "RIDGE_MODEL_NAME",
    "RIDGE_MODEL_VERSION",
    "ROSTER_COLUMN_MAP",
    "BaselineProjectionConfig",
    "FittedRidgePredictor",
    "FormWindowMapping",
    "PredictionConfigurationError",
    "PredictionError",
    "PredictionProvenance",
    "PredictionSnapshot",
    "RidgeProjectionConfig",
    "baseline_expected_points",
    "build_opening_projection_table",
    "build_projection_table",
    "fit_ridge_predictor",
    "predict_ridge_expected_points",
    "prepare_optimizer_projection",
    "required_feature_columns",
]
