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
from squadopt.features.rolling import shifted_rolling_mean, shifted_rolling_sum

__all__ = [
    "DEFAULT_FEATURE_CONFIG",
    "FEATURE_STEMS",
    "MINUTES_PER_FULL_MATCH",
    "FeatureConfig",
    "FeatureConfigurationError",
    "FeatureError",
    "build_feature_dataset",
    "feature_column_names",
    "per_90_feature_name",
    "rolling_feature_name",
    "shifted_rolling_mean",
    "shifted_rolling_sum",
]
