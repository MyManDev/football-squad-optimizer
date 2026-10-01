r"""Export one member's real one-week planning problem, and solve it with the server's solver.

    python spikes/in-browser-solve/export_instance.py \
        --capture <data/snapshots/fpl-live-...> --handoff <data/handoffs/...json> \
        --entry-json <published league/entries/<id>.json> --out <instance.json>

This is a feasibility spike, not product code. It builds the same one-week table
``live/transfers.py`` hands the planner (current prices, the stated squad sell value applied
through ``spending_power``, the member planning policy), solves it with the repository's own
``optimize_transfer_plan``, and writes the instance plus that reference answer as JSON. The
browser side solves the same instance with another solver and is compared against the
reference here. Nothing is written under ``data/`` and no live store is opened.
"""

import argparse
import json
import time
from pathlib import Path

import pandas as pd

from squadopt.data.snapshots import read_snapshot
from squadopt.live.recommendation import project, read_inputs, read_projection_handoff
from squadopt.optimization.coefficients import objective_coefficients, scale_expected_points
from squadopt.optimization.config import OptimizationConfig
from squadopt.planning import (
    InitialSquadState,
    PlanningHorizon,
    TransferPlanningConfig,
    optimize_transfer_plan,
)
from squadopt.planning.pricing import spending_power

