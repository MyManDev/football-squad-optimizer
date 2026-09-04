"""Contract tests for the typed seam between BO candidates and fold evaluations.

The prediction-side builder does not exist yet; these tests pin down what it must
accept and return, and what the binding refuses on its behalf. When the real builder
arrives, it plugs into `bind_policy_evaluator` without renegotiating the search side.
"""

import pytest

from squadopt.bayesopt import (
    EVALUATION_OBJECTIVE_VERSION,
    BayesianCandidate,
    BayesianOptimizationConfig,
    BayesianOptimizationConfigurationError,
    BayesianOptimizationExecutionError,
    BoundPolicyEvaluator,
    DeterministicPolicyFactors,
    DevelopmentFoldEvaluation,
    bind_policy_evaluator,
    policy_factors_from_candidate,
    run_bayesian_optimization,
)

DEVELOPMENT_FOLDS = ("2023-24-gw02", "2023-24-gw03", "2024-25-gw02")


def _candidate(**overrides: object) -> BayesianCandidate:
    values: dict[str, object] = {"form_window": 5, "bench_weight": 0.10, "risk_aversion": 0.20}
    values.update(overrides)
    return BayesianCandidate(values)  # type: ignore[arg-type]


def _evaluation(**overrides: object) -> DevelopmentFoldEvaluation:
    settings: dict[str, object] = {
        "objective_value": 55.0,
        "evaluated_fold_ids": DEVELOPMENT_FOLDS,
    }
    settings.update(overrides)
    return DevelopmentFoldEvaluation(**settings)  # type: ignore[arg-type]


# --- the factor vocabulary ---------------------------------------------------


def test_a_candidate_maps_onto_typed_policy_factors() -> None:
    factors = policy_factors_from_candidate(_candidate())

    assert factors == DeterministicPolicyFactors(
        form_window=5, bench_weight=0.10, risk_aversion=0.20
    )


def test_an_integer_valued_float_form_window_is_accepted() -> None:
    factors = policy_factors_from_candidate(_candidate(form_window=5.0))

    assert factors.form_window == 5


def test_a_fractional_form_window_is_refused() -> None:
    with pytest.raises(BayesianOptimizationExecutionError, match="integer-valued"):
        policy_factors_from_candidate(_candidate(form_window=5.5))


def test_a_missing_policy_factor_is_refused_not_defaulted() -> None:
    candidate = BayesianCandidate({"form_window": 5, "bench_weight": 0.10})

    with pytest.raises(BayesianOptimizationExecutionError, match="missing"):
        policy_factors_from_candidate(candidate)


def test_an_unknown_factor_is_refused_not_ignored() -> None:
    """Silently dropping a factor would fake its influence in the search trace."""

    with pytest.raises(BayesianOptimizationExecutionError, match="unexpected"):
        policy_factors_from_candidate(_candidate(learning_rate=0.01))


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("form_window", 0),
        ("bench_weight", -0.1),
        ("bench_weight", 1.5),
        ("risk_aversion", -0.2),
        ("risk_aversion", float("inf")),
    ],
)
def test_out_of_domain_factor_values_are_refused(name: str, value: object) -> None:
    with pytest.raises(BayesianOptimizationConfigurationError):
        DeterministicPolicyFactors(
            **{"form_window": 5, "bench_weight": 0.1, "risk_aversion": 0.2, name: value}  # type: ignore[arg-type]
        )


# --- what one fold evaluation must report -----------------------------------


def test_an_evaluation_carries_the_default_objective_version() -> None:
    evaluation = _evaluation()

    assert evaluation.objective_version == EVALUATION_OBJECTIVE_VERSION
    assert evaluation.evaluated_fold_ids == DEVELOPMENT_FOLDS


def test_a_non_finite_objective_is_refused() -> None:
    with pytest.raises(BayesianOptimizationConfigurationError, match="finite"):
        _evaluation(objective_value=float("nan"))


def test_duplicate_evaluated_folds_are_refused() -> None:
    with pytest.raises(BayesianOptimizationConfigurationError, match="unique"):
        _evaluation(evaluated_fold_ids=("2023-24-gw02", "2023-24-gw02"))


