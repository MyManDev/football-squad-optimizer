"""Expanding-season, leakage-safe screening of conformal risk objectives."""

import math
from collections import Counter
from collections.abc import Iterable
from numbers import Integral
from statistics import fmean, pstdev

from squadopt.evaluation import (
    EvaluationFold,
    EvaluationValidationError,
    score_realized_squad_points,
)
from squadopt.risk.config import (
    PlayerRiskScreeningConfig,
    RiskOptimizationConfig,
    RiskScreeningConfig,
)
from squadopt.risk.errors import RiskConfigurationError, RiskValidationError
from squadopt.risk.models import (
    RiskAwareOptimizationResult,
    RiskCandidateResult,
    RiskPairedComparison,
    RiskScreeningFoldResult,
    RiskScreeningMetrics,
    RiskScreeningResult,
)
from squadopt.risk.optimizer import optimize_risk_aware_squad
from squadopt.uncertainty import (
    PLAYER_ADAPTIVE_UNCERTAINTY_CONTRACT_VERSION,
    UncertaintyConfig,
    UncertaintyValidationError,
    apply_player_adaptive_uncertainty,
    apply_projection_uncertainty,
    evaluate_player_adaptive_uncertainty,
    evaluate_projection_uncertainty,
    fit_player_adaptive_uncertainty,
    fit_projection_uncertainty,
)


def _prepared_folds(
    folds: Iterable[EvaluationFold],
    config: RiskScreeningConfig,
) -> tuple[EvaluationFold, ...]:
    if isinstance(folds, str | bytes):
        raise RiskValidationError("folds must be an iterable of EvaluationFold values.")
    try:
        prepared = tuple(folds)
    except TypeError as error:
        raise RiskValidationError("folds must be an iterable of EvaluationFold values.") from error
    if not prepared:
        raise RiskValidationError("At least one prepared fold is required.")
    if any(not isinstance(fold, EvaluationFold) for fold in prepared):
        raise RiskValidationError("Every folds entry must be an EvaluationFold.")

    fold_ids = [fold.fold_id for fold in prepared]
    duplicates = sorted(fold_id for fold_id, count in Counter(fold_ids).items() if count > 1)
    if duplicates:
        raise RiskValidationError(f"fold_id values must be unique; duplicates: {duplicates!r}.")

    ranks = {season: rank for rank, season in enumerate(config.season_order)}
    contexts: list[tuple[int, int, str, EvaluationFold]] = []
    observed_seasons: set[str] = set()
    observed_decisions: set[tuple[str, int]] = set()
    expected_id_kind: str | None = None
    for fold in prepared:
        season = fold.metadata.get("season")
        gameweek = fold.metadata.get("gameweek")
        if not isinstance(season, str) or season not in ranks:
            raise RiskValidationError(
                f"Fold {fold.fold_id!r} season must be in season_order {config.season_order!r}."
            )
        if isinstance(gameweek, bool) or not isinstance(gameweek, Integral):
            raise RiskValidationError(f"Fold {fold.fold_id!r} gameweek must be an integer.")
        gameweek = int(gameweek)
        if gameweek <= config.min_prior_gameweeks_in_season:
            raise RiskValidationError(
                f"Fold {fold.fold_id!r} does not meet min_prior_gameweeks_in_season."
            )
        decision = (season, gameweek)
        if decision in observed_decisions:
            raise RiskValidationError(
                f"Only one fold is allowed for season {season!r}, gameweek {gameweek}."
            )
        observed_decisions.add(decision)
        observed_seasons.add(season)

        player_ids = fold.projections.get("player_id")
        if player_ids is None or player_ids.empty:
            raise RiskValidationError(
                f"Fold {fold.fold_id!r} projections must contain player_id rows."
            )
        first_id = player_ids.iloc[0]
        id_kind = (
            "integer"
            if isinstance(first_id, Integral) and not isinstance(first_id, bool)
            else "string"
        )
        if expected_id_kind is None:
            expected_id_kind = id_kind
        elif id_kind != expected_id_kind:
            raise RiskValidationError(
                "Projection player_id type must remain consistent across screening folds."
            )
        contexts.append((ranks[season], gameweek, fold.fold_id, fold))

    missing_seasons = [season for season in config.season_order if season not in observed_seasons]
    if missing_seasons:
        raise RiskValidationError(
            f"Screening folds do not cover configured seasons: {missing_seasons!r}."
        )
    return tuple(item[3] for item in sorted(contexts, key=lambda item: item[:3]))


