"""The level correction runner's gates: read as the protocol fixed them, never moved."""

import numpy as np
import pandas as pd
import pytest
from scripts.measure_prior_minutes_level import (
    LEVEL_GATE_SHARE,
    NO_HARM_FLOOR,
    factor_table,
    level_gate,
    verdict,
)

from squadopt.evaluation.live_projection_audit import PRIOR_MINUTES_BUCKETS


def test_the_three_verdicts_are_the_protocols() -> None:
    assert verdict(True, 0.4, (0.1, 0.7)) == "decisions"
    assert verdict(True, 0.1, (-0.2, 0.4)) == "level_only"
    assert verdict(True, NO_HARM_FLOOR, (-0.9, 0.4)) == "level_only"
    # Below the floor, an interval under zero, a failed level gate, or no interval at all.
    assert verdict(True, NO_HARM_FLOOR - 0.01, (-0.9, 0.4)) == "failed"
    assert verdict(True, -0.5, (-0.9, -0.1)) == "failed"
    assert verdict(False, 0.4, (0.1, 0.7)) == "failed"
    assert verdict(True, 0.4, None) == "failed"
    assert LEVEL_GATE_SHARE == 0.5 and NO_HARM_FLOOR == -0.25


def test_the_factor_table_reads_the_outcome_as_the_evaluation_does() -> None:
    rows = pd.DataFrame(
        {
            "season": ["2021-22"] * 3,
            "fold_id": ["2021-22-gw05"] * 3,
            "target_gameweek": [5, 5, 5],
            "player_id": [1, 2, 3],
            "fixture_count": [1, 1, 0],
            "appearance_target": [1, 0, 0],
            "points_target": [7.0, np.nan, np.nan],
            "control_expected_points": [4.0, 1.0, 0.0],
        }
    )
    panel = pd.DataFrame(
        {
            "season": ["2021-22"] * 4,
            "gameweek": [1, 2, 3, 4],
            "player_id": [1, 1, 1, 1],
            "minutes": [90, 90, 90, 90],
        }
    )
    table = factor_table(rows, panel)
    assert table["realized"].tolist() == [7.0, 0.0, 0.0]
    assert table["prior_minutes_per_week"].tolist() == [90.0, 0.0, 0.0]
    # A blank gameweek has no forecast to correct and teaches nothing.
    assert np.isnan(table.loc[2, "forecast"]) and table.loc[1, "forecast"] == 1.0


def _gate_inputs(after_scale: float) -> tuple[pd.DataFrame, pd.Series, pd.DataFrame]:
    priors = {"none": 0.0, "under_30": 10.0, "30_to_60": 45.0, "60_and_above": 80.0}
    rows = []
    for fold in ("a", "b"):
        for player, (_label, prior) in enumerate(priors.items(), 1):
            rows.append(
                {
                    "fold_id": fold,
                    "target_gameweek": 6,
                    "player_id": player,
                    "forecast": 2.0,
                    "realized": 3.0,
                    "prior_minutes_per_week": prior,
                }
            )
    table = pd.DataFrame(rows)
    factors = pd.DataFrame(
        [
            {"fold_id": fold, "bucket": label, "factor": 1.0 if fold == "a" else 1.5}
            for fold in ("a", "b")
            for label, _, _ in PRIOR_MINUTES_BUCKETS
        ]
    )
    corrected = table["forecast"] * np.where(table["fold_id"] == "b", after_scale, 1.0)
    return table, pd.Series(corrected, index=table.index), factors


def test_the_level_gate_reads_only_rows_a_factor_touched() -> None:
    table, corrected, factors = _gate_inputs(1.5)
    gate = level_gate(table, corrected, factors)
    # Decision "a" ran on factors of 1 and is not part of the reading.
    assert gate["rows"] == 4
    regulars = gate["buckets"]["60_and_above"]
    assert regulars["bias_uncorrected"] == pytest.approx(1.0)
    assert regulars["bias_corrected"] == pytest.approx(0.0)
    assert gate["passes"] is True


def test_the_level_gate_fails_when_a_bucket_keeps_more_than_half_its_bias() -> None:
    table, corrected, factors = _gate_inputs(1.2)  # 3.0 against 2.4: 0.6 of 1.0 remains
    gate = level_gate(table, corrected, factors)
    assert gate["buckets"]["none"]["passes"] is False and gate["passes"] is False
