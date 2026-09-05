"""Tests for deterministic evaluation of caller-prepared folds."""

from collections.abc import Mapping
from dataclasses import replace

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

from squadopt import (
    EvaluationConfig,
    EvaluationFold,
    EvaluationValidationError,
    OptimizationConfig,
    OptimizationResult,
    ScoringPolicy,
    SolverStatus,
    evaluate_prepared_folds,
    optimize_squad,
)


def _outcomes(players: pd.DataFrame, value: float = 1.0) -> pd.DataFrame:
    return pd.DataFrame({"player_id": players["player_id"].tolist(), "total_points": value})


def _fold(
    fold_id: str,
    players: pd.DataFrame,
    *,
    metadata: Mapping[str, object] | None = None,
) -> EvaluationFold:
    return EvaluationFold(
        fold_id=fold_id,
        projections=players,
        realized_points=_outcomes(players),
        metadata={} if metadata is None else metadata,
    )


def _solution_free_result(players: pd.DataFrame, status: SolverStatus) -> OptimizationResult:
    empty = players.iloc[0:0].copy(deep=True)
    return OptimizationResult(
        solver_status=status,
        selected_squad=empty.copy(deep=True),
        starting_xi=empty.copy(deep=True),
        bench=empty.copy(deep=True),
        captain=None,
        total_cost_tenths=None,
        projected_score=None,
        objective_value=None,
        diagnostics={"solve_time_seconds": 0.25},
    )


def test_evaluates_one_prepared_fold(
    known_optimum_players: pd.DataFrame,
    small_config: OptimizationConfig,
) -> None:
    result = evaluate_prepared_folds(
        [_fold("2025-26-GW02", known_optimum_players)],
        EvaluationConfig(optimization_config=small_config),
    )

    fold = result.folds[0]
    assert fold.optimization_result.solver_status is SolverStatus.OPTIMAL
    assert fold.realized_squad_points == 4.0
    assert fold.squad_turnover is None
    assert fold.is_scored
    assert result.summary.attempted_folds == 1
    assert result.summary.feasible_folds == 1
    assert result.summary.scored_folds == 1
    assert result.summary.feasibility_rate == 1.0
    assert result.summary.mean_realized_squad_points == 4.0
    assert result.summary.realized_squad_points_stddev == 0.0
    assert result.summary.runtime_observations == 1
    assert result.summary.median_solver_runtime_seconds is not None
    assert result.summary.p95_solver_runtime_seconds is not None
    assert result.summary.turnover_observations == 0


def test_official_v2_scoring_preserves_realized_minutes(
    baseline_players: pd.DataFrame,
) -> None:
    outcomes = _outcomes(baseline_players)
    outcomes["minutes"] = 90

    result = evaluate_prepared_folds(
        [EvaluationFold("official-v2", baseline_players, outcomes)],
        EvaluationConfig(scoring_policy=ScoringPolicy.OFFICIAL_AUTOSUB_CAPTAIN_V2),
    )

    assert result.folds[0].realized_squad_points == 12.0


def test_fold_order_and_turnover_are_deterministic(
    known_optimum_players: pd.DataFrame,
    small_config: OptimizationConfig,
) -> None:
    reversed_strength = known_optimum_players.copy(deep=True)
    reversed_strength["expected_points"] = [
        1.0 if str(player_id).endswith("_A") else 20.0
        for player_id in reversed_strength["player_id"]
    ]
    folds = [
        _fold("first", known_optimum_players),
        _fold("second", reversed_strength),
    ]
    config = EvaluationConfig(optimization_config=small_config)

    first = evaluate_prepared_folds(folds, config)
    second = evaluate_prepared_folds(folds, config)

    assert [fold.fold_id for fold in first.folds] == ["first", "second"]
    assert first.diagnostics["fold_order"] == ("first", "second")
    assert first.folds[1].squad_turnover == 4
    assert first.summary.turnover_observations == 1
    assert first.summary.mean_squad_turnover == 4.0
    assert [
        fold.optimization_result.selected_squad["player_id"].tolist() for fold in first.folds
    ] == [fold.optimization_result.selected_squad["player_id"].tolist() for fold in second.folds]


def test_player_id_representation_must_stay_consistent_across_folds(
    baseline_players: pd.DataFrame,
) -> None:
    text_ids = baseline_players.copy(deep=True)
    text_ids["player_id"] = text_ids["player_id"].map(str)

    with pytest.raises(EvaluationValidationError, match="type must remain consistent"):
        evaluate_prepared_folds(
            [_fold("integer-ids", baseline_players), _fold("text-ids", text_ids)],
            EvaluationConfig(),
        )