def _nearest_rank(values: list[float], probability: float) -> float:
    ordered = sorted(values)
    rank = max(1, math.ceil(probability * len(ordered)))
    return ordered[rank - 1]


def _mean_worst(values: list[float], probability: float) -> float:
    ordered = sorted(values)
    count = max(1, math.ceil(probability * len(ordered)))
    return fmean(ordered[:count])


def _metrics(
    folds: tuple[RiskScreeningFoldResult, ...],
    downside_quantile: float,
) -> RiskScreeningMetrics:
    feasible = [fold for fold in folds if fold.result.has_solution]
    scores = [
        fold.realized_squad_points for fold in folds if fold.realized_squad_points is not None
    ]
    expected_objectives = [
        fold.result.expected_points_objective_value
        for fold in feasible
        if fold.result.expected_points_objective_value is not None
    ]
    risk_objectives = [
        fold.result.risk_adjusted_objective_value
        for fold in feasible
        if fold.result.risk_adjusted_objective_value is not None
    ]
    penalties = [
        fold.result.risk_penalty_value
        for fold in feasible
        if fold.result.risk_penalty_value is not None
    ]
    attempted = len(folds)
    return RiskScreeningMetrics(
        attempted_folds=attempted,
        feasible_folds=len(feasible),
        scored_folds=len(scores),
        feasibility_rate=len(feasible) / attempted,
        mean_realized_squad_points=fmean(scores) if scores else None,
        realized_squad_points_stddev=pstdev(scores) if scores else None,
        downside_quantile_score=(_nearest_rank(scores, downside_quantile) if scores else None),
        mean_worst_fraction_score=(_mean_worst(scores, downside_quantile) if scores else None),
        minimum_realized_squad_points=min(scores) if scores else None,
        mean_expected_points_objective_value=(
            fmean(expected_objectives) if expected_objectives else None
        ),
        mean_risk_adjusted_objective_value=(fmean(risk_objectives) if risk_objectives else None),
        mean_risk_penalty_value=fmean(penalties) if penalties else None,
    )


def _comparison(
    candidate_id: str,
    folds: tuple[RiskScreeningFoldResult, ...],
    control_id: str,
    control_folds: tuple[RiskScreeningFoldResult, ...],
    downside_quantile: float,
) -> RiskPairedComparison:
    control_by_id = {fold.fold_id: fold for fold in control_folds}
    differences: list[float] = []
    comparable_decisions = 0
    squad_changes = 0
    starting_changes = 0
    captain_changes = 0
    for fold in folds:
        control = control_by_id.get(fold.fold_id)
        if (
            control is not None
            and fold.realized_squad_points is not None
            and control.realized_squad_points is not None
        ):
            differences.append(fold.realized_squad_points - control.realized_squad_points)
        if control is not None and fold.result.has_solution and control.result.has_solution:
            comparable_decisions += 1
            candidate_decision = fold.result.optimization_result
            control_decision = control.result.optimization_result
            squad_changes += int(
                set(candidate_decision.selected_squad["player_id"].tolist())
                != set(control_decision.selected_squad["player_id"].tolist())
            )
            starting_changes += int(
                set(candidate_decision.starting_xi["player_id"].tolist())
                != set(control_decision.starting_xi["player_id"].tolist())
            )
            if candidate_decision.captain is None or control_decision.captain is None:
                raise RiskValidationError("Comparable feasible decisions must contain captains.")
            captain_changes += int(
                candidate_decision.captain["player_id"] != control_decision.captain["player_id"]
            )
    return RiskPairedComparison(
        control_id=control_id,
        candidate_id=candidate_id,
        comparable_folds=len(differences),
        mean_difference=fmean(differences) if differences else None,
        difference_stddev=pstdev(differences) if differences else None,
        downside_quantile_difference=(
            _nearest_rank(differences, downside_quantile) if differences else None
        ),
        mean_worst_fraction_difference=(
            _mean_worst(differences, downside_quantile) if differences else None
        ),
        minimum_difference=min(differences) if differences else None,
        comparable_decision_folds=comparable_decisions,
        squad_changed_folds=squad_changes,
        starting_xi_changed_folds=starting_changes,
        captain_changed_folds=captain_changes,
    )


