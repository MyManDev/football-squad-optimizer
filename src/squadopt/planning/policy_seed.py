"""Reuse complete decisions when information changes forecasts alone.

Returned plans are seeds for the planner's independent incumbent certification.
They carry fresh arithmetic, never an inherited optimum or search bound.
"""

from dataclasses import replace

import pandas as pd

from squadopt.optimization import OptimizationConfig, SolverStatus
from squadopt.planning.lineup_utility import rescore_expected_week
from squadopt.planning.models import (
    ChipAvailability,
    PlanningHorizon,
    PlanningWeekResult,
    TransferPlanningConfig,
    TransferPlanningValidationError,
    TransferPlanResult,
)

_FORECAST_COLUMNS = frozenset({"expected_points", "appearance_probability"})


def _validate_chip_schedule(
    weeks: tuple[PlanningWeekResult, ...], rights: ChipAvailability
) -> None:
    played = {week.gameweek: week.chip for week in weeks if week.chip is not None}
    dates = {week.gameweek for week in weeks}
    if any(week not in rights.gameweeks_for(chip) for week, chip in played.items()) or any(
        played.get(week) != chip for week, chip in rights.forced.items() if week in dates
    ):
        raise TransferPlanningValidationError("Policy seed chip schedule violates supplied rights.")
    for name in rights.available:
        if any(
            sum(chip == name and week in period.gameweeks for week, chip in played.items()) > 1
            for period in rights.windows_for(name)
        ):
            raise TransferPlanningValidationError("Policy seed repeats a consumed chip right.")
    if any(played.get(week + 1) == "freehit" for week, chip in played.items() if chip == "freehit"):
        raise TransferPlanningValidationError("Policy seed plays consecutive Free Hits.")


def _refresh_frame(frame: pd.DataFrame, current: pd.DataFrame) -> pd.DataFrame:
    if "player_id" not in frame:
        raise TransferPlanningValidationError("Policy seed is missing player identifiers.")
    players = frame.player_id.tolist()
    if len(set(players)) != len(players) or not set(players) <= set(current.index):
        raise TransferPlanningValidationError("Policy seed has duplicate or unknown players.")
    updated = frame.copy(deep=True)
    for column in _FORECAST_COLUMNS:
        if column in current:
            updated[column] = current.loc[players, column].to_numpy()
        elif column in updated:
            updated = updated.drop(columns=column)
    return updated


