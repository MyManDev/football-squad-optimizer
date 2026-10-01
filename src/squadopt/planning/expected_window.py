"""Two bounded proposal routes ranked on the same expected lineup selection utility."""

from dataclasses import replace
from typing import Any, cast

from squadopt.contracts.preferences import DecisionPreferences
from squadopt.optimization import (
    OptimizationConfig,
    SolverExecutionError,
    wall_clock_stopped_the_search,
)
from squadopt.planning.guarded import optimize_guarded_window
from squadopt.planning.lineup_utility import (
    expected_selection_policy,
    expected_week_utility,
    improve_plan_lineups,
)
from squadopt.planning.models import (
    ChipAvailability,
    InitialSquadState,
    PlanningHorizon,
    TransferPlanningConfig,
    TransferPlanResult,
)


def optimize_expected_window(
    horizon: PlanningHorizon,
    initial: InitialSquadState,
    optimization: OptimizationConfig,
    transfer: TransferPlanningConfig,
    *,
    chips: ChipAvailability | None = None,
    preferences: DecisionPreferences | None = None,
) -> TransferPlanResult:
    """40% legacy proposals, 60% zero bench bonus, one common final objective.

    Neither discarded bench utility nor a change of point scale can masquerade as
    improvement. Every week still selects its own XI, so useful rotation remains.
    """
    budget = optimization.solver_deterministic_time_limit
    if budget is None or budget < 5:
        raise ValueError("Expected windows require an explicit budget of at least five.")
    menu = []
    ledger: list[dict[str, Any]] = []
    for label, fraction, bench_weight in (
        ("legacy_proposal", 0.4, optimization.bench_weight),
        ("zero_bonus_proposal", 0.6, 0.0),
    ):
        settings = replace(
            optimization,
            bench_weight=bench_weight,
            solver_deterministic_time_limit=budget * fraction,
            solver_time_limit_seconds=optimization.solver_time_limit_seconds * fraction,
        )
        plan = optimize_guarded_window(
            horizon, initial, settings, transfer, chips=chips, preferences=preferences
        )
        if wall_clock_stopped_the_search(plan.solver_status, plan.diagnostics):
            raise SolverExecutionError(
                "Expected lineup proposals reached their wall-clock safety limit."
            )
        hold = plan.diagnostics.get("hold_protection")
        if isinstance(hold, dict):
            probe_used = float(hold.get("deterministic_time") or 0)
            probe_cap = float(hold["deterministic_time_limit"])
            if hold.get("status") in {"FEASIBLE", "UNKNOWN"} and probe_used < probe_cap - 1e-9:
                raise SolverExecutionError(
                    "Expected lineup hold probe reached its wall-clock safety limit."
                )
        record = cast(dict[str, Any], plan.diagnostics["sequential_incumbent"])
        ledger.append(
            {
                "phase": label,
                "cap": budget * fraction,
                "actual": record["actual_total"],
                "status": plan.solver_status.name,
            }
        )
        if not plan.has_solution:
            continue
        scored = improve_plan_lineups(plan, settings, transfer)
        ledger[-1]["lineup_search"] = scored.diagnostics["lineup_search"]
        menu.append((label, scored))
    review: dict[str, Any] = {
        "version": "expected_lineup_window_v1",
        "status": "no_solution",
        "configured_total": budget,
        "actual_total": sum(float(r["actual"]) for r in ledger),
        "ledger": ledger,
        "selection_basis": "expected_lineup_selection_utility",
        "selection_policy": expected_selection_policy(transfer, chips),
        "chosen": None,
        "gain_vs_retained_baseline": None,
        "baseline_completed": False,
        "candidates": [],
    }
    if not menu:
        return replace(plan, diagnostics={**plan.diagnostics, "expected_lineup_window": review})

    def utility(candidate: TransferPlanResult) -> float:
        return (
            sum(
                transfer.horizon_discount_factor**i * expected_week_utility(w, transfer)
                for i, w in enumerate(candidate.weeks)
            )
            + float(str(candidate.diagnostics.get("terminal_banked_transfer_value", 0)))
            + float(str(candidate.diagnostics.get("terminal_chip_holding_value", 0)))
        )

    chosen = max(range(len(menu)), key=lambda i: (utility(menu[i][1]), -i))
    result = menu[chosen][1]
    review.update(
        status="compared" if len(menu) > 1 else "single_proposal",
        chosen=menu[chosen][0],
        gain_vs_retained_baseline=(
            utility(result) - utility(menu[0][1]) if menu[0][0] == "legacy_proposal" else None
        ),
        baseline_completed=menu[0][0] == "legacy_proposal",
        candidates=[{"proposal": label, "utility": utility(p)} for label, p in menu],
    )
    return replace(
        result,
        diagnostics={
            **result.diagnostics,
            "expected_lineup_window": review,
        },
    )
