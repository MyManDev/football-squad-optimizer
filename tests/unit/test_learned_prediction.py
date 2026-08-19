"""Tests for the deterministic Ridge reference and paired benchmark."""

import json
from dataclasses import replace

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal
from tests.fixtures.synthetic_gameweeks import (
    PREVIOUS_SEASON,
    SEASON,
    make_two_season_gameweeks,
)

from squadopt.backtest import (
    BacktestConfigurationError,
    DecisionPoint,
    LearnedBenchmarkConfig,
    build_ridge_prediction_snapshot,
    build_walk_forward_fold,
    learned_benchmark_to_dict,
    learned_benchmark_to_markdown,
    make_ridge_projection_builder,
    rows_through,
    run_learned_benchmark,
)
from squadopt.features import CrossSeasonConfig, build_feature_dataset
from squadopt.prediction import (
    PredictionConfigurationError,
    RidgeProjectionConfig,
    fit_ridge_predictor,
    predict_ridge_expected_points,
)
from squadopt.prediction.factors import FormWindowMapping

DECISION = DecisionPoint(SEASON, 6)


def _snapshot(panel: pd.DataFrame | None = None) -> object:
    source = make_two_season_gameweeks() if panel is None else panel
    visible = rows_through(source, DECISION)
    return build_ridge_prediction_snapshot(visible, DECISION)


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"alpha": 0.0}, "positive"),
        ({"alpha": float("nan")}, "positive"),
        ({"form_window": 0}, "at least 1"),
        ({"min_training_rows": 1}, "at least 2"),
        ({"min_training_rows": True}, "integer"),
    ],
)
def test_invalid_ridge_config_is_rejected(change: dict[str, object], message: str) -> None:
    with pytest.raises(PredictionConfigurationError, match=message):
        RidgeProjectionConfig(**change)  # type: ignore[arg-type]


def test_ridge_snapshot_is_optimizer_ready_and_carries_provenance() -> None:
    snapshot = _snapshot()

    assert snapshot.table.columns.tolist() == [
        "player_id",
        "name",
        "team_id",
        "position",
        "price_tenths",
        "expected_points",
    ]
    assert len(snapshot.table) == 36
    assert snapshot.table["expected_points"].ge(0.0).all()
    assert snapshot.provenance.model_name == "squadopt-ridge-reference"
    assert snapshot.provenance.training_cutoff == f"{SEASON}:GW05"
    assert snapshot.diagnostics["training_rows"] == 13 * 36
    assert len(str(snapshot.diagnostics["model_fingerprint"])) == 64


def test_ridge_snapshot_does_not_mutate_the_visible_panel() -> None:
    panel = make_two_season_gameweeks()
    visible = rows_through(panel, DECISION)
    before = visible.copy(deep=True)

    snapshot = build_ridge_prediction_snapshot(visible, DECISION)
    snapshot.table.loc[0, "expected_points"] = 999.0

    assert_frame_equal(visible, before)


def test_ridge_prediction_is_deterministic_across_runs_and_row_order() -> None:
    panel = make_two_season_gameweeks()
    first = _snapshot(panel)
    shuffled = panel.sample(frac=1.0, random_state=91).reset_index(drop=True)
    second = _snapshot(shuffled)

    assert_frame_equal(first.table, second.table)
    assert first.prediction_fingerprint == second.prediction_fingerprint
    assert first.diagnostics["model_fingerprint"] == second.diagnostics["model_fingerprint"]


@pytest.mark.parametrize("column", ["total_points", "minutes"])
def test_target_gameweek_outcome_cannot_change_its_prediction(column: str) -> None:
    panel = make_two_season_gameweeks()
    baseline = _snapshot(panel)
    changed = panel.copy(deep=True)
    mask = (changed["season"] == SEASON) & (changed["gameweek"] == DECISION.gameweek)
    changed.loc[mask, column] = changed.loc[mask, column] + 1_000

    rebuilt = _snapshot(changed)

    assert_frame_equal(rebuilt.table, baseline.table)
    assert rebuilt.prediction_fingerprint == baseline.prediction_fingerprint


def test_future_outcomes_never_reach_the_ridge_builder() -> None:
    panel = make_two_season_gameweeks()
    builder = make_ridge_projection_builder()
    baseline = build_walk_forward_fold(panel, DECISION, projection_builder=builder)
    changed = panel.copy(deep=True)
    future = (changed["season"] == SEASON) & (changed["gameweek"] > DECISION.gameweek)
    changed.loc[future, "total_points"] = 10_000

    rebuilt = build_walk_forward_fold(
        changed,
        DECISION,
        projection_builder=make_ridge_projection_builder(),
    )

    assert_frame_equal(rebuilt.projections, baseline.projections)


