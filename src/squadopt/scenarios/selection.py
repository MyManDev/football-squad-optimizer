"""Select a frozen complete decision using one shared component scenario draw."""

from collections.abc import Sequence
from dataclasses import dataclass, replace
from enum import StrEnum
from math import isfinite
from numbers import Integral, Real
from typing import Final

from squadopt.evaluation.scoring import complete_optimization_decision
from squadopt.optimization import OptimizationResult, SolverStatus
from squadopt.optimization.coefficients import scale_expected_points, sort_players_by_id
from squadopt.scenarios.components import ComponentScenarioDraw
from squadopt.scenarios.decision_scoring import score_component_scenario_decision
from squadopt.scenarios.models import ScenarioConfig, ScenarioValidationError

PHASE_E_UTILITY_CONTRACT_VERSION: Final = "phase_e_integer_mean_cvar_v1"
PHASE_E_SCENARIO_COUNT: Final = 1000
PHASE_E_POINTS_SCALE: Final = 1000
PHASE_E_TAIL_COUNT: Final = 100
PHASE_E_WEIGHT_SCALE: Final = 1000
PHASE_E_RISK_WEIGHT: Final = 250
PHASE_E_CANDIDATE_COUNTS: Final = (4, 8, 16)


class PhaseESelectionStatus(StrEnum):
    """Internal selection outcomes; every fallback returns the original control."""

    SELECTED = "SELECTED"
    FALLBACK_INCOMPLETE_CANDIDATES = "FALLBACK_INCOMPLETE_CANDIDATES"
    FALLBACK_SCENARIO_COVERAGE = "FALLBACK_SCENARIO_COVERAGE"
    FALLBACK_PHASE_D_NOT_CALIBRATED = "FALLBACK_PHASE_D_NOT_CALIBRATED"


@dataclass(frozen=True, slots=True)
class PhaseEUtility:
    """Exact comparison value and point-scale readings from the same integer sums."""

    mean: float
    cvar: float
    utility_int: int


def integer_mean_cvar(scores: Sequence[float]) -> PhaseEUtility:
    """Apply the frozen 0.25 risk weight and worst-100-of-1000 lower tail."""

    if len(scores) != PHASE_E_SCENARIO_COUNT:
        raise ScenarioValidationError("Phase E requires exactly 1000 scenario scores.")
    if any(
        isinstance(value, bool) or not isinstance(value, Real) or not isfinite(value)
        for value in scores
    ):
        raise ScenarioValidationError("Phase E scenario scores must be finite numbers.")
    integers = [scale_expected_points(value, PHASE_E_POINTS_SCALE) for value in scores]
    total = sum(integers)
    tail = sum(sorted(integers)[:PHASE_E_TAIL_COUNT])
    return PhaseEUtility(
        mean=total / (PHASE_E_POINTS_SCALE * PHASE_E_SCENARIO_COUNT),
        cvar=tail / (PHASE_E_POINTS_SCALE * PHASE_E_TAIL_COUNT),
        utility_int=(
            (PHASE_E_WEIGHT_SCALE - PHASE_E_RISK_WEIGHT) * PHASE_E_TAIL_COUNT * total
            + PHASE_E_RISK_WEIGHT * PHASE_E_SCENARIO_COUNT * tail
        ),
    )


@dataclass(frozen=True, slots=True)
class PhaseECandidateDiagnostic:
    """Identity, deterministic cost and optional scenario reading for one candidate."""

    rank: int
    squad_ids: tuple[object, ...]
    starting_ids: tuple[object, ...]
    captain_id: object
    objective: float
    deterministic_gap: float
    squad_overlap: int
    eleven_overlap: int
    same_captain: bool
    covered: bool | None = None
    mean: float | None = None
    cvar: float | None = None
    utility_int: int | None = None


@dataclass(frozen=True, slots=True)
class PhaseESelectionResult:
    """An internal decision and its provenance, with no member-facing probability."""

    selected_result: OptimizationResult
    control_result: OptimizationResult
    selection_status: PhaseESelectionStatus
    selected_candidate_rank: int
    candidate_count_requested: int
    candidate_count_proven: int
    candidate_count_scored: int
    scenario_fingerprint: str | None
    component_fingerprint: str | None
    diagnostics: tuple[PhaseECandidateDiagnostic, ...]
    utility_contract_version: str = PHASE_E_UTILITY_CONTRACT_VERSION


def _candidate_diagnostics(
    candidates: tuple[OptimizationResult, ...],
) -> tuple[PhaseECandidateDiagnostic, ...]:
    records: list[PhaseECandidateDiagnostic] = []
    signatures: set[tuple[tuple[object, ...], tuple[object, ...], object]] = set()
    for rank, candidate in enumerate(candidates):
        if rank > 0 and not candidate.has_solution:
            # A failed alternative has no complete identity to report; its primary
            # status still makes the set incomplete before scenarios are consulted.
            continue
        # Keep the existing completion boundary's exception for an unsolved control.
        decision = complete_optimization_decision(candidate)
        squad = tuple(sort_players_by_id(decision.squad)["player_id"].tolist())
        starters = tuple(sort_players_by_id(candidate.starting_xi)["player_id"].tolist())
        signature = (squad, starters, decision.captain_id)
        if signature in signatures:
            raise ScenarioValidationError("Phase E complete candidate signatures must be unique.")
        signatures.add(signature)
        objective = candidate.objective_value
        if objective is None or not isfinite(objective):
            raise ScenarioValidationError("Candidate objectives must be finite.")
        if records and objective > records[-1].objective:
            raise ScenarioValidationError("Candidates must be ordered by decreasing objective.")
        control = records[0] if records else None
        records.append(
            PhaseECandidateDiagnostic(
                rank=rank,
                squad_ids=squad,
                starting_ids=starters,
                captain_id=decision.captain_id,
                objective=objective,
                deterministic_gap=control.objective - objective if control else 0.0,
                squad_overlap=len(set(squad) & set(control.squad_ids)) if control else 15,
                eleven_overlap=len(set(starters) & set(control.starting_ids)) if control else 11,
                same_captain=decision.captain_id == control.captain_id if control else True,
            )
        )
    return tuple(records)


