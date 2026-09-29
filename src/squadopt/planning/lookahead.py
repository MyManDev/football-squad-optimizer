"""Explicit forecast lookahead, with decision-window points separated from the tail."""

from dataclasses import dataclass

from squadopt.contracts.preferences import DecisionPreferences
from squadopt.optimization import OptimizationConfig
from squadopt.planning.models import (
    ChipAvailability,
    InitialSquadState,
    PlanningHorizon,
    PlanningWeekResult,
    TransferPlanningConfig,
    TransferPlanningValidationError,
    TransferPlanResult,
)
from squadopt.planning.optimizer import optimize_transfer_plan
from squadopt.planning.recourse_chips import net_week_points


@dataclass(frozen=True)
class LookaheadPlan:
    """The full feasible path is retained; its tail is not a displayed-window return."""

    plan: TransferPlanResult
    decision_weeks: tuple[int, ...]
    forecast_fingerprint: str

    @property
    def window(self) -> tuple[PlanningWeekResult, ...]:
        return tuple(w for w in self.plan.weeks if w.gameweek in self.decision_weeks)

    @property
    def window_net_points(self) -> float:
        return sum(net_week_points(w) for w in self.window)

    @property
    def tail_net_points(self) -> float:
        return sum(
            net_week_points(w) for w in self.plan.weeks if w.gameweek not in self.decision_weeks
        )


def optimize_with_lookahead(
    forecast: PlanningHorizon,
    initial: InitialSquadState,
    optimization: OptimizationConfig,
    *,
    window: int,
    transfer: TransferPlanningConfig | None = None,
    chips: ChipAvailability | None = None,
    preferences: DecisionPreferences | None = None,
) -> LookaheadPlan:
    """Use an explicitly supplied tail instead of fitting a scalar terminal bonus.

    The caller must provide decision-time forecasts, including explicit blanks. A
    missing tail is an error, never repeated current-week points or assumed zeros.
    This deterministic extension can trade window points for later points. It is
    not a calibrated season value function, and is not guaranteed to improve returns.
    """
    forecast = forecast.validated_copy()
    if isinstance(window, bool) or not isinstance(window, int) or window not in (3, 5):
        raise ValueError("Decision window must be three or five weeks.")
    if len(forecast.gameweeks) <= window:
        raise ValueError("Lookahead requires explicit forecast weeks beyond the decision window.")
    settings = transfer or TransferPlanningConfig()
    if settings.banked_transfer_value_points or settings.chip_holding_value_points:
        raise ValueError("Explicit lookahead cannot be stacked with terminal constants.")
    if chips is not None and any(
        p.holding_value_points not in (None, 0)
        for name in chips.available
        for p in chips.windows_for(name)
    ):
        raise ValueError("Explicit lookahead requires unpriced chip rights.")
    result = optimize_transfer_plan(
        forecast,
        initial,
        optimization,
        settings,
        chips=chips,
        preferences=preferences,
        protect_hold=True,
        linearization_level=2,
    )
    if not result.has_solution:
        raise TransferPlanningValidationError("Lookahead did not find a feasible full path.")
    return LookaheadPlan(result, forecast.gameweeks[:window], forecast.horizon_fingerprint)
