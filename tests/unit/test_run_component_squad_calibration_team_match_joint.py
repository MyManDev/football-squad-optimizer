"""The joint team-match candidate on the calibration runner: the flag, the pinned v1 table,
its own fidelity verification, and the two control arms drawn beside it."""

import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from scripts.run_component_squad_calibration import (
    CANDIDATE_REPORT_VERSION,
    DEFAULT_OUTPUT,
    JOINT_PAIRED_DIFFERENCE_POLICY,
    TEAM_MATCH_JOINT_PREREG,
    BindingCalibrationError,
    _candidate_from_arguments,
    _candidate_record,
    _development_from_arguments,
    _history_rows,
    _joint_readings,
    _load_verified_candidate_fidelity,
    _measure_fold,
    _paired_differences,
    _pooled_diagnostics,
    _reference_from_arguments,
    _report_contract_version,
    _sampler_keywords,
    _sampler_record,
)
from tests.unit.test_run_component_squad_calibration import _handoff, _squad_positions
from tests.unit.test_run_component_squad_calibration_team_match_block import (
    DIGESTS,
    REFERENCE,
    _candidate_fidelity_document,
    _handoff_with_clubs,
)

from squadopt.scenarios import ScenarioConfig
from squadopt.scenarios.components import (
    COMPONENT_SCENARIO_CONTRACT_VERSION,
    TEAM_MATCH_BLOCK_CONTRACT_VERSION,
    TEAM_MATCH_JOINT_CONTRACT_VERSION,
    TeamMatchBlockConfig,
    TeamMatchJointConfig,
)


def _arguments(**overrides: object) -> SimpleNamespace:
    fields: dict[str, object] = {
        "phase_c_contract": "v1",
        "fidelity": Path("fidelity.json"),
        "folds": None,
        "team_match_block": False,
        "team_match_joint": True,
        "conditional_residual_fraction": None,
        "conditional_residual_minimum_rows": None,
        "json_output": Path("candidate.json"),
        **DIGESTS,
    }
    fields.update(overrides)
    return SimpleNamespace(**fields)


def _joint_fidelity_document() -> dict[str, object]:
    document = _candidate_fidelity_document()
    document["sampler"] = {
        "contract_version": TEAM_MATCH_JOINT_CONTRACT_VERSION,
        "residual_selection": "team_match_joint",
        "conditional_residual_fraction": None,
        "conditional_residual_minimum_rows": None,
    }
    document["candidate_prereg_document"] = TEAM_MATCH_JOINT_PREREG
    return document


def test_the_flag_selects_the_joint_candidate_and_names_one_sampler() -> None:
    assert _candidate_from_arguments(_arguments()) == TeamMatchJointConfig()  # type: ignore[arg-type]
    assert _report_contract_version(TeamMatchJointConfig()) == CANDIDATE_REPORT_VERSION
    with pytest.raises(BindingCalibrationError, match="one"):
        _candidate_from_arguments(_arguments(team_match_block=True))  # type: ignore[arg-type]
    with pytest.raises(BindingCalibrationError, match="one"):
        _candidate_from_arguments(_arguments(conditional_residual_fraction=0.15))  # type: ignore[arg-type]
    with pytest.raises(BindingCalibrationError, match="binding artifact path"):
        _candidate_from_arguments(_arguments(json_output=DEFAULT_OUTPUT))  # type: ignore[arg-type]


def test_a_pinned_joint_run_needs_the_three_digests_and_stands_the_v1_refusal_aside() -> None:
    assert _reference_from_arguments(_arguments()) == REFERENCE  # type: ignore[arg-type]
    assert _development_from_arguments(_arguments()) is None  # type: ignore[arg-type]
    with pytest.raises(BindingCalibrationError, match="team-match-joint"):
        _reference_from_arguments(_arguments(expected_table_sha256=None))  # type: ignore[arg-type]
    assert _reference_from_arguments(_arguments(team_match_joint=False)) is None  # type: ignore[arg-type]


