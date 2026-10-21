"""Export synthetic entry-state answers from the production Python readers and rules."""

import copy
import json
from dataclasses import asdict
from pathlib import Path

from squadopt.application.entries import chip_states
from squadopt.data.errors import DataError
from squadopt.data.sources.fpl_live import (
    entry_transfer_history,
    fpl_entry_picks,
    gameweek_deadlines,
    next_open_deadline,
)
from squadopt.live.banking import banked_free_transfers
from squadopt.live.free_hit import free_hit_basis_gameweek
from squadopt.live.rules import (
    CHIP_NAMES,
    SEASON_RULES_CONTRACT_VERSION,
    ChipWindow,
    ScoringRules,
    SeasonRules,
    TransferRules,
)

FIXTURE = Path(__file__).resolve().parents[1] / "web/src/features/league/entryState/vectors.json"
ENTRY = 101


def _bytes(value):
    return json.dumps(value).encode("utf-8")


def _history(weeks=6):
    return {
        "current": [
            {
                "event": week,
                "event_transfers": 15 if week == 1 else 0,
                "event_transfers_cost": 0,
                "bank": 10,
            }
            for week in range(1, weeks + 1)
        ],
        "chips": [],
    }


def _picks(week=4, chip=None):
    return {
        "active_chip": chip,
        "entry_history": {"event": week, "bank": 10, "value": 1000},
        "picks": [
            {
                "element": player,
                "position": player,
                "is_captain": player == 7,
                "is_vice_captain": player == 8,
                "multiplier": 2 if player == 7 else int(player <= 11),
            }
            for player in range(1, 16)
        ],
        "automatic_subs": [],
    }


def _rules():
    zero = dict.fromkeys(("GKP", "DEF", "MID", "FWD"), 0)
    return SeasonRules(
        SEASON_RULES_CONTRACT_VERSION,
        "2026-27",
        "synthetic-entry-state",
        ScoringRules(0, 0, 0, 0, 0, 0, 0, 0, 0, 0, zero, zero, zero, zero),
        TransferRules(15, 11, 3, 1000, 4, None, 0.5, False),
        tuple(
            ChipWindow(
                name, 1, start, stop, "transfer" if name in ("wildcard", "freehit") else "team"
            )
            for name in CHIP_NAMES
            for start, stop in ((2, 19), (20, 38))
        ),
    )


