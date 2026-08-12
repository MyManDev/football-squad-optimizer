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
    "BacktestConfigurationError",
    "BacktestError",
    "BaselineBenchmarkConfig",
    "DecisionPoint",
    "ProjectionBuilder",
    "baseline_projection_builder",
    "build_walk_forward_fold",
    "build_walk_forward_folds",
    "make_baseline_projection_builder",
    "realized_points_at",
    "rows_before",
    "rows_through",
    "run_baseline_benchmark",
    "season_ranks",
    "walk_forward_decision_points",
]
