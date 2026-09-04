"""Player-adaptive, leakage-safe standardized split-conformal intervals."""

import hashlib
import json
import math
from collections.abc import Iterable, Mapping
from dataclasses import asdict
from decimal import Decimal
from numbers import Integral, Real
from statistics import fmean, pstdev
from typing import cast

import pandas as pd

from squadopt.data.schema import POSITIONS, Position
from squadopt.evaluation import EvaluationFold
from squadopt.uncertainty.calibration import (
    INTERVAL_LOWER_COLUMN,
    INTERVAL_UPPER_COLUMN,
    UNCERTAINTY_GROUP_COLUMN,
    UNCERTAINTY_OBSERVATIONS_COLUMN,
    UNCERTAINTY_SOURCE_COLUMN,
    UNCERTAINTY_STDDEV_COLUMN,
    _aligned_scoring_table,
    _conformal_radius,
    _development_residuals,
    _fold_contexts,
    _group_metrics,
    _metrics,
    _validate_projection_table,
)
from squadopt.uncertainty.config import (
    PlayerAdaptiveUncertaintyConfig,
    UncertaintyConfig,
)
from squadopt.uncertainty.errors import UncertaintyValidationError
from squadopt.uncertainty.models import (
    AdaptiveGroupCalibration,
    CalibratedProjectionResult,
    PlayerAdaptiveUncertaintyCalibration,
    PlayerAdaptiveUncertaintyEvaluationResult,
    ResidualScaleSummary,
    UncertaintyFoldResult,
)

PLAYER_UNCERTAINTY_OBSERVATIONS_COLUMN = "player_uncertainty_observations"


def _context_config(config: PlayerAdaptiveUncertaintyConfig) -> UncertaintyConfig:
    return UncertaintyConfig(
        confidence_level=config.confidence_level,
        development_seasons=config.development_seasons,
        holdout_season=config.holdout_season,
        min_pooled_observations=config.min_pooled_observations,
        min_group_observations=config.min_position_observations,
    )


def _summary(values: list[float], label: str) -> ResidualScaleSummary:
    if not values:
        raise UncertaintyValidationError(f"{label} requires at least one residual.")
    try:
        mean = fmean(values)
        standard_deviation = pstdev(values)
    except (OverflowError, ValueError) as error:
        raise UncertaintyValidationError(f"{label} cannot be represented.") from error
    if not math.isfinite(mean) or not math.isfinite(standard_deviation):
        raise UncertaintyValidationError(f"{label} must contain finite diagnostics.")
    return ResidualScaleSummary(len(values), mean, standard_deviation)


def _typed_identifier(value: object) -> dict[str, object]:
    if isinstance(value, Integral) and not isinstance(value, bool):
        return {"kind": "integer", "value": int(value)}
    return {"kind": "string", "value": str(value)}


def _identifier_kind(value: object) -> str:
    return "integer" if isinstance(value, Integral) and not isinstance(value, bool) else "string"


def _scale_from_state(
    player_id: object,
    position: Position,
    config: PlayerAdaptiveUncertaintyConfig,
    groups: Mapping[Position, AdaptiveGroupCalibration],
    players: Mapping[object, ResidualScaleSummary],
) -> tuple[float, str, int, int]:
    group = groups[position]
    player = players.get(player_id)
    player_observations = player.observations if player is not None else 0
    if player is not None and player.observations >= config.min_player_observations:
        player_scale = max(player.residual_stddev, config.minimum_scale)
        scale = math.hypot(
            math.sqrt(player.observations) * player_scale,
            math.sqrt(config.shrinkage_observations) * group.position_scale,
        ) / math.sqrt(player.observations + config.shrinkage_observations)
        if not math.isfinite(scale):
            raise UncertaintyValidationError(
                f"Player {player_id!r} local residual scale cannot be represented."
            )
        return (
            max(scale, config.minimum_scale),
            "player_shrunk",
            player.observations,
            player_observations,
        )
    source = "position_fallback" if group.scale_source == "position" else "pooled_fallback"
    return group.position_scale, source, group.scale_observations, player_observations


