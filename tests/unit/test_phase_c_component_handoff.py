"""Tests for the Phase C OOF table/roster consumer boundary."""

import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest

from squadopt.evaluation import (
    OOF_ARTIFACT_COLUMNS,
    ROSTER_ARTIFACT_COLUMNS,
    EvaluationValidationError,
    evaluate_component_oof,
    read_phase_c_component_handoff,
)


def _artifacts(directory: Path) -> tuple[Path, Path, Path]:
    table = pd.DataFrame(
        {
            "contract_version": pd.Series(["phase_c_component_oof_v1"], dtype="string"),
            "model_version": pd.Series(["phase-c-component-control-v1"], dtype="string"),
            "feature_contract_version": pd.Series(
                ["phase_c_component_form_window_v1"], dtype="string"
            ),
            "target_contract_version": pd.Series(["phase_c_component_targets_v1"], dtype="string"),
            "dataset_contract_version": pd.Series(["phase_c_component_dataset_v1"], dtype="string"),
            "season": pd.Series(["2022-23"], dtype="string"),
            "target_gameweek": pd.Series([2], dtype="int64"),
            "decision_timestamp_utc": pd.Series([pd.NA], dtype="string"),
            "fold_id": pd.Series(["2022-23-gw02"], dtype="string"),
            "player_id": pd.Series([101], dtype="int64"),
            "fixture_count": pd.Series([1], dtype="int64"),
            "appearance_target": pd.Series([1], dtype="int64"),
            "start_target": pd.Series([pd.NA], dtype="Int64"),
            "minutes_target": pd.Series([90], dtype="Int64"),
            "points_target": pd.Series([6.0], dtype="Float64"),
            "appearance_probability": pd.Series([0.8], dtype="Float64"),
            "q_start_given_appearance": pd.Series([pd.NA], dtype="Float64"),
            "start_probability": pd.Series([pd.NA], dtype="Float64"),
            "expected_minutes_if_appearance": pd.Series([80.0], dtype="Float64"),
            "raw_expected_points_if_appearance": pd.Series([5.0], dtype="Float64"),
            "expected_points_if_appearance": pd.Series([5.0], dtype="Float64"),
            "control_expected_points": pd.Series([4.0], dtype="Float64"),
            "composition_route": pd.Series(["component_model"], dtype="string"),
            "evidence_status": pd.Series(["not_requested"], dtype="string"),
        }
    ).loc[:, list(OOF_ARTIFACT_COLUMNS)]
    roster = pd.DataFrame(
        {
            "contract_version": pd.Series(["phase_c_decision_roster_v1"], dtype="string"),
            "season": pd.Series(["2022-23"], dtype="string"),
            "target_gameweek": pd.Series([2], dtype="int64"),
            "fold_id": pd.Series(["2022-23-gw02"], dtype="string"),
            "player_id": pd.Series([101], dtype="int64"),
            "name": pd.Series(["Synthetic Player"], dtype="string"),
            "team_id": pd.Series(["T01"], dtype="string"),
            "position": pd.Series(["MID"], dtype="string"),
            "price_tenths": pd.Series([65], dtype="int64"),
        }
    ).loc[:, list(ROSTER_ARTIFACT_COLUMNS)]
    table_path = directory / "phase_c_component_oof_v1.csv"
    roster_path = directory / "phase_c_component_oof_v1.roster.csv"
    manifest_path = directory / "phase_c_component_oof_v1.manifest.json"
    table.to_csv(table_path, index=False, lineterminator="\n")
    roster.to_csv(roster_path, index=False, lineterminator="\n")
    manifest = {
        "contract_version": "phase_c_component_oof_v1",
        "model_version": "phase-c-component-control-v1",
        "feature_contract_version": "phase_c_component_form_window_v1",
        "target_contract_version": "phase_c_component_targets_v1",
        "dataset_contract_version": "phase_c_component_dataset_v1",
        "roster_contract_version": "phase_c_decision_roster_v1",
        "development_seasons": ["2021-22", "2022-23"],
        "fold_ids": ["2022-23-gw02"],
        "fold_count": 1,
        "scored_fold_count": 1,
        "folds": [
            {
                "fold_id": "2022-23-gw02",
                "season": "2022-23",
                "target_gameweek": 2,
                "decision_timestamp_utc": None,
                "training_cutoff_utc": None,
                "training_cutoff_fold_id": "2021-22-gw38",
                "training_fold_ids": ["2021-22-gw38"],
                "training_key_digest": "a" * 64,
                "training_rows": 100,
                "scored_rows": 1,
                "model_fitted": True,
                "model_version": "phase-c-component-control-v1",
                "feature_contract_version": "phase_c_component_form_window_v1",
                "target_contract_version": "phase_c_component_targets_v1",
            }
        ],
        "repository_commit": "b" * 40,
        "working_tree_dirty": False,
        "table_file": table_path.name,
        "table_sha256": hashlib.sha256(table_path.read_bytes()).hexdigest(),
        "table_columns": list(table.columns),
        "table_column_dtypes": {str(column): str(dtype) for column, dtype in table.dtypes.items()},
        "row_count": 1,
        "roster_file": roster_path.name,
        "roster_sha256": hashlib.sha256(roster_path.read_bytes()).hexdigest(),
        "roster_columns": list(roster.columns),
        "roster_column_dtypes": {
            str(column): str(dtype) for column, dtype in roster.dtypes.items()
        },
        "roster_row_count": 1,
        "locked_holdout_read": False,
        "locked_holdout_season": "2025-26",
    }
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8", newline="\n")
    return table_path, roster_path, manifest_path


