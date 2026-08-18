"""Tests for hierarchical empirical scenarios and fixed-decision scoring."""

import json
from collections.abc import Mapping
from dataclasses import replace
from typing import Any

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
    ScenarioOptimizationConfig,
    ScenarioTarget,
    ScenarioValidationError,
    evaluate_fixed_decision,
    generate_scenarios,
    optimize_scenario_aware_squad,
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


def test_generated_scenarios_feed_the_scenario_aware_optimizer() -> None:
    snapshot = _snapshot()
    scenarios = generate_scenarios(
        snapshot,
        _residual_history(snapshot),
        TARGET,
        replace(SMALL_CONFIG, scenario_count=100),
    )

    result = optimize_scenario_aware_squad(
        scenarios,
        OptimizationConfig(),
        ScenarioOptimizationConfig(risk_aversion=0.25, tail_fraction=0.10),
    )

    assert result.solver_status.value == "OPTIMAL"
    assert result.scenario_fingerprint == scenarios.scenario_fingerprint
    assert result.scenario_evaluation is not None
    assert result.scenario_evaluation.metrics.scenario_count == 100
    assert result.diagnostics["decision_reoptimized_per_scenario"] is False


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


# --- calibration corrections and rival comparison -------------------------------------


def test_a_location_shift_moves_every_summary_and_leaves_the_projection_alone() -> None:
    snapshot = _snapshot()
    scenarios = generate_scenarios(snapshot, _residual_history(snapshot), TARGET, SMALL_CONFIG)
    decision = optimize_squad(snapshot.table, OptimizationConfig())

    plain = evaluate_fixed_decision(decision, scenarios)
    shifted = evaluate_fixed_decision(
        decision, scenarios, ScenarioEvaluationConfig(location_shift_points=-30.0)
    )

    assert shifted.metrics.mean_score == pytest.approx(plain.metrics.mean_score - 30.0)
    assert shifted.metrics.lower_quantile_score == pytest.approx(
        plain.metrics.lower_quantile_score - 30.0
    )
    assert shifted.metrics.point_projection_score == plain.metrics.point_projection_score
    assert shifted.metrics.probability_below_threshold >= plain.metrics.probability_below_threshold
    assert shifted.diagnostics["location_shift_points"] == -30.0
    assert shifted.diagnostics["mean_score_before_shift"] == pytest.approx(plain.metrics.mean_score)
    low, high = shifted.diagnostics["probability_below_threshold_interval"]  # type: ignore[misc]
    assert 0.0 <= low <= shifted.metrics.probability_below_threshold <= high <= 1.0
    with pytest.raises(ScenarioConfigurationError, match="finite"):
        ScenarioEvaluationConfig(location_shift_points=float("nan"))


def test_a_dispersion_scale_widens_the_spread_around_the_shifted_centre() -> None:
    snapshot = _snapshot()
    scenarios = generate_scenarios(snapshot, _residual_history(snapshot), TARGET, SMALL_CONFIG)
    decision = optimize_squad(snapshot.table, OptimizationConfig())

    plain = evaluate_fixed_decision(decision, scenarios)
    widened = evaluate_fixed_decision(
        decision,
        scenarios,
        ScenarioEvaluationConfig(location_shift_points=-30.0, dispersion_scale=1.5),
    )

    # The centre moves by the shift only; the spread scales; the tail widens.
    assert widened.metrics.mean_score == pytest.approx(plain.metrics.mean_score - 30.0)
    assert widened.metrics.score_standard_deviation == pytest.approx(
        1.5 * plain.metrics.score_standard_deviation
    )
    assert widened.metrics.lower_quantile_score == pytest.approx(
        plain.metrics.mean_score
        - 30.0
        + 1.5 * (plain.metrics.lower_quantile_score - plain.metrics.mean_score)
    )
    assert widened.diagnostics["dispersion_scale"] == 1.5
    assert widened.diagnostics["standard_deviation_before_scale"] == pytest.approx(
        plain.metrics.score_standard_deviation
    )
    assert plain.diagnostics["dispersion_scale"] == 1.0
    for bad in (0.0, -1.0, float("inf")):
        with pytest.raises(ScenarioConfigurationError, match="dispersion_scale"):
            ScenarioEvaluationConfig(dispersion_scale=bad)


def test_wilson_interval_narrows_with_more_scenarios_and_brackets_the_estimate() -> None:
    from squadopt.scenarios import wilson_interval

    small = wilson_interval(14, 100)
    large = wilson_interval(140, 1000)
    assert small[0] < 0.14 < small[1]
    assert large[0] < 0.14 < large[1]
    assert (large[1] - large[0]) < (small[1] - small[0])
    assert wilson_interval(0, 50)[0] == 0.0 and wilson_interval(50, 50)[1] == 1.0