def test_projection_and_realized_id_types_must_match_within_fold(
    known_optimum_players: pd.DataFrame,
    small_config: OptimizationConfig,
) -> None:
    integer_outcomes = pd.DataFrame(
        {
            "player_id": range(len(known_optimum_players)),
            "total_points": 1.0,
        }
    )
    fold = EvaluationFold("mismatched-id-types", known_optimum_players, integer_outcomes)

    with pytest.raises(EvaluationValidationError, match="types must match within each fold"):
        evaluate_prepared_folds(
            [fold],
            EvaluationConfig(optimization_config=small_config),
        )


def test_summary_statistics_follow_the_documented_definitions(
    monkeypatch: pytest.MonkeyPatch,
    known_optimum_players: pd.DataFrame,
    small_config: OptimizationConfig,
) -> None:
    solved = optimize_squad(known_optimum_players, small_config)
    prepared_results = iter(
        (
            replace(
                solved,
                objective_value=10.0,
                diagnostics={"solve_time_seconds": 1.0},
            ),
            replace(
                solved,
                objective_value=20.0,
                diagnostics={"solve_time_seconds": 3.0},
            ),
        )
    )

    def return_prepared_result(
        players: pd.DataFrame,
        config: OptimizationConfig,
    ) -> OptimizationResult:
        del players, config
        return next(prepared_results)

    monkeypatch.setattr(
        "squadopt.evaluation.evaluator.optimize_squad",
        return_prepared_result,
    )
    first_fold = _fold("first-summary", known_optimum_players)
    second_fold = EvaluationFold(
        "second-summary",
        known_optimum_players,
        _outcomes(known_optimum_players, value=2.0),
    )

    result = evaluate_prepared_folds(
        [first_fold, second_fold],
        EvaluationConfig(optimization_config=small_config),
    )

    assert result.summary.mean_realized_squad_points == 6.0
    assert result.summary.realized_squad_points_stddev == 2.0
    assert result.summary.mean_projected_objective_value == 15.0
    assert result.summary.median_solver_runtime_seconds == 2.0
    assert result.summary.p95_solver_runtime_seconds == 3.0


def test_infeasible_fold_is_reported_without_fabricated_score(
    known_optimum_players: pd.DataFrame,
    small_config: OptimizationConfig,
) -> None:
    infeasible_config = OptimizationConfig(
        budget_tenths=0,
        squad_size=small_config.squad_size,
        squad_position_limits=small_config.squad_position_limits,
        starting_size=small_config.starting_size,
        starting_position_min=small_config.starting_position_min,
        starting_position_max=small_config.starting_position_max,
        max_players_per_team=small_config.max_players_per_team,
    )

    result = evaluate_prepared_folds(
        [_fold("infeasible", known_optimum_players)],
        EvaluationConfig(optimization_config=infeasible_config),
    )

    assert result.folds[0].optimization_result.solver_status is SolverStatus.INFEASIBLE
    assert result.folds[0].realized_squad_points is None
    assert not result.folds[0].is_scored
    assert result.summary.feasible_folds == 0
    assert result.summary.scored_folds == 0
    assert result.summary.feasibility_rate == 0.0
    assert result.summary.mean_realized_squad_points is None
    assert result.summary.mean_projected_objective_value is None


def test_unknown_fold_is_reported_without_fabricated_score(
    monkeypatch: pytest.MonkeyPatch,
    known_optimum_players: pd.DataFrame,
    small_config: OptimizationConfig,
) -> None:
    def return_unknown(
        players: pd.DataFrame,
        config: OptimizationConfig,
    ) -> OptimizationResult:
        del config
        return _solution_free_result(players, SolverStatus.UNKNOWN)

    monkeypatch.setattr("squadopt.evaluation.evaluator.optimize_squad", return_unknown)

    result = evaluate_prepared_folds(
        [_fold("unknown", known_optimum_players)],
        EvaluationConfig(optimization_config=small_config),
    )

    assert result.folds[0].optimization_result.solver_status is SolverStatus.UNKNOWN
    assert result.folds[0].realized_squad_points is None
    assert result.summary.feasibility_rate == 0.0


def test_inputs_are_not_mutated(
    known_optimum_players: pd.DataFrame,
    small_config: OptimizationConfig,
) -> None:
    projections = known_optimum_players.copy(deep=True)
    outcomes = _outcomes(projections)
    original_projections = projections.copy(deep=True)
    original_outcomes = outcomes.copy(deep=True)
    fold = EvaluationFold("immutable", projections, outcomes)

    projections.loc[0, "expected_points"] = 999.0
    outcomes.loc[0, "total_points"] = 999.0
    evaluate_prepared_folds(
        [fold],
        EvaluationConfig(optimization_config=small_config),
    )

    assert_frame_equal(fold.projections, original_projections)
    assert_frame_equal(fold.realized_points, original_outcomes)


