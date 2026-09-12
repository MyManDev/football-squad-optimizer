"""Measured residuals, missing evidence and official substitutions are distinct."""

from typing import Any

import pandas as pd
import pytest

from squadopt.application.scoreboard_diagnostics import score_recorded_decision
from squadopt.data.errors import DataError


def decision_inputs() -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame]:
    starters = [1, 3, 4, 5, 8, 9, 10, 11, 13, 14, 15]
    decision: dict[str, Any] = {
        "squad_player_ids": list(range(1, 16)),
        "starting_xi_player_ids": starters,
        "bench_player_ids": [2, 6, 7, 12],
        "captain_player_id": 8,
        "transfers": {"transfer_hit_points": 4.0, "chip": None},
    }
    projected = pd.DataFrame(
        {
            "player_id": range(1, 16),
            "position": ["GK"] * 2 + ["DEF"] * 5 + ["MID"] * 5 + ["FWD"] * 3,
            "expected_points": [10.0] * 15,
            "expected_minutes": [80.0] * 15,
        }
    )
    outcomes = pd.DataFrame(
        {
            "player_id": range(1, 16),
            "total_points": [0 if player == 8 else player for player in range(1, 16)],
            "minutes": [0 if player == 8 else 90 for player in range(1, 16)],
        }
    )
    return decision, projected, outcomes


def test_legacy_decision_does_not_invent_bench_order_or_vice() -> None:
    decision, projections, outcomes = decision_inputs()
    result = score_recorded_decision(decision, projections, outcomes)
    assert result["scoring_basis"] == "named_eleven_no_autosubs"
    assert result["diagnostics"] == {
        "zero_minute_starters": 1,
        "minutes_shortfall": -100.0,
        "captain_shortfall": 10.0,
        "autosub_recovery": None,
    }
    assert result["net"] == 81.0


def test_frozen_order_uses_official_autosubs_and_vice_recovery() -> None:
    decision, projections, outcomes = decision_inputs()
    decision.update(ordered_bench_player_ids=[2, 6, 7, 12], vice_captain_player_id=9)
    result = score_recorded_decision(decision, projections, outcomes)
    assert result["scoring_basis"] == "official_autosub_captain_v2"
    assert result["diagnostics"] == {
        "zero_minute_starters": 1,
        "minutes_shortfall": -100.0,
        "captain_shortfall": 1.0,
        "autosub_recovery": 6.0,
    }
    assert result["net"] == 96.0


@pytest.mark.parametrize("chip,expected", [("3xc", 105.0), ("bboost", 117.0)])
def test_official_scoring_preserves_chips_and_real_hit_charge(chip: str, expected: float) -> None:
    decision, projections, outcomes = decision_inputs()
    decision.update(ordered_bench_player_ids=[2, 6, 7, 12], vice_captain_player_id=9)
    decision["transfers"]["chip"] = chip
    assert score_recorded_decision(decision, projections, outcomes)["net"] == expected


def test_missing_minutes_prediction_is_not_a_zero_residual() -> None:
    decision, projections, outcomes = decision_inputs()
    result = score_recorded_decision(
        decision, projections.drop(columns="expected_minutes"), outcomes
    )
    assert result["diagnostics"]["minutes_shortfall"] is None


def test_absent_outcome_is_not_a_nonappearance() -> None:
    decision, projections, outcomes = decision_inputs()
    with pytest.raises(DataError, match="cover"):
        score_recorded_decision(decision, projections, outcomes.iloc[1:])


def test_nan_outcome_is_refused() -> None:
    decision, projections, outcomes = decision_inputs()
    outcomes.loc[0, "minutes"] = float("nan")
    with pytest.raises(DataError, match="finite"):
        score_recorded_decision(decision, projections, outcomes)


@pytest.mark.parametrize("hits", [float("nan"), float("inf"), -4, True, "4"])
def test_invalid_hit_charges_are_refused(hits: object) -> None:
    decision, projections, outcomes = decision_inputs()
    decision["transfers"]["transfer_hit_points"] = hits
    with pytest.raises(DataError, match="hit charges"):
        score_recorded_decision(decision, projections, outcomes)


@pytest.mark.parametrize(
    "field", ["starting_xi_player_ids", "bench_player_ids", "squad_player_ids"]
)
def test_duplicate_frozen_identities_are_refused(field: str) -> None:
    decision, projections, outcomes = decision_inputs()
    decision[field][0] = decision[field][1]
    with pytest.raises(DataError, match="duplicate"):
        score_recorded_decision(decision, projections, outcomes)


def test_numeric_outcomes_are_normalized_without_mutating_the_input() -> None:
    decision, projections, outcomes = decision_inputs()
    strings = outcomes.astype({"minutes": str, "total_points": str})
    assert score_recorded_decision(decision, projections, strings) == score_recorded_decision(
        decision, projections, outcomes
    )
    assert isinstance(strings.loc[0, "minutes"], str)


@pytest.mark.parametrize("minutes", [90.5, True])
def test_invalid_minute_values_are_not_appearances(minutes: object) -> None:
    decision, projections, outcomes = decision_inputs()
    outcomes["minutes"] = outcomes["minutes"].astype(object)
    outcomes.loc[0, "minutes"] = minutes
    with pytest.raises(DataError):
        score_recorded_decision(decision, projections, outcomes)


@pytest.mark.parametrize(
    "field,diagnostic",
    [("expected_minutes", "minutes_shortfall"), ("expected_points", "captain_shortfall")],
)
@pytest.mark.parametrize("value", [True, float("inf"), None])
def test_invalid_predictions_leave_the_residual_unmeasured(
    field: str, diagnostic: str, value: object
) -> None:
    decision, projections, outcomes = decision_inputs()
    projections[field] = projections[field].astype(object)
    projections.loc[projections.player_id == (1 if field == "expected_minutes" else 8), field] = (
        value
    )
    assert (
        score_recorded_decision(decision, projections, outcomes)["diagnostics"][diagnostic] is None
    )


@pytest.mark.parametrize("policy", ["", None, 17])
def test_invalid_recorded_completion_policy_is_a_data_error(policy: object) -> None:
    decision, projections, outcomes = decision_inputs()
    decision.update(
        ordered_bench_player_ids=[2, 6, 7, 12], vice_captain_player_id=9, completion_policy=policy
    )
    with pytest.raises(DataError, match="completion_policy"):
        score_recorded_decision(decision, projections, outcomes)
