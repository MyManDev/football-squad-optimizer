"""Write the device-plan parity fixture: synthetic instances with the server's own answers.

    python -m scripts.export_device_plan_fixture

The page's solver (``web/src/features/league/device/solve/week.ts`` over ``lp/``) restates
the server's one-week model. This fixture is what holds the two together: every instance here is
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

The ``rivals`` block is a second, smaller world: the unit tests' three-capture world
(``tests/unit/test_live_transfers.build_world``), whose device document the real producer
writes and whose answers the real advice service gives (``advise_entry`` under each rival
strategy against each rival). The device restates that service's rule, and this is what
holds it to it.
"""

from __future__ import annotations

import json
import random
import tempfile
from copy import deepcopy
from pathlib import Path
from typing import Any, Final

import pandas as pd
from scripts._experiment_cli import measurement_optimization_config

from squadopt.application.advice import (
    AdviseEntryRequest,
    _attributed_gains,
    _paired_by_position,
    advise_entry,
    advise_with_top100,
)
from squadopt.application.advice_chips import chip_week_points
from squadopt.application.device_plan import device_plan_entry, device_plan_table
from squadopt.application.entries import EntryError, held_squad_from_picks
from squadopt.application.lineup_publication import (
    best_eleven_points,
    best_lineup_points_with_chip,
)
from squadopt.application.top100_weight import Top100Counts, weighted_projection
from squadopt.contracts.players import order_outfield_bench
from squadopt.contracts.preferences import DecisionPreferences
from squadopt.live import Projection
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
RIVAL_STRATEGIES: Final = ("ortak-koru", "fark-yarat")
#: The Top 100 weights the device is held to, on the same world and members.
TOP100_CASE_WEIGHTS: Final = (20, 50)
RIVAL_LEAGUE: Final = 352490
#: The test world's members: the repair squad (four from two clubs, an injured player) and
#: the discretionary squad whose transfers are a choice. Codes are the world's own.
RIVAL_MEMBERS: Final = {
    101: (1001, 1002, 1004, 1005, 1006, 1007, 1008, 1012, 1013, 1014, 1015, 1016, 1020, 1021, 1022),
    102: (1001, 1002, 1004, 1006, 1007, 1008, 1009, 1012, 1013, 1014, 1015, 1016, 1022, 1023, 1024),
}
#: The rivals: an eleven sharing six with the repair squad (the differential band is one
#: swap away), and one holding the strongest players, which a core band has to buy into.
RIVAL_ELEVENS: Final = {
    202: (1004, 1005, 1006, 1012, 1013, 1014, 1003, 1009, 1017, 1018, 1019, 1010, 1011, 1023, 1024),
    203: (1003, 1002, 1009, 1010, 1011, 1017, 1018, 1019, 1023, 1024, 1016, 1001, 1004, 1012, 1020),
}
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
    preferences: DecisionPreferences | None = None,
    top100_counts: dict[int, int] | None = None,
    top100_weight: int = 0,
) -> dict[str, Any]:
    horizon_table = table.copy()
    if top100_weight:
        horizon_table = weighted_projection(
            Projection(horizon_table, (), {}), top100_counts or {}, top100_weight
        ).table
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
        preferences=preferences,
    )
    if preferences is not None and plan.solver_status.value == "INFEASIBLE":
        return {"refused": True, "solver_status": "INFEASIBLE"}
    if plan.solver_status.value != "OPTIMAL":
        raise RuntimeError(f"The reference solve was not proved: {plan.solver_status.value}.")
    week = plan.weeks[0]
    if week.chip != chip:
        raise RuntimeError(f"The forced {chip!r} plan came back playing {week.chip!r}.")
    captain = int(week.captain["player_id"])
    eligible = week.starting_xi.loc[week.starting_xi.player_id.ne(captain)]
    if top100_weight:
        eligible = eligible.copy()
        eligible["expected_points"] = eligible.player_id.map(
            table.set_index("player_id").expected_points
        )
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


