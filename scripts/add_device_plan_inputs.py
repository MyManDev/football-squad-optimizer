"""Add the device-plan inputs to a league tree that was published before they existed.

    python -m scripts.add_device_plan_inputs --snapshot-root <captures> \\
        --snapshot-id <capture> --handoff <exact-handoff> --site-data-root <candidate>/data

The league site builder writes ``device-plan.json`` and a ``device_plan`` block on every entry
document (``docs/contracts/league_device_plan_v1.md``). A tree built before that carries the
members' plans and nothing for a device to solve from. This writes exactly what the builder
would have written for that tree: the capture's table from the handoff the plans were
computed from, and each member's side from the entry document itself, under the tree's
own publication stamp. Nothing is solved and no plan changes; the plans stay the bytes
the advice record holds.

Refused: a tree whose members or entries name another capture than the one given, a
handoff for another capture or gameweek, a member whose fifteen the capture does not
price. With ``--verify`` every member's problem is rebuilt from the written documents and
solved with the repository's planner, and the transfers, captain and eleven must be the
published ones.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

from squadopt.application.device_plan import (
    DEVICE_PLAN_DOCUMENT,
    device_plan_entry,
    device_plan_table,
)
from squadopt.application.entries import EntryError
from squadopt.contracts.league import LEAGUE_VIEW_CONTRACT_VERSION
from squadopt.data.errors import DataError
from squadopt.data.snapshots import read_snapshot
from squadopt.live import read_inputs, read_season_rules
from squadopt.live.recommendation import project, read_projection_handoff
from squadopt.live.transfers import HeldSquad
from squadopt.optimization import OptimizationConfig
from squadopt.planning import (
    InitialSquadState,
    PlanningHorizon,
    TransferPlanningConfig,
    optimize_transfer_plan,
)


class DevicePlanInputsError(Exception):
    """The tree, the capture and the handoff do not describe one publication."""


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, document: dict) -> None:
    # The builder's own formatting, so the bytes are what it would have written.
    path.write_text(json.dumps(document, indent=2), encoding="utf-8", newline="\n")


def _held_from_entry(entry: dict, prices: dict[int, int]) -> HeldSquad:
    """The held squad as ``held_squad_from_picks`` builds it, from the published document.

    The entry publishes no purchase prices, so the current prices stand in for them and the
    stated squad selling value caps the budget, exactly the fallback the builder took.
    """

    ids = [int(p["player_id"]) for p in (*entry["starting_xi"], *entry["bench"])]
    missing = [p for p in ids if p not in prices]
    if missing:
        raise EntryError(
            f"No current price for players {missing[:5]!r}; the capture must cover the squad."
        )
    if entry.get("purchase_prices_known"):
        raise DevicePlanInputsError(
            f"Entry {entry['entry']['entry_id']} publishes purchase prices, which this tree's "
            "builder did not; the builder itself must write its inputs."
        )
    if entry.get("squad_sell_value_tenths") is None:
        raise EntryError(f"Entry {entry['entry']['entry_id']} states no squad selling value.")
    chips = entry.get("chips_used") or {}
    return HeldSquad(
        season=str(entry["season"]),
        decided_gameweek=int(entry["gameweek"]) - 1,
        squad_player_ids=tuple(ids),
        purchase_prices={p: prices[p] for p in ids},
        bank_tenths=int(entry["bank_tenths"]),
        free_transfers=int(entry["free_transfers"]),
        chips_used={str(name): tuple(int(w) for w in weeks) for name, weeks in chips.items()},
        squad_sell_value_tenths=int(entry["squad_sell_value_tenths"]),
    )


def add_device_plan_inputs(
    *,
    snapshot_root: Path,
    snapshot_id: str,
    handoff_path: Path,
    site_data_root: Path,
    verify: bool = False,
    out=sys.stdout,
) -> list[str]:
    """Write the two documents into the tree; return the relative paths written."""

    league_dir = site_data_root / "league"
    members_envelope = _read(league_dir / "members.json")
    members = members_envelope["payload"]
    stamp = str(members_envelope["generated_at_utc"])
    season, gameweek, league_id = (
        str(members["season"]),
        int(members["gameweek"]),
        int(members["league_id"]),
    )

    snapshot = read_snapshot(snapshot_root, snapshot_id)
    inputs = read_inputs(snapshot, season=season, gameweek=gameweek)
    handoff = read_projection_handoff(handoff_path)
    if handoff.source_snapshot_id != snapshot_id or int(handoff.gameweek) != gameweek:
        raise DevicePlanInputsError(
            f"The handoff is for capture {handoff.source_snapshot_id} gameweek {handoff.gameweek}, "
            f"not {snapshot_id} gameweek {gameweek}."
        )
    projection = project(inputs, in_season=handoff)
    rules = read_season_rules(snapshot, season=season)
    prices = {
        int(str(row["player_id"])): int(str(row["price_tenths"]))
        for _, row in inputs.players.iterrows()
    }

    written: list[str] = []
    entries = sorted((league_dir / "entries").glob("*.json"))
    for path in entries:
        envelope = _read(path)
        entry = envelope["payload"]
        if envelope.get("contract_version") != LEAGUE_VIEW_CONTRACT_VERSION:
            raise DevicePlanInputsError(f"{path.name} is not a league entry document.")
        if entry.get("source_snapshot_id") != snapshot_id:
            raise DevicePlanInputsError(
                f"{path.name} names capture {entry.get('source_snapshot_id')!r}, not {snapshot_id}."
            )
        if int(entry["gameweek"]) != gameweek or str(entry["season"]) != season:
            raise DevicePlanInputsError(f"{path.name} is for another deadline than members.json.")
        if envelope.get("generated_at_utc") != stamp:
            raise DevicePlanInputsError(
                f"{path.name} carries another publication stamp than members.json."
            )
        block = device_plan_entry(inputs, projection, _held_from_entry(entry, prices), rules)
        entry["device_plan"] = block
        _write(path, envelope)
        written.append(f"entries/{path.name}")
        print(
            f"  {path.name}: "
            + ("inputs written" if block else "no inputs, the live path would not plan"),
            file=out,
        )

    document = device_plan_table(inputs, projection, rules, league_id=league_id)
    _write(
        league_dir / DEVICE_PLAN_DOCUMENT,
        {
            "contract_version": LEAGUE_VIEW_CONTRACT_VERSION,
            "generated_at_utc": stamp,
            "source_kind": "live",
            "payload": document,
        },
    )
    written.append(DEVICE_PLAN_DOCUMENT)
    print(
        f"Wrote {DEVICE_PLAN_DOCUMENT} ({len(document['players'])} players) and {len(entries)} "
        f"entry blocks under stamp {stamp} for capture {snapshot_id}.",
        file=out,
    )
    if verify:
        _verify(league_dir, document, out)
    return written


def _verify(league_dir: Path, document: dict, out) -> None:
    """Rebuild every member's problem from the written documents: the published plan, or refuse."""

    rules = document["rules"]
    for path in sorted((league_dir / "entries").glob("*.json")):
        entry = _read(path)["payload"]
        block = entry.get("device_plan")
        advice_path = (
            league_dir / "advice" / str(entry["entry"]["entry_id"]) / "saf-puan" / "1.json"
        )
        if block is None or not advice_path.exists():
            print(f"  {path.name}: not verified (no inputs or no published plain plan)", file=out)
            continue
        published = _read(advice_path)["payload"]
        sell = {int(k): v for k, v in block["sell_tenths"].items()}
        players = document["players"]
        horizon = PlanningHorizon(
            pd.DataFrame(
                {
                    "gameweek": document["gameweek"],
                    "player_id": [p["id"] for p in players],
                    "name": [p["name"] for p in players],
                    "team_id": [p["team"] for p in players],
                    "position": [p["position"] for p in players],
                    "buy_price_tenths": [p["buy_tenths"] for p in players],
                    "sell_price_tenths": [sell.get(p["id"], p["buy_tenths"]) for p in players],
                    "expected_points": [p["expected_points"] for p in players],
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
            OptimizationConfig(
                solver_time_limit_seconds=300.0, solver_deterministic_time_limit=100.0
            ),
            TransferPlanningConfig(
                max_free_transfers=rules["max_free_transfers"],
                transfer_hit_cost_points=rules["hit_cost_scaled"] / rules["expected_points_scale"],
                hit_points_charged=rules["hit_points_charged"],
                banked_transfer_value_points=0.0,
                horizon_discount_factor=1.0,
                chip_holding_value_points={},
            ),
        )
        week = plan.weeks[0]
        same = (
            sorted(int(v) for v in week.transfers_in["player_id"])
            == sorted(m["player_in"]["player_id"] for m in published["moves"])
            and sorted(int(v) for v in week.transfers_out["player_id"])
            == sorted(m["player_out"]["player_id"] for m in published["moves"])
            and int(week.captain["player_id"]) == published["captain"]["player_id"]
            and sorted(int(v) for v in week.starting_xi["player_id"])
            == sorted(p["player_id"] for p in published["starting_xi"])
        )
        print(
            f"  {path.name}: {plan.solver_status.value}, "
            + ("same as published" if same else "DIFFERS"),
            file=out,
        )
        if not same:
            raise DevicePlanInputsError(
                f"{path.name}: the written inputs do not solve to the published plan."
            )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--snapshot-root", type=Path, required=True)
    parser.add_argument("--snapshot-id", required=True)
    parser.add_argument("--handoff", type=Path, required=True)
    parser.add_argument(
        "--site-data-root", type=Path, required=True, help="the candidate's data/ directory"
    )
    parser.add_argument(
        "--verify", action="store_true", help="solve every member from the written inputs"
    )
    arguments = parser.parse_args(argv)
    try:
        add_device_plan_inputs(
            snapshot_root=arguments.snapshot_root,
            snapshot_id=arguments.snapshot_id,
            handoff_path=arguments.handoff,
            site_data_root=arguments.site_data_root,
            verify=arguments.verify,
        )
    except (DevicePlanInputsError, EntryError, DataError, OSError, ValueError) as error:
        print(f"Refused: {error}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
