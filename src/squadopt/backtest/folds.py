"""Turning a historical panel into prepared folds the evaluator can consume.

This is the seam named in ``docs/evaluation_spec.md``: the evaluation package
deliberately holds no temporal logic, and this module supplies the folds instead,
so the time axis has exactly one implementation.

The projection step is injected rather than hard-coded. Sprint 1 passes the
deterministic baseline; a later sprint passes a fitted model without touching the
splitting logic, which is the part that must not be re-derived.
"""

from collections.abc import Callable, Sequence
from typing import TypeAlias

import pandas as pd

from squadopt.backtest.splits import (
    BacktestConfigurationError,
    DecisionPoint,
    realized_points_at,
    rows_through,
    walk_forward_decision_points,
)
from squadopt.evaluation import EvaluationFold
from squadopt.features import build_feature_dataset
from squadopt.prediction import build_projection_table

# Given the rows visible at a decision point and the decision itself, return an
# optimizer-ready projection table. The callable never receives later rows, so it
# cannot look ahead even if it tried.
ProjectionBuilder: TypeAlias = Callable[[pd.DataFrame, DecisionPoint], pd.DataFrame]


def baseline_projection_builder(
    visible: pd.DataFrame,
    decision: DecisionPoint,
) -> pd.DataFrame:
    """Build a projection table for the decision using the deterministic baseline."""

    features = build_feature_dataset(visible)
    return build_projection_table(
        features,
        season=decision.season,
        gameweek=decision.gameweek,
    )


def build_walk_forward_fold(
    panel: pd.DataFrame,
    decision: DecisionPoint,
    *,
    projection_builder: ProjectionBuilder | None = None,
    season_order: Sequence[str] | None = None,
) -> EvaluationFold:
    """Prepare one fold: a projection table plus the outcomes that will score it.

    The projection is built from ``rows_through(panel, decision)`` — everything up
    to and including the decision gameweek, with later gameweeks absent — while the
    realized points come from the decision gameweek itself. Those two reads are
    kept separate on purpose: one is the input to a decision, the other is the
    answer used only after the decision is frozen.
    """

    build = baseline_projection_builder if projection_builder is None else projection_builder
    visible = rows_through(panel, decision, season_order=season_order)
    projections = build(visible, decision)

    if not isinstance(projections, pd.DataFrame):
        raise BacktestConfigurationError(
            f"projection_builder must return a DataFrame for {decision.fold_id}."
        )

    return EvaluationFold(
        fold_id=decision.fold_id,
        projections=projections,
        realized_points=realized_points_at(panel, decision),
        metadata={
            "season": decision.season,
            "gameweek": decision.gameweek,
            "visible_rows": len(visible),
        },
    )


def build_walk_forward_folds(
    panel: pd.DataFrame,
    *,
    seasons: Sequence[str] | None = None,
    min_prior_gameweeks_in_season: int = 1,
    projection_builder: ProjectionBuilder | None = None,
    season_order: Sequence[str] | None = None,
) -> tuple[EvaluationFold, ...]:
    """Prepare every fold in the panel, in chronological order.

    Fold order is meaningful to the evaluator: squad turnover is measured between
    adjacent folds, so a non-chronological sequence would report turnover between
    unrelated gameweeks. The order here comes from the same ranking the split
    functions use, so the two cannot disagree.

    ``seasons`` restricts which seasons produce decisions while leaving earlier
    seasons available as history. That is how a holdout season stays untouched
    during tuning without being deleted from the panel.
    """

    decisions = walk_forward_decision_points(
        panel,
        seasons=seasons,
        min_prior_gameweeks_in_season=min_prior_gameweeks_in_season,
        season_order=season_order,
    )
    if not decisions:
        raise BacktestConfigurationError(
            "No decision points remain; the panel may be too short for the requested "
            "minimum history, or the requested seasons may be empty."
        )

    return tuple(
        build_walk_forward_fold(
            panel,
            decision,
            projection_builder=projection_builder,
            season_order=season_order,
        )
        for decision in decisions
    )
