"""Execution of development screening and explicitly separated frozen holdout runs."""

import hashlib
import json
import logging
import math
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace

import pandas as pd

from squadopt.backtest import (
    realized_points_at,
    season_ranks,
    walk_forward_decision_points,
)
from squadopt.evaluation import (
    EvaluationConfig,
    EvaluationFold,
    EvaluationResult,
    FoldEvaluationResult,
    evaluate_prepared_folds,
)
from squadopt.experiments.config import (
    SCREENING_EXPERIMENT_CONTRACT_VERSION,
    ExperimentCandidate,
    ExperimentExecutionError,
    FrozenCandidateError,
    ScreeningExperimentConfig,
)
from squadopt.experiments.models import (
    CandidateAssessment,
    FrozenCandidate,
    HoldoutEvaluationResult,
    ScreeningExperimentResult,
)
from squadopt.experiments.statistics import compare_to_control, factorial_effects
from squadopt.features import build_feature_dataset
from squadopt.optimization import (
    OptimizationResult,
    objective_coefficient_fingerprint,
)
from squadopt.optimization.validation import validate_players
from squadopt.prediction import (
    FEATURE_GENERATION_CONTRACT_VERSION,
    FormWindowMapping,
    build_projection_table,
)

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class _EvaluatedCandidate:
    candidate: ExperimentCandidate
    evaluation: EvaluationResult
    coefficient_signature: str
    equivalent_to: str | None


def _panel_through_evaluation_seasons(
    panel: pd.DataFrame,
    seasons: tuple[str, ...],
) -> pd.DataFrame:
    """Exclude seasons later than this run before any feature computation."""

    ranks = season_ranks(panel)
    unknown = sorted(set(seasons) - set(ranks))
    if unknown:
        raise ExperimentExecutionError(
            f"Requested experiment seasons are absent from the panel: {unknown!r}."
        )
    last_rank = max(ranks[season] for season in seasons)
    keep = panel["season"].map(lambda season: ranks[str(season)] <= last_rank)
    return panel.loc[keep].copy(deep=True)


def _validate_temporal_roles(
    panel: pd.DataFrame,
    settings: ScreeningExperimentConfig,
) -> None:
    """Require every locked-holdout season to follow development chronologically."""

    ranks = season_ranks(panel)
    requested = set(settings.development_seasons) | set(settings.holdout_seasons)
    unknown = sorted(requested - set(ranks))
    if unknown:
        raise ExperimentExecutionError(
            f"Configured experiment seasons are absent from the panel: {unknown!r}."
        )
    last_development = max(ranks[season] for season in settings.development_seasons)
    first_holdout = min(ranks[season] for season in settings.holdout_seasons)
    if first_holdout <= last_development:
        raise ExperimentExecutionError(
            "Every locked-holdout season must follow every development season "
            "chronologically in the panel."
        )


def _build_cached_projection_folds(
    panel: pd.DataFrame,
    settings: ScreeningExperimentConfig,
    *,
    form_window: int,
    seasons: tuple[str, ...],
) -> tuple[EvaluationFold, ...]:
    """Build shifted features once, then materialize every requested target fold.

    Shifted rolling features for an earlier row are invariant to rows appended in
    the future. Computing the complete visible season once is therefore exactly
    equivalent to repeatedly truncating after each decision, while avoiding the
    quadratic work of rebuilding the same history for every gameweek.
    """

    visible_panel = _panel_through_evaluation_seasons(panel, seasons)
    mapping = FormWindowMapping(form_window=form_window)
    features = build_feature_dataset(
        visible_panel,
        config=mapping.feature_config,
        cross_season=settings.cross_season_config,
    )
    decisions = walk_forward_decision_points(
        visible_panel,
        seasons=seasons,
        min_prior_gameweeks_in_season=settings.min_prior_gameweeks_in_season,
    )
    if not decisions:
        raise ExperimentExecutionError(
            "No decision points remain for the requested experiment seasons."
        )
    return tuple(
        EvaluationFold(
            fold_id=decision.fold_id,
            projections=build_projection_table(
                features,
                season=decision.season,
                gameweek=decision.gameweek,
                config=mapping.projection_config,
            ),
            realized_points=realized_points_at(visible_panel, decision),
            metadata={
                "season": decision.season,
                "gameweek": decision.gameweek,
                "feature_preparation": "full_visible_season_shifted_v1",
            },
        )
        for decision in decisions
    )