#: `live/transfers.py` MEMBER_PLANNING_POLICY, copied by value so the instance states it.
HIT_COST_IN_SOLVE = 8.0
HIT_POINTS_CHARGED = 4.0
MAX_FREE_TRANSFERS = 5


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--capture", type=Path, required=True)
    parser.add_argument("--handoff", type=Path, required=True)
    parser.add_argument("--entry-json", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    arguments = parser.parse_args()

    # The live path's own reading: the capture's roster, the handoff's numbers, and the
    # availability rule applied on top. Rebuilding this by hand from the bootstrap payload
    # gave a different pool and a different answer, because the rule is part of the price.
    snapshot = read_snapshot(arguments.capture.parent, arguments.capture.name)
    handoff = read_projection_handoff(arguments.handoff)
    inputs = read_inputs(snapshot, season=handoff.season, gameweek=handoff.gameweek)
    projection = project(inputs, in_season=handoff)
    table = (
        projection.table.loc[
            :, ["player_id", "name", "team_id", "position", "price_tenths", "expected_points"]
        ]
        .copy(deep=True)
        .reset_index(drop=True)
    )
    table["player_id"] = table["player_id"].astype("int64")

    entry = json.loads(arguments.entry_json.read_text(encoding="utf-8"))["payload"]
    held = [int(player["player_id"]) for player in (*entry["starting_xi"], *entry["bench"])]
    current = dict(zip(table["player_id"].tolist(), table["price_tenths"].tolist(), strict=True))
    # Purchase prices are not public for a member, so the current price is the per-player
    # sell price and the stated squad value removes the overstatement, bank first.
    budget = spending_power(
        bank_tenths=int(entry["bank_tenths"]),
        sell_prices_tenths={player: int(current[player]) for player in held},
        stated_squad_sell_value_tenths=entry.get("squad_sell_value_tenths"),
    )
    sell = dict(budget.sell_prices_tenths)
    gameweek = int(entry["gameweek"])
    horizon_table = pd.DataFrame(
        {
            "gameweek": gameweek,
            "player_id": table["player_id"].astype("int64"),
            "name": table["name"],
            "team_id": table["team_id"],
            "position": table["position"],
            "buy_price_tenths": table["price_tenths"].astype("int64"),
            "sell_price_tenths": [
                sell.get(int(player), int(price))
                for player, price in zip(table["player_id"], table["price_tenths"], strict=True)
            ],
            "expected_points": table["expected_points"].astype("float64"),
        }
    )
    free_transfers = min(int(entry["free_transfers"]), MAX_FREE_TRANSFERS)
    optimization = OptimizationConfig(
        solver_time_limit_seconds=300.0, solver_deterministic_time_limit=100.0
    )
    transfer_config = TransferPlanningConfig(
        max_free_transfers=MAX_FREE_TRANSFERS,
        transfer_hit_cost_points=HIT_COST_IN_SOLVE,
        hit_points_charged=HIT_POINTS_CHARGED,
        banked_transfer_value_points=0.0,
        horizon_discount_factor=1.0,
        chip_holding_value_points={},
    )
    started = time.perf_counter()
    plan = optimize_transfer_plan(
        PlanningHorizon(horizon_table),
        InitialSquadState(
            tuple(held), bank_tenths=budget.bank_tenths, free_transfers=free_transfers
        ),
        optimization,
        transfer_config,
    )
    seconds = time.perf_counter() - started
    week = plan.weeks[0]
    coefficients = objective_coefficients(table["expected_points"].tolist(), optimization)
    reference = {
        "solver": "ortools CP-SAT, the repository's optimize_transfer_plan",
        "solver_status": plan.solver_status.value,
        "seconds": seconds,
        "objective_value": plan.objective_value,
        "squad": sorted(int(value) for value in week.selected_squad["player_id"]),
        "starting_xi": sorted(int(value) for value in week.starting_xi["player_id"]),
        "captain": int(week.captain["player_id"]),
        "transfers_in": sorted(int(value) for value in week.transfers_in["player_id"]),
        "transfers_out": sorted(int(value) for value in week.transfers_out["player_id"]),
        "bench_order": [int(value) for value in week.bench["player_id"]],
        "vice_captain": None if week.vice_captain_id is None else int(week.vice_captain_id),
        "projected_score": float(week.projected_score),
    }
    instance = {
        "note": "feasibility spike; one member's one-week problem as the server builds it",
        "gameweek": gameweek,
        "source_snapshot_id": handoff.source_snapshot_id,
        "model_version": handoff.model_version,
        "players_marked_unavailable": len(projection.unavailable_players),
        "entry_id": int(entry["entry"]["entry_id"]),
        "held": held,
        "bank_tenths": int(budget.bank_tenths),
        "free_transfers": free_transfers,
        "rules": {
            "squad_size": optimization.squad_size,
            "starting_size": optimization.starting_size,
            "squad_position_limits": dict(optimization.squad_position_limits),
            "starting_position_min": dict(optimization.starting_position_min),
            "starting_position_max": dict(optimization.starting_position_max),
            "max_players_per_team": optimization.max_players_per_team,
            # Scaled the way the planner scales it, so the two objectives are one integer.
            "hit_cost_scaled": scale_expected_points(
                HIT_COST_IN_SOLVE, optimization.expected_points_scale
            ),
            "expected_points_scale": optimization.expected_points_scale,
        },
        "players": [
            {
                "id": int(row.player_id),
                "name": row.name,
                "team": str(row.team_id),
                "position": row.position,
                "buy": int(row.buy_price_tenths),
                "sell": int(row.sell_price_tenths),
                "expected_points": float(row.expected_points),
                # (squad, starter, captain): the server's exact integer coefficients.
                "coefficients": list(coefficients[index]),
            }
            for index, row in enumerate(horizon_table.itertuples(index=False))
        ],
        "reference": reference,
    }
    arguments.out.parent.mkdir(parents=True, exist_ok=True)
    arguments.out.write_text(json.dumps(instance, ensure_ascii=False), encoding="utf-8")
    names = dict(zip(table["player_id"], table["name"], strict=True))
    print(f"players {len(table)}, held {len(held)}, bank {budget.bank_tenths}, FT {free_transfers}")
    print(
        f"server solver: {plan.solver_status.value} in {seconds:.2f}s, "
        f"objective {plan.objective_value}"
    )
    print("out:", [names[p] for p in reference["transfers_out"]])
    print("in: ", [names[p] for p in reference["transfers_in"]])
    print("captain:", names[reference["captain"]])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
