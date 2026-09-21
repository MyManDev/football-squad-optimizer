"""Synthetic causal and population checks; no historical artifacts are opened."""

import numpy as np
import pandas as pd
import pytest

from squadopt.evaluation.appearance_recalibration import recalibrate_appearance, reliability


def rows() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "season": "2021-22",
                "fold_id": f"2021-22-gw{week:02d}",
                "player_id": player,
                "fixture_count": 1,
                "composition_route": "component_model",
                "appearance_probability": 0.2 if player < 15 else 0.8,
                "appearance_target": float(player >= 15),
                "expected_points_if_appearance": 5.0,
                "control_expected_points": 1.0 if player < 15 else 4.0,
            }
            for week in range(1, 11)
            for player in range(30)
        ]
    )


def test_future_and_same_decision_labels_cannot_change_predictions() -> None:
    original = rows()
    baseline = recalibrate_appearance(original)
    changed = original.copy()
    changed.loc[changed["fold_id"].ge("2021-22-gw09"), "appearance_target"] = 1.0
    updated = recalibrate_appearance(changed)
    through_nine = original["fold_id"].le("2021-22-gw09")
    pd.testing.assert_series_equal(
        baseline.probabilities[through_nine], updated.probabilities[through_nine]
    )
    assert not baseline.probabilities.equals(updated.probabilities)
    assert baseline.training_counts.iloc[8]["earlier_rows"] == 240
    assert baseline.training_counts["fitted"].tolist() == [False] * 8 + [True] * 2


def test_identity_warmup_and_monotone_recomposition() -> None:
    table = rows()
    result = recalibrate_appearance(table)
    pd.testing.assert_series_equal(
        result.points.iloc[:240], table.control_expected_points.iloc[:240]
    )
    assert result.probabilities.iloc[240:270].tolist() == [0.0] * 15 + [1.0] * 15
    assert result.points.iloc[240:270].tolist() == [0.0] * 15 + [5.0] * 15
    pd.testing.assert_frame_equal(table, rows())


@pytest.mark.parametrize("mode", ["one_class", "few_rows"])
def test_warmup_requires_both_classes_and_two_hundred_rows(mode: str) -> None:
    table = rows()
    if mode == "one_class":
        table["appearance_target"] = 1.0
    else:
        table = table.loc[table.player_id < 10].copy()
    result = recalibrate_appearance(table)
    assert not result.training_counts.fitted.any()
    pd.testing.assert_series_equal(result.points, table.control_expected_points)


def test_fallback_and_blank_do_not_train_or_change() -> None:
    table = rows()
    table.loc[table.player_id == 0, ["composition_route", "control_expected_points"]] = [
        "direct_control",
        np.nan,
    ]
    table.loc[table.player_id == 1, ["fixture_count", "control_expected_points"]] = [0, 0.0]
    result = recalibrate_appearance(table)
    untouched = table.player_id < 2
    pd.testing.assert_series_equal(
        result.points[untouched], table.control_expected_points[untouched]
    )
    assert result.training_counts.iloc[8].earlier_rows == 224
    assert not result.eligible[untouched].any()


@pytest.mark.parametrize(
    "column,value",
    [
        ("appearance_probability", np.nan),
        ("appearance_probability", 1.1),
        ("appearance_target", 0.5),
        ("control_expected_points", np.inf),
        ("expected_points_if_appearance", np.nan),
    ],
)
def test_invalid_component_is_refused_not_dropped(column: str, value: float) -> None:
    table = rows()
    table.loc[0, column] = value
    with pytest.raises(ValueError, match="numeric contract"):
        recalibrate_appearance(table)


def test_holdout_reordered_and_duplicate_inputs_are_refused() -> None:
    table = rows()
    with pytest.raises(ValueError, match="chronological"):
        recalibrate_appearance(table.iloc[::-1])
    with pytest.raises(ValueError, match="keys must be unique"):
        recalibrate_appearance(pd.concat([table, table.iloc[:1]], ignore_index=True))
    table.loc[0, "season"] = "2025-26"
    with pytest.raises(ValueError, match="four frozen"):
        recalibrate_appearance(table)


def test_fixed_reliability_bins_include_one_and_preserve_empty_readings() -> None:
    result = reliability(pd.Series([0.0, 0.1, 1.0]), pd.Series([0.0, 1.0, 1.0]))
    assert result["rows"] == 3
    assert result["brier"] == pytest.approx(0.27)
    bins = result["bins"]
    assert isinstance(bins, list)
    assert [row["rows"] for row in bins] == [1, 1, 0, 0, 0, 0, 0, 0, 0, 1]
    assert bins[2]["observed_appearance"] is None
    assert bins[9]["mean_prediction"] == 1.0
