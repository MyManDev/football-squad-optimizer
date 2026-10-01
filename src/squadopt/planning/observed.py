"""Bounded observation-aware window selection with a complete nominal fallback.

The objective retains the caller's bench and hit policy. Information branches are
posterior forecasts, never realized points. Every first action faces every branch.
"""

from __future__ import annotations

import math
from dataclasses import replace
from typing import Any

import pandas as pd

from squadopt.contracts.preferences import DecisionPreferences
from squadopt.optimization import (
    OptimizationConfig,
    SolverExecutionError,
    SolverStatus,
    wall_clock_stopped_the_search,
)
from squadopt.planning.guarded import optimize_guarded_window
from squadopt.planning.models import (
    ChipAvailability,
    InitialSquadState,
    PlanningHorizon,
    PlanningWeekResult,
    TransferPlanningConfig,
    TransferPlanResult,
)
from squadopt.planning.optimizer import optimize_transfer_plan
from squadopt.planning.recourse import ObservationNode, _continuation_horizon
from squadopt.planning.recourse_chips import net_week_points, remaining_chips, restrict_first_chip

OBSERVED_WINDOW_VERSION = "bounded_observed_window_v1"
OBSERVED_WINDOW_LIMIT = (
    "This experimental plan compares today's actions under two possible updates before "
    "the next deadline. Later transfers are conditional plans, not certain moves. "
    "The information timing is an assumption, not a measured recovery forecast."
)
OBSERVED_FALLBACK_LIMIT = (
    "The information comparison could not be completed within its shared search budget; "
    "the complete baseline plan is retained."
)


def validate_observations(baseline: PlanningHorizon, nodes: tuple[ObservationNode, ...]) -> None:
    """A narrow two-node contract; information may change forecasts, not assets."""
    if len(baseline.gameweeks) not in (3, 5) or len(nodes) != 2:
        raise ValueError("Observed windows require three/five weeks and two information nodes.")
    if len({n.observation_id for n in nodes}) != len(nodes) or any(
        not isinstance(n.observation_id, str) or not n.observation_id.strip() for n in nodes
    ):
        raise ValueError("Observation IDs must be unique nonempty strings.")
    if any(
        isinstance(n.probability, bool) or not math.isfinite(n.probability) or n.probability <= 0
        for n in nodes
    ) or not math.isclose(sum(n.probability for n in nodes), 1, abs_tol=1e-10, rel_tol=0):
        raise ValueError("Information probabilities must be positive and sum to one.")
    future = baseline.table.loc[baseline.table.gameweek.ne(baseline.gameweeks[0])]
    key = ["gameweek", "player_id"]
    expected = future.set_index(key).sort_index()
    for node in nodes:
        actual = node.horizon.validated_copy().table.set_index(key).sort_index()
        if not actual.index.equals(expected.index):
            raise ValueError("Observations must cover the same future weeks and players.")
        for column in ("position", "team_id", "buy_price_tenths", "sell_price_tenths"):
            if not actual[column].equals(expected[column]):
                raise ValueError(
                    "Information must not change player identity or transaction prices."
                )
    if "appearance_probability" in expected:
        if any("appearance_probability" not in n.horizon.table for n in nodes):
            raise ValueError("Information branches must retain appearance probabilities.")
        appearance_mean = sum(
            n.probability * n.horizon.table.set_index(key).sort_index().appearance_probability
            for n in nodes
        )
        if not ((appearance_mean - expected.appearance_probability).abs() <= 1e-8).all():
            raise ValueError("Information branches must preserve baseline appearance expectation.")
    # The product compares information resolution, not an undisclosed forecast upgrade.
    mean = sum(
        n.probability * n.horizon.table.set_index(key).sort_index().expected_points for n in nodes
    )
    if not ((mean - expected.expected_points).abs() <= 1e-8).all():
        raise ValueError("Information branches must preserve the baseline point expectation.")


def _utility(
    week: PlanningWeekResult, optimization: OptimizationConfig, transfer: TransferPlanningConfig
) -> float:
    bench = 1.0 if week.chip == "bboost" else optimization.bench_weight
    return (
        week.projected_score
        + bench * week.projected_bench_points
        - week.paid_transfer_count * transfer.transfer_hit_cost_points
    )