def run_risk_screening(
    folds: Iterable[EvaluationFold],
    config: RiskScreeningConfig,
) -> RiskScreeningResult:
    """Screen fixed risk levels using only completed seasons for each calibration."""

    if not isinstance(config, RiskScreeningConfig):
        raise RiskConfigurationError("config must be a RiskScreeningConfig instance.")
    prepared = _prepared_folds(folds, config)
    by_season = {
        season: tuple(fold for fold in prepared if fold.metadata["season"] == season)
        for season in config.season_order
    }
    results_by_candidate: dict[str, list[RiskScreeningFoldResult]] = {
        candidate.candidate_id: [] for candidate in config.candidates
    }

    for target_index in range(1, len(config.season_order)):
        target_season = config.season_order[target_index]
        calibration_seasons = config.season_order[:target_index]
        calibration_folds = tuple(
            fold for season in calibration_seasons for fold in by_season[season]
        )
        uncertainty_config = UncertaintyConfig(
            confidence_level=config.uncertainty_confidence_level,
            development_seasons=calibration_seasons,
            holdout_season=target_season,
            min_pooled_observations=config.min_pooled_observations,
            min_group_observations=config.min_group_observations,
        )
        try:
            calibration = fit_projection_uncertainty(
                calibration_folds,
                uncertainty_config,
            )
        except UncertaintyValidationError as error:
            raise RiskValidationError(str(error)) from error

        pending: list[
            tuple[EvaluationFold, RiskOptimizationConfig, RiskAwareOptimizationResult]
        ] = []
        for fold in by_season[target_season]:
            try:
                calibrated = apply_projection_uncertainty(fold.projections, calibration)
            except UncertaintyValidationError as error:
                raise RiskValidationError(str(error)) from error
            for candidate in config.candidates:
                result = optimize_risk_aware_squad(
                    calibrated,
                    config.optimization_config,
                    candidate,
                )
                pending.append((fold, candidate, result))

        try:
            evaluate_projection_uncertainty(by_season[target_season], calibration)
        except UncertaintyValidationError as error:
            raise RiskValidationError(str(error)) from error

        for fold, candidate, result in pending:
            gameweek_value = fold.metadata["gameweek"]
            if isinstance(gameweek_value, bool) or not isinstance(gameweek_value, Integral):
                raise RiskValidationError(
                    f"Fold {fold.fold_id!r} gameweek metadata changed after validation."
                )
            realized_score = None
            if result.has_solution:
                try:
                    realized_score = score_realized_squad_points(
                        result.optimization_result,
                        fold.realized_points,
                    )
                except EvaluationValidationError as error:
                    raise RiskValidationError(str(error)) from error
            results_by_candidate[candidate.candidate_id].append(
                RiskScreeningFoldResult(
                    fold_id=fold.fold_id,
                    season=target_season,
                    gameweek=int(gameweek_value),
                    calibration_seasons=calibration_seasons,
                    result=result,
                    realized_squad_points=realized_score,
                )
            )

    control_config = config.candidates[0]
    control_folds = tuple(results_by_candidate[control_config.candidate_id])
    candidate_results: list[RiskCandidateResult] = []
    for candidate in config.candidates:
        candidate_folds = tuple(results_by_candidate[candidate.candidate_id])
        candidate_results.append(
            RiskCandidateResult(
                risk_config=candidate,
                folds=candidate_folds,
                metrics=_metrics(candidate_folds, config.downside_quantile),
                comparison=_comparison(
                    candidate.candidate_id,
                    candidate_folds,
                    control_config.candidate_id,
                    control_folds,
                    config.downside_quantile,
                ),
            )
        )

    evaluation_fold_ids = tuple(fold.fold_id for fold in control_folds)
    return RiskScreeningResult(
        config=config,
        candidates=tuple(candidate_results),
        diagnostics={
            "contract_version": config.contract_version,
            "configuration_fingerprint": config.configuration_fingerprint,
            "calibration_policy": "expanding-completed-seasons",
            "seed_season": config.season_order[0],
            "evaluation_seasons": config.season_order[1:],
            "evaluation_fold_ids": evaluation_fold_ids,
            "control_candidate_id": control_config.candidate_id,
            "holdout_accessed": False,
            "promotion_performed": False,
            "downside_quantile_method": "nearest-rank",
            "mean_worst_fraction_method": "ceil(q*n)-lowest-observations",
        },
    )


