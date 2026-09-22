"""Chip-right transitions shared by the observation-contingent planner."""

from __future__ import annotations

from squadopt.planning.models import ChipAvailability, ChipUseWindow, PlanningWeekResult


def restrict_first_chip(
    chips: ChipAvailability, first: int, choice: str | None
) -> ChipAvailability:
    available = {}
    windows = {}
    for name in chips.available:
        periods = []
        for period in chips.windows_for(name):
            weeks = period.gameweeks if name == choice else period.gameweeks - {first}
            if weeks:
                periods.append(ChipUseWindow(frozenset(weeks), period.holding_value_points))
        if periods:
            windows[name] = tuple(periods)
            available[name] = frozenset().union(*(p.gameweeks for p in periods))
    forced = dict(chips.forced)
    if choice is not None:
        forced[first] = choice
    return ChipAvailability(available, forced, windows)


def remaining_chips(chips: ChipAvailability, week: PlanningWeekResult) -> ChipAvailability:
    """Consume only the current right, preserve renewals, prohibit consecutive Free Hits."""
    available = {}
    windows = {}
    for name in chips.available:
        periods = []
        for period in chips.windows_for(name):
            if name == week.chip and week.gameweek in period.gameweeks:
                continue
            weeks = frozenset(w for w in period.gameweeks if w > week.gameweek)
            if name == "freehit" and week.chip == "freehit":
                weeks -= {week.gameweek + 1}
            if weeks:
                periods.append(ChipUseWindow(weeks, period.holding_value_points))
        if periods:
            windows[name] = tuple(periods)
            available[name] = frozenset().union(*(p.gameweeks for p in periods))
    return ChipAvailability(
        available, {w: c for w, c in chips.forced.items() if w > week.gameweek}, windows
    )


def net_week_points(week: PlanningWeekResult) -> float:
    """projected_score includes TC but stores BB bench points separately."""
    return (
        week.projected_score
        + (week.projected_bench_points if week.chip == "bboost" else 0)
        - week.transfer_hit_points
    )
