"""Two-stage, observation-contingent CP-SAT continuation on a fixed candidate menu.

Observation nodes contain posterior forecasts, never sampled realized future scores.
One continuation is solved per information node, not per hidden world outcome.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, replace

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
) -> RecourseResult:
    """Keep hold/control candidates; choose today before tomorrow's observation.

    Explicit chips enable v2's per-chip restricted menu. The baseline produces the menu. Future
    purchase prices are rebased for new buys; old holdings use their input sell prices.
    FT value is a paired continuation diagnostic, not a fitted terminal constant.
    """
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
    for choice in choices:
        excluded = []
        permitted = restrict_first_chip(rights, first, choice)
        for _ in range(candidate_count):
            result = optimize_transfer_plan(
                baseline,
                initial,
                optimization,
                transfer,
                chips=permitted,
                excluded_squads=excluded,
                linearization_level=2,
            )
            if result.solver_status is SolverStatus.INFEASIBLE:
                break
            _proved(result)
            week = result.weeks[0]
            menu.append(week)
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
    )
    hold_feasible = held.solver_status is not SolverStatus.INFEASIBLE
    if hold_feasible:
        _proved(held)
        if not any(
            (frozenset(w.selected_squad.player_id), w.chip)
            == (frozenset(held.weeks[0].selected_squad.player_id), held.weeks[0].chip)
            for w in menu
        ):
            menu.append(held.weeks[0])
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
                horizon, state, optimization, transfer, chips=remaining, linearization_level=2
            )
            _proved(plan)
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
                    )
                    _proved(extra)
                    marginal = sum(net_week_points(w) for w in extra.weeks) - net
            continuations.append(
                ContinuationValue(node.observation_id, node.probability, plan, marginal)
            )
            value += node.probability * net
        scored.append(RecourseCandidate(week, value, tuple(continuations)))
    chosen = max(range(len(scored)), key=lambda i: (scored[i].expected_net_points, -i))
    return RecourseResult(
        tuple(scored),
        chosen,
        hold_feasible,
        "observed_chip_recourse_v2" if rights.available else "observed_two_stage_recourse_v1",
    )
