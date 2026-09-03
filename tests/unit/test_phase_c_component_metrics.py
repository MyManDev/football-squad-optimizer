"""Tests for Phase C component metrics over chronological OOF rows."""

import math

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

from squadopt.evaluation import EvaluationValidationError, evaluate_component_oof


def _rows() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "season": ["2022-23", "2022-23", "2022-23", "2023-24", "2023-24", "2023-24"],
            "target_gameweek": [2, 2, 2, 3, 3, 3],
            "player_id": ["p1", "p2", "p3", "p1", "p2", "p3"],
            "fold_id": ["2022-23-gw02"] * 3 + ["2023-24-gw03"] * 3,
            "position": ["GK", "DEF", "MID", "GK", "DEF", "MID"],
            "fixture_count": [1, 1, 1, 2, 0, 1],
            "appearance_target": [1, 1, 0, 1, 0, 1],
            "start_target": [1, 0, 0, pd.NA, 0, pd.NA],
            "minutes_target": [90, 30, 0, 120, 0, 20],
            "points_target": [7, 1, 0, -1, 0, 2],
            "appearance_probability": [0.8, 0.4, 0.2, 0.5, 0.0, pd.NA],
            "q_start_given_appearance": [0.75, 0.25, 0.5, pd.NA, 0.0, pd.NA],
            "start_probability": [0.6, 0.1, 0.1, pd.NA, 0.0, pd.NA],
            "expected_minutes_if_appearance": [80, 50, 50, 150, 0, pd.NA],
            "expected_minutes": [64, 20, 10, 75, 0, pd.NA],
            "expected_points_if_appearance": [6, 5, 2.5, 0, 0, pd.NA],
            "expected_points": [4.8, 2, 0.5, 0, 0, pd.NA],
        }
    )


def test_scores_component_metrics_without_merging_conditional_populations() -> None:
    result = evaluate_component_oof(_rows())

    assert result.overall.population_rows == 6
    assert result.overall.blank_rows == 1
    assert result.overall.missing_appearance_prediction_rows == 1
    assert result.overall.missing_start_label_rows == 2
    assert result.overall.appearance.observations == 4
    assert result.overall.appearance.brier_score == pytest.approx(0.1725)
    assert result.overall.start.observations == 3
    assert result.overall.start.brier_score == pytest.approx(0.06)
    assert result.overall.start_given_appearance.observations == 2
    assert result.overall.start_given_appearance.brier_score == pytest.approx(0.0625)
    assert result.overall.minutes.observations == 4
    assert result.overall.minutes.mean_absolute_error == pytest.approx(22.75)
    assert result.overall.minutes.root_mean_squared_error == pytest.approx(math.sqrt(725.25))
    assert result.overall.minutes_if_appearance.observations == 3
    assert result.overall.points.observations == 4
    assert result.overall.points_if_appearance.observations == 3


def test_reports_fixed_appearance_bins_and_descriptive_slices() -> None:
    result = evaluate_component_oof(_rows())

    assert len(result.overall.appearance.reliability_bins) == 10
    assert result.overall.appearance.reliability_bins[8].observations == 1
    assert tuple(result.by_season) == ("2022-23", "2023-24")
    assert tuple(result.by_position) == ("DEF", "GK", "MID")
    assert tuple(result.by_fixture_group) == ("blank", "double_plus", "single")
    assert result.by_fixture_group["blank"].appearance.observations == 0


def test_start_probability_must_be_structurally_composed() -> None:
    rows = _rows()
    rows.loc[0, "start_probability"] = 0.7

    with pytest.raises(EvaluationValidationError, match="must equal"):
        evaluate_component_oof(rows)


@pytest.mark.parametrize(
    "column,value",
    [("expected_minutes", 63.0), ("expected_points", 4.7)],
)
def test_reduced_form_predictions_must_be_structurally_composed(column: str, value: float) -> None:
    rows = _rows()
    rows.loc[0, column] = value

    with pytest.raises(EvaluationValidationError, match="must equal"):
        evaluate_component_oof(rows)


def test_start_probability_and_conditional_probability_are_jointly_available() -> None:
    rows = _rows()
    rows.loc[0, "q_start_given_appearance"] = pd.NA

    with pytest.raises(EvaluationValidationError, match="available together"):
        evaluate_component_oof(rows)


def test_verified_start_must_imply_appearance() -> None:
    rows = _rows()
    rows.loc[2, "start_target"] = 1

    with pytest.raises(EvaluationValidationError, match="must imply"):
        evaluate_component_oof(rows)


def test_appearance_label_must_match_realized_minutes() -> None:
    rows = _rows()
    rows.loc[0, "appearance_target"] = 0

    with pytest.raises(EvaluationValidationError, match="minutes > 0"):
        evaluate_component_oof(rows)


def test_blank_gameweek_predictions_must_be_zero() -> None:
    rows = _rows()
    rows.loc[4, "points_target"] = 1

    with pytest.raises(EvaluationValidationError, match="Blank-gameweek"):
        evaluate_component_oof(rows)


def test_minutes_predictions_respect_multi_fixture_support() -> None:
    rows = _rows()
    rows.loc[3, "expected_minutes_if_appearance"] = 181
    rows.loc[3, "expected_minutes"] = 90.5

    with pytest.raises(EvaluationValidationError, match=r"90 \* fixture_count"):
        evaluate_component_oof(rows)


def test_oof_keys_must_be_unique() -> None:
    rows = pd.concat([_rows(), _rows().iloc[[0]]], ignore_index=True)

    with pytest.raises(EvaluationValidationError, match="keys must be unique"):
        evaluate_component_oof(rows)


def test_locked_holdout_is_rejected() -> None:
    rows = _rows()
    rows["season"] = "2025-26"

    with pytest.raises(EvaluationValidationError, match="locked 2025-26"):
        evaluate_component_oof(rows)


def test_mixed_valid_and_invalid_positions_are_rejected() -> None:
    rows = _rows()
    rows.loc[0, "position"] = "WING"

    with pytest.raises(EvaluationValidationError, match="position"):
        evaluate_component_oof(rows)


def test_missing_start_labels_are_not_scored_as_zero() -> None:
    rows = _rows()
    rows.loc[3, "start_target"] = pd.NA
    rows.loc[3, ["q_start_given_appearance", "start_probability"]] = 0.0

    result = evaluate_component_oof(rows)

    assert result.overall.start.observations == 3
    assert result.overall.missing_start_label_rows == 2


def test_input_is_not_mutated_and_order_does_not_change_scores() -> None:
    rows = _rows()
    before = rows.copy(deep=True)

    first = evaluate_component_oof(rows)
    second = evaluate_component_oof(rows.iloc[::-1].reset_index(drop=True))

    assert_frame_equal(rows, before)
    assert first == second
