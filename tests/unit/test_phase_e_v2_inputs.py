"""The C/D/E v2 seam: complete evidence, explicit development scoring and old-path refusal."""

import hashlib
import json
from copy import deepcopy
from dataclasses import asdict, replace
from pathlib import Path

import pytest
from scripts import _phase_e_evaluation as evaluation
from scripts import _phase_e_inputs as inputs
from scripts import probe_phase_e_runtime as probe
from scripts import run_component_squad_calibration as binding
from scripts import run_phase_e_shadow as runner
from scripts._phase_e_development import select_development_candidate
from tests.unit.test_phase_e_evaluation import _inputs
from tests.unit.test_phase_e_selection import _candidates, _full_draw, _select
from tests.unit.test_run_phase_e_shadow import _probe
from tests.unit.test_transfer_decisions import START, _candidate, _optimization_result, _pin

from squadopt.evaluation import DEVELOPMENT_OOF_CONTRACT_VERSION
from squadopt.optimization import SolverStatus
from squadopt.optimization.candidates import SquadCandidateSet
from squadopt.scenarios import ScenarioConfig
from squadopt.scenarios.components import ConditionalResidualConfig, _component_fingerprint
from squadopt.scenarios.selection import PhaseESelectionStatus
from squadopt.scenarios.transfer_decisions import (
    TransferSelectionStatus,
    evaluate_transfer_candidates,
)

CONDITIONAL = ConditionalResidualConfig(fraction=0.15, minimum_rows=30)
REFERENCE = binding.DevelopmentInputs("1" * 64, "2" * 64, "3" * 64, None)


def _document() -> dict:
    ids = [f"2025-26-gw{week:02d}" for week in range(1, 31)]
    burn_in = [f"2024-25-gw{week:02d}" for week in range(31, 39)]
    decision = binding._decision_identity(_candidates()[0])
    verdict = {
        "status": "calibrated_internal",
        "fold_count": 30,
        "expected_fold_count": 30,
        "fold_ids": ids,
        "mean_probability_integral_transform": 0.45,
        "realized_below_lower_quantile_count": 3,
        "realized_below_lower_quantile_rate": 0.1,
        "s1_passes": True,
        "s2_passes": True,
        "abstention_reason": None,
        "contract_version": binding.COMPONENT_SQUAD_CALIBRATION_CONTRACT_VERSION,
    }
    return {
        "contract_version": binding.DEVELOPMENT_REPORT_VERSION,
        "evaluation_contract_version": binding.COMPONENT_SQUAD_CALIBRATION_CONTRACT_VERSION,
        "binding": False,
        "development_only": True,
        "internal_only": True,
        "operational_control_changed": False,
        "member_facing_probability_published": False,
        "locked_holdout_accessed": True,
        "sampler_fidelity_verified": True,
        "config": asdict(ScenarioConfig()),
        "solver_profile": binding._solver_profile(),
        "candidate": binding._candidate_record(
            CONDITIONAL, reference=binding.DEVELOPMENT_REPORT_VERSION
        ),
        "sampler_contract_version": CONDITIONAL.contract_version,
        "provenance": {"repository_commit": "a" * 40, "working_tree_dirty": False},
        "source": {
            "phase_c_contract": DEVELOPMENT_OOF_CONTRACT_VERSION,
            "phase_c_weighting": "equal_weights_v1",
            "model_version": "phase_c_control_components_v1",
            "feature_contract_version": "features",
            "target_contract_version": "targets",
            "dataset_contract_version": "dataset",
            "producer_repository_commit": "b" * 40,
            "table_sha256": REFERENCE.table_sha256,
            "roster_sha256": REFERENCE.roster_sha256,
            "manifest_sha256": REFERENCE.manifest_sha256,
            "pinned_by_arguments": True,
            "fidelity_contract_version": binding.DEVELOPMENT_FIDELITY_VERSION,
            "fidelity_artifact_sha256": "c" * 64,
            "fidelity_measured_fold_count": 30,
        },
        "population": {
            "full_fold_count": 38,
            "min_history_folds": 8,
            "history_seasons": list(binding.DEVELOPMENT_HISTORY_SEASONS),
            "decision_seasons": list(binding.DEVELOPMENT_HISTORY_SEASONS[1:]),
            "history_burn_in_fold_ids": burn_in,
            "history_eligible_fold_count": 30,
            "requested_fold_ids": None,
            "evaluated_fold_ids": ids,
            "direct_control_abstention_fold_ids": [],
            "unsolved_fold_ids": [],
            "unscored_fold_ids": [],
            "measured_fold_ids": ids,
        },
        "folds": [
            {
                "fold_id": fold_id,
                "sampler_contract_version": CONDITIONAL.contract_version,
                "solver_status": "OPTIMAL",
                "decision_identity": deepcopy(decision),
                "scenario_mean_score": 45.0,
                "scenario_standard_deviation": 10.0,
                "realized_score": 30.0 if index < 3 else 50.0,
                "q10_score": 35.0,
                "probability_integral_transform": 0.0 if index < 3 else 0.5,
                "realized_below_q10": index < 3,
                "scenario_fingerprint": "d" * 64,
                "component_fingerprint": "e" * 64,
            }
            for index, fold_id in enumerate(ids)
        ],
        "verdict": verdict,
    }


