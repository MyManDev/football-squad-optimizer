"""Research-only two-swap proposal; never imported by the product.

Keep the expected-window wrapper and its 40/60 allocation. Replace only its optional
proposal, with one fixed-first-squad solve and the same remaining deterministic budget.
The shortlist is a proxy, not an enumeration or a proof of the best transfer package.
"""

from collections import Counter
from dataclasses import replace
from itertools import combinations
from time import perf_counter

from squadopt.contracts.preferences import DecisionPreferences
from squadopt.planning.expected_swap import checked_work
from squadopt.planning.lineup_utility import improve_plan_lineups
from squadopt.planning.optimizer import optimize_transfer_plan
from squadopt.scenarios.expected_lineup import expected_lineup_score


def legal_package(first, initial, optimization, transfer, preferences, outgoing, incoming):
    ids = set(initial.squad_player_ids) - set(outgoing) | set(incoming)
    rules = preferences.for_week(1)
    bank = initial.bank_tenths + sum(int(first.at[p, "sell_price_tenths"]) for p in outgoing)
    bank -= sum(int(first.at[p, "buy_price_tenths"]) for p in incoming)
    paid = max(0, len(incoming) - initial.free_transfers)
    cap = transfer.max_transfers_per_gameweek
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
        len(ids) == 15
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


def propose_pairs(
    horizon,
    initial,
    optimization,
    transfer,
    template,
    retained_squads,
    *,
    deterministic_slack,
    wall_slack,
    chips=None,
    preferences=None,
):
    started = perf_counter()
    record = dict(
        phase="initial_up_to_two_swaps",
        status="skipped",
        reason=None,
        cap=0.0,
        actual=0.0,
        solver_calls=0,
        hold_score_calls=0,
        hold_score_states=0,
        lineup_search=None,
        cheap_pair_checks=0,
        cheap_pair_cap=0,
        proxy_is_exact_gain=False,
        shortlist_cap=32,
    )

    def skip(reason):
        record.update(reason=reason, wall_seconds=perf_counter() - started)
        return None, record

    preferences = preferences or DecisionPreferences()
    if deterministic_slack <= 1e-9 or wall_slack <= 0:
        return skip("no_remaining_budget")
    if template.chip in {"wildcard", "freehit"}:
        return skip("first_week_rebuild")
    if preferences.for_week(1).hold_transfers or preferences.hold_opening_transfers:
        return skip("hold_transfers")
    first = horizon.table.loc[horizon.table.gameweek.eq(horizon.gameweeks[0])].set_index(
        "player_id", drop=False
    )
    held = set(initial.squad_player_ids)
    selected = set(template.selected_squad.player_id)
    replacement = {}
    for position in ("GK", "DEF", "MID", "FWD"):
        incoming = sorted(p for p in selected - held if first.at[p, "position"] == position)
        outgoing = sorted(p for p in held - selected if first.at[p, "position"] == position)
        replacement.update(zip(incoming, outgoing, strict=True))
    xi = tuple(replacement.get(p, p) for p in template.starting_xi.player_id)
    bench = tuple(replacement.get(p, p) for p in template.bench.player_id)
    captain = replacement.get(template.captain.player_id, template.captain.player_id)
    vice = replacement.get(template.vice_captain_id, template.vice_captain_id)
    if selected == held and template.lineup_expectation is not None:
        multipliers = template.lineup_expectation["scoring_multipliers"]
    else:
        score = expected_lineup_score(
            first.loc[list(initial.squad_player_ids)], xi, bench, captain, vice
        )
        multipliers = score.scoring_multipliers
        record.update(hold_score_calls=1, hold_score_states=score.states_evaluated)
    outsiders = sorted(set(first.index) - held)
    record["cheap_pair_cap"] = 15 * len(outsiders)
    moves = []
    for outgoing in sorted(held):
        for incoming in outsiders:
            if first.at[outgoing, "position"] != first.at[incoming, "position"]:
                continue
            gain = float(multipliers[outgoing]) * (
                float(first.at[incoming, "expected_points"])
                - float(first.at[outgoing, "expected_points"])
            )
            cash = int(first.at[outgoing, "sell_price_tenths"]) - int(
                first.at[incoming, "buy_price_tenths"]
            )
            moves.append((gain, cash, outgoing, incoming))
    # Include funding moves even when their individual point proxy is negative.
    pool = sorted(
        set(
            sorted(moves, reverse=True)[:24]
            + sorted(moves, key=lambda m: (-m[1], -m[0], m[2:]))[:8]
        )
    )
    packages = [(move,) for move in moves]
    packages.extend((a, b) for a, b in combinations(pool, 2) if a[2] != b[2] and a[3] != b[3])
    best = None
    for package in packages[: record["cheap_pair_cap"]]:
        record["cheap_pair_checks"] += 1
        outgoing = tuple(m[2] for m in package)
        incoming = tuple(m[3] for m in package)
        ids = frozenset(held - set(outgoing) | set(incoming))
        if ids in retained_squads or not legal_package(
            first, initial, optimization, transfer, preferences, outgoing, incoming
        ):
            continue
        proxy = (
            sum(m[0] for m in package)
            - max(0, len(package) - initial.free_transfers) * transfer.transfer_hit_cost_points
        )
        candidate = (proxy, tuple(sorted(ids)), outgoing, incoming)
        if proxy > 0 and (best is None or candidate > best):
            best = candidate
    if best is None:
        return skip("no_distinct_legal_positive_package")
    remaining = wall_slack - (perf_counter() - started)
    if remaining <= 0:
        return skip("no_remaining_wall_budget")
    settings = replace(
        optimization,
        solver_deterministic_time_limit=deterministic_slack,
        solver_time_limit_seconds=remaining / 2,
    )
    record.update(
        cap=deterministic_slack,
        solver_calls=1,
        proxy=best[0],
        fixed_first_squad=list(best[1]),
        outgoing=list(best[2]),
        incoming=list(best[3]),
    )
    candidate = optimize_transfer_plan(
        horizon,
        initial,
        settings,
        transfer,
        chips=chips,
        preferences=preferences,
        fixed_week_squads={horizon.gameweeks[0]: best[1]},
        linearization_level=2,
        protect_hold=False,
        protect_incumbent=False,
    )
    record.update(
        status=candidate.solver_status.name,
        actual=checked_work(candidate.diagnostics["deterministic_time_used"], deterministic_slack),
    )
    if not candidate.has_solution:
        return skip("optional_no_solution")
    result = improve_plan_lineups(
        candidate, settings, transfer, preferences=preferences, max_evaluations=128
    )
    record.update(
        reason="retained",
        lineup_search=result.diagnostics["lineup_search"],
        wall_seconds=perf_counter() - started,
    )
    return result, record
