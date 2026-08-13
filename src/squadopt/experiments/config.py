"""Validated configuration for the versioned Sprint 2 screening experiment."""

import hashlib
import json
import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from numbers import Integral, Real
from typing import Final

from squadopt.evaluation import EvaluationConfig
from squadopt.features import CrossSeasonConfig, FeatureConfigurationError
from squadopt.optimization import OptimizationConfig
from squadopt.prediction import FormWindowMapping

SCREENING_EXPERIMENT_CONTRACT_VERSION: Final = "screening_doe_v1"
DEFAULT_DEVELOPMENT_SEASONS: Final = ("2021-22", "2022-23", "2023-24", "2024-25")
DEFAULT_HOLDOUT_SEASONS: Final = ("2025-26",)
DEFAULT_FORM_WINDOWS: Final = (3, 5, 7, 10)
DEFAULT_BENCH_WEIGHTS: Final = (0.0, 0.1, 0.25)


class ExperimentError(Exception):
    """Base exception for the experiment package."""


class ExperimentConfigurationError(ExperimentError):
    """Raised when an experiment configuration violates its public contract."""


class ExperimentExecutionError(ExperimentError):
    """Raised when an experiment cannot produce a trustworthy comparison."""


class FrozenCandidateError(ExperimentError):
    """Raised when a frozen candidate is invalid or used with a different design."""


def _bench_token(value: float) -> str:
    normalized = format(Decimal(str(value)).normalize(), "f")
    return normalized.replace("-", "m").replace(".", "p")


@dataclass(frozen=True, slots=True)
class ExperimentCandidate:
    """One cell in the two-factor Sprint 2 design."""

    form_window: int = 5
    bench_weight: float = 0.1

    def __post_init__(self) -> None:
        try:
            mapping = FormWindowMapping(form_window=self.form_window)
        except FeatureConfigurationError as error:
            raise ExperimentConfigurationError(str(error)) from error
        value = self.bench_weight
        if isinstance(value, bool) or not isinstance(value, Real):
            raise ExperimentConfigurationError("bench_weight must be a finite real number.")
        weight = float(value)
        if not math.isfinite(weight) or not 0.0 <= weight <= 1.0:
            raise ExperimentConfigurationError(
                f"bench_weight must be between 0 and 1 inclusive, got {weight!r}."
            )
        object.__setattr__(self, "form_window", mapping.form_window)
        object.__setattr__(self, "bench_weight", weight)

    @property
    def candidate_id(self) -> str:
        """Return a stable identifier independent of binary float formatting."""

        return f"fw{self.form_window:02d}-bw{_bench_token(self.bench_weight)}"


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


def _normalize_seasons(value: object, name: str) -> tuple[str, ...]:
    if not isinstance(value, tuple) or not value:
        raise ExperimentConfigurationError(f"{name} must be a non-empty tuple.")
    if any(not isinstance(season, str) for season in value):
        raise ExperimentConfigurationError(f"{name} entries must be strings.")
    normalized = tuple(season.strip() for season in value)
    if any(not season for season in normalized) or len(set(normalized)) != len(normalized):
        raise ExperimentConfigurationError(f"{name} must contain unique, non-empty season labels.")
    return normalized


