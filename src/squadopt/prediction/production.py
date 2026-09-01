"""The production projection: a scoring rate, expected minutes, and their product.

The scoring rate answers how well a player performs while he is on the pitch, which is
the half of the projection that the minutes stage deliberately does not touch. Keeping
them apart is what lets a residual be attributed: an error in a squad's score is either
a misjudged availability or a misjudged rate, and one number cannot say which.

This first production candidate keeps the rate itself deliberately plain — the
current-season rate, falling back to a carry-over rate. That is close to what the
baseline already uses, and the choice is a measurement strategy rather than modesty. Any
difference from the baseline then comes from two identifiable sources, the appearance
decomposition and the calendar, and it can be attributed before anything more elaborate
is layered on. Adding capacity first would leave the improvement unattributable, which
is exactly the position the two-stage split exists to avoid.
"""

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from numbers import Integral, Real
from typing import Final

import pandas as pd

from squadopt.features import (
    MINUTES_PER_FULL_MATCH,
    PRIOR_RATE_COLUMN,
    per_90_feature_name,
)
from squadopt.prediction.components import (
    COMPONENT_MODEL_ROUTE,
    DIRECT_CONTROL_ROUTE,
    EVIDENCE_NOT_REQUESTED,
    ComponentPredictionSnapshot,
    prepare_component_prediction,
)
from squadopt.prediction.config import (
    FITTED_OPENING_PRICE_COEFFICIENT,
    PredictionConfigurationError,
)
from squadopt.prediction.integration import PredictionProvenance
from squadopt.prediction.minutes import (
    FIXTURE_COUNT_COLUMN,
    MINUTES_BLANK_GAMEWEEK,
    ExpectedMinutesConfig,
    MinutesProjection,
    appearance_probability,
    expected_minutes,
)

# Where a player's scoring rate came from.
RATE_FROM_HISTORY: Final = "in_season_history"
RATE_FROM_CARRY_OVER: Final = "cross_season_carry_over"
RATE_UNKNOWN: Final = "no_record"

RATE_SOURCES: Final = (RATE_FROM_HISTORY, RATE_FROM_CARRY_OVER, RATE_UNKNOWN)

# How the two halves were combined, or that they were not.
POINTS_FROM_TWO_STAGE: Final = "minutes_times_rate"
POINTS_FROM_PRICE_PRIOR: Final = "price_prior"
POINTS_FROM_BLANK_GAMEWEEK: Final = "blank_gameweek"

POINTS_SOURCES: Final = (
    POINTS_FROM_TWO_STAGE,
    POINTS_FROM_PRICE_PRIOR,
    POINTS_FROM_BLANK_GAMEWEEK,
)


@dataclass(frozen=True, slots=True)
class ProductionProjectionConfig:
    """Controls for the production projection.

    ``rate_window`` selects which scoring-rate feature to read, so it must match a
    window the feature dataset was built with.

    ``carry_over_rate_weight`` shrinks an earlier-season rate toward zero, for the same
    reason the minutes stage shrinks its carry-over: a player with no current-season
    record has not been picked this season, and last season describes a situation that
    may no longer hold.

    ``opening_price_coefficient`` prices a player with no record anywhere. It estimates
    expected points directly, so it is applied instead of the two-stage product rather
    than inside it — multiplying it by expected minutes would count playing time twice.
    """

    rate_window: int = 6
    carry_over_rate_weight: float = 0.75
    opening_price_coefficient: float = FITTED_OPENING_PRICE_COEFFICIENT
    minutes: ExpectedMinutesConfig = field(default_factory=ExpectedMinutesConfig)

    def __post_init__(self) -> None:
        if isinstance(self.rate_window, bool) or not isinstance(self.rate_window, Integral):
            raise PredictionConfigurationError(
                f"rate_window must be an integer, got {self.rate_window!r}."
            )
        window = int(self.rate_window)
        if window < 1:
            raise PredictionConfigurationError(f"rate_window must be at least 1, got {window}.")

        weight = _require_unit_interval(self.carry_over_rate_weight, "carry_over_rate_weight")
        coefficient = _require_non_negative(
            self.opening_price_coefficient, "opening_price_coefficient"
        )
        if not isinstance(self.minutes, ExpectedMinutesConfig):
            raise PredictionConfigurationError("minutes must be an ExpectedMinutesConfig.")

        object.__setattr__(self, "rate_window", window)
        object.__setattr__(self, "carry_over_rate_weight", weight)
        object.__setattr__(self, "opening_price_coefficient", coefficient)

    @property
    def rate_column(self) -> str:
        """Feature holding the current-season scoring rate."""

        return per_90_feature_name(self.rate_window)

    @property
    def required_columns(self) -> tuple[str, ...]:
        """Feature columns the projection reads, across both stages."""

        return (self.rate_column, *self.minutes.required_columns, "price_tenths")


