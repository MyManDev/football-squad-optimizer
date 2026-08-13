"""Deterministic split-conformal calibration over prepared walk-forward folds."""

import hashlib
import json
import math
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from decimal import Decimal
from numbers import Integral, Real
from statistics import fmean, pstdev
from typing import cast

import pandas as pd

from squadopt.data.schema import POSITIONS, Position
from squadopt.evaluation import EvaluationFold
from squadopt.uncertainty.config import UncertaintyConfig
from squadopt.uncertainty.errors import UncertaintyValidationError
from squadopt.uncertainty.models import (
    CalibratedProjectionResult,
    GroupCalibration,
    ProjectionUncertaintyCalibration,
    UncertaintyEvaluationResult,
    UncertaintyFoldResult,
    UncertaintyMetrics,
)

UNCERTAINTY_STDDEV_COLUMN = "expected_points_stddev"
INTERVAL_LOWER_COLUMN = "prediction_interval_lower"
INTERVAL_UPPER_COLUMN = "prediction_interval_upper"
UNCERTAINTY_GROUP_COLUMN = "uncertainty_group"
UNCERTAINTY_SOURCE_COLUMN = "uncertainty_source"
UNCERTAINTY_OBSERVATIONS_COLUMN = "uncertainty_observations"

_PROJECTION_COLUMNS: tuple[str, ...] = ("player_id", "position", "expected_points")
_REALIZED_COLUMNS: tuple[str, ...] = ("player_id", "total_points")


@dataclass(frozen=True, slots=True)
class _FoldContext:
    fold: EvaluationFold
    season: str
    gameweek: int
    season_rank: int


def _as_fold_tuple(folds: Iterable[EvaluationFold]) -> tuple[EvaluationFold, ...]:
    if isinstance(folds, str | bytes):
        raise UncertaintyValidationError("folds must be an iterable of EvaluationFold values.")
    try:
        prepared = tuple(folds)
    except TypeError as error:
        raise UncertaintyValidationError(
            "folds must be an iterable of EvaluationFold values."
        ) from error
    if not prepared:
        raise UncertaintyValidationError("At least one prepared fold is required.")
    if any(not isinstance(fold, EvaluationFold) for fold in prepared):
        raise UncertaintyValidationError("Every folds entry must be an EvaluationFold.")
    return prepared


def _fold_contexts(
    folds: Iterable[EvaluationFold],
    config: UncertaintyConfig,
    *,
    role: str,
) -> tuple[_FoldContext, ...]:
    prepared = _as_fold_tuple(folds)
    fold_ids = [fold.fold_id for fold in prepared]
    duplicate_ids = sorted({fold_id for fold_id in fold_ids if fold_ids.count(fold_id) > 1})
    if duplicate_ids:
        raise UncertaintyValidationError(
            f"fold_id values must be unique; duplicates: {duplicate_ids!r}."
        )

    if role == "development":
        allowed = config.development_seasons
    elif role == "holdout":
        allowed = (config.holdout_season,)
    else:  # pragma: no cover - internal invariant
        raise AssertionError(f"Unknown fold role: {role!r}.")
    ranks = {season: rank for rank, season in enumerate(allowed)}

    contexts: list[_FoldContext] = []
    seen_decisions: set[tuple[str, int]] = set()
    for fold in prepared:
        season = fold.metadata.get("season")
        gameweek = fold.metadata.get("gameweek")
        if not isinstance(season, str) or not season.strip():
            raise UncertaintyValidationError(
                f"Fold {fold.fold_id!r} metadata must contain a non-empty season string."
            )
        season = season.strip()
        if season not in ranks:
            if season == config.holdout_season and role == "development":
                raise UncertaintyValidationError(
                    f"Holdout season {season!r} cannot be used to fit uncertainty calibration."
                )
            raise UncertaintyValidationError(
                f"Fold {fold.fold_id!r} season {season!r} is outside the configured "
                f"{role} seasons {allowed!r}."
            )
        if isinstance(gameweek, bool) or not isinstance(gameweek, Integral):
            raise UncertaintyValidationError(
                f"Fold {fold.fold_id!r} metadata gameweek must be an integer."
            )
        gameweek = int(gameweek)
        if gameweek <= 1:
            raise UncertaintyValidationError(
                "Opening gameweeks use a separate information set and are excluded from "
                f"uncertainty calibration; got fold {fold.fold_id!r}."
            )
        decision = (season, gameweek)
        if decision in seen_decisions:
            raise UncertaintyValidationError(
                f"Only one fold is allowed for decision {season!r} gameweek {gameweek}."
            )
        seen_decisions.add(decision)
        contexts.append(_FoldContext(fold, season, gameweek, ranks[season]))

    if role == "development":
        observed = {context.season for context in contexts}
        missing = [season for season in config.development_seasons if season not in observed]
        if missing:
            raise UncertaintyValidationError(
                f"Development folds do not cover configured seasons: {missing!r}."
            )

    return tuple(
        sorted(
            contexts,
            key=lambda item: (item.season_rank, item.gameweek, item.fold.fold_id),
        )
    )


