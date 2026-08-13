"""Versioned configuration for leakage-safe projection uncertainty calibration."""

import hashlib
import json
import math
from dataclasses import dataclass
from numbers import Integral, Real
from typing import Final

from squadopt.uncertainty.errors import UncertaintyConfigurationError

PROJECTION_UNCERTAINTY_CONTRACT_VERSION: Final = "projection_uncertainty_v1"
DEFAULT_UNCERTAINTY_DEVELOPMENT_SEASONS: Final = (
    "2021-22",
    "2022-23",
    "2023-24",
    "2024-25",
)
DEFAULT_UNCERTAINTY_HOLDOUT_SEASON: Final = "2025-26"


def _seasons(value: object, name: str) -> tuple[str, ...]:
    if not isinstance(value, tuple) or not value:
        raise UncertaintyConfigurationError(f"{name} must be a non-empty tuple.")
    invalid = [season for season in value if not isinstance(season, str) or not season.strip()]
    if invalid:
        raise UncertaintyConfigurationError(
            f"{name} entries must be non-empty strings; got {invalid!r}."
        )
    normalized = tuple(season.strip() for season in value)
    if len(set(normalized)) != len(normalized):
        raise UncertaintyConfigurationError(f"{name} entries must be unique.")
    return normalized


def _minimum(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, Integral):
        raise UncertaintyConfigurationError(f"{name} must be an integer, got {value!r}.")
    minimum = int(value)
    if minimum < 2:
        raise UncertaintyConfigurationError(f"{name} must be at least 2, got {minimum}.")
    return minimum


@dataclass(frozen=True, slots=True)
class UncertaintyConfig:
    """Controls for development-only conformal calibration and locked holdout use."""

    confidence_level: float = 0.90
    development_seasons: tuple[str, ...] = DEFAULT_UNCERTAINTY_DEVELOPMENT_SEASONS
    holdout_season: str = DEFAULT_UNCERTAINTY_HOLDOUT_SEASON
    min_pooled_observations: int = 30
    min_group_observations: int = 30
    contract_version: str = PROJECTION_UNCERTAINTY_CONTRACT_VERSION

    def __post_init__(self) -> None:
        confidence = self.confidence_level
        if isinstance(confidence, bool) or not isinstance(confidence, Real):
            raise UncertaintyConfigurationError(
                f"confidence_level must be a finite number between 0 and 1, got {confidence!r}."
            )
        try:
            confidence = float(confidence)
        except (OverflowError, ValueError) as error:
            raise UncertaintyConfigurationError(
                "confidence_level must be a finite number between 0 and 1."
            ) from error
        if not math.isfinite(confidence) or not 0.0 < confidence < 1.0:
            raise UncertaintyConfigurationError(
                f"confidence_level must be strictly between 0 and 1, got {confidence!r}."
            )

        development = _seasons(self.development_seasons, "development_seasons")
        if not isinstance(self.holdout_season, str) or not self.holdout_season.strip():
            raise UncertaintyConfigurationError("holdout_season must be a non-empty string.")
        holdout = self.holdout_season.strip()
        if holdout in development:
            raise UncertaintyConfigurationError(
                "holdout_season must be disjoint from development_seasons."
            )
        if self.contract_version != PROJECTION_UNCERTAINTY_CONTRACT_VERSION:
            raise UncertaintyConfigurationError(
                "contract_version must match the implemented uncertainty contract."
            )

        object.__setattr__(self, "confidence_level", confidence)
        object.__setattr__(self, "development_seasons", development)
        object.__setattr__(self, "holdout_season", holdout)
        object.__setattr__(
            self,
            "min_pooled_observations",
            _minimum(self.min_pooled_observations, "min_pooled_observations"),
        )
        object.__setattr__(
            self,
            "min_group_observations",
            _minimum(self.min_group_observations, "min_group_observations"),
        )

    @property
    def configuration_fingerprint(self) -> str:
        """Return a stable digest of every comparison-affecting control."""

        payload = {
            "confidence_level": self.confidence_level,
            "contract_version": self.contract_version,
            "development_seasons": self.development_seasons,
            "holdout_season": self.holdout_season,
            "min_group_observations": self.min_group_observations,
            "min_pooled_observations": self.min_pooled_observations,
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()
