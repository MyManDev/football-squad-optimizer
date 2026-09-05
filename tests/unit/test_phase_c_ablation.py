"""Tests for exact-key descriptive Phase C evidence ablations."""

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

from squadopt.evaluation import evaluate_component_oof
from squadopt.experiments import ExperimentExecutionError
from squadopt.experiments.phase_c_ablation import (
    PhaseCArmDeclaration,
    evaluate_phase_c_ablations,
    phase_c_evaluation_rows_sha256,
)
from squadopt.experiments.phase_c_reporting import (
    phase_c_ablation_to_dict,
    phase_c_component_evaluation_to_dict,
)


def _component_rows() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "contract_version": ["phase_c_component_oof_v1"] * 4,
            "model_version": ["phase-c-component-control-v1"] * 4,
            "feature_contract_version": ["phase_c_component_form_window_v1"] * 4,
            "target_contract_version": ["phase_c_component_targets_v1"] * 4,
            "dataset_contract_version": ["phase_c_component_dataset_v1"] * 4,
            "season": ["2022-23", "2022-23", "2023-24", "2023-24"],
            "target_gameweek": [2, 2, 2, 2],
            "player_id": ["p1", "p2", "p1", "p2"],
            "decision_timestamp_utc": [pd.NA] * 4,
            "fold_id": ["2022-23-gw02"] * 2 + ["2023-24-gw02"] * 2,
            "position": ["GK", "MID", "GK", "MID"],
            "fixture_count": [1, 1, 1, 1],
            "appearance_target": [1, 0, 1, 0],
            "start_target": [1, 0, 1, 0],
            "minutes_target": [90, pd.NA, 80, pd.NA],
            "points_target": [6, pd.NA, 4, pd.NA],
            "composition_route": ["component_model"] * 4,
            "evidence_status": ["not_requested"] * 4,
            "appearance_probability": [0.8, 0.2, 0.7, 0.3],
            "q_start_given_appearance": [0.75, 0.5, 0.8, 0.5],
            "start_probability": [0.6, 0.1, 0.56, 0.15],
            "expected_minutes_if_appearance": [80, 30, 75, 30],
            "raw_expected_points_if_appearance": [6, 2, 5, 2],
            "expected_points_if_appearance": [6, 2, 5, 2],
            "control_expected_points": [4.8, 0.4, 3.5, 0.6],
        }
    )


def _declaration(
    rows: pd.DataFrame,
    arm_id: str,
    family: str,
    *,
    target_contract: str = "phase_c_component_targets_v1",
) -> PhaseCArmDeclaration:
    return PhaseCArmDeclaration(
        arm_id=arm_id,
        evidence_family=family,
        model_version=str(rows["model_version"].iloc[0]),
        feature_contract_version=str(rows["feature_contract_version"].iloc[0]),
        target_contract_version=target_contract,
        evaluation_rows_sha256=phase_c_evaluation_rows_sha256(rows),
    )


def _evaluate(base: pd.DataFrame, candidate: pd.DataFrame):
    candidate_rows = candidate.copy(deep=True)
    candidate_rows["evidence_status"] = "available"
    return evaluate_phase_c_ablations(
        _declaration(base, "component_base", "none"),
        base,
        [
            (
                _declaration(candidate_rows, "component_plus_elite", "elite"),
                candidate_rows,
            )
        ],
    )


def test_scores_single_family_arm_on_exact_component_base_keys() -> None:
    base = _component_rows()
    elite = base.copy(deep=True)
    elite["appearance_probability"] = [0.9, 0.1, 0.8, 0.2]
    elite["start_probability"] = elite["appearance_probability"] * elite["q_start_given_appearance"]
    elite["control_expected_points"] = (
        elite["appearance_probability"] * elite["raw_expected_points_if_appearance"]
    )

    result = _evaluate(base, elite)

    assert result.paired_rows == 4
    assert result.base.metrics.overall.appearance.brier_score == pytest.approx(0.065)
    assert result.candidates[0].metrics.overall.appearance.brier_score == pytest.approx(0.025)
    assert len(result.comparison_fingerprint) == 64


def test_row_order_does_not_change_table_or_comparison_identity() -> None:
    base = _component_rows()
    reversed_rows = base.iloc[::-1].reset_index(drop=True)

    first = _evaluate(base, base.copy(deep=True))
    second = _evaluate(reversed_rows, reversed_rows.copy(deep=True))

    assert phase_c_evaluation_rows_sha256(base) == phase_c_evaluation_rows_sha256(reversed_rows)
    assert first.comparison_fingerprint == second.comparison_fingerprint


