"""Leakage-safe walk-forward benchmark for the Ridge reference projection."""

import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from numbers import Integral
from statistics import fmean
from types import MappingProxyType
from typing import Final

import pandas as pd

from squadopt.backtest.folds import build_walk_forward_folds, make_baseline_projection_builder
from squadopt.backtest.splits import BacktestConfigurationError, DecisionPoint, rows_before
from squadopt.evaluation import (
    EvaluationConfig,
    EvaluationFold,
    EvaluationResult,
    evaluate_prepared_folds,
)
from squadopt.features import (
    PRIOR_MINUTES_COLUMN,
    PRIOR_RATE_COLUMN,
    CrossSeasonConfig,
    build_feature_dataset,
)
from squadopt.features.cross_season import carry_over_as_of
from squadopt.optimization import OptimizationConfig
from squadopt.prediction import (
    PredictionProvenance,
    PredictionSnapshot,
    prepare_optimizer_projection,
)
from squadopt.prediction.factors import FEATURE_GENERATION_CONTRACT_VERSION, FormWindowMapping
from squadopt.prediction.learned import (
    RIDGE_FEATURE_CONTRACT_VERSION,
    RIDGE_MODEL_NAME,
    RIDGE_MODEL_VERSION,
    RidgeProjectionConfig,
    fit_ridge_predictor,
    predict_ridge_expected_points,
)

LEARNED_BENCHMARK_CONTRACT_VERSION: Final = "learned_vs_baseline_v1"
DEFAULT_LEARNED_BENCHMARK_SEASONS: Final = (
    "2021-22",
    "2022-23",
    "2023-24",
    "2024-25",
)
LOCKED_HOLDOUT_SEASON: Final = "2025-26"
RESIDUAL_COLUMNS: Final = (
    "fold_id",
    "season",
    "gameweek",
    "player_id",
    "team_id",
    "position",
    "predicted_points",
    "realized_points",
    "residual",
)


@dataclass(frozen=True, slots=True)
class LearnedBenchmarkConfig:
    """Development-only controls for the paired baseline/Ridge benchmark."""

    seasons: tuple[str, ...] = DEFAULT_LEARNED_BENCHMARK_SEASONS
    min_prior_gameweeks_in_season: int = 1
    ridge_config: RidgeProjectionConfig = field(default_factory=RidgeProjectionConfig)
    cross_season_config: CrossSeasonConfig = field(default_factory=CrossSeasonConfig)
    optimization_config: OptimizationConfig = field(default_factory=OptimizationConfig)
    run_metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.seasons, tuple) or not self.seasons:
            raise BacktestConfigurationError("seasons must be a non-empty tuple.")
        if any(not isinstance(season, str) for season in self.seasons):
            raise BacktestConfigurationError("seasons entries must be strings.")
        seasons = tuple(season.strip() for season in self.seasons)
        if any(not season for season in seasons) or len(set(seasons)) != len(seasons):
            raise BacktestConfigurationError("seasons must contain unique non-empty labels.")
        if LOCKED_HOLDOUT_SEASON in seasons:
            raise BacktestConfigurationError(
                f"{LOCKED_HOLDOUT_SEASON} is the locked holdout and cannot be read by "
                "the Sprint 6 development benchmark."
            )
        minimum = self.min_prior_gameweeks_in_season
        if isinstance(minimum, bool) or not isinstance(minimum, Integral):
            raise BacktestConfigurationError("min_prior_gameweeks_in_season must be an integer.")
        normalized_minimum = int(minimum)
        if normalized_minimum < 1:
            raise BacktestConfigurationError(
                "The learned benchmark excludes opening gameweeks; minimum must be at least 1."
            )
        if not isinstance(self.ridge_config, RidgeProjectionConfig):
            raise BacktestConfigurationError("ridge_config must be a RidgeProjectionConfig.")
        if not isinstance(self.cross_season_config, CrossSeasonConfig):
            raise BacktestConfigurationError("cross_season_config must be a CrossSeasonConfig.")
        if not isinstance(self.optimization_config, OptimizationConfig):
            raise BacktestConfigurationError("optimization_config must be an OptimizationConfig.")
        frozen_metadata = EvaluationConfig(
            optimization_config=self.optimization_config,
            run_metadata=self.run_metadata,
        ).run_metadata
        object.__setattr__(self, "seasons", seasons)
        object.__setattr__(self, "min_prior_gameweeks_in_season", normalized_minimum)
        object.__setattr__(self, "run_metadata", frozen_metadata)


