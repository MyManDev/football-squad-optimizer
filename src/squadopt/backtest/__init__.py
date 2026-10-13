"""Leakage-safe walk-forward preparation and baseline benchmarking."""

from squadopt.backtest.folds import (
    ProjectionBuilder,
    baseline_projection_builder,
    build_walk_forward_fold,
    build_walk_forward_folds,
    make_baseline_projection_builder,
)
from squadopt.backtest.learned import (
    RESIDUAL_COLUMNS,
    PairedDecisionMetrics,
    PositionPredictionMetrics,
    PredictionMetrics,
    build_residual_history,
    build_ridge_prediction_snapshot,
    make_ridge_projection_builder,
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
    "DEFAULT_OPENING_PRIOR_HOLDOUT_SEASON",
    "DEFAULT_OPENING_PRIOR_TRAINING_SEASONS",
    "OPENING_PRIOR_BACKTEST_CONTRACT_VERSION",
    "RESIDUAL_COLUMNS",
    "BacktestConfigurationError",
    "BacktestError",
    "DecisionPoint",
    "OpeningPriorBacktestConfig",
    "OpeningPriorBacktestResult",
    "OpeningPriorMetrics",
    "PairedDecisionMetrics",
    "PositionPredictionMetrics",
    "PredictionMetrics",
    "ProjectionBuilder",
    "baseline_projection_builder",
    "build_residual_history",
    "build_ridge_prediction_snapshot",
    "build_walk_forward_fold",
    "build_walk_forward_folds",
    "fit_opening_price_coefficient",
    "make_baseline_projection_builder",
    "make_ridge_projection_builder",
    "realized_points_at",
    "rows_before",
    "rows_through",
    "run_opening_prior_backtest",
    "season_ranks",
    "walk_forward_decision_points",
]
