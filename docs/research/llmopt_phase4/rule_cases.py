"""Fixed rule fixtures and solver-independent checks on published one-week decisions."""

from collections import Counter
from math import isclose

FAMILIES = ("keep", "avoid", "buy", "club", "bank", "hit", "frozen")


def legal_exchanges(players, entry, squad, bank):
    held = set(entry["held"])
    clubs = Counter(players[p]["team"] for p in squad)
    for outgoing in sorted(held & squad):
        old = players[outgoing]
        proceeds = entry["sell_tenths"][str(outgoing)]
        for incoming, new in players.items():
            if incoming in held or incoming in squad or new["position"] != old["position"]:
                continue
            remaining = bank + proceeds - new["buy_tenths"]
            if remaining < 0 or (new["team"] != old["team"] and clubs[new["team"]] >= 3):
                continue
            yield incoming, outgoing, remaining


def rule_cases(document, entry, reference, gameweek):
    """Select rules before either new solve; the archived unrestricted plan is a stimulus only."""
    players = {p["id"]: p for p in document["players"]}
    held = set(entry["held"])
    bank = entry["bank_tenths"]
    saved = set(reference["squad"])
    clubs = Counter(players[p]["team"] for p in saved)
    arrivals = {players[p]["team"] for p in saved - held}
    exchanges = sorted(
        legal_exchanges(players, entry, held, bank),
        key=lambda move: (-players[move[0]]["coefficients"][2], move),
    )
    buy_move = next(move for move in exchanges if move[0] not in saved)
    if gameweek % 2:
        club_move = next(move for move in exchanges if players[move[0]]["team"] not in arrivals)
        club = players[club_move[0]]["team"]
        count = dict(club=club, count=1, scope="transfers_in")
    else:
        for club_move in exchanges:
            i, o, _ = club_move
            club = players[i]["team"]
            n = sum(players[p]["team"] == club for p in (held - {o}) | {i})
            if 1 <= n <= 3 and n != clubs[club]:
                count = dict(club=club, count=n, scope="squad")
                break
        else:
            raise ValueError("No differing legal squad-count fixture.")

    # Every unrestricted reference spent zero hits. Force one paid transfer so the
    # maximum is actually tested: GW8 allows exactly one hit; GW9 excludes it.
    changed, funds = set(held), bank
    for _ in range(entry["free_transfers"] + 1):
        i, o, funds = max(
            legal_exchanges(players, entry, changed, funds),
            key=lambda move: (move[2], players[move[0]]["coefficients"][2], -move[0], -move[1]),
        )
        changed = (changed - {o}) | {i}

    frozen = {
        k: reference[k] for k in ("transfers_in", "transfers_out", "starting_xi", "captain", "chip")
    }
    rules = {
        "keep": dict(keep_players=[min(held - saved)]),
        "avoid": dict(avoid_players=[min(saved - held)]),
        "buy": dict(week_rules=[dict(week=1, rules=dict(buy_players=[buy_move[0]]))]),
        "club": dict(club_counts=[count]),
        "bank": dict(min_bank=dict(tenths=reference["bank"] + 1)),
        "hit": dict(
            max_hit_points=0 if gameweek % 2 else int(document["rules"]["hit_points_charged"]),
            week_rules=[dict(week=1, rules=dict(buy_players=sorted(changed - held)))],
        ),
        "frozen": dict(frozen_weeks=[dict(week=1, **frozen)]),
    }
    bank_move = next(move for move in exchanges if move[2] >= rules["bank"]["min_bank"]["tenths"])

    def exchanged(move):
        return (held - {move[1]}) | {move[0]}

    squads = dict(
        keep=held,
        avoid=held,
        buy=exchanged(buy_move),
        club=exchanged(club_move),
        bank=exchanged(bank_move),
        hit=changed,
        frozen=saved,
    )
    # Select a legal XI with the reference formation on every candidate squad.
    formation = Counter(players[p]["position"] for p in reference["starting_xi"])
    witnesses = {}
    for family, squad in squads.items():
        xi = sorted(
            reference["starting_xi"]
            if family == "frozen"
            else [
                player
                for position, n in formation.items()
                for player in sorted(p for p in squad if players[p]["position"] == position)[:n]
            ]
        )
        captain = reference["captain"] if family == "frozen" else xi[0]
        witness = {
            "squad": sorted(squad),
            "in": sorted(squad - held),
            "out": sorted(held - squad),
            "xi": xi,
            "captain": captain,
            "chip": None,
        }
        audit = check_decision(document, entry, rules[family], witness, published=False)
        expected_errors = []
        expectation = dict(
            feasible=True, witness={k: v for k, v in witness.items() if k != "squad"}
        )
        if family == "hit":
            required = set(rules[family]["week_rules"][0]["rules"]["buy_players"])
            minimum = (
                max(0, len(required - held) - entry["free_transfers"])
                * document["rules"]["hit_points_charged"]
            )
            if minimum > rules[family]["max_hit_points"]:
                expectation = dict(
                    feasible=False,
                    required_arrivals=len(required - held),
                    free_transfers=entry["free_transfers"],
                    minimum_hit_points=minimum,
                )
                expected_errors = ["maximum hit"]
        if audit["errors"] != expected_errors:
            raise ValueError(
                f"{family} fixture witness: {audit['errors']} (expected {expected_errors})"
            )
        witnesses[family] = expectation
    return rules, witnesses