@dataclass(frozen=True, slots=True)
class PositionPredictionMetrics:
    """Prediction errors for one canonical position."""

    position: str
    observations: int
    mean_absolute_error: float
    root_mean_squared_error: float
    mean_error: float


@dataclass(frozen=True, slots=True)
class PredictionMetrics:
    """Player-gameweek prediction errors overall and by position."""

    observations: int
    mean_absolute_error: float
    root_mean_squared_error: float
    mean_error: float
    by_position: tuple[PositionPredictionMetrics, ...]


@dataclass(frozen=True, slots=True)
class PairedDecisionMetrics:
    """Same-fold optimizer outcomes under baseline and learned projections."""

    folds: int
    comparable_scored_folds: int
    baseline_feasible_folds: int
    learned_feasible_folds: int
    baseline_mean_realized_points: float | None
    learned_mean_realized_points: float | None
    mean_realized_points_difference: float | None
    learned_wins: int
    ties: int
    learned_losses: int
    squad_changed_folds: int
    starting_xi_changed_folds: int
    captain_changed_folds: int
    mean_squad_entries: float | None
    mean_starting_xi_entries: float | None


@dataclass(frozen=True, slots=True)
class LearnedBenchmarkResult:
    """Complete paired benchmark plus learned out-of-sample residual history."""

    config: LearnedBenchmarkConfig
    baseline: EvaluationResult
    learned: EvaluationResult
    baseline_prediction_metrics: PredictionMetrics
    learned_prediction_metrics: PredictionMetrics
    decision_metrics: PairedDecisionMetrics
    residuals: pd.DataFrame
    diagnostics: Mapping[str, object]

    def __post_init__(self) -> None:
        if tuple(self.residuals.columns) != RESIDUAL_COLUMNS:
            raise BacktestConfigurationError(
                "residuals do not match the learned benchmark contract."
            )
        object.__setattr__(self, "residuals", self.residuals.copy(deep=True))
        object.__setattr__(self, "diagnostics", MappingProxyType(dict(self.diagnostics)))


def _training_cutoff(training: pd.DataFrame) -> str:
    last = training.iloc[-1]
    return f"{last['season']}:GW{int(last['gameweek']):02d}"


def build_ridge_prediction_snapshot(
    visible: pd.DataFrame,
    decision: DecisionPoint,
    *,
    config: RidgeProjectionConfig | None = None,
    cross_season: CrossSeasonConfig | None = None,
) -> PredictionSnapshot:
    """Fit on rows strictly before the decision and project its current roster."""

    settings = RidgeProjectionConfig() if config is None else config
    carry = CrossSeasonConfig() if cross_season is None else cross_season
    if not isinstance(settings, RidgeProjectionConfig):
        raise BacktestConfigurationError("config must be a RidgeProjectionConfig.")
    if not isinstance(carry, CrossSeasonConfig):
        raise BacktestConfigurationError("cross_season must be a CrossSeasonConfig.")
    mapping = FormWindowMapping(form_window=settings.form_window)
    features = build_feature_dataset(visible, config=mapping.feature_config, cross_season=carry)
    return _snapshot_from_features(features, decision, settings)