def _write(tmp_path: Path, name: str, document: dict) -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def _load(tmp_path: Path, document: dict | None = None):
    return inputs.load_phase_d_development(
        _write(tmp_path, "d-v2.json", document or _document()),
        development=REFERENCE,
        conditional_residuals=CONDITIONAL,
    )


def _v2_probe(evidence) -> dict:
    document = _probe(evidence)
    document.update(
        contract_version=probe.DEVELOPMENT_V2_PROBE_CONTRACT_VERSION,
        development_only=True,
        binding=False,
        phase_c_contract="development_v2",
        sampler=probe.sampler_record(CONDITIONAL),
        source=evidence.phase_c_source,
        measured_fold_ids=list(evidence.fold_ids),
        population={
            "all_fold_ids": sorted(
                (*evidence.history_burn_in_fold_ids, *evidence.history_eligible_fold_ids)
            ),
            "history_burn_in_fold_ids": list(evidence.history_burn_in_fold_ids),
            "history_eligible_fold_ids": list(evidence.history_eligible_fold_ids),
            "eligible_fold_ids": list(evidence.fold_ids),
            "direct_control_abstentions": list(evidence.direct_control_fold_ids),
            "eligibility_complete": True,
        },
    )
    for point in document["decision_points"]:
        for run in point["runs"]:
            run["scoring"]["draw"]["component_sampler_contract_version"] = (
                CONDITIONAL.contract_version
            )
            run["scoring"]["draw"]["development_contract"] = DEVELOPMENT_OOF_CONTRACT_VERSION
    rule = probe.candidate_count_rule(
        document["decision_points"],
        (4, 8, 16),
        expected_fold_ids=evidence.fold_ids,
        phase_c_contract="development_v2",
    )
    document.update(candidate_count_rule=rule, frozen_k=rule["frozen_k"])
    return document


def _development_draw(draw):
    component_inputs = replace(
        draw.inputs,
        provenance=replace(
            draw.inputs.provenance, development_contract=DEVELOPMENT_OOF_CONTRACT_VERSION
        ),
    )
    return replace(
        draw,
        inputs=component_inputs,
        component_fingerprint=_component_fingerprint(
            draw.scenarios, component_inputs, draw.sampled_minutes, draw.sampled_appearances
        ),
    )


def test_v2_evidence_uses_its_complete_population_and_cannot_enter_v1(tmp_path: Path) -> None:
    evidence = _load(tmp_path)
    assert len(evidence.fold_ids) == 30 and not evidence.binding
    assert evidence.development_contract == DEVELOPMENT_OOF_CONTRACT_VERSION
    assert evidence.sha256 == hashlib.sha256((tmp_path / "d-v2.json").read_bytes()).hexdigest()
    assert (
        evidence.control_identities[evidence.fold_ids[0]]
        == _document()["folds"][0]["decision_identity"]
    )
    with pytest.raises(ValueError):
        inputs.load_phase_d_binding(tmp_path / "d-v2.json")
    with pytest.raises(ValueError):
        inputs.load_phase_d_candidate(tmp_path / "d-v2.json", conditional_residuals=CONDITIONAL)


@pytest.mark.parametrize(
    "mutation",
    [
        "pilot",
        "missing",
        "unsolved",
        "unscored",
        "fidelity",
        "source",
        "sampler",
        "config",
        "verdict",
        "decision",
        "duplicate",
        "holdout",
        "missing_reading",
        "text_pit",
    ],
)
def test_v2_evidence_rejects_mixed_or_incomplete_records(tmp_path: Path, mutation: str) -> None:
    document = _document()
    if mutation == "pilot":
        document["population"]["requested_fold_ids"] = document["population"]["measured_fold_ids"]
    elif mutation == "missing":
        document["folds"].pop()
    elif mutation in ("unsolved", "unscored"):
        document["population"][f"{mutation}_fold_ids"] = [document["folds"][0]["fold_id"]]
    elif mutation == "fidelity":
        document["sampler_fidelity_verified"] = False
    elif mutation == "source":
        document["source"]["table_sha256"] = "f" * 64
    elif mutation == "sampler":
        document["folds"][0]["sampler_contract_version"] = "foundation"
    elif mutation == "config":
        document["config"]["deterministic_seed"] = 1
    elif mutation == "verdict":
        document["folds"][0]["probability_integral_transform"] = 0.1
    elif mutation == "decision":
        document["folds"][0]["decision_identity"]["captain"] = 99
    elif mutation == "duplicate":
        document["population"]["measured_fold_ids"][1] = document["population"][
            "measured_fold_ids"
        ][0]
    elif mutation == "missing_reading":
        del document["folds"][0]["q10_score"]
    elif mutation == "text_pit":
        document["folds"][0]["probability_integral_transform"] = "0.5"
    else:
        document["locked_holdout_accessed"] = False
    with pytest.raises(ValueError):
        _load(tmp_path, document)


