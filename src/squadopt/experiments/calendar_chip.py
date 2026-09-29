"""Research chip timing from explicit future forecasts of a fixed held squad.

No stationary resampling of the current window and no invented future fixture.
This restricted benchmark does not model transfers, injuries or chip competition.
"""

from dataclasses import replace

from squadopt.optimization import OptimizationConfig, SolverExecutionError, SolverStatus
from squadopt.planning import (
    ChipAvailability,
    InitialSquadState,
    PlanningHorizon,
    TransferPlanningConfig,
    TransferPlanResult,
    optimize_transfer_plan,
)


def optimize_calendar_chip(
    forecast: PlanningHorizon,
    initial: InitialSquadState,
    optimization: OptimizationConfig,
    chips: ChipAvailability,
    *,
    window: int,
) -> TransferPlanResult:
    """Joint lineup/chip timing in a short window, with a dated single-chip tail.

    Caller supplies one pre-deadline forecast through every eligible date, including
    explicit zero rows for known blanks. Missing dates are unknown, never zero.
    Only the existing squad is optimized. The finite deterministic stopping value
    is V(t)=max(opportunity(t), V(t+1)); it is not a fitted stochastic season MDP.
    Exactly one TC or BB right is supported, so tail chip collisions cannot hide.
    """
    forecast = forecast.validated_copy()
    if isinstance(window, bool) or not isinstance(window, int) or window not in (1, 3, 5):
        raise ValueError("Window must be 1, 3 or 5 weeks.")
    if optimization.bench_weight != 0:
        raise ValueError("Calendar chip benchmark requires zero bench weight.")
    if len(chips.available) != 1 or not set(chips.available) <= {"3xc", "bboost"}:
        raise ValueError("Calendar benchmark requires exactly one TC or BB chip.")
    name = next(iter(chips.available))
    periods = chips.windows_for(name)
    if len(periods) != 1 or periods[0].holding_value_points is not None:
        raise ValueError("Calendar benchmark requires one unpriced chip right.")
    dates = chips.gameweeks_for(name)
    first = forecast.gameweeks[0]
    end = first + window - 1
    if (
        not dates
        or not dates <= set(forecast.gameweeks)
        or min(dates) < first
        or end > forecast.gameweeks[-1]
    ):
        raise ValueError("Forecast must cover every eligible date and the full window.")
    if any(w > end for w in chips.forced):
        raise ValueError("A forced future chip is outside the selected decision window.")
    table = forecast.table.loc[forecast.table.player_id.isin(initial.squad_player_ids)].copy()
    if set(table.player_id) != set(initial.squad_player_ids):
        raise ValueError("Forecast is missing a held player.")
    held = PlanningHorizon(table)
    settings = TransferPlanningConfig()
    opportunities: dict[int, float] = {}
    for week in sorted(dates):
        reference = optimize_transfer_plan(
            PlanningHorizon(table.loc[table.gameweek.eq(week)].copy()),
            initial,
            optimization,
            settings,
            linearization_level=2,
        )
        if reference.solver_status is not SolverStatus.OPTIMAL or not reference.weeks:
            raise SolverExecutionError("Calendar chip reference must be proved optimal.")
        result = reference.weeks[0]
        opportunities[week] = max(
            0.0,
            float(
                result.captain.expected_points if name == "3xc" else result.projected_bench_points
            ),
        )
    tail = {w: v for w, v in opportunities.items() if w > end}
    reserve = max(tail.values(), default=0.0)
    priced = replace(
        chips, use_windows={name: (replace(periods[0], holding_value_points=reserve),)}
    )
    plan = optimize_transfer_plan(
        PlanningHorizon(table.loc[table.gameweek.le(end)].copy()),
        initial,
        optimization,
        settings,
        chips=priced,
        linearization_level=2,
        protect_hold=True,
    )
    return replace(
        plan,
        diagnostics={
            **plan.diagnostics,
            "calendar_chip": {
                "version": "fixed_squad_calendar_chip_v1",
                "forecast_fingerprint": forecast.horizon_fingerprint,
                "held_forecast_fingerprint": held.horizon_fingerprint,
                "opportunities": opportunities,
                "holding_value": reserve,
                "tail_best_week": max(tail, key=lambda w: tail[w]) if tail else None,
                "proof_scope": "fixed_squad_single_chip_forecast",
                "prospective_superiority": False,
                "limits": "Fixed squad; future news and chip competition excluded.",
            },
        },
    )
