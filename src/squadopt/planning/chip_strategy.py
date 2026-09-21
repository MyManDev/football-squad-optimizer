"""Receding-horizon chip allocation with a model-derived continuation approximation.

The continuation is *not* a fitted season MDP. For each chip it treats the current
horizon's marginal opportunity samples as an empirical stationary distribution:
V(0)=0; V(n)=mean(max(sample,V(n-1))). Within the horizon the ordinary joint
transfer model prices squad changes, collisions, expiry and Free Hit restoration.
Independent tail values omit future competition between chips and future injuries.
"""

import math
from collections.abc import Sequence
from dataclasses import replace

from squadopt.optimization import (
    OptimizationConfig,
    SolverExecutionError,
    SolverStatus,
    optimize_squad,
)
from squadopt.planning.models import (
    ChipAvailability,
    ChipUseWindow,
    InitialSquadState,
    PlanningHorizon,
    TransferPlanningConfig,
    TransferPlanResult,
)
from squadopt.planning.optimizer import optimize_transfer_plan

CHIP_STRATEGY_VERSION = "model_opportunity_reservation_v1"
CHIP_STRATEGY_LIMITS = (
    "Future chip value is an approximation from this capture's forecast opportunities, "
    "not a measured season-long advantage.",
    "The tail assumes stationary opportunities and values chips separately; "
    "future injuries, transfers and chip competition can change it.",
    "Wildcard and Free Hit tail opportunities use one-week rebuild gains; "
    "long-term Wildcard effects beyond the forecast are unmeasured.",
)


def continuation_value(samples: Sequence[float], opportunities: int) -> float:
    """Expected optimal stopping value before observing the next opportunity.

    No realized outcomes, calendar from the future, parameter search or old-model
    calibration enters this calculation. One constant sample remains constant;
    expiry is exactly zero; more opportunities never decrease the option value.
    """
    if (
        isinstance(opportunities, bool)
        or not isinstance(opportunities, int)
        or not 0 <= opportunities <= 38
    ):
        raise ValueError("Remaining opportunities must be an integer from 0 to 38.")
    if not samples or any(isinstance(v, bool) or not math.isfinite(v) or v < 0 for v in samples):
        raise ValueError("Opportunity samples must be finite non-negative values.")
    value = 0.0
    for _ in range(opportunities):
        value = math.fsum(max(float(sample), value) for sample in samples) / len(samples)
    return value


def optimize_chip_strategy(
    horizon: PlanningHorizon,
    initial: InitialSquadState,
    optimization: OptimizationConfig,
    transfer: TransferPlanningConfig,
    chips: ChipAvailability,
    *,
    linearization_level: int | None = None,
) -> TransferPlanResult:
    """Price remaining rights from the selected model, then optimize jointly.

    Requires proved reference plans: a solver gap must not become a chip opportunity.
    The final plan can be FEASIBLE, and retains its objective-scale proof gap.
    Existing fixed holding values are deliberately refused rather than stacked.
    """
    if transfer.chip_holding_value_points or transfer.banked_transfer_value_points:
        raise ValueError("Chip strategy derives its own continuation values.")
    if any(
        p.holding_value_points is not None for n in chips.available for p in chips.windows_for(n)
    ):
        raise ValueError("Chip strategy inputs must contain unpriced rights.")
    # Reference plans must be proved, unlike the final feasible allocation. Give
    # this prerequisite a fixed threefold deterministic budget, never a multiplier
    # selected on points won. The same wall-clock safety ceiling remains in force.
    reference = replace(
        optimization,
        solver_deterministic_time_limit=(
            None
            if optimization.solver_deterministic_time_limit is None
            else 3 * optimization.solver_deterministic_time_limit
        ),
    )
    control = optimize_transfer_plan(
        horizon,
        initial,
        reference,
        transfer,
        linearization_level=linearization_level,
    )
    if control.solver_status is not SolverStatus.OPTIMAL:
        raise SolverExecutionError("Chip opportunity reference must be proved optimal.")
    samples: dict[str, list[float]] = {name: [] for name in chips.available}
    probe_statuses: list[str] = []
    for week in control.weeks:
        # These are the same forecast units as the allocation objective, including
        # a selected Top100 utility. They are never published as raw expected points.
        if "3xc" in samples:
            samples["3xc"].append(max(0.0, float(week.captain["expected_points"])))
        if "bboost" in samples:
            samples["bboost"].append(
                max(0.0, (1 - optimization.bench_weight) * week.projected_bench_points)
            )
        if "wildcard" in samples or "freehit" in samples:
            table = horizon.table.loc[horizon.table.gameweek.eq(week.gameweek)].copy()
            table["price_tenths"] = table["buy_price_tenths"]
            held = table.loc[table.player_id.isin(week.selected_squad.player_id)]
            # Probe in the post-control state; use conservative sell proceeds, not
            # the roster's full purchase price when it contains price gains.
            budget = week.bank_after_tenths + int(held.sell_price_tenths.sum())
            rebuilt = optimize_squad(table, replace(optimization, budget_tenths=budget))
            if rebuilt.solver_status is not SolverStatus.OPTIMAL or rebuilt.objective_value is None:
                raise SolverExecutionError("Chip rebuild reference must be proved optimal.")
            probe_statuses.append(rebuilt.solver_status.name)
            current = week.projected_score + optimization.bench_weight * week.projected_bench_points
            gain = max(0.0, rebuilt.objective_value - current)
            for name in ("wildcard", "freehit"):
                if name in samples:
                    samples[name].append(gain)
    end = horizon.gameweeks[-1]
    priced: dict[str, tuple[ChipUseWindow, ...]] = {}
    reservations: list[dict[str, object]] = []
    for name in chips.available:
        periods = []
        for period in chips.windows_for(name):
            remaining = sum(w > end for w in period.gameweeks)
            value = continuation_value(samples[name], remaining)
            periods.append(replace(period, holding_value_points=value))
            reservations.append(
                {
                    "chip": name,
                    "first_gameweek": min(period.gameweeks),
                    "last_gameweek": max(period.gameweeks),
                    "remaining_opportunities": remaining,
                    "holding_value": value,
                    "sample_min": min(samples[name]),
                    "sample_max": max(samples[name]),
                }
            )
        priced[name] = tuple(periods)
    availability = replace(chips, use_windows=priced)
    plan = optimize_transfer_plan(
        horizon,
        initial,
        optimization,
        transfer,
        chips=availability,
        linearization_level=linearization_level,
    )
    return replace(
        plan,
        diagnostics={
            **plan.diagnostics,
            "chip_strategy": {
                "version": CHIP_STRATEGY_VERSION,
                "experimental": True,
                "basis": "selection_utility",
                "reservations": reservations,
                "samples": samples,
                "reference_solver_status": control.solver_status.name,
                "rebuild_solver_statuses": probe_statuses,
                "limits": list(CHIP_STRATEGY_LIMITS),
            },
        },
    )