def _identifier_kind(values: list[object], label: str) -> str:
    if not values:
        raise UncertaintyValidationError(f"{label} must contain at least one player row.")
    kinds: set[str] = set()
    invalid: list[object] = []
    for value in values:
        if isinstance(value, bool):
            invalid.append(value)
        elif isinstance(value, Integral):
            kinds.add("integer")
        elif isinstance(value, str) and value.strip():
            kinds.add("string")
        else:
            invalid.append(value)
    if invalid:
        raise UncertaintyValidationError(
            f"{label} player_id values must be non-empty strings or integers; "
            f"invalid examples: {invalid[:10]!r}."
        )
    if len(kinds) != 1:
        raise UncertaintyValidationError(
            f"{label} player_id must use one consistent ID type; found {sorted(kinds)!r}."
        )
    return next(iter(kinds))


def _finite_numbers(
    values: list[object],
    label: str,
    *,
    non_negative: bool,
) -> list[float]:
    converted: list[float] = []
    invalid: list[object] = []
    for value in values:
        if isinstance(value, bool) or not isinstance(value, (Real, Decimal)):
            invalid.append(value)
            continue
        try:
            number = float(value)
        except (OverflowError, TypeError, ValueError):
            invalid.append(value)
            continue
        if not math.isfinite(number) or (non_negative and number < 0.0):
            invalid.append(value)
            continue
        converted.append(number)
    if invalid:
        requirement = "finite and non-negative" if non_negative else "finite"
        raise UncertaintyValidationError(
            f"{label} values must be {requirement}; invalid examples: {invalid[:10]!r}."
        )
    return converted


def _validate_projection_table(table: pd.DataFrame, fold_id: str) -> tuple[pd.DataFrame, str]:
    if not isinstance(table, pd.DataFrame):
        raise UncertaintyValidationError(f"Fold {fold_id!r} projections must be a DataFrame.")
    duplicate_columns = table.columns[table.columns.duplicated()].tolist()
    if duplicate_columns:
        raise UncertaintyValidationError(
            f"Fold {fold_id!r} projections contain duplicate columns: {duplicate_columns!r}."
        )
    missing = [column for column in _PROJECTION_COLUMNS if column not in table.columns]
    if missing:
        raise UncertaintyValidationError(
            f"Fold {fold_id!r} projections are missing columns: {missing!r}."
        )
    selected = table.copy(deep=True)
    if selected.empty:
        raise UncertaintyValidationError(f"Fold {fold_id!r} projections must not be empty.")
    if bool(selected.loc[:, list(_PROJECTION_COLUMNS)].isna().any().any()):
        raise UncertaintyValidationError(
            f"Fold {fold_id!r} projection contract columns contain missing values."
        )
    ids = selected["player_id"].tolist()
    id_kind = _identifier_kind(ids, f"Fold {fold_id!r} projections")
    duplicates = selected.loc[selected["player_id"].duplicated(), "player_id"].tolist()
    if duplicates:
        raise UncertaintyValidationError(
            f"Fold {fold_id!r} projections contain duplicate player_id values: {duplicates[:10]!r}."
        )
    invalid_positions = sorted(
        {
            str(position)
            for position in selected["position"].tolist()
            if not isinstance(position, str) or position not in POSITIONS
        }
    )
    if invalid_positions:
        raise UncertaintyValidationError(
            f"Fold {fold_id!r} projections contain invalid positions: {invalid_positions!r}."
        )
    selected["expected_points"] = _finite_numbers(
        selected["expected_points"].tolist(),
        f"Fold {fold_id!r} expected_points",
        non_negative=True,
    )
    return selected, id_kind


