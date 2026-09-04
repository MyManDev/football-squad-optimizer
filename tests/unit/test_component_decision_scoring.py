"""Tests for official-rules scoring across component scenarios."""

from dataclasses import replace

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

from squadopt.evaluation import EvaluationValidationError
from squadopt.optimization import OptimizationResult, SolverStatus
from squadopt.prediction import PredictionProvenance, prepare_optimizer_projection
from squadopt.scenarios import (
    ScenarioConfig,
    ScenarioSet,
    ScenarioTarget,
    ScenarioValidationError,
    score_component_scenario_decision,
)
from squadopt.scenarios.components import (
    ComponentScenarioDraw,
    ComponentScenarioInputs,
    ComponentScenarioProvenance,
    _component_fingerprint,
)
from squadopt.scenarios.models import _scenario_fingerprint

TARGET = ScenarioTarget("2026-27", 3)


def _optimization_result() -> OptimizationResult:
    positions = {
        1: "GK",
        2: "GK",
        3: "DEF",
        4: "DEF",
        5: "DEF",
        6: "DEF",
        7: "DEF",
        8: "MID",
        9: "MID",
        10: "MID",
        11: "MID",
        12: "MID",
        13: "FWD",
        14: "FWD",
        15: "FWD",
    }
    starters = (1, 3, 4, 5, 8, 9, 10, 11, 13, 14, 15)
    bench = (2, 6, 7, 12)
    expected_points = {player_id: 1.0 for player_id in positions}
    expected_points.update({13: 12.0, 8: 11.0, 12: 9.0, 6: 8.0, 7: 7.0})
    squad = pd.DataFrame(
        {
            "player_id": list(positions),
            "name": [f"Player {player_id}" for player_id in positions],
            "team_id": [f"T{(player_id - 1) // 3}" for player_id in positions],
            "position": list(positions.values()),
            "price_tenths": [50] * len(positions),
            "expected_points": [expected_points[player_id] for player_id in positions],
        }
    )
    return OptimizationResult(
        solver_status=SolverStatus.OPTIMAL,
        selected_squad=squad,
        starting_xi=squad.loc[squad["player_id"].isin(starters)].copy(),
        bench=squad.loc[squad["player_id"].isin(bench)].copy(),
        captain=squad.loc[squad["player_id"] == 13].iloc[0].copy(),
        total_cost_tenths=750,
        projected_score=0.0,
        objective_value=0.0,
        diagnostics={},
    )


def _scenario_set(
    result: OptimizationResult,
    *,
    player_ids: tuple[int, ...] | None = None,
) -> ScenarioSet:
    selected = result.selected_squad
    ids = player_ids if player_ids is not None else tuple(selected["player_id"])
    players = selected.loc[selected["player_id"].isin(ids)].copy()
    provenance = PredictionProvenance(
        model_name="synthetic-component-model",
        model_version="1.0.0",
        feature_contract_version="synthetic-v1",
        training_cutoff="2026-27:GW02",
        training_data_fingerprint="a" * 64,
    )
    snapshot = prepare_optimizer_projection(
        players.drop(columns="expected_points"),
        players.loc[:, ["player_id", "expected_points"]],
        provenance,
    )
    config = ScenarioConfig(
        scenario_count=2,
        min_history_folds=2,
        min_player_observations=2,
    )
    scenario_ids = ("scenario-000000", "scenario-000001")
    source_fold_ids = ("2026-27-gw01", "2026-27-gw02")
    points = pd.DataFrame(
        1.0,
        index=pd.Index(scenario_ids, name="scenario_id"),
        columns=snapshot.table["player_id"].tolist(),
    )
    if 8 in points:
        points.loc["scenario-000001", 8] = 7.0
    if 12 in points:
        points.loc["scenario-000001", 12] = 3.0
    if 6 in points:
        points.loc["scenario-000001", 6] = 2.0
    for player_id in (3, 13):
        if player_id in points:
            points.loc["scenario-000001", player_id] = 0.0
    fingerprint = _scenario_fingerprint(
        snapshot,
        TARGET,
        config,
        scenario_ids,
        source_fold_ids,
        points,
    )
    return ScenarioSet(
        projections=snapshot,
        target=TARGET,
        config=config,
        scenario_ids=scenario_ids,
        source_fold_ids=source_fold_ids,
        scenario_points=points,
        scenario_fingerprint=fingerprint,
        diagnostics={"synthetic": True},
    )


