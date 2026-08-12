"""Walk-forward splitting and fold preparation for historical backtests.

Sits above the data, feature, prediction, and evaluation layers and composes them.
It owns the time axis: what counts as "before" a decision is decided here and
nowhere else, so no consumer needs to re-derive it and no consumer can bypass it.

Random row-level splits are not expressible through this API. That is the point.
"""

from squadopt.backtest.folds import (
    ProjectionBuilder,
    baseline_projection_builder,
    build_walk_forward_fold,
    build_walk_forward_folds,
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
    "BacktestConfigurationError",
    "BacktestError",
    "DecisionPoint",
    "ProjectionBuilder",
    "baseline_projection_builder",
    "build_walk_forward_fold",
    "build_walk_forward_folds",
    "realized_points_at",
    "rows_before",
    "rows_through",
    "season_ranks",
    "walk_forward_decision_points",
]