def _validate_realized_table(table: pd.DataFrame, fold_id: str) -> tuple[pd.DataFrame, str]:
    if not isinstance(table, pd.DataFrame):
        raise UncertaintyValidationError(f"Fold {fold_id!r} realized_points must be a DataFrame.")
    duplicate_columns = table.columns[table.columns.duplicated()].tolist()
    if duplicate_columns:
        raise UncertaintyValidationError(
            f"Fold {fold_id!r} realized points contain duplicate columns: {duplicate_columns!r}."
        )
    missing = [column for column in _REALIZED_COLUMNS if column not in table.columns]
    if missing:
        raise UncertaintyValidationError(
            f"Fold {fold_id!r} realized points are missing columns: {missing!r}."
        )
    selected = table.loc[:, list(_REALIZED_COLUMNS)].copy(deep=True)
    if bool(selected.isna().any().any()):
        raise UncertaintyValidationError(
            f"Fold {fold_id!r} realized-point columns contain missing values."
        )
    ids = selected["player_id"].tolist()
    id_kind = _identifier_kind(ids, f"Fold {fold_id!r} realized points")
    duplicates = selected.loc[selected["player_id"].duplicated(), "player_id"].tolist()
    if duplicates:
        raise UncertaintyValidationError(
            f"Fold {fold_id!r} realized points contain duplicate player_id values: "
            f"{duplicates[:10]!r}."
        )
    selected["total_points"] = _finite_numbers(
        selected["total_points"].tolist(),
        f"Fold {fold_id!r} total_points",
        non_negative=False,
    )
    return selected, id_kind


def _aligned_scoring_table(
    projections: pd.DataFrame,
    realized_points: pd.DataFrame,
    fold_id: str,
) -> tuple[pd.DataFrame, str]:
    projected, projection_kind = _validate_projection_table(projections, fold_id)
    realized, realized_kind = _validate_realized_table(realized_points, fold_id)
    if projection_kind != realized_kind:
        raise UncertaintyValidationError(
            f"Fold {fold_id!r} projection and realized player_id types must match; "
            f"got {projection_kind} and {realized_kind}."
        )
    projected_ids = set(projected["player_id"].tolist())
    realized_ids = set(realized["player_id"].tolist())
    if projected_ids != realized_ids:
        missing_outcomes = sorted(projected_ids - realized_ids, key=str)
        missing_projections = sorted(realized_ids - projected_ids, key=str)
        raise UncertaintyValidationError(
            f"Fold {fold_id!r} requires exact player_id alignment; "
            f"missing outcomes={missing_outcomes[:10]!r}, "
            f"missing projections={missing_projections[:10]!r}."
        )
    merged = projected.merge(realized, on="player_id", how="inner", validate="one_to_one")
    return merged.sort_values("player_id", kind="stable").reset_index(drop=True), projection_kind


