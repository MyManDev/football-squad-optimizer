"""Retained original proposals and one optional swap, on common expected utility."""

from dataclasses import replace
from time import perf_counter
from typing import Any, cast

from squadopt.contracts.preferences import DecisionPreferences
from squadopt.optimization import (
    OptimizationConfig,
    SolverExecutionError,
    SolverStatus,
    wall_clock_stopped_the_search,
)
from squadopt.planning.expected_swap import checked_work, propose_expected_swap
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
    """Keep both 40/60 routes; one optional swap uses only their actual CP slack.

    Original lineup work remains 256 evaluations per week. The optional phase
    permits 128 more per week plus one template score, explicitly more work.
    This route does not alter the separate observed-information branch menu.
    """
    started = perf_counter()
    budget = optimization.solver_deterministic_time_limit
    if budget is None or budget < 5:
        raise ValueError("Expected windows require an explicit budget of at least five.")
    menu = []
    originals = []
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
                "actual": checked_work(record["actual_total"], budget * fraction),
                "status": plan.solver_status.name,
            }
        )
        originals.append(plan)
        if not plan.has_solution:
            continue
        scored = improve_plan_lineups(plan, settings, transfer)
        ledger[-1]["lineup_search"] = scored.diagnostics["lineup_search"]
        menu.append((label, scored))
    original_actual = checked_work(sum(float(r["actual"]) for r in ledger), budget)
    review: dict[str, Any] = {
        "version": "expected_lineup_window_v2",
        "status": "no_solution",
        "configured_total": budget,
        "actual_total": original_actual,
        "ledger": ledger,
        "selection_basis": "expected_lineup_selection_utility",
        "selection_policy": expected_selection_policy(transfer, chips),
        "chosen": None,
        "gain_vs_retained_baseline": None,
        "baseline_completed": False,
        "candidates": [],
        "optional_swap": {"status": "skipped", "reason": "original_routes_incomplete"},
        "lineup_evaluation_cap": 384 * len(horizon.gameweeks) + 1,
        "previous_lineup_evaluation_cap": 256 * len(horizon.gameweeks),
        "equal_total_lineup_work_claim": False,
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

    # Raw CP completion is checked before role scoring deliberately marks a plan
    # FEASIBLE: neither the surrogate bound nor a seed is a lineup-optimality proof.
    complete = len(menu) == 2 and all(
        p.solver_status is SolverStatus.OPTIMAL
        and tuple(w.gameweek for w in p.weeks) == horizon.gameweeks
        and cast(dict[str, Any], p.diagnostics["sequential_incumbent"]).get("seed_completed")
        is True
        and not (
            p.diagnostics.get("tiebreak_attempted") is True
            and p.diagnostics.get("tiebreak_completed") is not True
        )
        for p in originals
    )
    if complete:
        template_index = max(range(2), key=lambda i: (utility(menu[i][1]), -i))
        optional, swap = propose_expected_swap(
            horizon,
            initial,
            optimization,
            transfer,
            menu[template_index][1].weeks[0],
            tuple(frozenset(p.weeks[0].selected_squad.player_id) for _, p in menu),
            deterministic_slack=max(0.0, budget - original_actual),
            wall_slack=optimization.solver_time_limit_seconds - (perf_counter() - started),
            chips=chips,
            preferences=preferences,
        )
        review["optional_swap"] = swap
        if swap["solver_calls"]:
            ledger.append(swap)
        if optional is not None:
            menu.append(("initial_single_swap", optional))
    actual = checked_work(sum(float(r["actual"]) for r in ledger), budget)
    swap = review["optional_swap"]
    lineup_records = [r["lineup_search"] for r in ledger if r.get("lineup_search") is not None]
    review.update(
        actual_total=actual,
        released_after_original_phases=max(0.0, budget - original_actual),
        reused_cap=swap.get("cap", 0.0),
        gross_sequential_issued_cap=sum(float(r["cap"]) for r in ledger),
        lineup_evaluations=sum(int(r["evaluations"]) for r in lineup_records)
        + int(swap.get("hold_score_calls", 0)),
        lineup_states=sum(int(w["states_evaluated"]) for r in lineup_records for w in r["weeks"])
        + int(swap.get("hold_score_states", 0)),
        wall_seconds=perf_counter() - started,
    )
    if review["lineup_evaluations"] > review["lineup_evaluation_cap"]:
        raise ValueError("Expected-window exact lineup work exceeded its disclosed cap.")
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
