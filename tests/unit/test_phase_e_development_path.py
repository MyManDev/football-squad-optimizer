"""The candidate-sampler development path of E3: its evidence, its pin and its own contract.

Candidate Phase D evidence is accepted only for the sampler it calibrated; a draw must declare
that same sampler before the selector's pin is built from it; the resulting artifact carries a
development contract that the binding E3 loader and the E4 hook refuse.
"""

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest
from scripts import _phase_e_evaluation as evaluation
from scripts import _phase_e_inputs as inputs
from scripts import _phase_e_shadow_live as live_shadow
from scripts import probe_phase_e_runtime as probe
from scripts import run_component_squad_calibration as binding
from scripts import run_phase_e_shadow as runner
from tests.unit.test_phase_e_evaluation import _inputs
from tests.unit.test_phase_e_inputs import _binding_document
from tests.unit.test_run_component_squad_calibration import _handoff
from tests.unit.test_run_phase_e_shadow import _evidence, _probe, _write_probe

from squadopt.experiments.phase_e_shadow import (
    PHASE_E_SHADOW_CONTRACT,
    PHASE_E_SHADOW_DEVELOPMENT_CONTRACT,
    PhaseEShadowError,
)
from squadopt.scenarios.components import (
    COMPONENT_SCENARIO_CONTRACT_VERSION,
    CONDITIONAL_RESIDUAL_CONTRACT_VERSION,
    ConditionalResidualConfig,
)

CONDITIONAL = ConditionalResidualConfig(fraction=0.15, minimum_rows=30)
CONDITIONAL_ARGUMENTS = (
    "--sampler",
    "conditional",
    "--conditional-residual-fraction",
    "0.15",
    "--conditional-residual-minimum-rows",
    "30",
)


def _candidate_document() -> dict:
    document = _binding_document()
    ids = document["population"]["expected_binding_fold_ids"]
    document["contract_version"] = binding.CANDIDATE_REPORT_VERSION
    document["binding"] = False
    document["candidate"] = binding._candidate_record(CONDITIONAL)
    document["folds"] = [
        {"fold_id": fold_id, "sampler_contract_version": CONDITIONAL_RESIDUAL_CONTRACT_VERSION}
        for fold_id in ids
    ]
    return document


def _write(tmp_path: Path, name: str, document: dict) -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def _development_probe(evidence) -> dict:
    document = _probe(evidence)
    document["contract_version"] = probe.DEVELOPMENT_PROBE_CONTRACT_VERSION
    document["development_only"] = True
    document["sampler"] = probe.sampler_record(CONDITIONAL)
    for point in document["decision_points"]:
        for run in point["runs"]:
            run["scoring"]["draw"]["component_sampler_contract_version"] = (
                CONDITIONAL_RESIDUAL_CONTRACT_VERSION
            )
    return document


def test_candidate_evidence_loads_only_for_its_own_sampler_settings(tmp_path: Path) -> None:
    path = _write(tmp_path, "candidate.json", _candidate_document())

    evidence = inputs.load_phase_d_candidate(path, conditional_residuals=CONDITIONAL)

    assert evidence.binding is False
    assert evidence.sampler_contract_version == CONDITIONAL_RESIDUAL_CONTRACT_VERSION
    assert evidence.status == "calibrated_internal" and len(evidence.fold_ids) == 137
    assert evidence.sha256 == hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises(PhaseEShadowError):
        inputs.load_phase_d_binding(path)
    with pytest.raises(PhaseEShadowError):
        inputs.load_phase_d_candidate(
            path, conditional_residuals=ConditionalResidualConfig(fraction=0.2, minimum_rows=30)
        )


@pytest.mark.parametrize(
    "mutation", ["claims_binding", "foundation_fold", "binding_contract", "no_candidate_block"]
)
def test_candidate_evidence_rejects_a_document_that_is_not_exactly_a_candidate_report(
    tmp_path: Path, mutation: str
) -> None:
    document = _candidate_document()
    if mutation == "claims_binding":
        document["binding"] = True
    elif mutation == "foundation_fold":
        document["folds"][5]["sampler_contract_version"] = COMPONENT_SCENARIO_CONTRACT_VERSION
    elif mutation == "binding_contract":
        document["contract_version"] = binding.REPORT_VERSION
    else:
        document["candidate"] = None
    with pytest.raises(PhaseEShadowError):
        inputs.load_phase_d_candidate(
            _write(tmp_path, "candidate.json", document), conditional_residuals=CONDITIONAL
        )