@dataclass(frozen=True, slots=True)
class ScreeningExperimentConfig:
    """Complete fixed design and controls for Sprint 2 screening."""

    development_seasons: tuple[str, ...] = DEFAULT_DEVELOPMENT_SEASONS
    holdout_seasons: tuple[str, ...] = DEFAULT_HOLDOUT_SEASONS
    form_windows: tuple[int, ...] = DEFAULT_FORM_WINDOWS
    bench_weights: tuple[float, ...] = DEFAULT_BENCH_WEIGHTS
    control: ExperimentCandidate = field(default_factory=ExperimentCandidate)
    min_prior_gameweeks_in_season: int = 1
    parallel_candidate_jobs: int = 3
    cross_season_config: CrossSeasonConfig = field(default_factory=CrossSeasonConfig)
    optimization_config: OptimizationConfig = field(default_factory=OptimizationConfig)
    promotion_policy: PromotionPolicy = field(default_factory=PromotionPolicy)
    run_metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        development = _normalize_seasons(self.development_seasons, "development_seasons")
        holdout = _normalize_seasons(self.holdout_seasons, "holdout_seasons")
        overlap = sorted(set(development) & set(holdout))
        if overlap:
            raise ExperimentConfigurationError(
                f"Development and holdout seasons must be disjoint; overlap={overlap!r}."
            )
        if not isinstance(self.form_windows, tuple) or not self.form_windows:
            raise ExperimentConfigurationError("form_windows must be a non-empty tuple.")
        windows = tuple(
            ExperimentCandidate(form_window=value, bench_weight=0.0).form_window
            for value in self.form_windows
        )
        if len(set(windows)) != len(windows):
            raise ExperimentConfigurationError("form_windows must contain unique values.")

        if not isinstance(self.bench_weights, tuple) or not self.bench_weights:
            raise ExperimentConfigurationError("bench_weights must be a non-empty tuple.")
        weights = tuple(
            ExperimentCandidate(form_window=windows[0], bench_weight=value).bench_weight
            for value in self.bench_weights
        )
        if len({_bench_token(value) for value in weights}) != len(weights):
            raise ExperimentConfigurationError("bench_weights must contain unique values.")

        if not isinstance(self.control, ExperimentCandidate):
            raise ExperimentConfigurationError("control must be an ExperimentCandidate.")
        candidate_ids = {
            ExperimentCandidate(window, weight).candidate_id
            for window in windows
            for weight in weights
        }
        if self.control.candidate_id not in candidate_ids:
            raise ExperimentConfigurationError(
                "control must be one of the declared full-factorial design cells."
            )

        minimum = self.min_prior_gameweeks_in_season
        if isinstance(minimum, bool) or not isinstance(minimum, Integral):
            raise ExperimentConfigurationError("min_prior_gameweeks_in_season must be an integer.")
        normalized_minimum = int(minimum)
        if normalized_minimum < 1:
            raise ExperimentConfigurationError(
                "Sprint 2 excludes opening gameweeks; min_prior_gameweeks_in_season "
                "must be at least 1."
            )
        parallel_jobs = self.parallel_candidate_jobs
        if isinstance(parallel_jobs, bool) or not isinstance(parallel_jobs, Integral):
            raise ExperimentConfigurationError("parallel_candidate_jobs must be an integer.")
        normalized_parallel_jobs = int(parallel_jobs)
        if normalized_parallel_jobs < 1:
            raise ExperimentConfigurationError("parallel_candidate_jobs must be at least 1.")
        if not isinstance(self.cross_season_config, CrossSeasonConfig):
            raise ExperimentConfigurationError(
                "cross_season_config must be a CrossSeasonConfig instance."
            )
        if not isinstance(self.optimization_config, OptimizationConfig):
            raise ExperimentConfigurationError(
                "optimization_config must be an OptimizationConfig instance."
            )
        if not isinstance(self.promotion_policy, PromotionPolicy):
            raise ExperimentConfigurationError(
                "promotion_policy must be a PromotionPolicy instance."
            )
        if not isinstance(self.run_metadata, Mapping):
            raise ExperimentConfigurationError("run_metadata must be a mapping.")
        frozen_metadata = EvaluationConfig(
            optimization_config=self.optimization_config,
            run_metadata=self.run_metadata,
        ).run_metadata

        object.__setattr__(self, "development_seasons", development)
        object.__setattr__(self, "holdout_seasons", holdout)
        object.__setattr__(self, "form_windows", windows)
        object.__setattr__(self, "bench_weights", weights)
        object.__setattr__(self, "min_prior_gameweeks_in_season", normalized_minimum)
        object.__setattr__(self, "parallel_candidate_jobs", normalized_parallel_jobs)
        object.__setattr__(self, "run_metadata", frozen_metadata)

    @property
    def candidates(self) -> tuple[ExperimentCandidate, ...]:
        """Return the full factorial in declared, deterministic order."""

        return tuple(
            ExperimentCandidate(form_window=window, bench_weight=weight)
            for window in self.form_windows
            for weight in self.bench_weights
        )

    @property
    def configuration_fingerprint(self) -> str:
        """Return a stable digest of every comparison-affecting control."""

        optimization = self.optimization_config
        policy = self.promotion_policy
        payload = {
            "contract_version": SCREENING_EXPERIMENT_CONTRACT_VERSION,
            "development_seasons": self.development_seasons,
            "holdout_seasons": self.holdout_seasons,
            "form_windows": self.form_windows,
            "bench_weights": [_bench_token(value) for value in self.bench_weights],
            "control": self.control.candidate_id,
            "min_prior_gameweeks_in_season": self.min_prior_gameweeks_in_season,
            "parallel_candidate_jobs": self.parallel_candidate_jobs,
            "cross_season": {
                "decay": self.cross_season_config.decay,
                "min_minutes": self.cross_season_config.min_minutes,
            },
            "optimization": {
                "budget_tenths": optimization.budget_tenths,
                "squad_size": optimization.squad_size,
                "squad_position_limits": dict(optimization.squad_position_limits),
                "starting_size": optimization.starting_size,
                "starting_position_min": dict(optimization.starting_position_min),
                "starting_position_max": dict(optimization.starting_position_max),
                "max_players_per_team": optimization.max_players_per_team,
                "expected_points_scale": optimization.expected_points_scale,
                "solver_time_limit_seconds": optimization.solver_time_limit_seconds,
                "deterministic_seed": optimization.deterministic_seed,
            },
            "promotion_policy": {
                "min_mean_improvement": policy.min_mean_improvement,
                "confidence_level": policy.confidence_level,
                "bootstrap_resamples": policy.bootstrap_resamples,
                "moving_block_length": policy.moving_block_length,
                "deterministic_seed": policy.deterministic_seed,
            },
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()