def test_e2_v2_gate_matches_d_scope_and_recomputes_k(tmp_path: Path) -> None:
    evidence = _load(tmp_path)
    document = _v2_probe(evidence)
    assert (
        runner.load_phase_e_runtime(
            _write(tmp_path, "e2.json", document), evidence, conditional_residuals=CONDITIONAL
        ).candidate_count
        == 16
    )
    mutations = []
    for key, value in (
        ("eligibility_complete", False),
        ("eligible_fold_ids", list(evidence.fold_ids[:-1])),
        ("direct_control_abstentions", [evidence.fold_ids[0]]),
    ):
        changed = deepcopy(document)
        changed["population"][key] = value
        mutations.append(changed)
    wrong_source = deepcopy(document)
    wrong_source["source"]["manifest_sha256"] = "9" * 64
    mutations.append(wrong_source)
    forged_k = deepcopy(document)
    forged_k["frozen_k"] = 4
    mutations.append(forged_k)
    disguised = deepcopy(document)
    disguised["decision_points"][3]["runs"][0]["scoring"]["draw"]["development_contract"] = None
    mutations.append(disguised)
    for index, changed in enumerate(mutations):
        with pytest.raises(ValueError):
            runner.load_phase_e_runtime(
                _write(tmp_path, f"bad-{index}.json", changed),
                evidence,
                conditional_residuals=CONDITIONAL,
            )


@pytest.mark.parametrize("missing", [None, 15])
def test_development_scoring_keeps_the_frozen_utility_coverage_and_production_refusal(
    missing,
) -> None:
    base = _full_draw(missing=missing)
    draw = _development_draw(base)
    candidates = _candidates()
    batch = SquadCandidateSet(candidates, 4, True, SolverStatus.INFEASIBLE)
    pin = ((draw.inputs.provenance.model_version, draw.inputs.contract_version),)
    expected = _select(candidates, base)
    measured = select_development_candidate(batch, draw, calibrated_versions=pin)
    assert measured.selection_status == expected.selection_status
    assert measured.selected_candidate_rank == expected.selected_candidate_rank
    assert measured.diagnostics == expected.diagnostics
    assert measured.component_fingerprint == draw.component_fingerprint
    assert _select(candidates, draw).candidate_count_scored == 0
    assert (
        select_development_candidate(batch, draw, calibrated_versions=()).candidate_count_scored
        == 0
    )
    assert (
        select_development_candidate(batch, base, calibrated_versions=pin).candidate_count_scored
        == 0
    )


def test_member_transfer_pin_never_admits_a_development_draw() -> None:
    draw = _development_draw(_full_draw())
    control = _candidate("control", _optimization_result())
    result = evaluate_transfer_candidates(
        (control,), draw, start_state=START, calibrated_versions=_pin(draw)
    )
    assert result.status is TransferSelectionStatus.FALLBACK_PHASE_D_NOT_CALIBRATED
    assert result.selected is control and all(row.utility_int is None for row in result.diagnostics)


def test_e3_v2_reaches_real_scoring_and_names_a_different_d_control() -> None:
    handoff, fold, evidence = _inputs()
    fold_id = "2025-26-gw01"
    rows = handoff.rows.copy(deep=True)
    target_rows = rows["fold_id"].eq(fold.fold_id)
    rows.loc[target_rows, "fold_id"] = fold_id
    rows.loc[target_rows, "season"] = "2025-26"
    rows.loc[target_rows, "target_gameweek"] = 1
    handoff = replace(handoff, rows=rows, development_contract=DEVELOPMENT_OOF_CONTRACT_VERSION)
    fold = replace(fold, fold_id=fold_id)
    evidence = replace(
        evidence,
        fold_ids=(fold_id,),
        binding=False,
        development_contract=DEVELOPMENT_OOF_CONTRACT_VERSION,
        sampler_contract_version=CONDITIONAL.contract_version,
    )
    result = evaluation.evaluate_phase_e_decision(
        handoff, fold, evidence, frozen_candidate_count=4, conditional_residuals=CONDITIONAL
    )
    assert result.status == "SELECTED" and result.error is None
    mismatch = evaluation.evaluate_phase_e_decision(
        handoff,
        fold,
        replace(evidence, control_identities={fold.fold_id: {}}),
        frozen_candidate_count=4,
        conditional_residuals=CONDITIONAL,
    )
    assert mismatch.status == "ERROR" and "differs from the Phase D" in mismatch.error


