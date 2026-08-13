"""Versioned configuration for conformal lower-bound squad optimization."""

import hashlib
import json
import math
from dataclasses import dataclass, field
from decimal import Decimal
from numbers import Integral, Real
from typing import Final

from squadopt.optimization import OptimizationConfig
from squadopt.risk.errors import RiskConfigurationError
from squadopt.uncertainty.config import PlayerAdaptiveUncertaintyConfig

RISK_OPTIMIZATION_CONTRACT_VERSION: Final = "conformal_lcb_objective_v1"
RISK_SCREENING_CONTRACT_VERSION: Final = "rolling_risk_screening_v1"
PLAYER_RISK_SCREENING_CONTRACT_VERSION: Final = "player_risk_screening_v1"
DEFAULT_RISK_AVERSION_LEVELS: Final = (0.0, 0.25, 0.5, 1.0)
DEFAULT_RISK_SCREENING_SEASONS: Final = (
    "2021-22",
    "2022-23",
    "2023-24",
    "2024-25",
)


def _probability(value: object, name: str, *, include_zero: bool) -> float:
    if isinstance(value, bool) or not isinstance(value, (Real, Decimal)):
        raise RiskConfigurationError(f"{name} must be a finite real number.")
    try:
        normalized = float(value)
    except (OverflowError, TypeError, ValueError) as error:
        raise RiskConfigurationError(f"{name} must be a finite real number.") from error
    lower_valid = normalized >= 0.0 if include_zero else normalized > 0.0
    if not math.isfinite(normalized) or not lower_valid or normalized > 1.0:
        interval = "[0, 1]" if include_zero else "(0, 1]"
        raise RiskConfigurationError(f"{name} must be in {interval}, got {normalized!r}.")
    return normalized


def _minimum(value: object, name: str, minimum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, Integral):
        raise RiskConfigurationError(f"{name} must be an integer.")
    normalized = int(value)
    if normalized < minimum:
        raise RiskConfigurationError(f"{name} must be at least {minimum}.")
    return normalized


def _risk_token(value: float) -> str:
    return format(Decimal(str(value)).normalize(), "f").replace("-", "m").replace(".", "p")


def _positive_number(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (Real, Decimal)):
        raise RiskConfigurationError(f"{name} must be a finite positive number.")
    try:
        normalized = float(value)
    except (OverflowError, TypeError, ValueError) as error:
        raise RiskConfigurationError(f"{name} must be a finite positive number.") from error
    if not math.isfinite(normalized) or normalized <= 0.0:
        raise RiskConfigurationError(f"{name} must be a finite positive number.")
    return normalized


