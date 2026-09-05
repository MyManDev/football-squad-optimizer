"""Expected minutes: the availability half of a two-stage projection.

Fantasy scoring is dominated by whether a player is on the pitch at all, and that
question fails differently from how well he plays when he is. An injured first-choice
striker and a fit fringe striker can carry the same recent scoring rate while being
opposite selections. Collapsing both into one regression forces a single model to
explain two unrelated things, and leaves its residual unattributable to either.

This module answers only the first question, and only from signals whose timing can be
proven. Historical availability — the platform's status flags and chance-of-playing
percentages — is deliberately absent: the archive records it after the fact and its
as-of time cannot be recovered, so a coefficient fitted on it would be fitted on
information nobody held at the deadline. Live availability is applied later as a
documented inference rule, which changes what is knowable going forward rather than
what is trained.

What is left is the appearance decomposition — how often a player features, and how
long when he does — plus cross-season carry-over for a player with no current-season
record. Their product is the estimate; the decomposition is what makes it more than a
minutes average, because it distinguishes a rotation risk from a player who is simply
substituted early.
"""

import math
from dataclasses import dataclass
from numbers import Integral, Real
from typing import Final

import numpy as np
import pandas as pd

from squadopt.features import (
    MINUTES_PER_FULL_MATCH,
    PRIOR_MINUTES_COLUMN,
    minutes_per_appearance_feature_name,
    rolling_feature_name,
)
from squadopt.features.config import APPEARANCE_SOURCE_COLUMN
from squadopt.features.fixtures import FIXTURE_FEATURE_COLUMNS
from squadopt.prediction.config import PredictionConfigurationError

# Which rung of the precedence ladder produced a player's estimate. Reported rather
# than discarded, because "we measured this" and "we fell back" are different claims
# and an operator reading a squad is entitled to know which one applies.
MINUTES_FROM_HISTORY: Final = "in_season_history"
MINUTES_FROM_NO_APPEARANCE: Final = "observed_absence"
MINUTES_FROM_CARRY_OVER: Final = "cross_season_carry_over"
MINUTES_UNKNOWN: Final = "no_record"
MINUTES_BLANK_GAMEWEEK: Final = "blank_gameweek"

# How many fixtures a club is assumed to play when the calendar is not supplied.
# One, because a gameweek normally holds one fixture per club and assuming otherwise
# would silently scale every projection.
DEFAULT_FIXTURE_COUNT: Final = 1

# The calendar column this stage reads, named once so it cannot drift from the
# feature layer that produces it.
FIXTURE_COUNT_COLUMN: Final = FIXTURE_FEATURE_COLUMNS[0]


@dataclass(frozen=True, slots=True)
class ExpectedMinutesConfig:
    """Controls for the expected-minutes stage.

    ``window`` selects which appearance decomposition to read, so it must match a
    window the feature dataset was built with.

    ``carry_over_weight`` shrinks a cross-season estimate toward zero. A player with
    no current-season record has, by definition, not yet been picked this season, and
    last season's minutes describe a situation that may no longer hold — a transfer, a
    new manager, a different depth chart. Shrinking states that uncertainty instead of
    projecting last season forward unchanged.
    """

    window: int = 6
    carry_over_weight: float = 0.75

    def __post_init__(self) -> None:
        if isinstance(self.window, bool) or not isinstance(self.window, Integral):
            raise PredictionConfigurationError(f"window must be an integer, got {self.window!r}.")
        window = int(self.window)
        if window < 1:
            raise PredictionConfigurationError(f"window must be at least 1, got {window}.")

        if isinstance(self.carry_over_weight, bool) or not isinstance(self.carry_over_weight, Real):
            raise PredictionConfigurationError(
                f"carry_over_weight must be a number, got {self.carry_over_weight!r}."
            )
        weight = float(self.carry_over_weight)
        if not math.isfinite(weight) or not 0.0 <= weight <= 1.0:
            raise PredictionConfigurationError(
                f"carry_over_weight must be a finite value in [0, 1], got {weight!r}."
            )

        object.__setattr__(self, "window", window)
        object.__setattr__(self, "carry_over_weight", weight)

    @property
    def appearance_rate_column(self) -> str:
        """Feature holding the share of recent gameweeks a player featured in."""

        return rolling_feature_name(APPEARANCE_SOURCE_COLUMN, self.window)

    @property
    def minutes_per_appearance_column(self) -> str:
        """Feature holding the minutes played per gameweek featured."""

        return minutes_per_appearance_feature_name(self.window)

    @property
    def required_columns(self) -> tuple[str, ...]:
        """Feature columns this stage reads."""

        return (self.appearance_rate_column, self.minutes_per_appearance_column)