def test_cached_chronological_builder_matches_uncached_snapshot() -> None:
    panel = make_two_season_gameweeks()
    builder = make_ridge_projection_builder()
    cached = None
    for gameweek in range(2, DECISION.gameweek + 1):
        decision = DecisionPoint(SEASON, gameweek)
        cached = builder(rows_through(panel, decision), decision)

    uncached = _snapshot(panel)

    assert cached is not None
    assert_frame_equal(cached.table, uncached.table)
    assert cached.prediction_fingerprint == uncached.prediction_fingerprint
    assert cached.diagnostics["model_fingerprint"] == uncached.diagnostics["model_fingerprint"]


def test_fit_and_predict_inputs_are_not_mutated() -> None:
    panel = make_two_season_gameweeks()
    mapping = FormWindowMapping(form_window=5)
    features = build_feature_dataset(
        rows_through(panel, DECISION),
        config=mapping.feature_config,
        cross_season=CrossSeasonConfig(),
    )
    training = features.loc[
        ~((features["season"] == SEASON) & (features["gameweek"] == DECISION.gameweek))
    ].copy(deep=True)
    target = features.loc[
        (features["season"] == SEASON) & (features["gameweek"] == DECISION.gameweek)
    ].copy(deep=True)
    training_before = training.copy(deep=True)
    target_before = target.copy(deep=True)

    model = fit_ridge_predictor(training)
    predict_ridge_expected_points(target, model)

    assert_frame_equal(training, training_before)
    assert_frame_equal(target, target_before)


def test_negative_raw_ridge_predictions_are_floored_at_zero() -> None:
    panel = make_two_season_gameweeks()
    mapping = FormWindowMapping(form_window=5)
    features = build_feature_dataset(
        panel.loc[panel["season"] == PREVIOUS_SEASON].copy(),
        config=mapping.feature_config,
        cross_season=CrossSeasonConfig(min_minutes=0),
    )
    training = features.assign(total_points=-10)

    model = fit_ridge_predictor(training, RidgeProjectionConfig(min_training_rows=20))
    predicted = predict_ridge_expected_points(features.iloc[:10], model)

    assert predicted.eq(0.0).all()


def test_changing_training_data_changes_its_fingerprint() -> None:
    panel = make_two_season_gameweeks()
    original = _snapshot(panel)
    changed = panel.copy(deep=True)
    mask = (changed["season"] == PREVIOUS_SEASON) & (changed["gameweek"] == 2)
    changed.loc[mask, "total_points"] = changed.loc[mask, "total_points"] + 1

    rebuilt = _snapshot(changed)

    assert (
        rebuilt.provenance.training_data_fingerprint
        != original.provenance.training_data_fingerprint
    )
    assert rebuilt.diagnostics["model_fingerprint"] != original.diagnostics["model_fingerprint"]


def test_locked_holdout_is_rejected_by_the_development_benchmark() -> None:
    with pytest.raises(BacktestConfigurationError, match="locked holdout"):
        LearnedBenchmarkConfig(seasons=(SEASON,))


def test_paired_benchmark_returns_prediction_decision_and_residual_contracts() -> None:
    panel = make_two_season_gameweeks()
    config = LearnedBenchmarkConfig(
        seasons=(PREVIOUS_SEASON,),
        ridge_config=RidgeProjectionConfig(min_training_rows=20),
    )
    before = panel.copy(deep=True)

    result = run_learned_benchmark(panel, config)

    assert result.decision_metrics.folds == 7
    assert result.decision_metrics.comparable_scored_folds == 7
    assert result.baseline_prediction_metrics.observations == 7 * 36
    assert result.learned_prediction_metrics.observations == 7 * 36
    assert len(result.learned_prediction_metrics.by_position) == 4
    assert len(result.residuals) == 7 * 36
    assert result.residuals["residual"].equals(
        result.residuals["realized_points"] - result.residuals["predicted_points"]
    )
    assert result.diagnostics["automatic_promotion"] is False
    assert result.diagnostics["holdout_accessed"] is False
    assert_frame_equal(panel, before)


def test_learned_benchmark_reports_are_json_safe_and_explicitly_non_promoting() -> None:
    result = run_learned_benchmark(
        make_two_season_gameweeks(),
        LearnedBenchmarkConfig(
            seasons=(PREVIOUS_SEASON,),
            ridge_config=RidgeProjectionConfig(min_training_rows=20),
        ),
    )

    report = learned_benchmark_to_dict(result)
    markdown = learned_benchmark_to_markdown(result)

    assert json.loads(json.dumps(report))["decision"]["automatic_promotion"] is False
    assert report["decision"]["holdout_accessed"] is False
    assert len(report["folds"]) == 7
    assert "No automatic promotion" in markdown
    assert "locked holdout was not accessed" in markdown


def test_fitted_model_rejects_tampered_state() -> None:
    snapshot = _snapshot()
    assert snapshot.diagnostics["training_rows"] > 0
    panel = make_two_season_gameweeks()
    mapping = FormWindowMapping(form_window=5)
    features = build_feature_dataset(
        panel,
        config=mapping.feature_config,
        cross_season=CrossSeasonConfig(),
    )
    model = fit_ridge_predictor(features)

    with pytest.raises(PredictionConfigurationError, match="does not match"):
        replace(model, model_fingerprint="b" * 64)