@dataclass(frozen=True, slots=True)
class RiskOptimizationConfig:
    """Controls one conformal lower-confidence-bound objective."""

    risk_aversion: float = 0.0
    contract_version: str = RISK_OPTIMIZATION_CONTRACT_VERSION

    def __post_init__(self) -> None:
        if self.contract_version != RISK_OPTIMIZATION_CONTRACT_VERSION:
            raise RiskConfigurationError(
                "contract_version must match the implemented risk objective contract."
            )
        object.__setattr__(
            self,
            "risk_aversion",
            _probability(self.risk_aversion, "risk_aversion", include_zero=True),
        )

    @property
    def candidate_id(self) -> str:
        """Return a stable ID for screening and reporting."""

        return f"risk-{_risk_token(self.risk_aversion)}"

    @property
    def configuration_fingerprint(self) -> str:
        """Return a stable digest of the comparison-affecting risk controls."""

        payload = {
            "contract_version": self.contract_version,
            "risk_aversion": _risk_token(self.risk_aversion),
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class RiskScreeningConfig:
    """Controls expanding-season, development-only risk screening."""

    season_order: tuple[str, ...] = DEFAULT_RISK_SCREENING_SEASONS
    risk_aversion_levels: tuple[float, ...] = DEFAULT_RISK_AVERSION_LEVELS
    downside_quantile: float = 0.10
    uncertainty_confidence_level: float = 0.90
    min_pooled_observations: int = 30
    min_group_observations: int = 30
    min_prior_gameweeks_in_season: int = 1
    optimization_config: OptimizationConfig = field(default_factory=OptimizationConfig)
    contract_version: str = RISK_SCREENING_CONTRACT_VERSION

    def __post_init__(self) -> None:
        if self.contract_version != RISK_SCREENING_CONTRACT_VERSION:
            raise RiskConfigurationError(
                "contract_version must match the implemented risk screening contract."
            )
        if not isinstance(self.season_order, tuple) or len(self.season_order) < 2:
            raise RiskConfigurationError("season_order must be a tuple with at least two seasons.")
        if any(not isinstance(season, str) or not season.strip() for season in self.season_order):
            raise RiskConfigurationError("season_order entries must be non-empty strings.")
        seasons = tuple(season.strip() for season in self.season_order)
        if len(set(seasons)) != len(seasons):
            raise RiskConfigurationError("season_order entries must be unique.")

        if not isinstance(self.risk_aversion_levels, tuple) or not self.risk_aversion_levels:
            raise RiskConfigurationError("risk_aversion_levels must be a non-empty tuple.")
        levels = tuple(
            sorted(
                _probability(value, "risk_aversion_levels entry", include_zero=True)
                for value in self.risk_aversion_levels
            )
        )
        tokens = tuple(_risk_token(value) for value in levels)
        if len(set(tokens)) != len(tokens):
            raise RiskConfigurationError("risk_aversion_levels must contain unique values.")
        if levels[0] != 0.0:
            raise RiskConfigurationError("risk_aversion_levels must include the 0.0 control.")
        if not isinstance(self.optimization_config, OptimizationConfig):
            raise RiskConfigurationError(
                "optimization_config must be an OptimizationConfig instance."
            )

        object.__setattr__(self, "season_order", seasons)
        object.__setattr__(self, "risk_aversion_levels", levels)
        object.__setattr__(
            self,
            "downside_quantile",
            _probability(self.downside_quantile, "downside_quantile", include_zero=False),
        )
        object.__setattr__(
            self,
            "uncertainty_confidence_level",
            _probability(
                self.uncertainty_confidence_level,
                "uncertainty_confidence_level",
                include_zero=False,
            ),
        )
        if self.uncertainty_confidence_level >= 1.0:
            raise RiskConfigurationError(
                "uncertainty_confidence_level must be strictly between 0 and 1."
            )
        object.__setattr__(
            self,
            "min_pooled_observations",
            _minimum(self.min_pooled_observations, "min_pooled_observations", 2),
        )
        object.__setattr__(
            self,
            "min_group_observations",
            _minimum(self.min_group_observations, "min_group_observations", 2),
        )
        object.__setattr__(
            self,
            "min_prior_gameweeks_in_season",
            _minimum(
                self.min_prior_gameweeks_in_season,
                "min_prior_gameweeks_in_season",
                1,
            ),
        )

    @property
    def candidates(self) -> tuple[RiskOptimizationConfig, ...]:
        """Return candidate risk objectives in deterministic order."""

        return tuple(RiskOptimizationConfig(level) for level in self.risk_aversion_levels)

    @property
    def configuration_fingerprint(self) -> str:
        """Return a stable digest of every screening control."""

        optimization = self.optimization_config
        payload = {
            "contract_version": self.contract_version,
            "risk_objective_contract_version": RISK_OPTIMIZATION_CONTRACT_VERSION,
            "season_order": self.season_order,
            "risk_aversion_levels": [_risk_token(value) for value in self.risk_aversion_levels],
            "downside_quantile": _risk_token(self.downside_quantile),
            "uncertainty_confidence_level": _risk_token(self.uncertainty_confidence_level),
            "min_pooled_observations": self.min_pooled_observations,
            "min_group_observations": self.min_group_observations,
            "min_prior_gameweeks_in_season": self.min_prior_gameweeks_in_season,
            "optimization": {
                "budget_tenths": optimization.budget_tenths,
                "squad_size": optimization.squad_size,
                "squad_position_limits": dict(optimization.squad_position_limits),
                "starting_size": optimization.starting_size,
                "starting_position_min": dict(optimization.starting_position_min),
                "starting_position_max": dict(optimization.starting_position_max),
                "max_players_per_team": optimization.max_players_per_team,
                "bench_weight": optimization.bench_weight,
                "expected_points_scale": optimization.expected_points_scale,
                "solver_time_limit_seconds": optimization.solver_time_limit_seconds,
                "deterministic_seed": optimization.deterministic_seed,
            },
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class PlayerRiskScreeningConfig(RiskScreeningConfig):
    """Controls expanding-season screening with player-adaptive uncertainty."""

    scale_training_fraction: float = 0.50
    min_player_observations: int = 5
    shrinkage_observations: float = 10.0
    minimum_scale: float = 0.25
    contract_version: str = PLAYER_RISK_SCREENING_CONTRACT_VERSION

    def __post_init__(self) -> None:
        if self.contract_version != PLAYER_RISK_SCREENING_CONTRACT_VERSION:
            raise RiskConfigurationError(
                "contract_version must match the implemented player risk screening contract."
            )
        common = RiskScreeningConfig(
            season_order=self.season_order,
            risk_aversion_levels=self.risk_aversion_levels,
            downside_quantile=self.downside_quantile,
            uncertainty_confidence_level=self.uncertainty_confidence_level,
            min_pooled_observations=self.min_pooled_observations,
            min_group_observations=self.min_group_observations,
            min_prior_gameweeks_in_season=self.min_prior_gameweeks_in_season,
            optimization_config=self.optimization_config,
        )
        for name in (
            "season_order",
            "risk_aversion_levels",
            "downside_quantile",
            "uncertainty_confidence_level",
            "min_pooled_observations",
            "min_group_observations",
            "min_prior_gameweeks_in_season",
            "optimization_config",
        ):
            object.__setattr__(self, name, getattr(common, name))
        split = _probability(
            self.scale_training_fraction,
            "scale_training_fraction",
            include_zero=False,
        )
        if split >= 1.0:
            raise RiskConfigurationError(
                "scale_training_fraction must be strictly between 0 and 1."
            )
        object.__setattr__(self, "scale_training_fraction", split)
        object.__setattr__(
            self,
            "min_player_observations",
            _minimum(self.min_player_observations, "min_player_observations", 2),
        )
        object.__setattr__(
            self,
            "shrinkage_observations",
            _positive_number(self.shrinkage_observations, "shrinkage_observations"),
        )
        object.__setattr__(
            self,
            "minimum_scale",
            _positive_number(self.minimum_scale, "minimum_scale"),
        )

    def uncertainty_config_for(
        self,
        calibration_seasons: tuple[str, ...],
        target_season: str,
    ) -> PlayerAdaptiveUncertaintyConfig:
        """Build the pre-registered adaptive calibration for one target season."""

        return PlayerAdaptiveUncertaintyConfig(
            confidence_level=self.uncertainty_confidence_level,
            development_seasons=calibration_seasons,
            holdout_season=target_season,
            scale_training_fraction=self.scale_training_fraction,
            min_pooled_observations=self.min_pooled_observations,
            min_position_observations=self.min_group_observations,
            min_player_observations=self.min_player_observations,
            shrinkage_observations=self.shrinkage_observations,
            minimum_scale=self.minimum_scale,
        )

    @property
    def configuration_fingerprint(self) -> str:
        """Return a stable digest of common and player-adaptive controls."""

        common = RiskScreeningConfig(
            season_order=self.season_order,
            risk_aversion_levels=self.risk_aversion_levels,
            downside_quantile=self.downside_quantile,
            uncertainty_confidence_level=self.uncertainty_confidence_level,
            min_pooled_observations=self.min_pooled_observations,
            min_group_observations=self.min_group_observations,
            min_prior_gameweeks_in_season=self.min_prior_gameweeks_in_season,
            optimization_config=self.optimization_config,
        )
        payload = {
            "common_screening_fingerprint": common.configuration_fingerprint,
            "contract_version": self.contract_version,
            "min_player_observations": self.min_player_observations,
            "minimum_scale": _risk_token(self.minimum_scale),
            "scale_training_fraction": _risk_token(self.scale_training_fraction),
            "shrinkage_observations": _risk_token(self.shrinkage_observations),
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()