def _rival_reference(payload: dict[str, Any]) -> dict[str, Any]:
    """What the device is held to from a rival strategy's published answer."""

    def ids(rows: list[dict[str, Any]]) -> list[int]:
        return sorted(int(row["player_id"]) for row in rows)

    moves = payload["moves"]
    alternative = payload.get("alternative_plan")
    return {
        "solver_status": payload["solver_status"],
        "control_solver_status": payload["control_solver_status"],
        "starting_xi": ids(payload["starting_xi"]),
        "captain": int(payload["captain"]["player_id"]),
        "vice_captain": int(payload["vice_captain"]["player_id"]),
        "bench": [int(row["player_id"]) for row in payload["bench"]],
        "transfers_in": sorted(int(m["player_in"]["player_id"]) for m in moves),
        "transfers_out": sorted(int(m["player_out"]["player_id"]) for m in moves),
        "moves": [
            {
                "out": int(m["player_out"]["player_id"]),
                "in": int(m["player_in"]["player_id"]),
                "gain": m["expected_points_delta"],
            }
            for m in moves
        ],
        "transfer_hit_points": float(payload["transfer_hit_points"]),
        "expected_own_points": float(payload["expected_own_points"]),
        "expected_gain_vs_hold": payload["expected_gain_vs_hold"],
        "expected_points_cost": float(payload["expected_points_cost"]),
        "expected_points_cost_ceiling": payload.get("expected_points_cost_ceiling"),
        "overlap_count": int(payload["overlap_count"]),
        "transfer_cap": int(payload["transfer_cap"]),
        "overlap_target": int(payload["overlap_target"]),
        "overlap_applied": int(payload["overlap_applied"]),
        "plan_kind": payload["plan_kind"],
        "alternative_plan": None
        if alternative is None
        else {
            "kind": alternative["kind"],
            "overlap_applied": int(alternative["overlap_applied"]),
            "transfer_hit_points": alternative["transfer_hit_points"],
            "expected_points_cost": float(alternative["expected_points_cost"]),
            "expected_points_cost_ceiling": alternative.get("expected_points_cost_ceiling"),
        },
        "expected_gap_vs_rival": float(payload["expected_gap_vs_rival"]),
        "captain_agreement": bool(payload["captain_agreement"]),
    }


def _top100_counts(codes: list[int], picks_snapshot_id: str) -> Top100Counts:
    """Synthetic Top 100 start counts for the world: a spread over the cohort, a few zeros.

    The spread is what matters, not the numbers: some players the cohort starts almost to
    a man, some nobody starts, so a weight moves the choice without moving every player
    the same way.
    """

    counts = {code: (code * 37) % 101 for code in codes}
    for code in codes[::5]:
        counts[code] = 0
    # Players the cohort backs almost to a man, outside the pure-points plan, so a weight
    # that is worth anything moves a decision; the plan's own star stays unbacked.
    counts.update({1010: 100, 1017: 100, 1023: 95, 1024: 0})
    return Top100Counts(
        counts={code: count for code, count in counts.items() if count > 0},
        table_sha256="synthetic-top100-counts",
        cohort_snapshot_id="synthetic-cohort",
        picks_snapshot_id=picks_snapshot_id,
        picks_gameweek=1,
    )


def _top100_reference(payload: dict[str, Any]) -> dict[str, Any]:
    """What the device is held to from a Top 100 document."""

    moves = payload["moves"]
    return {
        "solver_status": payload["solver_status"],
        "control_solver_status": payload["control_solver_status"],
        "starting_xi": sorted(int(row["player_id"]) for row in payload["starting_xi"]),
        "captain": int(payload["captain"]["player_id"]),
        "vice_captain": int(payload["vice_captain"]["player_id"]),
        "bench": [int(row["player_id"]) for row in payload["bench"]],
        "transfers_in": sorted(int(m["player_in"]["player_id"]) for m in moves),
        "transfers_out": sorted(int(m["player_out"]["player_id"]) for m in moves),
        "moves": [
            {
                "out": int(m["player_out"]["player_id"]),
                "in": int(m["player_in"]["player_id"]),
                "gain": m["expected_points_delta"],
                "reason": m["reason_code"],
            }
            for m in moves
        ],
        "transfer_hit_points": float(payload["transfer_hit_points"]),
        "expected_own_points": float(payload["expected_own_points"]),
        "expected_gain_vs_hold": payload["expected_gain_vs_hold"],
        "expected_points_cost": float(payload["expected_points_cost"]),
        "expected_points_cost_ceiling": payload.get("expected_points_cost_ceiling"),
        "changed": bool(payload["top100"]["changed"]),
    }


