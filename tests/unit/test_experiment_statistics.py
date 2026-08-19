"""Tests for paired bootstrap gates and balanced factorial summaries."""

from collections.abc import Sequence
from dataclasses import replace

import pandas as pd

from squadopt import OptimizationResult, SolverStatus
from squadopt.evaluation import (
    EvaluationConfig,
    EvaluationResult,
    EvaluationSummary,
    FoldEvaluationResult,
)
from squadopt.experiments import (
    CandidateAssessment,
    ExperimentCandidate,
    PromotionPolicy,
)
from squadopt.experiments.models import PairedComparison
from squadopt.experiments.statistics import compare_to_control, factorial_effects


def _evaluation(
    scores: Sequence[float],
    seasons: Sequence[str],
    *,
    turnover: float = 1.0,
    runtime: float = 0.01,
    feasibility_rate: float = 1.0,
) -> EvaluationResult:
    empty = pd.DataFrame(columns=["player_id"])
    fold_results = []
    for index, (score, season) in enumerate(zip(scores, seasons, strict=True), start=1):
        optimization = OptimizationResult(
            solver_status=SolverStatus.OPTIMAL,
            selected_squad=empty.copy(deep=True),
            starting_xi=empty.copy(deep=True),
            bench=empty.copy(deep=True),
            captain=None,
            total_cost_tenths=0,
            projected_score=score,
            objective_value=score,
            diagnostics={"solve_time_seconds": runtime},
        )
        fold_results.append(
            FoldEvaluationResult(
                fold_id=f"{season}-gw{index:02d}",
                optimization_result=optimization,
                realized_squad_points=float(score),
                squad_turnover=None if index == 1 else int(turnover),
                metadata={"season": season, "gameweek": index},
                diagnostics={},
            )
        )
    count = len(fold_results)
    feasible = int(count * feasibility_rate)
    return EvaluationResult(
        config=EvaluationConfig(),
        folds=tuple(fold_results),
        summary=EvaluationSummary(
            attempted_folds=count,
            feasible_folds=feasible,
            scored_folds=count,
            feasibility_rate=feasibility_rate,
            mean_realized_squad_points=sum(scores) / count,
            realized_squad_points_stddev=0.0,
            mean_projected_objective_value=sum(scores) / count,
            runtime_observations=count,
            median_solver_runtime_seconds=runtime,
            p95_solver_runtime_seconds=runtime,
            turnover_observations=max(0, count - 1),
            mean_squad_turnover=turnover,
        ),
        diagnostics={},
    )


def _blank_comparison(candidate: ExperimentCandidate) -> PairedComparison:
    return PairedComparison(
        candidate_id=candidate.candidate_id,
        control_id="control",
        comparable_folds=0,
        mean_difference=None,
        confidence_interval_lower=None,
        confidence_interval_upper=None,
        season_mean_differences={},
        passes_feasibility=False,
        passes_mean_improvement=False,
        passes_confidence_interval=False,
        eligible=False,
    )


def test_paired_moving_block_bootstrap_is_deterministic_and_season_aware() -> None:
    seasons = ("s1", "s1", "s1", "s2", "s2", "s2")
    control = ExperimentCandidate(5, 0.1)
    challenger = ExperimentCandidate(3, 0.1)
    policy = PromotionPolicy(
        min_mean_improvement=0.5,
        confidence_level=0.9,
        bootstrap_resamples=500,
        moving_block_length=2,
        deterministic_seed=11,
    )
    baseline = _evaluation((10, 10, 10, 10, 10, 10), seasons)
    candidate = _evaluation((11, 12, 11, 12, 11, 12), seasons)

    first = compare_to_control(challenger, candidate, control, baseline, policy)
    second = compare_to_control(challenger, candidate, control, baseline, policy)

    assert first == second
    assert first.mean_difference == 1.5
    assert first.season_mean_differences == {"s1": 4 / 3, "s2": 5 / 3}
    assert first.confidence_interval_lower is not None
    assert first.confidence_interval_lower > 0.0
    assert first.eligible


def test_feasibility_is_a_hard_promotion_gate() -> None:
    seasons = ("s1", "s1")
    control = ExperimentCandidate(5, 0.1)
    challenger = ExperimentCandidate(3, 0.1)
    comparison = compare_to_control(
        challenger,
        _evaluation((20, 20), seasons, feasibility_rate=0.5),
        control,
        _evaluation((10, 10), seasons),
        PromotionPolicy(bootstrap_resamples=20),
    )

    assert comparison.passes_mean_improvement
    assert comparison.passes_confidence_interval
    assert not comparison.passes_feasibility
    assert not comparison.eligible


def test_factorial_main_effects_and_interactions_use_balanced_cell_means() -> None:
    cells = (
        (ExperimentCandidate(3, 0.0), 10.0),
        (ExperimentCandidate(3, 0.1), 14.0),
        (ExperimentCandidate(5, 0.0), 20.0),
        (ExperimentCandidate(5, 0.1), 28.0),
    )
    assessments = tuple(
        CandidateAssessment(
            candidate=candidate,
            evaluation=_evaluation((response,), ("s1",)),
            coefficient_signature=candidate.candidate_id,
            equivalent_to=None,
            comparison=_blank_comparison(candidate),
        )
        for candidate, response in cells
    )

    main, interaction = factorial_effects(assessments, ExperimentCandidate(5, 0.1))

    main_lookup = {(effect.factor, effect.level): effect for effect in main}
    assert main_lookup[("form_window", "3")].marginal_mean == 12.0
    assert main_lookup[("form_window", "3")].effect_from_control_level == -12.0
    assert main_lookup[("bench_weight", "0.0")].marginal_mean == 15.0
    assert main_lookup[("bench_weight", "0.0")].effect_from_control_level == -6.0
    residuals = {effect.candidate_id: effect.interaction_residual for effect in interaction}
    assert residuals[ExperimentCandidate(3, 0.0).candidate_id] == 1.0
    assert residuals[ExperimentCandidate(3, 0.1).candidate_id] == -1.0


def test_factorial_effects_do_not_report_unbalanced_partial_marginals() -> None:
    candidates = (
        ExperimentCandidate(3, 0.0),
        ExperimentCandidate(3, 0.1),
        ExperimentCandidate(5, 0.0),
        ExperimentCandidate(5, 0.1),
    )
    assessments = []
    for candidate in candidates:
        evaluation = _evaluation((10.0,), ("s1",))
        if candidate == ExperimentCandidate(3, 0.1):
            evaluation = replace(
                evaluation,
                summary=replace(evaluation.summary, mean_realized_squad_points=None),
            )
        assessments.append(
            CandidateAssessment(
                candidate=candidate,
                evaluation=evaluation,
                coefficient_signature=candidate.candidate_id,
                equivalent_to=None,
                comparison=_blank_comparison(candidate),
            )
        )

    main, interactions = factorial_effects(
        tuple(assessments),
        ExperimentCandidate(5, 0.1),
    )

    main_lookup = {(effect.factor, effect.level): effect for effect in main}
    assert main_lookup[("form_window", "3")].marginal_mean is None
    assert main_lookup[("form_window", "5")].marginal_mean == 10.0
    assert main_lookup[("bench_weight", "0.0")].marginal_mean == 10.0
    assert main_lookup[("bench_weight", "0.1")].marginal_mean is None
    assert all(effect.interaction_residual is None for effect in interactions)