def _snapshot_from_features(
    features: pd.DataFrame,
    decision: DecisionPoint,
    settings: RidgeProjectionConfig,
) -> PredictionSnapshot:
    """Fit and predict after a caller has built the visible feature history."""

    training = rows_before(features, decision)
    target = features.loc[
        (features["season"] == decision.season) & (features["gameweek"] == decision.gameweek)
    ].copy(deep=True)
    if target.empty:
        raise BacktestConfigurationError(f"No target rows for {decision.fold_id}.")
    model = fit_ridge_predictor(training, settings)
    predictions = pd.DataFrame(
        {
            "player_id": target["player_id"].copy(),
            "expected_points": predict_ridge_expected_points(target, model),
        }
    )
    provenance = PredictionProvenance(
        model_name=RIDGE_MODEL_NAME,
        model_version=RIDGE_MODEL_VERSION,
        feature_contract_version=(
            f"{RIDGE_FEATURE_CONTRACT_VERSION}+{FEATURE_GENERATION_CONTRACT_VERSION}"
        ),
        training_cutoff=_training_cutoff(training),
        training_data_fingerprint=model.training_data_fingerprint,
    )
    snapshot = prepare_optimizer_projection(
        target.loc[:, ["player_id", "name", "team_id", "position", "price_tenths"]],
        predictions,
        provenance,
    )
    return PredictionSnapshot(
        table=snapshot.table,
        provenance=snapshot.provenance,
        prediction_fingerprint=snapshot.prediction_fingerprint,
        diagnostics={
            **dict(snapshot.diagnostics),
            "model_fingerprint": model.model_fingerprint,
            "training_rows": model.training_rows,
            "form_window": settings.form_window,
            "ridge_alpha": settings.alpha,
            "feature_names": model.feature_names,
            "imputation_policy": "training_median_else_zero",
            "prediction_floor": 0.0,
        },
    )


def _season_features(
    visible: pd.DataFrame,
    season: str,
    settings: RidgeProjectionConfig,
    carry_over: pd.DataFrame,
) -> pd.DataFrame:
    """Build one season plus carry-over known before that season."""

    mapping = FormWindowMapping(form_window=settings.form_window)
    season_rows = visible.loc[visible["season"] == season].copy(deep=True)
    features = build_feature_dataset(season_rows, config=mapping.feature_config)
    features = features.merge(carry_over, on="player_id", how="left", validate="many_to_one")
    for column in (PRIOR_MINUTES_COLUMN, PRIOR_RATE_COLUMN):
        features[column] = features[column].astype("float64")
    return features


def make_ridge_projection_builder(
    *,
    config: RidgeProjectionConfig | None = None,
    cross_season: CrossSeasonConfig | None = None,
) -> Callable[[pd.DataFrame, DecisionPoint], PredictionSnapshot]:
    """Return a state-free builder compatible with walk-forward preparation."""

    settings = RidgeProjectionConfig() if config is None else config
    carry = CrossSeasonConfig() if cross_season is None else cross_season
    completed_season_cache: dict[str, pd.DataFrame] = {}
    carry_over_cache: dict[str, pd.DataFrame] = {}

    def build(visible: pd.DataFrame, decision: DecisionPoint) -> PredictionSnapshot:
        seasons = sorted({str(value) for value in visible["season"].tolist()})
        earlier = [season for season in seasons if season < decision.season]
        for season in [*earlier, decision.season]:
            if season not in carry_over_cache:
                carry_over_cache[season] = carry_over_as_of(
                    visible,
                    target_season=season,
                    config=carry,
                )
        for season in earlier:
            if season not in completed_season_cache:
                completed_season_cache[season] = _season_features(
                    visible,
                    season,
                    settings,
                    carry_over_cache[season],
                )
        current = _season_features(
            visible,
            decision.season,
            settings,
            carry_over_cache[decision.season],
        )
        history = [completed_season_cache[season] for season in earlier]
        features = pd.concat([*history, current], ignore_index=True)
        return _snapshot_from_features(features, decision, settings)

    return build