def test_binding_evidence_never_carries_a_candidate_sampler(tmp_path: Path) -> None:
    evidence = inputs.load_phase_d_binding(_write(tmp_path, "b.json", _binding_document()))
    assert evidence.binding is True
    assert evidence.sampler_contract_version == COMPONENT_SCENARIO_CONTRACT_VERSION

    disguised = _binding_document()
    disguised["binding"] = False
    with pytest.raises(PhaseEShadowError):
        inputs.load_phase_d_binding(_write(tmp_path, "c.json", disguised))
    with_block = _binding_document()
    with_block["candidate"] = binding._candidate_record(CONDITIONAL)
    with pytest.raises(PhaseEShadowError):
        inputs.load_phase_d_binding(_write(tmp_path, "d.json", with_block))


def test_the_e2_loader_pairs_the_probe_contract_with_the_sampler(tmp_path: Path) -> None:
    evidence = _evidence(tmp_path)
    foundation = _write_probe(tmp_path, _probe(evidence))
    assert runner.load_phase_e_runtime(foundation, evidence).candidate_count == 16
    with pytest.raises(PhaseEShadowError, match="sampler"):
        runner.load_phase_e_runtime(foundation, evidence, conditional_residuals=CONDITIONAL)

    development = _write(tmp_path, "development.json", _development_probe(evidence))
    result = runner.load_phase_e_runtime(development, evidence, conditional_residuals=CONDITIONAL)
    assert result.candidate_count == 16
    assert result.sha256 == hashlib.sha256(development.read_bytes()).hexdigest()
    with pytest.raises(PhaseEShadowError, match="sampler"):
        runner.load_phase_e_runtime(development, evidence)
    with pytest.raises(PhaseEShadowError, match="sampler"):
        runner.load_phase_e_runtime(
            development,
            evidence,
            conditional_residuals=ConditionalResidualConfig(fraction=0.2, minimum_rows=30),
        )

    one_foundation_draw = _development_probe(evidence)
    run = one_foundation_draw["decision_points"][4]["runs"][0]
    run["scoring"]["draw"]["component_sampler_contract_version"] = (
        COMPONENT_SCENARIO_CONTRACT_VERSION
    )
    with pytest.raises(PhaseEShadowError, match="requested sampler"):
        runner.load_phase_e_runtime(
            _write(tmp_path, "mixed.json", one_foundation_draw),
            evidence,
            conditional_residuals=CONDITIONAL,
        )


@pytest.mark.slow
def test_evaluation_pins_the_declared_sampler_and_refuses_a_mismatch() -> None:
    handoff, fold, evidence = _inputs()
    development = replace(
        evidence, binding=False, sampler_contract_version=CONDITIONAL_RESIDUAL_CONTRACT_VERSION
    )
    settings = ConditionalResidualConfig(fraction=0.25, minimum_rows=4)

    result = evaluation.evaluate_phase_e_decision(
        handoff, fold, development, frozen_candidate_count=4, conditional_residuals=settings
    )
    assert result.error is None and result.status == "SELECTED"
    assert result.sampler_contract_version == CONDITIONAL_RESIDUAL_CONTRACT_VERSION
    assert len(result.candidates) == 4

    foundation = evaluation.evaluate_phase_e_decision(
        handoff, fold, evidence, frozen_candidate_count=4
    )
    assert foundation.status == "SELECTED"
    assert foundation.sampler_contract_version == COMPONENT_SCENARIO_CONTRACT_VERSION

    # Evidence and draw must name one sampler, in both directions.
    mismatch = evaluation.evaluate_phase_e_decision(
        handoff, fold, development, frozen_candidate_count=4
    )
    assert mismatch.status == "ERROR" and "declares sampler" in (mismatch.error or "")
    assert mismatch.sampler_contract_version == CONDITIONAL_RESIDUAL_CONTRACT_VERSION
    reverse = evaluation.evaluate_phase_e_decision(
        handoff, fold, evidence, frozen_candidate_count=4, conditional_residuals=settings
    )
    assert reverse.status == "ERROR" and "declares sampler" in (reverse.error or "")


