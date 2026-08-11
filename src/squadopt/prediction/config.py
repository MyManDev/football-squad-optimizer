"""Explicit configuration for the deterministic baseline projection.

Coefficients and fallbacks are declared here rather than scattered through the
computation, so the projection can be reasoned about and later tuned as a set of
experimental factors instead of hunted for in expressions.
"""

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from numbers import Integral, Real
from types import MappingProxyType

from squadopt.data.errors import DataError
from squadopt.data.schema import POSITIONS, Position
from squadopt.features.config import per_90_feature_name, rolling_feature_name

# Deliberately uniform across positions. A differentiated prior would imply a
# fitted claim this project has not earned yet; the per-position shape exists so
# a later sprint can refine it without changing any call site.
DEFAULT_OPENING_EXPECTED_POINTS = 3.0


class PredictionError(DataError):
    """Base exception for the prediction layer."""


class PredictionConfigurationError(PredictionError):
    """Raised when a projection configuration or its input frame is inconsistent."""


def _default_opening_expected_points() -> dict[Position, float]:
    return dict.fromkeys(POSITIONS, DEFAULT_OPENING_EXPECTED_POINTS)


def _require_window(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, Integral):
        raise PredictionConfigurationError(f"{name} must be an integer, got {value!r}.")
    window = int(value)
    if window < 1:
        raise PredictionConfigurationError(f"{name} must be at least 1, got {window}.")
    return window


@dataclass(frozen=True, slots=True)
class BaselineProjectionConfig:
    """Settings for the baseline expected-points projection.

    The projection scales a scoring rate by expected playing time:

        expected_points = points_per_90 * expected_minutes / 90

    Both inputs are shifted rolling features, so the value for gameweek ``t`` uses
    only gameweeks before ``t``.

    ``opening_expected_points`` covers the one case with no history at all: a
    player's first gameweek of a season. Because a rolling-only baseline has no
    signal there, the projection is uninformative for that gameweek by design, and
    the value is an explicit declared constant rather than a silent zero.
    """

    minutes_window: int = 5
    per_90_window: int = 5
    opening_expected_points: Mapping[Position, float] = field(
        default_factory=_default_opening_expected_points
    )

    def __post_init__(self) -> None:
        minutes_window = _require_window(self.minutes_window, "minutes_window")
        per_90_window = _require_window(self.per_90_window, "per_90_window")

        if not isinstance(self.opening_expected_points, Mapping):
            raise PredictionConfigurationError(
                "opening_expected_points must be a position-to-number mapping."
            )
        actual = set(self.opening_expected_points)
        expected = set(POSITIONS)
        if actual != expected:
            missing = sorted(expected - actual)
            extra = sorted(actual - expected)
            raise PredictionConfigurationError(
                f"opening_expected_points must cover exactly {list(POSITIONS)!r}; "
                f"missing={missing!r}, extra={extra!r}."
            )

        opening: dict[Position, float] = {}
        for position in POSITIONS:
            value = self.opening_expected_points[position]
            if isinstance(value, bool) or not isinstance(value, Real):
                raise PredictionConfigurationError(
                    f"opening_expected_points[{position!r}] must be a number, got {value!r}."
                )
            number = float(value)
            if not math.isfinite(number) or number < 0:
                raise PredictionConfigurationError(
                    f"opening_expected_points[{position!r}] must be finite and non-negative, "
                    f"got {number!r}."
                )
            opening[position] = number

        object.__setattr__(self, "minutes_window", minutes_window)
        object.__setattr__(self, "per_90_window", per_90_window)
        object.__setattr__(self, "opening_expected_points", MappingProxyType(opening))


DEFAULT_PROJECTION_CONFIG = BaselineProjectionConfig()


def required_feature_columns(config: BaselineProjectionConfig) -> tuple[str, ...]:
    """Return the feature columns the projection reads, given its windows."""

    return (
        rolling_feature_name("minutes", config.minutes_window),
        per_90_feature_name(config.per_90_window),
    )
