"""Solve one strategy's plan: the declared constraint, priced against the control.

The bridge between the catalogue and the planner. A strategy's declared constraints —
today the overlap band against a rival's known eleven — become solver terms
(``FirstWeekOverlap``), the plan is solved with the same deterministic planner that
decides everything else, and only a **proven** plan comes back: an unproven entry under
a band would be exactly the machine-dependent arbitrariness the live path refuses
everywhere else, so an infeasible or unproven band yields ``None`` and the caller's
menu shortens honestly.

The price tag is computed here and nowhere else: the control's expected points minus
the banded plan's, both from proven solves of the same inputs. What the constraint
costs is a difference of two expected points — the same currency the site publishes.
"""

from collections.abc import Mapping
from dataclasses import dataclass

from squadopt.application.strategies.catalog import (
    Strategy,
    StrategyConfigurationError,
)
from squadopt.optimization import OptimizationConfig, SolverStatus
from squadopt.planning import (
    ChipAvailability,
    FirstWeekOverlap,
    InitialSquadState,
    PlanningHorizon,
    TransferPlanningConfig,
    TransferPlanResult,
    optimize_transfer_plan,
)


@dataclass(frozen=True, slots=True)
class StrategyPlan:
    """One strategy's proven plan, with its overlap and price read off the solve."""

    slug: str
    plan: TransferPlanResult
    overlap_count: int | None
    """How many of the rival's known players the first week holds; None without a rival."""
    expected_points_cost: float
    """The control's expected points minus this plan's — what the constraint costs."""


def _band(
    strategy: Strategy,
    knob_values: Mapping[str, object],
    rival_player_ids: frozenset[object] | None,
) -> FirstWeekOverlap | None:
    floor = strategy.constraints.overlap_floor
    ceiling = strategy.constraints.overlap_ceiling
    for name, value in knob_values.items():
        if name not in strategy.knobs:
            raise StrategyConfigurationError(
                f"{strategy.slug!r} declares no knob {name!r}; the searched space must "
                "be the declared space."
            )
        if name == "overlap_floor":
            floor = int(str(value))
        elif name == "overlap_ceiling":
            ceiling = int(str(value))
    if floor is None and ceiling is None:
        return None
    if rival_player_ids is None:
        raise StrategyConfigurationError(
            f"{strategy.slug!r} needs a rival to state its overlap band."
        )
    return FirstWeekOverlap(player_ids=frozenset(rival_player_ids), minimum=floor, maximum=ceiling)


def solve_strategy_plan(
    strategy: Strategy,
    horizon: PlanningHorizon,
    initial_state: InitialSquadState,
    optimization_config: OptimizationConfig,
    transfer_config: TransferPlanningConfig | None = None,
    chips: ChipAvailability | None = None,
    *,
    rival_player_ids: frozenset[object] | None = None,
    knob_values: Mapping[str, object] | None = None,
    control_plan: TransferPlanResult | None = None,
) -> StrategyPlan | None:
    """Solve ``strategy``'s constrained plan; ``None`` when it cannot be proven.

    ``knob_values`` override the declared constraint defaults along the strategy's own
    knobs — an undeclared knob is refused, so a search cannot move what was not
    declared. ``control_plan`` is the unconstrained proven plan for the same inputs;
    when given, the price tag is computed against it (a caller building a menu solves
    the control once, not per band). Without it the price is computed against a fresh
    control solve.

    An infeasible band and an unproven solve both return ``None``: the menu shortens,
    no unproven entry is produced, and nothing is published for the band — the
    difference between "the band is impossible" and "the band was not attempted" stays
    visible to the caller through which bands it asked for.
    """

    if strategy.rival_required and rival_player_ids is None:
        raise StrategyConfigurationError(f"{strategy.slug!r} requires a rival.")
    band = _band(strategy, dict(knob_values or {}), rival_player_ids)
    plan = optimize_transfer_plan(
        horizon,
        initial_state,
        optimization_config,
        transfer_config,
        chips,
        first_week_overlap=band,
    )
    if plan.solver_status is not SolverStatus.OPTIMAL or not plan.weeks:
        return None
    control = control_plan
    if control is None:
        control = optimize_transfer_plan(
            horizon, initial_state, optimization_config, transfer_config, chips
        )
    if control.solver_status is not SolverStatus.OPTIMAL or not control.weeks:
        # A price tag against an unproven control would be a number nobody measured.
        return None
    control_points = float(control.total_projected_score or 0.0)
    plan_points = float(plan.total_projected_score or 0.0)
    overlap = None
    if band is not None:
        # Ids are whatever the horizon carries — codes in production, labels in tests —
        # so they are matched as they are, the same rule the planner's cuts follow.
        first_week = plan.weeks[0]
        held = {str(value) for value in first_week.selected_squad["player_id"].tolist()}
        overlap = len(held & {str(p) for p in band.player_ids})
    return StrategyPlan(
        slug=strategy.slug,
        plan=plan,
        overlap_count=overlap,
        expected_points_cost=control_points - plan_points,
    )
