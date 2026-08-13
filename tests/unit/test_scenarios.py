"""Tests for hierarchical empirical scenarios and fixed-decision scoring."""

import json
from collections.abc import Mapping
from dataclasses import replace

import numpy as np
import pandas as pd
import pytest
from pandas.testing import assert_frame_equal
from tests.fixtures.synthetic_gameweeks import SEASON, make_canonical_gameweeks

from squadopt.backtest import DecisionPoint, baseline_projection_builder, rows_through
from squadopt.optimization import OptimizationConfig, optimize_squad
from squadopt.prediction import (
    PredictionProvenance,
    PredictionSnapshot,
    prepare_optimizer_projection,
)
from squadopt.scenarios import (
    ScenarioConfig,
    ScenarioConfigurationError,
    ScenarioEvaluationConfig,
    ScenarioTarget,
    ScenarioValidationError,
    evaluate_fixed_decision,
    generate_scenarios,
    scenario_result_to_dict,
    scenario_result_to_markdown,
)

TARGET = ScenarioTarget(SEASON, 8)
SMALL_CONFIG = ScenarioConfig(
    scenario_count=500,
    deterministic_seed=19,
    min_history_folds=5,
    min_player_observations=3,
    player_scale_shrinkage=4.0,
)


def _snapshot() -> PredictionSnapshot:
    panel = make_canonical_gameweeks()
    decision = DecisionPoint(SEASON, TARGET.gameweek)
    projection = baseline_projection_builder(rows_through(panel, decision), decision)
    provenance = PredictionProvenance(
        model_name="synthetic-scenario-model",
        model_version="1.0.0",
        feature_contract_version="synthetic-scenario-features-v1",
        training_cutoff=f"{SEASON}:GW07",
        training_data_fingerprint="a" * 64,
    )
    return prepare_optimizer_projection(
        projection.drop(columns="expected_points"),
        projection.loc[:, ["player_id", "expected_points"]],
        provenance,
    )


def _residual_history(snapshot: PredictionSnapshot | None = None) -> pd.DataFrame:
    projection = _snapshot() if snapshot is None else snapshot
    position_effect = {"GK": -0.3, "DEF": -0.1, "MID": 0.1, "FWD": 0.3}
    common_effects = {2: -4.0, 3: -2.0, 4: 0.0, 5: 2.0, 6: 4.0}
    records: list[dict[str, object]] = []
    for gameweek, common in common_effects.items():
        for row in projection.table.itertuples(index=False):
            team_effect = ((int(row.team_id) * 3 + gameweek) % 7 - 3) * 0.7
            player_effect = ((int(row.player_id) + gameweek * 2) % 5 - 2) * 0.2
            residual = common + team_effect + position_effect[str(row.position)] + player_effect
            predicted = float(row.expected_points)
            records.append(
                {
                    "fold_id": f"{SEASON}-gw{gameweek:02d}",
                    "season": SEASON,
                    "gameweek": gameweek,
                    "player_id": row.player_id,
                    "team_id": row.team_id,
                    "position": row.position,
                    "predicted_points": predicted,
                    "realized_points": predicted + residual,
                    "residual": residual,
                }
            )
    return pd.DataFrame.from_records(records)


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"scenario_count": 0}, "at least 1"),
        ({"deterministic_seed": -1}, "at least 0"),
        ({"min_history_folds": 1}, "at least 2"),
        ({"min_player_observations": True}, "integer"),
        ({"player_scale_shrinkage": -1.0}, "non-negative"),
    ],
)
def test_invalid_scenario_config_is_rejected(change: dict[str, object], message: str) -> None:
    with pytest.raises(ScenarioConfigurationError, match=message):
        ScenarioConfig(**change)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"lower_quantile": 0.0}, "strictly between"),
        ({"worst_fraction": 1.0}, "strictly between"),
        ({"points_threshold": float("nan")}, "finite"),
    ],
)
def test_invalid_evaluation_config_is_rejected(change: dict[str, object], message: str) -> None:
    with pytest.raises(ScenarioConfigurationError, match=message):
        ScenarioEvaluationConfig(**change)  # type: ignore[arg-type]


