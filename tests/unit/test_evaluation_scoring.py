"""Tests for the versioned realized squad-points policy."""

from dataclasses import replace
from decimal import Decimal
from fractions import Fraction

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

from squadopt import (
    EvaluationValidationError,
    OptimizationResult,
    ScoringPolicy,
    SolverStatus,
    score_realized_squad_points,
)


def _realized_points(result: OptimizationResult, value: float = 1.0) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "player_id": result.selected_squad["player_id"].tolist(),
            "total_points": value,
        }
    )


def test_v1_scores_starting_xi_and_captain_bonus(
    baseline_result: OptimizationResult,
) -> None:
    realized = _realized_points(baseline_result)

    score = score_realized_squad_points(baseline_result, realized)

    assert score == 12.0


def test_bench_points_do_not_enter_v1_score(baseline_result: OptimizationResult) -> None:
    realized = _realized_points(baseline_result)
    bench_ids = set(baseline_result.bench["player_id"])
    realized.loc[realized["player_id"].isin(bench_ids), "total_points"] = 1000.0

    score = score_realized_squad_points(baseline_result, realized)

    assert score == 12.0


def test_captain_points_are_added_twice(baseline_result: OptimizationResult) -> None:
    assert baseline_result.captain is not None
    realized = _realized_points(baseline_result, value=0.0)
    captain_id = baseline_result.captain["player_id"]
    realized.loc[realized["player_id"] == captain_id, "total_points"] = 7.0

    score = score_realized_squad_points(baseline_result, realized)

    assert score == 14.0


def test_negative_realized_points_are_preserved(baseline_result: OptimizationResult) -> None:
    assert baseline_result.captain is not None
    realized = _realized_points(baseline_result, value=0.0)
    captain_id = baseline_result.captain["player_id"]
    realized.loc[realized["player_id"] == captain_id, "total_points"] = -2.0

    assert score_realized_squad_points(baseline_result, realized) == -4.0


def test_scoring_does_not_mutate_realized_points(baseline_result: OptimizationResult) -> None:
    realized = _realized_points(baseline_result)
    original = realized.copy(deep=True)

    score_realized_squad_points(baseline_result, realized)

    assert_frame_equal(realized, original)


def test_missing_realized_column_is_rejected(baseline_result: OptimizationResult) -> None:
    realized = _realized_points(baseline_result).drop(columns="total_points")

    with pytest.raises(EvaluationValidationError, match="missing required columns"):
        score_realized_squad_points(baseline_result, realized)


def test_duplicate_realized_player_id_is_rejected(
    baseline_result: OptimizationResult,
) -> None:
    realized = _realized_points(baseline_result)
    realized.loc[1, "player_id"] = realized.loc[0, "player_id"]

    with pytest.raises(EvaluationValidationError, match="duplicate player_id"):
        score_realized_squad_points(baseline_result, realized)


@pytest.mark.parametrize(
    "value",
    [float("nan"), float("inf"), float("-inf")],
    ids=["nan", "positive-infinity", "negative-infinity"],
)
def test_non_finite_realized_points_are_rejected(
    baseline_result: OptimizationResult,
    value: float,
) -> None:
    realized = _realized_points(baseline_result)
    realized.loc[0, "total_points"] = value

    with pytest.raises(EvaluationValidationError, match=r"missing values|finite numbers"):
        score_realized_squad_points(baseline_result, realized)


def test_unconvertible_real_number_raises_domain_error(
    baseline_result: OptimizationResult,
) -> None:
    realized = _realized_points(baseline_result).astype({"total_points": "object"})
    realized.loc[0, "total_points"] = Fraction(1, 2)

    with pytest.raises(EvaluationValidationError, match="finite numbers"):
        score_realized_squad_points(baseline_result, realized)


def test_score_that_overflows_public_float_is_rejected(
    baseline_result: OptimizationResult,
) -> None:
    assert baseline_result.captain is not None
    realized = _realized_points(baseline_result, value=0.0).astype({"total_points": "object"})
    captain_id = baseline_result.captain["player_id"]
    realized.loc[realized["player_id"] == captain_id, "total_points"] = Decimal("1e10000")

    with pytest.raises(EvaluationValidationError, match="finite float range"):
        score_realized_squad_points(baseline_result, realized)


def test_empty_realized_points_are_rejected(baseline_result: OptimizationResult) -> None:
    empty = pd.DataFrame(columns=["player_id", "total_points"])

    with pytest.raises(EvaluationValidationError, match="at least one player"):
        score_realized_squad_points(baseline_result, empty)


def test_missing_selected_player_outcome_is_rejected(
    baseline_result: OptimizationResult,
) -> None:
    realized = _realized_points(baseline_result)
    missing_id = baseline_result.starting_xi.iloc[0]["player_id"]
    realized = realized.loc[realized["player_id"] != missing_id]

    with pytest.raises(EvaluationValidationError, match=r"do not cover.*missing player_id"):
        score_realized_squad_points(baseline_result, realized)


def test_solution_free_result_cannot_be_scored(baseline_result: OptimizationResult) -> None:
    no_solution = replace(baseline_result, solver_status=SolverStatus.INFEASIBLE)

    with pytest.raises(EvaluationValidationError, match="OPTIMAL or FEASIBLE"):
        score_realized_squad_points(no_solution, _realized_points(baseline_result))


def test_scoring_policy_requires_the_versioned_enum(
    baseline_result: OptimizationResult,
) -> None:
    with pytest.raises(EvaluationValidationError, match="ScoringPolicy"):
        score_realized_squad_points(
            baseline_result,
            _realized_points(baseline_result),
            policy="realized_squad_points_v1",  # type: ignore[arg-type]
        )


def test_public_policy_value_is_stable() -> None:
    assert ScoringPolicy.STARTING_XI_CAPTAIN_V1.value == "realized_squad_points_v1"
