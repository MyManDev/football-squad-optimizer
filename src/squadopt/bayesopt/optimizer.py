"""Deterministic Gaussian-process Bayesian optimization over a finite policy grid."""

import hashlib
import json
import math
from collections.abc import Callable
from numbers import Real

import numpy as np
from sklearn.gaussian_process import GaussianProcessRegressor  # type: ignore[import-untyped]
from sklearn.gaussian_process.kernels import (  # type: ignore[import-untyped]
    ConstantKernel,
    Matern,
)

from squadopt.bayesopt.models import (
    BayesianCandidate,
    BayesianEvaluation,
    BayesianOptimizationConfig,
    BayesianOptimizationExecutionError,
    BayesianOptimizationResult,
    enumerate_candidates,
)

ObjectiveEvaluator = Callable[[BayesianCandidate, tuple[str, ...]], Real]


def _fold_ids(value: object, name: str, *, allow_empty: bool) -> tuple[str, ...]:
    if not isinstance(value, tuple) or (not value and not allow_empty):
        requirement = "a tuple" if allow_empty else "a non-empty tuple"
        raise BayesianOptimizationExecutionError(f"{name} must be {requirement}.")
    if any(not isinstance(fold_id, str) or not fold_id.strip() for fold_id in value):
        raise BayesianOptimizationExecutionError(
            f"{name} must contain non-empty string identifiers."
        )
    normalized = tuple(fold_id.strip() for fold_id in value)
    if len(set(normalized)) != len(normalized):
        raise BayesianOptimizationExecutionError(f"{name} must contain unique identifiers.")
    return normalized


def _candidate_matrix(
    candidates: tuple[BayesianCandidate, ...],
    config: BayesianOptimizationConfig,
) -> np.ndarray:
    matrix = np.empty((len(candidates), len(config.factors)), dtype=np.float64)
    for row_index, candidate in enumerate(candidates):
        for column_index, factor in enumerate(config.factors):
            value = float(candidate.values[factor.name])
            lower = float(factor.lower_bound)
            upper = float(factor.upper_bound)
            # A fixed factor spans no range: it contributes a constant coordinate, so it
            # neither divides by zero here nor separates any two candidates in the kernel.
            matrix[row_index, column_index] = (
                0.0 if factor.is_fixed else (value - lower) / (upper - lower)
            )
    return matrix


def _maximin_initial_indices(
    matrix: np.ndarray,
    candidates: tuple[BayesianCandidate, ...],
    count: int,
    seed: int,
) -> tuple[int, ...]:
    generator = np.random.default_rng(seed)
    selected = [int(generator.integers(0, len(candidates)))]
    while len(selected) < count:
        available = [index for index in range(len(candidates)) if index not in selected]
        minimum_distances: dict[int, float] = {}
        for index in available:
            minimum_distances[index] = min(
                float(np.linalg.norm(matrix[index] - matrix[chosen])) for chosen in selected
            )
        largest_distance = max(minimum_distances.values())
        tied = [
            index
            for index, distance in minimum_distances.items()
            if math.isclose(distance, largest_distance, rel_tol=1.0e-12, abs_tol=1.0e-15)
        ]
        selected.append(min(tied, key=lambda index: candidates[index].candidate_id))
    return tuple(selected)


def _fit_surrogate(
    x_values: np.ndarray,
    y_values: np.ndarray,
    config: BayesianOptimizationConfig,
) -> GaussianProcessRegressor:
    kernel = ConstantKernel(1.0, constant_value_bounds="fixed") * Matern(
        length_scale=config.kernel_length_scale,
        length_scale_bounds="fixed",
        nu=config.matern_nu,
    )
    surrogate = GaussianProcessRegressor(
        kernel=kernel,
        alpha=config.observation_noise,
        optimizer=None,
        normalize_y=True,
        random_state=config.deterministic_seed,
    )
    try:
        surrogate.fit(x_values, y_values)
    except Exception as error:
        raise BayesianOptimizationExecutionError(
            "Gaussian-process surrogate fitting failed."
        ) from error
    return surrogate


