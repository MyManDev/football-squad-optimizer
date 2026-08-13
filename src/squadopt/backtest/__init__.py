"""Leakage-safe walk-forward preparation and baseline benchmarking."""

from squadopt.backtest.benchmark import (
    BASELINE_BENCHMARK_CONTRACT_VERSION,
    DEFAULT_BENCHMARK_SEASONS,
    BaselineBenchmarkConfig,
    run_baseline_benchmark,
)
from squadopt.backtest.folds import (
    ProjectionBuilder,
    baseline_projection_builder,
    build_walk_forward_fold,
    build_walk_forward_folds,
    make_baseline_projection_builder,
)
from squadopt.backtest.opening_prior import (
    DEFAULT_OPENING_PRIOR_HOLDOUT_SEASON,
    DEFAULT_OPENING_PRIOR_TRAINING_SEASONS,
    OPENING_PRIOR_BACKTEST_CONTRACT_VERSION,
    OpeningPriorBacktestConfig,
    OpeningPriorBacktestResult,
    OpeningPriorMetrics,
    fit_opening_price_coefficient,
    run_opening_prior_backtest,
)
from squadopt.backtest.splits import (
    BacktestConfigurationError,
    BacktestError,
    DecisionPoint,
    realized_points_at,
    rows_before,
    rows_through,
    season_ranks,
    walk_forward_decision_points,
)

__all__ = [
    "BASELINE_BENCHMARK_CONTRACT_VERSION",
    "DEFAULT_BENCHMARK_SEASONS",
    "DEFAULT_OPENING_PRIOR_HOLDOUT_SEASON",
    "DEFAULT_OPENING_PRIOR_TRAINING_SEASONS",
    "OPENING_PRIOR_BACKTEST_CONTRACT_VERSION",
    "BacktestConfigurationError",
    "BacktestError",
    "BaselineBenchmarkConfig",
    "DecisionPoint",
    "OpeningPriorBacktestConfig",
    "OpeningPriorBacktestResult",
    "OpeningPriorMetrics",
    "ProjectionBuilder",
    "baseline_projection_builder",
    "build_walk_forward_fold",
    "build_walk_forward_folds",
    "fit_opening_price_coefficient",
    "make_baseline_projection_builder",
    "realized_points_at",
    "rows_before",
    "rows_through",
    "run_baseline_benchmark",
    "run_opening_prior_backtest",
    "season_ranks",
    "walk_forward_decision_points",
]
