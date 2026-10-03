"""Write the device-plan parity fixture: synthetic instances with the server's own answers.

    python -m scripts.export_device_plan_fixture

The page's solver (``web/src/features/league/device/planModel.ts``) restates the server's
one-week model. This fixture is what holds the two together: every instance here is
solved by the repository's planner under the member planning policy, and the web test
solves the same instances with the device solver and requires the same answer. The
Python test ``tests/unit/test_device_plan_fixture.py`` requires the recorded answers to
still be the planner's, so a planner change that moves an answer fails there first and
is carried here by rerunning this script.

The table is synthetic and small, built from a fixed seed, so the fixture is a model
parity check and not a claim about any player. The ``chips`` instances play each chip the
game has on two of the fifteens, forced for the decided week as the member's chosen chip
is, with every total on the chip week's own basis and the gain against the member's
no-chip plan the way ``advice_chips`` measures it.
"""

from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any, Final

import pandas as pd
from scripts._experiment_cli import measurement_optimization_config

from squadopt.application.advice import _attributed_gains, _paired_by_position
from squadopt.application.advice_chips import chip_week_points
from squadopt.application.lineup_publication import (
    best_eleven_points,
    best_lineup_points_with_chip,
)
from squadopt.contracts.players import order_outfield_bench
from squadopt.live.transfers import MEMBER_PLANNING_POLICY
from squadopt.optimization import OptimizationConfig
from squadopt.optimization.coefficients import objective_coefficients, scale_expected_points
from squadopt.planning import (
    ChipAvailability,
    InitialSquadState,
    PlanningHorizon,
    TransferPlanningConfig,
    optimize_transfer_plan,
)

FIXTURE: Final = (
    Path(__file__).resolve().parents[1]
    / "web"
    / "src"
    / "fixtures"
    / "device-plan"
    / "instances.json"
)
SEED: Final = 20261003
MAX_FREE_TRANSFERS: Final = 5
GAMEWEEK: Final = 7
CHIPS: Final = ("wildcard", "freehit", "bboost", "3xc")
#: Which fifteens play each chip: the one that holds two free transfers and a little money,
#: and the weak one with money, whose rebuild under a Wildcard is a real rebuild.
CHIP_MEMBERS: Final = (2, 7)
CLUBS: Final = tuple(f"Club {k}" for k in range(1, 9))
SHAPE: Final = {"GK": 8, "DEF": 20, "MID": 20, "FWD": 12}
PRICE: Final = {"GK": (40, 55), "DEF": (40, 75), "MID": (45, 130), "FWD": (45, 125)}


def _policy_number(name: str) -> float:
    value = MEMBER_PLANNING_POLICY[name]
    assert isinstance(value, float)
    return value


def _table(rng: random.Random) -> pd.DataFrame:
    rows = []
    player_id = 100
    for position, count in SHAPE.items():
        low, high = PRICE[position]
        for _ in range(count):
            player_id += 1
            price = rng.randint(low, high)
            # Points loosely follow price, with noise, two decimals, a few zeros for the
            # unavailable.
            base = (price - low) / max(1, high - low) * 6.0 + rng.uniform(-1.0, 2.5)
            points = 0.0 if rng.random() < 0.08 else round(max(0.0, base), 2)
            rows.append(
                {
                    "gameweek": GAMEWEEK,
                    "player_id": player_id,
                    "name": f"Player {player_id}",
                    "team_id": CLUBS[rng.randrange(len(CLUBS))],
                    "position": position,
                    "buy_price_tenths": price,
                    "sell_price_tenths": price,
                    "expected_points": points,
                }
            )
    # Three players worth paying a hit for: a transfer beyond the free ones pays the
    # policy's caution margin only when the gain is larger than it.
    for offset, points in ((-1, 11.5), (-2, 12.0), (-3, 12.5)):
        rows[offset]["expected_points"] = points
    return pd.DataFrame(rows)