def estimate_observation_noise(per_fold_values: object) -> float:
    """The variance of a fold-mean objective, measured from its own folds.

    The chip search ran at ``observation_noise = 1e-6`` — near interpolation — while
    the objective's season spread was 46-98 points; the surrogate treated one noisy
    fold-mean as exact and could not tell small differences apart, which is the
    recorded reason no candidate separated. A fold-paired objective knows its own
    uncertainty: the squared standard error of the mean. Set ``observation_noise``
    from this, per search, instead of inheriting the interpolation default.
    """

    values = np.asarray(per_fold_values, dtype=np.float64)
    if values.ndim != 1 or values.size < 2 or not bool(np.isfinite(values).all()):
        raise BayesianOptimizationExecutionError(
            "estimate_observation_noise needs at least two finite fold values."
        )
    return float(values.var(ddof=1) / values.size)


def _grid_edge_factors(
    candidate: BayesianCandidate, config: BayesianOptimizationConfig
) -> tuple[str, ...]:
    """Factors on which the candidate sits at the boundary of its declared grid.

    The wildcard-hold search put 13 of 20 evaluations on a grid edge and a human had
    to notice; the diagnostics say it now. A fixed factor (one level) is never an
    edge — there is nowhere else to be.
    """

    edges: list[str] = []
    for factor in config.factors:
        levels = factor.levels
        if len(levels) < 2:
            continue
        value = candidate.values[factor.name]
        if value == levels[0] or value == levels[-1]:
            edges.append(factor.name)
    return tuple(edges)


def _expected_improvement(
    means: np.ndarray,
    standard_deviations: np.ndarray,
    best_observed: float,
    exploration_xi: float,
) -> np.ndarray:
    improvements = means - best_observed - exploration_xi
    values = np.zeros_like(means, dtype=np.float64)
    positive_sigma = standard_deviations > 1.0e-15
    if bool(positive_sigma.any()):
        z_values = improvements[positive_sigma] / standard_deviations[positive_sigma]
        cdf = np.asarray(
            [0.5 * (1.0 + math.erf(value / math.sqrt(2.0))) for value in z_values],
            dtype=np.float64,
        )
        pdf = np.exp(-0.5 * z_values**2) / math.sqrt(2.0 * math.pi)
        values[positive_sigma] = (
            improvements[positive_sigma] * cdf + standard_deviations[positive_sigma] * pdf
        )
    values[~positive_sigma] = np.maximum(improvements[~positive_sigma], 0.0)
    return np.maximum(values, 0.0)


def _evaluate_candidate(
    evaluator: ObjectiveEvaluator,
    candidate: BayesianCandidate,
    development_fold_ids: tuple[str, ...],
) -> float:
    try:
        value = evaluator(candidate, development_fold_ids)
    except Exception as error:
        raise BayesianOptimizationExecutionError(
            f"Objective evaluation failed for candidate {candidate.candidate_id!r}."
        ) from error
    if isinstance(value, bool) or not isinstance(value, Real):
        raise BayesianOptimizationExecutionError(
            f"Objective for candidate {candidate.candidate_id!r} must be a finite number."
        )
    normalized = float(value)
    if not math.isfinite(normalized):
        raise BayesianOptimizationExecutionError(
            f"Objective for candidate {candidate.candidate_id!r} must be finite."
        )
    return normalized


