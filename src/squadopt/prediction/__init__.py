"""Baseline player projections and the optimizer-ready projection table.

The baseline is deliberately simple and deterministic. Its purpose is to make the
end-to-end pipeline reproducible and testable, not to claim predictive accuracy;
stronger models, uncertainty, and backtesting are later work.
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
from squadopt.prediction.projection import build_projection_table

__all__ = [
    "DEFAULT_OPENING_EXPECTED_POINTS",
    "DEFAULT_PROJECTION_CONFIG",
    "BaselineProjectionConfig",
    "PredictionConfigurationError",
    "PredictionError",
    "baseline_expected_points",
    "build_projection_table",
    "required_feature_columns",
]
