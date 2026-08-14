"""Tests for the gate evaluation and the judging report.

The orchestration is exercised by running the real benchmark; what is tested here is the
part that decides a verdict, because a wrong threshold produces a confident wrong answer
and nothing downstream would catch it.
"""

import json
from types import SimpleNamespace
from typing import Any

import pandas as pd
import pytest

from squadopt.backtest.learned import (
    PairedDecisionMetrics,
    PositionPredictionMetrics,
    PredictionMetrics,
)
from squadopt.backtest.production_benchmark import (
    PREDICTION_METRIC_TOLERANCE,
    RIDGE_LOWER_BOUND_TOLERANCE,
    VERDICT_PROMOTABLE,
    VERDICT_RETAIN_CONTROL,
    GateCondition,
    PairedComparison,
    ProductionBenchmarkConfig,
    ProductionBenchmarkResult,
    _evaluate_gates,
    _non_deterministic_truncations,
    _relative_change,
    candidate_labels,
)
from squadopt.backtest.production_reporting import judgement_to_dict, judgement_to_markdown
from squadopt.backtest.splits import BacktestConfigurationError
from squadopt.experiments.config import PromotionPolicy
from squadopt.optimization import SolverStatus

POLICY = PromotionPolicy()
FOLDS = 147


def _comparison(
    *,
    candidate: str = "production",
    reference: str = "baseline",
    mean: float = 3.6395,
    lower: float = 1.7548,
) -> PairedComparison:
    return PairedComparison(
        candidate=candidate,
        reference=reference,
        comparable_folds=FOLDS,
        mean_difference=mean,
        median_difference=0.0,
        difference_stdev=14.8,
        confidence_interval_lower=lower,
        confidence_interval_upper=lower + 4.0,
        candidate_wins=73,
        ties=22,
        candidate_losses=52,
        season_mean_differences={"2021-22": mean},
    )


def _metrics(mae: float = 1.1230, rmse: float = 2.2054) -> PredictionMetrics:
    return PredictionMetrics(
        observations=101_447,
        mean_absolute_error=mae,
        root_mean_squared_error=rmse,
        mean_error=0.05,
        by_position=(
            PositionPredictionMetrics("GK", 11_145, 0.7726, 1.7631, 0.0297),
            PositionPredictionMetrics("FWD", 12_437, 1.2520, 2.4564, 0.0738),
        ),
    )


def _gates(**overrides: Any) -> tuple[GateCondition, ...]:
    settings: dict[str, Any] = {
        "against_baseline": _comparison(),
        "against_ridge": _comparison(reference="ridge", mean=0.4694, lower=-1.6738),
        "production": _metrics(),
        "ridge": _metrics(mae=1.1300, rmse=2.0991),
        "feasible": {"baseline": FOLDS, "ridge": FOLDS, "production": FOLDS},
        "fold_count": FOLDS,
    }
    settings.update(overrides)
    return _evaluate_gates(
        settings["against_baseline"],
        settings["against_ridge"],
        settings["production"],
        settings["ridge"],
        policy=POLICY,
        feasible=settings["feasible"],
        fold_count=settings["fold_count"],
    )


def _named(gates: tuple[GateCondition, ...], name: str) -> GateCondition:
    return next(gate for gate in gates if gate.name == name)


# --- the measured case ------------------------------------------------------


def test_the_measured_candidate_fails_exactly_two_conditions() -> None:
    """The verdict on record, reproduced from the numbers that produced it."""

    failed = [gate.name for gate in _gates() if not gate.passed]

    assert failed == ["ridge_lower_bound", "other_prediction_metric_tolerance"]


def test_every_condition_is_reported_separately() -> None:
    """A candidate failing one condition and one failing four are different situations."""

    assert len(_gates()) == 7


# --- each condition ---------------------------------------------------------


def test_the_baseline_mean_requires_the_declared_improvement() -> None:
    assert _named(
        _gates(against_baseline=_comparison(mean=0.5)), "baseline_mean_improvement"
    ).passed
    assert not _named(
        _gates(against_baseline=_comparison(mean=0.4999)), "baseline_mean_improvement"
    ).passed


def test_the_baseline_lower_bound_must_clear_zero() -> None:
    assert _named(_gates(against_baseline=_comparison(lower=0.0)), "baseline_lower_bound").passed
    assert not _named(
        _gates(against_baseline=_comparison(lower=-0.0001)), "baseline_lower_bound"
    ).passed


def test_the_ridge_lower_bound_uses_the_declared_tolerance() -> None:
    at_limit = _comparison(reference="ridge", mean=0.0, lower=RIDGE_LOWER_BOUND_TOLERANCE)
    beyond = _comparison(reference="ridge", mean=0.0, lower=RIDGE_LOWER_BOUND_TOLERANCE - 0.0001)

    assert _named(_gates(against_ridge=at_limit), "ridge_lower_bound").passed
    assert not _named(_gates(against_ridge=beyond), "ridge_lower_bound").passed


