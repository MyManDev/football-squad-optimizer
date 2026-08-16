"""Tests for the prediction-side development-fold evaluator.

The panel is the small synthetic one used across the data-layer tests, so every CP-SAT
solve is fast. What is exercised is the real chronological machinery, not a stand-in:
the point of this seam is that ``form_window`` reaches the frozen feature mapping
unchanged, and the only way to test that is to run it.
"""

import pytest
from tests.fixtures.synthetic_gameweeks import (
    PREVIOUS_SEASON,
    SEASON,
    make_canonical_gameweeks,
    make_two_season_gameweeks,
)

from squadopt.backtest.policy_evaluation import (
    FORM_WINDOW_MAPPING_VERSION,
    PREDICTION_POLICY_EVALUATION_CONTRACT_VERSION,
    DevelopmentFoldPredictionEvaluator,
    PredictionPolicyEvaluatorConfig,
)
from squadopt.backtest.splits import (
    BacktestConfigurationError,
    walk_forward_decision_points,
)
from squadopt.bayesopt import (
    BayesianCandidate,
    BayesianFactor,
    BayesianOptimizationConfig,
    BayesianOptimizationExecutionError,
    DeterministicPolicyFactors,
    FactorKind,
    bind_policy_evaluator,
    run_bayesian_optimization,
)
from squadopt.evaluation import EvaluationConfig, EvaluationFold, evaluate_prepared_folds
from squadopt.features import CrossSeasonConfig, build_feature_dataset
from squadopt.prediction import FormWindowMapping, build_projection_table

CONFIG = PredictionPolicyEvaluatorConfig(development_seasons=(SEASON,))


def _evaluator() -> DevelopmentFoldPredictionEvaluator:
    return DevelopmentFoldPredictionEvaluator(make_canonical_gameweeks(), CONFIG)


def _factors(
    form_window: int = 5,
    bench_weight: float = 0.1,
    risk_aversion: float = 0.0,
) -> DeterministicPolicyFactors:
    return DeterministicPolicyFactors(
        form_window=form_window,
        bench_weight=bench_weight,
        risk_aversion=risk_aversion,
    )


# --- the development population ---------------------------------------------


def test_the_evaluator_exposes_chronological_development_folds() -> None:
    evaluator = _evaluator()

    fold_ids = evaluator.development_fold_ids

    assert fold_ids == tuple(sorted(fold_ids))
    assert all(fold_id.startswith(SEASON) for fold_id in fold_ids)


def test_seasons_after_the_development_range_never_reach_a_feature_window() -> None:
    """A later season must not enter even as carry-over history.

    The panel here holds two seasons and only the earlier one is declared, which is the
    same shape as declaring 2021-22..2024-25 while 2025-26 sits in the panel.
    """

    evaluator = DevelopmentFoldPredictionEvaluator(
        make_two_season_gameweeks(),
        PredictionPolicyEvaluatorConfig(development_seasons=(PREVIOUS_SEASON,)),
    )

    assert all(fold_id.startswith(PREVIOUS_SEASON) for fold_id in evaluator.development_fold_ids)

    evaluation = evaluator(_factors(), evaluator.development_fold_ids)
    only_earlier = DevelopmentFoldPredictionEvaluator(
        make_two_season_gameweeks().loc[lambda frame: frame["season"] == PREVIOUS_SEASON],
        PredictionPolicyEvaluatorConfig(development_seasons=(PREVIOUS_SEASON,)),
    )(_factors(), evaluator.development_fold_ids)

    assert evaluation.objective_value == only_earlier.objective_value


def test_a_season_absent_from_the_panel_is_refused() -> None:
    with pytest.raises(BacktestConfigurationError, match="absent from the panel"):
        DevelopmentFoldPredictionEvaluator(
            make_canonical_gameweeks(),
            PredictionPolicyEvaluatorConfig(development_seasons=("1999-00",)),
        )


def test_opening_gameweeks_stay_outside_the_development_population() -> None:
    """Opening gameweeks are a separate evidence regime, not a tunable setting."""

    with pytest.raises(BacktestConfigurationError, match="separate evidence regime"):
        PredictionPolicyEvaluatorConfig(min_prior_gameweeks_in_season=0)


# --- the frozen form_window mapping -----------------------------------------