def _local_scale(
    player_id: object,
    position: Position,
    calibration: PlayerAdaptiveUncertaintyCalibration,
) -> tuple[float, str, int, int]:
    return _scale_from_state(
        player_id,
        position,
        calibration.config,
        calibration.groups,
        calibration.players,
    )


def _fingerprint(
    config: PlayerAdaptiveUncertaintyConfig,
    scale_fold_ids: tuple[str, ...],
    conformal_fold_ids: tuple[str, ...],
    pooled: ResidualScaleSummary,
    groups: Mapping[Position, AdaptiveGroupCalibration],
    players: Mapping[object, ResidualScaleSummary],
) -> str:
    player_rows = [
        {
            "player_id": _typed_identifier(player_id),
            "summary": asdict(summary),
        }
        for player_id, summary in sorted(
            players.items(),
            key=lambda item: (type(item[0]).__name__, str(item[0])),
        )
    ]
    payload = {
        "configuration_fingerprint": config.configuration_fingerprint,
        "conformal_calibration_fold_ids": conformal_fold_ids,
        "groups": {position: asdict(groups[position]) for position in POSITIONS},
        "players": player_rows,
        "pooled_scale": asdict(pooled),
        "scale_training_fold_ids": scale_fold_ids,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _finite_number(value: object, label: str, *, non_negative: bool) -> float:
    if isinstance(value, bool) or not isinstance(value, (Real, Decimal)):
        raise UncertaintyValidationError(f"{label} must be a finite number.")
    try:
        normalized = float(value)
    except (OverflowError, TypeError, ValueError) as error:
        raise UncertaintyValidationError(f"{label} must be a finite number.") from error
    if not math.isfinite(normalized) or (non_negative and normalized < 0.0):
        raise UncertaintyValidationError(f"{label} must be finite and non-negative.")
    return normalized


def _validate_summary(
    summary: object,
    label: str,
    *,
    minimum_observations: int,
) -> ResidualScaleSummary:
    if not isinstance(summary, ResidualScaleSummary):
        raise UncertaintyValidationError(f"{label} must be a ResidualScaleSummary.")
    if (
        isinstance(summary.observations, bool)
        or not isinstance(summary.observations, Integral)
        or int(summary.observations) < minimum_observations
    ):
        raise UncertaintyValidationError(
            f"{label}.observations must be an integer of at least {minimum_observations}."
        )
    _finite_number(summary.residual_mean, f"{label}.residual_mean", non_negative=False)
    _finite_number(summary.residual_stddev, f"{label}.residual_stddev", non_negative=True)
    return summary


def _validate_calibration(
    calibration: PlayerAdaptiveUncertaintyCalibration,
) -> None:
    if not isinstance(calibration.config, PlayerAdaptiveUncertaintyConfig):
        raise UncertaintyValidationError(
            "calibration.config must be a PlayerAdaptiveUncertaintyConfig instance."
        )
    scale_ids = calibration.scale_training_fold_ids
    conformal_ids = calibration.conformal_calibration_fold_ids
    for values, label in (
        (scale_ids, "scale_training_fold_ids"),
        (conformal_ids, "conformal_calibration_fold_ids"),
    ):
        if (
            not isinstance(values, tuple)
            or not values
            or any(not isinstance(value, str) or not value for value in values)
            or len(set(values)) != len(values)
        ):
            raise UncertaintyValidationError(f"{label} must be a non-empty tuple of unique IDs.")
    if set(scale_ids) & set(conformal_ids):
        raise UncertaintyValidationError(
            "Scale-training and conformal-calibration fold IDs must be disjoint."
        )
    pooled = _validate_summary(
        calibration.pooled_scale,
        "pooled_scale",
        minimum_observations=calibration.config.min_pooled_observations,
    )

    if set(calibration.groups) != set(POSITIONS):
        raise UncertaintyValidationError(
            "calibration.groups must contain every canonical position exactly once."
        )
    for position in POSITIONS:
        group = calibration.groups[position]
        if not isinstance(group, AdaptiveGroupCalibration) or group.position != position:
            raise UncertaintyValidationError(
                f"calibration group {position!r} must match its canonical position."
            )
        counts = (
            group.scale_observations,
            group.group_calibration_observations,
            group.calibration_observations,
            group.conformal_rank,
        )
        if any(isinstance(value, bool) or not isinstance(value, Integral) for value in counts):
            raise UncertaintyValidationError(
                f"calibration group {position!r} counts and rank must be integers."
            )
        if (
            int(group.scale_observations) < 2
            or int(group.group_calibration_observations) < 0
            or int(group.calibration_observations) < 2
        ):
            raise UncertaintyValidationError(
                f"calibration group {position!r} effective counts must be at least 2."
            )
        if group.scale_source not in {"position", "pooled_fallback"}:
            raise UncertaintyValidationError(
                f"calibration group {position!r} has an invalid scale_source."
            )
        if (
            group.scale_source == "pooled_fallback"
            and int(group.scale_observations) != pooled.observations
        ):
            raise UncertaintyValidationError(
                f"calibration group {position!r} pooled scale count is inconsistent."
            )
        if group.scale_source == "position" and (
            int(group.scale_observations) < calibration.config.min_position_observations
        ):
            raise UncertaintyValidationError(
                f"calibration group {position!r} position scale is below its minimum count."
            )
        expected_conformal_source = (
            "position"
            if int(group.group_calibration_observations)
            >= calibration.config.min_position_observations
            else "pooled_fallback"
        )
        if group.conformal_source != expected_conformal_source:
            raise UncertaintyValidationError(
                f"calibration group {position!r} conformal source is inconsistent."
            )
        expected_calibration_count = (
            int(group.group_calibration_observations)
            if expected_conformal_source == "position"
            else sum(
                candidate.group_calibration_observations
                for candidate in calibration.groups.values()
            )
        )
        if int(group.calibration_observations) != expected_calibration_count:
            raise UncertaintyValidationError(
                f"calibration group {position!r} conformal count is inconsistent."
            )
        expected_rank = min(
            expected_calibration_count,
            math.ceil((expected_calibration_count + 1) * calibration.config.confidence_level),
        )
        if int(group.conformal_rank) != expected_rank:
            raise UncertaintyValidationError(
                f"calibration group {position!r} conformal rank is inconsistent."
            )
        scale = _finite_number(
            group.position_scale,
            f"calibration group {position!r} position_scale",
            non_negative=True,
        )
        multiplier = _finite_number(
            group.conformal_multiplier,
            f"calibration group {position!r} conformal_multiplier",
            non_negative=True,
        )
        if scale < calibration.config.minimum_scale or multiplier < 0.0:
            raise UncertaintyValidationError(
                f"calibration group {position!r} spread values are inconsistent."
            )

    if not calibration.players:
        raise UncertaintyValidationError("calibration.players must not be empty.")
    player_id_kinds: set[str] = set()
    player_observation_total = 0
    for player_id, summary in calibration.players.items():
        if isinstance(player_id, bool) or not (
            isinstance(player_id, Integral) or (isinstance(player_id, str) and player_id.strip())
        ):
            raise UncertaintyValidationError("calibration.players contains an invalid player_id.")
        player_id_kinds.add(_identifier_kind(player_id))
        _validate_summary(summary, f"player {player_id!r}", minimum_observations=1)
        player_observation_total += summary.observations
    if len(player_id_kinds) != 1:
        raise UncertaintyValidationError(
            "calibration.players must use one consistent player_id type."
        )
    if player_observation_total != pooled.observations:
        raise UncertaintyValidationError(
            "calibration player observation counts must equal pooled scale observations."
        )

    expected = _fingerprint(
        calibration.config,
        scale_ids,
        conformal_ids,
        pooled,
        calibration.groups,
        calibration.players,
    )
    if calibration.calibration_fingerprint != expected:
        raise UncertaintyValidationError(
            "calibration fingerprint does not match its configuration and learned state."
        )


def fit_player_adaptive_uncertainty(
    folds: Iterable[EvaluationFold],
    config: PlayerAdaptiveUncertaintyConfig | None = None,
) -> PlayerAdaptiveUncertaintyCalibration:
    """Fit local residual scales and conformal multipliers on disjoint past folds."""

    settings = PlayerAdaptiveUncertaintyConfig() if config is None else config
    if not isinstance(settings, PlayerAdaptiveUncertaintyConfig):
        raise UncertaintyValidationError(
            "config must be a PlayerAdaptiveUncertaintyConfig instance."
        )
    contexts = _fold_contexts(folds, _context_config(settings), role="development")
    if len(contexts) < 2:
        raise UncertaintyValidationError(
            "Player-adaptive calibration requires at least two chronological folds."
        )
    split = math.floor(len(contexts) * settings.scale_training_fraction)
    split = min(max(split, 1), len(contexts) - 1)
    scale_contexts = contexts[:split]
    conformal_contexts = contexts[split:]
    scale_residuals = _development_residuals(scale_contexts)
    conformal_residuals = _development_residuals(conformal_contexts)

    pooled_values = [float(value) for value in scale_residuals["residual"].tolist()]
    conformal_count = len(conformal_residuals)
    if len(pooled_values) < settings.min_pooled_observations:
        raise UncertaintyValidationError(
            "Scale-training residuals do not meet min_pooled_observations; "
            f"got {len(pooled_values)}, need {settings.min_pooled_observations}."
        )
    if conformal_count < settings.min_pooled_observations:
        raise UncertaintyValidationError(
            "Conformal-calibration residuals do not meet min_pooled_observations; "
            f"got {conformal_count}, need {settings.min_pooled_observations}."
        )
    pooled = _summary(pooled_values, "Pooled scale training")

    position_summaries: dict[Position, ResidualScaleSummary] = {}
    for position in POSITIONS:
        values = [
            float(value)
            for value in scale_residuals.loc[
                scale_residuals["position"].eq(position), "residual"
            ].tolist()
        ]
        if values:
            position_summaries[position] = _summary(values, f"Position {position} scale")

    player_summaries: dict[object, ResidualScaleSummary] = {}
    for player_id, selected in scale_residuals.groupby("player_id", sort=False):
        player_summaries[player_id] = _summary(
            [float(value) for value in selected["residual"].tolist()],
            f"Player {player_id!r} scale",
        )

    provisional_groups: dict[Position, AdaptiveGroupCalibration] = {}
    for position in POSITIONS:
        candidate = position_summaries.get(position)
        if candidate is not None and candidate.observations >= settings.min_position_observations:
            base = candidate
            scale_source = "position"
        else:
            base = pooled
            scale_source = "pooled_fallback"
        provisional_groups[position] = AdaptiveGroupCalibration(
            position=position,
            scale_source=scale_source,
            scale_observations=base.observations,
            position_scale=max(base.residual_stddev, settings.minimum_scale),
            conformal_source="pooled_fallback",
            group_calibration_observations=0,
            calibration_observations=conformal_count,
            conformal_multiplier=0.0,
            conformal_rank=1,
        )

    pooled_scores: list[float] = []
    scores_by_position: dict[Position, list[float]] = {position: [] for position in POSITIONS}
    for row in conformal_residuals.itertuples(index=False):
        position = cast(Position, str(row.position))
        scale, _, _, _ = _scale_from_state(
            row.player_id,
            position,
            settings,
            provisional_groups,
            player_summaries,
        )
        score = (
            abs(
                _finite_number(
                    row.residual,
                    "Conformal residual",
                    non_negative=False,
                )
            )
            / scale
        )
        if not math.isfinite(score):
            raise UncertaintyValidationError("Standardized conformal scores must be finite.")
        pooled_scores.append(score)
        scores_by_position[position].append(score)

    groups: dict[Position, AdaptiveGroupCalibration] = {}
    for position in POSITIONS:
        group_base = provisional_groups[position]
        position_scores = scores_by_position[position]
        if len(position_scores) >= settings.min_position_observations:
            effective_scores = position_scores
            conformal_source = "position"
        else:
            effective_scores = pooled_scores
            conformal_source = "pooled_fallback"
        multiplier, rank = _conformal_radius(effective_scores, settings.confidence_level)
        groups[position] = AdaptiveGroupCalibration(
            position=position,
            scale_source=group_base.scale_source,
            scale_observations=group_base.scale_observations,
            position_scale=group_base.position_scale,
            conformal_source=conformal_source,
            group_calibration_observations=len(position_scores),
            calibration_observations=len(effective_scores),
            conformal_multiplier=multiplier,
            conformal_rank=rank,
        )

    scale_fold_ids = tuple(context.fold.fold_id for context in scale_contexts)
    conformal_fold_ids = tuple(context.fold.fold_id for context in conformal_contexts)
    fingerprint = _fingerprint(
        settings,
        scale_fold_ids,
        conformal_fold_ids,
        pooled,
        groups,
        player_summaries,
    )
    calibration = PlayerAdaptiveUncertaintyCalibration(
        config=settings,
        scale_training_fold_ids=scale_fold_ids,
        conformal_calibration_fold_ids=conformal_fold_ids,
        pooled_scale=pooled,
        groups=groups,
        players=player_summaries,
        calibration_fingerprint=fingerprint,
        diagnostics={
            "contract_version": settings.contract_version,
            "configuration_fingerprint": settings.configuration_fingerprint,
            "development_fold_count": len(contexts),
            "scale_training_fold_count": len(scale_contexts),
            "conformal_calibration_fold_count": len(conformal_contexts),
            "residual_definition": "total_points-minus-expected_points",
            "scale_method": "player-variance-shrunk-to-position-with-fallback",
            "interval_method": "standardized-split-conformal",
            "calibration_split": "chronological-disjoint-folds",
            "opening_gameweeks_excluded": True,
        },
    )
    _validate_calibration(calibration)
    return calibration


def apply_player_adaptive_uncertainty(
    projections: pd.DataFrame,
    calibration: PlayerAdaptiveUncertaintyCalibration,
) -> CalibratedProjectionResult:
    """Attach player-adaptive uncertainty without changing point projections."""

    if not isinstance(calibration, PlayerAdaptiveUncertaintyCalibration):
        raise UncertaintyValidationError(
            "calibration must be a PlayerAdaptiveUncertaintyCalibration instance."
        )
    _validate_calibration(calibration)
    validated, application_id_kind = _validate_projection_table(projections, "application")
    learned_id_kind = _identifier_kind(next(iter(calibration.players)))
    if application_id_kind != learned_id_kind:
        raise UncertaintyValidationError(
            "Application projections and adaptive calibration must use the same player_id type."
        )
    stddevs: list[float] = []
    lowers: list[float] = []
    uppers: list[float] = []
    groups: list[str] = []
    sources: list[str] = []
    observations: list[int] = []
    player_observations: list[int] = []
    for player_id, position_value, expected_value in zip(
        validated["player_id"].tolist(),
        validated["position"].tolist(),
        validated["expected_points"].tolist(),
        strict=True,
    ):
        position = cast(Position, str(position_value))
        group = calibration.groups[position]
        scale, source, effective_count, player_count = _local_scale(
            player_id,
            position,
            calibration,
        )
        radius = group.conformal_multiplier * scale
        expected = float(expected_value)
        lower = expected - radius
        upper = expected + radius
        if not math.isfinite(lower) or not math.isfinite(upper):
            raise UncertaintyValidationError(
                "Applying player-adaptive calibration produced non-finite interval bounds."
            )
        stddevs.append(scale)
        lowers.append(lower)
        uppers.append(upper)
        groups.append(position)
        sources.append(source)
        observations.append(effective_count)
        player_observations.append(player_count)

    result = validated.copy(deep=True)
    result[UNCERTAINTY_STDDEV_COLUMN] = stddevs
    result[INTERVAL_LOWER_COLUMN] = lowers
    result[INTERVAL_UPPER_COLUMN] = uppers
    result[UNCERTAINTY_GROUP_COLUMN] = groups
    result[UNCERTAINTY_SOURCE_COLUMN] = sources
    result[UNCERTAINTY_OBSERVATIONS_COLUMN] = observations
    result[PLAYER_UNCERTAINTY_OBSERVATIONS_COLUMN] = player_observations
    result = result.astype(
        {
            UNCERTAINTY_GROUP_COLUMN: "string",
            UNCERTAINTY_SOURCE_COLUMN: "string",
            UNCERTAINTY_OBSERVATIONS_COLUMN: "int64",
            PLAYER_UNCERTAINTY_OBSERVATIONS_COLUMN: "int64",
        }
    )
    source_counts = result[UNCERTAINTY_SOURCE_COLUMN].value_counts().sort_index().to_dict()
    return CalibratedProjectionResult(
        table=result,
        calibration_fingerprint=calibration.calibration_fingerprint,
        diagnostics={
            "contract_version": calibration.config.contract_version,
            "configuration_fingerprint": calibration.config.configuration_fingerprint,
            "confidence_level": calibration.config.confidence_level,
            "uncertainty_source_counts": source_counts,
            "point_projection_changed": False,
            "interval_lower_bound_clamped": False,
        },
    )


def evaluate_player_adaptive_uncertainty(
    folds: Iterable[EvaluationFold],
    calibration: PlayerAdaptiveUncertaintyCalibration,
) -> PlayerAdaptiveUncertaintyEvaluationResult:
    """Apply a frozen player-adaptive calibration to its configured holdout season."""

    if not isinstance(calibration, PlayerAdaptiveUncertaintyCalibration):
        raise UncertaintyValidationError(
            "calibration must be a PlayerAdaptiveUncertaintyCalibration instance."
        )
    _validate_calibration(calibration)
    contexts = _fold_contexts(folds, _context_config(calibration.config), role="holdout")
    fold_results: list[UncertaintyFoldResult] = []
    id_kinds: set[str] = set()
    for context in contexts:
        calibrated = apply_player_adaptive_uncertainty(
            context.fold.projections,
            calibration,
        )
        aligned, id_kind = _aligned_scoring_table(
            calibrated.table,
            context.fold.realized_points,
            context.fold.fold_id,
        )
        id_kinds.add(id_kind)
        aligned.insert(0, "fold_id", context.fold.fold_id)
        aligned.insert(1, "season", context.season)
        aligned.insert(2, "gameweek", context.gameweek)
        aligned["residual"] = aligned["total_points"] - aligned["expected_points"]
        aligned["interval_covered"] = aligned["total_points"].ge(
            aligned[INTERVAL_LOWER_COLUMN]
        ) & aligned["total_points"].le(aligned[INTERVAL_UPPER_COLUMN])
        fold_results.append(
            UncertaintyFoldResult(
                fold_id=context.fold.fold_id,
                scored_players=aligned,
                metrics=_metrics(aligned),
                group_metrics=_group_metrics(aligned),
                metadata=context.fold.metadata,
            )
        )
    if len(id_kinds) != 1:
        raise UncertaintyValidationError(
            "player_id type must remain consistent across holdout folds."
        )
    combined = pd.concat(
        [fold.scored_players for fold in fold_results],
        ignore_index=True,
    )
    return PlayerAdaptiveUncertaintyEvaluationResult(
        calibration=calibration,
        folds=tuple(fold_results),
        metrics=_metrics(combined),
        group_metrics=_group_metrics(combined),
        diagnostics={
            "contract_version": calibration.config.contract_version,
            "calibration_fingerprint": calibration.calibration_fingerprint,
            "holdout_season": calibration.config.holdout_season,
            "holdout_fold_count": len(fold_results),
            "holdout_refit": False,
            "opening_gameweeks_excluded": True,
        },
    )