def test_an_improvement_on_either_prediction_metric_satisfies_that_condition() -> None:
    only_rmse = _gates(production=_metrics(mae=2.0, rmse=1.0), ridge=_metrics(mae=1.0, rmse=2.0))

    assert _named(only_rmse, "prediction_metric_improved_against_ridge").passed


def test_neither_metric_improving_fails_that_condition() -> None:
    worse = _gates(production=_metrics(mae=2.0, rmse=3.0), ridge=_metrics(mae=1.0, rmse=2.0))

    assert not _named(worse, "prediction_metric_improved_against_ridge").passed


def test_the_tolerance_bounds_the_metric_that_does_not_improve() -> None:
    # Kept off the exact boundary: 2.0 * 1.05 is not exactly 2.1 in binary floating
    # point, so testing the limit itself would test the arithmetic, not the rule.
    within = _metrics(mae=1.0, rmse=2.0 * (1.0 + PREDICTION_METRIC_TOLERANCE - 0.001))
    beyond = _metrics(mae=1.0, rmse=2.0 * (1.0 + PREDICTION_METRIC_TOLERANCE + 0.001))
    reference = _metrics(mae=2.0, rmse=2.0)

    assert _named(
        _gates(production=within, ridge=reference), "other_prediction_metric_tolerance"
    ).passed
    assert not _named(
        _gates(production=beyond, ridge=reference), "other_prediction_metric_tolerance"
    ).passed


def test_an_infeasible_fold_fails_the_feasibility_condition() -> None:
    short = {"baseline": FOLDS, "ridge": FOLDS, "production": FOLDS - 1}

    assert not _named(_gates(feasible=short), "every_fold_feasible").passed


def test_relative_change_is_signed_so_negative_means_better() -> None:
    assert _relative_change(0.9, 1.0) == pytest.approx(-0.1)
    assert _relative_change(1.1, 1.0) == pytest.approx(0.1)


def test_relative_change_survives_a_zero_reference() -> None:
    assert _relative_change(0.0, 0.0) == 0.0
    assert _relative_change(1.0, 0.0) == float("inf")


# --- the verdict ------------------------------------------------------------


def _result(gates: tuple[GateCondition, ...]) -> ProductionBenchmarkResult:
    decision = PairedDecisionMetrics(
        FOLDS,
        FOLDS,
        FOLDS,
        FOLDS,
        53.7755,
        57.4150,
        3.6395,
        73,
        22,
        52,
        FOLDS,
        FOLDS,
        FOLDS,
        15.0,
        11.0,
    )
    return ProductionBenchmarkResult(
        config=ProductionBenchmarkConfig(),
        metadata={"benchmark_contract_version": "test"},
        fold_count=FOLDS,
        feasible_folds={"baseline": FOLDS, "ridge": FOLDS, "production": FOLDS},
        solver_statuses={
            "baseline": {"OPTIMAL": FOLDS},
            "ridge": {"OPTIMAL": 116, "FEASIBLE": 31},
            "production": {"OPTIMAL": FOLDS},
        },
        mean_realized_points={"baseline": 53.7755, "ridge": 56.9456, "production": 57.4150},
        prediction_metrics={"production": _metrics(), "ridge": _metrics(1.13, 2.0991)},
        decision_metrics={"baseline": decision, "ridge": decision},
        comparisons=(_comparison(), _comparison(reference="ridge", mean=0.4694, lower=-1.6738)),
        gates=gates,
        verdict=(
            VERDICT_PROMOTABLE if all(gate.passed for gate in gates) else VERDICT_RETAIN_CONTROL
        ),
        residuals=pd.DataFrame({"residual": [0.0]}),
    )


def test_a_failing_condition_retains_the_control() -> None:
    assert _result(_gates()).verdict == VERDICT_RETAIN_CONTROL


def test_clearing_every_condition_is_eligibility_not_promotion() -> None:
    """Clearing the gates admits a candidate to the holdout protocol, nothing more."""

    passing = tuple(
        GateCondition(gate.name, gate.requirement, gate.measured, True) for gate in _gates()
    )

    assert _result(passing).verdict == VERDICT_PROMOTABLE
    assert "promoted" not in VERDICT_PROMOTABLE


# --- the report -------------------------------------------------------------


def test_the_document_records_the_numerical_environment() -> None:
    """Its absence is what made an earlier discrepancy unexplainable."""

    document = judgement_to_dict(_result(_gates()))
    environment = document["environment"]

    assert isinstance(environment, dict)
    for library in ("python", "pandas", "numpy", "scikit_learn", "ortools"):
        assert environment[library]


def test_the_document_is_serialisable() -> None:
    json.dumps(judgement_to_dict(_result(_gates())))


def test_the_document_records_every_condition_and_the_verdict() -> None:
    document = judgement_to_dict(_result(_gates()))

    assert len(document["gates"]) == 7  # type: ignore[arg-type]
    assert document["gates_all_passed"] is False
    assert document["verdict"] == VERDICT_RETAIN_CONTROL