def build_residual_history(folds: tuple[EvaluationFold, ...]) -> pd.DataFrame:
    """Build the canonical OOS residual table from chronological prepared folds."""

    if not isinstance(folds, tuple) or not folds:
        raise BacktestConfigurationError(
            "folds must be a non-empty tuple of EvaluationFold values."
        )
    if any(not isinstance(fold, EvaluationFold) for fold in folds):
        raise BacktestConfigurationError("folds must contain only EvaluationFold values.")
    records: list[pd.DataFrame] = []
    for fold in folds:
        projections = fold.projections.loc[
            :, ["player_id", "team_id", "position", "expected_points"]
        ]
        realized = fold.realized_points.loc[:, ["player_id", "total_points"]]
        joined = projections.merge(realized, on="player_id", how="inner", validate="one_to_one")
        joined = joined.rename(
            columns={"expected_points": "predicted_points", "total_points": "realized_points"}
        )
        joined["residual"] = joined["realized_points"] - joined["predicted_points"]
        joined.insert(0, "gameweek", int(str(fold.metadata["gameweek"])))
        joined.insert(0, "season", str(fold.metadata["season"]))
        joined.insert(0, "fold_id", fold.fold_id)
        records.append(joined.loc[:, list(RESIDUAL_COLUMNS)])
    return pd.concat(records, ignore_index=True)


def prediction_metrics(residuals: pd.DataFrame) -> PredictionMetrics:
    """Summarise prediction error overall and per position from a residual table.

    Public so a second candidate is measured by this code rather than by a copy of it.
    Two implementations of an error metric drift, and then two candidates' numbers are
    comparable only by coincidence.
    """

    def summarize(frame: pd.DataFrame) -> tuple[int, float, float, float]:
        errors = frame["predicted_points"] - frame["realized_points"]
        mae = float(errors.abs().mean())
        rmse = math.sqrt(float(errors.pow(2).mean()))
        bias = float(errors.mean())
        return len(frame), mae, rmse, bias

    overall = summarize(residuals)
    position_metrics: list[PositionPredictionMetrics] = []
    for position in ("GK", "DEF", "MID", "FWD"):
        position_rows = residuals.loc[residuals["position"] == position]
        position_metrics.append(PositionPredictionMetrics(position, *summarize(position_rows)))
    count, mae, rmse, bias = overall
    return PredictionMetrics(count, mae, rmse, bias, tuple(position_metrics))


def paired_decision_metrics(
    baseline: EvaluationResult,
    learned: EvaluationResult,
) -> PairedDecisionMetrics:
    if tuple(fold.fold_id for fold in baseline.folds) != tuple(
        fold.fold_id for fold in learned.folds
    ):
        raise BacktestConfigurationError("Baseline and learned fold sequences do not align.")
    differences: list[float] = []
    baseline_scores: list[float] = []
    learned_scores: list[float] = []
    squad_entries: list[int] = []
    starting_entries: list[int] = []
    wins = ties = losses = 0
    squad_changed = starting_changed = captain_changed = 0
    for control, candidate in zip(baseline.folds, learned.folds, strict=True):
        if control.is_scored and candidate.is_scored:
            assert control.realized_squad_points is not None
            assert candidate.realized_squad_points is not None
            difference = candidate.realized_squad_points - control.realized_squad_points
            differences.append(difference)
            baseline_scores.append(control.realized_squad_points)
            learned_scores.append(candidate.realized_squad_points)
            wins += difference > 0
            ties += difference == 0
            losses += difference < 0
        if control.optimization_result.has_solution and candidate.optimization_result.has_solution:
            base_squad = set(control.optimization_result.selected_squad["player_id"])
            learned_squad = set(candidate.optimization_result.selected_squad["player_id"])
            base_xi = set(control.optimization_result.starting_xi["player_id"])
            learned_xi = set(candidate.optimization_result.starting_xi["player_id"])
            squad_entry_count = len(learned_squad - base_squad)
            starting_entry_count = len(learned_xi - base_xi)
            squad_entries.append(squad_entry_count)
            starting_entries.append(starting_entry_count)
            squad_changed += squad_entry_count > 0
            starting_changed += starting_entry_count > 0
            base_captain = control.optimization_result.captain
            learned_captain = candidate.optimization_result.captain
            captain_changed += int(
                base_captain is not None
                and learned_captain is not None
                and bool(base_captain["player_id"] != learned_captain["player_id"])
            )
    return PairedDecisionMetrics(
        folds=len(baseline.folds),
        comparable_scored_folds=len(differences),
        baseline_feasible_folds=baseline.summary.feasible_folds,
        learned_feasible_folds=learned.summary.feasible_folds,
        baseline_mean_realized_points=fmean(baseline_scores) if baseline_scores else None,
        learned_mean_realized_points=fmean(learned_scores) if learned_scores else None,
        mean_realized_points_difference=fmean(differences) if differences else None,
        learned_wins=wins,
        ties=ties,
        learned_losses=losses,
        squad_changed_folds=squad_changed,
        starting_xi_changed_folds=starting_changed,
        captain_changed_folds=captain_changed,
        mean_squad_entries=fmean(squad_entries) if squad_entries else None,
        mean_starting_xi_entries=fmean(starting_entries) if starting_entries else None,
    )


