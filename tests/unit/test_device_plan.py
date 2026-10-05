"""The published device-plan inputs are the inputs the server's own solver was given.

Pinned by rebuilding the problem from the two published documents alone, solving it with
the repository's planner, and comparing with the advice the same build published.
"""

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pandas as pd
import pytest
import tests.unit.test_live_transfers as world_module
from tests.unit.test_league_views import (
    DISCRETIONARY_SQUAD,
    _discretionary_projection,
    _legal_squad,
    _member_picks,
    _Provider,
    _world_context,
)

from squadopt.application.device_plan import (
    DEVICE_PLAN_CONTRACT_VERSION,
    DEVICE_PLAN_DOCUMENT,
    device_plan_entry,
)
from squadopt.application.entries import EntryRegistration, held_squad_from_picks
from squadopt.application.league_views import build_league_views
from squadopt.live.transfers import MEMBER_PLANNING_POLICY, member_planning_inputs
from squadopt.optimization import OptimizationConfig
from squadopt.optimization.coefficients import objective_coefficients, scale_expected_points
from squadopt.planning import (
    InitialSquadState,
    PlanningHorizon,
    TransferPlanningConfig,
    optimize_transfer_plan,
)

world = world_module._world  # re-register the fixture in this module


def _build(
    world: dict[str, Any], out: Path
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    inputs, projection, rules = _world_context(world)
    squad = _legal_squad(world)
    build_league_views(
        _Provider({101: _member_picks(world, 101, squad)}),
        (EntryRegistration(101, "member-a", "2026-08-23T00:00:00Z"),),
        inputs,
        projection,
        rules,
        league_id=352490,
        league_name="Test League",
        out_dir=out,
    )
    shared = json.loads((out / DEVICE_PLAN_DOCUMENT).read_text(encoding="utf-8"))
    entry = json.loads((out / "entries" / "101.json").read_text(encoding="utf-8"))
    advice = json.loads(
        (out / "advice" / "101" / "saf-puan" / "1.json").read_text(encoding="utf-8")
    )
    return shared, entry, advice


def test_the_shared_document_carries_the_table_in_solver_order_with_the_solver_s_numbers(
    world: dict[str, Any], tmp_path: Path
) -> None:
    inputs, projection, rules = _world_context(world)
    shared, entry, _ = _build(world, tmp_path / "league")

    assert shared["contract_version"] == "provisional_league_ui_v1"
    payload = shared["payload"]
    assert payload["contract_version"] == DEVICE_PLAN_CONTRACT_VERSION
    assert payload["source_snapshot_id"] == inputs.snapshot_id
    assert (payload["season"], payload["gameweek"]) == (inputs.season, 2)
    # The table, in the order the solver breaks ties by.
    assert [p["id"] for p in payload["players"]] == [
        int(v) for v in projection.table["player_id"].tolist()
    ]
    expected = objective_coefficients(
        projection.table["expected_points"].tolist(), OptimizationConfig()
    )
    assert [tuple(p["coefficients"]) for p in payload["players"]] == list(expected)
    rules_out = payload["rules"]
    settings = OptimizationConfig()
    assert rules_out["squad_size"] == settings.squad_size
    assert rules_out["expected_points_scale"] == settings.expected_points_scale
    assert rules_out["max_free_transfers"] == rules.transfers.max_free_transfers
    assert rules_out["hit_points_charged"] == 4.0
    # The caution margin, as a literal and as the planner's own scaling of the policy.
    assert rules_out["hit_cost_scaled"] == 8000
    assert rules_out["hit_cost_scaled"] == scale_expected_points(
        MEMBER_PLANNING_POLICY["transfer_hit_cost_points"], rules_out["expected_points_scale"]
    )
    ids = [p["id"] for p in payload["players"]]
    assert ids == sorted(ids) and len(set(ids)) == len(ids)

    # The member's side: the fifteen, the spending power, the free transfers, a sale
    # price for each held player and for nobody else.
    block = entry["payload"]["device_plan"]
    held = held_squad_from_picks(
        _member_picks(world, 101, _legal_squad(world)),
        current_prices={
            int(v): int(p)
            for v, p in zip(
                projection.table["player_id"], projection.table["price_tenths"], strict=True
            )
        },
    )
    prepared = member_planning_inputs(inputs, projection, held, rules)
    assert block["held"] == list(held.squad_player_ids)
    assert block["bank_tenths"] == prepared.bank_tenths
    assert block["free_transfers"] == prepared.free_transfers
    assert block["sell_tenths"] == {
        str(p): prepared.sell_prices_tenths[p] for p in held.squad_player_ids
    }


def test_the_two_documents_alone_rebuild_the_problem_the_published_plan_solved(
    world: dict[str, Any], tmp_path: Path
) -> None:
    """Numbers from the documents, the repository's solver, the published answer."""

    shared, entry, advice = _build(world, tmp_path / "league")
    payload, block = shared["payload"], entry["payload"]["device_plan"]
    rules_out = payload["rules"]
    sell = {int(k): v for k, v in block["sell_tenths"].items()}
    horizon = PlanningHorizon(
        pd.DataFrame(
            {
                "gameweek": payload["gameweek"],
                "player_id": [p["id"] for p in payload["players"]],
                "name": [p["name"] for p in payload["players"]],
                "team_id": [p["team"] for p in payload["players"]],
                "position": [p["position"] for p in payload["players"]],
                "buy_price_tenths": [p["buy_tenths"] for p in payload["players"]],
                "sell_price_tenths": [
                    sell.get(p["id"], p["buy_tenths"]) for p in payload["players"]
                ],
                "expected_points": [p["expected_points"] for p in payload["players"]],
            }
        )
    )
    transfer = TransferPlanningConfig(
        max_free_transfers=rules_out["max_free_transfers"],
        transfer_hit_cost_points=rules_out["hit_cost_scaled"] / rules_out["expected_points_scale"],
        hit_points_charged=rules_out["hit_points_charged"],
        banked_transfer_value_points=0.0,
        horizon_discount_factor=1.0,
        chip_holding_value_points={},
    )
    plan = optimize_transfer_plan(
        horizon,
        InitialSquadState(
            tuple(block["held"]),
            bank_tenths=block["bank_tenths"],
            free_transfers=block["free_transfers"],
        ),
        OptimizationConfig(),
        transfer,
    )
    week = plan.weeks[0]
    published = advice["payload"]
    assert published["solver_status"] == "OPTIMAL"
    assert sorted(int(v) for v in week.transfers_in["player_id"]) == sorted(
        m["player_in"]["player_id"] for m in published["moves"]
    )
    assert sorted(int(v) for v in week.transfers_out["player_id"]) == sorted(
        m["player_out"]["player_id"] for m in published["moves"]
    )
    assert int(week.captain["player_id"]) == published["captain"]["player_id"]
    assert sorted(int(v) for v in week.starting_xi["player_id"]) == sorted(
        p["player_id"] for p in published["starting_xi"]
    )
    assert (
        published["transfer_hit_points"]
        == max(0, len(published["moves"]) - block["free_transfers"])
        * rules_out["hit_points_charged"]
    )


def test_the_member_block_carries_the_spending_power_not_the_raw_numbers(
    world: dict[str, Any],
) -> None:
    """A stated sale value below the priced total takes the bank first, then every price."""

    inputs, projection, rules = _world_context(world)
    picks = _member_picks(world, 101, _legal_squad(world))
    prices = {
        int(v): int(p)
        for v, p in zip(
            projection.table["player_id"], projection.table["price_tenths"], strict=True
        )
    }
    assert picks.bank_tenths == 5 and picks.squad_sell_value_tenths is not None
    short = replace(picks, squad_sell_value_tenths=picks.squad_sell_value_tenths - 12)
    block = device_plan_entry(
        inputs, projection, held_squad_from_picks(short, current_prices=prices), rules
    )
    assert block is not None
    # Shortfall 12: the bank of 5 is withheld first, the remaining 7 comes off every price.
    assert block["bank_tenths"] == 0
    assert block["sell_tenths"] == {str(p): prices[p] - 7 for p in picks.squad}
    assert block["free_transfers"] == 1


def test_the_published_caution_margin_is_the_one_that_decides_the_plan(
    world: dict[str, Any], tmp_path: Path
) -> None:
    """On a squad whose second upgrade straddles the margin, 8.0 declines it and 4.0 buys it."""

    inputs, projection, rules = _world_context(world)
    tuned = _discretionary_projection(projection)
    out = tmp_path / "league"
    build_league_views(
        _Provider({101: _member_picks(world, 101, list(DISCRETIONARY_SQUAD))}),
        (EntryRegistration(101, "member-a", "2026-08-23T00:00:00Z"),),
        inputs,
        tuned,
        rules,
        league_id=352490,
        league_name="Test League",
        out_dir=out,
    )
    shared = json.loads((out / DEVICE_PLAN_DOCUMENT).read_text(encoding="utf-8"))["payload"]
    block = json.loads((out / "entries" / "101.json").read_text(encoding="utf-8"))["payload"][
        "device_plan"
    ]
    published = json.loads(
        (out / "advice" / "101" / "saf-puan" / "1.json").read_text(encoding="utf-8")
    )["payload"]
    assert len(published["moves"]) == 1  # the free upgrade; the priced one is declined

    def solve_with(hit_cost_points: float) -> list[int]:
        sell = {int(k): v for k, v in block["sell_tenths"].items()}
        horizon = PlanningHorizon(
            pd.DataFrame(
                {
                    "gameweek": shared["gameweek"],
                    "player_id": [p["id"] for p in shared["players"]],
                    "name": [p["name"] for p in shared["players"]],
                    "team_id": [p["team"] for p in shared["players"]],
                    "position": [p["position"] for p in shared["players"]],
                    "buy_price_tenths": [p["buy_tenths"] for p in shared["players"]],
                    "sell_price_tenths": [
                        sell.get(p["id"], p["buy_tenths"]) for p in shared["players"]
                    ],
                    "expected_points": [p["expected_points"] for p in shared["players"]],
                }
            )
        )
        plan = optimize_transfer_plan(
            horizon,
            InitialSquadState(
                tuple(block["held"]),
                bank_tenths=block["bank_tenths"],
                free_transfers=block["free_transfers"],
            ),
            OptimizationConfig(),
            TransferPlanningConfig(
                max_free_transfers=shared["rules"]["max_free_transfers"],
                transfer_hit_cost_points=hit_cost_points,
                hit_points_charged=shared["rules"]["hit_points_charged"],
                banked_transfer_value_points=0.0,
                horizon_discount_factor=1.0,
                chip_holding_value_points={},
            ),
        )
        return sorted(int(v) for v in plan.weeks[0].transfers_in["player_id"])

    published_hit = shared["rules"]["hit_cost_scaled"] / shared["rules"]["expected_points_scale"]
    assert solve_with(published_hit) == sorted(
        m["player_in"]["player_id"] for m in published["moves"]
    )
    assert len(solve_with(4.0)) == 2


def test_a_member_the_live_path_refuses_publishes_no_block(world: dict[str, Any]) -> None:
    inputs, projection, rules = _world_context(world)
    picks = _member_picks(world, 101, _legal_squad(world))
    prices = {
        int(v): int(p)
        for v, p in zip(
            projection.table["player_id"], projection.table["price_tenths"], strict=True
        )
    }
    held = held_squad_from_picks(picks, current_prices=prices)
    assert device_plan_entry(inputs, projection, held, rules) is not None
    # A squad decided for another week is not this deadline's problem.
    stale = replace(held, decided_gameweek=held.decided_gameweek - 1)
    assert device_plan_entry(inputs, projection, stale, rules) is None


@pytest.mark.parametrize("field", ["held", "bank_tenths", "free_transfers", "sell_tenths"])
def test_the_member_block_names_every_input_the_device_needs(
    world: dict[str, Any], tmp_path: Path, field: str
) -> None:
    _, entry, _ = _build(world, tmp_path / "league")
    assert field in entry["payload"]["device_plan"]
