"""Executable contract for the deterministic real-data baseline benchmark."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from numbers import Integral

import pandas as pd

from squadopt.backtest.folds import build_walk_forward_folds, make_baseline_projection_builder
from squadopt.backtest.splits import BacktestConfigurationError
from squadopt.evaluation import EvaluationConfig, EvaluationResult, evaluate_prepared_folds
from squadopt.features import CrossSeasonConfig, FeatureConfigurationError
from squadopt.optimization import OptimizationConfig
from squadopt.prediction import (
    BASELINE_FORM_WINDOW,
    FEATURE_GENERATION_CONTRACT_VERSION,
    FormWindowMapping,
)

BASELINE_BENCHMARK_CONTRACT_VERSION = "walk_forward_baseline_v1"
DEFAULT_BENCHMARK_SEASONS: tuple[str, ...] = ("2025-26",)


@dataclass(frozen=True, slots=True)
class BaselineBenchmarkConfig:
    """Fixed controls for a leakage-safe historical baseline run.

    Opening gameweeks are deliberately excluded. They use a different information
    set and are evaluated by the opening-projection workflow instead of being mixed
    into the within-season response distribution.
    """

    seasons: tuple[str, ...] = DEFAULT_BENCHMARK_SEASONS
    form_window: int = BASELINE_FORM_WINDOW
    min_prior_gameweeks_in_season: int = 1
    cross_season_config: CrossSeasonConfig = field(default_factory=CrossSeasonConfig)
    optimization_config: OptimizationConfig = field(default_factory=OptimizationConfig)
    run_metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.seasons, tuple) or not self.seasons:
            raise BacktestConfigurationError("seasons must be a non-empty tuple.")
        if any(not isinstance(season, str) for season in self.seasons):
            raise BacktestConfigurationError("seasons entries must be strings.")
        normalized = tuple(season.strip() for season in self.seasons)
        if any(not season for season in normalized) or len(set(normalized)) != len(normalized):
            raise BacktestConfigurationError(
                "seasons must contain unique, non-empty season labels."
            )
        minimum = self.min_prior_gameweeks_in_season
        if isinstance(minimum, bool) or not isinstance(minimum, Integral):
            raise BacktestConfigurationError("min_prior_gameweeks_in_season must be an integer.")
        if int(minimum) < 1:
            raise BacktestConfigurationError(
                "The baseline benchmark excludes opening gameweeks; "
                "min_prior_gameweeks_in_season must be at least 1."
            )
        if not isinstance(self.cross_season_config, CrossSeasonConfig):
            raise BacktestConfigurationError(
                "cross_season_config must be a CrossSeasonConfig instance."
            )
        if not isinstance(self.optimization_config, OptimizationConfig):
            raise BacktestConfigurationError(
                "optimization_config must be an OptimizationConfig instance."
            )
        if not isinstance(self.run_metadata, Mapping):
            raise BacktestConfigurationError("run_metadata must be a mapping.")

        try:
            mapping = FormWindowMapping(form_window=self.form_window)
        except FeatureConfigurationError as error:
            raise BacktestConfigurationError(str(error)) from error
        frozen_metadata = EvaluationConfig(
            optimization_config=self.optimization_config,
            run_metadata=self.run_metadata,
        ).run_metadata

        object.__setattr__(self, "seasons", normalized)
        object.__setattr__(self, "form_window", mapping.form_window)
        object.__setattr__(self, "min_prior_gameweeks_in_season", int(minimum))
        object.__setattr__(self, "run_metadata", frozen_metadata)


def run_baseline_benchmark(
    panel: pd.DataFrame,
    config: BaselineBenchmarkConfig | None = None,
) -> EvaluationResult:
    """Run the named baseline over chronological, non-opening gameweek folds."""

    settings = BaselineBenchmarkConfig() if config is None else config
    if not isinstance(settings, BaselineBenchmarkConfig):
        raise BacktestConfigurationError("config must be a BaselineBenchmarkConfig instance.")

    builder = make_baseline_projection_builder(
        form_window=settings.form_window,
        cross_season=settings.cross_season_config,
    )
    folds = build_walk_forward_folds(
        panel,
        seasons=settings.seasons,
        min_prior_gameweeks_in_season=settings.min_prior_gameweeks_in_season,
        projection_builder=builder,
    )
    metadata = {
        **dict(settings.run_metadata),
        "benchmark_contract_version": BASELINE_BENCHMARK_CONTRACT_VERSION,
        "feature_generation_contract_version": FEATURE_GENERATION_CONTRACT_VERSION,
        "form_window": settings.form_window,
        "evaluation_seasons": settings.seasons,
        "min_prior_gameweeks_in_season": settings.min_prior_gameweeks_in_season,
        "cross_season_decay": settings.cross_season_config.decay,
        "cross_season_min_minutes": settings.cross_season_config.min_minutes,
    }
    return evaluate_prepared_folds(
        folds,
        EvaluationConfig(
            optimization_config=settings.optimization_config,
            run_metadata=metadata,
        ),
    )