def test_a_double_gameweek_scale_widens_only_the_doubles_and_needs_the_calendar() -> None:
    snapshot = _snapshot()
    history = _residual_history(snapshot)
    doubles = set(snapshot.table.loc[snapshot.table["team_id"] == 1, "player_id"].tolist())
    counts = {
        player_id: (2 if player_id in doubles else 1)
        for player_id in snapshot.table["player_id"].tolist()
    }
    plain = generate_scenarios(snapshot, history, TARGET, SMALL_CONFIG)
    scaled_config = replace(SMALL_CONFIG, double_gameweek_scale=1.5)
    scaled = generate_scenarios(snapshot, history, TARGET, scaled_config, fixture_counts=counts)

    assert scaled.diagnostics["double_gameweek_players"] == len(doubles)
    assert scaled.scenario_fingerprint != plain.scenario_fingerprint
    plain_sd = plain.scenario_points.std(ddof=0)
    scaled_sd = scaled.scenario_points.std(ddof=0)
    for player_id in snapshot.table["player_id"].tolist():
        if player_id in doubles:
            assert scaled_sd[player_id] > plain_sd[player_id]
        else:
            assert scaled_sd[player_id] == pytest.approx(plain_sd[player_id])
    # Means are (up to the empirical draws' own finite-sample mean) untouched: the
    # scale widens, it does not move.
    single_ids = [p for p in snapshot.table["player_id"].tolist() if p not in doubles]
    assert scaled.scenario_points[single_ids].mean().to_numpy() == pytest.approx(
        plain.scenario_points[single_ids].mean().to_numpy(), abs=1e-9
    )
    drift = (scaled.scenario_points.mean() - plain.scenario_points.mean()).abs().max()
    assert drift < 0.1
    with pytest.raises(ScenarioValidationError, match="fixture_counts"):
        generate_scenarios(snapshot, history, TARGET, scaled_config)


def test_a_rival_comparison_scores_both_squads_in_the_same_world() -> None:
    from squadopt.scenarios import RivalSquad, compare_fixed_decisions

    snapshot = _snapshot()
    scenarios = generate_scenarios(snapshot, _residual_history(snapshot), TARGET, SMALL_CONFIG)
    decision = optimize_squad(snapshot.table, OptimizationConfig())
    assert decision.captain is not None
    my_starters = decision.starting_xi["player_id"].tolist()
    my_captain = decision.captain["player_id"]

    # The same eleven and captain: never ahead, difference exactly zero.
    twin = RivalSquad("twin", tuple(my_starters), my_captain)
    same = compare_fixed_decisions(decision, twin, scenarios)
    assert same.probability_ahead == 0.0
    assert same.mean_difference == pytest.approx(0.0)
    assert same.shared_starters == 11
    assert same.diagnostics["location_shift_applied"] is False

    # A rival that captains a different starter: the difference is exactly the
    # captain swing, scenario by scenario, so shared players cancel.
    other = next(p for p in my_starters if p != my_captain)
    rival = RivalSquad("captain-swap", tuple(my_starters), other)
    swap = compare_fixed_decisions(decision, rival, scenarios)
    matrix = scenarios.scenario_points
    expected = (matrix[my_captain] - matrix[other]).to_numpy()
    assert swap.mean_difference == pytest.approx(float(expected.mean()))
    assert swap.probability_ahead == pytest.approx(float((expected > 0).mean()))
    low, high = swap.probability_ahead_interval
    assert low <= swap.probability_ahead <= high
    assert set(swap.difference_quantiles) == {"q10", "q25", "q50", "q75", "q90"}
    with pytest.raises(ScenarioValidationError, match="captain must be one"):
        RivalSquad("bad", tuple(my_starters), 999_999)


# --- rank-probability objective ---------------------------------------------------------


def _rank_world() -> tuple[Any, Any, Any]:
    from squadopt.scenarios import RivalSquad

    snapshot = _snapshot()
    # A modest scenario count: the big-M indicator model is a harder solve than the
    # CVaR one, and the tests want proven optima, not time-limited ones.
    scenarios = generate_scenarios(
        snapshot, _residual_history(snapshot), TARGET, replace(SMALL_CONFIG, scenario_count=96)
    )
    reference = optimize_squad(snapshot.table, OptimizationConfig())
    assert reference.captain is not None
    starters = tuple(reference.starting_xi["player_id"].tolist())
    rival = RivalSquad("template", starters, reference.captain["player_id"])
    return snapshot, scenarios, (reference, rival)


