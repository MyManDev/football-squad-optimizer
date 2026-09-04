"""Tests for the Phase D binding-run orchestration guards."""

import json
from pathlib import Path

import pandas as pd
import pytest
from scripts.run_component_squad_calibration import (
    BINDING_FOLD_COUNT,
    DIRECT_CONTROL_ABSTENTIONS,
    HISTORY_BURN_IN_FOLDS,
    PHASE_C_MANIFEST_SHA256,
    PHASE_C_ROSTER_SHA256,
    PHASE_C_TABLE_SHA256,
    BindingCalibrationError,
    _binding_population,
    _load_verified_fidelity,
    _selected_component_inputs,
)

from squadopt.evaluation import EvaluationFold
from squadopt.evaluation.component_handoff import PhaseCComponentHandoff
from squadopt.prediction.components import COMPONENT_MODEL_ROUTE


def _all_fold_ids() -> tuple[str, ...]:
    return (
        *(f"2021-22-gw{gameweek:02d}" for gameweek in range(2, 39)),
        *(f"2022-23-gw{gameweek:02d}" for gameweek in range(2, 39) if gameweek != 7),
        *(f"2023-24-gw{gameweek:02d}" for gameweek in range(2, 39)),
        *(f"2024-25-gw{gameweek:02d}" for gameweek in range(2, 39)),
    )


def _handoff() -> PhaseCComponentHandoff:
    return PhaseCComponentHandoff(
        rows=pd.DataFrame({"fold_id": _all_fold_ids()}),
        roster=pd.DataFrame(),
        table_sha256=PHASE_C_TABLE_SHA256,
        roster_sha256=PHASE_C_ROSTER_SHA256,
        manifest_sha256=PHASE_C_MANIFEST_SHA256,
        repository_commit="d" * 40,
        model_version="component-v1",
        feature_contract_version="features-v1",
        target_contract_version="targets-v1",
        dataset_contract_version="dataset-v1",
    )


def _fidelity_document() -> dict[str, object]:
    measured = _all_fold_ids()[len(HISTORY_BURN_IN_FOLDS) :]
    return {
        "contract_version": "phase_d_component_fidelity_v1",
        "diagnostic_only": True,
        "promotes_anything": False,
        "registers_any_threshold": False,
        "config": {
            "scenario_count": 1_000,
            "deterministic_seed": 0,
            "min_history_folds": 8,
        },
        "population": {
            "fold_count_total": 147,
            "fold_count_excluded": 9,
            "fold_count_measured": 138,
            "locked_holdout_season": "2025-26",
            "locked_holdout_rows_present": 0,
            "measured_fold_ids": list(measured),
        },
        "provenance": {
            "working_tree_dirty": False,
            "manifest_locked_holdout_read": False,
            "manifest_table_sha256": PHASE_C_TABLE_SHA256,
            "oof_table_sha256": PHASE_C_TABLE_SHA256,
            "manifest_roster_sha256": PHASE_C_ROSTER_SHA256,
            "roster_sha256": PHASE_C_ROSTER_SHA256,
            "manifest_sha256": PHASE_C_MANIFEST_SHA256,
            "model_version": "component-v1",
            "feature_contract_version": "features-v1",
        },
        "excluded_folds": [
            {"fold_id": fold_id, "reason": "burn-in"} for fold_id in HISTORY_BURN_IN_FOLDS
        ],
        "folds": [{"fold_id": fold_id, "mean": 1.0} for fold_id in measured],
        "warnings": [],
    }


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value), encoding="utf-8")


def _write_fidelity(path: Path, value: object, monkeypatch: pytest.MonkeyPatch) -> None:
    _write_json(path, value)
    # Unit tests exercise structure with a compact fixture; patching the digest avoids copying
    # the 6,135-line measured artifact into a second test fixture.
    from scripts import run_component_squad_calibration as runner

    monkeypatch.setattr(runner, "FIDELITY_ARTIFACT_SHA256", runner._sha256(path))