def test_the_sampler_and_candidate_records_name_the_joint_contract() -> None:
    assert _sampler_record(TeamMatchJointConfig()) == {
        "contract_version": TEAM_MATCH_JOINT_CONTRACT_VERSION,
        "conditional_residual_fraction": None,
        "conditional_residual_minimum_rows": None,
    }
    record = _candidate_record(TeamMatchJointConfig())
    assert record is not None
    assert record["sampler_contract_version"] == TEAM_MATCH_JOINT_CONTRACT_VERSION
    assert record["residual_selection"] == "team_match_joint"
    assert record["prereg_document"] == TEAM_MATCH_JOINT_PREREG
    assert record["binding"] is False
    assert _sampler_keywords(TeamMatchJointConfig()) == {"team_match_joint": TeamMatchJointConfig()}
    # The block record is what it was.
    block = _candidate_record(TeamMatchBlockConfig())
    assert block is not None and block["residual_selection"] == "team_match_block"


def test_a_joint_fidelity_record_is_verified_against_the_joint_sampler(tmp_path: Path) -> None:
    path = tmp_path / "joint_fidelity.json"
    path.write_text(json.dumps(_joint_fidelity_document()), encoding="utf-8")

    assert (
        len(_load_verified_candidate_fidelity(path, _handoff(), TeamMatchJointConfig(), REFERENCE))
        == 64
    )
    with pytest.raises(BindingCalibrationError, match="different sampler"):
        _load_verified_candidate_fidelity(path, _handoff(), TeamMatchBlockConfig(), REFERENCE)
    block_path = tmp_path / "block_fidelity.json"
    block_path.write_text(json.dumps(_candidate_fidelity_document()), encoding="utf-8")
    with pytest.raises(BindingCalibrationError, match="different sampler"):
        _load_verified_candidate_fidelity(block_path, _handoff(), TeamMatchJointConfig(), REFERENCE)


def test_the_history_rows_take_each_clubs_identity_from_the_roster_for_the_joint_candidate() -> (
    None
):
    handoff, _, _ = _handoff_with_clubs()
    rows = _history_rows(handoff, TeamMatchJointConfig())
    assert "team_id" in rows.columns and rows["team_id"].notna().all()
    assert "team_id" not in _history_rows(handoff, None).columns