def _legal_fifteen(table: pd.DataFrame, rng: random.Random, *, weak: bool = False) -> list[int]:
    """A fifteen under the position quotas and the three-per-club rule, drawn at random.

    ``weak`` draws from the lower half of each position by points: a squad whose repair
    is worth paying for.
    """

    quota = {"GK": 2, "DEF": 5, "MID": 5, "FWD": 3}
    while True:
        chosen: list[int] = []
        clubs: dict[str, int] = {}
        for position, count in quota.items():
            rows = table.loc[table.position.eq(position)]
            if weak:
                rows = rows.sort_values("expected_points").head(len(rows) // 2)
            pool = rows.sample(frac=1, random_state=rng.randrange(1 << 30))
            for row in pool.itertuples(index=False):
                if count == 0:
                    break
                if clubs.get(str(row.team_id), 0) >= 3:
                    continue
                chosen.append(int(str(row.player_id)))
                clubs[str(row.team_id)] = clubs.get(str(row.team_id), 0) + 1
                count -= 1
            if count:
                break
        else:
            return sorted(chosen)


def _document(table: pd.DataFrame, settings: OptimizationConfig) -> dict[str, Any]:
    coefficients = objective_coefficients(table["expected_points"].tolist(), settings)
    return {
        "contract_version": "league_device_plan_v1",
        "league_id": 1,
        "season": "2026-27",
        "gameweek": GAMEWEEK,
        "source_snapshot_id": "synthetic-device-plan-fixture",
        "policy_id": "member_planning_policy_v2",
        "rules": {
            "squad_size": settings.squad_size,
            "starting_size": settings.starting_size,
            "squad_position_limits": dict(settings.squad_position_limits),
            "starting_position_min": dict(settings.starting_position_min),
            "starting_position_max": dict(settings.starting_position_max),
            "max_players_per_team": settings.max_players_per_team,
            "max_free_transfers": MAX_FREE_TRANSFERS,
            "hit_cost_scaled": scale_expected_points(
                _policy_number("transfer_hit_cost_points"),
                settings.expected_points_scale,
            ),
            "hit_points_charged": _policy_number("hit_points_charged"),
            "expected_points_scale": settings.expected_points_scale,
        },
        "players": [
            {
                "id": int(str(row.player_id)),
                "name": str(row.name),
                "short_name": str(row.name).rsplit(" ", 1)[-1],
                "team": str(row.team_id),
                "position": str(row.position),
                "buy_tenths": int(str(row.buy_price_tenths)),
                "expected_points": float(str(row.expected_points)),
                "coefficients": list(coefficients[index]),
            }
            for index, row in enumerate(table.itertuples(index=False))
        ],
    }


def _reference(
    table: pd.DataFrame,
    held: list[int],
    sell: dict[int, int],
    bank: int,
    free: int,
    settings: OptimizationConfig,
    chip: str | None = None,
) -> dict[str, Any]:
    horizon_table = table.copy()
    horizon_table["sell_price_tenths"] = [
        sell.get(int(player), int(price))
        for player, price in zip(table["player_id"], table["buy_price_tenths"], strict=True)
    ]
    transfer = TransferPlanningConfig(
        max_free_transfers=MAX_FREE_TRANSFERS,
        transfer_hit_cost_points=_policy_number("transfer_hit_cost_points"),
        hit_points_charged=_policy_number("hit_points_charged"),
        banked_transfer_value_points=0.0,
        horizon_discount_factor=1.0,
        chip_holding_value_points={},
    )
    # A chosen chip is forced for the decided week, as the member's chip advice forces it.
    chips = (
        None
        if chip is None
        else ChipAvailability(available={chip: frozenset({GAMEWEEK})}, forced={GAMEWEEK: chip})
    )
    plan = optimize_transfer_plan(
        PlanningHorizon(horizon_table),
        InitialSquadState(tuple(held), bank_tenths=bank, free_transfers=free),
        settings,
        transfer,
        chips=chips,
    )
    if plan.solver_status.value != "OPTIMAL":
        raise RuntimeError(f"The reference solve was not proved: {plan.solver_status.value}.")
    week = plan.weeks[0]
    if week.chip != chip:
        raise RuntimeError(f"The forced {chip!r} plan came back playing {week.chip!r}.")
    captain = int(week.captain["player_id"])
    eligible = week.starting_xi.loc[week.starting_xi.player_id.ne(captain)]
    vice = int(
        eligible.sort_values(["expected_points", "player_id"], ascending=[False, True])
        .iloc[0]
        .player_id
    )
    goalkeeper = [int(v) for v in week.bench.loc[week.bench.position.eq("GK"), "player_id"]]
    outfield = order_outfield_bench(week.bench.loc[week.bench.position.ne("GK")])
    bench = [*goalkeeper, *(int(v) for v in outfield["player_id"])]
    lookup = {
        int(str(row.player_id)): (str(row.position), float(str(row.expected_points)))
        for row in table.itertuples(index=False)
    }
    squad = sorted(int(v) for v in week.selected_squad["player_id"])

    # What a fifteen is worth on the basis the week scores on: the eleven with the captain
    # doubled, or the chip week's own reading of it.
    def value_of(players: list[int]) -> float | None:
        if chip is None:
            return best_eleven_points(lookup[p] for p in players)
        return best_lineup_points_with_chip((lookup[p] for p in players), chip)

    plan_points = value_of(squad)
    hold_points = value_of(held)
    assert plan_points is not None and hold_points is not None
    assert plan.objective_value is not None
    if chip is not None and abs(chip_week_points(week) - plan_points) > 1e-6:
        raise RuntimeError(
            f"The {chip!r} week counts {chip_week_points(week)!r}; its fifteen is worth "
            f"{plan_points!r} on the chip basis."
        )
    # The move rows as the advice publishes them: paired by position in id order, each
    # row's gain the published basis's move when the swap is applied in row order.
    rows = {
        int(str(row.player_id)): row
        for row in table.rename(columns={"team_id": "team"}).itertuples(index=False)
    }
    series = {player: pd.Series({"position": row.position}) for player, row in rows.items()}
    outs = sorted(int(v) for v in week.transfers_out["player_id"])
    ins = sorted(int(v) for v in week.transfers_in["player_id"])
    paired = _paired_by_position(outs, ins, by_id=series, pool_by_id=series)
    gains = (
        _attributed_gains(paired, held=held, lookup=lookup, expected_total=plan_points)
        if chip is None
        else _gains_on_chip_basis(paired, held, value_of, plan_points)
    )
    moves = [
        {"out": out, "in": arriving, "gain": None if gains is None else gains[index]}
        for index, (out, arriving) in enumerate(paired)
    ]
    return {
        "solver_status": plan.solver_status.value,
        "objective_value": float(plan.objective_value),
        "squad": squad,
        "starting_xi": sorted(int(v) for v in week.starting_xi["player_id"]),
        "captain": captain,
        "vice_captain": vice,
        "bench": bench,
        "transfers_in": sorted(int(v) for v in week.transfers_in["player_id"]),
        "transfers_out": sorted(int(v) for v in week.transfers_out["player_id"]),
        "transfer_hit_points": float(week.transfer_hit_points),
        "expected_own_points": plan_points,
        "hold_points": hold_points,
        "moves": moves,
        "expected_gain_vs_hold": None if gains is None else sum(gains),
    }


def _gains_on_chip_basis(
    paired: list[tuple[int | None, int | None]],
    held: list[int],
    value_of: Any,
    expected_total: float,
) -> list[float] | None:
    """The move rows on the chip week's basis, as ``advice_chips._rows_on_chip_basis``
    walks them: the rows in order, each the change once that swap is added to the ones
    above it, from the held fifteen valued with the same chip played. ``None`` when the
    chain does not end at the eleven the plan fields."""

    squad = list(held)
    previous = value_of(squad)
    if previous is None:
        return None
    gains: list[float] = []
    for out, arriving in paired:
        if out is None or arriving is None or out not in squad or arriving in squad:
            return None
        squad[squad.index(out)] = arriving
        value = value_of(squad)
        if value is None:
            return None
        gains.append(value - previous)
        previous = value
    if abs(previous - expected_total) > 1e-6:
        return None
    return gains


def build_fixture() -> dict[str, Any]:
    rng = random.Random(SEED)
    # The limits of a run that writes a committed record: deterministic time binds, not the
    # machine's clock. The coefficients and the rules do not depend on the limits.
    settings = measurement_optimization_config()
    table = _table(rng)
    document = _document(table, settings)
    members: list[dict[str, Any]] = []
    # Free transfers across the cap, banks from empty to generous, and one fifteen whose
    # sale prices sit below the buy prices (a risen squad, sold at half the rise).
    for entry_id, (free, bank, risen, weak) in enumerate(
        [
            (1, 0, False, False),
            (2, 15, False, False),
            (5, 100, False, False),
            (1, 3, True, False),
            (3, 25, True, False),
            (1, 0, False, False),
            # A weak fifteen with money: the plan pays for transfers beyond the free ones.
            (1, 250, False, True),
            (2, 400, False, True),
        ],
        start=1,
    ):
        held = _legal_fifteen(table, rng, weak=weak)
        prices = dict(
            zip(
                (int(v) for v in table["player_id"]),
                (int(v) for v in table["buy_price_tenths"]),
                strict=True,
            )
        )
        sell = {
            p: (prices[p] - rng.randint(1, 4) if risen and rng.random() < 0.5 else prices[p])
            for p in held
        }
        members.append(
            {
                "entry_id": entry_id,
                "entry": {
                    "held": held,
                    "bank_tenths": bank,
                    "free_transfers": free,
                    "sell_tenths": {str(p): v for p, v in sell.items()},
                },
                "reference": _reference(table, held, sell, bank, free, settings),
            }
        )
    chips: list[dict[str, Any]] = []
    for member in members:
        if member["entry_id"] not in CHIP_MEMBERS:
            continue
        entry = member["entry"]
        plain = member["reference"]
        for chip in CHIPS:
            reference = _reference(
                table,
                list(entry["held"]),
                {int(k): int(v) for k, v in entry["sell_tenths"].items()},
                int(entry["bank_tenths"]),
                int(entry["free_transfers"]),
                settings,
                chip=chip,
            )
            # The chip week net of its hits above the member's own no-chip plan net of
            # its hits: ``advice_chips``'s gain_vs_no_chip.
            reference["gain_vs_no_chip"] = (
                reference["expected_own_points"] - reference["transfer_hit_points"]
            ) - (plain["expected_own_points"] - plain["transfer_hit_points"])
            chips.append({"entry_id": member["entry_id"], "chip": chip, "reference": reference})
    return {
        "note": "Synthetic device-plan parity instances; scripts/export_device_plan_fixture.py.",
        "seed": SEED,
        "document": document,
        "members": members,
        "chips": chips,
    }


def main() -> int:
    fixture = build_fixture()
    FIXTURE.parent.mkdir(parents=True, exist_ok=True)
    FIXTURE.write_text(json.dumps(fixture, indent=1), encoding="utf-8", newline="\n")
    print(
        f"Wrote {FIXTURE} with {len(fixture['members'])} instances and "
        f"{len(fixture['chips'])} chip instances."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
