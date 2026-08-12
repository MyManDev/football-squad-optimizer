"""The walk-forward chain, from a historical panel to evaluated squad decisions.

Closes the loop the two Sprint 1 halves were built to close: the data side prepares
folds, and the evaluation side scores the decisions they produce. Nothing here
touches the network, and no real data is required.
"""

import pytest
from tests.fixtures.synthetic_gameweeks import (
    GAMEWEEK_COUNT,
    PREVIOUS_SEASON,
    SEASON,
    make_two_season_gameweeks,
)

from squadopt import OptimizationConfig
from squadopt.backtest import build_walk_forward_folds
from squadopt.evaluation import EvaluationConfig, EvaluationResult, evaluate_prepared_folds


def _evaluate(**fold_kwargs: object) -> EvaluationResult:
    folds = build_walk_forward_folds(make_two_season_gameweeks(), **fold_kwargs)  # type: ignore[arg-type]
    return evaluate_prepared_folds(
        folds,
        EvaluationConfig(
            optimization_config=OptimizationConfig(),
            run_metadata={"dataset": "synthetic-two-season"},
        ),
    )


def test_every_prepared_fold_is_solved() -> None:
    """Sprint 1 requires a feasibility rate of exactly 1.0."""

    summary = _evaluate().summary

    assert summary.attempted_folds == 2 * (GAMEWEEK_COUNT - 1)
    assert summary.feasibility_rate == 1.0
    assert summary.scored_folds == summary.attempted_folds


def test_every_fold_produces_a_realized_score() -> None:
    result = _evaluate()

    assert all(fold.is_scored for fold in result.folds)
    assert all(fold.realized_squad_points is not None for fold in result.folds)


def test_turnover_is_measured_between_adjacent_folds_only() -> None:
    """Fold order is meaningful: the first fold has no predecessor to compare against."""

    result = _evaluate()

    assert result.folds[0].squad_turnover is None
    assert all(fold.squad_turnover is not None for fold in result.folds[1:])
    assert result.summary.turnover_observations == len(result.folds) - 1


def test_fold_metadata_survives_into_the_results() -> None:
    result = _evaluate()

    first = result.folds[0]
    assert first.metadata["season"] == PREVIOUS_SEASON
    assert first.metadata["gameweek"] == 2


def test_restricting_seasons_evaluates_only_those_seasons() -> None:
    """This is how a holdout season stays unscored while remaining available as history."""

    result = _evaluate(seasons=[SEASON])

    assert result.summary.attempted_folds == GAMEWEEK_COUNT - 1
    assert {str(fold.metadata["season"]) for fold in result.folds} == {SEASON}


def test_the_chain_is_reproducible() -> None:
    first = _evaluate().summary
    second = _evaluate().summary

    assert first.mean_realized_squad_points == second.mean_realized_squad_points
    assert first.feasibility_rate == second.feasibility_rate


def test_projected_objective_is_reported_separately_from_realized_score() -> None:
    """Projected value is a diagnostic; it must never be read as performance."""

    summary = _evaluate().summary

    assert summary.mean_projected_objective_value is not None
    assert summary.mean_realized_squad_points is not None
    assert summary.mean_projected_objective_value != pytest.approx(
        summary.mean_realized_squad_points
    )


def test_solver_runtime_is_recorded_for_every_attempt() -> None:
    summary = _evaluate().summary

    assert summary.runtime_observations == summary.attempted_folds
    assert summary.median_solver_runtime_seconds is not None
    assert summary.p95_solver_runtime_seconds is not None