def build_rival_fixture() -> dict[str, Any]:
    """The test world's device document, its members' blocks, and the service's answers."""

    # The test modules are imported here, not at the top: they pull in pytest, which the
    # fixture script needs for the world and nothing else.
    from tests.unit.test_league_views import _member_picks, _Provider
    from tests.unit.test_live_transfers import SEASON, _handoff, build_world

    from squadopt.data.snapshots import read_snapshot
    from squadopt.live import read_inputs, read_season_rules
    from squadopt.live.recommendation import project, read_projection_handoff

    with tempfile.TemporaryDirectory() as temporary:
        world = build_world(Path(temporary))
        snapshot = read_snapshot(world["snapshot_root"], world["gw2_id"])
        inputs = read_inputs(snapshot, season=SEASON, gameweek=2)
        # The world's own projection is coarse (2.0, 2.5, 3.0), and two plans with the same
        # points, the same hits and the same rank sums are told apart by nothing in either
        # solver's tie-break; a parity fixture needs every player on his own number. Each
        # code's points are nudged by a distinct hundredth, the world's order kept.
        points = {
            code: round(2.0 + (code % 3) * 0.5 + (code - 1000) / 100, 2)
            for code in range(1001, 1025)
        }
        points[1024] = 9.24
        points[1005] = 0.55
        handoff = read_projection_handoff(_handoff(world, points=points))
        projection = project(inputs, in_season=handoff)
        rules = read_season_rules(snapshot, season=SEASON)
        picks = {
            entry_id: _member_picks(world, entry_id, list(codes))
            for entry_id, codes in (*RIVAL_MEMBERS.items(), *RIVAL_ELEVENS.items())
        }
    provider = _Provider(picks)
    prices = {
        int(str(row["player_id"])): int(str(row["price_tenths"]))
        for _, row in inputs.players.iterrows()
    }
    counts = _top100_counts(
        sorted(int(str(v)) for v in inputs.players["player_id"]), world["gw1_id"]
    )
    document = device_plan_table(inputs, projection, rules, league_id=RIVAL_LEAGUE, top100=counts)
    members = {}
    for entry_id in RIVAL_MEMBERS:
        held = held_squad_from_picks(picks[entry_id], current_prices=prices)
        block = device_plan_entry(inputs, projection, held, rules, top100=counts)
        if block is None:
            raise RuntimeError(f"The producer writes no inputs for member {entry_id}.")
        members[str(entry_id)] = block
    rivals = {
        str(entry_id): {
            "entry_id": entry_id,
            "starting_xi": sorted(picks[entry_id].starting_xi),
            "captain": int(picks[entry_id].captain),
        }
        for entry_id in RIVAL_ELEVENS
    }
    cases = []
    for entry_id in RIVAL_MEMBERS:
        for rival_id in RIVAL_ELEVENS:
            for strategy in RIVAL_STRATEGIES:
                request = AdviseEntryRequest(
                    season=str(inputs.season),
                    gameweek=int(inputs.deadline.gameweek),
                    league_id=RIVAL_LEAGUE,
                    entry_id=entry_id,
                    strategy=strategy,
                    rival_entry_id=rival_id,
                )
                try:
                    payload = advise_entry(
                        request,
                        provider=provider,
                        inputs=inputs,
                        projection=projection,
                        rules=rules,
                    )
                except EntryError as error:
                    # A band the squad cannot meet at any level is the service's own
                    # refusal, and the device must refuse the same case.
                    reference: dict[str, Any] = {"refused": True, "reason": str(error)}
                else:
                    reference = {"refused": False, **_rival_reference(payload)}
                cases.append(
                    {
                        "entry_id": entry_id,
                        "rival_entry_id": rival_id,
                        "strategy": strategy,
                        "reference": reference,
                    }
                )
    top100_cases = []
    for entry_id in RIVAL_MEMBERS:
        for weight in TOP100_CASE_WEIGHTS:
            advice = advise_with_top100(
                AdviseEntryRequest(
                    season=str(inputs.season),
                    gameweek=int(inputs.deadline.gameweek),
                    league_id=RIVAL_LEAGUE,
                    entry_id=entry_id,
                ),
                weight=weight,
                counts=counts,
                provider=provider,
                inputs=inputs,
                projection=projection,
                rules=rules,
            )
            top100_cases.append(
                {
                    "entry_id": entry_id,
                    "weight": weight,
                    "reference": _top100_reference(dict(advice.payload)),
                }
            )
    return {
        "document": document,
        "members": members,
        "rivals": rivals,
        "cases": cases,
        "top100_cases": top100_cases,
    }


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
        "rivals": build_rival_fixture(),
        "preferences": build_preference_fixture(table, document, members, settings),
    }


