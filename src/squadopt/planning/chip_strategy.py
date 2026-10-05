"""Bounded chip selection with an explicit jointly allocated future calendar."""

import math
from dataclasses import replace

from squadopt.contracts.preferences import DecisionPreferences
from squadopt.optimization import OptimizationConfig, SolverExecutionError, SolverStatus
from squadopt.planning.chip_tail import (
    ChipTailForecast,
    build_chip_tail_table,
    chip_tail_context_fingerprint,
)
from squadopt.planning.lineup_utility import expected_week_utility, improve_plan_lineups
from squadopt.planning.models import (
    ChipAvailability,
    InitialSquadState,
    PlanningHorizon,
    TransferPlanningConfig,
    TransferPlanResult,
)
from squadopt.planning.optimizer import PLAN_DETERMINISTIC_TIME_LIMIT, optimize_transfer_plan

CHIP_STRATEGY_VERSION = "dated_joint_opportunity_v3"
CHIP_STRATEGY_LIMITS = (
    "Future chip opportunities are explicitly dated input values, not a calibrated season policy.",
    "Future rights compete for the same dates; expiry, renewal and consecutive "
    "Free Hit restrictions apply.",
    "The declared tail does not simulate future transfers, news or long-term Wildcard effects.",
)
EXPECTED_CHIP_LIMIT = (
    "Chip and no-chip candidates use the same expected lineup score, including autosubs "
    "and vice-captain cover. Automatic chip plans do not yet branch on future news."
)


def optimize_chip_strategy(
    horizon: PlanningHorizon,
    initial: InitialSquadState,
    optimization: OptimizationConfig,
    transfer: TransferPlanningConfig,
    chips: ChipAvailability,
    *,
    linearization_level: int | None = None,
    preferences: DecisionPreferences | None = None,
    protect_hold: bool = False,
    expected_lineups: bool = False,
    tail_forecast: ChipTailForecast | None = None,
) -> TransferPlanResult:
    """Select within one total deterministic budget, without extrapolated reserves.

    Rights expiring within the window have zero tail. Any later legal date needs
    explicit forecast coverage; missing coverage refuses before starting a solve.
    Joint tail assignment is exact for these declared values, not a season-optimal
    policy. Expected-lineup mode compares two complete resource paths on the same
    nonlinear score; the CP objective proposes them and cannot certify that score.
    """
    if expected_lineups and "appearance_probability" not in horizon.table:
        raise ValueError("Expected chip scoring requires appearance probabilities.")
    if transfer.chip_holding_value_points or transfer.banked_transfer_value_points:
        raise ValueError("Chip strategy requires explicit dated tail values, not fixed reserves.")
    if any(
        p.holding_value_points is not None for n in chips.available for p in chips.windows_for(n)
    ):
        raise ValueError("Chip strategy inputs must contain unpriced rights.")
    if transfer.horizon_discount_factor != 1:
        raise ValueError("Explicit dated chip tail requires undiscounted selection utility.")
    tail = build_chip_tail_table(
        chips,
        horizon.gameweeks[-1],
        tail_forecast,
        context_fingerprint=chip_tail_context_fingerprint(
            horizon,
            initial,
            optimization,
            transfer,
            preferences,
            expected_lineups=expected_lineups,
        ),
    )
    total = optimization.solver_deterministic_time_limit or PLAN_DETERMINISTIC_TIME_LIMIT
    forced_current = any(gw in horizon.gameweeks for gw in chips.forced)
    compare_control = expected_lineups and bool(chips.available) and not forced_current
    phases = (
        [("no_chip_control", 0.4), ("chip_proposal", 0.6)]
        if compare_control
        else [("chip_proposal", 1.0)]
    )
    ledger = []
    candidates = []
    for label, share in phases:
        phase_budget = total * share
        protected = protect_hold and phase_budget > 1
        wall = optimization.solver_time_limit_seconds * share
        config = replace(
            optimization,
            solver_deterministic_time_limit=phase_budget - (1 if protected else 0),
            solver_time_limit_seconds=wall - (min(30, wall / 2) if protected else 0),
        )
        control = label == "no_chip_control"
        plan = optimize_transfer_plan(
            horizon,
            initial,
            config,
            transfer,
            chips=None if control else chips,
            chip_tail=None if control else tail,
            linearization_level=linearization_level,
            preferences=preferences,
            protect_hold=protected,
        )
        used = float(str(plan.diagnostics.get("deterministic_time_used", 0)))
        probe = plan.diagnostics.get("hold_protection")
        if isinstance(probe, dict):
            used += float(str(probe.get("deterministic_time", 0)))
        if not math.isfinite(used) or used > phase_budget + 1e-5:
            raise SolverExecutionError("Chip phase exceeded its shared deterministic budget.")
        ledger.append({"phase": label, "allocation": phase_budget, "actual": used})
        if not plan.has_solution:
            raise SolverExecutionError(
                "The bounded chip comparison did not complete every candidate."
            )
        if control:
            reserve = tail.value({})
            plan = replace(
                plan,
                objective_value=float(plan.objective_value or 0) + reserve,
                diagnostics={**plan.diagnostics, "terminal_chip_holding_value": reserve},
            )
        if expected_lineups:
            plan = improve_plan_lineups(plan, optimization, transfer)
        candidates.append((label, plan))

    def utility(plan: TransferPlanResult) -> float:
        if expected_lineups:
            return sum(expected_week_utility(w, transfer) for w in plan.weeks) + tail.value(
                dict(plan.chips_played)
            )
        return float(plan.objective_value or 0)

    chosen = max(range(len(candidates)), key=lambda i: (utility(candidates[i][1]), -i))
    plan = candidates[chosen][1]
    comparison = {
        "basis": "expected_lineup_selection_utility_with_dated_joint_tail",
        "chosen": candidates[chosen][0],
        "candidates": [{"proposal": label, "utility": utility(p)} for label, p in candidates],
        "news_recourse": False,
    }
    if expected_lineups:
        plan = replace(
            plan,
            solver_status=SolverStatus.FEASIBLE,
            diagnostics={
                **plan.diagnostics,
                "proof_scope": "bounded_chip_menu_with_expected_lineup_selection",
                "solver_status_name": "FEASIBLE",
                "best_objective_bound": None,
                "absolute_optimality_gap": None,
                "relative_optimality_gap": None,
            },
        )
    return replace(
        plan,
        diagnostics={
            **plan.diagnostics,
            "chip_strategy": {
                "version": CHIP_STRATEGY_VERSION,
                "experimental": True,
                "basis": "selection_utility",
                "reservations": [],
                "joint_tail": {
                    "source_fingerprint": tail.source_fingerprint,
                    "value": tail.value(dict(plan.chips_played)),
                    "right_count": len(tail.rights),
                    "state_count": len(tail.values),
                    "opportunity_count": 0
                    if tail_forecast is None
                    else len(tail_forecast.opportunities),
                },
                "configured_total": total,
                "actual_total": sum(float(str(row["actual"])) for row in ledger),
                "ledger": ledger,
                "limits": [
                    *CHIP_STRATEGY_LIMITS,
                    *([EXPECTED_CHIP_LIMIT] if expected_lineups else []),
                ],
                **({"expected_lineup_comparison": comparison} if expected_lineups else {}),
            },
        },
    )