@pytest.mark.parametrize("form_window", [3, 5, 8])
def test_form_window_reaches_the_frozen_mapping_unchanged(form_window: int) -> None:
    """The evaluator must apply ``form_window_v1``, not its own interpretation.

    Built independently through ``FormWindowMapping`` and compared value by value: if
    the evaluator reinterpreted the window, a search would report tuning one thing
    while having tuned another.
    """

    panel = make_canonical_gameweeks()
    evaluator = DevelopmentFoldPredictionEvaluator(panel, CONFIG)
    mapping = FormWindowMapping(form_window=form_window)
    features = build_feature_dataset(
        panel, config=mapping.feature_config, cross_season=CrossSeasonConfig()
    )
    decisions = walk_forward_decision_points(panel, seasons=(SEASON,))

    folds = evaluator._folds(form_window)

    assert len(folds) == len(decisions)
    for fold, decision in zip(folds, decisions, strict=True):
        expected = build_projection_table(
            features,
            season=decision.season,
            gameweek=decision.gameweek,
            config=mapping.projection_config,
        )
        assert fold.projections.equals(expected)
        assert fold.metadata["form_window_mapping_version"] == FORM_WINDOW_MAPPING_VERSION


def test_the_mapping_holds_min_periods_at_one() -> None:
    """``min_periods`` is a fixed missing-history policy, not a hidden second factor."""

    assert FormWindowMapping(form_window=6).feature_config.min_periods == 1


# --- factors the evaluator cannot honor -------------------------------------


@pytest.mark.parametrize("risk_aversion", [0.1, 1.0])
def test_a_nonzero_risk_aversion_is_refused_rather_than_ignored(risk_aversion: float) -> None:
    """A dead axis accepted silently becomes a fake dimension in the search trace."""

    evaluator = _evaluator()

    with pytest.raises(BayesianOptimizationExecutionError, match="risk_aversion"):
        evaluator(_factors(risk_aversion=risk_aversion), evaluator.development_fold_ids)


def test_a_zero_risk_aversion_is_accepted_and_recorded() -> None:
    evaluator = _evaluator()

    evaluation = evaluator(_factors(risk_aversion=0.0), evaluator.development_fold_ids)

    assert evaluation.provenance["risk_aversion"] == 0.0


def test_factors_of_the_wrong_type_are_refused() -> None:
    evaluator = _evaluator()

    with pytest.raises(BayesianOptimizationExecutionError, match="DeterministicPolicyFactors"):
        evaluator({"form_window": 5}, evaluator.development_fold_ids)  # type: ignore[arg-type]


# --- the requested fold population ------------------------------------------


def test_a_fold_outside_the_declared_population_is_refused() -> None:
    evaluator = _evaluator()
    requested = (*evaluator.development_fold_ids, "2025-26-gw99")

    with pytest.raises(BayesianOptimizationExecutionError, match="extra"):
        evaluator(_factors(), requested)


def test_a_missing_fold_is_refused() -> None:
    evaluator = _evaluator()
    requested = evaluator.development_fold_ids[:-1]

    with pytest.raises(BayesianOptimizationExecutionError, match="missing"):
        evaluator(_factors(), requested)


# --- the reported evaluation ------------------------------------------------


def test_one_evaluation_is_deterministic_across_instances() -> None:
    first, second = _evaluator(), _evaluator()

    first_value = first(_factors(), first.development_fold_ids)
    second_value = second(_factors(), second.development_fold_ids)

    assert first_value.objective_value == second_value.objective_value
    assert first_value.evaluated_fold_ids == second_value.evaluated_fold_ids


def test_the_evaluation_covers_exactly_the_requested_folds() -> None:
    evaluator = _evaluator()

    evaluation = evaluator(_factors(), evaluator.development_fold_ids)

    assert set(evaluation.evaluated_fold_ids) == set(evaluator.development_fold_ids)


def test_the_objective_equals_the_evaluation_machinery_run_directly() -> None:
    """The seam must not quietly rescale or reweight the frozen objective."""

    evaluator = _evaluator()
    factors = _factors()
    folds: tuple[EvaluationFold, ...] = evaluator._folds(factors.form_window)
    direct = evaluate_prepared_folds(
        folds,
        EvaluationConfig(
            optimization_config=type(CONFIG.optimization_config)(bench_weight=factors.bench_weight)
        ),
    )

    evaluation = evaluator(factors, evaluator.development_fold_ids)

    assert evaluation.objective_value == direct.summary.mean_realized_squad_points