def run_learned_benchmark(
    panel: pd.DataFrame,
    config: LearnedBenchmarkConfig | None = None,
) -> LearnedBenchmarkResult:
    """Compare baseline and expanding-window Ridge on identical development folds."""

    settings = LearnedBenchmarkConfig() if config is None else config
    if not isinstance(settings, LearnedBenchmarkConfig):
        raise BacktestConfigurationError("config must be a LearnedBenchmarkConfig.")
    baseline_folds = build_walk_forward_folds(
        panel,
        seasons=settings.seasons,
        min_prior_gameweeks_in_season=settings.min_prior_gameweeks_in_season,
        projection_builder=make_baseline_projection_builder(
            form_window=settings.ridge_config.form_window,
            cross_season=settings.cross_season_config,
        ),
    )
    learned_folds = build_walk_forward_folds(
        panel,
        seasons=settings.seasons,
        min_prior_gameweeks_in_season=settings.min_prior_gameweeks_in_season,
        projection_builder=make_ridge_projection_builder(
            config=settings.ridge_config,
            cross_season=settings.cross_season_config,
        ),
    )
    metadata = {
        **dict(settings.run_metadata),
        "benchmark_contract_version": LEARNED_BENCHMARK_CONTRACT_VERSION,
        "evaluation_seasons": settings.seasons,
        "locked_holdout_season": LOCKED_HOLDOUT_SEASON,
        "form_window": settings.ridge_config.form_window,
        "ridge_alpha": settings.ridge_config.alpha,
    }
    evaluation_config = EvaluationConfig(
        optimization_config=settings.optimization_config,
        run_metadata=metadata,
    )
    baseline = evaluate_prepared_folds(baseline_folds, evaluation_config)
    learned = evaluate_prepared_folds(learned_folds, evaluation_config)
    baseline_residuals = build_residual_history(baseline_folds)
    learned_residuals = build_residual_history(learned_folds)
    return LearnedBenchmarkResult(
        config=settings,
        baseline=baseline,
        learned=learned,
        baseline_prediction_metrics=prediction_metrics(baseline_residuals),
        learned_prediction_metrics=prediction_metrics(learned_residuals),
        decision_metrics=paired_decision_metrics(baseline, learned),
        residuals=learned_residuals,
        diagnostics={
            "benchmark_contract_version": LEARNED_BENCHMARK_CONTRACT_VERSION,
            "paired_fold_ids": tuple(fold.fold_id for fold in baseline.folds),
            "residual_definition": "realized_points_minus_predicted_points",
            "automatic_promotion": False,
            "holdout_accessed": False,
        },
    )
