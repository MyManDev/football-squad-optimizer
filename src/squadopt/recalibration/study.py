"""Chronological uncertainty and scenario recalibration on matched residual regimes."""

import hashlib
import json
import math
from dataclasses import asdict, dataclass
from typing import cast

import numpy as np
import pandas as pd

from squadopt.data.schema import season_rank_map
from squadopt.recalibration.measurement import measure_calendar_recalibration
from squadopt.recalibration.models import (
    FIXTURE_GROUPS,
    FixtureIntervalComparison,
    IntervalMetrics,
    PlayerScaleComparison,
    RecalibrationValidationError,
    ScenarioComponentComparison,
    ScenarioComponentMetrics,
    TimeAwareRecalibrationConfig,
    TimeAwareRecalibrationResult,
)
from squadopt.scenarios.decomposition import decompose_residual_components


@dataclass(frozen=True, slots=True)
class _ScaleState:
    pooled_scale: float
    position_scales: dict[str, float]
    position_observations: dict[str, int]
    player_scales: dict[object, float]
    player_observations: dict[object, int]


@dataclass(frozen=True, slots=True)
class _RegimeState:
    scale: _ScaleState
    conformal_multipliers: dict[str, float]
    pooled_multiplier: float


def _population_scale(values: pd.Series, minimum: float) -> float:
    scale = float(values.to_numpy(dtype="float64").std(ddof=0))
    return max(scale, minimum)


def _fit_scale_state(frame: pd.DataFrame, config: TimeAwareRecalibrationConfig) -> _ScaleState:
    pooled = _population_scale(frame["residual"], config.minimum_scale)
    position_scales: dict[str, float] = {}
    position_observations: dict[str, int] = {}
    for position, group in frame.groupby("position", sort=True):
        label = str(position)
        count = len(group)
        position_observations[label] = count
        position_scales[label] = (
            _population_scale(group["residual"], config.minimum_scale)
            if count >= config.min_position_observations
            else pooled
        )

    player_scales: dict[object, float] = {}
    player_observations: dict[object, int] = {}
    for player_id, group in frame.groupby("player_id", sort=True):
        count = len(group)
        player_observations[player_id] = count
        if count < config.min_player_observations:
            continue
        player_scale = _population_scale(group["residual"], config.minimum_scale)
        latest_position = str(group.iloc[-1]["position"])
        fallback = position_scales.get(latest_position, pooled)
        strength = config.shrinkage_observations
        variance = (count * player_scale**2 + strength * fallback**2) / (count + strength)
        player_scales[player_id] = max(math.sqrt(variance), config.minimum_scale)
    return _ScaleState(
        pooled_scale=pooled,
        position_scales=position_scales,
        position_observations=position_observations,
        player_scales=player_scales,
        player_observations=player_observations,
    )


def _effective_scale(
    state: _ScaleState, player_id: object, position: str
) -> tuple[float, str, int]:
    if player_id in state.player_scales:
        return (
            state.player_scales[player_id],
            "player_shrunk",
            state.player_observations[player_id],
        )
    if position in state.position_scales:
        return (
            state.position_scales[position],
            "position_fallback",
            state.position_observations[position],
        )
    return state.pooled_scale, "pooled_fallback", 0


def _finite_sample_quantile(values: list[float], probability: float) -> float:
    if not values:
        raise RecalibrationValidationError(
            "Conformal calibration requires at least one standardized residual."
        )
    ordered = sorted(values)
    rank = min(len(ordered), math.ceil((len(ordered) + 1) * probability))
    return ordered[rank - 1]


def _fit_regime(
    scale_rows: pd.DataFrame,
    conformal_rows: pd.DataFrame,
    config: TimeAwareRecalibrationConfig,
) -> _RegimeState:
    scale = _fit_scale_state(scale_rows, config)
    scored = conformal_rows.copy(deep=True)
    standardized: list[float] = []
    for row in scored.itertuples(index=False):
        local_scale, _, _ = _effective_scale(scale, row.player_id, str(row.position))
        standardized.append(abs(float(cast(float, row.residual))) / local_scale)
    scored["standardized_residual"] = standardized
    pooled_scores = scored["standardized_residual"].astype("float64").tolist()
    pooled_multiplier = _finite_sample_quantile(pooled_scores, config.confidence_level)
    position_multipliers: dict[str, float] = {}
    for position, group in scored.groupby("position", sort=True):
        values = group["standardized_residual"].astype("float64").tolist()
        position_multipliers[str(position)] = (
            _finite_sample_quantile(values, config.confidence_level)
            if len(values) >= config.min_position_observations
            else pooled_multiplier
        )
    return _RegimeState(scale, position_multipliers, pooled_multiplier)


