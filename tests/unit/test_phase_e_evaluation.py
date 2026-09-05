"""Generator-to-realized-score integration, without a binding measurement."""

import json
from dataclasses import asdict, replace

import pandas as pd
import pytest
from scripts import _phase_e_evaluation as runner
from scripts._phase_e_inputs import PhaseDBindingEvidence
from tests.unit.test_phase_c_component_decisions import _control, _handoff
from tests.unit.test_run_component_squad_calibration import _all_fold_ids

from squadopt.experiments.phase_e_shadow import PhaseEShadowError
from squadopt.optimization.models import SolverExecutionError


def _inputs():
    handoff = _handoff()
    fold = _control()
    target = handoff.rows.assign(
        appearance_probability=1.0,
        expected_minutes_if_appearance=90.0,
        raw_expected_points_if_appearance=3.0,
        composition_route="component_model",
    )
    history = pd.concat(
        [
            target.assign(fold_id=f"2021-22-gw{week:02d}", season="2021-22", target_gameweek=week)
            for week in range(30, 38)
        ],
        ignore_index=True,
    )
    handoff = replace(handoff, rows=pd.concat([history, target], ignore_index=True))
    evidence = PhaseDBindingEvidence(
        "calibrated_internal", (fold.fold_id,), "a" * 64, handoff.model_version
    )
    return handoff, fold, evidence


def test_real_generator_sampler_selector_and_official_scorer_work_together() -> None:
    handoff, fold, evidence = _inputs()
    original = fold.projections.copy(deep=True)
    result = runner.evaluate_phase_e_decision(handoff, fold, evidence, frozen_candidate_count=4)
    assert result.error is None
    assert result.status == "SELECTED" and result.candidate_set_complete
    assert result.selected_rank == 0  # Every candidate ties on the constant point scenarios.
    assert result.control_points == result.selected_points == 24.0
    assert len(result.candidates) == 4
    assert (
        len({(item.squad_ids, item.starting_ids, item.captain_id) for item in result.candidates})
        == 4
    )
    assert result.scenario_fingerprint and result.component_fingerprint
    assert result.generation_seconds > 0 and result.scoring_seconds > 0
    json.dumps(asdict(result), allow_nan=False)
    pd.testing.assert_frame_equal(fold.projections, original)


def test_failed_phase_d_keeps_control_but_records_technical_candidate_pairs() -> None:
    handoff, fold, evidence = _inputs()
    result = runner.evaluate_phase_e_decision(
        handoff, fold, replace(evidence, status="failed"), frozen_candidate_count=4
    )
    assert result.error is None and result.difference == 0
    assert result.status == "FALLBACK_PHASE_D_NOT_CALIBRATED"
    assert len(result.candidates) == 4
    assert all(candidate.utility_int is not None for candidate in result.candidates)


def test_solver_failure_is_named_and_does_not_attempt_scenarios(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    handoff, fold, evidence = _inputs()

    def fail(*args, **kwargs):
        raise SolverExecutionError("synthetic failure")

    def forbidden(*args, **kwargs):
        pytest.fail("An unsolved control must not draw scenarios")

    monkeypatch.setattr(runner, "generate_squad_candidates", fail)
    monkeypatch.setattr(runner, "draw_phase_e_fold", forbidden)
    result = runner.evaluate_phase_e_decision(handoff, fold, evidence, frozen_candidate_count=4)
    assert result.status == "ERROR" and result.difference is None
    assert result.error == "SolverExecutionError: synthetic failure"


def test_population_cannot_be_shortened_and_k_cannot_be_tuned() -> None:
    handoff, fold, evidence = _inputs()
    with pytest.raises(PhaseEShadowError, match="137"):
        runner.evaluate_phase_e_prepared_folds(handoff, [fold], evidence, frozen_candidate_count=4)
    with pytest.raises(PhaseEShadowError, match="candidate count"):
        runner.evaluate_phase_e_decision(handoff, fold, evidence, frozen_candidate_count=5)
    with pytest.raises(PhaseEShadowError, match="population"):
        runner.evaluate_phase_e_decision(
            handoff, fold, replace(evidence, fold_ids=()), frozen_candidate_count=4
        )


def test_prepared_runner_retains_every_binding_fold_in_its_artifact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from scripts.run_component_squad_calibration import (
        DIRECT_CONTROL_ABSTENTIONS,
        _binding_population,
    )

    from squadopt.experiments.phase_e_shadow import PhaseEShadowCandidate, PhaseEShadowFold

    handoff, fold, evidence = _inputs()
    ids = _binding_population(_all_fold_ids(), DIRECT_CONTROL_ABSTENTIONS)
    evidence = replace(evidence, fold_ids=ids)

    def reading(handoff, fold, evidence, *, frozen_candidate_count):
        return PhaseEShadowFold(
            fold.fold_id,
            "FALLBACK_PHASE_D_NOT_CALIBRATED",
            True,
            control_points=24.0,
            selected_points=24.0,
            candidates=(PhaseEShadowCandidate(0, 24.0, None),),
        )

    monkeypatch.setattr(runner, "evaluate_phase_e_decision", reading)
    result = runner.evaluate_phase_e_prepared_folds(
        handoff,
        [replace(fold, fold_id=fold_id) for fold_id in reversed(ids)],
        evidence,
        frozen_candidate_count=4,
    )
    assert [item["fold_id"] for item in result["folds"]] == list(ids)
    assert result["verdict"]["fold_count"] == 137
    assert result["verdict"]["mean_difference"] == 0
    json.dumps(result, allow_nan=False)
