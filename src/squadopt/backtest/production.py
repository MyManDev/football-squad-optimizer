"""Walk-forward builder for the production projection.

The builder is the boundary the rest of the system already knows how to consume: it
takes the panel visible at a decision point, returns a ``PredictionSnapshot``, and the
optimizer never learns what produced it. The Ridge reference plugs in through the same
signature, which is what makes a paired comparison possible at all.

Two things are refitted per fold rather than fixed. Features are rebuilt from the visible
panel only, and the opening price coefficient is refitted on an expanding window of
completed seasons. A coefficient fitted once across every season and then used inside an
earlier fold would have seen that fold's own opening outcomes; refitting keeps the
walk-forward story uniform even though folds normally skip opening gameweeks.

The fixture table is captured when the builder is made, not passed per call, because the
builder signature is fixed by the contract. That is not a loophole: fixture context is
pre-match, so reading the target gameweek's own fixtures is exactly as safe as reading
its price.
"""

import hashlib
from collections.abc import Callable, Mapping
from typing import Final

import pandas as pd

from squadopt.backtest.opening_prior import fit_opening_price_coefficient
from squadopt.backtest.splits import BacktestConfigurationError, DecisionPoint, rows_before
from squadopt.features import (
    PRIOR_MINUTES_COLUMN,
    PRIOR_RATE_COLUMN,
    CrossSeasonConfig,
    FeatureConfig,
    build_feature_dataset,
)
from squadopt.features.cross_season import carry_over_as_of
from squadopt.features.fixtures import FIXTURE_FEATURE_COLUMNS, attach_fixture_features
from squadopt.prediction import (
    PredictionProvenance,
    PredictionSnapshot,
    prepare_optimizer_projection,
)
from squadopt.prediction.config import FITTED_OPENING_PRICE_COEFFICIENT
from squadopt.prediction.production import ProductionProjectionConfig, production_projection

PRODUCTION_MODEL_NAME: Final = "squadopt-two-stage"
PRODUCTION_MODEL_VERSION: Final = "two-stage-v1"

# Bumped when the feature set or its construction changes in a way that makes two runs
# incomparable. It names the calendar explicitly, because fixture context is the
# difference between this feature set and every earlier one.
PRODUCTION_FEATURE_CONTRACT_VERSION: Final = "two-stage-appearance-calendar-v1"

_SNAPSHOT_COLUMNS: Final = ("player_id", "name", "team_id", "position", "price_tenths")


def production_feature_config(config: ProductionProjectionConfig) -> FeatureConfig:
    """Return the feature configuration the projection's windows imply.

    Derived from the projection config rather than declared separately, so a window can
    never be tuned in one place and read from another.
    """

    window = config.minutes.window
    return FeatureConfig(
        minutes_windows=(window,),
        points_windows=(config.rate_window,),
        per_90_window=config.rate_window,
        appearance_windows=(window,),
        min_periods=1,
    )


def _training_cutoff(training: pd.DataFrame) -> str:
    last = training.iloc[-1]
    return f"{last['season']}:GW{int(last['gameweek']):02d}"


def _fingerprint(training: pd.DataFrame) -> str:
    """Digest the rows a fold was allowed to see.

    Only the identity and outcome columns are hashed. Features are a deterministic
    function of them, so including features would restate the same information while
    making the digest depend on the feature configuration as well as the data.
    """

    columns = [
        column
        for column in ("season", "gameweek", "player_id", "minutes", "total_points")
        if column in training.columns
    ]
    ordered = training.loc[:, columns].sort_values(columns, kind="stable")
    payload = ordered.to_csv(index=False).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _completed_seasons(visible: pd.DataFrame, decision: DecisionPoint) -> tuple[str, ...]:
    seasons = sorted({str(value) for value in visible["season"].tolist()})
    return tuple(season for season in seasons if season < decision.season)


def _price_coefficient(visible: pd.DataFrame, decision: DecisionPoint) -> tuple[float, str]:
    """Refit the opening price prior on the seasons completed before this decision."""

    seasons = _completed_seasons(visible, decision)
    if not seasons:
        # The first season has nothing to fit on. Falling back to the frozen constant is
        # stated in the diagnostics rather than hidden, because that fold's opening
        # behaviour is then not a product of this fold's own history.
        return FITTED_OPENING_PRICE_COEFFICIENT, "frozen_constant_no_completed_seasons"
    return fit_opening_price_coefficient(visible, seasons=seasons), "refit_expanding_window"


def _season_features(
    visible: pd.DataFrame,
    season: str,
    feature_config: FeatureConfig,
    carry_over: pd.DataFrame,
) -> pd.DataFrame:
    """Build one season's features plus the carry-over known entering that season."""

    season_rows = visible.loc[visible["season"] == season].copy(deep=True)
    features = build_feature_dataset(season_rows, config=feature_config)
    features = features.merge(carry_over, on="player_id", how="left", validate="many_to_one")
    for column in (PRIOR_MINUTES_COLUMN, PRIOR_RATE_COLUMN):
        features[column] = features[column].astype("float64")
    return features