def _development_residuals(
    contexts: tuple[_FoldContext, ...],
) -> pd.DataFrame:
    records: list[pd.DataFrame] = []
    expected_id_kind: str | None = None
    for context in contexts:
        aligned, id_kind = _aligned_scoring_table(
            context.fold.projections,
            context.fold.realized_points,
            context.fold.fold_id,
        )
        if expected_id_kind is None:
            expected_id_kind = id_kind
        elif id_kind != expected_id_kind:
            raise UncertaintyValidationError(
                "player_id type must remain consistent across development folds; "
                f"expected {expected_id_kind}, got {id_kind} in {context.fold.fold_id!r}."
            )
        block = aligned.loc[:, ["player_id", "position", "expected_points", "total_points"]].copy(
            deep=True
        )
        block.insert(0, "fold_id", context.fold.fold_id)
        block.insert(1, "season", context.season)
        block.insert(2, "gameweek", context.gameweek)
        block["residual"] = block["total_points"] - block["expected_points"]
        if not all(math.isfinite(float(value)) for value in block["residual"].tolist()):
            raise UncertaintyValidationError(
                f"Fold {context.fold.fold_id!r} derived residuals must be finite."
            )
        records.append(block)
    return pd.concat(records, ignore_index=True)


def _conformal_radius(values: list[float], confidence_level: float) -> tuple[float, int]:
    """Return the finite-sample split-conformal absolute-residual quantile.

    The one-based rank is ``ceil((n + 1) * confidence_level)``, capped at ``n``.
    Using the observed order statistic rather than interpolation preserves the
    finite-sample conformal convention. Its coverage interpretation still requires
    exchangeability between calibration and later residuals.
    """

    ordered = sorted(abs(value) for value in values)
    rank = min(len(ordered), math.ceil((len(ordered) + 1) * confidence_level))
    return ordered[rank - 1], rank


def _group_calibration(
    position: Position,
    group_values: list[float],
    pooled_values: list[float],
    config: UncertaintyConfig,
) -> GroupCalibration:
    if len(group_values) >= config.min_group_observations:
        effective = group_values
        source = "position"
    else:
        effective = pooled_values
        source = "pooled_fallback"
    radius, rank = _conformal_radius(effective, config.confidence_level)
    try:
        residual_mean = fmean(effective)
        residual_stddev = pstdev(effective)
    except (OverflowError, ValueError) as error:
        raise UncertaintyValidationError(
            f"Calibration diagnostics for position {position!r} cannot be represented."
        ) from error
    if not all(math.isfinite(value) for value in (residual_mean, residual_stddev, radius)):
        raise UncertaintyValidationError(
            f"Calibration diagnostics for position {position!r} must be finite."
        )
    return GroupCalibration(
        position=position,
        source=source,
        group_observations=len(group_values),
        calibration_observations=len(effective),
        residual_mean=residual_mean,
        residual_stddev=residual_stddev,
        interval_radius=radius,
        conformal_rank=rank,
    )


