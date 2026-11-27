"""The value of a held free transfer, walked on the component forecast.

Protocol: ``docs/research/component_banked_transfer_value_prereg.md``. The member planning
policy gives a free transfer carried into next week no value, so the one-week plan spends a
free transfer on any move its forecast scores above zero. A value ``v`` makes the planner
spend one only on a move worth more than ``v``; at the bank cap the threshold switches itself
off. This module holds what the protocol fixes and nothing that reads a file: the arms, the
labels, the gate, the three readings and the free-transfer description of a chain. The runner
is ``scripts/measure_component_banked_transfer_value.py``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final

from squadopt.evaluation.promotion import ExperimentConfigurationError
from squadopt.experiments.component_hit_margin import (
    COMPONENT,
    CONTROL,
    GAME_HIT_CHARGE,
    MAX_LOSING_SEASONS,
    NOISE_FLOOR_POINTS_PER_GAMEWEEK,
    POLICY_HIT_COST,
    gate,
)
from squadopt.experiments.multi_gw_rehearsal import (
    NAIVE_PROJECTION_RULE,
    SUPPLIED_DECISION_WEEK_PROJECTION_RULE,
)
from squadopt.experiments.season_chain import SeasonChainConfig
from squadopt.experiments.season_chain_runs import MAX_FREE_TRANSFERS
from squadopt.optimization import OptimizationConfig
from squadopt.planning import TransferPlanningConfig

COMPONENT_BANKED_TRANSFER_VALUE_CONTRACT_VERSION: Final = "component_banked_transfer_value_v1"

BANKED_VALUE_LEVELS: Final = (0.0, 0.5, 1.0, 1.5, 2.0, 3.0, 4.0, 6.0)
POLICY_BANKED_VALUE: Final = 0.0

RULES_2026_27: Final = "rules_2026_27"
SEASON_RULES: Final = "season_rules"
CURRENT_FREE_TRANSFER_CAP: Final = 5

PRIMARY_CELL: Final = (COMPONENT, RULES_2026_27)
SECONDARY_CELL: Final = (COMPONENT, SEASON_RULES)
DESCRIPTIVE_CELL: Final = (CONTROL, SEASON_RULES)
CELLS: Final = (PRIMARY_CELL, SECONDARY_CELL, DESCRIPTIVE_CELL)

READING_MOVE: Final = "move"
READING_DIRECTION: Final = "direction"
READING_UNSUPPORTED: Final = "unsupported"


@dataclass(frozen=True, slots=True)
class Arm:
    """One chain configuration of the measurement, named."""

    label: str
    forecast: str
    rules: str
    banked_value: float
    config: SeasonChainConfig


def _check_cell(forecast: str, rules: str) -> None:
    if (forecast, rules) not in CELLS:
        raise ExperimentConfigurationError(
            f"({forecast!r}, {rules!r}) is not a cell of the protocol: {CELLS!r}."
        )


def level_tag(level: float) -> str:
    """A level as a label fragment: 0, 0p5, 1p5, 6."""

    value = float(level)
    if value < 0 or value * 2 != int(value * 2):
        raise ExperimentConfigurationError("A banked value level is a non-negative half point.")
    return f"{value:g}".replace(".", "p")


def arm_label(forecast: str, rules: str, level: float) -> str:
    """The label of one forecast, under one free-transfer rule, at one banked value."""

    _check_cell(forecast, rules)
    return f"{forecast}_{rules}_bank{level_tag(level)}"


def free_transfer_cap(season: str, rules: str) -> int:
    """The bank cap a chain plans under: this season's 5, or the season's own."""

    if rules == RULES_2026_27:
        return CURRENT_FREE_TRANSFER_CAP
    if rules == SEASON_RULES:
        return MAX_FREE_TRANSFERS.get(season, CURRENT_FREE_TRANSFER_CAP)
    raise ExperimentConfigurationError(f"Unknown free-transfer rule {rules!r}.")


def member_transfer_config(season: str, rules: str, banked_value: float) -> TransferPlanningConfig:
    """The member planning policy with one control moved: the held free transfer's value."""

    return TransferPlanningConfig(
        max_free_transfers=free_transfer_cap(season, rules),
        transfer_hit_cost_points=float(POLICY_HIT_COST),
        hit_points_charged=float(GAME_HIT_CHARGE),
        banked_transfer_value_points=float(banked_value),
        horizon_discount_factor=1.0,
        max_transfers_per_gameweek=None,
        chip_holding_value_points={},
    )


def build_arms(
    season: str,
    forecast: str,
    rules: str,
    optimization_config: OptimizationConfig,
    *,
    levels: Sequence[float] = BANKED_VALUE_LEVELS,
    end_gameweek: int | None = None,
) -> tuple[Arm, ...]:
    """The arms of one season and one cell, in the order they are walked."""

    _check_cell(forecast, rules)
    values = tuple(float(level) for level in levels)
    if not values or len(set(values)) != len(values):
        raise ExperimentConfigurationError("levels must name each banked value once.")
    rule = (
        SUPPLIED_DECISION_WEEK_PROJECTION_RULE if forecast == COMPONENT else NAIVE_PROJECTION_RULE
    )
    return tuple(
        Arm(
            label=arm_label(forecast, rules, value),
            forecast=forecast,
            rules=rules,
            banked_value=value,
            config=SeasonChainConfig(
                season=season,
                lookahead=1,
                end_gameweek=end_gameweek,
                form_window=5,
                candidate_pool_per_position=20,
                cheap_pool_per_position=8,
                chip_windows=(),
                hit_points_charged=float(GAME_HIT_CHARGE),
                sell_on_fee_halved=True,
                projection_rule=rule,
                optimization_config=optimization_config,
                transfer_config=member_transfer_config(season, rules, value),
            ),
        )
        for value in values
    )