@pytest.mark.parametrize(
    "config", [ScenarioConfig(deterministic_seed=5), ScenarioConfig(scenario_count=10)]
)
def test_development_selector_rejects_non_frozen_config(config) -> None:
    draw = _development_draw(_full_draw(config=config))
    batch = SquadCandidateSet(_candidates(), 4, True, SolverStatus.INFEASIBLE)
    pin = ((draw.inputs.provenance.model_version, draw.inputs.contract_version),)
    result = select_development_candidate(batch, draw, calibrated_versions=pin)
    assert result.selection_status is PhaseESelectionStatus.FALLBACK_PHASE_D_NOT_CALIBRATED
    assert result.candidate_count_scored == 0


def test_v2_command_writes_its_own_identity_and_cannot_enable_e4(tmp_path, monkeypatch) -> None:
    from scripts import _phase_e_shadow_live as live_shadow

    evidence = _load(tmp_path)
    runtime_path = _write(tmp_path, "e2.json", _v2_probe(evidence))
    output = tmp_path / "e3.json"
    handoff, _, _ = _inputs()
    seen = []
    monkeypatch.setattr(binding, "_read_handoff", lambda *args: handoff)
    monkeypatch.setattr(runner, "prepare_phase_e_folds", lambda *args: ((), 12))
    monkeypatch.setattr(
        runner,
        "artifact_metadata",
        lambda **kwargs: {
            "provenance": {"repository_commit": "a" * 40, "working_tree_dirty": False},
            "environment": {},
        },
    )

    def evaluate(handoff, folds, observed, *, frozen_candidate_count, conditional_residuals):
        seen.append(observed)
        assert frozen_candidate_count == 16 and conditional_residuals == CONDITIONAL
        return {"folds": [], "verdict": {"status": "technical_only"}}

    monkeypatch.setattr(runner, "evaluate_phase_e_prepared_folds", evaluate)
    arguments = [
        "--phase-c-contract",
        "development_v2",
        "--phase-d-development",
        str(tmp_path / "d-v2.json"),
        "--runtime-probe",
        str(runtime_path),
        "--json-output",
        str(output),
        "--table",
        "unused-table",
        "--roster",
        "unused-roster",
        "--manifest",
        "unused-manifest",
        "--expected-table-sha256",
        REFERENCE.table_sha256,
        "--expected-roster-sha256",
        REFERENCE.roster_sha256,
        "--expected-manifest-sha256",
        REFERENCE.manifest_sha256,
        "--sampler",
        "conditional",
        "--conditional-residual-fraction",
        "0.15",
        "--conditional-residual-minimum-rows",
        "30",
    ]
    assert runner.main(arguments) == 0
    document = json.loads(output.read_text())
    assert len(seen) == 1
    assert document["contract_version"] == runner.PHASE_E_SHADOW_DEVELOPMENT_V2_CONTRACT
    assert document["source"] == evidence.phase_c_source
    assert document["phase_d_evidence"]["contract_version"] == binding.DEVELOPMENT_REPORT_VERSION
    assert document["binding"] is False and document["e4_permitted"] is False
    assert document["locked_holdout_accessed"] is True
    with pytest.raises(ValueError):
        live_shadow.load_shadow_eligibility(
            output, evidence, runner.PhaseERuntimeEvidence(16, "f" * 64)
        )
    before = output.read_bytes()
    assert runner.main(arguments) == 1
    assert output.read_bytes() == before


def test_v2_cli_refuses_mode_misuse_before_reading_data(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        runner,
        "load_phase_d_development",
        lambda *a, **kw: pytest.fail("Invalid CLI must precede file access"),
    )
    common = [
        value
        for name in ("runtime-probe", "table", "roster", "manifest", "json-output")
        for value in (f"--{name}", str(tmp_path / name))
    ]
    assert runner.main([*common, "--phase-c-contract", "development_v2"]) == 1
    assert runner.main([*common, "--phase-d-development", str(tmp_path / "d.json")]) == 1


def test_preparation_rejects_a_different_handoff_before_loading_history(
    tmp_path: Path, monkeypatch
) -> None:
    evidence = _load(tmp_path)
    handoff, _, _ = _inputs()
    monkeypatch.setattr(
        binding,
        "_load_development_panel",
        lambda *a: pytest.fail("Mismatched source must precede historical access"),
    )
    with pytest.raises(ValueError, match="reference"):
        inputs.prepare_phase_e_folds(handoff, evidence, tmp_path)