def test_scenarios_are_exact_aligned_and_keep_point_projection_unchanged() -> None:
    snapshot = _snapshot()
    original = snapshot.table.copy(deep=True)

    result = generate_scenarios(snapshot, _residual_history(snapshot), TARGET, SMALL_CONFIG)

    assert result.scenario_points.shape == (500, len(snapshot.table))
    assert result.scenario_points.columns.tolist() == snapshot.table["player_id"].tolist()
    assert result.scenario_points.index.tolist() == list(result.scenario_ids)
    assert len(result.source_fold_ids) == 500
    assert len(result.scenario_fingerprint) == 64
    assert result.diagnostics["point_projection_changed"] is False
    assert_frame_equal(snapshot.table, original)


def test_same_seed_and_content_produce_identical_scenarios_and_fingerprint() -> None:
    snapshot = _snapshot()
    history = _residual_history(snapshot)

    first = generate_scenarios(snapshot, history, TARGET, SMALL_CONFIG)
    second = generate_scenarios(
        snapshot,
        history.sample(frac=1.0, random_state=3).reset_index(drop=True),
        TARGET,
        SMALL_CONFIG,
    )

    assert_frame_equal(first.scenario_points, second.scenario_points)
    assert first.source_fold_ids == second.source_fold_ids
    assert first.scenario_fingerprint == second.scenario_fingerprint


def test_different_seed_changes_scenarios_and_fingerprint() -> None:
    snapshot = _snapshot()
    history = _residual_history(snapshot)

    first = generate_scenarios(snapshot, history, TARGET, SMALL_CONFIG)
    second = generate_scenarios(
        snapshot,
        history,
        TARGET,
        replace(SMALL_CONFIG, deterministic_seed=20),
    )

    assert not first.scenario_points.equals(second.scenario_points)
    assert first.scenario_fingerprint != second.scenario_fingerprint


def test_residual_history_inputs_are_not_mutated() -> None:
    snapshot = _snapshot()
    history = _residual_history(snapshot)
    before = history.copy(deep=True)

    generate_scenarios(snapshot, history, TARGET, SMALL_CONFIG)

    assert_frame_equal(history, before)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda frame: frame.drop(columns="residual"), "missing columns"),
        (
            lambda frame: pd.concat([frame, frame.iloc[[0]]], ignore_index=True),
            "at most one row",
        ),
        (lambda frame: frame.assign(position="INVALID"), "positions"),
        (lambda frame: frame.assign(player_id=frame["player_id"].astype(str)), "types must match"),
        (lambda frame: frame.assign(residual=frame["residual"] + 1.0), "must equal"),
    ],
)
def test_invalid_residual_history_is_rejected(mutation: object, message: str) -> None:
    snapshot = _snapshot()
    transform = mutation
    assert callable(transform)

    with pytest.raises(ScenarioValidationError, match=message):
        generate_scenarios(snapshot, transform(_residual_history(snapshot)), TARGET, SMALL_CONFIG)


def test_target_or_future_residuals_are_rejected() -> None:
    snapshot = _snapshot()
    history = _residual_history(snapshot)
    target_rows = history.loc[history["gameweek"] == 6].assign(
        fold_id=f"{SEASON}-gw08",
        gameweek=8,
    )

    with pytest.raises(ScenarioValidationError, match="strictly before"):
        generate_scenarios(
            snapshot,
            pd.concat([history, target_rows], ignore_index=True),
            TARGET,
            SMALL_CONFIG,
        )


def test_insufficient_historical_folds_are_rejected() -> None:
    snapshot = _snapshot()
    history = _residual_history(snapshot)
    too_short = history.loc[history["gameweek"].isin([2, 3])].reset_index(drop=True)

    with pytest.raises(ScenarioValidationError, match="at least 5"):
        generate_scenarios(snapshot, too_short, TARGET, SMALL_CONFIG)


def test_same_team_players_receive_stronger_shared_dependence_than_cross_team_players() -> None:
    snapshot = _snapshot()
    config = replace(SMALL_CONFIG, scenario_count=4_000)
    result = generate_scenarios(snapshot, _residual_history(snapshot), TARGET, config)
    table = snapshot.table.reset_index(drop=True)
    first_team = table.iloc[0]["team_id"]
    same_team_columns = table.index[table["team_id"] == first_team].tolist()[:2]
    cross_team_column = int(table.index[table["team_id"] != first_team][0])
    shocks = result.scenario_points.to_numpy() - table["expected_points"].to_numpy()

    same_correlation = float(
        np.corrcoef(shocks[:, same_team_columns[0]], shocks[:, same_team_columns[1]])[0, 1]
    )
    cross_correlation = float(
        np.corrcoef(shocks[:, same_team_columns[0]], shocks[:, cross_team_column])[0, 1]
    )

    assert same_correlation > cross_correlation
    assert same_correlation > 0.2