def _argv(tmp_path: Path, *extra: str) -> list[str]:
    return [
        *(
            value
            for name in ("runtime-probe", "table", "roster", "manifest", "json-output")
            for value in (f"--{name}", str(tmp_path / f"{name}.json"))
        ),
        *extra,
    ]


def test_the_command_writes_a_development_artifact_that_e4_cannot_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calibrated = _evidence(tmp_path)
    candidate_path = _write(tmp_path, "candidate.json", _candidate_document())
    probe_path = _write(tmp_path, "runtime-probe.json", _development_probe(calibrated))
    monkeypatch.setattr(
        runner,
        "artifact_metadata",
        lambda **kwargs: {
            "provenance": {"repository_commit": "b" * 40, "working_tree_dirty": False},
            "environment": {},
        },
    )
    monkeypatch.setattr(runner, "read_phase_c_component_handoff", lambda *args: _handoff())
    monkeypatch.setattr(runner, "prepare_phase_e_folds", lambda *args: ((), 12))
    seen: list[tuple[int, object]] = []

    def evaluate(handoff, folds, evidence, *, frozen_candidate_count, conditional_residuals=None):
        seen.append((frozen_candidate_count, conditional_residuals))
        assert evidence.binding is False
        return {
            "binding_artifact_sha256": evidence.sha256,
            "folds": [],
            "verdict": {"status": "technical_only"},
        }

    monkeypatch.setattr(runner, "evaluate_phase_e_prepared_folds", evaluate)

    # Mode misuse is refused before any evidence is read.
    assert runner.main(_argv(tmp_path, "--phase-d-candidate", str(candidate_path))) == 1
    assert runner.main(_argv(tmp_path, "--binding", str(tmp_path / "binding.json"))) == 1
    assert (
        runner.main(
            _argv(
                tmp_path,
                "--binding",
                str(tmp_path / "binding.json"),
                "--phase-d-candidate",
                str(candidate_path),
                *CONDITIONAL_ARGUMENTS,
            )
        )
        == 1
    )
    assert (
        runner.main(
            _argv(tmp_path, "--phase-d-candidate", str(candidate_path), "--sampler", "conditional")
        )
        == 1
    )
    assert seen == []

    assert (
        runner.main(
            _argv(tmp_path, "--phase-d-candidate", str(candidate_path), *CONDITIONAL_ARGUMENTS)
        )
        == 0
    )
    assert seen == [(16, CONDITIONAL)]
    output = tmp_path / "json-output.json"
    written = json.loads(output.read_text(encoding="utf-8"))
    assert written["contract_version"] == PHASE_E_SHADOW_DEVELOPMENT_CONTRACT
    assert written["contract_version"] != PHASE_E_SHADOW_CONTRACT
    assert written["binding"] is False and written["development_only"] is True
    assert written["e4_permitted"] is False
    assert written["sampler"] == probe.sampler_record(CONDITIONAL)
    assert written["phase_d_evidence"] == {
        "contract_version": binding.CANDIDATE_REPORT_VERSION,
        "binding": False,
        "status": "calibrated_internal",
        "sha256": hashlib.sha256(candidate_path.read_bytes()).hexdigest(),
        "sampler_contract_version": CONDITIONAL_RESIDUAL_CONTRACT_VERSION,
    }
    assert written["runtime_probe_sha256"] == hashlib.sha256(probe_path.read_bytes()).hexdigest()

    runtime = runner.PhaseERuntimeEvidence(16, written["runtime_probe_sha256"])
    with pytest.raises(PhaseEShadowError):
        live_shadow.load_shadow_eligibility(output, calibrated, runtime)
    development_evidence = inputs.load_phase_d_candidate(
        candidate_path, conditional_residuals=CONDITIONAL
    )
    with pytest.raises(PhaseEShadowError):
        live_shadow.load_shadow_eligibility(output, development_evidence, runtime)
