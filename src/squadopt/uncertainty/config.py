"""Versioned configuration for leakage-safe projection uncertainty calibration."""

import hashlib
import json
import math
from dataclasses import dataclass
from numbers import Integral, Real
from typing import Final

from squadopt.uncertainty.errors import UncertaintyConfigurationError

PROJECTION_UNCERTAINTY_CONTRACT_VERSION: Final = "projection_uncertainty_v1"
PROJECTION_UNCERTAINTY_FIXTURE_CONTRACT_VERSION: Final = "projection_uncertainty_v2"
UNCERTAINTY_GROUPINGS: Final = ("position", "position_fixture_group")
CONTRACT_BY_GROUPING: Final = {
    "position": PROJECTION_UNCERTAINTY_CONTRACT_VERSION,
    "position_fixture_group": PROJECTION_UNCERTAINTY_FIXTURE_CONTRACT_VERSION,
}
PLAYER_ADAPTIVE_UNCERTAINTY_CONTRACT_VERSION: Final = "player_adaptive_uncertainty_v1"
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


def _finite_float(value: object, name: str, *, lower_exclusive: float) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise UncertaintyConfigurationError(f"{name} must be a finite number.")
    try:
        normalized = float(value)
    except (OverflowError, TypeError, ValueError) as error:
        raise UncertaintyConfigurationError(f"{name} must be a finite number.") from error
    if not math.isfinite(normalized) or normalized <= lower_exclusive:
        raise UncertaintyConfigurationError(
            f"{name} must be greater than {lower_exclusive}, got {normalized!r}."
        )
    return normalized


@dataclass(frozen=True, slots=True)
class UncertaintyConfig:
    """Controls for development-only conformal calibration and locked holdout use."""

    confidence_level: float = 0.90
    development_seasons: tuple[str, ...] = DEFAULT_UNCERTAINTY_DEVELOPMENT_SEASONS
    holdout_season: str = DEFAULT_UNCERTAINTY_HOLDOUT_SEASON
    min_pooled_observations: int = 30
    min_group_observations: int = 30
    grouping: str = "position"
    """``position`` is the v1 contract: one conformal radius per position.
    ``position_fixture_group`` is v2: one radius per position and fixture group
    (``single`` / ``double_plus``, pooled fallback per position under the floor);
    fitting and applying it require a ``fixture_count`` column, and a blank (zero
    fixtures) projects zero with a zero radius. The contract version follows the
    grouping and must agree with it."""
    contract_version: str = PROJECTION_UNCERTAINTY_CONTRACT_VERSION

    def __post_init__(self) -> None:
        if self.grouping not in UNCERTAINTY_GROUPINGS:
            raise UncertaintyConfigurationError(
                f"grouping must be one of {UNCERTAINTY_GROUPINGS!r}, got {self.grouping!r}."
            )
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
        if self.contract_version != CONTRACT_BY_GROUPING[self.grouping]:
            raise UncertaintyConfigurationError(
                "contract_version must match the implemented uncertainty contract for the "
                f"grouping: {self.grouping!r} is {CONTRACT_BY_GROUPING[self.grouping]!r}."
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

        payload: dict[str, object] = {
            "confidence_level": self.confidence_level,
            "contract_version": self.contract_version,
            "development_seasons": self.development_seasons,
            "holdout_season": self.holdout_season,
            "min_group_observations": self.min_group_observations,
            "min_pooled_observations": self.min_pooled_observations,
        }
        # The v1 payload is unchanged so recorded v1 fingerprints still reproduce.
        if self.grouping != "position":
            payload["grouping"] = self.grouping
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @property
    def uses_fixture_groups(self) -> bool:
        return self.grouping == "position_fixture_group"


@dataclass(frozen=True, slots=True)
class PlayerAdaptiveUncertaintyConfig:
    """Controls a chronological player-adaptive split-conformal calibration."""

    confidence_level: float = 0.90
    development_seasons: tuple[str, ...] = DEFAULT_UNCERTAINTY_DEVELOPMENT_SEASONS
    holdout_season: str = DEFAULT_UNCERTAINTY_HOLDOUT_SEASON
    scale_training_fraction: float = 0.50
    min_pooled_observations: int = 30
    min_position_observations: int = 30
    min_player_observations: int = 5
    shrinkage_observations: float = 10.0
    minimum_scale: float = 0.25
    contract_version: str = PLAYER_ADAPTIVE_UNCERTAINTY_CONTRACT_VERSION

    def __post_init__(self) -> None:
        confidence = _finite_float(
            self.confidence_level,
            "confidence_level",
            lower_exclusive=0.0,
        )
        if confidence >= 1.0:
            raise UncertaintyConfigurationError(
                "confidence_level must be strictly between 0 and 1."
            )
        split = _finite_float(
            self.scale_training_fraction,
            "scale_training_fraction",
            lower_exclusive=0.0,
        )
        if split >= 1.0:
            raise UncertaintyConfigurationError(
                "scale_training_fraction must be strictly between 0 and 1."
            )
        development = _seasons(self.development_seasons, "development_seasons")
        if not isinstance(self.holdout_season, str) or not self.holdout_season.strip():
            raise UncertaintyConfigurationError("holdout_season must be a non-empty string.")
        holdout = self.holdout_season.strip()
        if holdout in development:
            raise UncertaintyConfigurationError(
                "holdout_season must be disjoint from development_seasons."
            )
        if self.contract_version != PLAYER_ADAPTIVE_UNCERTAINTY_CONTRACT_VERSION:
            raise UncertaintyConfigurationError(
                "contract_version must match the implemented player-adaptive contract."
            )

        object.__setattr__(self, "confidence_level", confidence)
        object.__setattr__(self, "development_seasons", development)
        object.__setattr__(self, "holdout_season", holdout)
        object.__setattr__(self, "scale_training_fraction", split)
        for name in (
            "min_pooled_observations",
            "min_position_observations",
            "min_player_observations",
        ):
            object.__setattr__(self, name, _minimum(getattr(self, name), name))
        object.__setattr__(
            self,
            "shrinkage_observations",
            _finite_float(
                self.shrinkage_observations,
                "shrinkage_observations",
                lower_exclusive=0.0,
            ),
        )
        object.__setattr__(
            self,
            "minimum_scale",
            _finite_float(self.minimum_scale, "minimum_scale", lower_exclusive=0.0),
        )

    @property
    def configuration_fingerprint(self) -> str:
        """Return a stable digest of every adaptive-calibration control."""

        payload = {
            "confidence_level": self.confidence_level,
            "contract_version": self.contract_version,
            "development_seasons": self.development_seasons,
            "holdout_season": self.holdout_season,
            "min_player_observations": self.min_player_observations,
            "min_pooled_observations": self.min_pooled_observations,
            "min_position_observations": self.min_position_observations,
            "minimum_scale": self.minimum_scale,
            "scale_training_fraction": self.scale_training_fraction,
            "shrinkage_observations": self.shrinkage_observations,
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()