@dataclass(frozen=True, slots=True)
class MinutesProjection:
    """Expected minutes per player, and which rung produced each value.

    ``expected_minutes`` is missing for a player with no record anywhere. That is not
    a silent gap: the points stage takes over entirely for those players, because a
    price prior estimates points directly and has no per-90 rate to multiply. Leaving
    the value missing here keeps the two claims separable rather than inventing a
    minutes figure to satisfy a formula.
    """

    expected_minutes: pd.Series
    source: pd.Series


def _numeric(features: pd.DataFrame, column: str) -> pd.Series:
    if column not in features.columns:
        raise PredictionConfigurationError(
            f"Feature dataset is missing column {column!r}, which the expected-minutes "
            "stage reads. Build features with a matching appearance window."
        )
    values = features[column]
    if isinstance(values, pd.DataFrame):
        raise PredictionConfigurationError(
            f"Feature dataset contains duplicate {column!r} columns."
        )
    return pd.to_numeric(values, errors="coerce").astype("float64")


def _fixture_count(features: pd.DataFrame) -> pd.Series:
    """Read the target gameweek's fixture count, defaulting to one fixture.

    Pre-match: how many fixtures a club plays is published before the deadline, so it
    is read from the target row rather than shifted. A missing value is treated as one
    fixture rather than as a blank gameweek, because absence of a calendar is not
    evidence of an empty one.
    """

    if FIXTURE_COUNT_COLUMN not in features.columns:
        return pd.Series(float(DEFAULT_FIXTURE_COUNT), index=features.index, dtype="float64")
    raw = features[FIXTURE_COUNT_COLUMN]
    if isinstance(raw, pd.DataFrame):
        raise PredictionConfigurationError(
            f"Feature dataset contains duplicate {FIXTURE_COUNT_COLUMN!r} columns."
        )
    counts = pd.to_numeric(raw, errors="coerce").astype("float64")
    negative = counts.notna() & counts.map(math.isfinite) & counts.lt(0.0)
    if bool(negative.any()):
        raise PredictionConfigurationError(
            f"{FIXTURE_COUNT_COLUMN!r} may not be negative; a club cannot play fewer than "
            "no fixtures."
        )
    invalid = raw.notna() & counts.isna()
    invalid |= raw.map(lambda value: isinstance(value, (bool, np.bool_))).fillna(False)
    invalid |= counts.notna() & (~counts.map(math.isfinite) | counts.mod(1.0).ne(0.0))
    if bool(invalid.any()):
        raise PredictionConfigurationError(
            f"{FIXTURE_COUNT_COLUMN!r} must contain only missing values or non-negative "
            "integer fixture counts."
        )
    return counts.fillna(float(DEFAULT_FIXTURE_COUNT))


def appearance_probability(
    features: pd.DataFrame,
    *,
    config: ExpectedMinutesConfig | None = None,
) -> pd.Series:
    """Return the shifted empirical probability of any gameweek appearance.

    Missing history remains missing, while an empty target calendar overrides history
    with zero. A double gameweek does not multiply the probability: the event is still
    whether the player appears at least once in the gameweek.
    """

    settings = ExpectedMinutesConfig() if config is None else config
    if not isinstance(settings, ExpectedMinutesConfig):
        raise PredictionConfigurationError("config must be an ExpectedMinutesConfig.")
    if not isinstance(features, pd.DataFrame):
        raise PredictionConfigurationError("appearance_probability expects a pandas DataFrame.")

    raw = features.get(settings.appearance_rate_column)
    probability = _numeric(features, settings.appearance_rate_column)
    assert raw is not None  # _numeric has already reported a missing column.
    invalid = raw.notna() & probability.isna()
    invalid |= raw.map(lambda value: isinstance(value, (bool, np.bool_))).fillna(False)
    invalid |= probability.notna() & (~probability.map(math.isfinite) | ~probability.between(0, 1))
    if bool(invalid.any()):
        raise PredictionConfigurationError(
            f"{settings.appearance_rate_column!r} must contain only missing values or finite "
            "probabilities in [0, 1]."
        )

    blank = _fixture_count(features).le(0.0)
    return probability.mask(blank, 0.0).astype("float64")


