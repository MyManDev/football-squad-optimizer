"""Bounded sequential construction followed by full-model incumbent protection."""

from dataclasses import replace
from typing import cast

from squadopt.contracts.preferences import DecisionPreferences
from squadopt.optimization import OptimizationConfig, SolverExecutionError
from squadopt.planning.models import (
    ChipAvailability,
    InitialSquadState,
    PlanningHorizon,
    TransferPlanningConfig,
    TransferPlanningValidationError,
    TransferPlanResult,
)
from squadopt.planning.optimizer import optimize_transfer_plan
from squadopt.planning.segmented import SegmentConstructionError, plan_in_segments

GUARDED_PLANNER_VERSION = "sequential_certified_window_v1"
GUARDED_PLAN_LIMIT = (
    "This experimental plan compares a week-by-week starting plan with a full-window "
    "search, retaining the starting plan only after full-window validation. "
    "Future performance is not established."
)
GUARDED_FALLBACK_LIMIT = (
    "The week-by-week starting plan could not be completed; "
    "this result uses the standard full-window search with the remaining budget."
)


def optimize_guarded_window(
    horizon: PlanningHorizon,
    initial: InitialSquadState,
    optimization: OptimizationConfig,
    transfer: TransferPlanningConfig,
    *,
    chips: ChipAvailability | None = None,
    preferences: DecisionPreferences | None = None,
) -> TransferPlanResult:
    """Spend 10% on construction and 90% on certification/search, without retries.

    No extra hold solve follows a certified seed. An incomplete deterministic seed
    falls back to the standard search, reserving its one-unit hold cost from the
    remaining allocation. Clock-truncated construction is refused by the same
    publication policy as a clock-truncated final search. Invalid contracts and
    failed certification are not swallowed into an uncertified answer.
    """
    budget = optimization.solver_deterministic_time_limit
    if budget is None or budget < 2:
        raise TransferPlanningValidationError("Guarded windows need a budget of at least two.")
    seed_cap = budget * 0.1
    final_cap = budget - seed_cap
    seed = None
    try:
        seed = plan_in_segments(
            horizon,
            initial,
            replace(
                optimization,
                solver_deterministic_time_limit=seed_cap,
                solver_time_limit_seconds=optimization.solver_time_limit_seconds * 0.1,
            ),
            segment_lengths=(1,) * len(horizon.gameweeks),
            transfer=transfer,
            chips=chips,
            preferences=preferences,
        )
        seed_work = cast(float, seed.diagnostics["deterministic_time_used"])
        clock_stopped = seed.diagnostics["construction_wall_clock_stopped"] is True
    except SegmentConstructionError as error:
        seed_work = error.actual_work
        clock_stopped = error.clock_stopped
    if clock_stopped:
        raise SolverExecutionError("Sequential construction reached its wall-clock safety limit.")
    final_wall = optimization.solver_time_limit_seconds * 0.9
    if seed is None:
        # The hold probe has its own wall ceiling in the underlying solver.
        final_wall -= min(30.0, final_wall / 2)
    plan = optimize_transfer_plan(
        horizon,
        initial,
        replace(
            optimization,
            solver_deterministic_time_limit=final_cap if seed is not None else final_cap - 1,
            solver_time_limit_seconds=final_wall,
        ),
        transfer,
        chips=chips,
        preferences=preferences,
        linearization_level=2,
        incumbent_plan=seed,
        protect_incumbent=seed is not None,
        protect_hold=seed is None,
    )
    final_work = cast(float, plan.diagnostics["deterministic_time_used"])
    hold = plan.diagnostics.get("hold_protection")
    hold_work = float(hold.get("deterministic_time") or 0) if isinstance(hold, dict) else 0.0
    return replace(
        plan,
        diagnostics={
            **plan.diagnostics,
            "sequential_incumbent": {
                "version": GUARDED_PLANNER_VERSION,
                "seed_completed": seed is not None,
                "configured_total": budget,
                "seed_cap": seed_cap,
                "final_cap_including_hold": final_cap,
                "seed_work": seed_work,
                "final_work_including_hold": final_work + hold_work,
                "actual_total": seed_work + final_work + hold_work,
            },
        },
    )
