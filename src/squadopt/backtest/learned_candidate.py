"""The Issue #43 candidate: the production pipeline with a learned scoring rate.

Everything the declaration freezes is reached through the existing code rather than
copied here — the feature windows, the per-season carry-over and fixture join, the
expanding-window opening-price refit, the expected-minutes stage, and the two-stage
combination. That is the point. A frozen component reimplemented in a second place stops
being frozen the moment the two copies drift, and no gate could see it happen.

What this module adds is one thing: at every fold, a rate model fitted on the rows the
decision point can already see, injected into the frozen combination through
``production_projection(..., rate=...)``.

The training slice is ``rows_before(features, decision)`` — the same slice the price
prior already refits on, and the same one the walk-forward contract guarantees is
strictly historical. Deriving it here a second way would be a second chance to get
leakage wrong.
"""

from collections.abc import Callable, Mapping
from typing import Final

import pandas as pd

from squadopt.backtest.production import _fingerprint as _training_fingerprint
from squadopt.backtest.production import (
    _price_coefficient,
    _route_counts,
    _season_features,
    _training_cutoff,
    production_feature_config,
)
from squadopt.backtest.splits import BacktestConfigurationError, DecisionPoint, rows_before
from squadopt.features import PRIOR_RATE_COLUMN, CrossSeasonConfig
from squadopt.features.cross_season import carry_over_as_of
from squadopt.prediction.integration import (
    PredictionProvenance,
    PredictionSnapshot,
    prepare_optimizer_projection,
)
from squadopt.prediction.learned_rate import (
    LEARNED_RATE_FEATURE_CONTRACT_VERSION,
    LEARNED_RATE_MODEL_NAME,
    LEARNED_RATE_MODEL_VERSION,
    LEARNED_RATE_TRAINING_CONTRACT_VERSION,
    LearnedRateConfig,
    LearnedRateModel,
    fit_learned_rate,
    learned_points_per_90,
)
from squadopt.prediction.production import (
    ProductionProjection,
    ProductionProjectionConfig,
    production_projection,
)

_SNAPSHOT_COLUMNS: Final = ("player_id", "name", "team_id", "position", "price_tenths")

__all__ = [
    "LEARNED_RATE_FEATURE_CONTRACT_VERSION",
    "LEARNED_RATE_MODEL_NAME",
    "LEARNED_RATE_MODEL_VERSION",
    "LEARNED_RATE_TRAINING_CONTRACT_VERSION",
    "build_learned_candidate_snapshot",
    "make_learned_rate_projection_builder",
]


def _require_matched_windows(
    settings: ProductionProjectionConfig,
    learned: LearnedRateConfig,
) -> None:
    """The learned stage must read the same frozen feature the stage it replaces read."""

    if learned.window != settings.rate_window:
        raise BacktestConfigurationError(
            f"The learned rate window ({learned.window}) must equal the projection's rate "
            f"window ({settings.rate_window}); reading a different window would change the "
            "frozen feature mapping as well as the rate."
        )


def build_learned_candidate_snapshot(
    visible: pd.DataFrame,
    decision: DecisionPoint,
    *,
    fixtures: pd.DataFrame,
    team_codes: pd.DataFrame,
    config: ProductionProjectionConfig | None = None,
    learned_config: LearnedRateConfig | None = None,
    cross_season: CrossSeasonConfig | None = None,
) -> PredictionSnapshot:
    """Project the decision gameweek with a rate fitted on visible history alone."""

    settings = ProductionProjectionConfig() if config is None else config
    learned = LearnedRateConfig() if learned_config is None else learned_config
    carry = CrossSeasonConfig() if cross_season is None else cross_season
    if not isinstance(settings, ProductionProjectionConfig):
        raise BacktestConfigurationError("config must be a ProductionProjectionConfig.")
    if not isinstance(learned, LearnedRateConfig):
        raise BacktestConfigurationError("learned_config must be a LearnedRateConfig.")
    if not isinstance(carry, CrossSeasonConfig):
        raise BacktestConfigurationError("cross_season must be a CrossSeasonConfig.")
    _require_matched_windows(settings, learned)

    feature_config = production_feature_config(settings)
    seasons = sorted({str(value) for value in visible["season"].tolist()})
    features = pd.concat(
        [
            _season_features(
                visible,
                season,
                feature_config,
                carry_over_as_of(visible, target_season=season, config=carry),
                fixtures,
                team_codes,
            )
            for season in seasons
        ],
        ignore_index=True,
    )

    training = rows_before(features, decision)
    if training.empty:
        raise BacktestConfigurationError(f"No training rows before {decision.fold_id}.")
    target = features.loc[
        (features["season"] == decision.season) & (features["gameweek"] == decision.gameweek)
    ].copy(deep=True)
    if target.empty:
        raise BacktestConfigurationError(f"No target rows for {decision.fold_id}.")

    model = fit_learned_rate(training, config=learned)
    rate = learned_points_per_90(
        target,
        model,
        config=learned,
        carry_over_rate_weight=settings.carry_over_rate_weight,
        prior_rate_column=PRIOR_RATE_COLUMN,
    )

    coefficient, prior_origin = _price_coefficient(visible, decision)
    fold_settings = ProductionProjectionConfig(
        rate_window=settings.rate_window,
        carry_over_rate_weight=settings.carry_over_rate_weight,
        opening_price_coefficient=coefficient,
        minutes=settings.minutes,
    )
    projection = production_projection(target, config=fold_settings, rate=rate)

    predictions = pd.DataFrame(
        {
            "player_id": target["player_id"].to_numpy(),
            "expected_points": projection.expected_points.to_numpy(),
        }
    )
    provenance = PredictionProvenance(
        model_name=LEARNED_RATE_MODEL_NAME,
        model_version=LEARNED_RATE_MODEL_VERSION,
        feature_contract_version=LEARNED_RATE_FEATURE_CONTRACT_VERSION,
        training_cutoff=_training_cutoff(training),
        training_data_fingerprint=_training_fingerprint(training),
    )
    snapshot = prepare_optimizer_projection(
        target.loc[:, list(_SNAPSHOT_COLUMNS)],
        predictions,
        provenance,
    )
    return PredictionSnapshot(
        table=snapshot.table,
        provenance=snapshot.provenance,
        prediction_fingerprint=snapshot.prediction_fingerprint,
        diagnostics=_diagnostics(snapshot.diagnostics, projection, model, prior_origin, learned),
    )


