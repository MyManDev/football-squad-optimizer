"""Leakage-safe feature engineering.

Features for a target gameweek are built only from earlier gameweeks. Every
time-dependent aggregation passes through a single shifted-rolling primitive, so
the timing rule has one implementation and one place to audit.
"""

from squadopt.features.builder import build_feature_dataset
from squadopt.features.config import (
    DEFAULT_FEATURE_CONFIG,
    FEATURE_STEMS,
    MINUTES_PER_FULL_MATCH,
    FeatureConfig,
    FeatureConfigurationError,
    FeatureError,
    feature_column_names,
    per_90_feature_name,
    rolling_feature_name,
)
from squadopt.features.cross_season import (
    CROSS_SEASON_COLUMNS,
    DEFAULT_CROSS_SEASON_CONFIG,
    PRIOR_MINUTES_COLUMN,
    PRIOR_RATE_COLUMN,
    CrossSeasonConfig,
    attach_cross_season_features,
    cross_season_features,
)
from squadopt.features.rolling import shifted_rolling_mean, shifted_rolling_sum

__all__ = [
    "CROSS_SEASON_COLUMNS",
    "DEFAULT_CROSS_SEASON_CONFIG",
    "DEFAULT_FEATURE_CONFIG",
    "FEATURE_STEMS",
    "MINUTES_PER_FULL_MATCH",
    "PRIOR_MINUTES_COLUMN",
    "PRIOR_RATE_COLUMN",
    "CrossSeasonConfig",
    "FeatureConfig",
    "FeatureConfigurationError",
    "FeatureError",
    "attach_cross_season_features",
    "build_feature_dataset",
    "cross_season_features",
    "feature_column_names",
    "per_90_feature_name",
    "rolling_feature_name",
    "shifted_rolling_mean",
    "shifted_rolling_sum",
]
