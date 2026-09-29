"""Two-stage, observation-contingent CP-SAT continuation on a fixed candidate menu.

Observation nodes contain posterior forecasts, never sampled realized future scores.
One continuation is solved per information node, not per hidden world outcome.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, replace

import pandas as pd

from squadopt.contracts.preferences import DecisionPreferences
from squadopt.optimization import OptimizationConfig, SolverStatus
from squadopt.planning.models import (
    ChipAvailability,
    FirstWeekOverlap,
    InitialSquadState,
    PlanningHorizon,
    PlanningWeekResult,
    TransferPlanningConfig,
    TransferPlanningValidationError,
    TransferPlanResult,
)
from squadopt.planning.optimizer import optimize_transfer_plan
from squadopt.planning.pricing import sell_price_tenths
from squadopt.planning.recourse_chips import net_week_points, remaining_chips, restrict_first_chip


@dataclass(frozen=True)
class ObservationNode:
    """A mutually exclusive next-deadline information state with prior probability."""

    observation_id: str
    probability: float
    horizon: PlanningHorizon


@dataclass(frozen=True)
class ContinuationValue:
    observation_id: str
    probability: float
    plan: TransferPlanResult
    extra_free_transfer_value: float | None


@dataclass(frozen=True)
class RecourseCandidate:
    first_week: PlanningWeekResult
    expected_net_points: float
    continuations: tuple[ContinuationValue, ...]


@dataclass(frozen=True)
class RecourseResult:
    candidates: tuple[RecourseCandidate, ...]
    chosen_index: int
    hold_feasible: bool
    contract_version: str = "observed_two_stage_recourse_v1"
    selection_status: str = "OPTIMAL_RESTRICTED_MENU"
    proposal_statuses: tuple[str, ...] = ()
    baseline_candidate_indices: tuple[int, ...] = ()


def _proved(result: TransferPlanResult) -> None:
    if result.solver_status is not SolverStatus.OPTIMAL or not result.weeks:
        raise TransferPlanningValidationError("Recourse comparison requires proved feasible plans.")


def _continuation_horizon(node: ObservationNode, week: PlanningWeekResult) -> PlanningHorizon:
    table = node.horizon.validated_copy().table.copy()
    bought = (
        {}
        if week.chip == "freehit"
        else dict(
            week.transfers_in[["player_id", "buy_price_tenths"]].itertuples(index=False, name=None)
        )
    )
    for index, row in table.iterrows():
        if row.player_id in bought:
            table.at[index, "sell_price_tenths"] = sell_price_tenths(
                current_tenths=int(row.buy_price_tenths), purchase_tenths=int(bought[row.player_id])
            )
    return PlanningHorizon(table)


def optimize_observed_recourse(
    baseline: PlanningHorizon,
    initial: InitialSquadState,
    nodes: Sequence[ObservationNode],
    optimization: OptimizationConfig,
    transfer: TransferPlanningConfig | None = None,
    *,
    candidate_count: int = 3,
    value_extra_free_transfer: bool = True,
    chips: ChipAvailability | None = None,
    preferences: DecisionPreferences | None = None,
    require_optimal: bool = True,
    observation_proposals: bool = False,
) -> RecourseResult:
    """Keep hold/control candidates; choose today before tomorrow's observation.

    Explicit chips enable v2's per-chip restricted menu. The baseline produces the menu. Future
    purchase prices are rebased for new buys; old holdings use their input sell prices.
    FT value is a paired continuation diagnostic, not a fitted terminal constant.
    Bounded mode retains feasible incumbents with explicit proof status. Observation
    proposals expand the action menu only: every action is evaluated in EVERY node,
    before choosing one common first decision. They are not perfect information.
    No seasonal improvement guarantee follows from this finite-menu comparison.
    """
    if not isinstance(require_optimal, bool) or not isinstance(observation_proposals, bool):
        raise ValueError("Recourse search switches must be booleans.")
    proposal_statuses: list[str] = []

    def accept(result: TransferPlanResult) -> None:
        if require_optimal:
            _proved(result)
        elif (
            result.solver_status not in (SolverStatus.OPTIMAL, SolverStatus.FEASIBLE)
            or not result.weeks
        ):
            raise TransferPlanningValidationError(
                "Recourse requires a feasible plan in every node."
            )

    baseline = baseline.validated_copy()
    transfer = transfer or TransferPlanningConfig()
    rights = chips or ChipAvailability()
    if any(
        p.holding_value_points not in (None, 0)
        for name in rights.available
        for p in rights.windows_for(name)
    ):
        raise ValueError("Recourse requires explicit zero terminal chip values.")
    if (
        isinstance(candidate_count, bool)
        or not isinstance(candidate_count, int)
        or not 1 <= candidate_count <= 20
    ):
        raise ValueError("candidate_count must be an integer between 1 and 20.")
    if (
        transfer.horizon_discount_factor != 1
        or transfer.banked_transfer_value_points != 0
        or transfer.chip_holding_value_points
        or transfer.transfer_hit_cost_points != transfer.hit_points_charged
        or optimization.bench_weight != 0
    ):
        raise ValueError(
            "Recourse net-points comparison requires zero bench/terminal weights, "
            "no discount, and actual hit costs."
        )
    if len(baseline.gameweeks) < 2 or not nodes:
        raise ValueError("Recourse requires a current and future horizon and observations.")
    identities = [node.observation_id for node in nodes]
    if any(not x or not isinstance(x, str) for x in identities) or len(set(identities)) != len(
        nodes
    ):
        raise ValueError("Each information node must have one unique observation ID.")
    probabilities = [node.probability for node in nodes]
    if any(
        isinstance(p, bool) or not math.isfinite(p) or p <= 0 for p in probabilities
    ) or not math.isclose(sum(probabilities), 1.0, rel_tol=0, abs_tol=1e-10):
        raise ValueError("Observation probabilities must be positive and sum to one.")
    universe = set(baseline.table.player_id)
    metadata = baseline.table.loc[baseline.table.gameweek.eq(baseline.gameweeks[0])].set_index(
        "player_id"
    )
    for node in nodes:
        if (
            node.horizon.gameweeks != baseline.gameweeks[1:]
            or set(node.horizon.table.player_id) != universe
        ):
            raise ValueError(
                "Every observation must cover the same future weeks and player universe."
            )
        for col in ("position", "team_id"):
            if (
                not node.horizon.table[col]
                .eq(node.horizon.table.player_id.map(metadata[col]))
                .all()
            ):
                raise ValueError("Observation changes roster identity or position.")
    menu: list[PlanningWeekResult] = []
    excluded: list[frozenset[object]] = []
    first = baseline.gameweeks[0]
    choices: list[str | None] = [
        None,
        *sorted(name for name in rights.available if first in rights.gameweeks_for(name)),
    ]
    if first in rights.forced:
        choices = [rights.forced[first]]
    if preferences is not None and preferences.save_chips:
        choices = [rights.forced.get(first)]
    proposals = [baseline]
    if observation_proposals:
        today = baseline.table.loc[baseline.table.gameweek.eq(first)]
        proposals.extend(
            PlanningHorizon(pd.concat([today, node.horizon.table], ignore_index=True))
            for node in nodes
        )

    def add(week: PlanningWeekResult) -> None:
        key = (frozenset(week.selected_squad.player_id), week.chip)
        for i, previous in enumerate(menu):
            if key == (frozenset(previous.selected_squad.player_id), previous.chip):
                # Same resource transition; keep the better current XI/captain.
                if net_week_points(week) > net_week_points(previous):
                    menu[i] = week
                return
        menu.append(week)

    baseline_keys: set[tuple[frozenset[object], str | None]] = set()
    for proposal_index, proposal in enumerate(proposals):
        for choice in choices:
            excluded = []
            permitted = restrict_first_chip(rights, first, choice)
            for _ in range(candidate_count):
                result = optimize_transfer_plan(
                    proposal,
                    initial,
                    optimization,
                    transfer,
                    chips=permitted,
                    excluded_squads=excluded,
                    linearization_level=2,
                    preferences=preferences,
                    protect_hold=not require_optimal,
                )
                proposal_statuses.append(result.solver_status.name)
                if result.solver_status is SolverStatus.INFEASIBLE:
                    break
                accept(result)
                week = result.weeks[0]
                add(week)
                if proposal_index == 0:
                    baseline_keys.add((frozenset(week.selected_squad.player_id), week.chip))
                excluded.append(frozenset(week.selected_squad.player_id))
    held = optimize_transfer_plan(
        baseline,
        initial,
        optimization,
        transfer,
        chips=restrict_first_chip(rights, first, rights.forced.get(first)),
        first_week_overlap=FirstWeekOverlap(
            frozenset(initial.squad_player_ids), minimum=optimization.squad_size
        ),
        linearization_level=2,
        preferences=preferences,
        protect_hold=not require_optimal,
    )
    proposal_statuses.append(held.solver_status.name)
    hold_feasible = held.solver_status is not SolverStatus.INFEASIBLE
    if hold_feasible:
        accept(held)
        add(held.weeks[0])
        baseline_keys.add((frozenset(held.weeks[0].selected_squad.player_id), held.weeks[0].chip))
    if not menu:
        raise TransferPlanningValidationError("No feasible first-week decision is available.")
    scored: list[RecourseCandidate] = []
    for week in menu:
        state = InitialSquadState(
            initial.squad_player_ids
            if week.chip == "freehit"
            else tuple(week.selected_squad.player_id),
            initial.bank_tenths if week.chip == "freehit" else week.bank_after_tenths,
            week.free_transfers_for_next_gameweek,
        )
        continuations: list[ContinuationValue] = []
        value = net_week_points(week)
        remaining = remaining_chips(rights, week)
        for node in nodes:
            horizon = _continuation_horizon(node, week)
            plan = optimize_transfer_plan(
                horizon,
                state,
                optimization,
                transfer,
                chips=remaining,
                linearization_level=2,
                preferences=preferences,
                protect_hold=not require_optimal,
            )
            accept(plan)
            net = sum(net_week_points(w) for w in plan.weeks)
            marginal: float | None = None
            if value_extra_free_transfer:
                if state.free_transfers >= transfer.max_free_transfers:
                    marginal = 0.0
                else:
                    richer = replace(state, free_transfers=state.free_transfers + 1)
                    extra = optimize_transfer_plan(
                        horizon,
                        richer,
                        optimization,
                        transfer,
                        chips=remaining,
                        linearization_level=2,
                        preferences=preferences,
                        protect_hold=not require_optimal,
                    )
                    accept(extra)
                    # Two lower bounds cannot identify the marginal optimum value.
                    if plan.solver_status is extra.solver_status is SolverStatus.OPTIMAL:
                        marginal = sum(net_week_points(w) for w in extra.weeks) - net
            continuations.append(
                ContinuationValue(node.observation_id, node.probability, plan, marginal)
            )
            value += node.probability * net
        scored.append(RecourseCandidate(week, value, tuple(continuations)))
    chosen = max(range(len(scored)), key=lambda i: (scored[i].expected_net_points, -i))
    all_proved = all(s != "FEASIBLE" for s in proposal_statuses) and all(
        c.plan.solver_status is SolverStatus.OPTIMAL
        for candidate in scored
        for c in candidate.continuations
    )
    return RecourseResult(
        tuple(scored),
        chosen,
        hold_feasible,
        "observed_rollout_v3"
        if observation_proposals or not require_optimal
        else (
            "observed_chip_recourse_v2" if rights.available else "observed_two_stage_recourse_v1"
        ),
        "OPTIMAL_RESTRICTED_MENU" if all_proved else "FEASIBLE_RESTRICTED_MENU",
        tuple(proposal_statuses),
        tuple(
            i
            for i, c in enumerate(scored)
            if (frozenset(c.first_week.selected_squad.player_id), c.first_week.chip)
            in baseline_keys
        ),
    )