def comparison_pairs(
    levels: Sequence[float] = BANKED_VALUE_LEVELS,
) -> tuple[tuple[str, str], ...]:
    """Every (variant, baseline) pair the record reports: each level against 0, per cell."""

    values = tuple(float(level) for level in levels)
    if POLICY_BANKED_VALUE not in values:
        raise ExperimentConfigurationError("The grid must hold the policy's 0.")
    return tuple(
        (
            arm_label(forecast, rules, value),
            arm_label(forecast, rules, POLICY_BANKED_VALUE),
        )
        for forecast, rules in CELLS
        for value in values
        if value != POLICY_BANKED_VALUE
    )


def _interval_high(comparison: Mapping[str, object] | None) -> float:
    """The upper end of a comparison's 90% interval; +inf when there is none."""

    interval = (
        None if comparison is None else comparison.get("weekly_advantage_block_bootstrap_interval")
    )
    if not isinstance(interval, list | tuple) or len(interval) != 2:
        return float("inf")
    return float(interval[1])


def _direction(item: Mapping[str, object]) -> bool:
    return (
        bool(item["available"])
        and bool(item["interval_excludes_zero"])
        and bool(item["at_most_one_losing_season"])
    )


def cell_reading(
    comparisons: Sequence[Mapping[str, object]],
    forecast: str,
    rules: str,
    *,
    levels: Sequence[float] = BANKED_VALUE_LEVELS,
) -> dict[str, object]:
    """The protocol's reading of one cell, fixed before any number was seen.

    ``move``: some level passes the gate against 0; the candidate is the passing level with
    the highest pooled mean, the lower level on a tie. ``direction``: none passes, but some
    level has its interval above zero and at most one losing season; the named level is
    chosen the same way. ``unsupported``: neither.
    """

    values = tuple(float(level) for level in levels)
    by_pair = {(str(item["variant"]), str(item["baseline"])): item for item in comparisons}
    baseline = arm_label(forecast, rules, POLICY_BANKED_VALUE)
    against_policy = {
        value: gate(by_pair.get((arm_label(forecast, rules, value), baseline)))
        for value in values
        if value != POLICY_BANKED_VALUE
    }
    means = {
        value: float(str(item["mean_weekly_advantage_points"]))
        for value, item in against_policy.items()
        if item["available"]
    }
    means[POLICY_BANKED_VALUE] = 0.0

    def pick(candidates: Sequence[float]) -> float:
        return max(candidates, key=lambda value: (means[value], -value))

    best = pick(list(means))
    passing = sorted(value for value, item in against_policy.items() if item["passed"])
    directional = sorted(value for value, item in against_policy.items() if _direction(item))
    harmful = sorted(
        value
        for value in against_policy
        if _interval_high(by_pair.get((arm_label(forecast, rules, value), baseline))) < 0.0
    )
    if passing:
        name, level = READING_MOVE, pick(passing)
    elif directional:
        name, level = READING_DIRECTION, pick(directional)
    else:
        name, level = READING_UNSUPPORTED, None
    return {
        "cell": {"forecast": forecast, "rules": rules},
        "reading": name,
        "named_level": level,
        "levels_passing": passing,
        "levels_directional": directional,
        "levels_with_interval_below_zero": harmful,
        "highest_pooled_mean_level": best,
        "highest_pooled_mean_on_grid_edge": best in (min(values), max(values)),
        "against_policy": {f"{value:g}": item for value, item in sorted(against_policy.items())},
    }


def reading(
    comparisons: Sequence[Mapping[str, object]],
    *,
    levels: Sequence[float] = BANKED_VALUE_LEVELS,
) -> dict[str, object]:
    """The primary cell's reading, the secondary's beside it, and whether they agree."""

    primary = cell_reading(comparisons, *PRIMARY_CELL, levels=levels)
    secondary = cell_reading(comparisons, *SECONDARY_CELL, levels=levels)
    descriptive = cell_reading(comparisons, *DESCRIPTIVE_CELL, levels=levels)
    return {
        "reading": primary["reading"],
        "named_level": primary["named_level"],
        "primary": primary,
        "secondary": secondary,
        "secondary_agrees": (
            secondary["reading"] == primary["reading"]
            and secondary["named_level"] == primary["named_level"]
        ),
        "descriptive_control": descriptive,
        "comparisons_against_one_baseline": len(levels) - 1,
        "intervals_corrected_for_multiplicity": False,
        "noise_floor_points_per_gameweek": NOISE_FLOOR_POINTS_PER_GAMEWEEK,
        "max_losing_seasons": MAX_LOSING_SEASONS,
        "changes_a_default": False,
    }


def free_transfer_use(record: Mapping[str, object], cap: int) -> dict[str, object]:
    """How a chain used its free transfers: used, paid, lost at the cap, held on average."""

    weeks = record.get("weeks")
    if not isinstance(weeks, list) or not weeks:
        raise ExperimentConfigurationError("A chain record needs its weeks to read its transfers.")
    used = paid = lost = held = 0
    for week in weeks:
        before = int(str(week["free_transfers_before"]))
        transfers = int(str(week["transfer_count"]))
        paid_here = int(str(week["paid_transfer_count"]))
        used += transfers - paid_here
        paid += paid_here
        held += before
        if before >= cap and transfers == 0:
            lost += 1
    return {
        "decisions": len(weeks),
        "free_transfers_used": used,
        "paid_transfers": paid,
        "free_transfers_lost_at_cap": lost,
        "mean_free_transfers_held": held / len(weeks),
        "cap": cap,
    }