def _diagnostics(
    base: Mapping[str, object],
    projection: ProductionProjection,
    model: LearnedRateModel,
    prior_origin: str,
    learned: LearnedRateConfig,
) -> dict[str, object]:
    """Report the fitted state alongside the routes, so a fold can be audited alone."""

    return {
        **dict(base),
        **_route_counts(projection.minutes_source, "minutes_source"),
        **_route_counts(projection.rate_source, "rate_source"),
        **_route_counts(projection.points_source, "points_source"),
        "opening_price_prior_origin": prior_origin,
        "training_contract_version": LEARNED_RATE_TRAINING_CONTRACT_VERSION,
        "rate_model_fingerprint": model.model_fingerprint,
        "rate_training_rows": model.training_rows,
        "rate_ridge_alpha": learned.ridge_alpha,
        "rate_input_columns": list(learned.input_columns),
    }


def make_learned_rate_projection_builder(
    *,
    fixtures: pd.DataFrame,
    team_codes: pd.DataFrame,
    config: ProductionProjectionConfig | None = None,
    learned_config: LearnedRateConfig | None = None,
    cross_season: CrossSeasonConfig | None = None,
) -> Callable[[pd.DataFrame, DecisionPoint], PredictionSnapshot]:
    """Return a builder matching the walk-forward contract.

    Completed seasons' features are cached exactly as the production builder caches
    them; the rate model is not, because it is refitted at every fold by design and a
    cached model would be one fitted before some of the history it now claims to have
    seen.
    """

    settings = ProductionProjectionConfig() if config is None else config
    learned = LearnedRateConfig() if learned_config is None else learned_config
    carry = CrossSeasonConfig() if cross_season is None else cross_season
    _require_matched_windows(settings, learned)
    feature_config = production_feature_config(settings)
    completed_cache: dict[str, pd.DataFrame] = {}
    carry_cache: dict[str, pd.DataFrame] = {}

    def build(visible: pd.DataFrame, decision: DecisionPoint) -> PredictionSnapshot:
        seasons = sorted({str(value) for value in visible["season"].tolist()})
        frames: list[pd.DataFrame] = []
        for season in seasons:
            if season not in carry_cache:
                carry_cache[season] = carry_over_as_of(visible, target_season=season, config=carry)
            completed = season != decision.season
            if completed and season in completed_cache:
                frames.append(completed_cache[season])
                continue
            built = _season_features(
                visible,
                season,
                feature_config,
                carry_cache[season],
                fixtures,
                team_codes,
            )
            if completed:
                completed_cache[season] = built
            frames.append(built)

        features = pd.concat(frames, ignore_index=True)
        training = rows_before(features, decision)
        if training.empty:
            raise BacktestConfigurationError(f"No training rows before {decision.fold_id}.")
        target = features.loc[
            (features["season"] == decision.season) & (features["gameweek"] == decision.gameweek)
        ].copy(deep=True)
        if target.empty:
            raise BacktestConfigurationError(f"No target rows for {decision.fold_id}.")

        model = fit_learned_rate(training, config=learned)
        rate = learned_points_per_90(
            target,
            model,
            config=learned,
            carry_over_rate_weight=settings.carry_over_rate_weight,
            prior_rate_column=PRIOR_RATE_COLUMN,
        )
        coefficient, prior_origin = _price_coefficient(visible, decision)
        fold_settings = ProductionProjectionConfig(
            rate_window=settings.rate_window,
            carry_over_rate_weight=settings.carry_over_rate_weight,
            opening_price_coefficient=coefficient,
            minutes=settings.minutes,
        )
        projection = production_projection(target, config=fold_settings, rate=rate)

        predictions = pd.DataFrame(
            {
                "player_id": target["player_id"].to_numpy(),
                "expected_points": projection.expected_points.to_numpy(),
            }
        )
        provenance = PredictionProvenance(
            model_name=LEARNED_RATE_MODEL_NAME,
            model_version=LEARNED_RATE_MODEL_VERSION,
            feature_contract_version=LEARNED_RATE_FEATURE_CONTRACT_VERSION,
            training_cutoff=_training_cutoff(training),
            training_data_fingerprint=_training_fingerprint(training),
        )
        snapshot = prepare_optimizer_projection(
            target.loc[:, list(_SNAPSHOT_COLUMNS)],
            predictions,
            provenance,
        )
        return PredictionSnapshot(
            table=snapshot.table,
            provenance=snapshot.provenance,
            prediction_fingerprint=snapshot.prediction_fingerprint,
            diagnostics=_diagnostics(
                snapshot.diagnostics, projection, model, prior_origin, learned
            ),
        )

    return build