def test_provenance_is_frozen_against_later_mutation() -> None:
    source = {"repository_commit": "a" * 40}
    evaluation = _evaluation(provenance=source)
    source["repository_commit"] = "b" * 40

    assert evaluation.provenance["repository_commit"] == "a" * 40
    with pytest.raises(TypeError):
        evaluation.provenance["extra"] = True  # type: ignore[index]


# --- the binding -------------------------------------------------------------


def test_the_binding_forwards_factors_and_returns_the_scalar_objective() -> None:
    seen: list[tuple[DeterministicPolicyFactors, tuple[str, ...]]] = []

    def evaluator(
        factors: DeterministicPolicyFactors, folds: tuple[str, ...]
    ) -> DevelopmentFoldEvaluation:
        seen.append((factors, folds))
        return _evaluation(objective_value=52.5)

    bound = bind_policy_evaluator(evaluator)
    value = bound(_candidate(), DEVELOPMENT_FOLDS)

    assert value == 52.5
    assert seen == [
        (
            DeterministicPolicyFactors(form_window=5, bench_weight=0.10, risk_aversion=0.20),
            DEVELOPMENT_FOLDS,
        )
    ]


def test_the_binding_records_every_evaluation_by_candidate_id() -> None:
    bound = bind_policy_evaluator(lambda factors, folds: _evaluation())
    candidate = _candidate()

    bound(candidate, DEVELOPMENT_FOLDS)

    assert set(bound.records) == {candidate.candidate_id}
    assert bound.records[candidate.candidate_id].objective_value == 55.0


def test_folds_not_covering_the_request_stop_the_search() -> None:
    bound = bind_policy_evaluator(
        lambda factors, folds: _evaluation(evaluated_fold_ids=DEVELOPMENT_FOLDS[:2])
    )

    with pytest.raises(BayesianOptimizationExecutionError, match="missing"):
        bound(_candidate(), DEVELOPMENT_FOLDS)


def test_extra_evaluated_folds_stop_the_search() -> None:
    """An evaluation covering unrequested folds may have read the locked holdout."""

    bound = bind_policy_evaluator(
        lambda factors, folds: _evaluation(evaluated_fold_ids=(*DEVELOPMENT_FOLDS, "2025-26-gw02"))
    )

    with pytest.raises(BayesianOptimizationExecutionError, match="extra"):
        bound(_candidate(), DEVELOPMENT_FOLDS)


def test_a_foreign_objective_version_stops_the_search() -> None:
    bound = bind_policy_evaluator(
        lambda factors, folds: _evaluation(objective_version="another_objective_v9")
    )

    with pytest.raises(BayesianOptimizationExecutionError, match="bound to"):
        bound(_candidate(), DEVELOPMENT_FOLDS)


def test_an_untyped_return_value_is_refused() -> None:
    bound = bind_policy_evaluator(lambda factors, folds: 55.0)  # type: ignore[arg-type, return-value]

    with pytest.raises(BayesianOptimizationExecutionError, match="DevelopmentFoldEvaluation"):
        bound(_candidate(), DEVELOPMENT_FOLDS)


# --- the bound evaluator drives a real search --------------------------------


def test_a_bound_evaluator_completes_a_deterministic_search() -> None:
    """The typed seam must satisfy the narrow callback the optimizer expects."""

    def evaluator(
        factors: DeterministicPolicyFactors, folds: tuple[str, ...]
    ) -> DevelopmentFoldEvaluation:
        objective = (
            50.0 - (factors.form_window - 5) ** 2 + factors.bench_weight - factors.risk_aversion
        )
        return _evaluation(objective_value=objective, evaluated_fold_ids=folds)

    config = BayesianOptimizationConfig(evaluation_budget=10, initial_design_size=4)
    bound: BoundPolicyEvaluator = bind_policy_evaluator(evaluator)

    first = run_bayesian_optimization(bound, DEVELOPMENT_FOLDS, config)
    second = run_bayesian_optimization(bind_policy_evaluator(evaluator), DEVELOPMENT_FOLDS, config)

    assert first.run_fingerprint == second.run_fingerprint
    assert first.best_objective_value == max(item.objective_value for item in first.evaluations)
    assert set(bound.records) == {item.candidate.candidate_id for item in first.evaluations}
    recorded = bound.records[first.recommended_candidate.candidate_id]
    assert recorded.objective_value == first.best_objective_value
    assert recorded.evaluated_fold_ids == DEVELOPMENT_FOLDS
