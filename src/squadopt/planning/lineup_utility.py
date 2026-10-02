"""Expected official lineup utility on an already feasible transfer/resource path.

The CP objective remains a proposal surrogate. No CP bound certifies this finite
lineup neighborhood. Forecasts contain unconditional points and weekly appearance.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import replace
from typing import Any

from squadopt.contracts import order_outfield_bench
from squadopt.optimization import OptimizationConfig, SolverStatus
from squadopt.planning.models import (
    ChipAvailability,
    PlanningWeekResult,
    TransferPlanningConfig,
    TransferPlanResult,
)
from squadopt.scenarios.expected_lineup import (
    ExpectedLineupScore,
    expected_lineup_score,
    improve_expected_lineup,
)

LINEUP_UTILITY_VERSION = "expected_lineup_v1"
LINEUP_EVALUATIONS_PER_WEEK = 128


def _roles(
    week: PlanningWeekResult, not_captain: Iterable[object] = ()
) -> tuple[tuple[object, ...], tuple[object, ...], object, object]:
    captain = week.captain.player_id
    vice = week.vice_captain_id
    if vice is None:
        eligible = week.starting_xi.loc[
            week.starting_xi.player_id.ne(captain)
            & ~week.starting_xi.player_id.isin(tuple(not_captain))
        ]
        if eligible.empty:
            raise ValueError("No allowed vice-captain in the supplied XI.")
        vice = (
            eligible.sort_values(["expected_points", "player_id"], ascending=[False, True])
            .iloc[0]
            .player_id
        )
    if week.lineup_expectation is not None:
        bench = tuple(week.bench.player_id)
    else:
        goalkeeper = tuple(week.bench.loc[week.bench.position.eq("GK"), "player_id"])
        outfield = order_outfield_bench(week.bench.loc[week.bench.position.ne("GK")])
        bench = (*goalkeeper, *outfield.player_id)
    return tuple(week.starting_xi.player_id), bench, captain, vice


def _metadata(score: ExpectedLineupScore) -> dict[str, object]:
    return {
        "version": LINEUP_UTILITY_VERSION,
        "scorer_version": score.contract_version,
        "expected_net_points": score.expected_net_points,
        "starting_points": score.starting_points,
        "autosub_points": score.autosub_points,
        "captain_bonus_points": score.captain_bonus_points,
        "vice_bonus_points": score.vice_bonus_points,
        "bench_boost_points": score.bench_boost_points,
        "scoring_multipliers": dict(score.scoring_multipliers),
        "assumptions": list(score.assumptions),
        "fingerprint": score.fingerprint,
        "states_evaluated": score.states_evaluated,
    }


def rescore_expected_week(week: PlanningWeekResult) -> PlanningWeekResult:
    """Preserve every role and bench priority while refreshing the forecast basis."""
    score = expected_lineup_score(
        week.selected_squad, *_roles(week), chip=week.chip, hit_points=week.transfer_hit_points
    )
    roster = week.selected_squad.set_index("player_id", drop=False)
    return replace(
        week,
        bench=roster.loc[list(score.ordered_bench)].reset_index(drop=True),
        vice_captain_id=score.vice_captain_id,
        lineup_expectation=_metadata(score),
    )


def expected_week_utility(week: PlanningWeekResult, transfer: TransferPlanningConfig) -> float:
    if week.lineup_expectation is None:
        raise ValueError("Expected utility requires the explicit fixed lineup score.")
    # Actual FPL hits are in the scorer; a caller's selection hit policy may differ.
    return (
        float(str(week.lineup_expectation["expected_net_points"]))
        + week.transfer_hit_points
        - week.paid_transfer_count * transfer.transfer_hit_cost_points
    )


def expected_selection_policy(
    transfer: TransferPlanningConfig, chips: ChipAvailability | None
) -> dict[str, object]:
    """Describe selection controls separately from the official points forecast."""
    return {
        "hit_points_charged": transfer.hit_points_charged,
        "transfer_hit_cost_points": transfer.transfer_hit_cost_points,
        "horizon_discount_factor": transfer.horizon_discount_factor,
        "banked_transfer_value_points": transfer.banked_transfer_value_points,
        "chip_holding_value_points": dict(transfer.chip_holding_value_points),
        "chip_holding_value_overrides": {
            name: [
                {
                    "gameweeks": sorted(period.gameweeks),
                    "holding_value_points": period.holding_value_points,
                }
                for period in periods
                if period.holding_value_points is not None
            ]
            for name, periods in sorted((chips or ChipAvailability()).use_windows.items())
            if any(period.holding_value_points is not None for period in periods)
        },
    }


def improve_plan_lineups(
    plan: TransferPlanResult,
    optimization: OptimizationConfig,
    transfer: TransferPlanningConfig,
    *,
    fixed_first: PlanningWeekResult | None = None,
    max_evaluations: int = LINEUP_EVALUATIONS_PER_WEEK,
    not_starting: Iterable[object] = (),
    not_captain: Iterable[object] = (),
) -> TransferPlanResult:
    """Change roles only; retain every transfer, price, bank, FT and chip decision.

    The supplied first action stays completely fixed before information arrives.
    Search validates formation, partition, captain/vice and ordered bench without
    another solver call. Candidate construction already enforces human constraints
    on ownership, hits and chips, none of which this function changes.
    """
    if not plan.has_solution:
        return plan
    not_starting, not_captain = tuple(not_starting), tuple(not_captain)
    weeks = []
    work: list[dict[str, Any]] = []
    for index, week in enumerate(plan.weeks):
        if index == 0 and fixed_first is not None:
            if (
                set(week.selected_squad.player_id) != set(fixed_first.selected_squad.player_id)
                or week.chip != fixed_first.chip
            ):
                raise ValueError("A fixed first action must retain its squad and chip.")
            roles = _roles(fixed_first, not_captain)
        else:
            roles = _roles(week, not_captain if index == 0 else ())
        result = improve_expected_lineup(
            week.selected_squad,
            *roles,
            chip=week.chip,
            hit_points=week.transfer_hit_points,
            max_evaluations=max_evaluations,
            locked_first=index == 0 and fixed_first is not None,
            not_starting=not_starting if index == 0 else (),
            not_captain=not_captain if index == 0 else (),
        )
        score = result.best
        roster = week.selected_squad.set_index("player_id", drop=False)
        starters = roster.loc[list(score.starting_xi)].reset_index(drop=True)
        bench = roster.loc[list(score.ordered_bench)].reset_index(drop=True)
        captain = roster.loc[[score.captain_id]].iloc[0].copy()
        raw_score = float(starters.expected_points.sum()) + float(captain.expected_points) * (
            2 if week.chip == "3xc" else 1
        )
        bench_points = float(bench.expected_points.sum())
        bench_weight = 1.0 if week.chip == "bboost" else optimization.bench_weight
        weeks.append(
            replace(
                week,
                starting_xi=starters,
                bench=bench,
                captain=captain,
                vice_captain_id=score.vice_captain_id,
                lineup_expectation=_metadata(score),
                projected_score=raw_score,
                projected_bench_points=bench_points,
                discounted_objective_contribution=transfer.horizon_discount_factor**index
                * (
                    raw_score
                    + bench_weight * bench_points
                    - week.paid_transfer_count * transfer.transfer_hit_cost_points
                ),
            )
        )
        work.append(
            {
                "gameweek": week.gameweek,
                "evaluations": result.evaluations,
                "cap": result.max_evaluations,
                "cache_hits": result.cache_hits,
                "budget_exhausted": result.budget_exhausted,
                "first_action_locked": result.locked_first,
                "states_evaluated": result.states_evaluated,
                "autosub_cache_hits": result.autosub_cache_hits,
                "captain_pairs_considered": result.captain_pairs_considered,
            }
        )
    terminal = float(str(plan.diagnostics.get("terminal_banked_transfer_value", 0))) + float(
        str(plan.diagnostics.get("terminal_chip_holding_value", 0))
    )
    return replace(
        plan,
        weeks=tuple(weeks),
        solver_status=SolverStatus.FEASIBLE,
        total_projected_score=sum(w.projected_score for w in weeks),
        total_projected_bench_points=sum(w.projected_bench_points for w in weeks),
        objective_value=sum(w.discounted_objective_contribution for w in weeks) + terminal,
        diagnostics={
            **plan.diagnostics,
            "lineup_search": {
                "version": LINEUP_UTILITY_VERSION,
                "weeks": work,
                "evaluations": sum(int(w["evaluations"]) for w in work),
                "proof_scope": "bounded_fixed_squad_neighborhood_only",
            },
            "primary_search_status": plan.diagnostics.get(
                "primary_search_status", plan.solver_status.name
            ),
            "solver_status_name": "FEASIBLE",
            "proof_scope": "feasible_resource_path_with_expected_lineup_selection",
            "scaled_model_objective_value": None,
            "best_objective_bound": None,
            "absolute_optimality_gap": None,
            "relative_optimality_gap": None,
        },
    )