def test_measure_fold_draws_the_joint_candidate_beside_both_control_arms() -> None:
    handoff, prepared, result = _handoff_with_clubs()
    # A few rested history rows, so the joint pool has non-appearances to inherit from.
    rows = handoff.rows.copy()
    rested = rows["fold_id"].eq("2021-22-gw05") & rows["player_id"].isin([2, 6, 12])
    rows.loc[rested, "appearance_target"] = 0
    rows.loc[rested, ["minutes_target", "points_target"]] = np.nan
    handoff = type(handoff)(
        rows=rows,
        roster=handoff.roster,
        table_sha256=handoff.table_sha256,
        roster_sha256=handoff.roster_sha256,
        manifest_sha256=handoff.manifest_sha256,
        repository_commit=handoff.repository_commit,
        model_version=handoff.model_version,
        feature_contract_version=handoff.feature_contract_version,
        target_contract_version=handoff.target_contract_version,
        dataset_contract_version=handoff.dataset_contract_version,
    )
    settings = ScenarioConfig(scenario_count=64)
    selected = tuple(_squad_positions())

    reading, record = _measure_fold(
        handoff,
        prepared,
        result,
        40.0,
        selected,
        settings,
        TeamMatchJointConfig(),
        control_arm=True,  # type: ignore[arg-type]
    )
    _, foundation = _measure_fold(handoff, prepared, result, 40.0, selected, settings, None)  # type: ignore[arg-type]
    _, block = _measure_fold(
        handoff,
        prepared,
        result,
        40.0,
        selected,
        settings,
        TeamMatchBlockConfig(),  # type: ignore[arg-type]
    )

    assert reading.fold_id == prepared.fold_id  # type: ignore[attr-defined]
    assert record["sampler_contract_version"] == TEAM_MATCH_JOINT_CONTRACT_VERSION
    control = record["control_arm"]
    assert control["sampler_contract_version"] == COMPONENT_SCENARIO_CONTRACT_VERSION  # type: ignore[index]
    assert control["scenario_fingerprint"] == foundation["scenario_fingerprint"]  # type: ignore[index]
    block_arm = record["block_arm"]
    assert block_arm["sampler_contract_version"] == TEAM_MATCH_BLOCK_CONTRACT_VERSION  # type: ignore[index]
    assert block_arm["scenario_fingerprint"] == block["scenario_fingerprint"]  # type: ignore[index]
    assert record["scenario_fingerprint"] not in (
        foundation["scenario_fingerprint"],
        block["scenario_fingerprint"],
    )
    assert record["realized_score"] == control["realized_score"] == block_arm["realized_score"]  # type: ignore[index]
    points = record["within_club_points_correlation"]
    assert points["pairs"] == 15 and set(points) == {"pairs", "candidate", "control", "block"}  # type: ignore[arg-type]
    appearance = record["within_club_appearance_correlation"]
    assert set(appearance) == {"pairs", "candidate", "control", "block"}  # type: ignore[arg-type]
    diagnostics = record["block_diagnostics"]
    assert diagnostics["team_match_joint_target_clubs"] == 5  # type: ignore[index]
    assert diagnostics["team_match_joint_blocks_per_fold_mean"] == 5.0  # type: ignore[index]
    assert "team_match_joint_pool_excluded_rows" not in diagnostics  # type: ignore[operator]
    assert record["pool_excluded_rows"]["direct_control_rows"] == 0  # type: ignore[index]
    assert "block_arm" not in block and "block_arm" not in foundation


def _fold_records() -> list[dict[str, object]]:
    def arm(pit: float, below: bool, fingerprint: str) -> dict[str, object]:
        return {
            "sampler_contract_version": fingerprint,
            "probability_integral_transform": pit,
            "realized_below_q10": below,
            "q10_score": 40.0,
            "scenario_standard_deviation": 10.0,
        }

    records: list[dict[str, object]] = []
    for index, (
        fold_id,
        pit,
        below,
        control_pit,
        control_below,
        block_pit,
        block_below,
    ) in enumerate(
        (
            ("2021-22-gw11", 0.50, False, 0.40, True, 0.60, False),
            ("2021-22-gw12", 0.30, True, 0.35, False, 0.30, True),
            ("2022-23-gw05", 0.96, False, 0.96, False, 0.90, False),
            ("2022-23-gw06", 0.04, True, 0.05, True, 0.04, True),
        )
    ):
        records.append(
            {
                "fold_id": fold_id,
                **arm(pit, below, TEAM_MATCH_JOINT_CONTRACT_VERSION),
                "control_arm": arm(control_pit, control_below, COMPONENT_SCENARIO_CONTRACT_VERSION),
                "block_arm": arm(block_pit, block_below, TEAM_MATCH_BLOCK_CONTRACT_VERSION),
                "within_club_points_correlation": {
                    "pairs": 3,
                    "candidate": 0.2,
                    "control": 0.0,
                    "block": 0.1 + index * 0.0,
                },
                "within_club_appearance_correlation": {
                    "pairs": 3,
                    "candidate": 0.3,
                    "control": 0.0,
                    "block": 0.0,
                },
                "block_diagnostics": {"team_match_joint_redraw_rate": 0.1},
            }
        )
    return records


