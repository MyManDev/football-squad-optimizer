"""Connect full-pool candidate generation to the fixed E3 shadow evaluator."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict, replace
from numbers import Integral
from time import perf_counter

from scripts._phase_e_inputs import PhaseDBindingEvidence, draw_phase_e_fold
from scripts.run_component_squad_calibration import BINDING_FOLD_COUNT

from squadopt.evaluation import EvaluationError, EvaluationFold
from squadopt.evaluation.component_handoff import PhaseCComponentHandoff
from squadopt.evaluation.scoring import complete_optimization_decision
from squadopt.experiments.phase_e_shadow import (
    PhaseEShadowError,
    PhaseEShadowFold,
    evaluate_phase_e_shadow,
    score_phase_e_shadow_fold,
)
from squadopt.optimization import OptimizationConfig
from squadopt.optimization.candidates import generate_squad_candidates
from squadopt.optimization.models import SquadOptimizationError
from squadopt.scenarios import ScenarioError
from squadopt.scenarios.components import ComponentScenarioDraw, ConditionalResidualConfig
from squadopt.scenarios.selection import PHASE_E_CANDIDATE_COUNTS, select_phase_e_candidate


def draw_sampler_version(draw: ComponentScenarioDraw) -> str:
    """The sampler a draw declares; a draw without the key is the foundation sampler."""

    return str(
        draw.scenarios.diagnostics.get(
            "component_sampler_contract_version", draw.inputs.contract_version
        )
    )


def evaluate_phase_e_decision(
    handoff: PhaseCComponentHandoff,
    fold: EvaluationFold,
    evidence: PhaseDBindingEvidence,
    *,
    frozen_candidate_count: int,
    conditional_residuals: ConditionalResidualConfig | None = None,
) -> PhaseEShadowFold:
    """Freeze one full-pool decision before drawing scenarios or reading realized scores.

    The runner supplies K from verified outcome-free E2 evidence, not from a tuning loop.
    A failed fold has a named error and no invented control or paired result. The draw must
    declare the sampler the Phase D evidence calibrated; the pin is built from that declared
    sampler, never from the inputs contract alone, so a candidate draw can only pass under
    candidate evidence and a foundation draw only under the binding evidence.
    """

    if (
        isinstance(frozen_candidate_count, bool)
        or not isinstance(frozen_candidate_count, Integral)
        or frozen_candidate_count not in PHASE_E_CANDIDATE_COUNTS
    ):
        raise PhaseEShadowError("E3 requires a frozen E2 candidate count of 4, 8 or 16.")
    if fold.fold_id not in evidence.fold_ids:
        raise PhaseEShadowError("Decision is outside the binding population.")
    started = perf_counter()
    generated_at: float | None = None
    try:
        generated = generate_squad_candidates(
            fold.projections, OptimizationConfig(), candidate_count=frozen_candidate_count
        )
        generated_at = perf_counter()
        # Preserve the existing completion failure before any scenario work is attempted.
        complete_optimization_decision(generated.control)
        draw = draw_phase_e_fold(handoff, fold, conditional_residuals=conditional_residuals)
        if draw.scenarios.target.fold_id != fold.fold_id:
            raise PhaseEShadowError("The shared scenario draw names a different decision fold.")
        sampler_version = draw_sampler_version(draw)
        if sampler_version != evidence.sampler_contract_version:
            raise PhaseEShadowError(
                f"The draw declares sampler {sampler_version!r} but the Phase D evidence "
                f"calibrated {evidence.sampler_contract_version!r}."
            )
        pins = (
            ((evidence.model_version, sampler_version),)
            if evidence.status == "calibrated_internal"
            else ()
        )
        selection = select_phase_e_candidate(
            generated.candidates,
            draw,
            candidate_count_requested=generated.candidate_count_requested,
            candidate_set_complete=generated.complete,
            calibrated_versions=pins,
        )
        reading = score_phase_e_shadow_fold(
            fold.fold_id,
            generated.candidates,
            selection,
            fold.realized_points,
            candidate_set_complete=generated.complete,
            draw=draw,
        )
        return replace(
            reading,
            generation_seconds=generated_at - started,
            scoring_seconds=perf_counter() - generated_at,
            sampler_contract_version=sampler_version,
        )
    except (EvaluationError, SquadOptimizationError, ScenarioError, ValueError) as error:
        completed = perf_counter()
        return PhaseEShadowFold(
            fold_id=fold.fold_id,
            status="ERROR",
            candidate_set_complete=False,
            error=f"{type(error).__name__}: {error}",
            generation_seconds=(generated_at or completed) - started,
            scoring_seconds=completed - generated_at if generated_at is not None else 0.0,
            sampler_contract_version=evidence.sampler_contract_version,
        )


def evaluate_phase_e_prepared_folds(
    handoff: PhaseCComponentHandoff,
    folds: Sequence[EvaluationFold],
    evidence: PhaseDBindingEvidence,
    *,
    frozen_candidate_count: int,
    conditional_residuals: ConditionalResidualConfig | None = None,
) -> dict[str, object]:
    """Retain all 137 binding folds and return internal, JSON-ready shadow evidence."""

    ordered = tuple(sorted(folds, key=lambda fold: fold.fold_id))
    if (
        len(evidence.fold_ids) != BINDING_FOLD_COUNT
        or tuple(fold.fold_id for fold in ordered) != evidence.fold_ids
    ):
        raise PhaseEShadowError("E3 must evaluate the complete binding population of 137 folds.")
    readings = tuple(
        evaluate_phase_e_decision(
            handoff,
            fold,
            evidence,
            frozen_candidate_count=frozen_candidate_count,
            conditional_residuals=conditional_residuals,
        )
        for fold in ordered
    )
    return {
        "binding_artifact_sha256": evidence.sha256,
        "frozen_candidate_count": frozen_candidate_count,
        "folds": [asdict(reading) for reading in readings],
        "verdict": evaluate_phase_e_shadow(
            readings, expected_fold_ids=evidence.fold_ids, phase_d_status=evidence.status
        ),
    }