def forecast_policy_seed(
    plan: TransferPlanResult,
    source_horizon: PlanningHorizon,
    target_horizon: PlanningHorizon,
    optimization: OptimizationConfig,
    transfer: TransferPlanningConfig,
    *,
    source_chips: ChipAvailability | None = None,
    target_chips: ChipAvailability | None = None,
) -> TransferPlanResult:
    """Refresh a complete policy for forecasts on exactly the same asset paths.

    Original and target weeks, identities, prices and all non-forecast columns must
    agree. The source plan must match its source horizon, transfer rules and chip
    rights. Explicit target rights can relax proposal restrictions, but the entire
    existing chip schedule must remain valid. All squad, lineup, captain, transfer,
    chip, bank and free-transfer decisions remain unchanged; acquisition lots keep
    their original clock because this adapter never slices or rebases the horizon.

    Pass the result as ``incumbent_plan`` with ``protect_incumbent=True``. This
    function performs no solve: the current CP model must independently certify
    feasibility, preferences and resource accounting before using these decisions.
    Its recomputed scores are descriptive and are never a supplied solver bound.
    """
    source = source_horizon.validated_copy()
    target = target_horizon.validated_copy()
    original_rights = source_chips or ChipAvailability()
    rights = original_rights if target_chips is None else target_chips
    if (
        not isinstance(plan, TransferPlanResult)
        or not plan.has_solution
        or plan.horizon_fingerprint != source.horizon_fingerprint
        or tuple(week.gameweek for week in plan.weeks) != source.gameweeks
        or plan.diagnostics.get("configuration_fingerprint") != transfer.configuration_fingerprint
        or plan.diagnostics.get("chip_availability_fingerprint")
        != original_rights.availability_fingerprint
    ):
        raise TransferPlanningValidationError(
            "Policy seed must match its complete source horizon and rules."
        )
    expected = source.table.set_index(["gameweek", "player_id"]).sort_index()
    current = target.table.set_index(["gameweek", "player_id"]).sort_index()
    fixed_columns = set(expected.columns) - _FORECAST_COLUMNS
    if (
        source.gameweeks != target.gameweeks
        or not expected.index.equals(current.index)
        or fixed_columns != set(current.columns) - _FORECAST_COLUMNS
        or any(not expected[column].equals(current[column]) for column in fixed_columns)
    ):
        raise TransferPlanningValidationError(
            "Policy seed reuse permits forecast changes only; "
            "weeks, identities and prices must match."
        )
    chips_played = {week.gameweek: week.chip for week in plan.weeks if week.chip is not None}
    if dict(plan.chips_played) != chips_played:
        raise TransferPlanningValidationError(
            "Policy seed chip summary disagrees with its decisions."
        )
    _validate_chip_schedule(plan.weeks, original_rights)
    _validate_chip_schedule(plan.weeks, rights)
    weeks = []
    for index, week in enumerate(plan.weeks):
        players = target.table.loc[target.table.gameweek.eq(week.gameweek)].set_index("player_id")
        squad = _refresh_frame(week.selected_squad, players)
        starters = _refresh_frame(week.starting_xi, players)
        bench = _refresh_frame(week.bench, players)
        captain = _refresh_frame(week.captain.to_frame().T, players).iloc[0].copy(deep=True)
        captain.name = None
        score = float(starters.expected_points.sum()) + float(captain.expected_points) * (
            2 if week.chip == "3xc" else 1
        )
        bench_points = float(bench.expected_points.sum())
        bench_weight = 1.0 if week.chip == "bboost" else optimization.bench_weight
        weeks.append(
            replace(
                week,
                selected_squad=squad,
                starting_xi=starters,
                bench=bench,
                captain=captain,
                transfers_in=_refresh_frame(week.transfers_in, players),
                transfers_out=_refresh_frame(week.transfers_out, players),
                projected_score=score,
                projected_bench_points=bench_points,
                transfer_hit_points=week.paid_transfer_count * transfer.hit_points_charged,
                discounted_objective_contribution=transfer.horizon_discount_factor**index
                * (
                    score
                    + bench_weight * bench_points
                    - week.paid_transfer_count * transfer.transfer_hit_cost_points
                ),
            )
        )
    weeks = [
        rescore_expected_week(week) if week.lineup_expectation is not None else week
        for week in weeks
    ]
    discount = transfer.horizon_discount_factor ** (len(weeks) - 1)
    terminal_transfers = (
        transfer.banked_transfer_value_points
        * weeks[-1].free_transfers_for_next_gameweek
        * discount
    )
    terminal_chips = discount * sum(
        transfer.chip_holding_value_points.get(name, 0.0)
        if period.holding_value_points is None
        else period.holding_value_points
        for name in rights.available
        for period in rights.windows_for(name)
        if not any(chip == name and week in period.gameweeks for week, chip in chips_played.items())
    )
    return TransferPlanResult(
        solver_status=SolverStatus.FEASIBLE,
        weeks=tuple(weeks),
        horizon_fingerprint=target.horizon_fingerprint,
        total_projected_score=sum(week.projected_score for week in weeks),
        total_projected_bench_points=sum(week.projected_bench_points for week in weeks),
        total_transfer_hit_points=sum(week.transfer_hit_points for week in weeks),
        objective_value=sum(week.discounted_objective_contribution for week in weeks)
        + terminal_transfers
        + terminal_chips,
        diagnostics={
            "configuration_fingerprint": transfer.configuration_fingerprint,
            "chip_availability_fingerprint": rights.availability_fingerprint,
            "proof_scope": "forecast_policy_seed_requires_certification",
            "solver_status_name": "FEASIBLE",
            "best_objective_bound": None,
            "absolute_optimality_gap": None,
            "relative_optimality_gap": None,
            "terminal_banked_transfer_value": terminal_transfers,
            "terminal_chip_holding_value": terminal_chips,
            "source_horizon_fingerprint": source.horizon_fingerprint,
            "source_objective_used": False,
        },
        chips_played=chips_played,
    )
