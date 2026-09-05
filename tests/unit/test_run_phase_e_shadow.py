"""E3 artifact gates precede data access and consume the actual E2 rule contract."""

import hashlib
import json
from copy import deepcopy
from pathlib import Path

import pytest
from scripts import run_phase_e_shadow as runner
from scripts._phase_e_inputs import load_phase_d_binding
from tests.unit.test_phase_e_inputs import _binding_document
from tests.unit.test_run_component_squad_calibration import _handoff


def _evidence(tmp_path: Path):
    path = tmp_path / "binding.json"
    path.write_text(json.dumps(_binding_document()), encoding="utf-8")
    return load_phase_d_binding(path)


def _probe(evidence):
    points = []
    for kind, labels in (("live", runner.probe.E2_LIVE_LABELS), ("fold", evidence.fold_ids)):
        for label in labels:
            runs = []
            for count in (4, 8, 16):
                runs.append(
                    {
                        "candidate_count": count,
                        "generation_seconds": 1.0,
                        "generation_seconds_repeat": 1.1,
                        "generation_repeat_identical": True,
                        "complete": True,
                        "all_optimal": True,
                        "termination_status": "OPTIMAL",
                        "within_budget": True,
                        "budget_seconds": 3.0,
                        "candidates_found": count,
                        "candidates": [
                            {
                                "rank": rank,
                                "solver_status": "OPTIMAL",
                                "squad_ids": [str(identifier) for identifier in range(1, 15)]
                                + [str(15 + rank)],
                                "eleven_ids": [str(identifier) for identifier in range(1, 12)],
                                "captain_id": "1",
                            }
                            for rank in range(count)
                        ],
                        "scoring": {
                            "scoring_seconds_total": 2.0,
                            "draw_repeat_identical": True,
                            "selection_repeat_identical": True,
                            "draw": {"scenario_count": 1000, "deterministic_seed": 0},
                        },
                    }
                )
            points.append(
                {
                    "kind": kind,
                    "label": label,
                    "draw_available": True,
                    "draw_unavailable_reason": None,
                    "runs": runs,
                }
            )
    rule = runner.probe.candidate_count_rule(
        points, (4, 8, 16), expected_fold_ids=evidence.fold_ids
    )
    return {
        "contract_version": runner.probe.PROBE_CONTRACT_VERSION,
        "preregistration": runner.probe.PREREGISTRATION,
        "preregistration_version": runner.probe.PREREGISTRATION_VERSION,
        "source": {
            "table_sha256": runner.binding.PHASE_C_TABLE_SHA256,
            "roster_sha256": runner.binding.PHASE_C_ROSTER_SHA256,
            "manifest_sha256": runner.binding.PHASE_C_MANIFEST_SHA256,
        },
        "diagnostic_only": True,
        "promotes_anything": False,
        "reads_realized_outcomes": False,
        "outcome_policy": runner.probe.OUTCOME_POLICY,
        "scoring_requested": True,
        "constants": {
            "candidate_counts": [4, 8, 16],
            "sensitivity_seeds": [1, 2, 3, 4],
            "budget_seconds": 120.0,
            "scenario_count": 1000,
            "risk_weight": 0.25,
            "tail_fraction": 0.1,
        },
        "provenance": {"working_tree_dirty": False, "repository_commit": "a" * 40},
        "decision_points": points,
        "candidate_count_rule": rule,
        "frozen_k": rule["frozen_k"],
    }


def _write_probe(tmp_path: Path, document: dict) -> Path:
    path = tmp_path / "probe.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def test_accepts_only_the_largest_k_from_the_complete_measured_probe(tmp_path: Path) -> None:
    evidence = _evidence(tmp_path)
    path = _write_probe(tmp_path, _probe(evidence))
    result = runner.load_phase_e_runtime(path, evidence)
    assert result.candidate_count == 16
    assert result.sha256 == hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.parametrize(
    "mutation",
    [
        "missing_pool",
        "duplicate_pool",
        "missing_k",
        "fake_k",
        "missing_draw",
        "fake_budget",
        "fake_optimal",
        "fake_complete",
        "duplicate_candidate",
        "duplicate_starter",
        "duplicate_rank",
        "dirty",
        "outcomes",
        "old_schema",
        "missing_amendment",
        "wrong_source",
    ],
)
def test_refuses_incomplete_or_inconsistent_e2_evidence(tmp_path: Path, mutation: str) -> None:
    evidence = _evidence(tmp_path)
    document = _probe(evidence)
    points = document["decision_points"]
    first = points[0]["runs"][0]
    if mutation == "missing_pool":
        points.pop()
    elif mutation == "duplicate_pool":
        points[-1] = deepcopy(points[-2])
    elif mutation == "missing_k":
        points[0]["runs"].pop()
    elif mutation == "fake_k":
        document["frozen_k"] = 8
    elif mutation == "missing_draw":
        points[0]["draw_available"] = False
    elif mutation == "fake_budget":
        first["generation_seconds"] = 121
    elif mutation == "fake_optimal":
        first["candidates"][0]["solver_status"] = "FEASIBLE"
    elif mutation == "fake_complete":
        first.update(
            candidates=first["candidates"][:1], candidates_found=1, termination_status="UNKNOWN"
        )
    elif mutation == "duplicate_candidate":
        first["candidates"][1] = {**deepcopy(first["candidates"][0]), "rank": 1}
    elif mutation == "duplicate_starter":
        first["candidates"][0]["eleven_ids"][0] = "2"
    elif mutation == "duplicate_rank":
        first["candidates"][1]["rank"] = 0
    elif mutation == "dirty":
        document["provenance"]["working_tree_dirty"] = True
    elif mutation == "old_schema":
        document["contract_version"] = "phase_e_runtime_probe_v1"
    elif mutation == "missing_amendment":
        document.pop("preregistration_version")
    elif mutation == "wrong_source":
        document["source"]["table_sha256"] = "0" * 64
    else:
        document["reads_realized_outcomes"] = True
    with pytest.raises(runner.PhaseEShadowError):
        runner.load_phase_e_runtime(_write_probe(tmp_path, document), evidence)