def _document(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _write_document(path: Path, value: dict[str, object]) -> None:
    path.write_text(json.dumps(value), encoding="utf-8", newline="\n")


def test_reads_exact_handoff_and_supplies_position_to_the_scorer(tmp_path: Path) -> None:
    artifacts = _artifacts(tmp_path)
    handoff = read_phase_c_component_handoff(*artifacts)

    assert handoff.rows["position"].tolist() == ["MID"]
    assert handoff.roster["price_tenths"].tolist() == [65]
    assert handoff.manifest_sha256 == hashlib.sha256(artifacts[2].read_bytes()).hexdigest()
    assert handoff.model_version == "phase-c-component-control-v1"
    assert evaluate_component_oof(handoff.rows).overall.appearance.observations == 1


@pytest.mark.parametrize("which", ["table", "roster"])
def test_refuses_a_byte_change_in_either_csv(tmp_path: Path, which: str) -> None:
    table_path, roster_path, manifest_path = _artifacts(tmp_path)
    path = table_path if which == "table" else roster_path
    path.write_bytes(path.read_bytes() + b"\n")

    with pytest.raises(EvaluationValidationError, match="checksum"):
        read_phase_c_component_handoff(table_path, roster_path, manifest_path)


@pytest.mark.parametrize(
    "training,cutoff",
    [
        (["2022-23-gw02"], "2022-23-gw02"),
        (["2022-23-gw03"], "2022-23-gw03"),
        (["2021-22-gw38"], "2021-22-gw37"),
    ],
)
def test_refuses_invalid_fold_chronology(tmp_path: Path, training: list[str], cutoff: str) -> None:
    table_path, roster_path, manifest_path = _artifacts(tmp_path)
    document = _document(manifest_path)
    record = document["folds"][0]  # type: ignore[index]
    record["training_fold_ids"] = training  # type: ignore[index]
    record["training_cutoff_fold_id"] = cutoff  # type: ignore[index]
    _write_document(manifest_path, document)

    with pytest.raises(EvaluationValidationError, match=r"out of fold|cutoff"):
        read_phase_c_component_handoff(table_path, roster_path, manifest_path)


def test_refuses_roster_key_drift_even_when_counts_match(tmp_path: Path) -> None:
    table_path, roster_path, manifest_path = _artifacts(tmp_path)
    roster = pd.read_csv(roster_path)
    roster.loc[0, "player_id"] = 999
    roster.to_csv(roster_path, index=False, lineterminator="\n")
    document = _document(manifest_path)
    document["roster_sha256"] = hashlib.sha256(roster_path.read_bytes()).hexdigest()
    _write_document(manifest_path, document)

    with pytest.raises(EvaluationValidationError, match="keys do not match"):
        read_phase_c_component_handoff(table_path, roster_path, manifest_path)


def test_refuses_any_claim_that_the_locked_holdout_was_read(tmp_path: Path) -> None:
    table_path, roster_path, manifest_path = _artifacts(tmp_path)
    document = _document(manifest_path)
    document["locked_holdout_read"] = True
    _write_document(manifest_path, document)

    with pytest.raises(EvaluationValidationError, match="locked-holdout"):
        read_phase_c_component_handoff(table_path, roster_path, manifest_path)