def expected_minutes(
    features: pd.DataFrame,
    *,
    config: ExpectedMinutesConfig | None = None,
) -> MinutesProjection:
    """Project minutes for every row of a feature dataset.

    Precedence, in order, with the reason each rung exists:

    1. **Current-season appearance history.** The product of how often a player
       features and how long when he does.
    2. **An observed absence.** A player with history that says he featured in none of
       the recent gameweeks projects to zero. This is a measurement, not a gap, and
       collapsing it into the fallback would discard a real observation.
    3. **Cross-season carry-over**, shrunk. He has a record, just not this season.
    4. **Nothing.** Left missing for the points stage to resolve.

    Then the calendar is applied. The panel sums minutes across every fixture inside a
    gameweek, so a club playing twice offers up to twice the minutes, and the estimate
    is scaled by the fixture count and clipped at that many full matches. A club with
    no fixture projects to zero whatever its players' history says, because history
    cannot override an empty calendar.

    Without a ``fixture_count`` column the estimate assumes one fixture, which is what
    a gameweek normally holds. Assuming anything else would silently scale every
    projection for a caller who simply has no calendar to hand.

    One limitation is deliberate and worth stating. The rolling rate is minutes per
    *gameweek featured*, not per fixture, because the panel records a gameweek's total
    and cannot say whether a player featured in one of two fixtures or both. A history
    containing double gameweeks therefore carries a slightly inflated base rate. Double
    gameweeks are 6,919 of 156,075 rows across the supported seasons, so the bias is
    small, and removing it would need player data at fixture grain that the archive
    does not publish.
    """

    settings = ExpectedMinutesConfig() if config is None else config
    if not isinstance(settings, ExpectedMinutesConfig):
        raise PredictionConfigurationError("config must be an ExpectedMinutesConfig.")
    if not isinstance(features, pd.DataFrame):
        raise PredictionConfigurationError("expected_minutes expects a pandas DataFrame.")

    rate = appearance_probability(features, config=settings)
    per_appearance = _numeric(features, settings.minutes_per_appearance_column)

    index = features.index
    values = pd.Series(float("nan"), index=index, dtype="float64")
    source = pd.Series(MINUTES_UNKNOWN, index=index, dtype="object")

    # Rung 3 first, so the more specific rungs overwrite it. Assigning in precedence
    # order would need every later rung to carry a "not already set" condition.
    if PRIOR_MINUTES_COLUMN in features.columns:
        carried = _numeric(features, PRIOR_MINUTES_COLUMN).mul(settings.carry_over_weight)
        usable = carried.notna()
        values = values.mask(usable, carried)
        source = source.mask(usable, MINUTES_FROM_CARRY_OVER)

    absent = rate.notna() & rate.le(0.0)
    values = values.mask(absent, 0.0)
    source = source.mask(absent, MINUTES_FROM_NO_APPEARANCE)

    measured = rate.notna() & rate.gt(0.0) & per_appearance.notna()
    product = rate.mul(per_appearance)
    values = values.mask(measured, product)
    source = source.mask(measured, MINUTES_FROM_HISTORY)

    fixtures = _fixture_count(features)
    scaled = values.mul(fixtures)
    capped = scaled.clip(lower=0.0, upper=fixtures.mul(float(MINUTES_PER_FULL_MATCH)))

    blank = fixtures.le(0.0)
    capped = capped.mask(blank, 0.0)
    source = source.mask(blank, MINUTES_BLANK_GAMEWEEK)

    return MinutesProjection(
        expected_minutes=capped.astype("float64"),
        source=source.astype("string"),
    )
