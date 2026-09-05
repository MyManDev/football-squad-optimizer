"""E4 evidence gates and the prospective runtime check use the existing engines."""

import hashlib
import json
from dataclasses import asdict, replace
from pathlib import Path

import pandas as pd
import pytest
from scripts import _phase_e_shadow_live as shadow
from scripts._phase_e_inputs import PhaseDBindingEvidence
from scripts.run_phase_e_shadow import PhaseERuntimeEvidence
from tests.unit.test_phase_e_evaluation import _inputs
from tests.unit.test_phase_e_inputs import _binding_document

from squadopt.experiments.phase_e_shadow import PhaseEShadowCandidate, PhaseEShadowFold
from squadopt.live import Projection


def _e3(tmp_path: Path):
    ids = tuple(_binding_document()["population"]["expected_binding_fold_ids"])
    binding = PhaseDBindingEvidence(
        "calibrated_internal", ids, "a" * 64, "phase_c_control_components_v1"
    )
    runtime = PhaseERuntimeEvidence(4, "b" * 64)
    folds = [
        PhaseEShadowFold(
            fold_id,
            "SELECTED",
            True,
            selected_rank=1,
            control_points=10.0,
            selected_points=11.0,
            squad_changed=True,
            candidates=(PhaseEShadowCandidate(0, 10.0, None), PhaseEShadowCandidate(1, 11.0, None)),
        )
        for fold_id in ids
    ]
    document = {
        "contract_version": shadow.PHASE_E_SHADOW_CONTRACT,
        "preregistration_version": shadow.probe.PREREGISTRATION_VERSION,
        "prereg_document": shadow.probe.PREREGISTRATION,
        "binding_artifact_sha256": binding.sha256,
        "runtime_probe_sha256": runtime.sha256,
        "frozen_candidate_count": runtime.candidate_count,
        "internal_only": True,
        "operational_control_changed": False,
        "locked_holdout_accessed": False,
        "provenance": {"repository_commit": "c" * 40, "working_tree_dirty": False},
        "source": {
            "table_sha256": shadow.calibration.PHASE_C_TABLE_SHA256,
            "roster_sha256": shadow.calibration.PHASE_C_ROSTER_SHA256,
            "manifest_sha256": shadow.calibration.PHASE_C_MANIFEST_SHA256,
        },
        "folds": [asdict(fold) for fold in folds],
        "verdict": shadow.evaluate_phase_e_shadow(
            folds, expected_fold_ids=ids, phase_d_status=binding.status
        ),
    }
    path = tmp_path / "e3.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    return path, binding, runtime, document


def test_e3_eligibility_recomputes_the_entire_verdict(tmp_path: Path) -> None:
    path, binding, runtime, _ = _e3(tmp_path)
    assert (
        shadow.load_shadow_eligibility(path, binding, runtime)
        == hashlib.sha256(path.read_bytes()).hexdigest()
    )


@pytest.mark.parametrize(
    "problem",
    [
        "binding",
        "k",
        "source",
        "dirty",
        "population",
        "fake_verdict",
        "harmful",
        "old_amendment",
        "prereg_document",
        "string_boolean",
    ],
)
def test_unproven_or_mismatched_e3_cannot_authorize_live_shadow(
    tmp_path: Path, problem: str
) -> None:
    path, binding, runtime, document = _e3(tmp_path)
    if problem == "binding":
        binding = replace(binding, status="failed")
    elif problem == "k":
        document["frozen_candidate_count"] = 16
    elif problem == "source":
        document["source"]["table_sha256"] = "f" * 64
    elif problem == "dirty":
        document["provenance"]["working_tree_dirty"] = True
    elif problem == "population":
        document["folds"].pop()
    elif problem == "fake_verdict":
        document["verdict"]["mean_difference"] = 100.0
    elif problem == "old_amendment":
        document["preregistration_version"] = "old"
    elif problem == "prereg_document":
        document.pop("prereg_document")
    elif problem == "string_boolean":
        document["folds"][0]["candidate_set_complete"] = "false"
    else:
        for fold in document["folds"]:
            fold["selected_points"] = 0.0
            fold["candidates"][1]["realized_points"] = 0.0
    path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(shadow.PhaseEShadowError):
        shadow.load_shadow_eligibility(path, binding, runtime)


