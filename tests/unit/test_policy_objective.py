"""Synthetic tests binding Bayesian policy search to the real fold evaluator.

The panel here is the small synthetic one used across the data-layer tests, so every
CP-SAT solve is fast; the point is that the adapter drives the *actual* chronological
evaluation machinery, not a stand-in objective.
"""

import pytest
from tests.fixtures.synthetic_gameweeks import SEASON, make_canonical_gameweeks

from squadopt.bayesopt import (
    BayesianCandidate,
    BayesianFactor,
    BayesianOptimizationConfig,
    FactorKind,
    run_bayesian_optimization,
)
from squadopt.experiments import (
    PINNED_RISK_AVERSION,
    BaselinePolicyObjective,
    ExperimentExecutionError,
    PolicyObjectiveConfig,
)

CONFIG = PolicyObjectiveConfig(development_seasons=(SEASON,))


def _objective() -> BaselinePolicyObjective:
    return BaselinePolicyObjective(make_canonical_gameweeks(), CONFIG)


def _candidate(form_window: int = 5, bench_weight: float = 0.1) -> BayesianCandidate:
    return BayesianCandidate({"form_window": form_window, "bench_weight": bench_weight})


# --- the objective on its own ------------------------------------------------


def test_the_objective_exposes_chronological_development_folds() -> None:
    objective = _objective()

    fold_ids = objective.development_fold_ids
    assert len(fold_ids) == 7
    assert fold_ids == tuple(sorted(fold_ids))
    assert all(fold_id.startswith(SEASON) for fold_id in fold_ids)


def test_one_candidate_evaluation_is_deterministic_across_instances() -> None:
    first = _objective()
    second = _objective()
    candidate = _candidate()

    first_value = first(candidate, first.development_fold_ids)
    second_value = second(candidate, second.development_fold_ids)

    assert first_value == second_value
    record = first.records[candidate.candidate_id]
    assert record["mean_realized_squad_points"] == first_value
    assert record["risk_aversion"] == PINNED_RISK_AVERSION
    assert record["scored_folds"] == 7


def test_a_factor_the_evaluator_cannot_honor_is_refused() -> None:
    """Searching a dead axis would produce a flat, fake dimension in the trace."""

    objective = _objective()
    candidate = BayesianCandidate({"form_window": 5, "bench_weight": 0.1, "risk_aversion": 0.5})

    with pytest.raises(ExperimentExecutionError, match="cannot honor"):
        objective(candidate, objective.development_fold_ids)


def test_a_missing_factor_is_refused() -> None:
    objective = _objective()

    with pytest.raises(ExperimentExecutionError, match="missing"):
        objective(BayesianCandidate({"form_window": 5}), objective.development_fold_ids)


def test_an_out_of_domain_bench_weight_is_refused() -> None:
    objective = _objective()

    with pytest.raises(ExperimentExecutionError, match=r"\[0, 1\]"):
        objective(_candidate(bench_weight=1.5), objective.development_fold_ids)


def test_foreign_fold_ids_are_refused() -> None:
    objective = _objective()

    with pytest.raises(ExperimentExecutionError, match="same panel"):
        objective(_candidate(), ("2030-31-gw02",))


def test_an_unknown_season_is_refused_at_construction() -> None:
    with pytest.raises(ExperimentExecutionError, match="absent from the panel"):
        BaselinePolicyObjective(
            make_canonical_gameweeks(),
            PolicyObjectiveConfig(development_seasons=("1999-00",)),
        )


# --- the objective under the real search loop --------------------------------


def _search_config() -> BayesianOptimizationConfig:
    return BayesianOptimizationConfig(
        factors=(
            BayesianFactor("form_window", 3, 5, 1, FactorKind.INTEGER),
            BayesianFactor("bench_weight", 0.0, 0.10, 0.05),
        ),
        evaluation_budget=5,
        initial_design_size=3,
    )


def test_the_search_runs_end_to_end_on_the_real_evaluator() -> None:
    objective = _objective()

    result = run_bayesian_optimization(
        objective,
        objective.development_fold_ids,
        _search_config(),
    )

    assert len(result.evaluations) == 5
    assert set(objective.records) == {item.candidate.candidate_id for item in result.evaluations}
    assert result.best_objective_value == max(item.objective_value for item in result.evaluations)
    assert result.diagnostics["locked_holdout_accessed"] is False


def test_the_search_is_reproducible_run_to_run() -> None:
    first = run_bayesian_optimization(
        _objective(),
        _objective().development_fold_ids,
        _search_config(),
    )
    second = run_bayesian_optimization(
        _objective(),
        _objective().development_fold_ids,
        _search_config(),
    )

    assert first.run_fingerprint == second.run_fingerprint
    assert first.recommended_candidate == second.recommended_candidate
