"""Shared, pre-registered controls for paired development comparisons."""

import math
from dataclasses import dataclass
from numbers import Integral, Real


class ExperimentError(Exception):
    """Compatibility base for shared policy and experiment errors."""


class ExperimentConfigurationError(ExperimentError):
    """A policy or experiment configuration violates its public contract."""


class ExperimentExecutionError(ExperimentError):
    """Raised when an experiment cannot produce a trustworthy comparison."""


@dataclass(frozen=True, slots=True)
class PromotionPolicy:
    """Pre-registered gates for sending a challenger to the locked holdout."""

    min_mean_improvement: float = 0.5
    confidence_level: float = 0.90
    bootstrap_resamples: int = 5_000
    moving_block_length: int = 4
    deterministic_seed: int = 0

    def __post_init__(self) -> None:
        improvement = self.min_mean_improvement
        confidence = self.confidence_level
        if isinstance(improvement, bool) or not isinstance(improvement, Real):
            raise ExperimentConfigurationError("min_mean_improvement must be a finite real.")
        normalized_improvement = float(improvement)
        if not math.isfinite(normalized_improvement) or normalized_improvement < 0.0:
            raise ExperimentConfigurationError("min_mean_improvement must be non-negative.")
        if isinstance(confidence, bool) or not isinstance(confidence, Real):
            raise ExperimentConfigurationError("confidence_level must be a finite real.")
        normalized_confidence = float(confidence)
        if not math.isfinite(normalized_confidence) or not 0.0 < normalized_confidence < 1.0:
            raise ExperimentConfigurationError("confidence_level must be strictly between 0 and 1.")

        normalized_integers: dict[str, int] = {}
        for name, value, minimum in (
            ("bootstrap_resamples", self.bootstrap_resamples, 1),
            ("moving_block_length", self.moving_block_length, 1),
            ("deterministic_seed", self.deterministic_seed, 0),
        ):
            if isinstance(value, bool) or not isinstance(value, Integral):
                raise ExperimentConfigurationError(f"{name} must be an integer.")
            normalized = int(value)
            if normalized < minimum:
                raise ExperimentConfigurationError(f"{name} must be at least {minimum}.")
            normalized_integers[name] = normalized

        object.__setattr__(self, "min_mean_improvement", normalized_improvement)
        object.__setattr__(self, "confidence_level", normalized_confidence)
        for name, value in normalized_integers.items():
            object.__setattr__(self, name, value)
