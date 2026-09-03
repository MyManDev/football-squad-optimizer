"""Tests for exact-key Phase C decision-level comparison."""

from dataclasses import replace

import pandas as pd
import pytest

from squadopt.evaluation import (
    EvaluationConfig,
    EvaluationFold,
    EvaluationValidationError,
    PhaseCComponentHandoff,
    ScoringPolicy,
    evaluate_phase_c_component_decisions,
    prepare_phase_c_component_folds,
)
from squadopt.optimization import OptimizationConfig


def _players() -> pd.DataFrame:
    positions = ["GK", "GK", *(["DEF"] * 5), *(["MID"] * 5), *(["FWD"] * 3)]
    return pd.DataFrame(
        {
            "player_id": list(range(1, 16)),
            "name": [f"P{item}" for item in range(1, 16)],
            "team_id": [f"T{item}" for item in range(1, 16)],
            "position": positions,
            "price_tenths": [50] * 15,
        }
    )


def _handoff() -> PhaseCComponentHandoff:
    roster = _players().assign(
        contract_version="phase_c_decision_roster_v1",
        season="2022-23",
        target_gameweek=2,
        fold_id="2022-23-gw02",
    )[
        [
            "contract_version",
            "season",
            "target_gameweek",
            "fold_id",
            "player_id",
            "name",
            "team_id",
            "position",
            "price_tenths",
        ]
    ]
    rows = pd.DataFrame(
        {
            "contract_version": ["phase_c_component_oof_v1"] * 15,
            "model_version": ["phase-c-component-control-v1"] * 15,
            "feature_contract_version": ["phase-c-features-v1"] * 15,
            "target_contract_version": ["phase-c-targets-v1"] * 15,
            "dataset_contract_version": ["phase-c-dataset-v1"] * 15,
            "season": ["2022-23"] * 15,
            "target_gameweek": [2] * 15,
            "decision_timestamp_utc": [pd.NA] * 15,
            "fold_id": ["2022-23-gw02"] * 15,
            "player_id": list(range(1, 16)),
            "fixture_count": [1] * 15,
            "appearance_target": [1] * 15,
            "start_target": [pd.NA] * 15,
            "minutes_target": [90] * 15,
            "points_target": [2] * 15,
            "appearance_probability": [1.0] * 14 + [pd.NA],
            "q_start_given_appearance": [pd.NA] * 15,
            "start_probability": [pd.NA] * 15,
            "expected_minutes_if_appearance": [90.0] * 14 + [pd.NA],
            "raw_expected_points_if_appearance": [3.0] * 14 + [pd.NA],
            "expected_points_if_appearance": [3.0] * 14 + [pd.NA],
            "control_expected_points": [3.0] * 14 + [pd.NA],
            "composition_route": ["component_model"] * 14 + ["direct_control"],
            "evidence_status": ["not_requested"] * 15,
            "position": _players()["position"],
        }
    )
    return PhaseCComponentHandoff(rows, roster, "a" * 64, "b" * 64, "c" * 40)


def _control() -> EvaluationFold:
    projection = _players().copy(deep=True)
    projection["expected_points"] = [2.0] * 14 + [9.0]
    realized = pd.DataFrame(
        {"player_id": list(range(1, 16)), "total_points": [2.0] * 15, "minutes": [90] * 15}
    )
    return EvaluationFold("2022-23-gw02", projection, realized)


def _config() -> EvaluationConfig:
    return EvaluationConfig(
        optimization_config=OptimizationConfig(solver_time_limit_seconds=2.0),
        scoring_policy=ScoringPolicy.OFFICIAL_AUTOSUB_CAPTAIN_V2,
    )


def test_direct_route_uses_the_exact_key_control_fallback() -> None:
    folds = prepare_phase_c_component_folds(_handoff(), [_control()])

    projection = folds[0].projections.set_index("player_id")
    assert projection.loc[1, "expected_points"] == 3.0
    assert projection.loc[15, "expected_points"] == 9.0
    assert folds[0].metadata["direct_control_rows"] == 1


def test_comparison_uses_official_scoring_and_reports_no_promotion() -> None:
    control = _control()
    historical = replace(
        control,
        realized_points=control.realized_points.loc[:, ["player_id", "total_points"]],
    )

    result = evaluate_phase_c_component_decisions(_handoff(), [historical], _config())

    assert result.diagnostics.attempted_folds == 1
    assert result.diagnostics.comparable_folds == 1
    assert result.diagnostics.mean_difference == 0.0
    assert result.diagnostics.ties == 1
    assert isinstance(result.diagnostics.candidate_vice_captain_recoveries, int)
    assert result.control.config.scoring_policy is ScoringPolicy.OFFICIAL_AUTOSUB_CAPTAIN_V2


def test_control_pool_must_match_the_handoff_exactly() -> None:
    control = _control()
    smaller = replace(control, projections=control.projections.iloc[:-1])

    with pytest.raises(EvaluationValidationError, match=r"exactly cover|outside"):
        prepare_phase_c_component_folds(_handoff(), [smaller])


def test_control_outcomes_cannot_change_handoff_targets() -> None:
    control = _control()
    changed = control.realized_points.copy(deep=True)
    changed.loc[0, "total_points"] = 99.0

    with pytest.raises(EvaluationValidationError, match="points outcomes"):
        prepare_phase_c_component_folds(_handoff(), [replace(control, realized_points=changed)])


def test_nonappearance_keeps_the_official_outcome_instead_of_inventing_zero() -> None:
    handoff = _handoff()
    rows = handoff.rows.copy(deep=True)
    rows.loc[14, "appearance_target"] = 0
    rows.loc[14, ["minutes_target", "points_target"]] = pd.NA
    control = _control()
    outcomes = control.realized_points.copy(deep=True)
    outcomes.loc[14, ["total_points", "minutes"]] = [-1.0, 0]

    prepared = prepare_phase_c_component_folds(
        replace(handoff, rows=rows),
        [replace(control, realized_points=outcomes)],
    )

    realized = prepared[0].realized_points.set_index("player_id")
    assert realized.loc[15, "total_points"] == -1.0
    assert realized.loc[15, "minutes"] == 0


def test_decision_comparison_requires_official_scoring_v2() -> None:
    with pytest.raises(EvaluationValidationError, match="official_autosub_captain_v2"):
        evaluate_phase_c_component_decisions(
            _handoff(),
            [_control()],
            EvaluationConfig(optimization_config=OptimizationConfig()),
        )