def test_verified_fidelity_is_bound_to_the_phase_c_handoff(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "fidelity.json"
    _write_fidelity(path, _fidelity_document(), monkeypatch)

    digest = _load_verified_fidelity(path, _handoff())

    assert len(digest) == 64


def test_fidelity_from_a_different_phase_c_table_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    document = _fidelity_document()
    provenance = document["provenance"]
    assert isinstance(provenance, dict)
    provenance["oof_table_sha256"] = "e" * 64
    path = tmp_path / "fidelity.json"
    _write_fidelity(path, document, monkeypatch)

    with pytest.raises(BindingCalibrationError, match="does not describe"):
        _load_verified_fidelity(path, _handoff())


def test_non_finite_fidelity_reading_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    document = _fidelity_document()
    folds = document["folds"]
    assert isinstance(folds, list)
    assert isinstance(folds[0], dict)
    folds[0]["mean"] = float("nan")
    path = tmp_path / "fidelity.json"
    _write_fidelity(path, document, monkeypatch)

    with pytest.raises(BindingCalibrationError, match="non-finite"):
        _load_verified_fidelity(path, _handoff())


def test_binding_population_is_exactly_the_preregistered_137_folds() -> None:
    eligible = _binding_population(_all_fold_ids(), DIRECT_CONTROL_ABSTENTIONS)

    assert len(eligible) == BINDING_FOLD_COUNT
    assert eligible[0] == "2021-22-gw11"
    assert eligible[-1] == "2024-25-gw38"
    assert "2021-22-gw15" not in eligible


def test_a_different_direct_control_abstention_is_rejected() -> None:
    with pytest.raises(BindingCalibrationError, match="direct-control"):
        _binding_population(_all_fold_ids(), ("2021-22-gw16",))


def test_a_missing_middle_fold_cannot_silently_change_the_denominator() -> None:
    fold_ids = list(_all_fold_ids())
    fold_ids.remove("2023-24-gw20")

    with pytest.raises(BindingCalibrationError, match="OOF fold population"):
        _binding_population(fold_ids, DIRECT_CONTROL_ABSTENTIONS)


def test_selected_component_inputs_align_the_same_fifteen_players() -> None:
    fold_id = "2021-22-gw11"
    ids = list(range(1, 16))
    rows = pd.DataFrame(
        {
            "fold_id": [fold_id] * 15,
            "player_id": ids,
            "position": ["GK", "GK", *(["DEF"] * 5), *(["MID"] * 5), *(["FWD"] * 3)],
            "fixture_count": [1] * 15,
            "appearance_probability": [0.8] * 15,
            "expected_minutes_if_appearance": [60.0] * 15,
            "raw_expected_points_if_appearance": [3.0] * 15,
            "composition_route": [COMPONENT_MODEL_ROUTE] * 15,
            "evidence_status": ["not_requested"] * 15,
        }
    )
    handoff = PhaseCComponentHandoff(
        rows=rows,
        roster=pd.DataFrame(),
        table_sha256="a" * 64,
        roster_sha256="b" * 64,
        manifest_sha256="c" * 64,
        repository_commit="d" * 40,
        model_version="component-v1",
        feature_contract_version="features-v1",
        target_contract_version="targets-v1",
        dataset_contract_version="dataset-v1",
    )
    projections = pd.DataFrame(
        {
            "player_id": list(reversed(ids)),
            "name": [f"Player {player_id}" for player_id in reversed(ids)],
            "team_id": [f"T{player_id // 3}" for player_id in reversed(ids)],
            "position": list(
                reversed(["GK", "GK", *(["DEF"] * 5), *(["MID"] * 5), *(["FWD"] * 3)])
            ),
            "price_tenths": [50] * 15,
            "expected_points": [2.0] * 15,
        }
    )
    candidate = EvaluationFold(
        fold_id=fold_id,
        projections=projections,
        realized_points=pd.DataFrame({"player_id": ids, "total_points": [0.0] * 15}),
    )

    inputs, snapshot = _selected_component_inputs(handoff, candidate, ids)

    assert inputs.player_ids == tuple(ids)
    assert tuple(snapshot.table["player_id"]) == tuple(ids)
    assert tuple(inputs.table["team_id"]) == tuple(snapshot.table["team_id"])