def _require_unit_interval(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise PredictionConfigurationError(f"{name} must be a number, got {value!r}.")
    number = float(value)
    if not math.isfinite(number) or not 0.0 <= number <= 1.0:
        raise PredictionConfigurationError(
            f"{name} must be a finite value in [0, 1], got {number!r}."
        )
    return number


def _require_non_negative(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise PredictionConfigurationError(f"{name} must be a number, got {value!r}.")
    number = float(value)
    if not math.isfinite(number) or number < 0.0:
        raise PredictionConfigurationError(
            f"{name} must be a finite non-negative number, got {number!r}."
        )
    return number


@dataclass(frozen=True, slots=True)
class ProductionProjection:
    """Expected points, both halves that produced them, and the route taken.

    Every series is reported rather than only the product. A squad built mostly from
    price priors is a different object from one built from measured history, and the
    only way to see that after the fact is to keep the routes.
    """

    expected_points: pd.Series
    expected_minutes: pd.Series
    expected_points_per_90: pd.Series
    minutes_source: pd.Series
    rate_source: pd.Series
    points_source: pd.Series


def _numeric(features: pd.DataFrame, column: str, *, required: bool) -> pd.Series:
    if column not in features.columns:
        if required:
            raise PredictionConfigurationError(
                f"Feature dataset is missing column {column!r}, which the production "
                "projection reads."
            )
        return pd.Series(float("nan"), index=features.index, dtype="float64")
    return pd.to_numeric(features[column], errors="coerce").astype("float64")


def _validated_rate(
    rate: tuple[pd.Series, pd.Series],
    features: pd.DataFrame,
) -> tuple[pd.Series, pd.Series]:
    """Check an injected rate lines up with the rows it will be multiplied against.

    Reindexing a misaligned rate would silently pair one player's playing time with
    another's scoring, which no downstream check could detect.
    """

    if not isinstance(rate, tuple) or len(rate) != 2:
        raise PredictionConfigurationError("rate must be a (values, source) pair of pandas Series.")
    values, source = rate
    if not isinstance(values, pd.Series) or not isinstance(source, pd.Series):
        raise PredictionConfigurationError("rate must be a (values, source) pair of pandas Series.")
    if not values.index.equals(features.index) or not source.index.equals(features.index):
        raise PredictionConfigurationError(
            "An injected rate must share the feature dataset's index; it is multiplied "
            "row by row against expected minutes."
        )
    return (
        pd.to_numeric(values, errors="coerce").astype("float64"),
        source.astype("string"),
    )


def expected_points_per_90(
    features: pd.DataFrame,
    *,
    config: ProductionProjectionConfig | None = None,
) -> tuple[pd.Series, pd.Series]:
    """Project the scoring rate, and report where each value came from.

    Two rungs and a gap. The current-season rate is used where it exists; a shrunk
    earlier-season rate covers a player with a record but not this season; below that
    the rate is left missing, because a price prior estimates points and not a rate,
    and inventing one to fill the gap would put a fabricated number inside a product.
    """

    settings = ProductionProjectionConfig() if config is None else config
    if not isinstance(settings, ProductionProjectionConfig):
        raise PredictionConfigurationError("config must be a ProductionProjectionConfig.")

    in_season = _numeric(features, settings.rate_column, required=True)
    carried = _numeric(features, PRIOR_RATE_COLUMN, required=False)

    values = pd.Series(float("nan"), index=features.index, dtype="float64")
    source = pd.Series(RATE_UNKNOWN, index=features.index, dtype="object")

    usable_carry = carried.notna()
    values = values.mask(usable_carry, carried.mul(settings.carry_over_rate_weight))
    source = source.mask(usable_carry, RATE_FROM_CARRY_OVER)

    usable_history = in_season.notna()
    values = values.mask(usable_history, in_season)
    source = source.mask(usable_history, RATE_FROM_HISTORY)

    return values.clip(lower=0.0).astype("float64"), source.astype("string")


def production_projection(
    features: pd.DataFrame,
    *,
    config: ProductionProjectionConfig | None = None,
    rate: tuple[pd.Series, pd.Series] | None = None,
) -> ProductionProjection:
    """Project expected points for every row of a feature dataset.

    Where both stages have signal the estimate is ``minutes / 90 * rate``. Where the
    minutes stage found nothing the price prior supplies expected points directly and
    the product is bypassed, because the prior already accounts for playing time and
    multiplying it by playing time again would count it twice.

    A club with no fixture scores nothing, whatever either stage says. That case is
    reported separately from the price prior so a zero from an empty calendar is not
    mistaken for a zero from an absent record.

    The result is finite and non-negative everywhere. A row that reaches the end
    without a value is an error rather than a zero, because a silent zero would read as
    a confident prediction of nothing.

    ``rate`` supplies an already-projected ``(values, source)`` pair instead of reading
    the rolling feature. It exists so the Issue #43 candidate can replace the scoring
    rate and nothing else: the minutes stage, the price prior, the blank-gameweek rule,
    and the combination below stay literally this code rather than a copy of it, which
    is what makes "only the rate changed" checkable instead of merely asserted. A rate
    that does not align with ``features`` is refused rather than reindexed.
    """

    settings = ProductionProjectionConfig() if config is None else config
    if not isinstance(settings, ProductionProjectionConfig):
        raise PredictionConfigurationError("config must be a ProductionProjectionConfig.")
    if not isinstance(features, pd.DataFrame):
        raise PredictionConfigurationError("production_projection expects a pandas DataFrame.")
    if features.empty:
        raise PredictionConfigurationError("Feature dataset has no rows to project.")

    minutes: MinutesProjection = expected_minutes(features, config=settings.minutes)
    if rate is None:
        rate_values, rate_source = expected_points_per_90(features, config=settings)
    else:
        rate_values, rate_source = _validated_rate(rate, features)

    price = _numeric(features, "price_tenths", required=True)
    if bool(price.isna().any()) or bool(price.lt(0.0).any()):
        raise PredictionConfigurationError(
            "price_tenths must be present and non-negative for every projected row; the "
            "price prior is the only estimate available to a player with no record."
        )

    prior = price.div(10.0).mul(settings.opening_price_coefficient)

    values = prior
    source = pd.Series(POINTS_FROM_PRICE_PRIOR, index=features.index, dtype="object")

    # A projected absence needs no rate. When expected minutes are zero the product is
    # zero whatever the rate would have been, so requiring a rate here would push a
    # player we expect not to play onto the price prior — which prices him as though he
    # will. That is the difference between "we expect nothing from him" and "we know
    # nothing about him", and only the second warrants a prior.
    absent = minutes.expected_minutes.notna() & minutes.expected_minutes.le(0.0)
    measured = (
        minutes.expected_minutes.notna() & minutes.expected_minutes.gt(0.0) & rate_values.notna()
    )

    product = minutes.expected_minutes.div(float(MINUTES_PER_FULL_MATCH)).mul(rate_values)
    values = values.mask(measured, product)
    source = source.mask(measured, POINTS_FROM_TWO_STAGE)

    values = values.mask(absent, 0.0)
    source = source.mask(absent, POINTS_FROM_TWO_STAGE)

    blank = minutes.source.eq(MINUTES_BLANK_GAMEWEEK)
    values = values.mask(blank, 0.0)
    source = source.mask(blank, POINTS_FROM_BLANK_GAMEWEEK)

    values = values.clip(lower=0.0).astype("float64")
    if bool(values.isna().any()) or not bool(values.map(math.isfinite).all()):
        raise PredictionConfigurationError(
            "The projection produced a missing or non-finite expected points value. Every "
            "row must reach a rung of the precedence ladder; a silent zero would read as "
            "a confident prediction of nothing."
        )

    return ProductionProjection(
        expected_points=values,
        expected_minutes=minutes.expected_minutes,
        expected_points_per_90=rate_values,
        minutes_source=minutes.source,
        rate_source=rate_source,
        points_source=source.astype("string"),
    )


def production_component_prediction(
    features: pd.DataFrame,
    provenance: PredictionProvenance,
    *,
    decision_timestamp_utc: str,
    config: ProductionProjectionConfig | None = None,
    decision_context: Mapping[str, str] | None = None,
) -> ComponentPredictionSnapshot:
    """Expose the operational control through the Phase C component boundary."""

    settings = ProductionProjectionConfig() if config is None else config
    if not isinstance(settings, ProductionProjectionConfig):
        raise PredictionConfigurationError("config must be a ProductionProjectionConfig.")
    if not isinstance(features, pd.DataFrame):
        raise PredictionConfigurationError(
            "production_component_prediction expects a pandas DataFrame."
        )
    if "player_id" not in features.columns:
        raise PredictionConfigurationError("Component features must carry 'player_id'.")

    projection = production_projection(features, config=settings)
    probability = appearance_probability(features, config=settings.minutes)
    if FIXTURE_COUNT_COLUMN in features.columns:
        fixtures = (
            pd.to_numeric(features[FIXTURE_COUNT_COLUMN], errors="raise").fillna(1).astype(int)
        )
    else:
        fixtures = pd.Series(1, index=features.index, dtype="int64")

    positive = projection.points_source.eq(POINTS_FROM_TWO_STAGE) & probability.gt(0.0)
    zero = projection.points_source.eq(POINTS_FROM_TWO_STAGE) & probability.eq(0.0)
    conditional_minutes = projection.expected_minutes.div(probability)
    conditional_points = projection.expected_points.div(probability)
    supported = positive & conditional_minutes.le(fixtures.mul(float(MINUTES_PER_FULL_MATCH)))
    component = zero | supported
    conditional_minutes = conditional_minutes.mask(zero, 0.0).where(component)
    conditional_points = conditional_points.mask(zero, 0.0).where(component)

    rows = pd.DataFrame(
        {
            "player_id": features["player_id"].to_numpy(),
            "fixture_count": fixtures.to_numpy(),
            "appearance_probability": probability.where(component).to_numpy(),
            "expected_minutes_if_appearance": conditional_minutes.to_numpy(),
            "expected_points_if_appearance": conditional_points.to_numpy(),
            "fallback_expected_points": projection.expected_points.where(~component).to_numpy(),
            "composition_route": pd.Series(DIRECT_CONTROL_ROUTE, index=features.index)
            .mask(component, COMPONENT_MODEL_ROUTE)
            .to_numpy(),
            "evidence_status": EVIDENCE_NOT_REQUESTED,
        }
    )
    snapshot = prepare_component_prediction(
        rows,
        provenance,
        decision_timestamp_utc=decision_timestamp_utc,
        decision_context=decision_context,
    )
    expected = projection.expected_points.set_axis(features["player_id"]).sort_index()
    actual = snapshot.table.set_index("player_id")["expected_points"]
    if bool(actual.sub(expected).abs().gt(1e-12).any()):
        raise PredictionConfigurationError(
            "Component decomposition changed the operational expected-points control."
        )
    return snapshot
