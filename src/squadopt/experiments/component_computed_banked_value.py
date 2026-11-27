"""A held free transfer's value computed each week from the planner's own forecast.

Protocol: ``docs/research/component_computed_banked_value_prereg.md``. The fixed-level
measurement (``component_banked_transfer_value``) priced a carried free transfer at one
constant for the season. This chain prices it per decision: the gain of next week's one-week
plan from one more free transfer, read on this week's forecast moved to next week's fixtures.
It overrides only the week's transfer configuration; every other step is the season chain's.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Final

import pandas as pd

from squadopt.experiments.component_banked_transfer_value import (
    PRIMARY_CELL,
    arm_label,
    build_arms,
)
from squadopt.experiments.component_hit_margin import MAX_LOSING_SEASONS, gate
from squadopt.experiments.season_chain import SeasonChain, SeasonChainConfig
from squadopt.optimization import OptimizationConfig
from squadopt.planning import InitialSquadState, TransferPlanningConfig, optimize_transfer_plan

COMPUTED_LABEL: Final = f"{PRIMARY_CELL[0]}_{PRIMARY_CELL[1]}_bankcomputed"
POLICY_LABEL: Final = arm_label(*PRIMARY_CELL, 0.0)
SECONDARY_LABELS: Final = (arm_label(*PRIMARY_CELL, 0.5), arm_label(*PRIMARY_CELL, 1.2))

READING_MOVE: Final = "move"
READING_DIRECTION: Final = "direction"
READING_UNSUPPORTED: Final = "unsupported"


def next_week_points(
    expected: Sequence[float],
    this_week_fixtures: Sequence[int],
    next_week_fixtures: Sequence[int],
) -> list[float]:
    """This week's expected points moved to next week's fixtures, per player.

    Per fixture where the club plays this week; unscaled where it is blank this week. The
    horizon builder then zeroes a club blank next week.
    """

    moved: list[float] = []
    for points, now, then in zip(expected, this_week_fixtures, next_week_fixtures, strict=True):
        rate = float(points) / int(now) if int(now) > 0 else float(points)
        moved.append(rate * int(then))
    return moved


def computed_value(hold: float | None, spend: float | None) -> float:
    """``max(0, P(k_hold) - P(k_spend))``; zero when either plan has no objective."""

    if hold is None or spend is None:
        return 0.0
    return max(0.0, float(hold) - float(spend))


class ComputedBankValueChain(SeasonChain):
    """The season chain with the banked value computed at every decision."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)  # type: ignore[arg-type]
        self.computed_values: dict[int, float] = {}

    def _next_gameweek(self, gameweek: int) -> int | None:
        later = [candidate for candidate in self.chain_gameweeks if candidate > gameweek]
        return min(later) if later else None

    def _week_transfer_config(self, gameweek: int, state: object) -> TransferPlanningConfig:
        frozen = self._settings.frozen_transfer_config
        cap = frozen.max_free_transfers
        free = int(state.free_transfers)  # type: ignore[attr-defined]
        k_spend = min(cap, free)
        k_hold = min(cap, free + 1)
        following = self._next_gameweek(gameweek)
        value = 0.0
        if following is not None and k_hold != k_spend:
            value = self._marginal_transfer_value(gameweek, following, state, k_hold, k_spend)
        self.computed_values[gameweek] = value
        return replace(frozen, banked_transfer_value_points=value)

    def _marginal_transfer_value(
        self, gameweek: int, following: int, state: object, k_hold: int, k_spend: int
    ) -> float:
        pool, _, _, _ = self._week_pool(gameweek, state)  # type: ignore[arg-type]
        teams = pool["team_id"].tolist()
        moved = pool.copy(deep=True)
        moved["expected_points"] = pd.Series(
            next_week_points(
                pool["expected_points"].tolist(),
                [self._fixture_counts.get((gameweek, team), 0) for team in teams],
                [self._fixture_counts.get((following, team), 0) for team in teams],
            ),
            index=pool.index,
            dtype="float64",
        )
        horizon = self._planning_horizon(moved, (following,), state)  # type: ignore[arg-type]
        plain = replace(self._settings.frozen_transfer_config, banked_transfer_value_points=0.0)
        objectives: dict[int, float | None] = {}
        for k in (k_spend, k_hold):
            plan = optimize_transfer_plan(
                horizon,
                InitialSquadState(
                    state.squad_ids,  # type: ignore[attr-defined]
                    bank_tenths=state.bank_tenths,  # type: ignore[attr-defined]
                    free_transfers=k,
                ),
                self._settings.frozen_optimization_config,
                plain,
                chips=None,
            )
            objectives[k] = plan.objective_value if plan.has_solution else None
        return computed_value(objectives[k_hold], objectives[k_spend])


@dataclass(frozen=True, slots=True)
class ComputedArm:
    """The one arm of the protocol: the primary cell with the computed value."""

    label: str
    config: SeasonChainConfig


def build_computed_arm(
    season: str, optimization_config: OptimizationConfig, *, end_gameweek: int | None = None
) -> ComputedArm:
    """The primary cell's policy arm; the chain computes its banked value each week."""

    (policy,) = build_arms(
        season,
        *PRIMARY_CELL,
        optimization_config,
        levels=(0.0,),
        end_gameweek=end_gameweek,
    )
    return ComputedArm(label=COMPUTED_LABEL, config=policy.config)


def _interval(comparison: Mapping[str, object]) -> tuple[float, float]:
    bounds = comparison["weekly_advantage_block_bootstrap_interval"]
    if not isinstance(bounds, list | tuple) or len(bounds) != 2:
        raise ValueError("A comparison carries a two-sided interval.")
    return float(bounds[0]), float(bounds[1])


def computed_reading(
    primary: Mapping[str, object],
    secondary: Mapping[str, Mapping[str, object]],
) -> dict[str, object]:
    """The protocol's reading from the primary comparison and the two secondary ones."""

    verdict = gate(primary)
    conditions = (
        bool(verdict["clears_noise_floor"]),
        bool(verdict["interval_excludes_zero"]),
        len(verdict["losing_seasons"]) <= MAX_LOSING_SEASONS,  # type: ignore[arg-type]
    )
    if all(conditions):
        label = READING_MOVE
    elif conditions[1] or sum(conditions) == 2:
        label = READING_DIRECTION
    else:
        label = READING_UNSUPPORTED
    sides: dict[str, str] = {}
    for name, comparison in secondary.items():
        low, high = _interval(comparison)
        sides[name] = "better" if low > 0 else "worse" if high < 0 else "not_separable"
    return {
        "reading": label,
        "primary": {
            "mean": float(verdict["mean_weekly_advantage_points"]),  # type: ignore[arg-type]
            "interval": list(_interval(primary)),
            "losing_seasons": verdict["losing_seasons"],
            "passed": all(conditions),
        },
        "secondary": sides,
        "proposes_computed_value": label == READING_MOVE
        and sides.get(SECONDARY_LABELS[0]) != "worse",
    }