def test_unseen_player_uses_position_fallback() -> None:
    snapshot = _snapshot()
    history = _residual_history(snapshot)
    unseen_id = snapshot.table.iloc[0]["player_id"]
    history = history.loc[history["player_id"] != unseen_id].reset_index(drop=True)

    result = generate_scenarios(snapshot, history, TARGET, SMALL_CONFIG)

    counts = result.diagnostics["idiosyncratic_fallback_counts"]
    assert isinstance(counts, Mapping)
    assert counts["position"] >= 1


def test_negative_scenario_points_are_allowed_and_fingerprinted() -> None:
    snapshot = _snapshot()
    history = _residual_history(snapshot)
    history.loc[history["gameweek"] == 2, "realized_points"] -= 50.0
    history["residual"] = history["realized_points"] - history["predicted_points"]
    result = generate_scenarios(
        snapshot,
        history,
        TARGET,
        replace(SMALL_CONFIG, scenario_count=2_000),
    )

    assert bool((result.scenario_points < 0.0).any().any())
    assert result.diagnostics["negative_scenario_points_allowed"] is True


def test_tampering_with_scenario_values_invalidates_the_fingerprint() -> None:
    result = generate_scenarios(_snapshot(), _residual_history(), TARGET, SMALL_CONFIG)
    changed = result.scenario_points.copy(deep=True)
    changed.iloc[0, 0] += 1.0

    with pytest.raises(ScenarioValidationError, match="does not match"):
        replace(result, scenario_points=changed)


def test_fixed_decision_score_matches_manual_starting_xi_and_double_captain() -> None:
    snapshot = _snapshot()
    scenarios = generate_scenarios(snapshot, _residual_history(snapshot), TARGET, SMALL_CONFIG)
    decision = optimize_squad(snapshot.table, OptimizationConfig())

    result = evaluate_fixed_decision(decision, scenarios)

    assert decision.captain is not None
    first = scenarios.scenario_points.iloc[0]
    manual = float(first.loc[decision.starting_xi["player_id"].tolist()].sum())
    manual += float(first.loc[decision.captain["player_id"]])
    assert result.scenario_scores[0] == pytest.approx(manual)
    assert result.metrics.scenario_count == SMALL_CONFIG.scenario_count
    assert result.metrics.minimum_score == min(result.scenario_scores)
    assert result.diagnostics["decision_reoptimized_per_scenario"] is False
    assert result.diagnostics["bench_points_included"] is False


def test_fixed_decision_metrics_follow_declared_quantile_worst_and_threshold_rules() -> None:
    snapshot = _snapshot()
    scenarios = generate_scenarios(snapshot, _residual_history(snapshot), TARGET, SMALL_CONFIG)
    decision = optimize_squad(snapshot.table, OptimizationConfig())
    config = ScenarioEvaluationConfig(
        lower_quantile=0.2,
        worst_fraction=0.15,
        points_threshold=45.0,
    )

    result = evaluate_fixed_decision(decision, scenarios, config)
    scores = np.asarray(result.scenario_scores)
    worst_count = int(np.ceil(0.15 * len(scores)))

    assert result.metrics.lower_quantile_score == pytest.approx(
        np.quantile(scores, 0.2, method="linear")
    )
    assert result.metrics.worst_fraction_count == worst_count
    assert result.metrics.mean_worst_fraction_score == pytest.approx(
        np.sort(scores)[:worst_count].mean()
    )
    assert result.metrics.probability_below_threshold == pytest.approx((scores < 45.0).mean())


def test_scenario_reports_are_json_safe_and_explicitly_fixed_decision() -> None:
    snapshot = _snapshot()
    scenarios = generate_scenarios(snapshot, _residual_history(snapshot), TARGET, SMALL_CONFIG)
    decision = optimize_squad(snapshot.table, OptimizationConfig())
    evaluation = evaluate_fixed_decision(decision, scenarios)

    report = scenario_result_to_dict(scenarios, evaluation)
    markdown = scenario_result_to_markdown(scenarios, evaluation)

    encoded = json.loads(json.dumps(report))
    assert encoded["evaluation_diagnostics"]["decision_reoptimized_per_scenario"] is False
    assert encoded["history"]["folds"] == 5
    assert "no scenario reoptimization" in markdown
    assert "No CVaR" in markdown
