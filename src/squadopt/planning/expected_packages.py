"""Bounded point and funding packages, checked on the original whole-squad state."""

from collections import Counter
from collections.abc import Mapping, Sequence
from itertools import combinations
from typing import Any, cast

import pandas as pd

from squadopt.contracts.preferences import DecisionPreferences
from squadopt.optimization import OptimizationConfig
from squadopt.planning.expected_swap import PackageChoice
from squadopt.planning.models import InitialSquadState, TransferPlanningConfig, _stable_id_key

Move = tuple[float, int, object, object]


def package_menu(moves: list[Move]) -> list[tuple[Move, ...]]:
    def order(m: Move) -> tuple[float, int | str, int | str]:
        return -m[0], _stable_id_key(m[2]), _stable_id_key(m[3])

    singles = sorted(moves, key=order)
    funding = sorted(moves, key=lambda m: (-m[1], *order(m)))[:8]
    pool = sorted(set(singles[:24] + funding), key=order)
    pairs = [(a, b) for a, b in combinations(pool, 2) if a[2] != b[2] and a[3] != b[3]]
    pairs.sort(
        key=lambda p: (
            -sum(m[0] for m in p),
            tuple((_stable_id_key(m[2]), _stable_id_key(m[3])) for m in p),
        )
    )
    result: list[tuple[Move, ...]] = [(move,) for move in singles]
    result.extend(pairs)
    return result


def legal_package(
    first: pd.DataFrame,
    initial: InitialSquadState,
    optimization: OptimizationConfig,
    transfer: TransferPlanningConfig,
    preferences: DecisionPreferences,
    outgoing: tuple[object, ...],
    incoming: tuple[object, ...],
    gameweek: int,
) -> bool:
    held = set(initial.squad_player_ids)
    if (
        len(outgoing) != len(incoming)
        or len(incoming) not in (1, 2)
        or len(set(outgoing)) != len(outgoing)
        or len(set(incoming)) != len(incoming)
        or not set(outgoing) <= held
        or set(incoming) & held
        or any(
            first.at[a, "position"] != first.at[b, "position"]
            for a, b in zip(outgoing, incoming, strict=True)
        )
    ):
        return False
    ids = held - set(outgoing) | set(incoming)
    rules = preferences.for_week(1)
    bank = initial.bank_tenths + sum(
        int(cast(int, first.at[p, "sell_price_tenths"])) for p in outgoing
    )
    bank -= sum(int(cast(int, first.at[p, "buy_price_tenths"])) for p in incoming)
    paid = max(0, len(incoming) - initial.free_transfers)
    cap = transfer.transfer_caps_by_gameweek.get(gameweek, transfer.max_transfers_per_gameweek)
    if (
        cap is not None
        and len(incoming) > cap
        and not (
            transfer.allow_two_free_transfers and len(incoming) <= min(2, initial.free_transfers)
        )
    ):
        return False
    clubs = Counter(str(first.at[p, "team_id"]) for p in ids)
    return (
        len(ids) == optimization.squad_size
        and bank >= (preferences.min_opening_bank_tenths or 0)
        and max(clubs.values()) <= optimization.max_players_per_team
        and set(rules.keep_players).union(rules.include_players) <= ids
        and not set(rules.avoid_players).intersection(ids)
        and set(rules.buy_players) <= set(incoming)
        and not (rules.no_hits and paid)
        and (
            preferences.max_hit_points is None
            or paid * transfer.hit_points_charged <= preferences.max_hit_points
        )
        and all(
            (
                sum(str(first.at[p, "team_id"]) == rule.club for p in incoming)
                if rule.scope == "transfers_in"
                else clubs[rule.club]
            )
            == rule.count
            for rule in rules.club_counts
        )
    )


def pick_package(
    first: pd.DataFrame,
    initial: InitialSquadState,
    optimization: OptimizationConfig,
    transfer: TransferPlanningConfig,
    preferences: DecisionPreferences,
    multipliers: Mapping[object, object],
    retained: Sequence[frozenset[object]],
    record: dict[str, Any],
) -> PackageChoice | None:
    record.update(
        phase="initial_up_to_two_swaps",
        shortlist_cap=32,
        proxy_is_exact_gain=False,
        checked_single_packages=0,
        checked_pair_packages=0,
    )
    if any(week.week == 1 for week in preferences.frozen_weeks):
        record["reason"] = "fixed_first_week"
        return None
    held = set(initial.squad_player_ids)
    outsiders = sorted(set(first.index) - held, key=_stable_id_key)
    moves: list[Move] = []
    for outgoing in sorted(held, key=_stable_id_key):
        for incoming in outsiders:
            if first.at[outgoing, "position"] != first.at[incoming, "position"]:
                continue
            gain = float(cast(float, multipliers[outgoing])) * (
                float(cast(float, first.at[incoming, "expected_points"]))
                - float(cast(float, first.at[outgoing, "expected_points"]))
            )
            cash = int(cast(int, first.at[outgoing, "sell_price_tenths"])) - int(
                cast(int, first.at[incoming, "buy_price_tenths"])
            )
            moves.append((gain, cash, outgoing, incoming))
    packages = package_menu(moves)
    check_cap = 15 * len(outsiders)
    record.update(
        cheap_pair_cap=check_cap,
        generated_packages=len(packages),
        generated_singles=len(moves),
        generated_pairs=len(packages) - len(moves),
        truncated_packages=max(0, len(packages) - check_cap),
    )
    best: PackageChoice | None = None
    for package in packages[:check_cap]:
        record["cheap_pair_checks"] += 1
        record["checked_single_packages" if len(package) == 1 else "checked_pair_packages"] += 1
        outgoing, incoming = tuple(m[2] for m in package), tuple(m[3] for m in package)
        ids = frozenset(held - set(outgoing) | set(incoming))
        if ids in retained or not legal_package(
            first,
            initial,
            optimization,
            transfer,
            preferences,
            outgoing,
            incoming,
            int(first.iloc[0].gameweek),
        ):
            continue
        proxy = (
            sum(m[0] for m in package)
            - max(0, len(package) - initial.free_transfers) * transfer.transfer_hit_cost_points
        )
        if proxy > 0 and (best is None or proxy > best[0]):
            best = (proxy, outgoing, incoming, tuple(sorted(ids, key=_stable_id_key)))
    return best
