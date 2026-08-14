"""Synthetic acceptance tests for deterministic Bayesian policy search."""

import math
from dataclasses import replace

import numpy as np
import pytest

import squadopt.bayesopt.optimizer as bayesian_optimizer
from squadopt.bayesopt import (
    BayesianCandidate,
    BayesianFactor,
    BayesianOptimizationConfig,
    BayesianOptimizationConfigurationError,
    BayesianOptimizationExecutionError,
    FactorKind,
    enumerate_candidates,
    run_bayesian_optimization,
)

DEVELOPMENT_FOLDS = ("2023-24-gw10", "2023-24-gw11", "2024-25-gw10")


def _small_config(**changes: object) -> BayesianOptimizationConfig:
    values: dict[str, object] = {
        "factors": (
            BayesianFactor("form_window", 1, 5, 1, FactorKind.INTEGER),
            BayesianFactor("bench_weight", 0.0, 1.0, 0.5),
        ),
        "evaluation_budget": 10,
        "initial_design_size": 4,
        "deterministic_seed": 7,
    }
    values.update(changes)
    return BayesianOptimizationConfig(**values)  # type: ignore[arg-type]


def _objective(candidate: BayesianCandidate, folds: tuple[str, ...]) -> float:
    assert folds == DEVELOPMENT_FOLDS
    window = float(candidate.values["form_window"])
    bench = float(candidate.values["bench_weight"])
    return -((window - 4.0) ** 2) - 3.0 * ((bench - 0.5) ** 2)


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"factors": ()}, "non-empty"),
        ({"evaluation_budget": 0}, "at least 1"),
        ({"evaluation_budget": 16}, "search-space size"),
        ({"initial_design_size": 11}, "may not exceed evaluation_budget"),
        ({"deterministic_seed": -1}, "at least 0"),
        ({"exploration_xi": -0.1}, "at least 0"),
        ({"min_expected_improvement": -0.1}, "at least 0"),
        ({"kernel_length_scale": 0.0}, "at least"),
        ({"matern_nu": 1.0}, "must be 0.5, 1.5, or 2.5"),
        ({"observation_noise": 0.0}, "at least"),
        ({"contract_version": "future"}, "contract_version"),
    ],
)
def test_invalid_bayesian_config_is_rejected(
    change: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(BayesianOptimizationConfigurationError, match=message):
        _small_config(**change)


def test_factor_quantization_must_land_on_the_upper_bound() -> None:
    with pytest.raises(BayesianOptimizationConfigurationError, match="land exactly"):
        BayesianFactor("risk_aversion", 0.0, 1.0, 0.3)
    with pytest.raises(BayesianOptimizationConfigurationError, match="land exactly"):
        BayesianFactor("form_window", 1, 6, 2, FactorKind.INTEGER)


def test_mixed_search_space_is_exact_and_deterministic() -> None:
    config = _small_config()
    candidates = enumerate_candidates(config)

    assert config.search_space_size == 15
    assert len(candidates) == 15
    assert candidates[0].values == {"form_window": 1, "bench_weight": 0.0}
    assert candidates[-1].values == {"form_window": 5, "bench_weight": 1.0}
    assert len({candidate.candidate_id for candidate in candidates}) == 15


def test_configuration_fingerprint_changes_with_search_controls() -> None:
    config = _small_config()

    assert config.configuration_fingerprint == _small_config().configuration_fingerprint
    assert (
        config.configuration_fingerprint
        != replace(
            config,
            exploration_xi=0.2,
        ).configuration_fingerprint
    )


def test_repeated_runs_produce_the_same_trace_and_recommendation() -> None:
    config = _small_config()

    first = run_bayesian_optimization(_objective, DEVELOPMENT_FOLDS, config)
    second = run_bayesian_optimization(_objective, DEVELOPMENT_FOLDS, config)

    assert [item.candidate.candidate_id for item in first.evaluations] == [
        item.candidate.candidate_id for item in second.evaluations
    ]
    assert [item.objective_value for item in first.evaluations] == [
        item.objective_value for item in second.evaluations
    ]
    assert first.recommended_candidate == second.recommended_candidate
    assert first.run_fingerprint == second.run_fingerprint


def test_candidates_are_evaluated_once_and_only_on_development_folds() -> None:
    calls: list[tuple[str, tuple[str, ...]]] = []

    def evaluator(candidate: BayesianCandidate, folds: tuple[str, ...]) -> float:
        calls.append((candidate.candidate_id, folds))
        return _objective(candidate, folds)

    result = run_bayesian_optimization(
        evaluator,
        DEVELOPMENT_FOLDS,
        _small_config(),
        locked_holdout_fold_ids=("2025-26-gw10",),
    )

    assert len(calls) == len(result.evaluations)
    assert len({candidate_id for candidate_id, _ in calls}) == len(calls)
    assert all(folds == DEVELOPMENT_FOLDS for _, folds in calls)
    assert result.diagnostics["locked_holdout_accessed"] is False
    assert result.diagnostics["duplicate_candidate_evaluations"] == 0
    assert result.diagnostics["automatic_promotion"] is False


def test_small_budget_search_matches_exhaustive_known_optimum() -> None:
    config = _small_config()
    exhaustive = {
        candidate.candidate_id: _objective(candidate, DEVELOPMENT_FOLDS)
        for candidate in enumerate_candidates(config)
    }

    result = run_bayesian_optimization(_objective, DEVELOPMENT_FOLDS, config)

    expected_id = min(
        exhaustive, key=lambda candidate_id: (-exhaustive[candidate_id], candidate_id)
    )
    assert len(result.evaluations) == config.evaluation_budget
    assert len(result.evaluations) < config.search_space_size
    assert result.recommended_candidate.candidate_id == expected_id
    assert result.best_objective_value == pytest.approx(exhaustive[expected_id])
    assert result.stopped_reason == "evaluation_budget_exhausted"


def test_exhausting_a_finite_grid_is_reported_explicitly() -> None:
    config = _small_config(evaluation_budget=15)

    result = run_bayesian_optimization(_objective, DEVELOPMENT_FOLDS, config)

    assert len(result.evaluations) == config.search_space_size
    assert result.stopped_reason == "search_space_exhausted"


def test_expected_improvement_matches_closed_form_at_the_incumbent() -> None:
    acquisition = bayesian_optimizer._expected_improvement(
        np.asarray([0.0, 1.0]),
        np.asarray([1.0, 0.0]),
        best_observed=0.0,
        exploration_xi=0.0,
    )

    assert acquisition[0] == pytest.approx(1.0 / math.sqrt(2.0 * math.pi))
    assert acquisition[1] == pytest.approx(1.0)


def test_invalid_surrogate_predictions_raise_a_domain_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class InvalidSurrogate:
        kernel_ = "invalid"

        def predict(
            self,
            values: np.ndarray,
            *,
            return_std: bool,
        ) -> tuple[np.ndarray, np.ndarray]:
            assert return_std is True
            return np.full(len(values), math.nan), np.ones(len(values))

    monkeypatch.setattr(
        bayesian_optimizer,
        "_fit_surrogate",
        lambda x_values, y_values, config: InvalidSurrogate(),
    )

    with pytest.raises(BayesianOptimizationExecutionError, match="predictive statistics"):
        run_bayesian_optimization(_objective, DEVELOPMENT_FOLDS, _small_config())


def test_high_ei_threshold_stops_after_the_initial_design() -> None:
    config = _small_config(min_expected_improvement=1.0e9)

    result = run_bayesian_optimization(_objective, DEVELOPMENT_FOLDS, config)

    assert len(result.evaluations) == config.initial_design_size
    assert all(item.phase == "initial_design" for item in result.evaluations)
    assert result.stopped_reason == "minimum_expected_improvement_reached"


def test_invalid_objective_value_is_not_silently_accepted() -> None:
    def invalid(candidate: BayesianCandidate, folds: tuple[str, ...]) -> float:
        return math.nan

    with pytest.raises(BayesianOptimizationExecutionError, match="must be finite"):
        run_bayesian_optimization(invalid, DEVELOPMENT_FOLDS, _small_config())


def test_development_and_holdout_folds_must_be_disjoint() -> None:
    with pytest.raises(BayesianOptimizationExecutionError, match="must be disjoint"):
        run_bayesian_optimization(
            _objective,
            DEVELOPMENT_FOLDS,
            _small_config(),
            locked_holdout_fold_ids=(DEVELOPMENT_FOLDS[0],),
        )


def test_default_policy_space_contains_declared_three_factors() -> None:
    config = BayesianOptimizationConfig()

    assert tuple(factor.name for factor in config.factors) == (
        "form_window",
        "bench_weight",
        "risk_aversion",
    )
    assert config.search_space_size == 616