def _candidate_evaluation_config(
    settings: ScreeningExperimentConfig,
    candidate: ExperimentCandidate,
    *,
    role: str,
    seasons: tuple[str, ...],
) -> EvaluationConfig:
    optimization = replace(
        settings.optimization_config,
        bench_weight=candidate.bench_weight,
    )
    metadata = {
        **dict(settings.run_metadata),
        "experiment_contract_version": SCREENING_EXPERIMENT_CONTRACT_VERSION,
        "feature_generation_contract_version": FEATURE_GENERATION_CONTRACT_VERSION,
        "experiment_role": role,
        "evaluation_seasons": seasons,
        "candidate_id": candidate.candidate_id,
        "form_window": candidate.form_window,
        "bench_weight": candidate.bench_weight,
        "min_prior_gameweeks_in_season": settings.min_prior_gameweeks_in_season,
        "cross_season_decay": settings.cross_season_config.decay,
        "cross_season_min_minutes": settings.cross_season_config.min_minutes,
    }
    return EvaluationConfig(optimization_config=optimization, run_metadata=metadata)


def _coefficient_signature(
    folds: tuple[EvaluationFold, ...],
    config: EvaluationConfig,
) -> str:
    fold_fingerprints: list[tuple[str, str]] = []
    for fold in folds:
        validated = validate_players(fold.projections, config.optimization_config)
        fingerprint = objective_coefficient_fingerprint(validated, config.optimization_config)
        fold_fingerprints.append((fold.fold_id, fingerprint))
    encoded = json.dumps(fold_fingerprints, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _clone_optimization_result(
    source: OptimizationResult,
    *,
    candidate: ExperimentCandidate,
    equivalent_to: str,
) -> OptimizationResult:
    diagnostics = {
        **dict(source.diagnostics),
        "bench_weight": candidate.bench_weight,
        "solve_reused": True,
        "coefficient_equivalent_to": equivalent_to,
    }
    captain = None if source.captain is None else source.captain.copy(deep=True)
    return OptimizationResult(
        solver_status=source.solver_status,
        selected_squad=source.selected_squad.copy(deep=True),
        starting_xi=source.starting_xi.copy(deep=True),
        bench=source.bench.copy(deep=True),
        captain=captain,
        total_cost_tenths=source.total_cost_tenths,
        projected_score=source.projected_score,
        objective_value=source.objective_value,
        diagnostics=diagnostics,
    )


def _clone_equivalent_evaluation(
    source: EvaluationResult,
    config: EvaluationConfig,
    *,
    candidate: ExperimentCandidate,
    equivalent_to: str,
) -> EvaluationResult:
    folds = tuple(
        FoldEvaluationResult(
            fold_id=fold.fold_id,
            optimization_result=_clone_optimization_result(
                fold.optimization_result,
                candidate=candidate,
                equivalent_to=equivalent_to,
            ),
            realized_squad_points=fold.realized_squad_points,
            squad_turnover=fold.squad_turnover,
            metadata=fold.metadata,
            diagnostics={
                **dict(fold.diagnostics),
                "solve_reused": True,
                "coefficient_equivalent_to": equivalent_to,
            },
        )
        for fold in source.folds
    )
    return EvaluationResult(
        config=config,
        folds=folds,
        summary=source.summary,
        diagnostics={
            **dict(source.diagnostics),
            "solve_reused": True,
            "coefficient_equivalent_to": equivalent_to,
        },
    )


def _evaluate_design(
    panel: pd.DataFrame,
    settings: ScreeningExperimentConfig,
    candidates: tuple[ExperimentCandidate, ...],
    *,
    seasons: tuple[str, ...],
    role: str,
) -> tuple[tuple[_EvaluatedCandidate, ...], dict[str, int]]:
    projection_cache: dict[int, tuple[EvaluationFold, ...]] = {}
    evaluated: list[_EvaluatedCandidate] = []
    optimized_cells = 0
    optimized_folds = 0
    reused_cells = 0

    candidates_by_window: dict[int, list[ExperimentCandidate]] = {}
    for candidate in candidates:
        candidates_by_window.setdefault(candidate.form_window, []).append(candidate)

    for form_window, window_candidates in candidates_by_window.items():
        LOGGER.info("Preparing projection folds for form_window=%s", form_window)
        folds = _build_cached_projection_folds(
            panel,
            settings,
            form_window=form_window,
            seasons=seasons,
        )
        projection_cache[form_window] = folds
        LOGGER.info("Prepared %s folds for form_window=%s", len(folds), form_window)

        prepared: list[tuple[ExperimentCandidate, EvaluationConfig, str]] = []
        first_by_signature: dict[str, tuple[ExperimentCandidate, EvaluationConfig]] = {}
        for candidate in window_candidates:
            evaluation_config = _candidate_evaluation_config(
                settings,
                candidate,
                role=role,
                seasons=seasons,
            )
            signature = _coefficient_signature(folds, evaluation_config)
            prepared.append((candidate, evaluation_config, signature))
            first_by_signature.setdefault(signature, (candidate, evaluation_config))

        workers = min(settings.parallel_candidate_jobs, len(first_by_signature))
        LOGGER.info(
            "Evaluating %s unique coefficient cells with %s parallel candidate job(s)",
            len(first_by_signature),
            workers,
        )
        source_by_signature: dict[str, _EvaluatedCandidate] = {}
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {
                signature: executor.submit(evaluate_prepared_folds, folds, evaluation_config)
                for signature, (_, evaluation_config) in first_by_signature.items()
            }
            for signature, (candidate, _) in first_by_signature.items():
                evaluation = futures[signature].result()
                source_by_signature[signature] = _EvaluatedCandidate(
                    candidate,
                    evaluation,
                    signature,
                    None,
                )
                LOGGER.info("Completed candidate %s", candidate.candidate_id)
                optimized_cells += 1
                optimized_folds += len(folds)

        for candidate, evaluation_config, signature in prepared:
            source = source_by_signature[signature]
            if candidate.candidate_id == source.candidate.candidate_id:
                item = source
            else:
                evaluation = _clone_equivalent_evaluation(
                    source.evaluation,
                    evaluation_config,
                    candidate=candidate,
                    equivalent_to=source.candidate.candidate_id,
                )
                item = _EvaluatedCandidate(
                    candidate,
                    evaluation,
                    signature,
                    source.candidate.candidate_id,
                )
                reused_cells += 1
                LOGGER.info(
                    "Reused coefficient-equivalent result %s for %s",
                    source.candidate.candidate_id,
                    candidate.candidate_id,
                )
            evaluated.append(item)

    fold_sets = {tuple(fold.fold_id for fold in item.evaluation.folds) for item in evaluated}
    if len(fold_sets) != 1:
        raise ExperimentExecutionError(
            "All factorial candidates must be evaluated on identical chronological folds."
        )
    return tuple(evaluated), {
        "projection_cache_entries": len(projection_cache),
        "optimized_candidate_cells": optimized_cells,
        "optimized_fold_solves": optimized_folds,
        "coefficient_equivalent_cells_reused": reused_cells,
    }


def _build_assessments(
    evaluated: tuple[_EvaluatedCandidate, ...],
    settings: ScreeningExperimentConfig,
) -> tuple[CandidateAssessment, ...]:
    by_id = {item.candidate.candidate_id: item for item in evaluated}
    control = by_id.get(settings.control.candidate_id)
    if control is None:
        raise ExperimentExecutionError("The named control is absent from the evaluated design.")

    return tuple(
        CandidateAssessment(
            candidate=item.candidate,
            evaluation=item.evaluation,
            coefficient_signature=item.coefficient_signature,
            equivalent_to=item.equivalent_to,
            comparison=compare_to_control(
                item.candidate,
                item.evaluation,
                control.candidate,
                control.evaluation,
                settings.promotion_policy,
            ),
        )
        for item in evaluated
    )


def _select_candidate(
    assessments: tuple[CandidateAssessment, ...],
    control: ExperimentCandidate,
) -> tuple[ExperimentCandidate, str]:
    eligible = [
        item
        for item in assessments
        if item.candidate.candidate_id != control.candidate_id and item.comparison.eligible
    ]
    if not eligible:
        return control, "No challenger passed every development promotion gate; control retained."

    def selection_key(item: CandidateAssessment) -> tuple[float, float, float, str]:
        difference = item.comparison.mean_difference
        turnover = item.evaluation.summary.mean_squad_turnover
        runtime = item.evaluation.summary.median_solver_runtime_seconds
        return (
            -difference if difference is not None else math.inf,
            turnover if turnover is not None else math.inf,
            runtime if runtime is not None else math.inf,
            item.candidate.candidate_id,
        )

    selected = min(eligible, key=selection_key)
    return (
        selected.candidate,
        "Highest eligible paired mean improvement selected; exact ties use lower "
        "turnover, then lower median solver runtime, then candidate_id.",
    )


def _screening_fingerprint(
    settings: ScreeningExperimentConfig,
    assessments: tuple[CandidateAssessment, ...],
    selected: ExperimentCandidate,
) -> str:
    payload = {
        "contract_version": SCREENING_EXPERIMENT_CONTRACT_VERSION,
        "configuration_fingerprint": settings.configuration_fingerprint,
        "selected_candidate": selected.candidate_id,
        "candidates": [
            {
                "candidate_id": item.candidate.candidate_id,
                "coefficient_signature": item.coefficient_signature,
                "equivalent_to": item.equivalent_to,
                "folds": [
                    {
                        "fold_id": fold.fold_id,
                        "solver_status": fold.optimization_result.solver_status.value,
                        "realized_squad_points": fold.realized_squad_points,
                    }
                    for fold in item.evaluation.folds
                ],
                "paired_mean_difference": item.comparison.mean_difference,
                "confidence_interval_lower": item.comparison.confidence_interval_lower,
                "confidence_interval_upper": item.comparison.confidence_interval_upper,
                "eligible": item.comparison.eligible,
            }
            for item in assessments
        ],
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def run_screening_experiment(
    panel: pd.DataFrame,
    config: ScreeningExperimentConfig | None = None,
) -> ScreeningExperimentResult:
    """Run the 4x3 screening design using development seasons only."""

    settings = ScreeningExperimentConfig() if config is None else config
    if not isinstance(settings, ScreeningExperimentConfig):
        raise ExperimentExecutionError("config must be a ScreeningExperimentConfig instance.")
    _validate_temporal_roles(panel, settings)
    evaluated, diagnostics = _evaluate_design(
        panel,
        settings,
        settings.candidates,
        seasons=settings.development_seasons,
        role="development_screening",
    )
    assessments = _build_assessments(evaluated, settings)
    main_effects, interactions = factorial_effects(assessments, settings.control)
    selected, reason = _select_candidate(assessments, settings.control)
    fingerprint = _screening_fingerprint(settings, assessments, selected)
    return ScreeningExperimentResult(
        config=settings,
        assessments=assessments,
        main_effects=main_effects,
        interactions=interactions,
        selected_candidate=selected,
        selection_reason=reason,
        screening_fingerprint=fingerprint,
        diagnostics={
            **diagnostics,
            "evaluated_role": "development_screening",
            "development_seasons": settings.development_seasons,
            "holdout_seasons_accessed": False,
            "candidate_count": len(settings.candidates),
        },
    )


def freeze_screening_candidate(result: ScreeningExperimentResult) -> FrozenCandidate:
    """Seal the development decision before any locked-holdout evaluation."""

    if not isinstance(result, ScreeningExperimentResult):
        raise FrozenCandidateError("result must be a ScreeningExperimentResult instance.")
    return FrozenCandidate(
        candidate=result.selected_candidate,
        control=result.config.control,
        screening_fingerprint=result.screening_fingerprint,
        configuration_fingerprint=result.config.configuration_fingerprint,
    )


def run_frozen_holdout(
    panel: pd.DataFrame,
    frozen_candidate: FrozenCandidate,
    config: ScreeningExperimentConfig | None = None,
) -> HoldoutEvaluationResult:
    """Evaluate exactly one frozen development choice against the control on holdout."""

    settings = ScreeningExperimentConfig() if config is None else config
    if not isinstance(settings, ScreeningExperimentConfig):
        raise FrozenCandidateError("config must be a ScreeningExperimentConfig instance.")
    if not isinstance(frozen_candidate, FrozenCandidate):
        raise FrozenCandidateError("frozen_candidate must be a FrozenCandidate instance.")
    if frozen_candidate.configuration_fingerprint != settings.configuration_fingerprint:
        raise FrozenCandidateError(
            "Frozen candidate configuration does not match the requested holdout design."
        )
    if frozen_candidate.control.candidate_id != settings.control.candidate_id:
        raise FrozenCandidateError("Frozen candidate control does not match the design control.")
    _validate_temporal_roles(panel, settings)

    candidate_sequence: tuple[ExperimentCandidate, ...] = (frozen_candidate.control,)
    if frozen_candidate.candidate.candidate_id != frozen_candidate.control.candidate_id:
        candidate_sequence = (frozen_candidate.control, frozen_candidate.candidate)
    evaluated, diagnostics = _evaluate_design(
        panel,
        settings,
        candidate_sequence,
        seasons=settings.holdout_seasons,
        role="locked_holdout",
    )
    assessments = _build_assessments(evaluated, settings)
    by_id = {item.candidate.candidate_id: item for item in assessments}
    control_assessment = by_id[frozen_candidate.control.candidate_id]
    candidate_assessment = by_id[frozen_candidate.candidate.candidate_id]
    promoted = (
        frozen_candidate.candidate.candidate_id != frozen_candidate.control.candidate_id
        and candidate_assessment.comparison.eligible
    )
    if frozen_candidate.candidate.candidate_id == frozen_candidate.control.candidate_id:
        reason = "Development screening retained the control; no challenger was promoted."
    elif promoted:
        reason = "Frozen challenger passed every locked-holdout promotion gate."
    else:
        reason = "Frozen challenger failed at least one locked-holdout promotion gate."

    return HoldoutEvaluationResult(
        frozen_candidate=frozen_candidate,
        candidate_assessment=candidate_assessment,
        control_assessment=control_assessment,
        promoted=promoted,
        decision_reason=reason,
        diagnostics={
            **diagnostics,
            "evaluated_role": "locked_holdout",
            "development_seasons_accessed": False,
            "holdout_seasons": settings.holdout_seasons,
        },
    )