def test_against_its_own_template_the_rank_objective_finds_a_differential_and_reports_it() -> None:
    from squadopt.scenarios import RankObjectiveConfig, optimize_rank_probability_squad

    _, scenarios, (_reference, rival) = _rank_world()

    result = optimize_rank_probability_squad(scenarios, rival, OptimizationConfig())

    assert result.has_solution
    assert result.probability_ahead is not None and 0.0 <= result.probability_ahead <= 1.0
    # The template itself is never ahead of itself; the optimizer must do at least as well.
    assert result.probability_ahead > 0.0
    low, high = result.probability_ahead_interval  # type: ignore[misc]
    assert low <= result.probability_ahead <= high
    assert result.comparison is not None
    assert result.comparison.probability_ahead == pytest.approx(result.probability_ahead)
    chosen = result.optimization_result
    assert len(chosen.selected_squad) == OptimizationConfig().squad_size
    assert result.diagnostics["ahead_count"] == round(result.probability_ahead * 96)
    assert result.diagnostics["ahead_count_from_indicators"] == result.diagnostics["ahead_count"]
    # A margin no squad can clear leaves every indicator at zero.
    hopeless = optimize_rank_probability_squad(
        scenarios, rival, OptimizationConfig(), RankObjectiveConfig(margin_points=10_000.0)
    )
    assert hopeless.probability_ahead == 0.0


def test_the_expected_points_budget_binds_and_a_menu_is_monotone_in_the_budget() -> None:
    from squadopt.scenarios import RankObjectiveConfig, goal_menu, optimize_rank_probability_squad

    _, scenarios, (reference, rival) = _rank_world()
    with pytest.raises(ScenarioConfigurationError, match="reference_expected_points"):
        optimize_rank_probability_squad(
            scenarios, rival, OptimizationConfig(), RankObjectiveConfig(expected_points_budget=1.0)
        )

    menu = goal_menu(
        scenarios, rival, reference, OptimizationConfig(), budgets=(0.0, 0.5, 2.0, None)
    )
    entries = [entry for entry, _ in menu]
    assert [e.expected_points_budget for e in entries] == [0.0, 0.5, 2.0, None]
    probabilities = [e.probability_ahead for e in entries]
    costs = [e.expected_points_cost for e in entries]
    assert all(p is not None for p in probabilities)
    # More budget can only widen the feasible set: among proven optima, probability
    # ahead never falls with the budget.
    proven = [e.probability_ahead for e in entries if e.solver_status == "OPTIMAL"]
    assert proven == sorted(proven)  # type: ignore[type-var]
    assert len(proven) >= 2
    # And each cost respects its budget (the unconstrained entry has no cap).
    for entry in entries[:-1]:
        assert entry.expected_points_cost is not None and entry.expected_points_budget is not None
        assert entry.expected_points_cost <= entry.expected_points_budget + 1e-6
    assert all(cost is not None for cost in costs)
    assert all(e.solver_status in {"OPTIMAL", "FEASIBLE"} for e in entries)


def test_the_rank_objective_is_deterministic() -> None:
    from squadopt.scenarios import optimize_rank_probability_squad

    _, scenarios, (_, rival) = _rank_world()
    first = optimize_rank_probability_squad(scenarios, rival, OptimizationConfig())
    second = optimize_rank_probability_squad(scenarios, rival, OptimizationConfig())
    assert first.probability_ahead == second.probability_ahead
    assert first.optimization_result.selected_squad["player_id"].tolist() == (
        second.optimization_result.selected_squad["player_id"].tolist()
    )


def test_a_held_out_claim_is_read_from_scenarios_the_squad_never_saw() -> None:
    from squadopt.scenarios import RankObjectiveConfig, optimize_rank_probability_squad

    _, scenarios, (_reference, rival) = _rank_world()
    with pytest.raises(ScenarioConfigurationError, match="claim_scenarios"):
        RankObjectiveConfig(claim_scenarios="all")

    held_out = optimize_rank_probability_squad(
        scenarios, rival, OptimizationConfig(), RankObjectiveConfig(claim_scenarios="held_out_half")
    )
    assert held_out.has_solution
    assert held_out.diagnostics["selection_scenario_count"] == 48
    assert held_out.diagnostics["claim_scenario_count"] == 48
    assert held_out.probability_ahead is not None
    # The reported probability is the claim-half frequency; the selection-half one is
    # kept as a diagnostic, and the two are read from the same chosen squad.
    claim = held_out.diagnostics["claim_ahead_count"]
    assert held_out.probability_ahead == pytest.approx(claim / 48)  # type: ignore[operator]
    assert held_out.diagnostics["ahead_count"] == round(
        held_out.diagnostics["selection_probability_ahead"] * 48  # type: ignore[operator]
    )
    assert (
        held_out.diagnostics["ahead_count_from_indicators"] == held_out.diagnostics["ahead_count"]
    )
    low, high = held_out.probability_ahead_interval  # type: ignore[misc]
    assert low <= held_out.probability_ahead <= high
    # No in-sample comparison object is attached to a held-out claim.
    assert held_out.comparison is None
    # The lexicographic phases are recorded.
    assert held_out.diagnostics["secondary_attempted"] is True
    assert held_out.diagnostics["claim_scenarios"] == "held_out_half"