def test_the_evaluation_carries_the_factor_translation_in_its_provenance() -> None:
    evaluator = _evaluator()

    provenance = evaluator(_factors(form_window=7), evaluator.development_fold_ids).provenance

    assert provenance["form_window"] == 7
    assert provenance["form_window_mapping_version"] == FORM_WINDOW_MAPPING_VERSION
    assert provenance["contract_version"] == PREDICTION_POLICY_EVALUATION_CONTRACT_VERSION
    assert provenance["development_seasons"] == (SEASON,)


def test_folds_are_reused_across_bench_weights_for_one_window() -> None:
    """Two bench weights must be scored on byte-identical projections."""

    evaluator = _evaluator()

    first = evaluator._folds(5)
    evaluator(_factors(bench_weight=0.0), evaluator.development_fold_ids)
    evaluator(_factors(bench_weight=0.3), evaluator.development_fold_ids)

    assert evaluator._folds(5) is first


# --- binding to the search --------------------------------------------------


def test_the_search_binding_accepts_this_evaluator() -> None:
    evaluator = _evaluator()

    bound = bind_policy_evaluator(evaluator)
    candidate = BayesianCandidate({"form_window": 5, "bench_weight": 0.1, "risk_aversion": 0.0})

    value = bound(candidate, evaluator.development_fold_ids)

    assert value == pytest.approx(
        evaluator(_factors(), evaluator.development_fold_ids).objective_value
    )
    assert bound.records[candidate.candidate_id].objective_value == value


def test_a_smoke_sweep_through_the_binding_is_deterministic() -> None:
    """The same candidate grid must produce the same trace twice, not merely finish.

    Driven through ``bind_policy_evaluator`` rather than ``run_bayesian_optimization``
    for the reason the next test records: a three-factor search space cannot pin
    ``risk_aversion``, so a real search cannot reach this evaluator today.
    """

    grid = tuple(
        BayesianCandidate({"form_window": window, "bench_weight": weight, "risk_aversion": 0.0})
        for window in (3, 4, 5)
        for weight in (0.0, 0.1)
    )

    def sweep() -> tuple[tuple[str, float], ...]:
        evaluator = _evaluator()
        bound = bind_policy_evaluator(evaluator)
        return tuple(
            (candidate.candidate_id, bound(candidate, evaluator.development_fold_ids))
            for candidate in grid
        )

    first, second = sweep(), sweep()

    assert first == second
    assert len(first) == len(grid)


def test_a_search_space_that_varies_risk_aversion_fails_loudly() -> None:
    """A search that moves ``risk_aversion`` hands this evaluator a nonzero value.

    It refuses rather than accepting-and-ignoring, because a flat axis in the search
    trace is the fake effect this evaluator exists to prevent. Pinning the factor is
    the supported alternative, tested below.
    """

    space = BayesianOptimizationConfig(
        factors=(
            BayesianFactor("form_window", 3, 5, 1, FactorKind.INTEGER),
            BayesianFactor("bench_weight", 0.0, 0.2, 0.1),
            BayesianFactor("risk_aversion", 0.0, 0.2, 0.1),
        ),
        evaluation_budget=4,
        initial_design_size=2,
    )
    evaluator = _evaluator()

    with pytest.raises(BayesianOptimizationExecutionError, match="risk_aversion"):
        run_bayesian_optimization(
            bind_policy_evaluator(evaluator),
            development_fold_ids=evaluator.development_fold_ids,
            config=space,
        )


def test_a_pinned_risk_aversion_lets_the_deterministic_evaluator_be_searched() -> None:
    """The seam gap closed: ``risk_aversion`` pinned at zero, the two real axes searched.

    The factor stays in the contract and in every trace record at exactly zero, so the
    search is honest about what it varied; and the search is deterministic end to end.
    """

    space = BayesianOptimizationConfig(
        factors=(
            BayesianFactor("form_window", 3, 5, 1, FactorKind.INTEGER),
            BayesianFactor("bench_weight", 0.0, 0.2, 0.1),
            BayesianFactor("risk_aversion", 0.0, 0.0, 0.1),
        ),
        evaluation_budget=4,
        initial_design_size=2,
    )
    evaluator = _evaluator()

    def search() -> tuple[tuple[str, float], ...]:
        result = run_bayesian_optimization(
            bind_policy_evaluator(evaluator),
            development_fold_ids=evaluator.development_fold_ids,
            config=space,
        )
        assert all(
            float(record.candidate.values["risk_aversion"]) == 0.0 for record in result.evaluations
        )
        return tuple(
            (record.candidate.candidate_id, record.objective_value) for record in result.evaluations
        )

    assert search() == search()
