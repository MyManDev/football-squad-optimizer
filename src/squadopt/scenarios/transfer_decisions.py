"""Score a member's rule-compliant transfer candidates on one shared component draw.

Transport-neutral core connection for the member advice path. The candidates are the
planner's own week decisions, all produced from one start state (held squad, bank, free
transfers) under the game's transfer, hit and chip rules; the control is the deterministic
plan the live path publishes. Every candidate is scored by the official scorer on the same
draw, the transfer hit is subtracted once from every scenario score, and the frozen Phase E
utility and selection rule choose. Nothing here re-optimizes, reads an outcome or invents a
calibration pin: the application supplies the pin explicitly, exactly as for Phase E.

This scope differs from Phase E's full-pool squad generation. A full-pool E2/E3 result says
nothing about transfer decisions, and a result here says nothing about the public mode names.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from enum import StrEnum
from math import isclose, isfinite
from numbers import Integral, Real
from typing import Final, Protocol

import pandas as pd

from squadopt.optimization import OptimizationResult, SolverStatus
from squadopt.optimization.candidates import DecisionSignature, decision_signature
from squadopt.optimization.coefficients import sort_players_by_id
from squadopt.scenarios.components import ComponentScenarioDraw
from squadopt.scenarios.decision_scoring import score_component_scenario_decision
from squadopt.scenarios.models import ScenarioConfig, ScenarioTarget, ScenarioValidationError
from squadopt.scenarios.selection import PHASE_E_UTILITY_CONTRACT_VERSION, integer_mean_cvar

TRANSFER_SCENARIO_CONTRACT_VERSION: Final = "transfer_scenario_selection_v1"
# The official component scorer knows the starting eleven, captain, vice-captain and autosubs.
# A bench boost or triple captain changes that arithmetic and is not scored here. A wildcard
# or free hit changes only the week's transfer accounting, which the planner already applied.
UNSUPPORTED_CHIPS: Final = frozenset({"bboost", "3xc"})
FREE_TRANSFER_CHIPS: Final = frozenset({"wildcard", "freehit"})
KNOWN_CHIPS: Final = UNSUPPORTED_CHIPS | FREE_TRANSFER_CHIPS


class TransferWeekLike(Protocol):
    """The first-week fields of a planner result this module reads; no planner import."""

    @property
    def gameweek(self) -> int: ...
    @property
    def selected_squad(self) -> pd.DataFrame: ...
    @property
    def starting_xi(self) -> pd.DataFrame: ...
    @property
    def bench(self) -> pd.DataFrame: ...
    @property
    def captain(self) -> pd.Series: ...
    @property
    def transfers_in(self) -> pd.DataFrame: ...
    @property
    def transfers_out(self) -> pd.DataFrame: ...
    @property
    def bank_before_tenths(self) -> int: ...
    @property
    def bank_after_tenths(self) -> int: ...
    @property
    def free_transfers_before(self) -> int: ...
    @property
    def paid_transfer_count(self) -> int: ...
    @property
    def transfer_hit_points(self) -> float: ...
    @property
    def projected_score(self) -> float: ...
    @property
    def chip(self) -> str | None: ...


class TransferPlanLike(Protocol):
    """The plan-level fields this module reads from a planner result."""

    @property
    def solver_status(self) -> SolverStatus: ...
    @property
    def weeks(self) -> Sequence[TransferWeekLike]: ...
    @property
    def horizon_fingerprint(self) -> str: ...
    @property
    def objective_value(self) -> float | None: ...


class TransferSelectionStatus(StrEnum):
    """Every fallback keeps the control, and its reason is recorded."""

    SELECTED = "SELECTED"
    FALLBACK_PHASE_D_NOT_CALIBRATED = "FALLBACK_PHASE_D_NOT_CALIBRATED"
    FALLBACK_SCENARIO_COVERAGE = "FALLBACK_SCENARIO_COVERAGE"
    FALLBACK_UNSUPPORTED_CHIP = "FALLBACK_UNSUPPORTED_CHIP"


def _plain(value: object) -> object:
    return int(value) if isinstance(value, Integral) and not isinstance(value, bool) else value


def _frame_ids(frame: pd.DataFrame) -> tuple[object, ...]:
    if "player_id" not in frame.columns:
        raise ScenarioValidationError("Transfer frames need a player_id column.")
    if frame.empty:
        return ()
    return tuple(_plain(value) for value in sort_players_by_id(frame)["player_id"].tolist())


def _sorted_ids(values: Sequence[object]) -> tuple[object, ...]:
    plain = [_plain(value) for value in values]
    return tuple(sorted(plain, key=lambda value: (str(type(value).__name__), str(value))))


@dataclass(frozen=True, slots=True)
class TransferStartState:
    """The held squad, bank and free transfers every candidate must have started from."""

    season: str
    gameweek: int
    squad_player_ids: tuple[object, ...]
    bank_tenths: int
    free_transfers: int

    def __post_init__(self) -> None:
        if not isinstance(self.season, str) or not self.season.strip():
            raise ScenarioValidationError("season must be a non-empty string.")
        for name in ("gameweek", "bank_tenths", "free_transfers"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, Integral) or value < 0:
                raise ScenarioValidationError(f"{name} must be a non-negative integer.")
        ids = _sorted_ids(tuple(self.squad_player_ids))
        if len(ids) != len(set(ids)) or not ids:
            raise ScenarioValidationError("squad_player_ids must be unique and non-empty.")
        object.__setattr__(self, "squad_player_ids", ids)

    @property
    def target(self) -> ScenarioTarget:
        return ScenarioTarget(season=self.season, gameweek=int(self.gameweek))

    @property
    def fingerprint(self) -> str:
        payload = {
            "season": self.season,
            "gameweek": int(self.gameweek),
            "squad_player_ids": [str(value) for value in self.squad_player_ids],
            "bank_tenths": int(self.bank_tenths),
            "free_transfers": int(self.free_transfers),
        }
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()


@dataclass(frozen=True, slots=True)
class TransferDecisionCandidate:
    """One planner week decision with the transfer accounting the planner attached to it.

    ``decision`` carries the post-transfer squad, starting eleven, bench and captain in the
    container the official scorer takes. The hit is the planner's own figure and is verified
    against the start state before it is applied, once, to every scenario score.
    """

    label: str
    gameweek: int
    decision: OptimizationResult
    transfers_in: tuple[object, ...]
    transfers_out: tuple[object, ...]
    free_transfers_before: int
    paid_transfer_count: int
    transfer_hit_points: float
    bank_before_tenths: int
    bank_after_tenths: int
    chip: str | None = None
    planner_status: str | None = None
    planner_objective: float | None = None
    horizon_fingerprint: str | None = None
    projected_score: float | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.label, str) or not self.label.strip():
            raise ScenarioValidationError("A transfer candidate needs a non-empty label.")
        if not isinstance(self.decision, OptimizationResult):
            raise ScenarioValidationError("decision must be an OptimizationResult.")
        if self.chip is not None and self.chip not in KNOWN_CHIPS:
            raise ScenarioValidationError(f"Unknown chip {self.chip!r} on a transfer candidate.")
        for name in (
            "gameweek",
            "free_transfers_before",
            "paid_transfer_count",
            "bank_before_tenths",
            "bank_after_tenths",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, Integral) or value < 0:
                raise ScenarioValidationError(f"{name} must be a non-negative integer.")
        if (
            isinstance(self.transfer_hit_points, bool)
            or not isinstance(self.transfer_hit_points, Real)
            or not isfinite(self.transfer_hit_points)
            or self.transfer_hit_points < 0
        ):
            raise ScenarioValidationError(
                "transfer_hit_points must be a finite non-negative number."
            )
        object.__setattr__(self, "transfers_in", _sorted_ids(tuple(self.transfers_in)))
        object.__setattr__(self, "transfers_out", _sorted_ids(tuple(self.transfers_out)))

    @property
    def transfer_count(self) -> int:
        return len(self.transfers_in)

    def signature(self) -> DecisionSignature:
        squad, starters, captain = decision_signature(self.decision)
        return (
            tuple(_plain(value) for value in squad),
            tuple(_plain(value) for value in starters),
            _plain(captain),
        )

    def identity(self) -> tuple[tuple[object, ...], tuple[object, ...], object, str | None]:
        """What makes two candidates the same decision: the complete signature and the chip.

        The same squad, eleven and captain reached under a wildcard and under paid transfers
        are two decisions with two hit costs; the transfers themselves follow from the squad
        and the start state, so they add nothing to the identity.
        """

        squad, starters, captain = self.signature()
        return squad, starters, captain, self.chip


def transfer_candidate_from_plan(
    plan: TransferPlanLike, *, label: str, gameweek: int | None = None
) -> TransferDecisionCandidate:
    """Adapt the first week of a planner result; later weeks are not decisions of this deadline.

    ``gameweek`` names the deadline the caller is deciding; a plan whose first week is another
    gameweek is refused here rather than evaluated against the wrong start state.
    """

    if not plan.weeks:
        raise ScenarioValidationError("A transfer plan needs at least one planned week.")
    week = plan.weeks[0]
    if gameweek is not None and int(week.gameweek) != int(gameweek):
        raise ScenarioValidationError(
            f"{label}: the plan's first week is gameweek {int(week.gameweek)}, not {int(gameweek)}."
        )
    decision = OptimizationResult(
        solver_status=plan.solver_status,
        selected_squad=week.selected_squad,
        starting_xi=week.starting_xi,
        bench=week.bench,
        captain=week.captain,
        total_cost_tenths=None,
        projected_score=float(week.projected_score),
        objective_value=plan.objective_value,
        diagnostics={},
    )
    return TransferDecisionCandidate(
        label=label,
        gameweek=int(week.gameweek),
        decision=decision,
        transfers_in=_frame_ids(week.transfers_in),
        transfers_out=_frame_ids(week.transfers_out),
        free_transfers_before=int(week.free_transfers_before),
        paid_transfer_count=int(week.paid_transfer_count),
        transfer_hit_points=float(week.transfer_hit_points),
        bank_before_tenths=int(week.bank_before_tenths),
        bank_after_tenths=int(week.bank_after_tenths),
        chip=week.chip,
        planner_status=plan.solver_status.value,
        planner_objective=plan.objective_value,
        horizon_fingerprint=plan.horizon_fingerprint,
        projected_score=float(week.projected_score),
    )


@dataclass(frozen=True, slots=True)
class TransferCandidateDiagnostic:
    """Identity, transfer accounting and scenario reading of one candidate; net of the hit."""

    rank: int
    label: str
    squad_ids: tuple[object, ...]
    starting_ids: tuple[object, ...]
    captain_id: object
    transfers_in: tuple[object, ...]
    transfers_out: tuple[object, ...]
    chip: str | None
    transfer_hit_points: float
    planner_status: str | None
    planner_objective: float | None
    squad_overlap: int
    same_captain: bool
    supported: bool
    covered: bool | None = None
    mean: float | None = None
    cvar: float | None = None
    utility_int: int | None = None
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class TransferScenarioSelection:
    """The chosen candidate, the retained control and every identity needed to replay it."""

    selected: TransferDecisionCandidate
    control: TransferDecisionCandidate
    status: TransferSelectionStatus
    reason: str
    selected_rank: int
    candidate_count: int
    candidate_count_scored: int
    start_state_fingerprint: str
    sampler_contract_version: str | None
    scenario_fingerprint: str | None
    component_fingerprint: str | None
    diagnostics: tuple[TransferCandidateDiagnostic, ...]
    contract_version: str = TRANSFER_SCENARIO_CONTRACT_VERSION
    utility_contract_version: str = PHASE_E_UTILITY_CONTRACT_VERSION


def draw_sampler_version(draw: ComponentScenarioDraw) -> str:
    """The sampler a draw declares; a draw without the key is the foundation sampler."""

    return str(
        draw.scenarios.diagnostics.get(
            "component_sampler_contract_version", draw.inputs.contract_version
        )
    )


def _validate_candidate(
    candidate: TransferDecisionCandidate,
    start_state: TransferStartState,
    *,
    transfer_hit_cost_points: float,
) -> None:
    if not candidate.decision.has_solution or candidate.decision.captain is None:
        raise ScenarioValidationError(f"{candidate.label}: a candidate needs a solved decision.")
    if int(candidate.gameweek) != int(start_state.gameweek):
        raise ScenarioValidationError(
            f"{candidate.label}: the plan is for gameweek {int(candidate.gameweek)}, not the "
            f"start state's gameweek {int(start_state.gameweek)}."
        )
    start = set(start_state.squad_player_ids)
    ins, outs = set(candidate.transfers_in), set(candidate.transfers_out)
    if len(candidate.transfers_in) != len(candidate.transfers_out):
        raise ScenarioValidationError(f"{candidate.label}: transfers in and out must pair up.")
    if ins & outs or not outs <= start or ins & start:
        raise ScenarioValidationError(
            f"{candidate.label}: transfers must leave the held squad and bring new players in."
        )
    squad, _, _ = candidate.signature()
    if set(squad) != (start - outs) | ins or len(squad) != len(start):
        raise ScenarioValidationError(
            f"{candidate.label}: the decision squad is not the held squad after its transfers."
        )
    if candidate.bank_before_tenths != start_state.bank_tenths:
        raise ScenarioValidationError(f"{candidate.label}: bank differs from the start state.")
    if candidate.free_transfers_before != start_state.free_transfers:
        raise ScenarioValidationError(
            f"{candidate.label}: free transfers differ from the start state."
        )
    expected_paid = (
        0
        if candidate.chip in FREE_TRANSFER_CHIPS
        else max(0, candidate.transfer_count - candidate.free_transfers_before)
    )
    if candidate.paid_transfer_count != expected_paid or not isclose(
        candidate.transfer_hit_points, expected_paid * transfer_hit_cost_points, abs_tol=1e-9
    ):
        raise ScenarioValidationError(
            f"{candidate.label}: paid transfers and hit points do not follow the free-transfer "
            f"and chip rules at {transfer_hit_cost_points} points per hit."
        )


def _validated_draw(
    draw: ComponentScenarioDraw, start_state: TransferStartState
) -> ComponentScenarioDraw:
    validated = ComponentScenarioDraw(
        scenarios=draw.scenarios.validated_copy(),
        inputs=draw.inputs,
        sampled_minutes=draw.sampled_minutes,
        sampled_appearances=draw.sampled_appearances,
        component_fingerprint=draw.component_fingerprint,
    )
    if validated.scenarios.target != start_state.target:
        raise ScenarioValidationError(
            f"The draw simulates {validated.scenarios.target.fold_id}, not the start state's "
            f"{start_state.target.fold_id}."
        )
    return validated


def _pinned(draw: ComponentScenarioDraw, calibrated_versions: Sequence[tuple[str, str]]) -> bool:
    """The Phase E pin rule with the frozen seed-0 configuration; nothing weaker for a member."""

    provenance = draw.inputs.provenance
    projection_provenance = draw.scenarios.projections.provenance
    identity = (provenance.model_version, draw_sampler_version(draw))
    return (
        identity in tuple(calibrated_versions)
        and provenance.model_version == projection_provenance.model_version
        and provenance.feature_contract_version == projection_provenance.feature_contract_version
        and provenance.season == draw.scenarios.target.season
        and provenance.target_gameweek == draw.scenarios.target.gameweek
        and draw.scenarios.config == ScenarioConfig()
    )


def evaluate_transfer_candidates(
    candidates: Sequence[TransferDecisionCandidate],
    draw: ComponentScenarioDraw | None,
    *,
    start_state: TransferStartState,
    transfer_hit_cost_points: float = 4.0,
    calibrated_versions: Sequence[tuple[str, str]] = (),
) -> TransferScenarioSelection:
    """Choose among fixed transfer candidates on one shared draw, or keep the control and say why.

    The first candidate is the control. Every candidate is checked against the start state
    and the transfer rules before any scenario is read; an inconsistent candidate is an error,
    never a silent exclusion. Candidates whose chip the official scorer cannot score are
    excluded with a reason; an unsupported control disables selection. The hit is subtracted
    from every scenario score exactly once, so the utility already contains its cost and the
    planner's objective is not consulted for ranking.
    """

    frozen = tuple(candidates)
    if not frozen or any(not isinstance(item, TransferDecisionCandidate) for item in frozen):
        raise ScenarioValidationError(
            "Candidates must be a non-empty sequence of transfer candidates."
        )
    if not isinstance(start_state, TransferStartState):
        raise ScenarioValidationError("start_state must be a TransferStartState.")
    if (
        isinstance(transfer_hit_cost_points, bool)
        or not isinstance(transfer_hit_cost_points, Real)
        or not isfinite(transfer_hit_cost_points)
        or transfer_hit_cost_points < 0
    ):
        raise ScenarioValidationError(
            "transfer_hit_cost_points must be a finite non-negative number."
        )
    labels = [item.label for item in frozen]
    if len(set(labels)) != len(labels):
        raise ScenarioValidationError("Transfer candidate labels must be unique.")
    horizons = {item.horizon_fingerprint for item in frozen if item.horizon_fingerprint is not None}
    if len(horizons) > 1:
        raise ScenarioValidationError("All candidates must come from one projection horizon.")
    signatures: list[DecisionSignature] = []
    identities: set[tuple[tuple[object, ...], tuple[object, ...], object, str | None]] = set()
    for candidate in frozen:
        _validate_candidate(
            candidate, start_state, transfer_hit_cost_points=transfer_hit_cost_points
        )
        identity = candidate.identity()
        if identity in identities:
            raise ScenarioValidationError(
                "Transfer candidates must be distinct complete decisions (squad, eleven, "
                "captain and chip)."
            )
        identities.add(identity)
        signatures.append(candidate.signature())

    control_signature = signatures[0]
    diagnostics = tuple(
        TransferCandidateDiagnostic(
            rank=rank,
            label=candidate.label,
            squad_ids=signature[0],
            starting_ids=signature[1],
            captain_id=signature[2],
            transfers_in=candidate.transfers_in,
            transfers_out=candidate.transfers_out,
            chip=candidate.chip,
            transfer_hit_points=float(candidate.transfer_hit_points),
            planner_status=candidate.planner_status,
            planner_objective=candidate.planner_objective,
            squad_overlap=len(set(signature[0]) & set(control_signature[0])),
            same_captain=signature[2] == control_signature[2],
            supported=candidate.chip not in UNSUPPORTED_CHIPS,
            reason=(
                f"{candidate.chip} is not scored by the official component scorer"
                if candidate.chip in UNSUPPORTED_CHIPS
                else None
            ),
        )
        for rank, (candidate, signature) in enumerate(zip(frozen, signatures, strict=True))
    )
    result = TransferScenarioSelection(
        selected=frozen[0],
        control=frozen[0],
        status=TransferSelectionStatus.FALLBACK_UNSUPPORTED_CHIP,
        reason="",
        selected_rank=0,
        candidate_count=len(frozen),
        candidate_count_scored=0,
        start_state_fingerprint=start_state.fingerprint,
        sampler_contract_version=None,
        scenario_fingerprint=None,
        component_fingerprint=None,
        diagnostics=diagnostics,
    )
    if not diagnostics[0].supported:
        return replace(
            result,
            reason=(
                f"the control plays {frozen[0].chip}, which the official component scorer "
                "cannot score; the control is kept"
            ),
        )
    if draw is None:
        return replace(
            result,
            status=TransferSelectionStatus.FALLBACK_PHASE_D_NOT_CALIBRATED,
            reason="no component scenario draw was supplied; the control is kept",
        )
    if not isinstance(draw, ComponentScenarioDraw):
        raise ScenarioValidationError("draw must be a ComponentScenarioDraw or None.")
    validated = _validated_draw(draw, start_state)
    result = replace(
        result,
        sampler_contract_version=draw_sampler_version(validated),
        scenario_fingerprint=validated.scenarios.scenario_fingerprint,
        component_fingerprint=validated.component_fingerprint,
    )
    if not _pinned(validated, calibrated_versions):
        return replace(
            result,
            status=TransferSelectionStatus.FALLBACK_PHASE_D_NOT_CALIBRATED,
            reason=(
                "the draw's model and sampler identity is not on the supplied calibration pin "
                "or its configuration is not the frozen default; the control is kept"
            ),
        )

    covered_ids = set(validated.scenarios.scenario_points.columns)
    scored: list[TransferCandidateDiagnostic] = []
    for candidate, record in zip(frozen, diagnostics, strict=True):
        if not record.supported:
            scored.append(record)
            continue
        if not set(record.squad_ids) <= covered_ids:
            scored.append(
                replace(record, covered=False, reason="a squad player is absent from the draw")
            )
            continue
        scores = score_component_scenario_decision(candidate.decision, validated)
        net = [
            float(score.total_points) - float(candidate.transfer_hit_points)
            for score in scores.scores
        ]
        utility = integer_mean_cvar(net)
        scored.append(
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
        diagnostics=tuple(scored),
        candidate_count_scored=sum(record.covered is True for record in scored),
    )
    if scored[0].covered is not True or result.candidate_count_scored < 2:
        return replace(
            result,
            status=TransferSelectionStatus.FALLBACK_SCENARIO_COVERAGE,
            reason=(
                "the control is not covered by the draw"
                if scored[0].covered is not True
                else "fewer than two candidates are scorable on the draw"
            )
            + "; the control is kept",
        )
    # max keeps the first rank on equal Python-integer utility, so a tie keeps the control.
    chosen = max(
        (record for record in scored if record.utility_int is not None),
        key=lambda record: record.utility_int if record.utility_int is not None else 0,
    )
    return replace(
        result,
        selected=frozen[chosen.rank],
        selected_rank=chosen.rank,
        status=TransferSelectionStatus.SELECTED,
        reason=(
            "the control has the highest net utility"
            if chosen.rank == 0
            else f"{chosen.label} has the highest net utility on the shared draw"
        ),
    )


def selection_record(selection: TransferScenarioSelection) -> Mapping[str, object]:
    """A JSON-shaped view of a selection for ledgers and diagnostics; no member-facing field."""

    return {
        "contract_version": selection.contract_version,
        "utility_contract_version": selection.utility_contract_version,
        "status": selection.status.value,
        "reason": selection.reason,
        "selected_rank": selection.selected_rank,
        "selected_label": selection.selected.label,
        "control_label": selection.control.label,
        "candidate_count": selection.candidate_count,
        "candidate_count_scored": selection.candidate_count_scored,
        "start_state_fingerprint": selection.start_state_fingerprint,
        "sampler_contract_version": selection.sampler_contract_version,
        "scenario_fingerprint": selection.scenario_fingerprint,
        "component_fingerprint": selection.component_fingerprint,
        "candidates": [
            {
                "rank": record.rank,
                "label": record.label,
                "squad_ids": [str(value) for value in record.squad_ids],
                "starting_ids": [str(value) for value in record.starting_ids],
                "captain_id": str(record.captain_id),
                "transfers_in": [str(value) for value in record.transfers_in],
                "transfers_out": [str(value) for value in record.transfers_out],
                "chip": record.chip,
                "transfer_hit_points": record.transfer_hit_points,
                "planner_status": record.planner_status,
                "planner_objective": record.planner_objective,
                "squad_overlap": record.squad_overlap,
                "same_captain": record.same_captain,
                "supported": record.supported,
                "covered": record.covered,
                "mean_net_of_hit": record.mean,
                "cvar_net_of_hit": record.cvar,
                "utility_int": record.utility_int,
                "reason": record.reason,
            }
            for record in selection.diagnostics
        ],
    }