def _score_intervals(frame: pd.DataFrame, state: _RegimeState) -> pd.DataFrame:
    scored = frame.copy(deep=True)
    widths: list[float] = []
    covered: list[bool] = []
    for row in scored.itertuples(index=False):
        position = str(row.position)
        scale, _, _ = _effective_scale(state.scale, row.player_id, position)
        multiplier = state.conformal_multipliers.get(position, state.pooled_multiplier)
        radius = multiplier * scale
        widths.append(2.0 * radius)
        covered.append(abs(float(cast(float, row.residual))) <= radius)
    scored["interval_width"] = widths
    scored["interval_covered"] = covered
    return scored


def _interval_metrics(frame: pd.DataFrame) -> IntervalMetrics:
    return IntervalMetrics(
        observations=len(frame),
        empirical_coverage=float(frame["interval_covered"].astype("float64").mean()),
        mean_interval_width=float(frame["interval_width"].astype("float64").mean()),
    )


def _interval_comparisons(
    reference: pd.DataFrame, candidate: pd.DataFrame
) -> tuple[FixtureIntervalComparison, ...]:
    comparisons: list[FixtureIntervalComparison] = []
    for group_name in ("overall", *FIXTURE_GROUPS):
        reference_group = (
            reference
            if group_name == "overall"
            else reference.loc[reference["fixture_group"] == group_name]
        )
        candidate_group = (
            candidate
            if group_name == "overall"
            else candidate.loc[candidate["fixture_group"] == group_name]
        )
        if reference_group.empty:
            continue
        reference_metrics = _interval_metrics(reference_group)
        candidate_metrics = _interval_metrics(candidate_group)
        comparisons.append(
            FixtureIntervalComparison(
                fixture_group=group_name,
                reference=reference_metrics,
                candidate=candidate_metrics,
                coverage_delta=(
                    candidate_metrics.empirical_coverage - reference_metrics.empirical_coverage
                ),
                mean_interval_width_delta=(
                    candidate_metrics.mean_interval_width - reference_metrics.mean_interval_width
                ),
            )
        )
    return tuple(comparisons)


def _player_scale_comparisons(
    reference_rows: pd.DataFrame,
    reference_state: _ScaleState,
    candidate_state: _ScaleState,
) -> tuple[PlayerScaleComparison, ...]:
    double_rows = reference_rows.loc[reference_rows["fixture_group"] == "double_plus"]
    player_ids = sorted(double_rows["player_id"].unique().tolist(), key=str)
    comparisons: list[PlayerScaleComparison] = []
    for player_id in player_ids:
        history = reference_rows.loc[reference_rows["player_id"] == player_id]
        position = str(history.iloc[-1]["position"])
        reference_scale, reference_source, _ = _effective_scale(
            reference_state, player_id, position
        )
        candidate_scale, candidate_source, _ = _effective_scale(
            candidate_state, player_id, position
        )
        comparisons.append(
            PlayerScaleComparison(
                player_id=player_id,
                position=position,
                observations=len(history),
                double_plus_observations=int((history["fixture_group"] == "double_plus").sum()),
                reference_source=reference_source,
                candidate_source=candidate_source,
                reference_scale=reference_scale,
                candidate_scale=candidate_scale,
                scale_delta=candidate_scale - reference_scale,
            )
        )
    return tuple(comparisons)


def _component_metrics(frame: pd.DataFrame, candidate: str) -> ScenarioComponentMetrics:
    decomposed = decompose_residual_components(frame)
    common = decomposed.groupby("fold_id", sort=False)["common_component"].first()
    team = decomposed.groupby(["fold_id", "team_id"], sort=False)["team_component"].first()
    common_stddev = float(common.to_numpy(dtype="float64").std(ddof=0))
    team_stddev = float(team.to_numpy(dtype="float64").std(ddof=0))
    idiosyncratic_stddev = float(
        decomposed["idiosyncratic_component"].to_numpy(dtype="float64").std(ddof=0)
    )
    variances = np.square(
        np.asarray([common_stddev, team_stddev, idiosyncratic_stddev], dtype="float64")
    )
    denominator = float(variances.sum())
    shares = variances / denominator if denominator > 0.0 else np.zeros(3)
    return ScenarioComponentMetrics(
        candidate=candidate,
        observations=len(decomposed),
        fold_count=int(decomposed["fold_id"].nunique()),
        team_fold_count=len(team),
        common_stddev=common_stddev,
        team_stddev=team_stddev,
        idiosyncratic_stddev=idiosyncratic_stddev,
        common_variance_share=float(shares[0]),
        team_variance_share=float(shares[1]),
        idiosyncratic_variance_share=float(shares[2]),
    )


