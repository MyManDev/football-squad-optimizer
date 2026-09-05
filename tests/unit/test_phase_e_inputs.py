"""Binding evidence and outcome-isolated full-pool historical scenario preparation."""

import hashlib
import json
from dataclasses import asdict, replace
from pathlib import Path

import pandas as pd
import pytest
from scripts import _phase_e_inputs as inputs
from scripts import run_component_squad_calibration as binding
from tests.unit.test_phase_c_component_decisions import _control, _handoff
from tests.unit.test_run_component_squad_calibration import _all_fold_ids

from squadopt.experiments.phase_e_shadow import PhaseEShadowError
from squadopt.scenarios import ScenarioConfig


def _binding_document() -> dict:
    ids = binding._binding_population(_all_fold_ids(), binding.DIRECT_CONTROL_ABSTENTIONS)
    return {
        "contract_version": binding.REPORT_VERSION,
        "evaluation_contract_version": binding.COMPONENT_SQUAD_CALIBRATION_CONTRACT_VERSION,
        "locked_holdout_accessed": False,
        "operational_control_changed": False,
        "internal_only": True,
        "provenance": {"working_tree_dirty": False},
        "source": {
            "table_sha256": binding.PHASE_C_TABLE_SHA256,
            "roster_sha256": binding.PHASE_C_ROSTER_SHA256,
            "manifest_sha256": binding.PHASE_C_MANIFEST_SHA256,
            "fidelity_artifact_sha256": binding.FIDELITY_ARTIFACT_SHA256,
            "model_version": "phase_c_control_components_v1",
        },
        "config": asdict(ScenarioConfig()),
        "population": {
            "full_fold_count": binding.FULL_FOLD_COUNT,
            "history_burn_in_fold_ids": list(binding.HISTORY_BURN_IN_FOLDS),
            "direct_control_abstention_fold_ids": list(binding.DIRECT_CONTROL_ABSTENTIONS),
            "expected_binding_fold_ids": list(ids),
        },
        "verdict": {
            "status": "calibrated_internal",
            "fold_count": 137,
            "expected_fold_count": 137,
            "fold_ids": list(ids),
            "s1_passes": True,
            "s2_passes": True,
        },
    }


@pytest.mark.parametrize("status", ["calibrated_internal", "failed", "abstained"])
def test_binding_loader_requires_a_real_artifact_and_preserves_its_status(
    tmp_path: Path, status: str
) -> None:
    path = tmp_path / "binding.json"
    with pytest.raises(FileNotFoundError):
        inputs.load_phase_d_binding(path)
    document = _binding_document()
    document["verdict"]["status"] = status
    path.write_text(json.dumps(document), encoding="utf-8")
    evidence = inputs.load_phase_d_binding(path)
    assert evidence.status == status
    assert len(evidence.fold_ids) == 137 and "2021-22-gw15" not in evidence.fold_ids
    assert evidence.sha256 == hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.parametrize(
    "section,key,value",
    [
        ("source", "table_sha256", "0" * 64),
        ("config", "deterministic_seed", 1),
        ("verdict", "s1_passes", False),
        ("verdict", "fold_count", 136),
        ("verdict", "status", "passed"),
        ("population", "direct_control_abstention_fold_ids", []),
        ("provenance", "working_tree_dirty", True),
    ],
)
def test_binding_loader_rejects_changed_inputs_or_unearned_success(
    tmp_path: Path, section: str, key: str, value: object
) -> None:
    document = _binding_document()
    document[section][key] = value
    path = tmp_path / "binding.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(PhaseEShadowError):
        inputs.load_phase_d_binding(path)


def test_draw_covers_all_component_players_and_cannot_see_target_or_future_outcomes() -> None:
    handoff = _handoff()
    fold = _control()
    rows = pd.concat(
        [handoff.rows, *(handoff.rows.iloc[[0]].assign(player_id=i) for i in (16, 17))],
        ignore_index=True,
    )
    projections = pd.concat(
        [
            fold.projections,
            *(fold.projections.iloc[[0]].assign(player_id=i, name=f"P{i}") for i in (16, 17)),
        ],
        ignore_index=True,
    )
    history = pd.concat(
        [
            rows.assign(fold_id=f"2021-22-gw{week:02d}", season="2021-22", target_gameweek=week)
            for week in range(30, 38)
        ],
        ignore_index=True,
    )
    future = rows.assign(fold_id="2022-23-gw03", target_gameweek=3)
    handoff = replace(handoff, rows=pd.concat([history, rows, future], ignore_index=True))
    fold = replace(fold, projections=projections)
    before = handoff.rows.copy(deep=True)
    first = inputs.draw_phase_e_fold(handoff, fold)
    assert set(first.inputs.player_ids) == set(range(1, 18)) - {15}
    assert 15 in fold.projections["player_id"].tolist()  # Direct control stays in optimizer pool.
    assert first.scenarios.config == ScenarioConfig()
    assert set(first.scenarios.source_fold_ids) <= set(history["fold_id"])
    changed = handoff.rows.copy(deep=True)
    changed.loc[changed["fold_id"].ge(fold.fold_id), ["points_target", "minutes_target"]] = 999
    second = inputs.draw_phase_e_fold(
        replace(handoff, rows=changed),
        replace(fold, realized_points=fold.realized_points.assign(total_points=999, minutes=0)),
    )
    assert second.component_fingerprint == first.component_fingerprint
    assert second.scenarios.scenario_fingerprint == first.scenarios.scenario_fingerprint
    pd.testing.assert_frame_equal(handoff.rows, before)