def test_declared_digest_is_bound_to_the_exact_rows() -> None:
    base = _component_rows()
    candidate = base.copy(deep=True)
    declaration = _declaration(candidate, "component_plus_elite", "elite")
    candidate.loc[0, "appearance_probability"] = 0.9
    candidate.loc[0, "start_probability"] = 0.675
    candidate.loc[0, "control_expected_points"] = 5.4

    with pytest.raises(ExperimentExecutionError, match="does not match"):
        evaluate_phase_c_ablations(
            _declaration(base, "component_base", "none"),
            base,
            [(declaration, candidate)],
        )


def test_candidate_cannot_change_target_population() -> None:
    candidate = _component_rows()
    candidate.loc[0, "points_target"] = 99

    with pytest.raises(ExperimentExecutionError, match="points_target"):
        _evaluate(_component_rows(), candidate)


def test_candidate_cannot_shrink_a_prediction_eligibility_mask() -> None:
    candidate = _component_rows()
    candidate.loc[0, ["appearance_probability", "q_start_given_appearance"]] = pd.NA
    candidate.loc[0, "appearance_probability"] = 0.8
    candidate.loc[0, "start_probability"] = pd.NA

    with pytest.raises(ExperimentExecutionError, match="eligibility mask"):
        _evaluate(_component_rows(), candidate)


def test_all_arms_must_share_the_target_contract() -> None:
    base = _component_rows()
    candidate = _component_rows()

    with pytest.raises(ExperimentExecutionError, match="target_contract_version"):
        evaluate_phase_c_ablations(
            _declaration(base, "component_base", "none"),
            base,
            [
                (
                    _declaration(
                        candidate,
                        "component_plus_elite",
                        "elite",
                        target_contract="other-target-v1",
                    ),
                    candidate,
                )
            ],
        )


def test_missing_evidence_must_reproduce_the_component_base_row() -> None:
    base = _component_rows()
    candidate = base.copy(deep=True)
    candidate["evidence_status"] = "available"
    candidate.loc[0, "evidence_status"] = "missing"
    candidate.loc[0, "appearance_probability"] = 0.9
    candidate.loc[0, "start_probability"] = 0.675
    candidate.loc[0, "control_expected_points"] = 5.4

    with pytest.raises(ExperimentExecutionError, match="reproduce component_base"):
        evaluate_phase_c_ablations(
            _declaration(base, "component_base", "none"),
            base,
            [(_declaration(candidate, "component_plus_elite", "elite"), candidate)],
        )


def test_only_one_candidate_per_evidence_family_is_allowed() -> None:
    base = _component_rows()
    first = _component_rows()
    second = _component_rows()
    first["evidence_status"] = "available"
    second["evidence_status"] = "available"

    with pytest.raises(ExperimentExecutionError, match="one candidate"):
        evaluate_phase_c_ablations(
            _declaration(base, "component_base", "none"),
            base,
            [
                (_declaration(first, "elite-a", "elite"), first),
                (_declaration(second, "elite-b", "elite"), second),
            ],
        )


def test_report_is_descriptive_and_contains_missingness() -> None:
    result = _evaluate(_component_rows(), _component_rows())

    record = phase_c_ablation_to_dict(result)

    assert record["promotion_decision"] == "not_evaluated"
    overall = record["base"]["metrics"]["overall"]
    assert overall["missing_points_prediction_rows"] == 0
    assert len(overall["appearance"]["reliability_bins"]) == 10


def test_component_metrics_are_serialized_without_a_promotion_claim() -> None:
    result = evaluate_component_oof(_component_rows())

    record = phase_c_component_evaluation_to_dict(result)

    assert record["contract_version"] == "phase_c_component_metrics_v1"
    assert record["overall"]["population_rows"] == 4  # type: ignore[index]
    assert "promotion_decision" not in record


def test_inputs_are_not_mutated() -> None:
    base = _component_rows()
    candidate = _component_rows()
    base_before = base.copy(deep=True)
    candidate_before = candidate.copy(deep=True)

    _evaluate(base, candidate)

    assert_frame_equal(base, base_before)
    assert_frame_equal(candidate, candidate_before)