def test_the_document_records_the_deterministic_solver_budget() -> None:
    document = judgement_to_dict(_result(_gates()))

    optimization = document["configuration"]["optimization"]  # type: ignore[index]
    assert optimization["solver_deterministic_time_limit"] == 0.5
    assert optimization["solver_time_limit_seconds"] == 120.0
    assert optimization["stopping_rule"] == ("deterministic_work_with_wall_clock_safety_cap")


def test_the_report_names_the_distinction_it_rests_on() -> None:
    markdown = judgement_to_markdown(_result(_gates()))

    assert "development gate verdict" in markdown
    assert "not an operational promotion" in markdown


def test_the_report_breaks_prediction_error_down_by_position() -> None:
    """Pooling is what hides a systematic skew."""

    markdown = judgement_to_markdown(_result(_gates()))

    assert "by position" in markdown
    assert "| GK |" in markdown


def test_the_report_states_the_holdout_is_untouched() -> None:
    markdown = judgement_to_markdown(_result(_gates()))

    assert "2025-26" in markdown


# --- configuration ----------------------------------------------------------


def test_the_candidates_are_named_in_report_order() -> None:
    assert tuple(candidate_labels()) == ("baseline", "ridge", "production")


def test_the_default_seasons_exclude_the_holdout() -> None:
    assert "2025-26" not in ProductionBenchmarkConfig().seasons


def test_the_default_benchmark_uses_deterministic_work_with_a_wall_safety_cap() -> None:
    optimization = ProductionBenchmarkConfig().evaluation_config.optimization_config

    assert optimization.solver_deterministic_time_limit == 0.5
    assert optimization.solver_time_limit_seconds == 120.0


@pytest.mark.parametrize("seasons", [(), "2024-25", ("",)])
def test_invalid_seasons_are_rejected(seasons: Any) -> None:
    with pytest.raises(BacktestConfigurationError, match="seasons"):
        ProductionBenchmarkConfig(seasons=seasons)


# --- solver truncation ------------------------------------------------------


def test_a_truncated_candidate_is_named() -> None:
    """A fold that stopped at the limit is a search result, not a projection result."""

    assert _result(_gates()).truncated_candidates == ("ridge",)


def test_a_fully_optimal_run_names_nobody() -> None:
    result = _result(_gates())
    optimal = ProductionBenchmarkResult(
        config=result.config,
        metadata=result.metadata,
        fold_count=result.fold_count,
        feasible_folds=result.feasible_folds,
        solver_statuses={label: {"OPTIMAL": FOLDS} for label in result.solver_statuses},
        mean_realized_points=result.mean_realized_points,
        prediction_metrics=result.prediction_metrics,
        decision_metrics=result.decision_metrics,
        comparisons=result.comparisons,
        gates=result.gates,
        verdict=result.verdict,
        residuals=result.residuals,
    )

    assert optimal.truncated_candidates == ()


def test_the_report_warns_when_a_candidate_was_truncated() -> None:
    """Silently accepting a timeout is what made an earlier run irreproducible."""

    markdown = judgement_to_markdown(_result(_gates()))

    assert "Solver truncation" in markdown
    assert "did not solve every fold to optimality" in markdown
    assert "unknown direction" in markdown
    assert "depressed" not in markdown


def test_the_document_records_solver_outcomes_per_candidate() -> None:
    document = judgement_to_dict(_result(_gates()))

    assert document["solver_statuses"]["ridge"] == {"OPTIMAL": 116, "FEASIBLE": 31}
    assert document["truncated_candidates"] == ["ridge"]


def test_wall_limited_incomplete_fold_is_rejected_as_non_deterministic() -> None:
    fold = SimpleNamespace(
        fold_id="2024-25-gw1",
        optimization_result=SimpleNamespace(
            solver_status=SolverStatus.FEASIBLE,
            diagnostics={"deterministic_time_budget_exhausted": False},
        ),
    )

    assert _non_deterministic_truncations(SimpleNamespace(folds=(fold,))) == ("2024-25-gw1",)


def test_deterministic_budget_truncation_is_reproducible() -> None:
    fold = SimpleNamespace(
        fold_id="2024-25-gw1",
        optimization_result=SimpleNamespace(
            solver_status=SolverStatus.FEASIBLE,
            diagnostics={"deterministic_time_budget_exhausted": True},
        ),
    )

    assert _non_deterministic_truncations(SimpleNamespace(folds=(fold,))) == ()


@pytest.mark.parametrize(
    ("budget_exhausted", "expected"),
    [
        (False, ("2024-25-gw1",)),
        (True, ()),
    ],
)
def test_incomplete_tiebreak_must_stop_on_deterministic_work(
    budget_exhausted: bool,
    expected: tuple[str, ...],
) -> None:
    fold = SimpleNamespace(
        fold_id="2024-25-gw1",
        optimization_result=SimpleNamespace(
            solver_status=SolverStatus.OPTIMAL,
            diagnostics={
                "tiebreak_attempted": True,
                "tiebreak_completed": False,
                "deterministic_time_budget_exhausted": budget_exhausted,
            },
        ),
    )

    assert _non_deterministic_truncations(SimpleNamespace(folds=(fold,))) == expected
