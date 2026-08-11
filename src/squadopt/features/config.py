"""Explicit configuration and naming for leakage-safe rolling features.

Windows live in configuration rather than being inlined at call sites, because a
later sprint treats them as experimental factors for Design of Experiments. A
window buried in a call is not tunable; a declared one is.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from numbers import Integral
from types import MappingProxyType

from squadopt.data.errors import DataError

# One full match. Scoring rates are normalized to this so players with different
# amounts of playing time become comparable.
MINUTES_PER_FULL_MATCH = 90


class FeatureError(DataError):
    """Base exception for the feature layer.

    Derived from ``DataError`` so a caller can guard the whole data path with one
    except clause, while still staying disjoint from optimizer exceptions.
    """


class FeatureConfigurationError(FeatureError):
    """Raised when a feature configuration or its input frame is inconsistent."""


# Canonical source column to feature-name stem, so feature names are derived
# rather than written out as string literals at each use.
FEATURE_STEMS: Mapping[str, str] = MappingProxyType(
    {
        "minutes": "minutes",
        "total_points": "points",
    }
)


def rolling_feature_name(column: str, window: int) -> str:
    """Return the canonical name of a rolling feature over a source column."""

    stem = FEATURE_STEMS.get(column)
    if stem is None:
        raise FeatureConfigurationError(
            f"No feature-name stem is declared for column {column!r}; "
            f"known columns are {sorted(FEATURE_STEMS)!r}."
        )
    return f"{stem}_last_{window}"


def per_90_feature_name(window: int) -> str:
    """Return the canonical name of the rolling points-per-90 feature."""

    return f"points_per_90_last_{window}"


def _require_window(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, Integral):
        raise FeatureConfigurationError(f"{name} must be an integer, got {value!r}.")
    window = int(value)
    if window < 1:
        raise FeatureConfigurationError(f"{name} must be at least 1, got {window}.")
    return window


def _normalize_windows(windows: object, name: str) -> tuple[int, ...]:
    """Return sorted, unique windows so feature naming is order-independent."""

    if isinstance(windows, str) or not isinstance(windows, tuple | list):
        raise FeatureConfigurationError(f"{name} must be a tuple of integers, got {windows!r}.")
    if not windows:
        raise FeatureConfigurationError(f"{name} must declare at least one window.")
    normalized = sorted({_require_window(value, f"{name} entry") for value in windows})
    return tuple(normalized)


@dataclass(frozen=True, slots=True)
class FeatureConfig:
    """Windows and history requirements for leakage-safe rolling features.

    ``min_periods`` defaults to 1: a player's second gameweek already has one
    prior observation, and one real observation beats no signal at all. The cost
    is noisier early-season values; the benefit is that every gameweek after the
    first is projectable, which matters because a squad has to be picked for
    those gameweeks too.

    Only the very first gameweek of a player's season has no history and stays
    missing. That gap is filled by an explicit fallback in the prediction layer,
    never by looking forward.
    """

    minutes_windows: tuple[int, ...] = (3, 5)
    points_windows: tuple[int, ...] = (3, 5)
    per_90_window: int = 5
    min_periods: int = 1

    def __post_init__(self) -> None:
        minutes_windows = _normalize_windows(self.minutes_windows, "minutes_windows")
        points_windows = _normalize_windows(self.points_windows, "points_windows")
        per_90_window = _require_window(self.per_90_window, "per_90_window")
        min_periods = _require_window(self.min_periods, "min_periods")

        smallest = min(*minutes_windows, *points_windows, per_90_window)
        if min_periods > smallest:
            raise FeatureConfigurationError(
                f"min_periods ({min_periods}) cannot exceed the smallest window ({smallest}), "
                "otherwise that window could never produce a value."
            )

        object.__setattr__(self, "minutes_windows", minutes_windows)
        object.__setattr__(self, "points_windows", points_windows)
        object.__setattr__(self, "per_90_window", per_90_window)
        object.__setattr__(self, "min_periods", min_periods)


DEFAULT_FEATURE_CONFIG = FeatureConfig()


def feature_column_names(config: FeatureConfig) -> tuple[str, ...]:
    """Return every feature column the configuration produces, in output order."""

    names = [rolling_feature_name("minutes", window) for window in config.minutes_windows]
    names.extend(rolling_feature_name("total_points", window) for window in config.points_windows)
    names.append(per_90_feature_name(config.per_90_window))
    return tuple(names)
