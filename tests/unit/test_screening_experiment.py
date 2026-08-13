"""Integration tests for development screening and locked holdout separation."""

from dataclasses import replace

import pytest
from pandas.testing import assert_frame_equal
from tests.fixtures.synthetic_gameweeks import (
    PREVIOUS_SEASON,
    SEASON,
    make_two_season_gameweeks,
)

from squadopt import OptimizationConfig
from squadopt.backtest import build_walk_forward_folds, make_baseline_projection_builder
from squadopt.experiments import (
    ExperimentCandidate,
    ExperimentExecutionError,
    FrozenCandidateError,
    PromotionPolicy,
    ScreeningExperimentConfig,
    ScreeningExperimentResult,
    freeze_screening_candidate,
    run_frozen_holdout,
    run_screening_experiment,
)
from squadopt.experiments.runner import _build_cached_projection_folds


@pytest.fixture(scope="module")
def screening_config() -> ScreeningExperimentConfig:
    return ScreeningExperimentConfig(
        development_seasons=(PREVIOUS_SEASON,),
        holdout_seasons=(SEASON,),
        promotion_policy=PromotionPolicy(bootstrap_resamples=100),
    )


@pytest.fixture(scope="module")
def screening_result(
    screening_config: ScreeningExperimentConfig,
) -> ScreeningExperimentResult:
    panel = make_two_season_gameweeks()
    original = panel.copy(deep=True)
    result = run_screening_experiment(panel, screening_config)
    assert_frame_equal(panel, original)
    return result


def test_screening_runs_all_twelve_cells_on_identical_development_folds(
    screening_result: ScreeningExperimentResult,
) -> None:
    assert len(screening_result.assessments) == 12
    fold_orders = {
        tuple(fold.fold_id for fold in assessment.evaluation.folds)
        for assessment in screening_result.assessments
    }
    assert len(fold_orders) == 1
    assert {
        fold.metadata["season"]
        for assessment in screening_result.assessments
        for fold in assessment.evaluation.folds
    } == {PREVIOUS_SEASON}
    assert screening_result.diagnostics["holdout_seasons_accessed"] is False


def test_projection_tables_are_cached_once_per_form_window(
    screening_result: ScreeningExperimentResult,
) -> None:
    assert screening_result.diagnostics["projection_cache_entries"] == 4
    assert screening_result.diagnostics["candidate_count"] == 12
    assert screening_result.diagnostics["optimized_candidate_cells"] <= 12


@pytest.mark.parametrize("evaluation_season", [PREVIOUS_SEASON, SEASON])
def test_full_visible_season_feature_cache_matches_truncated_walk_forward_folds(
    evaluation_season: str,
) -> None:
    panel = make_two_season_gameweeks()
    config = ScreeningExperimentConfig(
        development_seasons=(PREVIOUS_SEASON,),
        holdout_seasons=(SEASON,),
        form_windows=(3,),
        bench_weights=(0.1,),
        control=ExperimentCandidate(3, 0.1),
        promotion_policy=PromotionPolicy(bootstrap_resamples=20),
    )
    cached = _build_cached_projection_folds(
        panel,
        config,
        form_window=3,
        seasons=(evaluation_season,),
    )
    reference = build_walk_forward_folds(
        panel,
        seasons=(evaluation_season,),
        min_prior_gameweeks_in_season=1,
        projection_builder=make_baseline_projection_builder(form_window=3),
    )

    assert [fold.fold_id for fold in cached] == [fold.fold_id for fold in reference]
    for cached_fold, reference_fold in zip(cached, reference, strict=True):
        assert_frame_equal(cached_fold.projections, reference_fold.projections)
        assert_frame_equal(cached_fold.realized_points, reference_fold.realized_points)


def test_development_screening_is_invariant_to_holdout_outcomes() -> None:
    panel = make_two_season_gameweeks()
    config = ScreeningExperimentConfig(
        development_seasons=(PREVIOUS_SEASON,),
        holdout_seasons=(SEASON,),
        form_windows=(5,),
        bench_weights=(0.1,),
        promotion_policy=PromotionPolicy(bootstrap_resamples=20),
    )
    changed = panel.copy(deep=True)
    holdout_rows = changed["season"] == SEASON
    changed.loc[holdout_rows, "minutes"] = 0
    changed.loc[holdout_rows, "total_points"] = 999
    changed.loc[holdout_rows, "price_tenths"] += 100

    first = run_screening_experiment(panel, config)
    second = run_screening_experiment(changed, config)

    assert first.screening_fingerprint == second.screening_fingerprint


def test_holdout_must_follow_development_in_the_panel() -> None:
    config = ScreeningExperimentConfig(
        development_seasons=(SEASON,),
        holdout_seasons=(PREVIOUS_SEASON,),
        form_windows=(5,),
        bench_weights=(0.1,),
        promotion_policy=PromotionPolicy(bootstrap_resamples=20),
    )

    with pytest.raises(ExperimentExecutionError, match="must follow"):
        run_screening_experiment(make_two_season_gameweeks(), config)


def test_screening_reports_effects_and_a_stable_frozen_decision(
    screening_result: ScreeningExperimentResult,
) -> None:
    assert len(screening_result.main_effects) == 7
    assert len(screening_result.interactions) == 12
    assert screening_result.selected_candidate in screening_result.config.candidates
    assert len(screening_result.screening_fingerprint) == 64

    frozen = freeze_screening_candidate(screening_result)
    assert frozen.candidate == screening_result.selected_candidate
    assert frozen.screening_fingerprint == screening_result.screening_fingerprint


def test_locked_holdout_requires_the_frozen_candidate(
    screening_result: ScreeningExperimentResult,
    screening_config: ScreeningExperimentConfig,
) -> None:
    frozen = freeze_screening_candidate(screening_result)
    result = run_frozen_holdout(make_two_season_gameweeks(), frozen, screening_config)

    assert {fold.metadata["season"] for fold in result.candidate_assessment.evaluation.folds} == {
        SEASON
    }
    assert result.diagnostics["development_seasons_accessed"] is False
    assert result.candidate_assessment.comparison.control_id == frozen.control.candidate_id


def test_changed_design_cannot_reuse_a_frozen_candidate(
    screening_result: ScreeningExperimentResult,
    screening_config: ScreeningExperimentConfig,
) -> None:
    frozen = freeze_screening_candidate(screening_result)
    changed = replace(
        screening_config,
        promotion_policy=replace(
            screening_config.promotion_policy,
            bootstrap_resamples=101,
        ),
    )

    with pytest.raises(FrozenCandidateError, match="does not match"):
        run_frozen_holdout(make_two_season_gameweeks(), frozen, changed)


def test_coefficient_equivalent_bench_weights_reuse_solver_results() -> None:
    config = ScreeningExperimentConfig(
        development_seasons=(PREVIOUS_SEASON,),
        holdout_seasons=(SEASON,),
        form_windows=(5,),
        bench_weights=(0.0, 0.0001),
        control=ExperimentCandidate(5, 0.0),
        optimization_config=OptimizationConfig(expected_points_scale=1),
        promotion_policy=PromotionPolicy(bootstrap_resamples=20),
    )

    result = run_screening_experiment(make_two_season_gameweeks(), config)

    assert result.diagnostics["coefficient_equivalent_cells_reused"] == 1
    equivalent = next(item for item in result.assessments if item.equivalent_to is not None)
    assert equivalent.evaluation.diagnostics["solve_reused"] is True
    assert all(
        fold.optimization_result.diagnostics["solve_reused"] is True
        for fold in equivalent.evaluation.folds
    )