def build_preference_fixture(
    table: pd.DataFrame,
    document: dict[str, Any],
    members: list[dict[str, Any]],
    settings: OptimizationConfig,
) -> dict[str, Any]:
    """The window-one planner reference for the device's explicit preferences."""
    member = next(row for row in members if row["entry_id"] == 2)
    entry = member["entry"]
    held = list(entry["held"])
    not_held = min(set(table.player_id) - set(held))
    specifications = [
        ("keep-held", DecisionPreferences(keep_players=(held[0],)), None, 2, 0),
        ("avoid-held", DecisionPreferences(avoid_players=(held[0],)), None, 2, 0),
        ("avoid-not-held", DecisionPreferences(avoid_players=(int(not_held),)), None, 2, 0),
        ("no-hits-zero-free", DecisionPreferences(no_hits=True), None, 0, 0),
        ("no-hits-wildcard", DecisionPreferences(no_hits=True), "wildcard", 0, 0),
        ("no-hits-freehit", DecisionPreferences(no_hits=True), "freehit", 0, 0),
        ("save-chips", DecisionPreferences(save_chips=True), None, 2, 0),
        ("keep-freehit", DecisionPreferences(keep_players=(held[0],)), "freehit", 2, 0),
        ("avoid-top100", DecisionPreferences(avoid_players=(held[0],)), None, 2, 20),
        (
            "infeasible-no-hits-sale",
            DecisionPreferences(avoid_players=(held[0],), no_hits=True),
            None,
            0,
            0,
        ),
    ]
    counts = {int(code): int(code) * 37 % 101 for code in table.player_id}
    weighted = weighted_projection(Projection(table, (), {}), counts, 20).table
    weighted_points = weighted.set_index("player_id").expected_points.to_dict()
    preference_document = deepcopy(document)
    preference_document["rules"]["top100"] = {"weights": [20], "cohort_size": 100}
    for player in preference_document["players"]:
        player["top100_count"] = counts[player["id"]]
        player["top100_scaled"] = {
            "20": scale_expected_points(
                weighted_points[player["id"]], settings.expected_points_scale
            )
        }
    cases = []
    for name, preferences, chip, free, weight in specifications:
        preferences.validate_selection("saf-puan", False, chip)
        selected_entry = {**deepcopy(entry), "free_transfers": free, "top100_weights": [20]}
        reference = _reference(
            table,
            held,
            {int(k): int(v) for k, v in entry["sell_tenths"].items()},
            int(entry["bank_tenths"]),
            free,
            settings,
            chip=chip,
            preferences=preferences,
            top100_counts=counts,
            top100_weight=weight,
        )
        cases.append(
            {
                "name": name,
                "entry_id": member["entry_id"],
                "entry": selected_entry,
                "preferences": preferences.payload(),
                "chip": chip,
                "top100_weight": weight,
                "reference": {"refused": False, **reference},
            }
        )
    return {"document": preference_document, "cases": cases}


def main() -> int:
    fixture = build_fixture()
    FIXTURE.parent.mkdir(parents=True, exist_ok=True)
    FIXTURE.write_text(json.dumps(fixture, indent=1), encoding="utf-8", newline="\n")
    print(
        f"Wrote {FIXTURE} with {len(fixture['members'])} instances, "
        f"{len(fixture['chips'])} chip instances and "
        f"{len(fixture['rivals']['cases'])} rival strategy cases and "
        f"{len(fixture['rivals']['top100_cases'])} Top 100 cases."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
