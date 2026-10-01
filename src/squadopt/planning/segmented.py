"""Build complete incumbent decisions in segments without resetting squad resources.

These paths are proposals for full-model certification, not a global optimum or an
observation-contingent policy. Every segment sees the same decision-time forecast.
"""

from collections.abc import Sequence
from dataclasses import replace
from numbers import Integral
from typing import cast

from squadopt.contracts.preferences import DecisionPreferences
from squadopt.optimization import OptimizationConfig, SolverStatus, wall_clock_stopped_the_search
from squadopt.planning.models import (
    ChipAvailability,
    ChipUseWindow,
    InitialSquadState,
    PlanningHorizon,
    TransferPlanningConfig,
    TransferPlanningValidationError,
    TransferPlanResult,
)
from squadopt.planning.optimizer import optimize_transfer_plan
from squadopt.planning.pricing import sell_price_tenths
from squadopt.planning.recourse_chips import remaining_chips


class SegmentConstructionError(TransferPlanningValidationError):
    """An incomplete construction with its spent work preserved for the caller."""

    def __init__(self, message: str, *, actual_work: float, clock_stopped: bool):
        super().__init__(message)
        self.actual_work = actual_work
        self.clock_stopped = clock_stopped


def _segment_rights(rights: ChipAvailability, last: int) -> ChipAvailability:
    """Reserve a dated right forced later, even when that date is outside this solve."""
    windows = {}
    for name in rights.available:
        periods = []
        for period in rights.windows_for(name):
            reserved = any(
                chip == name and week > last and week in period.gameweeks
                for week, chip in rights.forced.items()
            )
            dates = (
                frozenset(week for week in period.gameweeks if week > last)
                if reserved
                else period.gameweeks
            )
            if dates:
                periods.append(ChipUseWindow(dates, period.holding_value_points))
        if periods:
            windows[name] = tuple(periods)
    return ChipAvailability(
        {
            name: frozenset().union(*(p.gameweeks for p in periods))
            for name, periods in windows.items()
        },
        rights.forced,
        windows,
    )