def build_vectors():
    banking = []
    histories = {
        "cap-five": _history(),
        "late-joiner": _history(),
        "gap": _history(),
        "cost-mismatch": _history(),
        "charged-hit": _history(),
        "wildcard-keeps-savings": _history(),
        "active-free-hit": _history(),
    }
    histories["late-joiner"]["current"] = histories["late-joiner"]["current"][2:]
    histories["gap"]["current"].pop(2)
    histories["cost-mismatch"]["current"][2]["event_transfers_cost"] = 4
    histories["charged-hit"]["current"][2].update(event_transfers=4, event_transfers_cost=8)
    histories["wildcard-keeps-savings"]["chips"] = [{"name": "wildcard", "event": 4}]
    for name, history in histories.items():
        active = "freehit" if name == "active-free-hit" else None
        for cap in (1, 5, None):
            answer = banked_free_transfers(
                entry_transfer_history(_bytes(history), entry_id=ENTRY),
                gameweek=6,
                max_free_transfers=cap,
                active_chip=active,
            )
            banking.append(
                {
                    "name": f"{name}-cap-{cap}",
                    "history": history,
                    "week": 6,
                    "cap": cap,
                    "active_chip": active,
                    "expected": {"count": answer.count, "known": answer.known},
                }
            )
    picks = []
    normal = _picks()
    benched = copy.deepcopy(normal)
    benched["picks"][6]["position"], benched["picks"][12]["position"] = 13, 7
    benched["automatic_subs"] = [{"entry": ENTRY, "event": 4, "element_out": 7, "element_in": 13}]
    unmatched = copy.deepcopy(benched)
    unmatched["automatic_subs"] = []
    duplicate = copy.deepcopy(normal)
    duplicate["picks"][14]["element"] = 1
    for name, document in (
        ("normal", normal),
        ("bench-captain-after-autosub", benched),
        ("bench-captain-without-sub", unmatched),
        ("duplicate-player", duplicate),
    ):
        try:
            answer = fpl_entry_picks(
                _bytes(document), _bytes(_history()), entry_id=ENTRY, season="2026-27", gameweek=4
            )
            expected = {
                "entry_id": answer.entry_id,
                "gameweek": answer.gameweek,
                "squad": list(answer.squad),
                "starting_xi": list(answer.starting_xi),
                "captain": answer.captain,
                "vice_captain": answer.vice_captain,
                "bank_tenths": answer.bank_tenths,
                "market_value_tenths": answer.squad_sell_value_tenths + answer.bank_tenths,
                "active_chip": answer.active_chip,
            }
        except DataError:
            expected = {"refused": True}
        picks.append({"name": name, "input": document, "expected": expected})
    free_hits = []
    for name, chips in (
        ("ordinary", [None, None, None]),
        ("wildcard-persists", [None, "wildcard"]),
        ("free-hit", [None, None, "freehit"]),
        ("consecutive-free-hits", [None, None, "freehit", "freehit"]),
        ("no-earlier-squad", ["freehit"]),
    ):
        week = len(chips)
        basis = (
            week
            if chips[-1] != "freehit"
            else free_hit_basis_gameweek(
                week, was_free_hit=lambda at, chips=chips: chips[at - 1] == "freehit"
            )
        )
        free_hits.append(
            {
                "name": name,
                "picks": [_picks(at, chip) for at, chip in enumerate(chips, 1)],
                "expected_week": basis,
            }
        )
    rules = _rules()
    windows = [
        {key: value for key, value in asdict(window).items() if key != "chip_type"}
        for window in rules.chips
    ]
    chips = []
    for name, week, played in (
        ("unknown", 4, None),
        ("unused", 4, {}),
        ("played", 4, {"wildcard": [2], "3xc": [3]}),
        ("free-hit-last-half", 20, {"freehit": [19]}),
        ("free-hit-next-week", 21, {"freehit": [19]}),
        ("expired", 20, {}),
    ):
        expected = {
            name: {
                half: None if state is None else state.to_dict() for half, state in halves.items()
            }
            for name, halves in chip_states(rules, week, played).items()
        }
        chips.append({"name": name, "week": week, "played": played, "expected": expected})
    bootstrap = {
        "events": [
            {"id": 1, "deadline_time": "2026-08-01T12:00:00Z", "finished": True, "is_next": True},
            {
                "id": 2,
                "deadline_time": "2026-08-08T12:00:00.000001Z",
                "finished": False,
                "is_next": False,
            },
            {"id": 3, "deadline_time": "2026-08-15T12:00:00Z", "finished": False, "is_next": False},
        ]
    }
    deadlines = []
    for as_of in (
        "2026-08-01T11:59:59Z",
        "2026-08-01T12:00:00Z",
        "2026-08-08T12:00:00Z",
        "2026-08-08T12:00:00.000001Z",
        "2026-08-15T12:00:00Z",
    ):
        try:
            expected = next_open_deadline(
                gameweek_deadlines(_bytes(bootstrap)), as_of_utc=as_of
            ).gameweek
        except DataError:
            expected = None
        deadlines.append({"as_of": as_of, "expected_week": expected})
    return {
        "reference": "Python entry readers, banking, free_hit and chip_states",
        "entry_id": ENTRY,
        "banking": banking,
        "picks": picks,
        "free_hits": free_hits,
        "windows": windows,
        "chips": chips,
        "bootstrap": bootstrap,
        "deadlines": deadlines,
    }


def main():
    FIXTURE.parent.mkdir(parents=True, exist_ok=True)
    FIXTURE.write_text(
        json.dumps(build_vectors(), indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
