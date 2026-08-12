"""Construction of the prediction-ready feature dataset."""

import pandas as pd

from squadopt.data.schema import (
    CANONICAL_SORT_COLUMNS,
    PLAYER_TIME_SORT_COLUMNS,
    REQUIRED_COLUMNS,
    canonical_column_order,
)
from squadopt.features.config import (
    DEFAULT_FEATURE_CONFIG,
    MINUTES_PER_FULL_MATCH,
    FeatureConfig,
    FeatureConfigurationError,
    feature_column_names,
    per_90_feature_name,
    rolling_feature_name,
)
from squadopt.features.cross_season import CrossSeasonConfig, attach_cross_season_features
from squadopt.features.rolling import shifted_rolling_mean, shifted_rolling_sum


def _points_per_90(frame: pd.DataFrame, window: int, min_periods: int) -> pd.Series:
    """Scoring rate over the previous gameweeks, as a ratio of shifted sums.

    Total points divided by total minutes, rather than an average of per-gameweek
    rates: a substitute's ten-minute cameo should not carry the same weight as a
    full match, and a per-row ratio would divide by zero for every gameweek a
    player did not feature.

    The rate is undefined, not zero, when a player logged no minutes across the
    whole window. Left missing here, it is resolved by the prediction layer,
    where a player with no minutes is projected from the same information.
    """

    points = shifted_rolling_sum(frame, "total_points", window, min_periods=min_periods)
    minutes = shifted_rolling_sum(frame, "minutes", window, min_periods=min_periods)
    rate = points.div(minutes).mul(MINUTES_PER_FULL_MATCH)
    return rate.where(minutes > 0)


def build_feature_dataset(
    canonical: pd.DataFrame,
    *,
    config: FeatureConfig | None = None,
    cross_season: CrossSeasonConfig | None = None,
) -> pd.DataFrame:
    """Attach leakage-safe rolling features to a canonical player-gameweek dataset.

    A feature for gameweek ``t`` is computed only from gameweeks before ``t``:
    every aggregation is grouped by ``(season, player_id)`` and shifted by one
    gameweek before its window is applied.

    Because the features are already shifted, the realized ``total_points`` on the
    same row is a valid prediction label, and no separate target column is
    produced. A second time shift in the same table would be one more thing to get
    wrong, and it would make the leakage rules harder to audit rather than easier.

    Passing ``cross_season`` also attaches a player's earlier-season carry-over,
    which is what lets an opening gameweek rank players instead of falling back to a
    constant for everyone. It is off by default because it only means anything for a
    panel spanning several seasons, and a caller working within one season should not
    silently gain two always-missing columns.

    Returns an independent copy in canonical row order with a reset index. The
    input frame is never modified, and the result does not depend on the input's
    row order or index.
    """

    if not isinstance(canonical, pd.DataFrame):
        raise FeatureConfigurationError("build_feature_dataset expects a pandas DataFrame.")

    settings = DEFAULT_FEATURE_CONFIG if config is None else config

    missing = [column for column in REQUIRED_COLUMNS if column not in canonical.columns]
    if missing:
        raise FeatureConfigurationError(
            f"Canonical dataset is missing required columns: {missing!r}."
        )

    duplicates = canonical.columns[canonical.columns.duplicated()].tolist()
    if duplicates:
        raise FeatureConfigurationError(f"Duplicate columns are not allowed: {duplicates!r}.")

    collisions = [name for name in feature_column_names(settings) if name in canonical.columns]
    if collisions:
        raise FeatureConfigurationError(
            f"Feature names collide with existing columns: {collisions!r}; "
            "the input already looks like a feature dataset."
        )

    # Sorting once here is what lets the rolling primitive verify rather than
    # re-sort on every call.
    ordered = canonical.sort_values(list(PLAYER_TIME_SORT_COLUMNS), kind="stable").copy(deep=True)

    features: dict[str, pd.Series] = {}
    for window in settings.minutes_windows:
        features[rolling_feature_name("minutes", window)] = shifted_rolling_mean(
            ordered, "minutes", window, min_periods=settings.min_periods
        )
    for window in settings.points_windows:
        features[rolling_feature_name("total_points", window)] = shifted_rolling_mean(
            ordered, "total_points", window, min_periods=settings.min_periods
        )
    features[per_90_feature_name(settings.per_90_window)] = _points_per_90(
        ordered, settings.per_90_window, settings.min_periods
    )

    combined = ordered.assign(**features)
    result = combined.sort_values(list(CANONICAL_SORT_COLUMNS), kind="stable").reset_index(
        drop=True
    )

    canonical_columns = canonical_column_order(
        [column for column in result.columns if column not in features]
    )
    ordered_result = result.loc[:, [*canonical_columns, *feature_column_names(settings)]]

    if cross_season is None:
        return ordered_result
    return attach_cross_season_features(ordered_result, config=cross_season)
