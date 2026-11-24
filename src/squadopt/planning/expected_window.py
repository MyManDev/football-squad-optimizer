"""Retained original proposals and one optional swap, on common expected utility."""

from dataclasses import replace
from math import floor, ulp
from time import perf_counter
from typing import Any, cast

from squadopt.contracts.preferences import DecisionPreferences
from squadopt.optimization import (
    OptimizationConfig,
    SolverExecutionError,
    SolverStatus,
    wall_clock_stopped_the_search,
)
from squadopt.optimization.work_budget import WorkBudgetExhausted, current_work_budget
from squadopt.planning.expected_packages import pick_package
from squadopt.planning.expected_swap import WORK_TOLERANCE, checked_work, propose_expected_swap
from squadopt.planning.guarded import GUARDED_PLANNER_VERSION, optimize_guarded_window
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


def _certified_phase(
    plan: TransferPlanResult,
    record: dict[str, Any],
    cap: float,
    actual: float,
) -> bool:
    protection = plan.diagnostics.get("incumbent_protection")
    hint = plan.diagnostics.get("incumbent_hint")
    hold = plan.diagnostics.get("hold_protection")
    has_witness = (
        isinstance(protection, dict)
        and protection.get("version") == "certified_fallback_v1"
        and protection.get("claimed_objective_used") is False
        and isinstance(hint, dict)
        and hint.get("version") == "certified_decisions_v1"
        and hint.get("claimed_objective_used") is False
        and record.get("seed_completed") is True
    ) or (
        isinstance(hold, dict)
        and hold.get("version") == "feasible_hold_v1"
        and hold.get("status") in {"OPTIMAL", "FEASIBLE"}
        and hold.get("objective_value") is not None
    )
    return (
        has_witness
        and record.get("version") == GUARDED_PLANNER_VERSION
        and record.get("configured_total") == cap
        and abs(
            checked_work(record.get("seed_work"), actual)
            + checked_work(record.get("final_work_including_hold"), actual)
            - actual
        )
        <= ulp(actual)
    )


def _stopped_work(
    plan: TransferPlanResult,
    horizon: PlanningHorizon,
    used: float,
    limit: float,
    *,
    verified: bool,
) -> dict[str, float]:
    """Retain a complete witness only within the window and job accounting checks."""
    if (
        not verified
        or not plan.has_solution
        or plan.horizon_fingerprint != horizon.horizon_fingerprint
        or tuple(week.gameweek for week in plan.weeks) != horizon.gameweeks
    ):
        raise ValueError("Invalid deterministic-work accounting for expected windows.")
    receipt = {"actual_total": checked_work(used, limit)}
    shared = current_work_budget()
    if shared is not None:
        receipt.update(
            shared_used=checked_work(
                shared.cp_used + shared.native_reserved + shared.unconfirmed, shared.limit
            ),
            shared_limit=shared.limit,
        )
    return receipt


