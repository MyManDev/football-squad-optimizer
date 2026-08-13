"""Leakage-safe calibration and evaluation of player projection uncertainty."""

from squadopt.uncertainty.adaptive import (
    PLAYER_UNCERTAINTY_OBSERVATIONS_COLUMN,
    apply_player_adaptive_uncertainty,
    evaluate_player_adaptive_uncertainty,
    fit_player_adaptive_uncertainty,
)
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
    PLAYER_ADAPTIVE_UNCERTAINTY_CONTRACT_VERSION,
    PROJECTION_UNCERTAINTY_CONTRACT_VERSION,
    PlayerAdaptiveUncertaintyConfig,
    UncertaintyConfig,
)
from squadopt.uncertainty.errors import (
    UncertaintyConfigurationError,
    UncertaintyError,
    UncertaintyValidationError,
)
from squadopt.uncertainty.models import (
    AdaptiveGroupCalibration,
    CalibratedProjectionResult,
    GroupCalibration,
    PlayerAdaptiveUncertaintyCalibration,
    PlayerAdaptiveUncertaintyEvaluationResult,
    ProjectionUncertaintyCalibration,
    ResidualScaleSummary,
    UncertaintyEvaluationResult,
    UncertaintyFoldResult,
    UncertaintyMetrics,
)

__all__ = [
    "DEFAULT_UNCERTAINTY_DEVELOPMENT_SEASONS",
    "DEFAULT_UNCERTAINTY_HOLDOUT_SEASON",
    "INTERVAL_LOWER_COLUMN",
    "INTERVAL_UPPER_COLUMN",
    "PLAYER_ADAPTIVE_UNCERTAINTY_CONTRACT_VERSION",
    "PLAYER_UNCERTAINTY_OBSERVATIONS_COLUMN",
    "PROJECTION_UNCERTAINTY_CONTRACT_VERSION",
    "UNCERTAINTY_GROUP_COLUMN",
    "UNCERTAINTY_OBSERVATIONS_COLUMN",
    "UNCERTAINTY_SOURCE_COLUMN",
    "UNCERTAINTY_STDDEV_COLUMN",
    "AdaptiveGroupCalibration",
    "CalibratedProjectionResult",
    "GroupCalibration",
    "PlayerAdaptiveUncertaintyCalibration",
    "PlayerAdaptiveUncertaintyConfig",
    "PlayerAdaptiveUncertaintyEvaluationResult",
    "ProjectionUncertaintyCalibration",
    "ResidualScaleSummary",
    "UncertaintyConfig",
    "UncertaintyConfigurationError",
    "UncertaintyError",
    "UncertaintyEvaluationResult",
    "UncertaintyFoldResult",
    "UncertaintyMetrics",
    "UncertaintyValidationError",
    "apply_player_adaptive_uncertainty",
    "apply_projection_uncertainty",
    "evaluate_player_adaptive_uncertainty",
    "evaluate_projection_uncertainty",
    "fit_player_adaptive_uncertainty",
    "fit_projection_uncertainty",
]
