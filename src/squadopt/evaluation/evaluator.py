"""Evaluation runner for caller-prepared, ordered gameweek folds."""

import math
from collections import Counter
from collections.abc import Iterable
from numbers import Integral, Real
from statistics import fmean, median, pstdev

from squadopt.evaluation.models import (
    EvaluationConfig,
    EvaluationFold,
    EvaluationResult,
    EvaluationSummary,
    EvaluationValidationError,
    FoldEvaluationResult,
)
from squadopt.evaluation.scoring import _validate_realized_points, score_realized_squad_points
from squadopt.optimization import OptimizationResult, optimize_squad


def _solver_runtime(result: OptimizationResult) -> float:
    value = result.diagnostics.get("solve_time_seconds")
    if isinstance(value, bool) or not isinstance(value, Real):
        raise EvaluationValidationError(
            "Optimization diagnostics must contain numeric solve_time_seconds."
        )
    runtime = float(value)
    if not math.isfinite(runtime) or runtime < 0:
        raise EvaluationValidationError(
            "Optimization solve_time_seconds must be finite and non-negative."
        )
    return runtime


def _player_id_set(result: OptimizationResult) -> set[object]:
    return set(result.selected_squad["player_id"].tolist())


def _player_id_kind(values: list[object]) -> str:
    """Return the identifier representation after upstream validation."""

    return "integer" if isinstance(values[0], Integral) else "string"


def _nearest_rank_p95(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, math.ceil(0.95 * len(ordered)))
    return ordered[rank - 1]


def _summarize(folds: tuple[FoldEvaluationResult, ...]) -> EvaluationSummary:
    attempted = len(folds)
    feasible = [fold for fold in folds if fold.optimization_result.has_solution]
    scores = [
        fold.realized_squad_points for fold in folds if fold.realized_squad_points is not None
    ]
    objectives = [
        fold.optimization_result.objective_value
        for fold in feasible
        if fold.optimization_result.objective_value is not None
    ]
    runtimes = [_solver_runtime(fold.optimization_result) for fold in folds]
    turnovers = [fold.squad_turnover for fold in folds if fold.squad_turnover is not None]

    return EvaluationSummary(
        attempted_folds=attempted,
        feasible_folds=len(feasible),
        scored_folds=len(scores),
        feasibility_rate=len(feasible) / attempted,
        mean_realized_squad_points=fmean(scores) if scores else None,
        realized_squad_points_stddev=pstdev(scores) if scores else None,
        mean_projected_objective_value=fmean(objectives) if objectives else None,
        runtime_observations=len(runtimes),
        median_solver_runtime_seconds=median(runtimes) if runtimes else None,
        p95_solver_runtime_seconds=_nearest_rank_p95(runtimes),
        turnover_observations=len(turnovers),
        mean_squad_turnover=fmean(turnovers) if turnovers else None,
    )


def evaluate_prepared_folds(
    folds: Iterable[EvaluationFold],
    config: EvaluationConfig,
) -> EvaluationResult:
    """Optimize and score ordered folds prepared by a time-aware data component.

    This function never creates temporal splits, fits projections, or reads future
    data. Each input fold must already contain a one-gameweek projection table and
    the matching outcomes observed later.
    """

    if not isinstance(config, EvaluationConfig):
        raise EvaluationValidationError("config must be an EvaluationConfig instance.")
    if isinstance(folds, str | bytes):
        raise EvaluationValidationError("folds must be an iterable of EvaluationFold values.")
    try:
        prepared = tuple(folds)
    except TypeError as error:
        raise EvaluationValidationError(
            "folds must be an iterable of EvaluationFold values."
        ) from error
    if not prepared:
        raise EvaluationValidationError("At least one prepared evaluation fold is required.")
    invalid = [fold for fold in prepared if not isinstance(fold, EvaluationFold)]
    if invalid:
        raise EvaluationValidationError("Every folds entry must be an EvaluationFold.")

    fold_ids = [fold.fold_id for fold in prepared]
    duplicate_fold_ids = [fold_id for fold_id, count in Counter(fold_ids).items() if count > 1]
    if duplicate_fold_ids:
        raise EvaluationValidationError(
            f"fold_id values must be unique; duplicates: {duplicate_fold_ids!r}."
        )

    evaluated: list[FoldEvaluationResult] = []
    previous_result: OptimizationResult | None = None
    expected_player_id_kind: str | None = None
    for fold in prepared:
        optimization_result = optimize_squad(fold.projections, config.optimization_config)
        projection_id_kind = _player_id_kind(fold.projections["player_id"].tolist())
        if expected_player_id_kind is None:
            expected_player_id_kind = projection_id_kind
        elif projection_id_kind != expected_player_id_kind:
            raise EvaluationValidationError(
                "Projection player_id type must remain consistent across folds; "
                f"expected {expected_player_id_kind}, got {projection_id_kind} "
                f"in fold {fold.fold_id!r}."
            )

        validated_realized = _validate_realized_points(fold.realized_points)
        realized_id_kind = _player_id_kind(validated_realized["player_id"].tolist())
        if realized_id_kind != projection_id_kind:
            raise EvaluationValidationError(
                "Projection and realized player_id types must match within each fold; "
                f"got projection={projection_id_kind} and realized={realized_id_kind} "
                f"in fold {fold.fold_id!r}."
            )

        realized_score = None
        if optimization_result.has_solution:
            realized_score = score_realized_squad_points(
                optimization_result,
                fold.realized_points,
                policy=config.scoring_policy,
            )

        turnover = None
        if (
            previous_result is not None
            and previous_result.has_solution
            and optimization_result.has_solution
        ):
            turnover = len(_player_id_set(optimization_result) - _player_id_set(previous_result))

        evaluated.append(
            FoldEvaluationResult(
                fold_id=fold.fold_id,
                optimization_result=optimization_result,
                realized_squad_points=realized_score,
                squad_turnover=turnover,
                metadata=fold.metadata,
                diagnostics={
                    "scoring_policy": config.scoring_policy.value,
                    "realized_points_rows": len(fold.realized_points),
                },
            )
        )
        previous_result = optimization_result

    fold_results = tuple(evaluated)
    return EvaluationResult(
        config=config,
        folds=fold_results,
        summary=_summarize(fold_results),
        diagnostics={
            "fold_order": tuple(fold_ids),
            "scoring_policy": config.scoring_policy.value,
            "realized_dispersion": "population_standard_deviation",
            "runtime_p95": "nearest_rank",
            "turnover_definition": "entering_player_count",
        },
    )