def _retained_expected_window(
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
    if preferences is not None and preferences.net_points_priority:
        raise ValueError("Net points comparisons require the scoring-lineup objective.")
    started = perf_counter()
    budget = optimization.solver_deterministic_time_limit
    if budget is None or budget < 5:
        raise ValueError("Expected windows require an explicit budget of at least five.")
    menu = []
    originals = []
    ledger: list[dict[str, Any]] = []
    remaining = budget
    stop_receipt: dict[str, float] = {}
    for label, fraction, bench_weight in (
        ("legacy_proposal", 0.4, optimization.bench_weight),
        ("zero_bonus_proposal", 0.6, 0.0),
    ):
        phase_cap = min(budget * fraction, remaining)
        settings = replace(
            optimization,
            bench_weight=bench_weight,
            solver_deterministic_time_limit=phase_cap,
            solver_time_limit_seconds=optimization.solver_time_limit_seconds * fraction,
        )
        plan = optimize_guarded_window(
            horizon,
            initial,
            settings,
            transfer,
            chips=chips,
            preferences=preferences,
            limit_remaining_work=True,
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
        actual = checked_work(record["actual_total"], remaining)
        if actual > phase_cap + WORK_TOLERANCE:
            # A completed CP call may cross its stopping boundary. Charge the
            # full receipt and stop, but only with a certified complete result
            # and within the window's unchanged aggregate accounting check.
            stop_receipt = _stopped_work(
                plan,
                horizon,
                sum(float(row["actual"]) for row in ledger) + actual,
                budget,
                verified=_certified_phase(plan, record, phase_cap, actual),
            )
        remaining -= actual
        ledger.append(
            {
                "phase": label,
                "cap": phase_cap,
                "actual": actual,
                "status": plan.solver_status.name,
            }
        )
        originals.append(plan)
        if not plan.has_solution:
            continue
        scored = improve_plan_lineups(plan, settings, transfer, preferences=preferences)
        ledger[-1]["lineup_search"] = scored.diagnostics["lineup_search"]
        menu.append((label, scored))
        if stop_receipt:
            break
    original_actual = checked_work(sum(float(r["actual"]) for r in ledger), budget)
    review: dict[str, Any] = {
        "version": "expected_lineup_window_v2",
        "status": "no_solution",
        "configured_total": budget,
        "actual_total": original_actual,
        **stop_receipt,
        "ledger": ledger,
        "selection_basis": "expected_lineup_selection_utility",
        "selection_policy": expected_selection_policy(transfer, chips),
        "chosen": None,
        "gain_vs_retained_baseline": None,
        "baseline_completed": False,
        "candidates": [],
        "optional_swap": {
            "status": "skipped",
            "reason": "original_phase_work_exhausted"
            if stop_receipt
            else "original_routes_incomplete",
        },
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
    complete = (
        not stop_receipt
        and len(menu) == 2
        and all(
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
        released_after_original_phases=0.0 if stop_receipt else max(0.0, budget - original_actual),
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


def package_metrics(plan: TransferPlanResult, transfer: TransferPlanningConfig) -> dict[str, float]:
    """The three separately disclosed metrics, without realized outcomes."""
    return {
        "raw_xi_net_points": sum(w.projected_score - w.transfer_hit_points for w in plan.weeks),
        "expected_lineup_net_points": sum(
            float(str(w.lineup_expectation["expected_net_points"]))
            for w in plan.weeks
            if w.lineup_expectation is not None
        ),
        "selection_utility": sum(
            transfer.horizon_discount_factor**i * expected_week_utility(w, transfer)
            for i, w in enumerate(plan.weeks)
        )
        + float(str(plan.diagnostics.get("terminal_banked_transfer_value", 0)))
        + float(str(plan.diagnostics.get("terminal_chip_holding_value", 0))),
    }


def optimize_expected_window(
    horizon: PlanningHorizon,
    initial: InitialSquadState,
    optimization: OptimizationConfig,
    transfer: TransferPlanningConfig,
    *,
    chips: ChipAvailability | None = None,
    preferences: DecisionPreferences | None = None,
) -> TransferPlanResult:
    """Retain today's entire result before spending unused work on a package."""
    if not transfer.transfer_packages:
        return _retained_expected_window(
            horizon, initial, optimization, transfer, chips=chips, preferences=preferences
        )
    started = perf_counter()
    # The old optional single is part of the incumbent, including its seed identity.
    legacy = replace(transfer, transfer_packages=False, package_gate=False)
    baseline = _retained_expected_window(
        horizon, initial, optimization, legacy, chips=chips, preferences=preferences
    )
    return extend_expected_packages(
        horizon,
        initial,
        optimization,
        transfer,
        baseline,
        elapsed_seconds=perf_counter() - started,
        chips=chips,
        preferences=preferences,
    )


def extend_expected_packages(
    horizon: PlanningHorizon,
    initial: InitialSquadState,
    optimization: OptimizationConfig,
    transfer: TransferPlanningConfig,
    baseline: TransferPlanResult,
    *,
    elapsed_seconds: float,
    chips: ChipAvailability | None = None,
    preferences: DecisionPreferences | None = None,
) -> TransferPlanResult:
    """Continue a retained prefix without resetting any elapsed or charged work."""
    if (
        not transfer.transfer_packages
        or baseline.horizon_fingerprint != horizon.horizon_fingerprint
    ):
        raise ValueError("A package continuation requires its own retained horizon.")
    if not 0 <= elapsed_seconds < float("inf"):
        raise ValueError("A package continuation requires finite elapsed work.")
    started = perf_counter() - elapsed_seconds
    legacy = replace(transfer, transfer_packages=False, package_gate=False)
    review = cast(dict[str, Any], baseline.diagnostics["expected_lineup_window"])
    record: dict[str, Any] = {
        "version": "transfer_packages_v1",
        "status": "skipped",
        "reason": None,
        "gate_open": transfer.package_gate,
        "accepted": False,
        "configuration_fingerprint": transfer.configuration_fingerprint,
        "baseline_metrics": None,
        "proposal_metrics": None,
        "accepted_metrics": None,
    }

    def retained(reason: str) -> TransferPlanResult:
        record.update(reason=reason, wall_seconds=perf_counter() - started)
        retained_review = review
        if "actual_total" in record:
            retained_review = {
                **review,
                "actual_total": record["actual_total"],
                "lineup_evaluations": record.get(
                    "lineup_evaluations", review["lineup_evaluations"]
                ),
                "lineup_states": record.get("lineup_states", review.get("lineup_states")),
                "wall_seconds": record["wall_seconds"],
                "gross_sequential_issued_cap": float(review.get("gross_sequential_issued_cap", 0))
                + float(record.get("phase", {}).get("cap", 0)),
                "ledger": [*review["ledger"], *([record["phase"]] if "phase" in record else [])],
            }
        return replace(
            baseline,
            diagnostics={
                **baseline.diagnostics,
                "expected_lineup_window": retained_review,
                "transfer_packages_v1": record,
            },
        )

    if not baseline.has_solution or tuple(w.gameweek for w in baseline.weeks) != horizon.gameweeks:
        return retained("no_retained_full_path")
    metrics = package_metrics(baseline, transfer)
    record.update(baseline_metrics=metrics, accepted_metrics=metrics)
    original_stop = review["optional_swap"].get("reason")
    if original_stop == "original_phase_work_exhausted":
        return retained(original_stop)
    old_gate = original_stop != "original_routes_incomplete"
    record["original_gate_satisfied"] = old_gate
    if not old_gate and not transfer.package_gate:
        return retained("original_routes_incomplete")
    if preferences is not None and any(w.week == 1 for w in preferences.frozen_weeks):
        return retained("fixed_first_week")
    budget = float(review["configured_total"])
    used = checked_work(review["actual_total"], budget)
    evaluations = int(review["lineup_evaluations"])
    evaluation_cap = int(review["lineup_evaluation_cap"])
    remaining_evaluations = min(128, (evaluation_cap - evaluations - 1) // len(horizon.gameweeks))
    shared = current_work_budget()
    if remaining_evaluations <= 0 or budget - used <= 1 or (shared and shared.remaining <= 1):
        return retained("no_remaining_budget")
    cp_before = shared.cp_used if shared else 0.0
    wall_slack = optimization.solver_time_limit_seconds - (perf_counter() - started)
    if shared is not None:
        # Leave the full phase CP cap, one certificate/stop unit, and the native
        # reservation available together before starting any optional work.
        native_units = floor(max(0.0, shared.remaining - (budget - used) - 1.0))
        record["shared_native_units_cap"] = native_units
        if native_units < 1:
            return retained("no_remaining_native_and_cp_allocation")
        wall_slack = min(wall_slack, 2 * 30.0 * native_units)
    try:
        proposal, phase = propose_expected_swap(
            horizon,
            initial,
            optimization,
            legacy,
            baseline.weeks[0],
            (frozenset(baseline.weeks[0].selected_squad.player_id),),
            deterministic_slack=budget - used,
            wall_slack=wall_slack,
            chips=chips,
            preferences=preferences,
            package_picker=pick_package,
            max_lineup_evaluations=remaining_evaluations,
            deterministic_reserve=1.0,
        )
    except WorkBudgetExhausted:
        if shared is None:
            raise
        # A final CP call can stop beyond its grant. Keep its full charge and the
        # verified incumbent when admission refuses the next optional solve.
        extra_cp = checked_work(shared.cp_used - cp_before, budget - used)
        record.update(
            additional_cp_work=extra_cp,
            **_stopped_work(baseline, horizon, used + extra_cp, budget, verified=True),
        )
        return retained("shared_work_exhausted")
    actual = checked_work(used + float(phase["actual"]), budget)
    lineup = phase.get("lineup_search")
    extra_evaluations = int(lineup["evaluations"]) if lineup else 0
    total_evaluations = evaluations + extra_evaluations + int(phase["hold_score_calls"])
    if total_evaluations > evaluation_cap:
        raise ValueError("Package lineup work exceeded the original window cap.")
    record.update(
        phase=phase,
        actual_total=actual,
        configured_total=budget,
        lineup_evaluations=total_evaluations,
        lineup_evaluation_cap=evaluation_cap,
        lineup_states=int(review.get("lineup_states", 0))
        + int(phase.get("hold_score_states", 0))
        + (sum(int(w["states_evaluated"]) for w in lineup["weeks"]) if lineup else 0),
        wall_seconds=perf_counter() - started,
    )
    if proposal is None:
        return retained(str(phase["reason"]))
    proposed = package_metrics(proposal, transfer)
    record["proposal_metrics"] = proposed
    # Preserve every reported component; a proxy win alone never changes a plan.
    accepted = proposed["selection_utility"] > metrics["selection_utility"] and all(
        proposed[key] >= value for key, value in metrics.items()
    )
    record.update(
        status="compared",
        reason="accepted" if accepted else "retained_incumbent",
        accepted=accepted,
    )
    if not accepted:
        return retained("retained_incumbent")
    record["accepted_metrics"] = proposed
    combined = {
        **review,
        "actual_total": actual,
        "lineup_evaluations": total_evaluations,
        "lineup_states": record["lineup_states"],
        "wall_seconds": record["wall_seconds"],
        "gross_sequential_issued_cap": float(review.get("gross_sequential_issued_cap", 0))
        + float(phase["cap"]),
        "ledger": [*review["ledger"], phase],
        "chosen": "initial_transfer_package",
        "candidates": [
            *review["candidates"],
            {"proposal": "initial_transfer_package", "utility": proposed["selection_utility"]},
        ],
    }
    return replace(
        proposal,
        diagnostics={
            **proposal.diagnostics,
            "expected_lineup_window": combined,
            "transfer_packages_v1": record,
        },
    )