def plan_in_segments(
    horizon: PlanningHorizon,
    initial: InitialSquadState,
    optimization: OptimizationConfig,
    *,
    segment_lengths: Sequence[int],
    transfer: TransferPlanningConfig | None = None,
    chips: ChipAvailability | None = None,
    preferences: DecisionPreferences | None = None,
) -> TransferPlanResult:
    """Construct a complete sequential or window-then-tail incumbent.

    The explicit deterministic budget is for ALL segments together, apportioned by
    their lengths; no extra hold probe is run. Each segment's wall ceiling is also
    apportioned. Failed segments raise instead of silently returning a partial plan.
    New purchases keep their acquisition basis; original holdings retain their input
    sale paths until sold. Free Hit restores permanent holdings, lots and bank.
    Dates, player universe, points and user preferences are never regenerated.

    Only zero terminal bonuses are supported: placing a terminal bonus at each
    segment boundary would change the objective. Contributions are rebased to the
    original discount clock. Pass the result to incumbent protection before selecting
    it against another search; segment optimality is NOT full-horizon optimality.
    """
    forecast = horizon.validated_copy()
    lengths = tuple(segment_lengths)
    if (
        not lengths
        or any(isinstance(n, bool) or not isinstance(n, Integral) or n < 1 for n in lengths)
        or sum(lengths) != len(forecast.gameweeks)
    ):
        raise TransferPlanningValidationError("Segments must partition all forecast weeks.")
    budget = optimization.solver_deterministic_time_limit
    if budget is None:
        raise TransferPlanningValidationError(
            "Segment construction needs an explicit total budget."
        )
    settings = transfer or TransferPlanningConfig()
    rights = chips or ChipAvailability()
    original_rights = rights
    if (
        settings.banked_transfer_value_points
        or settings.chip_holding_value_points
        or any(
            period.holding_value_points not in (None, 0)
            for name in rights.available
            for period in rights.windows_for(name)
        )
    ):
        raise TransferPlanningValidationError(
            "Segment construction requires unpriced terminal rights."
        )
    state = initial
    purchases: dict[object, int] = {}
    weeks = []
    parts: list[TransferPlanResult] = []
    offset = 0
    clock_stopped = False
    fee = settings.acquisition_sell_on_fee
    for length in lengths:
        dates = forecast.gameweeks[offset : offset + length]
        table = forecast.table.loc[forecast.table.gameweek.isin(dates)].copy()
        if fee is not None:
            for index, row in table.iterrows():
                if row.player_id in purchases:
                    table.at[index, "sell_price_tenths"] = sell_price_tenths(
                        int(row.buy_price_tenths), purchases[row.player_id], sell_on_fee=fee
                    )
        fraction = length / len(forecast.gameweeks)
        config = replace(
            optimization,
            solver_deterministic_time_limit=budget * fraction,
            solver_time_limit_seconds=optimization.solver_time_limit_seconds * fraction,
        )
        part = optimize_transfer_plan(
            PlanningHorizon(table),
            state,
            config,
            settings,
            chips=_segment_rights(rights, dates[-1]),
            preferences=preferences,
            linearization_level=2,
        )
        clock_stopped = clock_stopped or wall_clock_stopped_the_search(
            part.solver_status, part.diagnostics
        )
        if not part.has_solution or tuple(w.gameweek for w in part.weeks) != dates:
            raise SegmentConstructionError(
                f"Segment starting at GW{dates[0]} did not produce a complete feasible path "
                f"({part.solver_status.name}); used deterministic time "
                f"{part.diagnostics.get('deterministic_time_used')}.",
                actual_work=sum(
                    cast(float, p.diagnostics["deterministic_time_used"]) for p in [*parts, part]
                ),
                clock_stopped=clock_stopped,
            )
        parts.append(part)
        for week in part.weeks:
            if week.bank_before_tenths != state.bank_tenths or (
                week.free_transfers_before != state.free_transfers
            ):
                raise TransferPlanningValidationError(
                    "Segment resource continuity is inconsistent."
                )
            if week.chip != "freehit":
                for player in week.transfers_out.player_id:
                    purchases.pop(player, None)
                if fee is not None:
                    purchases.update(
                        {
                            row.player_id: int(row.buy_price_tenths)
                            for _, row in week.transfers_in.iterrows()
                        }
                    )
                state = InitialSquadState(
                    tuple(week.selected_squad.player_id),
                    week.bank_after_tenths,
                    week.free_transfers_for_next_gameweek,
                )
            else:
                state = replace(state, free_transfers=week.free_transfers_for_next_gameweek)
            rights = remaining_chips(rights, week)
            weeks.append(
                replace(
                    week,
                    discounted_objective_contribution=(
                        week.discounted_objective_contribution
                        * settings.horizon_discount_factor**offset
                    ),
                )
            )
        offset += length
    diagnostics: dict[str, object] = {
        "configuration_fingerprint": settings.configuration_fingerprint,
        "chip_availability_fingerprint": original_rights.availability_fingerprint,
        "proof_scope": "segmented_feasible_only",
        "solver_status_name": "FEASIBLE",
        "best_objective_bound": None,
        "absolute_optimality_gap": None,
        "relative_optimality_gap": None,
        "segment_lengths": lengths,
        "construction_wall_clock_stopped": clock_stopped,
        "segment_statuses": tuple(part.solver_status.name for part in parts),
        "solver_deterministic_time_limit": budget,
        "deterministic_time_used": sum(
            cast(float, part.diagnostics["deterministic_time_used"]) for part in parts
        ),
        "solve_time_seconds": sum(
            cast(float, part.diagnostics["solve_time_seconds"]) for part in parts
        ),
    }
    if preferences is not None and preferences.active:
        diagnostics["decision_preferences"] = preferences.payload()
    return TransferPlanResult(
        solver_status=SolverStatus.FEASIBLE,
        weeks=tuple(weeks),
        horizon_fingerprint=forecast.horizon_fingerprint,
        total_projected_score=sum(w.projected_score for w in weeks),
        total_projected_bench_points=sum(w.projected_bench_points for w in weeks),
        total_transfer_hit_points=sum(w.transfer_hit_points for w in weeks),
        objective_value=sum(w.discounted_objective_contribution for w in weeks),
        diagnostics=diagnostics,
        chips_played={w.gameweek: w.chip for w in weeks if w.chip is not None},
    )
