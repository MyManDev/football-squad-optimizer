"""Descriptive scoring rules for Phase C appearance probabilities."""

import math

import pandas as pd
import pytest

from squadopt.evaluation import EvaluationValidationError, evaluate_appearance_snapshot
from squadopt.prediction import (
    ComponentPredictionSnapshot,
    PredictionProvenance,
    prepare_component_prediction,
)


def _snapshot() -> ComponentPredictionSnapshot:
    components = pd.DataFrame(
        {
            "player_id": [1, 2, 3, 4, 5, 6],
            "fixture_count": [1, 1, 1, 1, 1, 0],
            "appearance_probability": [0.0, 0.25, 0.75, 1.0, float("nan"), 0.0],
            "expected_minutes_if_appearance": [0.0, 80.0, 80.0, 80.0, float("nan"), 0.0],
            "expected_points_if_appearance": [0.0, 4.0, 4.0, 4.0, float("nan"), 0.0],
            "fallback_expected_points": [
                float("nan"),
                float("nan"),
                float("nan"),
                float("nan"),
                3.0,
                float("nan"),
            ],
            "composition_route": [
                "component_model",
                "component_model",
                "component_model",
                "component_model",
                "direct_control",
                "component_model",
            ],
            "evidence_status": ["not_requested"] * 6,
        }
    )
    provenance = PredictionProvenance(
        model_name="appearance-control",
        model_version="v1",
        feature_contract_version="features-v1",
        training_cutoff="2024-25:GW38",
        training_data_fingerprint="a" * 64,
    )
    return prepare_component_prediction(
        components,
        provenance,
        decision_timestamp_utc="2026-09-01T12:00:00Z",
    )


def _outcomes() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "player_id": [1, 2, 3, 4, 5, 6],
            "minutes": [0.0, 0.0, 90.0, 90.0, 45.0, 0.0],
        }
    )


def test_scores_only_available_non_blank_probabilities() -> None:
    result = evaluate_appearance_snapshot(_snapshot(), _outcomes())

    assert result.population_rows == 6
    assert result.eligible_rows == 5
    assert result.scored_rows == 4
    assert result.direct_control_rows == 1
    assert result.blank_rows == 1
    assert result.probability_coverage == pytest.approx(0.8)
    assert result.brier_score == pytest.approx(0.03125)
    assert result.mean_probability == pytest.approx(0.5)
    assert result.appearance_rate == pytest.approx(0.5)
    assert result.mean_calibration_bias == pytest.approx(0.0)


def test_positive_mean_calibration_bias_means_overprediction() -> None:
    outcomes = _outcomes()
    outcomes.loc[outcomes["player_id"] == 3, "minutes"] = 0.0

    result = evaluate_appearance_snapshot(_snapshot(), outcomes)

    assert result.mean_probability == pytest.approx(0.5)
    assert result.appearance_rate == pytest.approx(0.25)
    assert result.mean_calibration_bias == pytest.approx(0.25)


def test_log_loss_uses_the_frozen_clipping_epsilon() -> None:
    result = evaluate_appearance_snapshot(_snapshot(), _outcomes())
    expected = -(math.log(1.0 - 1e-6) + math.log(0.75) + math.log(0.75) + math.log(1 - 1e-6)) / 4

    assert result.log_loss == pytest.approx(expected)


def test_reliability_bins_are_fixed_and_include_probability_one() -> None:
    result = evaluate_appearance_snapshot(_snapshot(), _outcomes())

    assert len(result.reliability_bins) == 10
    assert result.reliability_bins[0].observations == 1
    assert result.reliability_bins[2].observations == 1
    assert result.reliability_bins[7].observations == 1
    assert result.reliability_bins[9].observations == 1
    assert result.reliability_bins[1].mean_probability is None