def select_phase_e_candidate(
    candidates: Sequence[OptimizationResult],
    draw: ComponentScenarioDraw | None,
    *,
    candidate_count_requested: int,
    candidate_set_complete: bool,
    calibrated_versions: tuple[tuple[str, str], ...] = (),
) -> PhaseESelectionResult:
    """Score fixed candidates without generating decisions or drawing new scenarios.

    The application owns the reviewed calibration pin and supplies it explicitly. An empty
    pin disables selection. The generator owns candidate-set completeness, including legal
    exhaustion; primary statuses are also checked here before any scenario is consulted.
    """

    if (
        isinstance(candidate_count_requested, bool)
        or not isinstance(candidate_count_requested, Integral)
        or candidate_count_requested not in PHASE_E_CANDIDATE_COUNTS
    ):
        raise ScenarioValidationError("Phase E candidate_count_requested must be 4, 8 or 16.")
    if not isinstance(candidate_set_complete, bool):
        raise ScenarioValidationError("candidate_set_complete must be a boolean.")
    frozen = tuple(candidates)
    if not frozen or len(frozen) > candidate_count_requested:
        raise ScenarioValidationError(
            "Phase E requires a control and at most the requested candidates."
        )
    diagnostics = _candidate_diagnostics(frozen)
    proven = sum(candidate.solver_status is SolverStatus.OPTIMAL for candidate in frozen)
    result = PhaseESelectionResult(
        selected_result=frozen[0],
        control_result=frozen[0],
        selection_status=PhaseESelectionStatus.FALLBACK_INCOMPLETE_CANDIDATES,
        selected_candidate_rank=0,
        candidate_count_requested=candidate_count_requested,
        candidate_count_proven=proven,
        candidate_count_scored=0,
        scenario_fingerprint=None,
        component_fingerprint=None,
        diagnostics=diagnostics,
    )
    if not candidate_set_complete or proven != len(frozen):
        return result
    result = replace(result, selection_status=PhaseESelectionStatus.FALLBACK_PHASE_D_NOT_CALIBRATED)
    if draw is None:
        return result
    if not isinstance(draw, ComponentScenarioDraw):
        raise ScenarioValidationError("draw must be a ComponentScenarioDraw or None.")
    validated = ComponentScenarioDraw(
        scenarios=draw.scenarios.validated_copy(),
        inputs=draw.inputs,
        sampled_minutes=draw.sampled_minutes,
        sampled_appearances=draw.sampled_appearances,
        component_fingerprint=draw.component_fingerprint,
    )
    result = replace(
        result,
        scenario_fingerprint=validated.scenarios.scenario_fingerprint,
        component_fingerprint=validated.component_fingerprint,
    )
    identity = (validated.inputs.provenance.model_version, validated.inputs.contract_version)
    provenance = validated.inputs.provenance
    projection_provenance = validated.scenarios.projections.provenance
    # Seeds 0..4 are permitted for the preregistered outcome-free sensitivity diagnostic.
    config = validated.scenarios.config
    if (
        identity not in calibrated_versions
        or provenance.model_version != projection_provenance.model_version
        or provenance.feature_contract_version != projection_provenance.feature_contract_version
        or provenance.season != validated.scenarios.target.season
        or provenance.target_gameweek != validated.scenarios.target.gameweek
        or replace(config, deterministic_seed=0) != ScenarioConfig()
    ):
        return result
    if config.deterministic_seed not in range(5):
        return result
    scored_records: list[PhaseECandidateDiagnostic] = []
    for candidate, record in zip(frozen, diagnostics, strict=True):
        if not set(record.squad_ids) <= set(validated.scenarios.scenario_points.columns):
            scored_records.append(replace(record, covered=False))
            continue
        scored = score_component_scenario_decision(candidate, validated)
        utility = integer_mean_cvar(scored.total_points)
        scored_records.append(
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
        diagnostics=tuple(scored_records),
        candidate_count_scored=sum(record.covered is True for record in scored_records),
    )
    if not scored_records[0].covered or result.candidate_count_scored < 2:
        return replace(result, selection_status=PhaseESelectionStatus.FALLBACK_SCENARIO_COVERAGE)
    # max keeps the first rank on equal Python-integer utility, including the control.
    selected = max(
        (record for record in scored_records if record.utility_int is not None),
        key=lambda record: record.utility_int if record.utility_int is not None else 0,
    )
    return replace(
        result,
        selected_result=frozen[selected.rank],
        selected_candidate_rank=selected.rank,
        selection_status=PhaseESelectionStatus.SELECTED,
    )