def _calibration_fingerprint(
    config: UncertaintyConfig,
    groups: Mapping[Position, GroupCalibration],
) -> str:
    payload = {
        "configuration_fingerprint": config.configuration_fingerprint,
        "groups": {position: asdict(groups[position]) for position in POSITIONS},
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _validate_calibration_integrity(
    calibration: ProjectionUncertaintyCalibration,
) -> None:
    """Reject malformed or tampered public calibration records with a domain error."""

    if not isinstance(calibration.config, UncertaintyConfig):
        raise UncertaintyValidationError(
            "calibration.config must be an UncertaintyConfig instance."
        )
    pooled = calibration.pooled_observations
    if isinstance(pooled, bool) or not isinstance(pooled, Integral):
        raise UncertaintyValidationError("calibration.pooled_observations must be an integer.")
    pooled = int(pooled)
    if pooled < calibration.config.min_pooled_observations:
        raise UncertaintyValidationError(
            "calibration.pooled_observations is below the configured minimum."
        )

    expected_positions = set(POSITIONS)
    observed_positions = set(calibration.groups)
    if observed_positions != expected_positions:
        missing = sorted(expected_positions - observed_positions)
        extra = sorted(observed_positions - expected_positions, key=str)
        raise UncertaintyValidationError(
            "calibration.groups must contain every canonical position exactly once; "
            f"missing={missing!r}, extra={extra!r}."
        )

    group_total = 0
    for position in POSITIONS:
        group = calibration.groups[position]
        if not isinstance(group, GroupCalibration):
            raise UncertaintyValidationError(
                f"calibration group {position!r} must be a GroupCalibration."
            )
        if group.position != position:
            raise UncertaintyValidationError(
                f"calibration group key {position!r} does not match position {group.position!r}."
            )

        counts = {
            "group_observations": group.group_observations,
            "calibration_observations": group.calibration_observations,
            "conformal_rank": group.conformal_rank,
        }
        if any(
            isinstance(value, bool) or not isinstance(value, Integral) for value in counts.values()
        ):
            raise UncertaintyValidationError(
                f"calibration group {position!r} observation counts and rank must be integers."
            )
        group_observations = int(group.group_observations)
        calibration_observations = int(group.calibration_observations)
        conformal_rank = int(group.conformal_rank)
        if group_observations < 0 or calibration_observations < 2:
            raise UncertaintyValidationError(
                f"calibration group {position!r} has invalid observation counts."
            )

        expected_source = (
            "position"
            if group_observations >= calibration.config.min_group_observations
            else "pooled_fallback"
        )
        if group.source != expected_source:
            raise UncertaintyValidationError(
                f"calibration group {position!r} source must be {expected_source!r}."
            )
        expected_observations = group_observations if expected_source == "position" else pooled
        if calibration_observations != expected_observations:
            raise UncertaintyValidationError(
                f"calibration group {position!r} has inconsistent effective observations."
            )

        numeric_diagnostics = {
            "residual_mean": group.residual_mean,
            "residual_stddev": group.residual_stddev,
            "interval_radius": group.interval_radius,
        }
        converted_diagnostics: dict[str, float] = {}
        invalid_diagnostic = False
        for name, value in numeric_diagnostics.items():
            if isinstance(value, bool) or not isinstance(value, (Real, Decimal)):
                invalid_diagnostic = True
                break
            try:
                converted = float(value)
            except (OverflowError, TypeError, ValueError):
                invalid_diagnostic = True
                break
            if not math.isfinite(converted):
                invalid_diagnostic = True
                break
            converted_diagnostics[name] = converted
        if invalid_diagnostic:
            raise UncertaintyValidationError(
                f"calibration group {position!r} diagnostics must be finite numbers."
            )
        if (
            converted_diagnostics["residual_stddev"] < 0.0
            or converted_diagnostics["interval_radius"] < 0.0
        ):
            raise UncertaintyValidationError(
                f"calibration group {position!r} spread and radius must be non-negative."
            )
        expected_rank = min(
            calibration_observations,
            math.ceil((calibration_observations + 1) * calibration.config.confidence_level),
        )
        if conformal_rank != expected_rank:
            raise UncertaintyValidationError(
                f"calibration group {position!r} conformal rank is inconsistent with its config."
            )
        group_total += group_observations

    if group_total != pooled:
        raise UncertaintyValidationError(
            "calibration pooled observations must equal the sum of position observations."
        )
    expected_fingerprint = _calibration_fingerprint(calibration.config, calibration.groups)
    if calibration.calibration_fingerprint != expected_fingerprint:
        raise UncertaintyValidationError(
            "calibration fingerprint does not match its configuration and group state."
        )


def fit_projection_uncertainty(
    folds: Iterable[EvaluationFold],
    config: UncertaintyConfig | None = None,
) -> ProjectionUncertaintyCalibration:
    """Fit position-conditional conformal residuals on development folds only."""

    settings = UncertaintyConfig() if config is None else config
    if not isinstance(settings, UncertaintyConfig):
        raise UncertaintyValidationError("config must be an UncertaintyConfig instance.")
    contexts = _fold_contexts(folds, settings, role="development")
    residuals = _development_residuals(contexts)
    pooled = [float(value) for value in residuals["residual"].tolist()]
    if len(pooled) < settings.min_pooled_observations:
        raise UncertaintyValidationError(
            "Development residuals do not meet min_pooled_observations; "
            f"got {len(pooled)}, need {settings.min_pooled_observations}."
        )

    groups: dict[Position, GroupCalibration] = {}
    for position in POSITIONS:
        values = [
            float(value)
            for value in residuals.loc[residuals["position"].eq(position), "residual"].tolist()
        ]
        groups[position] = _group_calibration(position, values, pooled, settings)
    fingerprint = _calibration_fingerprint(settings, groups)
    calibration = ProjectionUncertaintyCalibration(
        config=settings,
        pooled_observations=len(pooled),
        groups=groups,
        calibration_fingerprint=fingerprint,
        diagnostics={
            "contract_version": settings.contract_version,
            "configuration_fingerprint": settings.configuration_fingerprint,
            "development_fold_count": len(contexts),
            "residual_definition": "total_points-minus-expected_points",
            "interval_method": "symmetric-split-conformal-absolute-residual",
            "quantile_rank": "ceil((n+1)*confidence_level)-capped-at-n",
            "grouping": "position-with-pooled-fallback",
            "opening_gameweeks_excluded": True,
        },
    )
    _validate_calibration_integrity(calibration)
    return calibration


def apply_projection_uncertainty(
    projections: pd.DataFrame,
    calibration: ProjectionUncertaintyCalibration,
) -> CalibratedProjectionResult:
    """Attach frozen uncertainty columns without changing point projections."""

    if not isinstance(calibration, ProjectionUncertaintyCalibration):
        raise UncertaintyValidationError(
            "calibration must be a ProjectionUncertaintyCalibration instance."
        )
    _validate_calibration_integrity(calibration)
    validated, _ = _validate_projection_table(projections, "application")
    stddevs: list[float] = []
    lowers: list[float] = []
    uppers: list[float] = []
    groups: list[str] = []
    sources: list[str] = []
    observations: list[int] = []
    for position_value, expected_value in zip(
        validated["position"].tolist(),
        validated["expected_points"].tolist(),
        strict=True,
    ):
        position = cast(Position, str(position_value))
        group = calibration.groups[position]
        expected = float(expected_value)
        lower = expected - group.interval_radius
        upper = expected + group.interval_radius
        if not math.isfinite(lower) or not math.isfinite(upper):
            raise UncertaintyValidationError(
                "Applying calibration produced non-finite prediction interval bounds."
            )
        stddevs.append(group.residual_stddev)
        lowers.append(lower)
        uppers.append(upper)
        groups.append(position)
        sources.append(group.source)
        observations.append(group.calibration_observations)

    result = validated.copy(deep=True)
    result[UNCERTAINTY_STDDEV_COLUMN] = stddevs
    result[INTERVAL_LOWER_COLUMN] = lowers
    result[INTERVAL_UPPER_COLUMN] = uppers
    result[UNCERTAINTY_GROUP_COLUMN] = groups
    result[UNCERTAINTY_SOURCE_COLUMN] = sources
    result[UNCERTAINTY_OBSERVATIONS_COLUMN] = observations
    result = result.astype(
        {
            UNCERTAINTY_GROUP_COLUMN: "string",
            UNCERTAINTY_SOURCE_COLUMN: "string",
            UNCERTAINTY_OBSERVATIONS_COLUMN: "int64",
        }
    )
    return CalibratedProjectionResult(
        table=result,
        calibration_fingerprint=calibration.calibration_fingerprint,
        diagnostics={
            "contract_version": calibration.config.contract_version,
            "confidence_level": calibration.config.confidence_level,
            "point_projection_changed": False,
            "interval_lower_bound_clamped": False,
        },
    )


def _metrics(scored: pd.DataFrame) -> UncertaintyMetrics:
    observations = len(scored)
    if observations == 0:
        raise UncertaintyValidationError("Uncertainty metrics require at least one player row.")
    errors = [float(value) for value in scored["residual"].tolist()]
    widths = [
        float(upper) - float(lower)
        for lower, upper in zip(
            scored[INTERVAL_LOWER_COLUMN].tolist(),
            scored[INTERVAL_UPPER_COLUMN].tolist(),
            strict=True,
        )
    ]
    squared_errors = [value * value for value in errors]
    if not all(math.isfinite(value) for value in errors + widths + squared_errors):
        raise UncertaintyValidationError(
            "Derived uncertainty metrics cannot be represented as finite values."
        )
    covered = [bool(value) for value in scored["interval_covered"].tolist()]
    try:
        return UncertaintyMetrics(
            observations=observations,
            empirical_coverage=sum(covered) / observations,
            mean_interval_width=fmean(widths),
            mean_absolute_error=fmean(abs(value) for value in errors),
            root_mean_squared_error=fmean(squared_errors) ** 0.5,
            mean_error=fmean(errors),
        )
    except (OverflowError, ValueError) as error:
        raise UncertaintyValidationError(
            "Derived uncertainty metrics cannot be represented as finite values."
        ) from error


def _group_metrics(scored: pd.DataFrame) -> dict[Position, UncertaintyMetrics]:
    result: dict[Position, UncertaintyMetrics] = {}
    for position in POSITIONS:
        selected = scored.loc[scored["position"].eq(position)]
        if not selected.empty:
            result[position] = _metrics(selected)
    return result


def _score_calibrated_fold(
    context: _FoldContext,
    calibration: ProjectionUncertaintyCalibration,
) -> tuple[UncertaintyFoldResult, str]:
    calibrated = apply_projection_uncertainty(context.fold.projections, calibration)
    aligned, id_kind = _aligned_scoring_table(
        calibrated.table,
        context.fold.realized_points,
        context.fold.fold_id,
    )
    aligned.insert(0, "fold_id", context.fold.fold_id)
    aligned.insert(1, "season", context.season)
    aligned.insert(2, "gameweek", context.gameweek)
    aligned["residual"] = aligned["total_points"] - aligned["expected_points"]
    if not all(math.isfinite(float(value)) for value in aligned["residual"].tolist()):
        raise UncertaintyValidationError(
            f"Fold {context.fold.fold_id!r} derived residuals must be finite."
        )
    aligned["interval_covered"] = aligned["total_points"].ge(
        aligned[INTERVAL_LOWER_COLUMN]
    ) & aligned["total_points"].le(aligned[INTERVAL_UPPER_COLUMN])
    return (
        UncertaintyFoldResult(
            fold_id=context.fold.fold_id,
            scored_players=aligned,
            metrics=_metrics(aligned),
            group_metrics=_group_metrics(aligned),
            metadata=context.fold.metadata,
        ),
        id_kind,
    )


def evaluate_projection_uncertainty(
    folds: Iterable[EvaluationFold],
    calibration: ProjectionUncertaintyCalibration,
) -> UncertaintyEvaluationResult:
    """Apply a frozen development calibration to the configured holdout season."""

    if not isinstance(calibration, ProjectionUncertaintyCalibration):
        raise UncertaintyValidationError(
            "calibration must be a ProjectionUncertaintyCalibration instance."
        )
    _validate_calibration_integrity(calibration)
    contexts = _fold_contexts(folds, calibration.config, role="holdout")
    scored = tuple(_score_calibrated_fold(context, calibration) for context in contexts)
    id_kinds = {id_kind for _, id_kind in scored}
    if len(id_kinds) != 1:
        raise UncertaintyValidationError(
            "player_id type must remain consistent across holdout folds; "
            f"found {sorted(id_kinds)!r}."
        )
    fold_results = tuple(result for result, _ in scored)
    combined = pd.concat([fold.scored_players for fold in fold_results], ignore_index=True)
    return UncertaintyEvaluationResult(
        calibration=calibration,
        folds=fold_results,
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