def _appearances(scenarios: ScenarioSet) -> pd.DataFrame:
    appearances = pd.DataFrame(
        True,
        index=scenarios.scenario_points.index.copy(),
        columns=scenarios.scenario_points.columns.copy(),
        dtype="bool",
    )
    appearances.loc["scenario-000001", [3, 13]] = False
    return appearances


def _draw(
    result: OptimizationResult,
    *,
    player_ids: tuple[int, ...] | None = None,
) -> ComponentScenarioDraw:
    scenarios = _scenario_set(result, player_ids=player_ids)
    appearances = _appearances(scenarios)
    selected = result.selected_squad.set_index("player_id")
    ids = list(scenarios.scenario_points.columns)
    inputs = ComponentScenarioInputs(
        table=pd.DataFrame(
            {
                "player_id": ids,
                "team_id": [selected.loc[player_id, "team_id"] for player_id in ids],
                "position": [selected.loc[player_id, "position"] for player_id in ids],
                "fixture_count": [1] * len(ids),
                "appearance_probability": [1.0] * len(ids),
                "expected_minutes_if_appearance": [60.0] * len(ids),
                "raw_expected_points_if_appearance": [
                    selected.loc[player_id, "expected_points"] for player_id in ids
                ],
                "composition_route": ["component_model"] * len(ids),
                "evidence_status": ["not_requested"] * len(ids),
            }
        ),
        provenance=ComponentScenarioProvenance(
            phase_c_table_sha="a" * 64,
            roster_sha="b" * 64,
            model_version="synthetic-component-model",
            feature_contract_version="synthetic-v1",
            target_contract_version="synthetic-target-v1",
            dataset_contract_version="synthetic-dataset-v1",
            season=TARGET.season,
            target_gameweek=TARGET.gameweek,
            deterministic_seed=0,
        ),
    )
    minutes = appearances.astype("float64") * 60.0
    fingerprint = _component_fingerprint(scenarios, inputs, minutes, appearances)
    return ComponentScenarioDraw(
        scenarios=scenarios,
        inputs=inputs,
        sampled_minutes=minutes,
        sampled_appearances=appearances,
        component_fingerprint=fingerprint,
    )


def test_scores_each_scenario_with_official_autosubs_and_captain_fallback() -> None:
    result = _optimization_result()
    draw = _draw(result)

    scored = score_component_scenario_decision(result, draw)

    assert scored.scenario_ids == draw.scenarios.scenario_ids
    assert scored.total_points == (12.0, 27.0)
    assert scored.scores[1].autosubs == ((13, 12), (3, 6))
    assert scored.scores[1].captain_bonus_player_id == 8
    assert scored.scores[1].captain_bonus_points == 7.0


def test_decision_completion_is_identical_across_scenarios() -> None:
    result = _optimization_result()
    draw = _draw(result)

    scored = score_component_scenario_decision(result, draw)

    assert scored.frozen_decision.bench == (2, 12, 6, 7)
    assert scored.frozen_decision.vice_captain_id == 8


def test_missing_selected_player_is_rejected() -> None:
    result = _optimization_result()
    draw = _draw(result, player_ids=tuple(range(1, 15)))

    with pytest.raises(ScenarioValidationError, match="every selected squad player"):
        score_component_scenario_decision(result, draw)


def test_draw_is_revalidated_when_consumed() -> None:
    result = _optimization_result()
    draw = _draw(result)
    draw.sampled_appearances.iloc[0, 0] = False

    with pytest.raises(ScenarioValidationError, match="did not feature scored nothing"):
        score_component_scenario_decision(result, draw)


def test_draw_type_is_required() -> None:
    result = _optimization_result()

    with pytest.raises(ScenarioValidationError, match="ComponentScenarioDraw"):
        score_component_scenario_decision(result, object())  # type: ignore[arg-type]


def test_scoring_does_not_mutate_caller_frames() -> None:
    result = _optimization_result()
    draw = _draw(result)
    original_squad = result.selected_squad.copy(deep=True)
    original_points = draw.scenarios.scenario_points.copy(deep=True)
    original_appearances = draw.sampled_appearances.copy(deep=True)

    score_component_scenario_decision(result, draw)

    assert_frame_equal(result.selected_squad, original_squad)
    assert_frame_equal(draw.scenarios.scenario_points, original_points)
    assert_frame_equal(draw.sampled_appearances, original_appearances)


def test_solution_free_decision_is_rejected_before_scenario_outcomes() -> None:
    result = _optimization_result()
    draw = _draw(result)
    invalid_result = replace(result, solver_status=SolverStatus.INFEASIBLE)

    with pytest.raises(EvaluationValidationError, match="OPTIMAL or FEASIBLE"):
        score_component_scenario_decision(invalid_result, draw)
