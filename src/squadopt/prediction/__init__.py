"""Baseline player projections and the optimizer-ready projection table.

The baseline is deliberately simple and deterministic. Its purpose is to make the
end-to-end pipeline reproducible and testable, not to claim predictive accuracy.
"""

from squadopt.prediction.baseline import baseline_expected_points
from squadopt.prediction.config import (
    DEFAULT_OPENING_EXPECTED_POINTS,
    DEFAULT_PROJECTION_CONFIG,
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
    "ROSTER_COLUMN_MAP",
    "BaselineProjectionConfig",
    "FormWindowMapping",
    "PredictionConfigurationError",
    "PredictionError",
    "baseline_expected_points",
    "build_opening_projection_table",
    "build_projection_table",
    "required_feature_columns",
]
