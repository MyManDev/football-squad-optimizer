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

from squadopt.contracts.preferences import DecisionPreferences
from squadopt.optimization import (
    OptimizationConfig,
    OptimizationResult,
    SolverExecutionError,
    SolverStatus,
    optimize_squad,
)
from squadopt.planning.lineup_utility import (
    expected_week_utility,
    improve_plan_lineups,
    rescore_expected_week,
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
from squadopt.planning.policy_seed import forecast_policy_seed

CHIP_STRATEGY_VERSION = "model_opportunity_reservation_v2"
CHIP_STRATEGY_LIMITS = (
    "Future chip value is an approximation from this capture's forecast opportunities, "
    "not a measured season-long advantage.",
    "The tail assumes stationary opportunities and values chips separately; "
    "future injuries, transfers and chip competition can change it.",
    "Wildcard and Free Hit tail opportunities use one-week rebuild gains; "
    "long-term Wildcard effects beyond the forecast are unmeasured.",
)
EXPECTED_CHIP_LIMIT = (
    "Chip and no-chip candidates use the same expected lineup score, including autosubs "
    "and vice-captain cover. Automatic chip plans do not yet branch on future news."
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
    preferences: DecisionPreferences | None = None,
    protect_hold: bool = False,
    expected_lineups: bool = False,
) -> TransferPlanResult:
    """Price remaining rights from the selected model, then optimize jointly.

    Requires proved reference plans: a solver gap must not become a chip opportunity.
    The final plan can be FEASIBLE, and retains its objective-scale proof gap.
    Existing fixed holding values are deliberately refused rather than stacked.
    Optional expected-lineup scoring compares the complete chip proposal and its
    no-chip control on the same autosub/captain basis, including dated reserves.
    These are nominal forecast paths; automatic chips do not yet branch on news.
    """
    if expected_lineups and "appearance_probability" not in horizon.table:
        raise ValueError("Expected chip scoring requires appearance probabilities.")
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
        reference if chips.available else optimization,
        transfer,
        linearization_level=linearization_level,
        preferences=preferences,
        protect_hold=protect_hold,
    )
    if chips.available and control.solver_status is not SolverStatus.OPTIMAL:
        raise SolverExecutionError("Chip opportunity reference must be proved optimal.")
    reference_status = control.solver_status.name
    if expected_lineups:
        control = improve_plan_lineups(control, optimization, transfer)
    samples: dict[str, list[float]] = {name: [] for name in chips.available}
    probe_statuses: list[str] = []
    for week in control.weeks:
        # These are the same forecast units as the allocation objective, including
        # a selected Top100 utility. They are never published as raw expected points.
        if "3xc" in samples:
            gain = float(week.captain["expected_points"])
            if expected_lineups:
                boosted = rescore_expected_week(replace(week, chip="3xc"))
                gain = expected_week_utility(boosted, transfer) - expected_week_utility(
                    week, transfer
                )
            samples["3xc"].append(max(0.0, gain))
        if "bboost" in samples:
            gain = (1 - optimization.bench_weight) * week.projected_bench_points
            if expected_lineups:
                boosted = rescore_expected_week(replace(week, chip="bboost"))
                gain = expected_week_utility(boosted, transfer) - expected_week_utility(
                    week, transfer
                )
            samples["bboost"].append(max(0.0, gain))
        if "wildcard" in samples or "freehit" in samples:
            table = horizon.table.loc[horizon.table.gameweek.eq(week.gameweek)].copy()
            table["price_tenths"] = table["buy_price_tenths"]
            # This probe starts after the control's transfers. A player bought or
            # bought again has a new acquisition lot; the original horizon sale
            # path no longer describes that holding's liquidation value.
            sale_prices = week.selected_squad.set_index("player_id").sell_price_tenths
            held_mask = table.player_id.isin(sale_prices.index)
            table.loc[held_mask, "sell_price_tenths"] = (
                table.loc[held_mask, "player_id"].map(sale_prices).astype("int64")
            )
            held = table.loc[table.player_id.isin(week.selected_squad.player_id)]
            # Probe in the post-control state; use conservative sell proceeds, not
            # the roster's full purchase price when it contains price gains.
            budget = week.bank_after_tenths + int(held.sell_price_tenths.sum())
            rebuilt: TransferPlanResult | OptimizationResult
            if expected_lineups or (preferences is not None and preferences.active):
                # A rebuild opportunity must obey the same human constraints as
                # the final plan. A one-week wildcard removes transfer costs while
                # retaining the captured bank and sale values.
                rebuilt = optimize_transfer_plan(
                    PlanningHorizon(table),
                    InitialSquadState(
                        tuple(week.selected_squad.player_id),
                        bank_tenths=week.bank_after_tenths,
                        free_transfers=week.free_transfers_for_next_gameweek,
                    ),
                    reference,
                    transfer,
                    chips=ChipAvailability(
                        available={"wildcard": frozenset({week.gameweek})},
                        forced={week.gameweek: "wildcard"},
                    ),
                    preferences=preferences,
                    linearization_level=linearization_level,
                )
            else:
                rebuilt = optimize_squad(table, replace(optimization, budget_tenths=budget))
            if rebuilt.solver_status is not SolverStatus.OPTIMAL or rebuilt.objective_value is None:
                raise SolverExecutionError("Chip rebuild reference must be proved optimal.")
            probe_statuses.append(rebuilt.solver_status.name)
            current = week.projected_score + optimization.bench_weight * week.projected_bench_points
            rebuilt_value = rebuilt.objective_value
            if expected_lineups:
                assert isinstance(rebuilt, TransferPlanResult)
                rebuilt = improve_plan_lineups(rebuilt, optimization, transfer)
                rebuilt_value = expected_week_utility(rebuilt.weeks[0], transfer)
                current = expected_week_utility(week, transfer) + (
                    week.paid_transfer_count * transfer.transfer_hit_cost_points
                )
            gain = max(0.0, rebuilt_value - current)
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
    plan = (
        optimize_transfer_plan(
            horizon,
            initial,
            optimization,
            transfer,
            chips=availability,
            linearization_level=linearization_level,
            preferences=preferences,
            protect_hold=protect_hold,
        )
        if chips.available
        else control
    )
    comparison: dict[str, object] = {}
    if expected_lineups and plan.has_solution:
        plan = improve_plan_lineups(plan, optimization, transfer)

        def utility(candidate: TransferPlanResult) -> float:
            return sum(
                transfer.horizon_discount_factor**i * expected_week_utility(week, transfer)
                for i, week in enumerate(candidate.weeks)
            ) + float(str(candidate.diagnostics.get("terminal_chip_holding_value", 0)))

        menu = [("chip_proposal", plan)]
        if chips.available and not any(week in horizon.gameweeks for week in chips.forced):
            # The no-chip control must receive the same dated unused-right value.
            # Only rights change; forecast_policy_seed independently verifies that
            # all its existing resource decisions and its chip schedule remain legal.
            retained = forecast_policy_seed(
                control,
                horizon,
                horizon,
                optimization,
                transfer,
                target_chips=availability,
            )
            menu.insert(0, ("no_chip_control", retained))
        chosen = max(range(len(menu)), key=lambda i: (utility(menu[i][1]), -i))
        comparison = {
            "basis": "expected_lineup_selection_utility_with_chip_reserve",
            "chosen": menu[chosen][0],
            "candidates": [{"proposal": label, "utility": utility(p)} for label, p in menu],
            "news_recourse": False,
        }
        # Preserve the completed final search diagnostics even when its complete
        # no-chip control wins. Its old surrogate optimum is not the common score.
        plan = replace(
            menu[chosen][1],
            diagnostics={
                **plan.diagnostics,
                **menu[chosen][1].diagnostics,
                "proof_scope": "bounded_chip_menu_with_expected_lineup_selection",
                "solver_status_name": "FEASIBLE",
                "best_objective_bound": None,
                "absolute_optimality_gap": None,
                "relative_optimality_gap": None,
            },
            solver_status=SolverStatus.FEASIBLE,
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
                "reference_solver_status": reference_status,
                "rebuild_solver_statuses": probe_statuses,
                "limits": [
                    *CHIP_STRATEGY_LIMITS,
                    *([EXPECTED_CHIP_LIMIT] if expected_lineups else []),
                ],
                **({"expected_lineup_comparison": comparison} if expected_lineups else {}),
            },
        },
    )
