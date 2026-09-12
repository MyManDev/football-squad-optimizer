"""Independent chip alternatives under the same captured planning policy.

These are window comparisons, not a joint chip calendar or an estimate of a chip's
option value after the horizon. The operational no-chip decision remains the control.
"""

import math
from dataclasses import dataclass

from squadopt.data.errors import DataSourceError
from squadopt.live.recommendation import Projection, RecommendationInputs
from squadopt.live.rules import ChipWindow, SeasonRules
from squadopt.live.transfers import HeldSquad, plan_transfer_horizon, plan_transfers
from squadopt.optimization import (
    OptimizationConfig,
    SolverExecutionError,
    wall_clock_stopped_the_search,
)
from squadopt.planning import (
    ChipAvailability,
    PlanningWeekResult,
    ProjectionHorizon,
    TransferPlanResult,
)


@dataclass(frozen=True, slots=True)
class ChipRecommendation:
    window: ChipWindow
    remaining: int
    gameweek: int | None
    expected_gain: float | None
    reason: str
    plan: TransferPlanResult | None


def expected_chip_week_points(week: PlanningWeekResult) -> float:
    """The planner reports bench points separately, including on Bench Boost."""
    return week.projected_score + (week.projected_bench_points if week.chip == "bboost" else 0.0)


def _net(plan: TransferPlanResult) -> float:
    if not plan.has_solution:
        raise DataSourceError("A chip comparison requires a feasible plan.")
    if wall_clock_stopped_the_search(plan.solver_status, plan.diagnostics):
        raise SolverExecutionError("Chip comparison stopped at the wall-clock safety cap.")
    week_hits = [week.transfer_hit_points for week in plan.weeks]
    if any(not math.isfinite(value) or value < 0 for value in week_hits):
        raise DataSourceError("A chip comparison requires finite non-negative weekly hit charges.")
    score, hits = (
        sum(expected_chip_week_points(week) for week in plan.weeks),
        plan.total_transfer_hit_points,
    )
    if score is None or hits is None or not math.isfinite(score) or not math.isfinite(hits):
        raise DataSourceError("A chip comparison requires finite projected points and hit charges.")
    if not math.isclose(sum(week_hits), hits, rel_tol=0.0, abs_tol=1e-8):
        raise DataSourceError("Chip comparison total hits disagree with its weekly charges.")
    return score - hits


def recommend_chips(
    inputs: RecommendationInputs,
    projection: Projection,
    held: HeldSquad,
    rules: SeasonRules,
    control: TransferPlanResult,
    *,
    horizon: ProjectionHorizon | None = None,
    optimization: OptimizationConfig | None = None,
) -> tuple[ChipRecommendation, ...]:
    """One solve per unspent chip window, sharing the no-chip control.

    Both plans include actual hit charges in the published difference. The planner
    still selects each plan under its margin, terminal FT value and horizon discount.
    A FEASIBLE alternative is a found plan, never described as the best possible one.
    """
    targets = (inputs.deadline.gameweek,) if horizon is None else horizon.target_gameweeks
    if tuple(week.gameweek for week in control.weeks) != targets:
        raise DataSourceError("Chip alternatives and the no-chip control need the same horizon.")
    if any(week.chip is not None for week in control.weeks):
        raise DataSourceError("The chip comparison control must not play a chip.")
    control_net = _net(control)
    result = []
    for window in sorted(rules.chips, key=lambda item: (item.start_event, item.name)):
        remaining = window.number - sum(
            window.covers(week) for week in held.chips_used.get(window.name, ())
        )
        if remaining <= 0 or window.stop_event < targets[0]:
            continue
        available = frozenset(week for week in targets if window.covers(week))
        if not available:
            result.append(
                ChipRecommendation(window, remaining, None, None, "outside_horizon", None)
            )
            continue
        if horizon is None:
            plan, _, _ = plan_transfers(
                inputs, projection, held, rules, optimization=optimization, chip=window.name
            )
        else:
            plan, _ = plan_transfer_horizon(
                inputs,
                horizon,
                held,
                rules,
                optimization=optimization,
                chips=ChipAvailability(available={window.name: available}),
            )
        if tuple(week.gameweek for week in plan.weeks) != targets:
            raise DataSourceError("Chip alternative returned a different horizon.")
        if (
            not control.diagnostics.get("configuration_fingerprint")
            or plan.horizon_fingerprint != control.horizon_fingerprint
            or plan.diagnostics.get("configuration_fingerprint")
            != control.diagnostics.get("configuration_fingerprint")
        ):
            raise DataSourceError(
                "Chip alternatives need the same inputs and policy as their control."
            )
        played = [week for week in plan.weeks if week.chip is not None]
        if len(played) > 1 or any(
            week.chip != window.name or week.gameweek not in available for week in played
        ):
            raise DataSourceError("Chip alternative violates the requested chip window.")
        chosen = played[0].gameweek if played else None
        gain = _net(plan) - control_net
        play = chosen is not None and gain > 0
        result.append(
            ChipRecommendation(
                window,
                remaining,
                chosen if play else None,
                gain if chosen is not None else None,
                "window_gain" if play else "no_positive_gain",
                plan,
            )
        )
    return tuple(result)
