"""Deterministic paired inference and factorial effect summaries."""

import hashlib
import random
from collections import defaultdict
from statistics import fmean

from squadopt.evaluation import EvaluationResult
from squadopt.experiments.config import ExperimentCandidate, PromotionPolicy
from squadopt.experiments.models import (
    CandidateAssessment,
    InteractionEffect,
    MainEffect,
    PairedComparison,
)


def _percentile(values: list[float], probability: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] + fraction * (ordered[upper] - ordered[lower])


def _bootstrap_seed(base_seed: int, candidate_id: str) -> int:
    digest = hashlib.sha256(candidate_id.encode("utf-8")).hexdigest()
    return base_seed + int(digest[:8], 16)


def _season_aware_moving_block_interval(
    differences: list[tuple[str, float]],
    *,
    policy: PromotionPolicy,
    candidate_id: str,
) -> tuple[float, float]:
    grouped: dict[str, list[float]] = defaultdict(list)
    for season, value in differences:
        grouped[season].append(value)

    generator = random.Random(_bootstrap_seed(policy.deterministic_seed, candidate_id))
    means: list[float] = []
    for _ in range(policy.bootstrap_resamples):
        sample: list[float] = []
        for season in sorted(grouped):
            season_values = grouped[season]
            block_length = min(policy.moving_block_length, len(season_values))
            starts = len(season_values) - block_length + 1
            season_sample: list[float] = []
            while len(season_sample) < len(season_values):
                start = generator.randrange(starts)
                season_sample.extend(season_values[start : start + block_length])
            sample.extend(season_sample[: len(season_values)])
        means.append(fmean(sample))

    alpha = (1.0 - policy.confidence_level) / 2.0
    return _percentile(means, alpha), _percentile(means, 1.0 - alpha)


def compare_to_control(
    candidate: ExperimentCandidate,
    candidate_result: EvaluationResult,
    control: ExperimentCandidate,
    control_result: EvaluationResult,
    policy: PromotionPolicy,
) -> PairedComparison:
    """Compare exact matching folds using a season-aware moving-block bootstrap."""

    control_folds = {fold.fold_id: fold for fold in control_result.folds}
    differences: list[tuple[str, float]] = []
    for fold in candidate_result.folds:
        other = control_folds.get(fold.fold_id)
        if (
            other is None
            or fold.realized_squad_points is None
            or other.realized_squad_points is None
        ):
            continue
        season = fold.metadata.get("season")
        if not isinstance(season, str) or not season:
            continue
        differences.append(
            (season, float(fold.realized_squad_points - other.realized_squad_points))
        )

    season_values: dict[str, list[float]] = defaultdict(list)
    for season, value in differences:
        season_values[season].append(value)
    season_means = {season: fmean(values) for season, values in sorted(season_values.items())}

    mean_difference = fmean(value for _, value in differences) if differences else None
    lower: float | None = None
    upper: float | None = None
    if differences:
        lower, upper = _season_aware_moving_block_interval(
            differences,
            policy=policy,
            candidate_id=candidate.candidate_id,
        )

    full_candidate = candidate_result.summary.feasibility_rate == 1.0
    full_control = control_result.summary.feasibility_rate == 1.0
    all_folds_paired = (
        len(differences)
        == candidate_result.summary.attempted_folds
        == control_result.summary.attempted_folds
    )
    passes_feasibility = full_candidate and full_control and all_folds_paired
    passes_mean = mean_difference is not None and mean_difference >= policy.min_mean_improvement
    passes_interval = lower is not None and lower >= 0.0

    return PairedComparison(
        candidate_id=candidate.candidate_id,
        control_id=control.candidate_id,
        comparable_folds=len(differences),
        mean_difference=mean_difference,
        confidence_interval_lower=lower,
        confidence_interval_upper=upper,
        season_mean_differences=season_means,
        passes_feasibility=passes_feasibility,
        passes_mean_improvement=passes_mean,
        passes_confidence_interval=passes_interval,
        eligible=passes_feasibility and passes_mean and passes_interval,
    )


def factorial_effects(
    assessments: tuple[CandidateAssessment, ...],
    control: ExperimentCandidate,
) -> tuple[tuple[MainEffect, ...], tuple[InteractionEffect, ...]]:
    """Calculate balanced marginal means and two-factor interaction residuals."""

    responses = {
        item.candidate.candidate_id: item.evaluation.summary.mean_realized_squad_points
        for item in assessments
    }
    by_window: dict[int, list[float]] = defaultdict(list)
    by_weight: dict[float, list[float]] = defaultdict(list)
    observed: list[float] = []
    for item in assessments:
        response = responses[item.candidate.candidate_id]
        if response is None:
            continue
        by_window[item.candidate.form_window].append(response)
        by_weight[item.candidate.bench_weight].append(response)
        observed.append(response)

    window_levels = {item.candidate.form_window for item in assessments}
    weight_levels = {item.candidate.bench_weight for item in assessments}
    window_means = {
        level: fmean(values)
        for level, values in by_window.items()
        if len(values) == len(weight_levels)
    }
    weight_means = {
        level: fmean(values)
        for level, values in by_weight.items()
        if len(values) == len(window_levels)
    }
    control_window_mean = window_means.get(control.form_window)
    control_weight_mean = weight_means.get(control.bench_weight)

    main_effects: list[MainEffect] = []
    for window_level in sorted(window_levels):
        marginal = window_means.get(window_level)
        effect = (
            marginal - control_window_mean
            if marginal is not None and control_window_mean is not None
            else None
        )
        main_effects.append(MainEffect("form_window", str(window_level), marginal, effect))
    for weight_level in sorted(weight_levels):
        marginal = weight_means.get(weight_level)
        effect = (
            marginal - control_weight_mean
            if marginal is not None and control_weight_mean is not None
            else None
        )
        main_effects.append(MainEffect("bench_weight", str(weight_level), marginal, effect))

    grand_mean = fmean(observed) if len(observed) == len(assessments) else None
    interactions: list[InteractionEffect] = []
    for item in assessments:
        response = responses[item.candidate.candidate_id]
        window_mean = window_means.get(item.candidate.form_window)
        weight_mean = weight_means.get(item.candidate.bench_weight)
        residual = (
            response - window_mean - weight_mean + grand_mean
            if response is not None
            and window_mean is not None
            and weight_mean is not None
            and grand_mean is not None
            else None
        )
        interactions.append(
            InteractionEffect(
                candidate_id=item.candidate.candidate_id,
                form_window=item.candidate.form_window,
                bench_weight=item.candidate.bench_weight,
                mean_response=response,
                interaction_residual=residual,
            )
        )
    return tuple(main_effects), tuple(interactions)
