"""The transfer-plan menu: proven alternatives a play mode can choose between.

Built on the same synthetic world the league views use, because the menu sits on the same
live path: a real capture-shaped snapshot, the in-season handoff, and a held squad.
"""

from typing import Any

import pytest
import tests.unit.test_live_transfers as world_module

from squadopt.application.entries import EntryPicks, held_squad_from_picks
from squadopt.data.errors import DataSourceError
from squadopt.data.snapshots import read_snapshot
from squadopt.live import read_inputs, read_season_rules
from squadopt.live.recommendation import project, read_projection_handoff
from squadopt.live.transfers import HeldSquad, plan_transfer_menu, plan_transfers

SEASON = world_module.SEASON
world = world_module._world


def _context(world: dict[str, Any]) -> tuple[Any, Any, Any]:
    snapshot = read_snapshot(world["snapshot_root"], world["gw2_id"])
    inputs = read_inputs(snapshot, season=SEASON, gameweek=2)
    handoff = read_projection_handoff(world_module._handoff(world))
    projection = project(inputs, in_season=handoff)
    rules = read_season_rules(snapshot, season=SEASON)
    return inputs, projection, rules


def _held(world: dict[str, Any], inputs: Any, squad: list[int]) -> HeldSquad:
    """The same route a league member's squad takes: picks valued at current prices."""

    picks = EntryPicks(
        entry_id=101,
        season=SEASON,
        gameweek=1,
        squad=tuple(squad),
        starting_xi=tuple(squad[:11]),
        captain=squad[0],
        vice_captain=squad[1],
        bank_tenths=5,
        free_transfers=1,
        free_transfers_known=False,
        source_snapshot_id=world["gw2_id"],
    )
    prices = {
        int(str(row["player_id"])): int(str(row["price_tenths"]))
        for _, row in inputs.players.iterrows()
    }
    return held_squad_from_picks(picks, current_prices=prices)


def _legal_squad() -> list[int]:
    codes = [1001, 1002]
    codes += [1004, 1005, 1006, 1007, 1008]
    codes += [1012, 1013, 1014, 1015, 1016]
    codes += [1020, 1021, 1022]
    return codes


def test_the_menu_is_distinct_proven_plans_in_falling_order(world: dict[str, Any]) -> None:
    """Entry k keeps none of the previous squads intact and scores no better than entry 1.

    This is the property a mode needs: real alternatives, each proven optimal under its
    exclusions, ordered by the objective — not one plan under four names.
    """

    inputs, projection, rules = _context(world)

    menu = plan_transfer_menu(
        inputs, projection, rules=rules, held=_held(world, inputs, _legal_squad())
    )

    assert 2 <= len(menu) <= 5
    squads = [frozenset(d.purchase_prices_after) for _, d in menu]
    assert len(set(squads)) == len(squads), "every plan fields a different fifteen"
    scores = [plan.objective_value for plan, _ in menu]
    assert scores == sorted(scores, reverse=True), "best first, monotone thereafter"
    assert all(plan.solver_status.name == "OPTIMAL" for plan, _ in menu)


def test_the_menus_first_entry_is_the_planners_own_answer(world: dict[str, Any]) -> None:
    """A mode that picks entry one must get exactly what plan_transfers would decide."""

    inputs, projection, rules = _context(world)
    held = _held(world, inputs, _legal_squad())

    _, single, _ = plan_transfers(inputs, projection, held, rules)
    menu = plan_transfer_menu(inputs, projection, rules=rules, held=held)

    first = menu[0][1]
    assert sorted(first.purchase_prices_after) == sorted(single.purchase_prices_after)
    assert first.transfer_count == single.transfer_count
    assert first.transfer_hit_points == single.transfer_hit_points


def test_a_bad_plan_count_is_refused(world: dict[str, Any]) -> None:
    inputs, projection, rules = _context(world)

    with pytest.raises(DataSourceError, match="plan_count"):
        plan_transfer_menu(
            inputs, projection, rules=rules, held=_held(world, inputs, _legal_squad()), plan_count=0
        )
