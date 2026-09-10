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
