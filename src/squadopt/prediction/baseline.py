"""Deterministic baseline expected-points projection.

The baseline exists to give the optimizer a reproducible, testable number, not to
claim predictive accuracy. It is a scoring rate scaled by expected playing time,
which captures the dominant driver of fantasy scoring — whether a player is on the
pitch at all — while staying simple enough to verify by hand.
"""

import math

import pandas as pd

from squadopt.data.schema import POSITIONS
from squadopt.features.config import MINUTES_PER_FULL_MATCH
from squadopt.features.cross_season import PRIOR_MINUTES_COLUMN, PRIOR_RATE_COLUMN
from squadopt.prediction.config import (
    DEFAULT_PROJECTION_CONFIG,
    BaselineProjectionConfig,
    PredictionConfigurationError,
    required_feature_columns,
)


def _opening_fallback(features: pd.DataFrame, config: BaselineProjectionConfig) -> pd.Series:
    """Per-position projection for rows with no prior history at all."""

    values: list[float] = []
    for position in features["position"].tolist():
        key = str(position)
        if key not in POSITIONS:
            raise PredictionConfigurationError(
                f"Cannot project an unknown position {position!r}; expected one of "
                f"{list(POSITIONS)!r}."
            )
        values.append(config.opening_expected_points[key])
    return pd.Series(values, index=features.index, dtype="float64")


def _carried_projection(features: pd.DataFrame) -> pd.Series:
    """Project from a player's earlier seasons, where that record exists.

    Used only when the current season offers no history at all — its opening
    gameweek. The same rate-times-minutes shape as the within-season formula, so a
    player carried over is scored on the same scale as one with recent form.

    Returns all-missing when the feature dataset does not carry the cross-season
    columns, which keeps a caller that never attached them behaving exactly as
    before rather than failing.
    """

    if PRIOR_RATE_COLUMN not in features.columns or PRIOR_MINUTES_COLUMN not in features.columns:
        return pd.Series(float("nan"), index=features.index, dtype="float64")

    rate = features[PRIOR_RATE_COLUMN].astype("float64")
    minutes = features[PRIOR_MINUTES_COLUMN].astype("float64")
    return rate.mul(minutes).div(MINUTES_PER_FULL_MATCH)


def baseline_expected_points(
    features: pd.DataFrame,
    *,
    config: BaselineProjectionConfig | None = None,
) -> pd.Series:
    """Project expected points for every row of a feature dataset.

    Computed as ``points_per_90 * expected_minutes / 90`` from shifted rolling
    features, so a row's projection uses only gameweeks before its own.

    Four cases, in order of precedence:

    - **Within-season history exists**: the formula, clamped at zero.
    - **History exists but no minutes were played in the window**: zero. This is
      not missing information — the player demonstrably did not feature, and the
      expected minutes are zero, so the projection is zero regardless of rate.
    - **No within-season history, but earlier seasons are carried**: the same
      formula applied to the carry-over, so the opening gameweek can rank players
      instead of treating everyone alike. Requires the feature dataset to carry the
      cross-season columns; a caller that never attached them is unaffected.
    - **No record anywhere** (a genuine debut, a new signing from abroad, a
      promoted-team player): the declared per-position fallback. There is truly no
      signal, so the constant is explicit rather than a silent zero.

    The result is always finite and non-negative, because the optimizer rejects
    negative or non-finite projections. Realized points may be negative from cards
    and own goals, but a *projection* may not be.
    """

    if not isinstance(features, pd.DataFrame):
        raise PredictionConfigurationError("baseline_expected_points expects a pandas DataFrame.")

    settings = DEFAULT_PROJECTION_CONFIG if config is None else config
    minutes_column, rate_column = required_feature_columns(settings)

    missing = [
        column
        for column in (minutes_column, rate_column, "position")
        if column not in features.columns
    ]
    if missing:
        raise PredictionConfigurationError(
            f"Feature dataset is missing columns {missing!r} needed by the baseline; "
            "build features with matching windows first."
        )

    expected_minutes = features[minutes_column].astype("float64")
    rate = features[rate_column].astype("float64")

    projected = rate.mul(expected_minutes).div(MINUTES_PER_FULL_MATCH)
    # A known-but-idle history means zero, while no history at all means the player
    # falls through to their earlier seasons. Applying the rate rule first lets the
    # minutes rule override it, and missing minutes always imply a missing rate, so
    # the two cases cannot be confused.
    projected = projected.where(rate.notna(), 0.0)
    projected = projected.where(expected_minutes.notna(), _carried_projection(features))
    # Whatever is still missing has no record anywhere: a genuine debut.
    projected = projected.where(projected.notna(), _opening_fallback(features, settings))
    projected = projected.clip(lower=0.0).astype("float64")

    if not bool(projected.notna().all()):
        raise PredictionConfigurationError(
            "Baseline projection produced missing values, which the optimizer rejects."
        )
    non_finite = [value for value in projected.tolist() if not math.isfinite(value)]
    if non_finite:
        raise PredictionConfigurationError(
            f"Baseline projection produced non-finite values: {non_finite[:10]!r}."
        )

    return projected.rename("expected_points")
