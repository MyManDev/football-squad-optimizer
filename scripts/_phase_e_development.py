"""Explicit development-only scoring; the production selector keeps refusing these draws."""

from dataclasses import replace

from squadopt.evaluation import DEVELOPMENT_OOF_CONTRACT_VERSION
from squadopt.optimization.candidates import SquadCandidateSet
from squadopt.scenarios import ScenarioConfig
from squadopt.scenarios.components import ComponentScenarioDraw
from squadopt.scenarios.decision_scoring import score_component_scenario_decision
from squadopt.scenarios.selection import (
    PhaseESelectionResult,
    PhaseESelectionStatus,
    integer_mean_cvar,
    select_phase_e_candidate,
)


def select_development_candidate(
    batch: SquadCandidateSet,
    draw: ComponentScenarioDraw,
    *,
    calibrated_versions: tuple[tuple[str, str], ...],
) -> PhaseESelectionResult:
    """Use the existing candidate validation, official scorer, utility and first-rank tie.

    This experiment boundary admits only the named C v2 development contract. It never
    strips provenance or supplies a production pin, and is not imported by the application.
    """

    result = select_phase_e_candidate(
        batch.candidates,
        draw,
        candidate_count_requested=batch.candidate_count_requested,
        candidate_set_complete=batch.complete,
        calibrated_versions=(),
    )
    if result.selection_status is not PhaseESelectionStatus.FALLBACK_PHASE_D_NOT_CALIBRATED:
        return result
    provenance = draw.inputs.provenance
    projection = draw.scenarios.projections.provenance
    sampler = str(
        draw.scenarios.diagnostics.get(
            "component_sampler_contract_version", draw.inputs.contract_version
        )
    )
    config = draw.scenarios.config
    if (
        provenance.development_contract != DEVELOPMENT_OOF_CONTRACT_VERSION
        or (provenance.model_version, sampler) not in calibrated_versions
        or provenance.model_version != projection.model_version
        or provenance.feature_contract_version != projection.feature_contract_version
        or provenance.season != draw.scenarios.target.season
        or provenance.target_gameweek != draw.scenarios.target.gameweek
        or replace(config, deterministic_seed=0) != ScenarioConfig()
        or config.deterministic_seed not in range(5)
    ):
        return result
    records = []
    covered_ids = set(draw.scenarios.scenario_points.columns)
    for candidate, record in zip(batch.candidates, result.diagnostics, strict=True):
        if not set(record.squad_ids) <= covered_ids:
            records.append(replace(record, covered=False))
            continue
        utility = integer_mean_cvar(score_component_scenario_decision(candidate, draw).total_points)
        records.append(
            replace(
                record,
                covered=True,
                mean=utility.mean,
                cvar=utility.cvar,
                utility_int=utility.utility_int,
            )
        )
    result = replace(
        result,
        diagnostics=tuple(records),
        candidate_count_scored=sum(record.covered is True for record in records),
    )
    if not records[0].covered or result.candidate_count_scored < 2:
        return replace(result, selection_status=PhaseESelectionStatus.FALLBACK_SCENARIO_COVERAGE)
    winner = max(
        (record for record in records if record.utility_int is not None),
        key=lambda record: record.utility_int if record.utility_int is not None else 0,
    )
    return replace(
        result,
        selected_result=batch.candidates[winner.rank],
        selected_candidate_rank=winner.rank,
        selection_status=PhaseESelectionStatus.SELECTED,
    )