def _run_fingerprint(
    config: BayesianOptimizationConfig,
    development_fold_ids: tuple[str, ...],
    locked_holdout_fold_ids: tuple[str, ...],
    evaluations: tuple[BayesianEvaluation, ...],
    stopped_reason: str,
) -> str:
    payload = {
        "contract_version": config.contract_version,
        "configuration_fingerprint": config.configuration_fingerprint,
        "development_fold_ids": development_fold_ids,
        "locked_holdout_fold_ids_recorded_not_accessed": locked_holdout_fold_ids,
        "stopped_reason": stopped_reason,
        "evaluations": [
            {
                "iteration": item.iteration,
                "phase": item.phase,
                "candidate_id": item.candidate.candidate_id,
                "objective_value": float(item.objective_value).hex(),
                "predicted_mean": (
                    None if item.predicted_mean is None else float(item.predicted_mean).hex()
                ),
                "predicted_standard_deviation": (
                    None
                    if item.predicted_standard_deviation is None
                    else float(item.predicted_standard_deviation).hex()
                ),
                "expected_improvement": (
                    None
                    if item.expected_improvement is None
                    else float(item.expected_improvement).hex()
                ),
            }
            for item in evaluations
        ],
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def run_bayesian_optimization(
    evaluator: ObjectiveEvaluator,
    development_fold_ids: tuple[str, ...],
    config: BayesianOptimizationConfig | None = None,
    *,
    locked_holdout_fold_ids: tuple[str, ...] = (),
) -> BayesianOptimizationResult:
    """Recommend a policy using development folds only and a fixed evaluation budget."""

    if not callable(evaluator):
        raise BayesianOptimizationExecutionError("evaluator must be callable.")
    settings = BayesianOptimizationConfig() if config is None else config
    if not isinstance(settings, BayesianOptimizationConfig):
        raise BayesianOptimizationExecutionError(
            "config must be a BayesianOptimizationConfig instance."
        )
    development = _fold_ids(development_fold_ids, "development_fold_ids", allow_empty=False)
    holdout = _fold_ids(
        locked_holdout_fold_ids,
        "locked_holdout_fold_ids",
        allow_empty=True,
    )
    overlap = sorted(set(development) & set(holdout))
    if overlap:
        raise BayesianOptimizationExecutionError(
            f"Development and locked holdout folds must be disjoint; overlap={overlap!r}."
        )

    candidates = enumerate_candidates(settings)
    candidate_matrix = _candidate_matrix(candidates, settings)
    initial_indices = _maximin_initial_indices(
        candidate_matrix,
        candidates,
        settings.initial_design_size,
        settings.deterministic_seed,
    )
    evaluations: list[BayesianEvaluation] = []
    cache: dict[str, float] = {}
    evaluated_indices: list[int] = []
    for candidate_index in initial_indices:
        candidate = candidates[candidate_index]
        score = _evaluate_candidate(evaluator, candidate, development)
        cache[candidate.candidate_id] = score
        evaluated_indices.append(candidate_index)
        evaluations.append(
            BayesianEvaluation(
                iteration=len(evaluations),
                phase="initial_design",
                candidate=candidate,
                objective_value=score,
                predicted_mean=None,
                predicted_standard_deviation=None,
                expected_improvement=None,
            )
        )

    stopped_reason = "evaluation_budget_exhausted"
    surrogate_fit_count = 0
    last_kernel = None
    last_selected_ei: float | None = None
    while len(evaluations) < settings.evaluation_budget:
        remaining_indices = [
            index
            for index, candidate in enumerate(candidates)
            if candidate.candidate_id not in cache
        ]
        if not remaining_indices:
            stopped_reason = "search_space_exhausted"
            break
        x_train = candidate_matrix[evaluated_indices]
        y_train = np.asarray(
            [cache[candidates[index].candidate_id] for index in evaluated_indices],
            dtype=np.float64,
        )
        surrogate = _fit_surrogate(x_train, y_train, settings)
        surrogate_fit_count += 1
        last_kernel = str(surrogate.kernel_)

        # Constant-liar batch: this fit proposes up to ``batch_size`` candidates. Each
        # pick after the first is made as if the earlier picks had come back at the
        # incumbent best (the "constant liar"), which pushes the batch apart instead
        # of proposing one neighbourhood twice; the lies never enter the cache. With
        # ``batch_size=1`` this is the historical sequential loop, bit for bit — the
        # first pick's surrogate, tie-break and stop rule are unchanged.
        batch_limit = min(
            settings.batch_size,
            settings.evaluation_budget - len(evaluations),
            len(remaining_indices),
        )
        liar_surrogate = surrogate
        liar_x = x_train
        liar_y = y_train
        liar_remaining = list(remaining_indices)
        picks: list[tuple[int, float, float, float]] = []
        minimum_reached = False
        for pick_number in range(batch_limit):
            if pick_number > 0:
                liar_surrogate = _fit_surrogate(liar_x, liar_y, settings)
                surrogate_fit_count += 1
            x_remaining = candidate_matrix[liar_remaining]
            try:
                raw_means, raw_standard_deviations = liar_surrogate.predict(
                    x_remaining,
                    return_std=True,
                )
            except Exception as error:
                raise BayesianOptimizationExecutionError(
                    "Gaussian-process surrogate prediction failed."
                ) from error
            means = np.asarray(raw_means, dtype=np.float64)
            standard_deviations = np.asarray(raw_standard_deviations, dtype=np.float64)
            expected_shape = (len(liar_remaining),)
            if (
                means.shape != expected_shape
                or standard_deviations.shape != expected_shape
                or not bool(np.isfinite(means).all())
                or not bool(np.isfinite(standard_deviations).all())
                or bool((standard_deviations < 0.0).any())
            ):
                raise BayesianOptimizationExecutionError(
                    "Gaussian-process surrogate returned invalid predictive statistics."
                )
            best_observed = float(liar_y.max())
            acquisition = _expected_improvement(
                means,
                standard_deviations,
                best_observed=best_observed,
                exploration_xi=settings.exploration_xi,
            )
            if not bool(np.isfinite(acquisition).all()):
                raise BayesianOptimizationExecutionError(
                    "Expected Improvement produced a non-finite acquisition value."
                )
            largest_ei = float(acquisition.max())
            if largest_ei <= settings.min_expected_improvement:
                # On the first pick this is the run's stop rule, exactly as before; on
                # a later pick it only ends the batch — the lie-shrunken EI is not the
                # true model's verdict on the run.
                if pick_number == 0:
                    minimum_reached = True
                    last_selected_ei = largest_ei
                break
            tied_positions = [
                position
                for position, value in enumerate(acquisition)
                if math.isclose(float(value), largest_ei, rel_tol=1.0e-12, abs_tol=1.0e-15)
            ]
            selected_position = min(
                tied_positions,
                key=lambda position: candidates[liar_remaining[position]].candidate_id,
            )
            candidate_index = liar_remaining[selected_position]
            picks.append(
                (
                    candidate_index,
                    float(means[selected_position]),
                    float(standard_deviations[selected_position]),
                    float(acquisition[selected_position]),
                )
            )
            liar_x = np.vstack([liar_x, candidate_matrix[candidate_index : candidate_index + 1]])
            liar_y = np.append(liar_y, best_observed)
            del liar_remaining[selected_position]

        if minimum_reached:
            stopped_reason = "minimum_expected_improvement_reached"
            break
        for candidate_index, predicted_mean, predicted_sd, selected_ei in picks:
            candidate = candidates[candidate_index]
            score = _evaluate_candidate(evaluator, candidate, development)
            if candidate.candidate_id in cache:
                raise BayesianOptimizationExecutionError(
                    "Bayesian optimizer attempted to evaluate a duplicate candidate."
                )
            cache[candidate.candidate_id] = score
            evaluated_indices.append(candidate_index)
            last_selected_ei = selected_ei
            evaluations.append(
                BayesianEvaluation(
                    iteration=len(evaluations),
                    phase="expected_improvement",
                    candidate=candidate,
                    objective_value=score,
                    predicted_mean=predicted_mean,
                    predicted_standard_deviation=predicted_sd,
                    expected_improvement=selected_ei,
                )
            )
        if not picks:
            break

    if len(cache) == len(candidates):
        stopped_reason = "search_space_exhausted"

    trace = tuple(evaluations)
    recommended = min(
        trace,
        key=lambda item: (-item.objective_value, item.candidate.candidate_id),
    )
    fingerprint = _run_fingerprint(
        settings,
        development,
        holdout,
        trace,
        stopped_reason,
    )
    return BayesianOptimizationResult(
        config=settings,
        development_fold_ids=development,
        locked_holdout_fold_ids=holdout,
        evaluations=trace,
        recommended_candidate=recommended.candidate,
        best_objective_value=recommended.objective_value,
        stopped_reason=stopped_reason,
        run_fingerprint=fingerprint,
        diagnostics={
            "search_space_size": len(candidates),
            "batch_size": settings.batch_size,
            # The wildcard-hold search sat 13 of 20 evaluations on a grid edge and a
            # human had to notice; the record says it now, per recommendation.
            "recommended_on_grid_edge": bool(_grid_edge_factors(recommended.candidate, settings)),
            "grid_edge_factors": list(_grid_edge_factors(recommended.candidate, settings)),
            "evaluation_budget": settings.evaluation_budget,
            "evaluated_candidate_count": len(trace),
            "evaluation_cache_entries": len(cache),
            "duplicate_candidate_evaluations": 0,
            "initial_design_policy": "seeded_maximin_normalized_grid",
            "surrogate": "GaussianProcessRegressor",
            "kernel": last_kernel,
            "kernel_hyperparameter_optimizer": None,
            "acquisition": "expected_improvement",
            "last_selected_expected_improvement": last_selected_ei,
            "surrogate_fit_count": surrogate_fit_count,
            "development_fold_ids": development,
            "locked_holdout_fold_ids_recorded": holdout,
            "locked_holdout_accessed": False,
            "automatic_promotion": False,
            "recommendation_only": True,
            "configuration_fingerprint": settings.configuration_fingerprint,
        },
    )
