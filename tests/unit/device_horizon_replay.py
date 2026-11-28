"""Replay a published live pool using its same-capture public calendar.

No archive, member endpoint, server, source-file write or solve is involved. This is a
numeric reconstruction using the server's existing calendar helper, not the original
projection handoff or its provenance fingerprint. Raw expected_points are mandatory;
integer coefficients must never be inverted to manufacture a base forecast.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
from collections import Counter
from collections.abc import Mapping
from decimal import Decimal
from pathlib import Path
from typing import Any

import pandas as pd

from squadopt.contracts.players import sort_players_by_id
from squadopt.live.horizon import (
    FIXTURE_SCALING_RULE_VERSION,
    _fixture_counts_by_team_code,
    _gameweek_rows,
)
from squadopt.live.rules import SeasonRules
from squadopt.live.transfers import member_window_policy
from squadopt.optimization import OptimizationConfig
from squadopt.optimization.coefficients import objective_coefficients, round_half_up

REPLAY_CONTRACT = "published_device_calendar_replay_v1"
LIVE_SEASON = "2026-27"


class PublishedHorizonReplayError(ValueError):
    """The public inputs cannot establish the requested numeric problem."""


def _payload(envelope: Mapping[str, Any]) -> Mapping[str, Any]:
    value = envelope.get("payload", envelope)
    if not isinstance(value, Mapping):
        raise PublishedHorizonReplayError("The published payload is not an object.")
    return value


def replay_published_weeks(
    table: Mapping[str, Any],
    fixtures: Mapping[str, Any],
    *,
    season: str,
    weeks: int,
) -> list[dict[str, Any]]:
    """Return raw points and exact coefficients from the unchanged server helper.

    The public calendar preserves every scheduled fixture's event, home/away club and
    capture. Seasonal club ids are only local join tokens here. Both sides of the join
    are built from the same public club name/id pairs; the returned team names remain
    the pool's names. No claim is made about the unexposed persistent club-code ids.
    """

    document, calendar = _payload(table), _payload(fixtures)
    if (
        season != LIVE_SEASON
        or document.get("season") != season
        or calendar.get("season") != season
    ):
        raise PublishedHorizonReplayError("Only explicitly named live 2026-27 inputs are allowed.")
    if document.get("source_snapshot_id") != calendar.get("source_snapshot_id"):
        raise PublishedHorizonReplayError("Pool and calendar belong to different captures.")
    if isinstance(weeks, bool) or not 1 <= weeks <= 5:
        raise PublishedHorizonReplayError("Replay length must be between one and five weeks.")
    first = int(document["gameweek"])
    targets = tuple(range(first, first + weeks))
    published = {int(week["gameweek"]) for week in calendar["gameweeks"]}
    if not set(targets).issubset(published):
        raise PublishedHorizonReplayError("The calendar does not carry every requested week.")

    clubs: dict[str, int] = {}
    names: dict[int, str] = {}
    counts: Counter[tuple[int, int]] = Counter()
    homes: Counter[tuple[int, int]] = Counter()
    seen: set[int] = set()
    for week in calendar["gameweeks"]:
        gameweek = int(week["gameweek"])
        for fixture in week["fixtures"]:
            fixture_id = int(fixture["fixture_id"])
            if fixture_id in seen:
                raise PublishedHorizonReplayError("A fixture is repeated in the calendar.")
            seen.add(fixture_id)
            for side in ("home", "away"):
                club = fixture[side]
                name, identifier = str(club["name"]), int(club["team_id"])
                if (
                    clubs.setdefault(name, identifier) != identifier
                    or names.setdefault(identifier, name) != name
                ):
                    raise PublishedHorizonReplayError(
                        "The calendar's club identity is inconsistent."
                    )
                counts[gameweek, identifier] += 1
                homes[gameweek, identifier] += int(side == "home")

    settings = OptimizationConfig()
    if document["rules"]["expected_points_scale"] != settings.expected_points_scale:
        raise PublishedHorizonReplayError("The pool uses a different coefficient scale.")
    players = document["players"]
    if not players or any(
        isinstance(player.get("expected_points"), bool)
        or not isinstance(player.get("expected_points"), int | float)
        or not math.isfinite(player["expected_points"])
        or player["expected_points"] < 0
        for player in players
    ):
        raise PublishedHorizonReplayError("Finite nonnegative raw expected_points are required.")
    coefficients = objective_coefficients(
        [player["expected_points"] for player in players], settings
    )
    if any(
        list(row) != player["coefficients"]
        for player, row in zip(players, coefficients, strict=True)
    ):
        raise PublishedHorizonReplayError(
            "The raw H1 points do not reproduce the published coefficients."
        )
    if len({int(player["id"]) for player in players}) != len(players):
        raise PublishedHorizonReplayError("The pool repeats a player.")
    if any(player["team"] not in clubs for player in players):
        raise PublishedHorizonReplayError("A pool club is absent from the same-capture calendar.")
    base = sort_players_by_id(
        pd.DataFrame(
            {
                "player_id": int(player["id"]),
                "name": player["name"],
                "team_id": player["team"],
                "team_code": clubs[player["team"]],
                "position": player["position"],
                "price_tenths": int(player["buy_tenths"]),
                "expected_points": float(player["expected_points"]),
            }
            for player in players
        )
    )
    schedule = pd.DataFrame(
        {
            "gameweek": gameweek,
            "team_id": club,
            "fixture_count": count,
            "home_fixture_count": homes[gameweek, club],
        }
        for (gameweek, club), count in sorted(counts.items())
    )
    decision_counts = _fixture_counts_by_team_code(schedule, first)
    result: list[dict[str, Any]] = []
    for gameweek in targets:
        rows = _gameweek_rows(
            base,
            schedule,
            gameweek,
            preserve_expected_points=gameweek == first,
            decision_fixture_counts=decision_counts,
        )
        scaled = objective_coefficients(rows.expected_points.tolist(), settings)
        result.append(
            {
                "gameweek": gameweek,
                "players": [
                    {
                        "id": int(str(row.player_id)),
                        "buy_tenths": int(str(row.price_tenths)),
                        "expected_points": float(str(row.expected_points)),
                        "coefficients": list(scaled[index]),
                    }
                    for index, row in enumerate(rows.itertuples(index=False))
                ],
            }
        )
    return result


def benchmark_problem(
    table: Mapping[str, Any], calendar: Mapping[str, Any], rules: SeasonRules
) -> dict[str, Any]:
    """Build only an in-memory diagnostic problem, without claiming original provenance.

    Season rules may be verified rule metadata from another live-season capture. Every
    overlapping published constraint is checked. The synthetic holdings buy and sell at
    the frozen current price, so an acquisition's sell-on fee cannot change its price.
    Original projection/rules fingerprints remain unknown in the measurement metadata.
    """
    document = copy.deepcopy(dict(_payload(table)))
    if rules.season != LIVE_SEASON:
        raise PublishedHorizonReplayError("Only live-season rule metadata is allowed.")
    transfers = rules.transfers
    checks = {
        "squad_size": transfers.squad_size,
        "starting_size": transfers.starting_size,
        "max_players_per_team": transfers.team_limit,
        "max_free_transfers": transfers.max_free_transfers,
        "transfers_cap": transfers.transfers_cap,
    }
    if any(
        document["rules"][key] != value for key, value in checks.items() if key in document["rules"]
    ):
        raise PublishedHorizonReplayError("Rule metadata conflicts with published constraints.")
    policy = member_window_policy(rules, gameweek=document["gameweek"], transfer_cap=1, weeks=5)
    settings = OptimizationConfig()
    if document["rules"]["hit_cost_scaled"] != round_half_up(
        Decimal(str(policy.transfer_hit_cost_points)) * settings.expected_points_scale
    ):
        raise PublishedHorizonReplayError("Published hit cost conflicts with the window policy.")
    weeks = replay_published_weeks(document, calendar, season=LIVE_SEASON, weeks=5)
    for offset, week in enumerate(weeks):
        week["discount_weight"] = round_half_up(
            Decimal(str(policy.horizon_discount_factor)) ** offset * policy.objective_weight_scale
        )
    document["horizon"] = {
        "contract_version": "league_device_horizon_v1",
        "windows": [3, 5],
        "rules": {
            "max_transfers_per_gameweek": policy.max_transfers_per_gameweek,
            "free_transfer_accrual": policy.free_transfer_accrual,
            "bench_weight": settings.bench_weight,
            "objective_weight_scale": policy.objective_weight_scale,
            "horizon_discount_factor": policy.horizon_discount_factor,
            "banked_transfer_value_scaled": 0,
            "acquisition_sell_on_fee": transfers.sell_on_fee,
        },
        "weeks": weeks,
    }
    return {"document": document, "members": synthetic_members(document, transfers.budget_tenths)}


def synthetic_squad_path(document: Mapping[str, Any], budget: int) -> list[list[int]]:
    """Reproducible legal squad path; no endpoint or solve timing is used.

    Start with the cheapest eligible player of each required position, respecting club
    caps. Then apply the largest positive raw-points upgrade that preserves every rule.
    The cheap, middle and final squads are deliberately different starting states. This
    is a roster constructor, not an optimum reference for any horizon solve.
    """
    players, rules = document["players"], document["rules"]
    by_id = {player["id"]: player for player in players}
    held: list[int] = []
    clubs: Counter[str] = Counter()
    for position, quota in rules["squad_position_limits"].items():
        candidates = sorted(
            (p for p in players if p["position"] == position),
            key=lambda p: (p["buy_tenths"], p["id"]),
        )
        for _ in range(quota):
            eligible = [
                p
                for p in candidates
                if p["id"] not in held and clubs[p["team"]] < rules["max_players_per_team"]
            ]
            if not eligible:
                raise PublishedHorizonReplayError("Cannot construct a legal synthetic squad.")
            player = eligible[0]
            held.append(player["id"])
            clubs[player["team"]] += 1
    trace = [sorted(held)]
    while True:
        cost = sum(by_id[identifier]["buy_tenths"] for identifier in held)
        choices = []
        for outgoing in (by_id[identifier] for identifier in held):
            for incoming in players:
                gain = incoming["expected_points"] - outgoing["expected_points"]
                if (
                    incoming["position"] != outgoing["position"]
                    or incoming["id"] in held
                    or gain <= 0
                    or cost - outgoing["buy_tenths"] + incoming["buy_tenths"] > budget
                    or clubs[incoming["team"]] - int(incoming["team"] == outgoing["team"])
                    >= rules["max_players_per_team"]
                ):
                    continue
                choices.append((gain, -incoming["id"], -outgoing["id"]))
        if not choices:
            break
        _, negative_in, negative_out = max(choices)
        incoming, outgoing = by_id[-negative_in], by_id[-negative_out]
        held.remove(outgoing["id"])
        held.append(incoming["id"])
        clubs[outgoing["team"]] -= 1
        clubs[incoming["team"]] += 1
        trace.append(sorted(held))
    if len(trace) < 3:
        raise PublishedHorizonReplayError("The pool cannot produce three different squad shapes.")
    return trace


def synthetic_members(document: Mapping[str, Any], budget: int) -> list[dict[str, Any]]:
    """The original three-member cohort, unchanged for historical replay hashes."""
    trace = synthetic_squad_path(document, budget)
    by_id = {player["id"]: player for player in document["players"]}
    members = []
    for free, roster in zip((0, 1, 5), (trace[0], trace[len(trace) // 2], trace[-1]), strict=True):
        bank = budget - sum(by_id[identifier]["buy_tenths"] for identifier in roster)
        if bank < 0:
            raise PublishedHorizonReplayError("Synthetic squad exceeds the season budget.")
        members.append(
            {
                "member": f"synthetic-ft{free}",
                "entry": {
                    "held": roster,
                    "bank_tenths": bank,
                    "free_transfers": free,
                    "sell_tenths": {
                        str(identifier): by_id[identifier]["buy_tenths"] for identifier in roster
                    },
                    "horizon": {"windows": [3, 5]},
                },
            }
        )
    return members


def five_shape_members(
    document: Mapping[str, Any], budget: int, free_transfers: int
) -> list[dict[str, Any]]:
    """Five fixed structural quantiles, selected before any horizon solve runs.

    Deduplicate the roster constructor's path by (bank, club spread), then take
    its endpoints and quarter points. No time/answer/admission result is an input.
    The same five squads are used for every requested FT group and both windows.
    """
    by_id = {player["id"]: player for player in document["players"]}
    trace = synthetic_squad_path(document, budget)
    shapes = []
    seen = set()
    for roster in trace:
        bank = budget - sum(by_id[identifier]["buy_tenths"] for identifier in roster)
        clubs = Counter(by_id[identifier]["team"] for identifier in roster)
        shape = (bank, tuple(sorted(clubs.values())))
        if shape not in seen:
            shapes.append((roster, bank))
            seen.add(shape)
    if len(shapes) < 5:
        raise PublishedHorizonReplayError("The pool does not provide five structural shapes.")
    selected = [shapes[round(part * (len(shapes) - 1) / 4)] for part in range(5)]
    return [
        {
            "member": f"synthetic-ft{free_transfers}-shape{index + 1}",
            "entry": {
                "held": roster,
                "bank_tenths": bank,
                "free_transfers": free_transfers,
                "sell_tenths": {
                    str(identifier): by_id[identifier]["buy_tenths"] for identifier in roster
                },
                "horizon": {"windows": [3, 5]},
            },
        }
        for index, (roster, bank) in enumerate(selected)
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--table", type=Path, required=True)
    parser.add_argument("--calendar", type=Path, required=True)
    parser.add_argument("--season", choices=[LIVE_SEASON], required=True)
    parser.add_argument("--weeks", type=int, choices=[3, 5], default=5)
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args()
    table_bytes, calendar_bytes = args.table.read_bytes(), args.calendar.read_bytes()
    table, calendar = json.loads(table_bytes), json.loads(calendar_bytes)
    weeks = replay_published_weeks(table, calendar, season=args.season, weeks=args.weeks)
    document = _payload(table)
    output: dict[str, Any] = {
        "contract_version": REPLAY_CONTRACT,
        "season": args.season,
        "source_snapshot_id": document["source_snapshot_id"],
        "gameweek": document["gameweek"],
        "players": len(document["players"]),
        "weeks": len(weeks),
        "source_table_sha256": hashlib.sha256(table_bytes).hexdigest(),
        "source_calendar_sha256": hashlib.sha256(calendar_bytes).hexdigest(),
        "numeric_weeks_sha256": hashlib.sha256(
            json.dumps(weeks, sort_keys=True).encode()
        ).hexdigest(),
        "fixture_scaling_rule_version": FIXTURE_SCALING_RULE_VERSION,
        "original_projection_handoff_available": False,
        "original_projection_horizon_fingerprint": None,
    }
    if not args.summary:
        output["numeric_weeks"] = weeks
    print(json.dumps(output, allow_nan=False))


if __name__ == "__main__":
    main()