def _study_fingerprint(
    config: TimeAwareRecalibrationConfig,
    measurement_fingerprint: str,
    splits: tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]],
    intervals: tuple[FixtureIntervalComparison, ...],
    scales: tuple[PlayerScaleComparison, ...],
    components: ScenarioComponentComparison,
) -> str:
    payload = {
        "contract_version": config.contract_version,
        "configuration_fingerprint": config.configuration_fingerprint,
        "measurement_fingerprint": measurement_fingerprint,
        "splits": splits,
        "intervals": [asdict(value) for value in intervals],
        "scales": [asdict(value) for value in scales],
        "components": asdict(components),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def run_time_aware_recalibration(
    residuals: pd.DataFrame,
    fixtures: pd.DataFrame,
    team_codes: pd.DataFrame,
    config: TimeAwareRecalibrationConfig | None = None,
) -> TimeAwareRecalibrationResult:
    """Fit on past folds and compare both residual regimes on later matched folds."""

    settings = TimeAwareRecalibrationConfig() if config is None else config
    if not isinstance(settings, TimeAwareRecalibrationConfig):
        raise RecalibrationValidationError("config must be a TimeAwareRecalibrationConfig.")
    measurement = measure_calendar_recalibration(
        residuals, fixtures, team_codes, settings.residual_config
    )
    enriched = measurement.residuals_with_fixture_context
    reference_label = settings.residual_config.reference_candidate
    candidate_label = settings.residual_config.candidate
    reference = enriched.loc[enriched["candidate"] == reference_label].copy(deep=True)
    candidate = enriched.loc[enriched["candidate"] == candidate_label].copy(deep=True)

    ranks = season_rank_map(reference["season"].astype(str).tolist())
    fold_rows = reference.loc[:, ["fold_id", "season", "gameweek"]].drop_duplicates()
    fold_rows["season_rank"] = fold_rows["season"].map(ranks)
    fold_ids = tuple(
        fold_rows.sort_values(["season_rank", "gameweek", "fold_id"], kind="stable")[
            "fold_id"
        ].tolist()
    )
    if len(fold_ids) < 3:
        raise RecalibrationValidationError(
            "Time-aware recalibration requires at least three chronological folds."
        )
    scale_count = max(1, math.floor(len(fold_ids) * settings.scale_training_fraction))
    conformal_count = max(
        1,
        math.floor(len(fold_ids) * settings.conformal_calibration_fraction),
    )
    if scale_count + conformal_count >= len(fold_ids):
        raise RecalibrationValidationError(
            "Configured chronological split leaves no evaluation fold."
        )
    scale_ids = fold_ids[:scale_count]
    conformal_ids = fold_ids[scale_count : scale_count + conformal_count]
    evaluation_ids = fold_ids[scale_count + conformal_count :]

    def select(frame: pd.DataFrame, ids: tuple[str, ...]) -> pd.DataFrame:
        return frame.loc[frame["fold_id"].isin(ids)].copy(deep=True)

    reference_scale_rows = select(reference, scale_ids)
    candidate_scale_rows = select(candidate, scale_ids)
    reference_state = _fit_regime(reference_scale_rows, select(reference, conformal_ids), settings)
    candidate_state = _fit_regime(candidate_scale_rows, select(candidate, conformal_ids), settings)
    reference_evaluation = _score_intervals(select(reference, evaluation_ids), reference_state)
    candidate_evaluation = _score_intervals(select(candidate, evaluation_ids), candidate_state)
    intervals = _interval_comparisons(reference_evaluation, candidate_evaluation)
    scales = _player_scale_comparisons(
        reference_scale_rows,
        reference_state.scale,
        candidate_state.scale,
    )
    history_ids = (*scale_ids, *conformal_ids)
    reference_components = _component_metrics(select(reference, history_ids), reference_label)
    candidate_components = _component_metrics(select(candidate, history_ids), candidate_label)
    components = ScenarioComponentComparison(
        reference=reference_components,
        candidate=candidate_components,
        common_stddev_delta=(
            candidate_components.common_stddev - reference_components.common_stddev
        ),
        team_stddev_delta=(candidate_components.team_stddev - reference_components.team_stddev),
        idiosyncratic_stddev_delta=(
            candidate_components.idiosyncratic_stddev - reference_components.idiosyncratic_stddev
        ),
    )
    splits = (scale_ids, conformal_ids, evaluation_ids)
    fingerprint = _study_fingerprint(
        settings,
        measurement.measurement_fingerprint,
        splits,
        intervals,
        scales,
        components,
    )
    return TimeAwareRecalibrationResult(
        config=settings,
        measurement=measurement,
        scale_training_fold_ids=scale_ids,
        conformal_calibration_fold_ids=conformal_ids,
        evaluation_fold_ids=evaluation_ids,
        interval_comparisons=intervals,
        player_scale_comparisons=scales,
        scenario_components=components,
        study_fingerprint=fingerprint,
        diagnostics={
            "fold_count": len(fold_ids),
            "scale_training_rows_per_regime": len(reference_scale_rows),
            "conformal_calibration_rows_per_regime": len(select(reference, conformal_ids)),
            "evaluation_rows_per_regime": len(reference_evaluation),
            "chronological_split_verified": True,
            "evaluation_refit": False,
            "matched_evaluation_rows": True,
            "fixture_conditioned_reporting": True,
            "double_gameweek_player_scale_count": len(scales),
            "opening_gameweek_uncertainty_inferred": False,
        },
    )