def optimize_observed_window(
    horizon: PlanningHorizon,
    initial: InitialSquadState,
    nodes: tuple[ObservationNode, ...],
    optimization: OptimizationConfig,
    transfer: TransferPlanningConfig,
    *,
    chips: ChipAvailability | None = None,
    preferences: DecisionPreferences | None = None,
) -> TransferPlanResult:
    """40% baseline, 20% proposals, 30% continuations, 10% nominal reconciliation.

    At most three distinct first actions and two information branches are compared.
    Incomplete comparisons never select from the surviving subset. The baseline
    remains a feasible fallback, not a guarantee of better realized FPL performance.
    Fixed allocations include every solver invocation; no hidden hold probes or retries.
    """
    horizon = horizon.validated_copy()
    validate_observations(horizon, nodes)
    budget = optimization.solver_deterministic_time_limit
    if budget is None or budget < 5:
        raise ValueError("Observed windows need an explicit total budget of at least five.")
    rights = chips or ChipAvailability()
    if (
        transfer.horizon_discount_factor != 1
        or transfer.banked_transfer_value_points != 0
        or transfer.chip_holding_value_points
        or any(
            p.holding_value_points not in (None, 0)
            for name in rights.available
            for p in rights.windows_for(name)
        )
    ):
        raise ValueError("Observed windows require zero terminal values and no discount.")
    ledger: list[dict[str, object]] = []

    def config(fraction: float) -> OptimizationConfig:
        return replace(
            optimization,
            solver_deterministic_time_limit=budget * fraction,
            solver_time_limit_seconds=optimization.solver_time_limit_seconds * fraction,
        )

    def record(label: str, fraction: float, plan: TransferPlanResult) -> None:
        if wall_clock_stopped_the_search(plan.solver_status, plan.diagnostics):
            raise SolverExecutionError(
                "Information comparison reached its wall-clock safety limit."
            )
        construction = plan.diagnostics.get("sequential_incumbent")
        used = (
            construction["actual_total"]
            if isinstance(construction, dict)
            else plan.diagnostics.get("deterministic_time_used", 0)
        )
        ledger.append(
            {
                "phase": label,
                "cap": budget * fraction,
                "actual": float(str(used)),
                "status": plan.solver_status.name,
            }
        )

    baseline = optimize_guarded_window(
        horizon, initial, config(0.4), transfer, chips=rights, preferences=preferences
    )
    record("baseline", 0.4, baseline)
    if not baseline.has_solution:
        return baseline
    menu = [baseline]
    first = horizon.gameweeks[0]

    def finish(plan: TransferPlanResult, status: str, **details: object) -> TransferPlanResult:
        return replace(
            plan,
            diagnostics={
                **plan.diagnostics,
                "observed_window": {
                    "version": OBSERVED_WINDOW_VERSION,
                    "status": status,
                    "configured_total": budget,
                    "allocated_total": sum(float(str(x["cap"])) for x in ledger),
                    "actual_total": sum(float(str(x["actual"])) for x in ledger),
                    "ledger": ledger,
                    **details,
                },
            },
        )

    def add(plan: TransferPlanResult) -> None:
        if plan.has_solution:
            week = plan.weeks[0]
            key = (frozenset(week.selected_squad.player_id), week.chip)
            if all(
                key != (frozenset(p.weeks[0].selected_squad.player_id), p.weeks[0].chip)
                for p in menu
            ):
                menu.append(plan)

    held = optimize_transfer_plan(
        horizon,
        initial,
        config(0.1),
        transfer,
        chips=restrict_first_chip(rights, first, rights.forced.get(first)),
        fixed_week_squads={first: tuple(initial.squad_player_ids)},
        preferences=preferences,
        linearization_level=2,
    )
    record("hold_proposal", 0.1, held)
    if held.solver_status is SolverStatus.UNKNOWN:
        return finish(baseline, "incomplete_hold")
    add(held)
    today = horizon.table.loc[horizon.table.gameweek.eq(first)]
    proposal = optimize_transfer_plan(
        PlanningHorizon(pd.concat([today, nodes[0].horizon.table], ignore_index=True)),
        initial,
        config(0.1),
        transfer,
        chips=rights,
        preferences=preferences,
        linearization_level=2,
    )
    record("information_proposal", 0.1, proposal)
    if not proposal.has_solution:
        return finish(baseline, "incomplete_proposal")
    add(proposal)
    share = 0.3 / (len(menu) * len(nodes))
    baseline_points = horizon.table.set_index(["gameweek", "player_id"]).expected_points

    def point_terms(weeks: tuple[PlanningWeekResult, ...]) -> list[dict[str, object]]:
        terms: list[dict[str, object]] = []
        for week in weeks:
            frame = week.selected_squad if week.chip == "bboost" else week.starting_xi
            for row in frame.itertuples():
                multiplier = (
                    (3 if week.chip == "3xc" else 2)
                    if row.player_id == week.captain.player_id
                    else 1
                )
                terms.append(
                    {
                        "gameweek": week.gameweek,
                        "player_id": row.player_id,
                        "multiplier": multiplier,
                        "forecast": float(str(row.expected_points)),
                        "baseline_forecast": float(
                            baseline_points.loc[(week.gameweek, row.player_id)]
                        ),
                    }
                )
        return terms

    scores: list[float] = []
    summaries: list[dict[str, Any]] = []
    for index, candidate in enumerate(menu):
        week = candidate.weeks[0]
        state = InitialSquadState(
            initial.squad_player_ids
            if week.chip == "freehit"
            else tuple(week.selected_squad.player_id),
            initial.bank_tenths if week.chip == "freehit" else week.bank_after_tenths,
            week.free_transfers_for_next_gameweek,
        )
        utility = _utility(week, optimization, transfer)
        branch_summaries = []
        for node in nodes:
            future = _continuation_horizon(
                node,
                week,
                sell_on_fee=(
                    0.5
                    if transfer.acquisition_sell_on_fee is None
                    else transfer.acquisition_sell_on_fee
                ),
            )
            continuation = optimize_transfer_plan(
                future,
                state,
                config(share),
                transfer,
                chips=remaining_chips(rights, week),
                preferences=preferences,
                linearization_level=2,
            )
            record(f"candidate_{index}/{node.observation_id}", share, continuation)
            if not continuation.has_solution:
                return finish(baseline, "incomplete_continuation")
            utility += node.probability * sum(
                _utility(w, optimization, transfer) for w in continuation.weeks
            )
            branch_summaries.append(
                {
                    "id": node.observation_id,
                    "probability": node.probability,
                    "point_terms": point_terms((week, *continuation.weeks)),
                    "net_points_on_selection_scale": net_week_points(week)
                    + sum(net_week_points(w) for w in continuation.weeks),
                    "hit_points": week.transfer_hit_points
                    + float(continuation.total_transfer_hit_points or 0),
                    "weeks": [
                        {
                            "gameweek": w.gameweek,
                            "in": w.transfers_in.player_id.tolist(),
                            "out": w.transfers_out.player_id.tolist(),
                            "chip": w.chip,
                            "bank": w.bank_after_tenths,
                            "ft": w.free_transfers_for_next_gameweek,
                        }
                        for w in continuation.weeks
                    ],
                }
            )
        scores.append(utility)
        summaries.append(
            {
                "first_in": week.transfers_in.player_id.tolist(),
                "first_out": week.transfers_out.player_id.tolist(),
                "first_chip": week.chip,
                "selection_utility": utility,
                "branches": branch_summaries,
            }
        )
    chosen = max(range(len(menu)), key=lambda i: (scores[i], -i))
    nominal = baseline
    if chosen:
        week = menu[chosen].weeks[0]
        nominal = optimize_transfer_plan(
            horizon,
            initial,
            config(0.1),
            transfer,
            chips=restrict_first_chip(rights, first, week.chip),
            fixed_week_squads={first: tuple(week.selected_squad.player_id)},
            preferences=preferences,
            linearization_level=2,
        )
        record("nominal_reconciliation", 0.1, nominal)
        if not nominal.has_solution:
            return finish(baseline, "incomplete_nominal")
        published = nominal.weeks[0]
        if (
            frozenset(published.starting_xi.player_id) != frozenset(week.starting_xi.player_id)
            or published.captain.player_id != week.captain.player_id
        ):
            # A bounded solve may pick another lineup for the same squad. Its score
            # was not the first action evaluated in every information branch.
            return finish(baseline, "incomplete_nominal_action")
    # A restricted information menu is not a global optimality certificate. Its nominal
    # solution's bound belongs to a different objective and must not be published here.
    nominal = replace(
        nominal,
        diagnostics={
            **nominal.diagnostics,
            "selection_status": "FEASIBLE_RESTRICTED_MENU",
            "absolute_optimality_gap": None,
            "relative_optimality_gap": None,
        },
    )
    return finish(
        nominal,
        "compared",
        chosen_index=chosen,
        candidates=summaries,
        utility_gain_vs_baseline=scores[chosen] - scores[0],
        hold_feasible=held.has_solution,
    )
