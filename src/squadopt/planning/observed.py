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
    FirstWeekExclusion,
    InitialSquadState,
    PlanningHorizon,
    PlanningWeekResult,
    TransferPlanningConfig,
    TransferPlanResult,
)
from squadopt.planning.optimizer import optimize_transfer_plan
from squadopt.planning.policy_seed import forecast_policy_seed
from squadopt.planning.recourse import ObservationNode
from squadopt.planning.recourse_chips import net_week_points, restrict_first_chip

OBSERVED_WINDOW_VERSION = "complete_observed_window_v2"
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

    Complete policies are reused and certified against every full-horizon branch.
    At most three distinct first actions and two information branches are compared.
    Optional proposals are admitted only when complete. Incomplete evaluation of
    an admitted action never selects from the surviving subset. The baseline
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
        hold_work = plan.diagnostics.get("hold_protection")
        if isinstance(hold_work, dict):
            probe_used = float(hold_work.get("deterministic_time") or 0)
            probe_cap = float(hold_work["deterministic_time_limit"])
            if hold_work.get("status") in {"FEASIBLE", "UNKNOWN"} and probe_used < probe_cap - 1e-9:
                raise SolverExecutionError(
                    "Information hold probe reached its wall-clock safety limit."
                )
            if not isinstance(construction, dict):
                used = float(str(used)) + probe_used
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

    def add(
        plan: TransferPlanResult,
        source: PlanningHorizon,
        source_rights: ChipAvailability,
    ) -> None:
        if not plan.has_solution:
            return
        # Normalize provenance and scores to the nominal horizon; every branch
        # independently certifies these decisions in its final constrained model.
        plan = forecast_policy_seed(
            plan,
            source,
            horizon,
            optimization,
            transfer,
            source_chips=source_rights,
            target_chips=rights,
        )
        week = plan.weeks[0]
        key = action_key(week)
        if all(key != action_key(p.weeks[0]) for p in menu):
            menu.append(plan)

    def action_key(week: PlanningWeekResult) -> tuple[object, ...]:
        return (
            frozenset(week.selected_squad.player_id),
            frozenset(week.starting_xi.player_id),
            week.captain.player_id,
            week.chip,
        )

    def retain_float_utility(
        result: TransferPlanResult,
        seed: TransferPlanResult,
    ) -> TransferPlanResult:
        # The CP objective rounds coefficients. Its certified witness is also
        # protected on the unrounded utility used by this finite-menu comparison.
        if result.has_solution and sum(
            _utility(w, optimization, transfer) for w in result.weeks
        ) + 1e-9 < sum(_utility(w, optimization, transfer) for w in seed.weeks):
            return replace(
                seed,
                diagnostics={
                    **result.diagnostics,
                    "selection_status": "FEASIBLE_RESTRICTED_MENU",
                    "unrounded_incumbent_retained": True,
                    "primary_search_status": result.diagnostics.get(
                        "primary_search_status", result.solver_status.name
                    ),
                    "solver_status_name": "FEASIBLE",
                    "scaled_model_objective_value": None,
                    "best_objective_bound": None,
                    "absolute_optimality_gap": None,
                    "relative_optimality_gap": None,
                },
                solver_status=SolverStatus.FEASIBLE,
            )
        return result

    held_rights = restrict_first_chip(rights, first, rights.forced.get(first))
    hold_config = config(0.1)
    # Reuse the existing independently verified all-hold witness. Reserve its
    # one-unit probe inside this phase; the main search still allows later moves.
    hold_cap = budget * 0.1
    protect_hold = hold_cap > 1
    if protect_hold:
        hold_wall = hold_config.solver_time_limit_seconds
        hold_config = replace(
            hold_config,
            solver_deterministic_time_limit=hold_cap - 1,
            solver_time_limit_seconds=hold_wall - min(30.0, hold_wall / 2),
        )
    held = optimize_transfer_plan(
        horizon,
        initial,
        hold_config,
        transfer,
        chips=held_rights,
        fixed_week_squads={first: tuple(initial.squad_player_ids)},
        preferences=preferences,
        linearization_level=2,
        protect_hold=protect_hold,
    )
    record("hold_proposal", 0.1, held)
    add(held, horizon, held_rights)
    today = horizon.table.loc[horizon.table.gameweek.eq(first)]
    branches = tuple(
        PlanningHorizon(pd.concat([today, node.horizon.table], ignore_index=True)) for node in nodes
    )
    proposal_seed = forecast_policy_seed(
        baseline,
        horizon,
        branches[0],
        optimization,
        transfer,
        source_chips=rights,
        target_chips=rights,
    )
    proposal = optimize_transfer_plan(
        branches[0],
        initial,
        config(0.1),
        transfer,
        chips=rights,
        preferences=preferences,
        linearization_level=2,
        incumbent_plan=proposal_seed,
        protect_incumbent=True,
    )
    record("information_proposal", 0.1, proposal)
    add(proposal, branches[0], rights)
    if len(menu) < 2:
        return finish(baseline, "no_distinct_alternative", candidate_count=len(menu))
    share = 0.3 / (len(menu) * len(nodes))
    universe = frozenset(today.player_id)

    def improve(
        candidate: TransferPlanResult,
        target: PlanningHorizon,
        fraction: float,
    ) -> TransferPlanResult:
        week = candidate.weeks[0]
        branch_rights = restrict_first_chip(rights, first, week.chip)
        seed = forecast_policy_seed(
            candidate,
            horizon,
            target,
            optimization,
            transfer,
            source_chips=rights,
            target_chips=branch_rights,
        )
        result = optimize_transfer_plan(
            target,
            initial,
            config(fraction),
            transfer,
            chips=branch_rights,
            fixed_week_squads={first: tuple(week.selected_squad.player_id)},
            first_week_exclusion=FirstWeekExclusion(
                not_starting=universe - frozenset(week.starting_xi.player_id),
                not_captain=universe - {week.captain.player_id},
            ),
            preferences=preferences,
            linearization_level=2,
            incumbent_plan=seed,
            protect_incumbent=True,
        )
        return retain_float_utility(result, seed)

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
        utility = 0.0
        branch_summaries = []
        for node, branch in zip(nodes, branches, strict=True):
            continuation = improve(candidate, branch, share)
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
                    "point_terms": point_terms(continuation.weeks),
                    "net_points_on_selection_scale": sum(
                        net_week_points(w) for w in continuation.weeks
                    ),
                    "hit_points": float(continuation.total_transfer_hit_points or 0),
                    "first_action": {
                        "squad": continuation.weeks[0].selected_squad.player_id.tolist(),
                        "starters": continuation.weeks[0].starting_xi.player_id.tolist(),
                        "captain": continuation.weeks[0].captain.player_id,
                        "chip": continuation.weeks[0].chip,
                        "in": continuation.weeks[0].transfers_in.player_id.tolist(),
                        "out": continuation.weeks[0].transfers_out.player_id.tolist(),
                        "bank": continuation.weeks[0].bank_after_tenths,
                        "ft": continuation.weeks[0].free_transfers_for_next_gameweek,
                    },
                    "weeks": [
                        {
                            "gameweek": w.gameweek,
                            "in": w.transfers_in.player_id.tolist(),
                            "out": w.transfers_out.player_id.tolist(),
                            "chip": w.chip,
                            "bank": w.bank_after_tenths,
                            "ft": w.free_transfers_for_next_gameweek,
                        }
                        for w in continuation.weeks[1:]
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
        nominal = improve(menu[chosen], horizon, 0.1)
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
        solver_status=SolverStatus.FEASIBLE,
        diagnostics={
            **nominal.diagnostics,
            "selection_status": "FEASIBLE_RESTRICTED_MENU",
            "proof_scope": "complete_observed_action_menu",
            "primary_search_status": nominal.diagnostics.get(
                "primary_search_status", nominal.solver_status.name
            ),
            "solver_status_name": "FEASIBLE",
            "scaled_model_objective_value": None,
            "best_objective_bound": None,
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
        candidate_count=len(menu),
        branch_count=len(nodes),
        horizon_length=len(horizon.gameweeks),
        proposal_completed=proposal.has_solution,
    )