def test_fold_and_run_metadata_are_defensively_copied(
    known_optimum_players: pd.DataFrame,
) -> None:
    fold_metadata: dict[str, object] = {
        "gameweek": 2,
        "context": {"tags": ["baseline"]},
    }
    run_metadata: dict[str, object] = {
        "dataset_version": "synthetic-v1",
        "tags": ["control"],
    }

    fold = _fold("metadata", known_optimum_players, metadata=fold_metadata)
    config = EvaluationConfig(run_metadata=run_metadata)
    fold_metadata["gameweek"] = 99
    fold_context = fold_metadata["context"]
    assert isinstance(fold_context, dict)
    fold_tags = fold_context["tags"]
    assert isinstance(fold_tags, list)
    fold_tags.append("mutated")
    run_metadata["dataset_version"] = "changed"
    run_tags = run_metadata["tags"]
    assert isinstance(run_tags, list)
    run_tags.append("mutated")

    assert fold.metadata["gameweek"] == 2
    frozen_context = fold.metadata["context"]
    assert isinstance(frozen_context, Mapping)
    assert frozen_context["tags"] == ("baseline",)
    assert config.run_metadata["dataset_version"] == "synthetic-v1"
    assert config.run_metadata["tags"] == ("control",)


@pytest.mark.parametrize("key", [" ", "\t", "\r\n"])
def test_whitespace_only_metadata_keys_are_rejected(
    key: str,
    known_optimum_players: pd.DataFrame,
) -> None:
    with pytest.raises(EvaluationValidationError, match="non-empty strings"):
        EvaluationConfig(run_metadata={key: "value"})
    with pytest.raises(EvaluationValidationError, match="non-empty strings"):
        _fold("invalid-metadata", known_optimum_players, metadata={key: "value"})


def test_non_json_metadata_value_is_rejected() -> None:
    with pytest.raises(EvaluationValidationError, match="JSON-compatible"):
        EvaluationConfig(run_metadata={"unsupported": object()})


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_metadata_number_is_rejected(value: float) -> None:
    with pytest.raises(EvaluationValidationError, match="must be finite"):
        EvaluationConfig(run_metadata={"metric": value})


def test_duplicate_fold_ids_are_rejected(
    known_optimum_players: pd.DataFrame,
    small_config: OptimizationConfig,
) -> None:
    folds = [_fold("same", known_optimum_players), _fold("same", known_optimum_players)]

    with pytest.raises(EvaluationValidationError, match="fold_id values must be unique"):
        evaluate_prepared_folds(
            folds,
            EvaluationConfig(optimization_config=small_config),
        )


def test_empty_fold_collection_is_rejected() -> None:
    with pytest.raises(EvaluationValidationError, match="At least one"):
        evaluate_prepared_folds([], EvaluationConfig())


def test_invalid_fold_entry_is_rejected() -> None:
    with pytest.raises(EvaluationValidationError, match="EvaluationFold"):
        evaluate_prepared_folds(["not-a-fold"], EvaluationConfig())  # type: ignore[list-item]


def test_invalid_config_is_rejected(known_optimum_players: pd.DataFrame) -> None:
    with pytest.raises(EvaluationValidationError, match="EvaluationConfig"):
        evaluate_prepared_folds(  # type: ignore[arg-type]
            [_fold("invalid-config", known_optimum_players)],
            OptimizationConfig(),
        )


def test_realized_schema_is_checked_even_when_solver_has_no_solution(
    monkeypatch: pytest.MonkeyPatch,
    known_optimum_players: pd.DataFrame,
    small_config: OptimizationConfig,
) -> None:
    def return_infeasible(
        players: pd.DataFrame,
        config: OptimizationConfig,
    ) -> OptimizationResult:
        del config
        return _solution_free_result(players, SolverStatus.INFEASIBLE)

    monkeypatch.setattr("squadopt.evaluation.evaluator.optimize_squad", return_infeasible)
    invalid_fold = EvaluationFold(
        "bad-outcomes",
        known_optimum_players,
        pd.DataFrame({"player_id": known_optimum_players["player_id"]}),
    )

    with pytest.raises(EvaluationValidationError, match="missing required columns"):
        evaluate_prepared_folds(
            [invalid_fold],
            EvaluationConfig(optimization_config=small_config),
        )
