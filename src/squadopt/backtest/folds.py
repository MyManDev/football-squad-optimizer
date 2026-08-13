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
from squadopt.features import (
    PRIOR_MINUTES_COLUMN,
    PRIOR_RATE_COLUMN,
    CrossSeasonConfig,
    build_feature_dataset,
)
from squadopt.features.cross_season import carry_over_as_of
from squadopt.prediction import (
    BASELINE_FORM_WINDOW,
    FormWindowMapping,
    PredictionSnapshot,
    build_projection_table,
)

# Given the rows visible at a decision point and the decision itself, return an
# optimizer-ready projection table. The callable never receives later rows, so it
# cannot look ahead even if it tried.
ProjectionBuilder: TypeAlias = Callable[
    [pd.DataFrame, DecisionPoint], pd.DataFrame | PredictionSnapshot
]


def make_baseline_projection_builder(
    *,
    form_window: int = BASELINE_FORM_WINDOW,
    cross_season: CrossSeasonConfig | None = None,
) -> Callable[[pd.DataFrame, DecisionPoint], pd.DataFrame]:
    """Return a baseline builder for one ordered evaluation run.

    Within-season rolling features need only the target season. Earlier seasons are
    reduced to a carry-over once per target season and cached inside this builder.
    The cache is scoped to the returned callable, so separate runs cannot share it.
    """

    mapping = FormWindowMapping(form_window=form_window)
    carry_settings = CrossSeasonConfig() if cross_season is None else cross_season
    carry_cache: dict[str, pd.DataFrame] = {}

    def build(visible: pd.DataFrame, decision: DecisionPoint) -> pd.DataFrame:
        current_season = visible.loc[visible["season"] == decision.season].copy(deep=True)
        features = build_feature_dataset(
            current_season,
            config=mapping.feature_config,
        )
        if decision.season not in carry_cache:
            carry_cache[decision.season] = carry_over_as_of(
                visible,
                target_season=decision.season,
                config=carry_settings,
            )
        features = features.merge(
            carry_cache[decision.season],
            on="player_id",
            how="left",
            validate="many_to_one",
        )
        for column in (PRIOR_MINUTES_COLUMN, PRIOR_RATE_COLUMN):
            features[column] = features[column].astype("float64")
        return build_projection_table(
            features,
            season=decision.season,
            gameweek=decision.gameweek,
            config=mapping.projection_config,
        )

    return build


def baseline_projection_builder(
    visible: pd.DataFrame,
    decision: DecisionPoint,
) -> pd.DataFrame:
    """Build a projection table for the decision using the deterministic baseline."""

    return make_baseline_projection_builder()(visible, decision)


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
    built = build(visible, decision)

    prediction_metadata: dict[str, object] = {}
    if isinstance(built, PredictionSnapshot):
        verified = built.validated_copy()
        projections = verified.table
        provenance = verified.provenance
        prediction_metadata = {
            "prediction_contract_version": provenance.contract_version,
            "prediction_fingerprint": verified.prediction_fingerprint,
            "prediction_provenance_fingerprint": provenance.provenance_fingerprint,
            "prediction_model_name": provenance.model_name,
            "prediction_model_version": provenance.model_version,
            "prediction_feature_contract_version": provenance.feature_contract_version,
            "prediction_training_cutoff": provenance.training_cutoff,
            "prediction_training_data_fingerprint": provenance.training_data_fingerprint,
        }
    elif isinstance(built, pd.DataFrame):
        projections = built
    else:
        raise BacktestConfigurationError(
            "projection_builder must return a DataFrame or PredictionSnapshot "
            f"for {decision.fold_id}."
        )

    return EvaluationFold(
        fold_id=decision.fold_id,
        projections=projections,
        realized_points=realized_points_at(panel, decision),
        metadata={
            "season": decision.season,
            "gameweek": decision.gameweek,
            "visible_rows": len(visible),
            **prediction_metadata,
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