def check_decision(document, entry, preferences, decision, *, published=True):
    """Rebuild the squad, admissibility, integer objective, bank and hits from source tables."""
    players = {p["id"]: p for p in document["players"]}
    rules = document["rules"]
    held = set(entry["held"])
    incoming, outgoing, xi = (set(decision[k]) for k in ("in", "out", "xi"))
    captain = decision["captain"]
    squad = (held - outgoing) | incoming
    issues = []

    def require(condition, label):
        if not condition:
            issues.append(label)

    if not (squad | xi | incoming | outgoing | {captain}) <= players.keys():
        return dict(errors=["unknown player"], net_scaled=None)
    require(
        all(len(decision[k]) == len(set(decision[k])) for k in ("in", "out", "xi")), "duplicates"
    )
    require(outgoing <= held and not incoming & held and len(incoming) == len(outgoing), "moves")
    require(len(squad) == rules["squad_size"] and squad == set(decision["squad"]), "squad")
    require(len(xi) == rules["starting_size"] and xi <= squad and captain in xi, "lineup")
    require(
        Counter(players[p]["position"] for p in squad) == rules["squad_position_limits"],
        "positions",
    )
    counts = Counter(players[p]["position"] for p in xi)
    require(
        all(
            n <= counts[pos] <= rules["starting_position_max"][pos]
            for pos, n in rules["starting_position_min"].items()
        ),
        "formation",
    )
    clubs = Counter(players[p]["team"] for p in squad)
    require(max(clubs.values(), default=0) <= rules["max_players_per_team"], "club maximum")
    require(decision["chip"] is None, "no chip")
    bank = (
        entry["bank_tenths"]
        + sum(entry["sell_tenths"][str(p)] for p in outgoing & held)
        - sum(players[p]["buy_tenths"] for p in incoming)
    )
    hits = max(0, len(incoming) - entry["free_transfers"]) * rules["hit_points_charged"]
    require(bank >= 0, "nonnegative bank")
    net = (
        sum(players[p]["coefficients"][2] for p in xi)
        + players[captain]["coefficients"][2]
        - int(hits * rules["expected_points_scale"])
    )
    if published:
        require(bank == decision["bank"], "bank account")
        require(hits == decision["hit"], "hit account")
        for key in ("objective_scaled", "published_net_scaled"):
            reported = decision[key]
            require(
                isinstance(reported, (int, float))
                and isclose(net, reported, rel_tol=0, abs_tol=1e-8),
                key,
            )
    require(set(preferences.get("keep_players", [])) <= squad & held, "keep")
    require(not (set(preferences.get("avoid_players", [])) & squad), "avoid")
    for week in preferences.get("week_rules", []):
        require(set(week["rules"]["buy_players"]) <= incoming, "buy")
    for rule in preferences.get("club_counts", []):
        members = incoming if rule.get("scope") == "transfers_in" else squad
        require(sum(players[p]["team"] == rule["club"] for p in members) == rule["count"], "club")
    if "min_bank" in preferences:
        require(bank >= preferences["min_bank"]["tenths"], "bank floor")
    if "max_hit_points" in preferences:
        require(hits <= preferences["max_hit_points"], "maximum hit")
    for frozen in preferences.get("frozen_weeks", []):
        require(
            set(frozen["transfers_in"]) == incoming
            and set(frozen["transfers_out"]) == outgoing
            and set(frozen["starting_xi"]) == xi
            and frozen["captain"] == captain
            and frozen["chip"] == decision["chip"],
            "frozen week",
        )
    return dict(net_scaled=net, errors=issues)