def _ready():
    return {
        "candidate_count": 4,
        "complete": True,
        "all_optimal": True,
        "generation_repeat_identical": True,
        "within_budget": True,
        "scoring": {
            "draw_repeat_identical": True,
            "selection_repeat_identical": True,
            "control_covered": True,
            "candidates_covered": 4,
            "selector_probe_pin": {"status": "SELECTED"},
        },
    }


@pytest.mark.parametrize(
    "field",
    [
        "complete",
        "all_optimal",
        "generation_repeat_identical",
        "within_budget",
        "draw_repeat_identical",
        "selection_repeat_identical",
        "control_covered",
    ],
)
def test_historical_k_does_not_bypass_prospective_failure(field: str) -> None:
    run = _ready()
    assert shadow.prospective_readiness(run, 4)
    if field in run:
        run[field] = False
    else:
        run["scoring"][field] = False
    assert not shadow.prospective_readiness(run, 4)


def test_a_covered_control_alone_cannot_establish_live_readiness() -> None:
    run = _ready()
    run["scoring"]["candidates_covered"] = 1
    assert not shadow.prospective_readiness(run, 4)


def test_missing_evidence_stops_e4_before_live_decision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from scripts import run_phase_e_live_shadow as command

    monkeypatch.setattr(
        command, "decide", lambda *args, **kwargs: pytest.fail("No live decision before evidence")
    )
    arguments = [
        item
        for name in (
            "binding",
            "runtime-probe",
            "shadow-evaluation",
            "table",
            "roster",
            "manifest",
            "in-season-projection",
            "snapshot-root",
            "ledger-root",
            "archive-root",
        )
        for item in (f"--{name}", str(tmp_path / name))
    ]
    assert command.main([*arguments, "--snapshot-id", "not-read"]) == 1


def test_live_hook_reuses_real_probe_and_keeps_the_pool(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from types import SimpleNamespace

    path, binding, runtime, _ = _e3(tmp_path)
    handoff, fold, _ = _inputs()
    rows = handoff.rows.copy(deep=True)
    current = rows["fold_id"].eq(fold.fold_id)
    rows.loc[current, "fold_id"] = "2026-27-gw04"
    rows.loc[current, "season"] = "2026-27"
    rows.loc[current, "target_gameweek"] = 4
    handoff = replace(handoff, rows=rows)
    fold = replace(fold, fold_id="2026-27-gw04")
    from scripts._phase_e_inputs import draw_phase_e_fold

    draw = draw_phase_e_fold(handoff, fold)
    point = shadow.probe.DecisionPoint(
        label="2026-27-gw04",
        kind="live",
        pool=fold.projections,
        draw_factory=lambda seed: draw,
    )
    monkeypatch.setattr(shadow, "load_phase_d_binding", lambda path: binding)
    monkeypatch.setattr(shadow, "load_phase_e_runtime", lambda path, binding: runtime)
    monkeypatch.setattr(shadow, "read_phase_c_component_handoff", lambda *args: handoff)
    monkeypatch.setattr(
        shadow,
        "read_projection_handoff",
        lambda path: SimpleNamespace(season="2026-27", gameweek=4),
    )
    monkeypatch.setattr(shadow, "live_component_decision", lambda *args, **kwargs: point)
    hook = shadow.make_live_shadow_hook(
        binding_path=path,
        runtime_path=path,
        shadow_path=path,
        table_path=path,
        roster_path=path,
        manifest_path=path,
        projection_path=path,
        archive_root=tmp_path,
    )
    original = fold.projections.copy(deep=True)
    record = hook(SimpleNamespace(), Projection(fold.projections, (), {}))
    assert record["status"] == "SHADOW_RECORDED"
    assert record["prospective_ready"] is True
    assert record["comparison_scope"] == "full_pool_squad_diagnostic"
    assert record["published_decision_changed"] is False
    assert record["is_transfer_alternative"] is False
    assert record["selected_candidate_rank"] == 0
    assert record["shadow_evaluation_sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    pd.testing.assert_frame_equal(fold.projections, original)
    json.dumps(record, allow_nan=False)
