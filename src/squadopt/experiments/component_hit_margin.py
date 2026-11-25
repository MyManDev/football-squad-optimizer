"""The member planner's hit margin, walked on the component forecast.

Protocol: ``docs/research/component_hit_margin_prereg.md``. The member planning policy plans
an extra transfer at 8 points while the game charges 4. That margin was chosen on a season
chain walked on the form-window control (`docs/member_policy_hit_cost_grid.md`), whose own
note reads the gain as hits not paid on an optimistic projection. The squads a member is
served are decided on the Phase C component base, and the chain could not be walked on it.

This module holds what the protocol fixes and nothing that reads a file: the arms, the labels,
the gate, the three readings and the forecast-against-realized gap of a chain. The runner is
``scripts/measure_component_hit_margin.py``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final

from squadopt.evaluation.promotion import ExperimentConfigurationError
from squadopt.experiments.multi_gw_rehearsal import (
    NAIVE_PROJECTION_RULE,
    SUPPLIED_DECISION_WEEK_PROJECTION_RULE,
)
from squadopt.experiments.season_chain import SeasonChainConfig
from squadopt.experiments.season_chain_runs import MAX_FREE_TRANSFERS
from squadopt.optimization import OptimizationConfig
from squadopt.planning import TransferPlanningConfig

COMPONENT_HIT_MARGIN_CONTRACT_VERSION: Final = "component_hit_margin_v1"
COMPONENT: Final = "component"
CONTROL: Final = "control"
FORECASTS: Final = (COMPONENT, CONTROL)
HIT_COST_LEVELS: Final = (4, 5, 6, 7, 8, 9, 10, 11, 12)
POLICY_HIT_COST: Final = 8
GAME_HIT_CHARGE: Final = 4
NOISE_FLOOR_POINTS_PER_GAMEWEEK: Final = 1.5
MAX_LOSING_SEASONS: Final = 1

READING_MOVE: Final = "move"
READING_CONFIRMED: Final = "confirmed"
READING_UNSUPPORTED: Final = "unsupported"


@dataclass(frozen=True, slots=True)
class Arm:
    """One chain configuration of the measurement, named."""

    label: str
    forecast: str
    hit_cost: int
    config: SeasonChainConfig


def arm_label(forecast: str, hit_cost: int) -> str:
    """The label of one forecast walked at one planning hit cost."""

    if forecast not in FORECASTS:
        raise ExperimentConfigurationError(f"forecast must be one of {FORECASTS!r}.")
    return f"{forecast}_hit{int(hit_cost)}"


def member_transfer_config(season: str, hit_cost: int) -> TransferPlanningConfig:
    """The member planning policy as the chain expresses it, at one planning hit cost.

    Everything but the planning cost is the policy's: the game's charge on the sheet, no
    banked transfer value, no discount, no transfer cap (the one-week member plan has none)
    and no chip.
    """

    return TransferPlanningConfig(
        max_free_transfers=MAX_FREE_TRANSFERS.get(season, 5),
        transfer_hit_cost_points=float(hit_cost),
        hit_points_charged=float(GAME_HIT_CHARGE),
        banked_transfer_value_points=0.0,
        horizon_discount_factor=1.0,
        max_transfers_per_gameweek=None,
        chip_holding_value_points={},
    )


def build_arms(
    season: str,
    forecast: str,
    optimization_config: OptimizationConfig,
    *,
    hit_costs: Sequence[int] = HIT_COST_LEVELS,
    end_gameweek: int | None = None,
) -> tuple[Arm, ...]:
    """The arms of one season and one forecast, in the order they are walked."""

    if forecast not in FORECASTS:
        raise ExperimentConfigurationError(f"forecast must be one of {FORECASTS!r}.")
    levels = tuple(int(level) for level in hit_costs)
    if not levels or len(set(levels)) != len(levels) or any(level < 0 for level in levels):
        raise ExperimentConfigurationError("hit_costs must name each non-negative level once.")
    rule = (
        SUPPLIED_DECISION_WEEK_PROJECTION_RULE if forecast == COMPONENT else NAIVE_PROJECTION_RULE
    )
    return tuple(
        Arm(
            label=arm_label(forecast, level),
            forecast=forecast,
            hit_cost=level,
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
                transfer_config=member_transfer_config(season, level),
            ),
        )
        for level in levels
    )


def comparison_pairs(
    hit_costs: Sequence[int] = HIT_COST_LEVELS,
) -> tuple[tuple[str, str], ...]:
    """Every (variant, baseline) label pair the record reports, primary first.

    For each forecast: every other level against the policy's 8, then every other level
    against the game's 4. The pair of 8 against 4 appears once, in the second group.
    """

    levels = tuple(int(level) for level in hit_costs)
    pairs: list[tuple[str, str]] = []
    for forecast in FORECASTS:
        for baseline in (POLICY_HIT_COST, GAME_HIT_CHARGE):
            if baseline not in levels:
                continue
            for level in levels:
                if level == baseline or (baseline == POLICY_HIT_COST and level == GAME_HIT_CHARGE):
                    continue
                pairs.append((arm_label(forecast, level), arm_label(forecast, baseline)))
    return tuple(pairs)


def gate(comparison: Mapping[str, object] | None) -> dict[str, object]:
    """The protocol's three checks on one paired comparison.

    A comparison passes when its mean paired gain is at least the noise floor, its 90%
    interval excludes zero on the positive side, and the variant's season net is lower than
    the baseline's in at most `MAX_LOSING_SEASONS` seasons.
    """

    if comparison is None:
        return {"available": False, "passed": False}
    mean = float(str(comparison["mean_weekly_advantage_points"]))
    interval = comparison.get("weekly_advantage_block_bootstrap_interval")
    low = float(interval[0]) if isinstance(interval, list | tuple) and len(interval) == 2 else None
    seasons = comparison.get("season_net_advantage_points")
    losing = (
        sorted(str(season) for season, value in seasons.items() if float(str(value)) < 0.0)
        if isinstance(seasons, Mapping)
        else []
    )
    clears_floor = mean >= NOISE_FLOOR_POINTS_PER_GAMEWEEK
    excludes_zero = low is not None and low > 0.0
    few_losing = len(losing) <= MAX_LOSING_SEASONS
    return {
        "available": True,
        "variant": comparison["variant"],
        "baseline": comparison["baseline"],
        "mean_weekly_advantage_points": mean,
        "interval_low": low,
        "losing_seasons": losing,
        "clears_noise_floor": clears_floor,
        "interval_excludes_zero": excludes_zero,
        "at_most_one_losing_season": few_losing,
        "passed": clears_floor and excludes_zero and few_losing,
    }


def reading(
    comparisons: Sequence[Mapping[str, object]],
    *,
    hit_costs: Sequence[int] = HIT_COST_LEVELS,
) -> dict[str, object]:
    """The protocol's reading of the component arm, fixed before any number was seen.

    ``move``: some level passes the gate against the policy's 8; the candidate is the passing
    level with the highest pooled mean, the one nearer 8 on a tie. ``confirmed``: none does,
    and 8 passes the gate against the game's 4. ``unsupported``: neither. The level with the
    highest pooled mean against 8 is named in every reading, with whether it sits on the
    edge of the grid, and decides nothing by itself.
    """

    levels = tuple(int(level) for level in hit_costs)
    by_pair = {(str(item["variant"]), str(item["baseline"])): item for item in comparisons}
    policy = arm_label(COMPONENT, POLICY_HIT_COST)
    against_policy = {
        level: gate(by_pair.get((arm_label(COMPONENT, level), policy)))
        for level in levels
        if level != POLICY_HIT_COST
    }
    policy_against_charge = gate(by_pair.get((policy, arm_label(COMPONENT, GAME_HIT_CHARGE))))
    means = {
        level: float(str(item["mean_weekly_advantage_points"]))
        for level, item in against_policy.items()
        if item["available"]
    }
    means[POLICY_HIT_COST] = 0.0
    best = max(means, key=lambda level: (means[level], -abs(level - POLICY_HIT_COST)))
    passing = sorted(level for level, item in against_policy.items() if item["passed"])
    if passing:
        candidate: int | None = max(
            passing, key=lambda level: (means[level], -abs(level - POLICY_HIT_COST))
        )
        name = READING_MOVE
    elif policy_against_charge["passed"]:
        candidate, name = None, READING_CONFIRMED
    else:
        candidate, name = None, READING_UNSUPPORTED
    return {
        "reading": name,
        "candidate_hit_cost": candidate,
        "levels_passing_against_policy": passing,
        "policy_against_game_charge": policy_against_charge,
        "against_policy": {str(level): item for level, item in sorted(against_policy.items())},
        "highest_pooled_mean_level": best,
        "highest_pooled_mean_on_grid_edge": best in (min(levels), max(levels)),
        "changes_a_default": False,
    }


def forecast_gap(record: Mapping[str, object]) -> dict[str, object]:
    """A chain's projected points against what it realized, per decision, before hits.

    The planner's projected score of each applied week minus the points that week scored on
    the chain's sheet: positive when the forecast promised more than the squad delivered.
    """

    weeks = record.get("weeks")
    if not isinstance(weeks, list) or not weeks:
        raise ExperimentConfigurationError("A chain record needs its weeks to read a gap.")
    gaps = [
        float(str(week["projected_points"])) - float(str(week["realized_points"])) for week in weeks
    ]
    return {
        "decisions": len(gaps),
        "mean_projected_points": sum(float(str(week["projected_points"])) for week in weeks)
        / len(weeks),
        "mean_realized_points": sum(float(str(week["realized_points"])) for week in weeks)
        / len(weeks),
        "mean_projected_minus_realized": sum(gaps) / len(gaps),
    }