def test_missing_labels_are_excluded_without_becoming_absences() -> None:
    outcomes = _outcomes()
    outcomes.loc[outcomes["player_id"] == 2, "minutes"] = pd.NA

    result = evaluate_appearance_snapshot(_snapshot(), outcomes)

    assert result.missing_label_rows == 1
    assert result.eligible_rows == 4
    assert result.scored_rows == 3
    assert result.probability_coverage == pytest.approx(0.75)


def test_exclusion_counts_reconcile_without_blank_missing_overlap() -> None:
    outcomes = _outcomes()
    outcomes.loc[outcomes["player_id"].isin([2, 6]), "minutes"] = pd.NA

    result = evaluate_appearance_snapshot(_snapshot(), outcomes)

    assert result.missing_label_rows == 1
    assert result.blank_rows == 1
    assert (
        result.scored_rows
        + result.direct_control_rows
        + result.missing_label_rows
        + result.blank_rows
        == result.population_rows
    )


def test_an_observed_appearance_in_a_declared_blank_is_reported() -> None:
    outcomes = _outcomes()
    outcomes.loc[outcomes["player_id"] == 6, "minutes"] = 10.0

    result = evaluate_appearance_snapshot(_snapshot(), outcomes)

    assert result.blank_appearance_violations == 1
    assert result.scored_rows == 4


def test_no_available_probability_returns_coverage_without_inventing_scores() -> None:
    snapshot = _snapshot()
    outcomes = _outcomes()
    direct = snapshot.table.loc[snapshot.table["player_id"] == 5]
    only_direct = prepare_component_prediction(
        direct,
        snapshot.provenance,
        decision_timestamp_utc=snapshot.decision_timestamp_utc,
    )

    result = evaluate_appearance_snapshot(only_direct, outcomes.loc[outcomes["player_id"] == 5])

    assert result.eligible_rows == 1
    assert result.scored_rows == 0
    assert result.probability_coverage == 0.0
    assert result.brier_score is None
    assert result.log_loss is None


def test_no_eligible_rows_reports_missing_metrics_not_zeroes() -> None:
    snapshot = _snapshot()
    outcomes = _outcomes()
    blank = snapshot.table.loc[snapshot.table["player_id"] == 6]
    only_blank = prepare_component_prediction(
        blank,
        snapshot.provenance,
        decision_timestamp_utc=snapshot.decision_timestamp_utc,
    )

    result = evaluate_appearance_snapshot(only_blank, outcomes.loc[outcomes["player_id"] == 6])

    assert result.eligible_rows == 0
    assert result.probability_coverage is None
    assert result.brier_score is None
    assert result.mean_calibration_bias is None


@pytest.mark.parametrize("minutes", [-1.0, float("inf"), "not-a-number"])
def test_invalid_settled_minutes_are_rejected(minutes: object) -> None:
    outcomes = _outcomes().astype({"minutes": "object"})
    outcomes.loc[0, "minutes"] = minutes

    with pytest.raises(EvaluationValidationError, match="minutes"):
        evaluate_appearance_snapshot(_snapshot(), outcomes)


def test_outcome_ids_must_match_the_snapshot_exactly() -> None:
    with pytest.raises(EvaluationValidationError, match=r"match.*exactly"):
        evaluate_appearance_snapshot(_snapshot(), _outcomes().iloc[:-1])


def test_duplicate_outcome_ids_are_rejected() -> None:
    outcomes = _outcomes()
    outcomes.loc[1, "player_id"] = 1

    with pytest.raises(EvaluationValidationError, match="repeated"):
        evaluate_appearance_snapshot(_snapshot(), outcomes)


def test_inputs_are_not_mutated() -> None:
    snapshot = _snapshot()
    snapshot_before = snapshot.table.copy(deep=True)
    outcomes = _outcomes()
    outcomes_before = outcomes.copy(deep=True)

    evaluate_appearance_snapshot(snapshot, outcomes)

    pd.testing.assert_frame_equal(snapshot.table, snapshot_before)
    pd.testing.assert_frame_equal(outcomes, outcomes_before)
