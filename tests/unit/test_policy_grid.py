"""Tests for exhaustive grid evaluation and search-efficiency measurement.

The grid here is small and synthetic, but the evaluations run through the real
chronological machinery, so the ground-truth ranking and the determinism cross-check
against a recorded search are exercised exactly as they will be on the full grid.
"""

import pytest
from tests.fixtures.synthetic_gameweeks import SEASON, make_canonical_gameweeks

from squadopt.bayesopt import (
    BayesianFactor,
    BayesianOptimizationConfig,
    BayesianOptimizationResult,
    FactorKind,
    run_bayesian_optimization,
)
from squadopt.experiments import (
    BaselinePolicyObjective,
    ExperimentExecutionError,
    PolicyGridResult,
    PolicyObjectiveConfig,
    evaluate_policy_grid,
    summarize_search_efficiency,
)

CONFIG = PolicyObjectiveConfig(development_seasons=(SEASON,))


def _objective() -> BaselinePolicyObjective:
    return BaselinePolicyObjective(make_canonical_gameweeks(), CONFIG)


def _search_config(budget: int = 4) -> BayesianOptimizationConfig:
    return BayesianOptimizationConfig(
        factors=(
            BayesianFactor("form_window", 3, 5, 1, FactorKind.INTEGER),
            BayesianFactor("bench_weight", 0.0, 0.10, 0.05),
        ),
        evaluation_budget=budget,
        initial_design_size=min(budget, 3),
    )


def _search_document(
    result: BayesianOptimizationResult,
    objective: BaselinePolicyObjective,
) -> dict[str, object]:
    return {
        "objective_configuration_fingerprint": (objective.config.configuration_fingerprint),
        "recommended_candidate_id": result.recommended_candidate.candidate_id,
        "trace": [
            {
                "iteration": item.iteration,
                "candidate_id": item.candidate.candidate_id,
                "mean_realized_squad_points": item.objective_value,
            }
            for item in result.evaluations
        ],
    }


@pytest.fixture(scope="module")
def grid() -> PolicyGridResult:
    return evaluate_policy_grid(_objective(), _search_config())


@pytest.fixture(scope="module")
def search_document(grid: PolicyGridResult) -> dict[str, object]:
    objective = _objective()
    result = run_bayesian_optimization(objective, objective.development_fold_ids, _search_config())
    return _search_document(result, objective)


# --- the exhaustive grid -----------------------------------------------------


def test_the_grid_covers_every_candidate_with_consecutive_ranks(
    grid: PolicyGridResult,
) -> None:
    assert len(grid.cells) == 9
    assert [cell.rank for cell in grid.cells] == list(range(1, 10))
    assert grid.best.mean_realized_squad_points == max(
        cell.mean_realized_squad_points for cell in grid.cells
    )


def test_the_grid_is_deterministic(grid: PolicyGridResult) -> None:
    repeat = evaluate_policy_grid(_objective(), _search_config())

    assert [(cell.candidate_id, cell.mean_realized_squad_points) for cell in repeat.cells] == [
        (cell.candidate_id, cell.mean_realized_squad_points) for cell in grid.cells
    ]


# --- measuring a recorded search against ground truth ------------------------


def test_efficiency_measures_regret_and_rank_against_ground_truth(
    grid: PolicyGridResult,
    search_document: dict[str, object],
) -> None:
    efficiency = summarize_search_efficiency(grid, search_document)

    assert efficiency["grid_size"] == 9
    assert efficiency["search_evaluations"] == 4
    regret = efficiency["recommendation_regret_points"]
    assert isinstance(regret, float) and regret >= 0.0
    rank = efficiency["recommendation_true_rank"]
    assert isinstance(rank, int) and 1 <= rank <= 9
    if efficiency["recommended_candidate_id"] == efficiency["true_best_candidate_id"]:
        assert regret == 0.0 and rank == 1


def test_a_search_that_found_the_optimum_reports_the_iteration(
    grid: PolicyGridResult,
) -> None:
    objective = _objective()
    result = run_bayesian_optimization(
        objective, objective.development_fold_ids, _search_config(budget=9)
    )

    efficiency = summarize_search_efficiency(grid, _search_document(result, objective))

    assert efficiency["search_found_true_best"] is True
    assert efficiency["recommendation_regret_points"] == 0.0
    assert efficiency["recommendation_true_rank"] == 1
    assert isinstance(efficiency["true_best_found_at_iteration"], int)


def test_a_foreign_objective_configuration_is_refused(
    grid: PolicyGridResult,
    search_document: dict[str, object],
) -> None:
    document = dict(search_document)
    document["objective_configuration_fingerprint"] = "f" * 64

    with pytest.raises(ExperimentExecutionError, match="not comparable"):
        summarize_search_efficiency(grid, document)


def test_a_non_reproduced_trace_value_is_refused(
    grid: PolicyGridResult,
    search_document: dict[str, object],
) -> None:
    """A deterministic objective that disagrees with itself is a broken comparison."""

    document = dict(search_document)
    trace = [dict(entry) for entry in search_document["trace"]]  # type: ignore[union-attr]
    trace[0]["mean_realized_squad_points"] = 99.0
    document["trace"] = trace

    with pytest.raises(ExperimentExecutionError, match="does not reproduce"):
        summarize_search_efficiency(grid, document)


def test_a_trace_candidate_outside_the_grid_is_refused(
    grid: PolicyGridResult,
    search_document: dict[str, object],
) -> None:
    document = dict(search_document)
    trace = [dict(entry) for entry in search_document["trace"]]  # type: ignore[union-attr]
    trace[0]["candidate_id"] = "bench_weight=0.9-form_window=99"
    document["trace"] = trace

    with pytest.raises(ExperimentExecutionError, match="not part of the evaluated grid"):
        summarize_search_efficiency(grid, document)