def build_production_prediction_snapshot(
    visible: pd.DataFrame,
    decision: DecisionPoint,
    *,
    fixtures: pd.DataFrame,
    team_codes: pd.DataFrame,
    config: ProductionProjectionConfig | None = None,
    cross_season: CrossSeasonConfig | None = None,
) -> PredictionSnapshot:
    """Project the decision gameweek's roster from the visible panel alone."""

    settings = ProductionProjectionConfig() if config is None else config
    carry = CrossSeasonConfig() if cross_season is None else cross_season
    if not isinstance(settings, ProductionProjectionConfig):
        raise BacktestConfigurationError("config must be a ProductionProjectionConfig.")
    if not isinstance(carry, CrossSeasonConfig):
        raise BacktestConfigurationError("cross_season must be a CrossSeasonConfig.")

    feature_config = production_feature_config(settings)
    seasons = sorted({str(value) for value in visible["season"].tolist()})
    frames = [
        _season_features(
            visible,
            season,
            feature_config,
            carry_over_as_of(visible, target_season=season, config=carry),
        )
        for season in seasons
    ]
    features = pd.concat(frames, ignore_index=True)
    features = attach_fixture_features(features, fixtures, team_codes)

    return _snapshot_from_features(features, visible, decision, settings)


def _snapshot_from_features(
    features: pd.DataFrame,
    visible: pd.DataFrame,
    decision: DecisionPoint,
    settings: ProductionProjectionConfig,
) -> PredictionSnapshot:
    training = rows_before(features, decision)
    if training.empty:
        raise BacktestConfigurationError(f"No training rows before {decision.fold_id}.")
    target = features.loc[
        (features["season"] == decision.season) & (features["gameweek"] == decision.gameweek)
    ].copy(deep=True)
    if target.empty:
        raise BacktestConfigurationError(f"No target rows for {decision.fold_id}.")

    coefficient, prior_origin = _price_coefficient(visible, decision)
    fold_settings = ProductionProjectionConfig(
        rate_window=settings.rate_window,
        carry_over_rate_weight=settings.carry_over_rate_weight,
        opening_price_coefficient=coefficient,
        minutes=settings.minutes,
    )
    projection = production_projection(target, config=fold_settings)

    predictions = pd.DataFrame(
        {
            "player_id": target["player_id"].to_numpy(),
            "expected_points": projection.expected_points.to_numpy(),
        }
    )
    provenance = PredictionProvenance(
        model_name=PRODUCTION_MODEL_NAME,
        model_version=PRODUCTION_MODEL_VERSION,
        feature_contract_version=PRODUCTION_FEATURE_CONTRACT_VERSION,
        training_cutoff=_training_cutoff(training),
        training_data_fingerprint=_fingerprint(training),
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
        diagnostics={
            **dict(snapshot.diagnostics),
            **_route_counts(projection.minutes_source, "minutes_source"),
            **_route_counts(projection.rate_source, "rate_source"),
            **_route_counts(projection.points_source, "points_source"),
            "training_rows": len(training),
            "appearance_window": settings.minutes.window,
            "rate_window": settings.rate_window,
            "carry_over_minutes_weight": settings.minutes.carry_over_weight,
            "carry_over_rate_weight": settings.carry_over_rate_weight,
            "opening_price_coefficient": coefficient,
            "opening_price_prior_origin": prior_origin,
            "double_gameweek_players": int((target["fixture_count"] > 1).sum()),
            "blank_gameweek_players": int((target["fixture_count"] == 0).sum()),
        },
    )


def _route_counts(source: pd.Series, label: str) -> Mapping[str, int]:
    """Count how many players each rung produced, so fallbacks stay visible."""

    counts = source.value_counts()
    return {f"{label}:{route}": int(count) for route, count in counts.items()}


def make_production_projection_builder(
    *,
    fixtures: pd.DataFrame,
    team_codes: pd.DataFrame,
    config: ProductionProjectionConfig | None = None,
    cross_season: CrossSeasonConfig | None = None,
) -> Callable[[pd.DataFrame, DecisionPoint], PredictionSnapshot]:
    """Return a builder matching the walk-forward contract.

    Completed seasons are cached because their features cannot change once the season is
    past, while the current season is rebuilt every fold as its history grows. The cache
    holds only what the panel already contains, so it cannot make a later fold see
    anything an earlier one could not.
    """

    settings = ProductionProjectionConfig() if config is None else config
    carry = CrossSeasonConfig() if cross_season is None else cross_season
    feature_config = production_feature_config(settings)
    completed_cache: dict[str, pd.DataFrame] = {}
    carry_cache: dict[str, pd.DataFrame] = {}

    def build(visible: pd.DataFrame, decision: DecisionPoint) -> PredictionSnapshot:
        seasons = sorted({str(value) for value in visible["season"].tolist()})
        for season in seasons:
            if season not in carry_cache:
                carry_cache[season] = carry_over_as_of(visible, target_season=season, config=carry)
        frames: list[pd.DataFrame] = []
        for season in seasons:
            if season < decision.season:
                if season not in completed_cache:
                    completed_cache[season] = _season_features(
                        visible, season, feature_config, carry_cache[season]
                    )
                frames.append(completed_cache[season])
            else:
                frames.append(
                    _season_features(visible, season, feature_config, carry_cache[season])
                )
        features = pd.concat(frames, ignore_index=True)
        features = attach_fixture_features(features, fixtures, team_codes)
        return _snapshot_from_features(features, visible, decision, settings)

    return build


__all__ = [
    "FIXTURE_FEATURE_COLUMNS",
    "PRODUCTION_FEATURE_CONTRACT_VERSION",
    "PRODUCTION_MODEL_NAME",
    "PRODUCTION_MODEL_VERSION",
    "build_production_prediction_snapshot",
    "make_production_projection_builder",
    "production_feature_config",
]