def test_proven_exhaustion_can_complete_a_set_smaller_than_requested_k(tmp_path: Path) -> None:
    evidence = _evidence(tmp_path)
    document = _probe(evidence)
    for point in document["decision_points"]:
        for run in point["runs"]:
            run.update(
                candidates=run["candidates"][:1],
                candidates_found=1,
                termination_status="INFEASIBLE",
            )
    result = runner.load_phase_e_runtime(_write_probe(tmp_path, document), evidence)
    assert result.candidate_count == 16


def test_k4_failure_cannot_be_overridden_by_a_larger_success(tmp_path: Path) -> None:
    evidence = _evidence(tmp_path)
    document = _probe(evidence)
    first = document["decision_points"][3]["runs"][0]
    first.update(generation_seconds=121.0, budget_seconds=123.0, within_budget=False)
    rule = runner.probe.candidate_count_rule(
        document["decision_points"], (4, 8, 16), expected_fold_ids=evidence.fold_ids
    )
    document.update(candidate_count_rule=rule, frozen_k=rule["frozen_k"])
    assert rule["frozen_k"] is None
    with pytest.raises(runner.PhaseEShadowError, match="K=4 failed"):
        runner.load_phase_e_runtime(_write_probe(tmp_path, document), evidence)


def _unscore_live(document: dict) -> None:
    for point in document["decision_points"][:3]:
        point.update(
            draw_available=False, draw_unavailable_reason="original capture missing history"
        )
        for run in point["runs"]:
            run.update(
                scoring=None,
                scoring_unavailable_reason="original capture missing history",
                budget_seconds=None,
                within_budget=None,
            )


def test_accepts_unscored_original_live_diagnostics_without_claiming_live_readiness(
    tmp_path: Path,
) -> None:
    evidence = _evidence(tmp_path)
    document = _probe(evidence)
    _unscore_live(document)
    result = runner.load_phase_e_runtime(_write_probe(tmp_path, document), evidence)
    assert result.candidate_count == 16
    assert document["candidate_count_rule"]["live_readiness_established"] is False


@pytest.mark.parametrize(
    "mutation",
    ["zero_budget", "success_budget", "missing_reason", "missing_generation", "missing_fold_draw"],
)
def test_unavailable_live_scoring_cannot_be_presented_as_a_measured_success(
    tmp_path: Path, mutation: str
) -> None:
    evidence = _evidence(tmp_path)
    document = _probe(evidence)
    _unscore_live(document)
    run = document["decision_points"][0]["runs"][0]
    if mutation == "zero_budget":
        run["budget_seconds"] = 0
    elif mutation == "success_budget":
        run["within_budget"] = True
    elif mutation == "missing_reason":
        run["scoring_unavailable_reason"] = None
    elif mutation == "missing_generation":
        run["generation_seconds"] = None
    else:
        document["decision_points"][3]["draw_available"] = False
    with pytest.raises(runner.PhaseEShadowError):
        runner.load_phase_e_runtime(_write_probe(tmp_path, document), evidence)


def test_unsolved_live_control_is_retained_as_diagnostic_failure(tmp_path: Path) -> None:
    evidence = _evidence(tmp_path)
    document = _probe(evidence)
    _unscore_live(document)
    run = document["decision_points"][0]["runs"][0]
    run.update(
        candidates=[],
        candidates_found=0,
        complete=False,
        all_optimal=False,
        termination_status="UNKNOWN",
    )
    result = runner.load_phase_e_runtime(_write_probe(tmp_path, document), evidence)
    assert result.candidate_count == 16


def _argv(tmp_path: Path) -> list[str]:
    return [
        value
        for name in ("binding", "runtime-probe", "table", "roster", "manifest", "json-output")
        for value in (f"--{name}", str(tmp_path / f"{name}.json"))
    ]


def test_missing_binding_or_unfrozen_probe_stops_before_historical_inputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def forbidden(*args, **kwargs):
        pytest.fail("Historical data must not be accessed before both artifact gates pass")

    monkeypatch.setattr(runner, "read_phase_c_component_handoff", forbidden)
    assert runner.main(_argv(tmp_path)) == 1
    evidence = _evidence(tmp_path)
    document = _probe(evidence)
    document["frozen_k"] = None
    (tmp_path / "runtime-probe.json").write_text(json.dumps(document), encoding="utf-8")
    assert runner.main(_argv(tmp_path)) == 1


def test_command_writes_once_and_carries_both_artifact_digests(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    evidence = _evidence(tmp_path)
    document = _probe(evidence)
    path = tmp_path / "runtime-probe.json"
    path.write_text(json.dumps(document), encoding="utf-8")
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
    seen = []

    def evaluate(handoff, folds, binding, *, frozen_candidate_count):
        seen.append(frozen_candidate_count)
        return {
            "binding_artifact_sha256": binding.sha256,
            "folds": [],
            "verdict": {"status": "technical_only"},
        }

    monkeypatch.setattr(runner, "evaluate_phase_e_prepared_folds", evaluate)
    assert runner.main(_argv(tmp_path)) == 0
    output = tmp_path / "json-output.json"
    written = json.loads(output.read_text(encoding="utf-8"))
    assert seen == [16]
    assert written["runtime_probe_sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert written["binding_artifact_sha256"] == evidence.sha256
    assert written["operational_control_changed"] is False
    assert runner.main(_argv(tmp_path)) == 1 and seen == [16]
