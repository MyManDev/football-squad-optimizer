"""Leakage-safe calibration and evaluation of player projection uncertainty."""

from squadopt.uncertainty.calibration import (
    INTERVAL_LOWER_COLUMN,
    INTERVAL_UPPER_COLUMN,
    UNCERTAINTY_GROUP_COLUMN,
    UNCERTAINTY_OBSERVATIONS_COLUMN,
    UNCERTAINTY_SOURCE_COLUMN,
    UNCERTAINTY_STDDEV_COLUMN,
    apply_projection_uncertainty,
    evaluate_projection_uncertainty,
    fit_projection_uncertainty,
)
from squadopt.uncertainty.config import (
    DEFAULT_UNCERTAINTY_DEVELOPMENT_SEASONS,
    DEFAULT_UNCERTAINTY_HOLDOUT_SEASON,
    PROJECTION_UNCERTAINTY_CONTRACT_VERSION,
    UncertaintyConfig,
)
from squadopt.uncertainty.errors import (
    UncertaintyConfigurationError,
    UncertaintyError,
    UncertaintyValidationError,
)
from squadopt.uncertainty.models import (
    CalibratedProjectionResult,
    GroupCalibration,
    ProjectionUncertaintyCalibration,
    UncertaintyEvaluationResult,
    UncertaintyFoldResult,
    UncertaintyMetrics,
)

__all__ = [
    "DEFAULT_UNCERTAINTY_DEVELOPMENT_SEASONS",
    "DEFAULT_UNCERTAINTY_HOLDOUT_SEASON",
    "INTERVAL_LOWER_COLUMN",
    "INTERVAL_UPPER_COLUMN",
    "PROJECTION_UNCERTAINTY_CONTRACT_VERSION",
    "UNCERTAINTY_GROUP_COLUMN",
    "UNCERTAINTY_OBSERVATIONS_COLUMN",
    "UNCERTAINTY_SOURCE_COLUMN",
    "UNCERTAINTY_STDDEV_COLUMN",
    "CalibratedProjectionResult",
    "GroupCalibration",
    "ProjectionUncertaintyCalibration",
    "UncertaintyConfig",
    "UncertaintyConfigurationError",
    "UncertaintyError",
    "UncertaintyEvaluationResult",
    "UncertaintyFoldResult",
    "UncertaintyMetrics",
    "UncertaintyValidationError",
    "apply_projection_uncertainty",
    "evaluate_projection_uncertainty",
    "fit_projection_uncertainty",
]
