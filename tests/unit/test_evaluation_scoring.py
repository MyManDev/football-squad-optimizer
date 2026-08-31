"""Tests for the versioned realized squad-points policy."""

from dataclasses import replace
from decimal import Decimal
from fractions import Fraction

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

from squadopt import (
    EvaluationValidationError,
    FrozenSquadDecision,
    OptimizationResult,
    ScoringPolicy,
    SolverStatus,
    complete_optimization_decision,
    score_frozen_squad_decision,
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
    assert ScoringPolicy.OFFICIAL_AUTOSUB_CAPTAIN_V2.value == "official_autosub_captain_v2"


def _frozen_decision(*, bench: tuple[int, ...] = (2, 12, 6, 7)) -> FrozenSquadDecision:
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
    squad = pd.DataFrame({"player_id": list(positions), "position": list(positions.values())})
    return FrozenSquadDecision(
        squad=squad,
        starting_xi=(1, 3, 4, 5, 8, 9, 10, 11, 13, 14, 15),
        bench=bench,
        captain_id=13,
        vice_captain_id=8,
    )


def _outcomes(
    *,
    points: dict[int, int] | None = None,
    minutes: dict[int, int] | None = None,
) -> pd.DataFrame:
    point_values = points or {}
    minute_values = minutes or {}
    return pd.DataFrame(
        {
            "player_id": list(range(1, 16)),
            "total_points": [point_values.get(player_id, 1) for player_id in range(1, 16)],
            "minutes": [minute_values.get(player_id, 90) for player_id in range(1, 16)],
        }
    )


def test_v2_scores_the_named_eleven_and_captain_when_everyone_plays() -> None:
    score = score_frozen_squad_decision(_frozen_decision(), _outcomes())

    assert score.total_points == 12.0
    assert score.final_xi == _frozen_decision().starting_xi
    assert score.autosubs == ()
    assert score.captain_bonus_player_id == 13


def test_v2_uses_outfield_bench_order_not_realized_points() -> None:
    outcomes = _outcomes(points={12: 2, 6: 20}, minutes={8: 0})

    score = score_frozen_squad_decision(_frozen_decision(), outcomes)

    assert score.autosubs == ((8, 12),)
    assert 12 in score.final_xi
    assert 6 not in score.final_xi


def test_v2_skips_a_higher_priority_sub_that_breaks_formation() -> None:
    outcomes = _outcomes(points={12: 20, 6: 2}, minutes={3: 0})

    score = score_frozen_squad_decision(_frozen_decision(), outcomes)

    assert score.autosubs == ((3, 6),)
    assert 12 not in score.final_xi


def test_v2_goalkeeper_can_only_be_replaced_by_the_bench_goalkeeper() -> None:
    score = score_frozen_squad_decision(_frozen_decision(), _outcomes(minutes={1: 0}))

    assert score.autosubs == ((1, 2),)
    assert 2 in score.final_xi


def test_v2_leaves_a_vacancy_when_no_legal_bench_player_plays() -> None:
    score = score_frozen_squad_decision(
        _frozen_decision(),
        _outcomes(minutes={3: 0, 6: 0, 7: 0}),
    )

    assert len(score.final_xi) == 10
    assert score.autosubs == ()


def test_v2_moves_the_bonus_to_a_playing_vice_captain() -> None:
    score = score_frozen_squad_decision(
        _frozen_decision(),
        _outcomes(points={8: 7}, minutes={13: 0}),
    )

    assert score.captain_bonus_player_id == 8
    assert score.captain_bonus_points == 7.0


def test_v2_has_no_bonus_when_captain_and_vice_do_not_play() -> None:
    score = score_frozen_squad_decision(
        _frozen_decision(),
        _outcomes(minutes={8: 0, 13: 0}),
    )

    assert score.captain_bonus_player_id is None
    assert score.captain_bonus_points == 0.0


def test_v2_does_not_bonus_a_vice_captain_who_remains_on_the_bench() -> None:
    decision = FrozenSquadDecision(
        squad=_frozen_decision().squad,
        starting_xi=_frozen_decision().starting_xi,
        bench=_frozen_decision().bench,
        captain_id=13,
        vice_captain_id=2,
    )
    score = score_frozen_squad_decision(decision, _outcomes(minutes={13: 0}))

    assert score.captain_bonus_player_id is None


def test_v2_preserves_negative_event_points() -> None:
    score = score_frozen_squad_decision(_frozen_decision(), _outcomes(points={13: -2}))

    assert score.total_points == 6.0


def test_v2_requires_minutes_for_every_squad_player() -> None:
    outcomes = _outcomes().drop(columns="minutes")

    with pytest.raises(EvaluationValidationError, match="minutes"):
        score_frozen_squad_decision(_frozen_decision(), outcomes)


def test_v2_does_not_mutate_the_decision_or_outcomes() -> None:
    decision = _frozen_decision()
    outcomes = _outcomes(minutes={3: 0})
    original_squad = decision.squad.copy(deep=True)
    original_outcomes = outcomes.copy(deep=True)

    score_frozen_squad_decision(decision, outcomes)

    assert_frame_equal(decision.squad, original_squad)
    assert_frame_equal(outcomes, original_outcomes)


def test_optimizer_completion_uses_projection_order_and_stable_vice(
    baseline_result: OptimizationResult,
) -> None:
    completed = complete_optimization_decision(baseline_result)
    squad = baseline_result.selected_squad.set_index("player_id")

    assert completed.completion_policy == "optimizer_projection_order_v1"
    assert squad.at[completed.bench[0], "position"] == "GK"
    outfield = list(completed.bench[1:])
    assert outfield == sorted(
        outfield,
        key=lambda player_id: (-float(squad.at[player_id, "expected_points"]), player_id),
    )
    assert completed.vice_captain_id != completed.captain_id


def test_public_v2_policy_completes_and_scores_an_optimizer_result(
    baseline_result: OptimizationResult,
) -> None:
    realized = _realized_points(baseline_result)
    realized["minutes"] = 90

    assert (
        score_realized_squad_points(
            baseline_result,
            realized,
            policy=ScoringPolicy.OFFICIAL_AUTOSUB_CAPTAIN_V2,
        )
        == 12.0
    )
