"""Chip prices count official points and keep independent windows separate."""

from dataclasses import replace
from typing import Any

import pytest
from tests.unit.test_advice_record import _legal_squad, _member_picks, _world_context
from tests.unit.test_live_transfers import _world
from tests.unit.test_member_windows import _window_world

from squadopt.application.chip_publication import chip_recommendation_payload
from squadopt.application.entries import held_squad_from_picks
from squadopt.live.chip_advice import expected_chip_week_points, recommend_chips
from squadopt.live.rules import ChipWindow
from squadopt.live.transfers import plan_transfer_horizon, plan_transfers
from squadopt.optimization import OptimizationConfig
from squadopt.planning import CHIP_NAMES

world = _world
window_world = _window_world


def test_each_copy_has_its_own_window_and_spent_chips_are_not_offered(
    world: dict[str, Any],
) -> None:
    inputs, projection, rules = _world_context(world)
    rules = replace(
        rules,
        chips=tuple(
            ChipWindow(
                chip, 1, start, stop, "transfer" if chip in ("wildcard", "freehit") else "team"
            )
            for start, stop in [(1, 19), (20, 38)]
            for chip in CHIP_NAMES
        ),
    )
    picks = replace(_member_picks(world, 101, _legal_squad()), chips_used={"bboost": (1,)})
    prices = dict(zip(projection.table["player_id"], projection.table["price_tenths"], strict=True))
    held = held_squad_from_picks(picks, current_prices=prices)
    control, _, _ = plan_transfers(inputs, projection, held, rules)
    recommendations = recommend_chips(inputs, projection, held, rules, control)
    assert len(recommendations) == 7
    assert all(
        item.window.start_event == 20 for item in recommendations if item.window.name == "bboost"
    )
    future = [item for item in recommendations if item.window.start_event == 20]
    assert len(future) == 4
    assert all(item.gameweek is None and item.expected_gain is None for item in future)
    assert control.weeks[0].chip is None
    triple = next(
        item
        for item in recommendations
        if item.window.name == "3xc" and item.window.start_event == 1
    )
    assert triple.gameweek == 2
    assert triple.expected_gain is not None and triple.expected_gain > 0


def test_bench_boost_price_includes_bench_and_charges_actual_hits(world: dict[str, Any]) -> None:
    inputs, projection, rules = _world_context(world)
    rules = replace(rules, chips=tuple(row for row in rules.chips if row.name == "bboost"))
    picks = _member_picks(world, 101, _legal_squad())
    prices = dict(zip(projection.table["player_id"], projection.table["price_tenths"], strict=True))
    held = held_squad_from_picks(picks, current_prices=prices)
    control, _, _ = plan_transfers(inputs, projection, held, rules)
    recommendations = recommend_chips(inputs, projection, held, rules, control)
    item = recommendations[0]
    assert item.plan is not None
    week = item.plan.weeks[0]
    gross = float(week.selected_squad["expected_points"].sum() + week.captain["expected_points"])
    assert expected_chip_week_points(week) == pytest.approx(gross)
    assert item.expected_gain == pytest.approx(
        gross
        - week.transfer_hit_points
        - (control.weeks[0].projected_score - control.weeks[0].transfer_hit_points)
    )
    payload: Any = chip_recommendation_payload(recommendations, control)
    assert payload["comparisons"][0]["decision"]["expected_own_points"] == pytest.approx(gross)
    assert payload["planning_policy_id"] == "member_planning_policy_v3"


def test_window_places_triple_captain_in_the_later_high_scoring_week(
    window_world: dict[str, Any],
) -> None:
    inputs, projection, rules = (window_world[key] for key in ("inputs", "projection", "rules"))
    horizon = window_world["builder"]((2, 3, 4))
    table = horizon.table.copy()
    table.loc[table["gameweek"] == 3, "expected_points"] *= 10
    horizon = replace(horizon, table=table)
    rules = replace(rules, chips=(ChipWindow("3xc", 1, 1, 19, "team"),))
    picks = window_world["provider"].picks(101, "2026-27", 1)
    prices = dict(zip(projection.table["player_id"], projection.table["price_tenths"], strict=True))
    held = held_squad_from_picks(picks, current_prices=prices)
    settings = OptimizationConfig(
        solver_time_limit_seconds=1800, solver_deterministic_time_limit=60
    )
    control, _ = plan_transfer_horizon(inputs, horizon, held, rules, optimization=settings)
    items = recommend_chips(
        inputs, projection, held, rules, control, horizon=horizon, optimization=settings
    )
    assert items[0].gameweek == 3
    assert items[0].expected_gain is not None and items[0].expected_gain > 0
    assert all(week.chip is None for week in control.weeks)