def run_player_risk_screening(
    folds: Iterable[EvaluationFold],
    config: PlayerRiskScreeningConfig,
) -> RiskScreeningResult:
    """Screen risk levels using expanding seasons and player-adaptive intervals."""

    if not isinstance(config, PlayerRiskScreeningConfig):
        raise RiskConfigurationError("config must be a PlayerRiskScreeningConfig instance.")
    prepared = _prepared_folds(folds, config)
    by_season = {
        season: tuple(fold for fold in prepared if fold.metadata["season"] == season)
        for season in config.season_order
    }
    results_by_candidate: dict[str, list[RiskScreeningFoldResult]] = {
        candidate.candidate_id: [] for candidate in config.candidates
    }

    for target_index in range(1, len(config.season_order)):
        target_season = config.season_order[target_index]
        calibration_seasons = config.season_order[:target_index]
        calibration_folds = tuple(
            fold for season in calibration_seasons for fold in by_season[season]
        )
        uncertainty_config = config.uncertainty_config_for(
            calibration_seasons,
            target_season,
        )
        try:
            calibration = fit_player_adaptive_uncertainty(
                calibration_folds,
                uncertainty_config,
            )
        except UncertaintyValidationError as error:
            raise RiskValidationError(str(error)) from error

        pending: list[
            tuple[EvaluationFold, RiskOptimizationConfig, RiskAwareOptimizationResult]
        ] = []
        for fold in by_season[target_season]:
            try:
                calibrated = apply_player_adaptive_uncertainty(
                    fold.projections,
                    calibration,
                )
            except UncertaintyValidationError as error:
                raise RiskValidationError(str(error)) from error
            for candidate in config.candidates:
                result = optimize_risk_aware_squad(
                    calibrated,
                    config.optimization_config,
                    candidate,
                )
                pending.append((fold, candidate, result))

        try:
            evaluate_player_adaptive_uncertainty(
                by_season[target_season],
                calibration,
            )
        except UncertaintyValidationError as error:
            raise RiskValidationError(str(error)) from error

        for fold, candidate, result in pending:
            gameweek_value = fold.metadata["gameweek"]
            if isinstance(gameweek_value, bool) or not isinstance(gameweek_value, Integral):
                raise RiskValidationError(
                    f"Fold {fold.fold_id!r} gameweek metadata changed after validation."
                )
            realized_score = None
            if result.has_solution:
                try:
                    realized_score = score_realized_squad_points(
                        result.optimization_result,
                        fold.realized_points,
                    )
                except EvaluationValidationError as error:
                    raise RiskValidationError(str(error)) from error
            results_by_candidate[candidate.candidate_id].append(
                RiskScreeningFoldResult(
                    fold_id=fold.fold_id,
                    season=target_season,
                    gameweek=int(gameweek_value),
                    calibration_seasons=calibration_seasons,
                    result=result,
                    realized_squad_points=realized_score,
                )
            )

    control_config = config.candidates[0]
    control_folds = tuple(results_by_candidate[control_config.candidate_id])
    candidate_results: list[RiskCandidateResult] = []
    for candidate in config.candidates:
        candidate_folds = tuple(results_by_candidate[candidate.candidate_id])
        candidate_results.append(
            RiskCandidateResult(
                risk_config=candidate,
                folds=candidate_folds,
                metrics=_metrics(candidate_folds, config.downside_quantile),
                comparison=_comparison(
                    candidate.candidate_id,
                    candidate_folds,
                    control_config.candidate_id,
                    control_folds,
                    config.downside_quantile,
                ),
            )
        )

    return RiskScreeningResult(
        config=config,
        candidates=tuple(candidate_results),
        diagnostics={
            "contract_version": config.contract_version,
            "configuration_fingerprint": config.configuration_fingerprint,
            "uncertainty_contract_version": PLAYER_ADAPTIVE_UNCERTAINTY_CONTRACT_VERSION,
            "calibration_policy": "expanding-completed-seasons",
            "calibration_split": "chronological-disjoint-folds",
            "seed_season": config.season_order[0],
            "evaluation_seasons": config.season_order[1:],
            "evaluation_fold_ids": tuple(fold.fold_id for fold in control_folds),
            "control_candidate_id": control_config.candidate_id,
            "player_specific_uncertainty": True,
            "holdout_accessed": False,
            "promotion_performed": False,
            "downside_quantile_method": "nearest-rank",
            "mean_worst_fraction_method": "ceil(q*n)-lowest-observations",
        },
    )