def test_the_joint_readings_report_both_controls_the_tails_the_flags_and_the_gate() -> None:
    readings = _joint_readings(_fold_records())

    assert readings["candidate_prereg_document"] == TEAM_MATCH_JOINT_PREREG
    block = readings["block_arm"]
    assert block["sampler_contract_version"] == TEAM_MATCH_BLOCK_CONTRACT_VERSION  # type: ignore[index]
    assert block["realized_below_lower_quantile_count"] == 2  # type: ignore[index]
    tails = readings["pit_tails"]
    assert tails["candidate"]["pit_at_or_above_0_95_count"] == 1  # type: ignore[index]
    assert tails["candidate"]["pit_at_or_below_0_05_count"] == 1  # type: ignore[index]
    assert tails["block_arm"]["pit_at_or_above_0_95_count"] == 0  # type: ignore[index]
    flags = readings["tail_flag_changes"]["against_control_arm"]  # type: ignore[index]
    assert flags["tail_flag"] == {
        "wins_left_the_tail": ["2021-22-gw11"],
        "losses_entered_the_tail": ["2021-22-gw12"],
        "ties": 2,
    }
    # gw11 closer to the centre, gw12 and gw06 farther, gw05 the same distance.
    assert flags["pit_distance_from_centre"] == {"wins": 1, "ties": 1, "losses": 2}
    against_block = readings["tail_flag_changes"]["against_block_arm"]  # type: ignore[index]
    assert against_block["tail_flag"]["ties"] == 4
    gate = readings["gate"]
    assert gate["g1_s1_mean_pit_within_bounds"]["value"] == pytest.approx(0.45)  # type: ignore[index]
    assert gate["g1_s1_mean_pit_within_bounds"]["holds"] is True  # type: ignore[index]
    assert gate["g2_s2_lower_tail_rate_within_bounds"]["count"] == 2  # type: ignore[index]
    assert gate["g2_s2_lower_tail_rate_within_bounds"]["holds"] is False  # type: ignore[index]
    g3 = gate["g3_not_worse_than_the_foundation"]  # type: ignore[index]
    assert g3["candidate_lower_tail_count"] == 2 and g3["control_lower_tail_count"] == 2
    assert g3["lower_tail_count_not_greater"] is True
    assert g3["mean_pit_not_farther_from_centre"] is True and g3["holds"] is True
    g4 = gate["g4_not_worse_than_the_block_sampler_descriptive"]  # type: ignore[index]
    # The block arm's mean PIT (0.46) sits closer to the centre than the candidate's (0.45).
    assert g4["mean_pit_not_farther_from_centre"] is False and g4["holds"] is False
    appearance = readings["within_club_appearance_correlation"]
    assert appearance["candidate_mean"] == pytest.approx(0.3)  # type: ignore[index]
    assert readings["within_club_points_correlation_block_mean"] == pytest.approx(0.1)
    against = readings["paired_differences_against_block"]
    assert against["against"] == "block_arm"  # type: ignore[index]
    assert against["bootstrap"]["resamples"] == JOINT_PAIRED_DIFFERENCE_POLICY.bootstrap_resamples  # type: ignore[index]
    assert "decision_level_reading" in readings


def test_the_paired_differences_keep_the_block_defaults_and_take_the_joint_policy() -> None:
    records = _fold_records()
    default = _paired_differences(records)
    joint = _paired_differences(
        records,
        candidate_id=TEAM_MATCH_JOINT_CONTRACT_VERSION,
        policy=JOINT_PAIRED_DIFFERENCE_POLICY,
    )

    assert default["against"] == "control_arm" and default["bootstrap"]["resamples"] == 2_000  # type: ignore[index]
    assert joint["bootstrap"]["resamples"] == 5_000  # type: ignore[index]
    assert default["realized_below_q10"]["mean"] == joint["realized_below_q10"]["mean"] == 0.0  # type: ignore[index]
    pooled = _pooled_diagnostics(records)
    assert pooled["within_club_points_correlation"]["candidate_mean"] == pytest.approx(0.2)  # type: ignore[index]
