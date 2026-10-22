"""Synthetic parity inputs for the device port of the accepted purchase-price replay."""

import copy
import json
from dataclasses import asdict
from pathlib import Path

from scripts.export_entry_state_vectors import ENTRY, _bytes, _history, _picks

from squadopt.application.entries import EntryError, EntryPicks, held_squad_from_picks
from squadopt.data.sources.fpl_live import entry_transfer_history, entry_transfers, fpl_entry_picks
from squadopt.live.purchase_prices import rebuild_purchase_prices
from squadopt.planning.pricing import sell_price_tenths

FIXTURE = (
    Path(__file__).resolve().parents[1] / "web/src/features/league/entryState/price-vectors.json"
)
DEADLINES = {week: f"2026-08-{1 + (week - 1) * 7:02d}T12:00:00Z" for week in range(1, 6)}


def _transfer(week, out, into, paid=65, raised=60, time=None):
    return {
        "entry": ENTRY,
        "event": week,
        "element_out": out,
        "element_in": into,
        "element_out_cost": raised,
        "element_in_cost": paid,
        "time": time or f"2026-08-{2 + (week - 2) * 7:02d}T12:00:00Z",
    }


def _base():
    opening, held, history = _picks(1), _picks(3), _history(3)
    for picks in (opening, held):
        picks["entry_history"]["bank"] = 100
    for row in history["current"]:
        row["bank"] = 100
    return {
        "transfers": [],
        "history": history,
        "opening": opening,
        "held": held,
        "budget_tenths": 1000,
        "start_prices": dict.fromkeys(range(1, 21), 60),
        "current_prices": dict.fromkeys(range(1, 21), 60),
        "deadlines": DEADLINES,
        "through_gameweek": 3,
        "active_chip": None,
        "sell_on_fee": 0.5,
    }


def _bank(case, week, amount, count=0):
    case["history"]["current"][week - 1].update(bank=amount, event_transfers=count)


def _held(case, out=None, into=None, bank=100):
    if out is not None:
        for row in case["held"]["picks"]:
            if row["element"] == out:
                row["element"] = into
    case["held"]["entry_history"]["bank"] = bank


def _answer(case):
    history = entry_transfer_history(_bytes(case["history"]), entry_id=ENTRY)
    opening = fpl_entry_picks(
        _bytes(case["opening"]),
        _bytes(case["history"]),
        entry_id=ENTRY,
        season="2026-27",
        gameweek=1,
    )
    basis = fpl_entry_picks(
        _bytes(case["held"]),
        _bytes(case["history"]),
        entry_id=ENTRY,
        season="2026-27",
        gameweek=case["held"]["entry_history"]["event"],
    )
    rebuilt = rebuild_purchase_prices(
        entry_transfers(_bytes(case["transfers"]), entry_id=ENTRY),
        history=history,
        opening_squad=opening.squad,
        opening_bank_tenths=opening.bank_tenths,
        budget_tenths=case["budget_tenths"],
        start_prices=case["start_prices"],
        deadlines=case["deadlines"],
        through_gameweek=case["through_gameweek"],
        active_chip=case["active_chip"],
        held_squad=basis.squad,
        held_bank_tenths=basis.bank_tenths,
        sell_on_fee=case["sell_on_fee"],
    )
    expected = {
        "known": rebuilt.known,
        "prices": dict(rebuilt.prices),
        "applied": rebuilt.applied,
        "free_hit_skipped": rebuilt.free_hit_skipped,
        "pending": rebuilt.pending,
        "sales_checked": rebuilt.sales_checked,
    }
    picks = EntryPicks(
        entry_id=ENTRY,
        season="2026-27",
        gameweek=case["through_gameweek"],
        squad=basis.squad,
        starting_xi=basis.starting_xi,
        captain=basis.captain,
        vice_captain=basis.vice_captain,
        bank_tenths=basis.bank_tenths,
        free_transfers=1,
        purchase_prices=rebuilt.prices,
        purchase_prices_known=rebuilt.known,
        squad_sell_value_tenths=basis.squad_sell_value_tenths,
    )
    try:
        held = held_squad_from_picks(picks, current_prices=case["current_prices"])
        sell = {
            player: sell_price_tenths(
                case["current_prices"][player],
                held.purchase_prices[player],
                sell_on_fee=case["sell_on_fee"],
            )
            for player in held.squad_player_ids
        }
        selling = {
            "sell_tenths": sell,
            "purchase_prices_known": rebuilt.known,
            "squad_sell_value_tenths": sum(sell.values())
            if rebuilt.known
            else held.squad_sell_value_tenths,
        }
    except EntryError:
        selling = {"refused": True}
    return expected, selling


def build_vectors():
    cases = []

    def case(name, base=None):
        value = copy.deepcopy(_base() if base is None else base)
        cases.append({"name": name, "input": value})
        return value

    case("no-transfers")
    rising = case("held-player-rise")
    rising["current_prices"][1] = 65
    single = case("one-purchase")
    single["transfers"] = [_transfer(2, 1, 16)]
    _bank(single, 2, 95, 1)
    _bank(single, 3, 95)
    _held(single, 1, 16, 95)
    bought_back = case("sold-and-bought-back")
    bought_back["transfers"] = [_transfer(3, 16, 1, 70, 65), _transfer(2, 1, 16)]
    _bank(bought_back, 2, 95, 1)
    _bank(bought_back, 3, 90, 1)
    _held(bought_back, bank=90)
    bought_back["current_prices"][1] = 75
    free_hit = case("free-hit-reverts")
    free_hit["transfers"] = [_transfer(2, 1, 16)]
    free_hit["history"]["chips"] = [{"name": "freehit", "event": 2}]
    active = case("active-free-hit")
    active["transfers"] = [_transfer(3, 1, 16)]
    active["active_chip"] = "freehit"
    active["held"]["entry_history"]["event"] = 2
    wildcard = case("wildcard-persists", single)
    wildcard["history"]["chips"] = [{"name": "wildcard", "event": 2}]
    _bank(wildcard, 2, 95)
    pending = case("pending-transfers")
    pending["transfers"] = [_transfer(4, 1, 16), _transfer(5, 16, 17, 70, 65)]
    invalid_pending = case("pending-squad-mismatch", pending)
    invalid_pending["transfers"][0]["element_out"] = 19
    tied = case("tied-sale-and-repurchase")
    tied["transfers"] = [_transfer(2, 16, 1, 70, 65), _transfer(2, 1, 16, 65, 65)]
    _bank(tied, 2, 95, 2)
    _bank(tied, 3, 95)
    _held(tied, bank=95)
    bad_sale = case("tied-sale-price-mismatch", tied)
    bad_sale["transfers"][1]["element_out_cost"] = 60
    repeat = case("repeated-element-at-one-instant", tied)
    repeat["transfers"][0].update(element_out=1, element_in=17)
    micro = case("distinct-microseconds-are-not-tied", tied)
    micro["transfers"][0]["time"] = "2026-08-02T12:00:00.000002Z"
    micro["transfers"][1]["time"] = "2026-08-02T12:00:00.000001Z"
    micro["transfers"][1]["element_out_cost"] = 60
    _bank(micro, 2, 90, 2)
    _bank(micro, 3, 90)
    _held(micro, bank=90)
    late = case("late-joiner-market-cap")
    late["history"]["current"].pop(0)
    late["current_prices"][1] = 75
    bad_count = case("history-count-mismatch", single)
    _bank(bad_count, 2, 95, 2)
    bad_budget = case("opening-budget-mismatch")
    bad_budget["start_prices"][1] = 65
    no_bank = case("missing-history-bank")
    no_bank["history"]["current"][1].pop("bank")
    wrong_held = case("held-squad-mismatch")
    _held(wrong_held, 1, 16)
    boundary = case("exact-deadline-is-refused", single)
    boundary["transfers"][0]["time"] = DEADLINES[2]
    bad_free_hit = case("free-hit-copy-is-validated", free_hit)
    bad_free_hit["transfers"][0]["element_out"] = 19
    no_current = case("missing-current-price")
    no_current["current_prices"].pop(1)
    for row in cases:
        row["expected"], row["expected_selling"] = _answer(row["input"])
    sales = [
        {
            "current": purchase + rise,
            "purchase": purchase,
            "fee": fee,
            "expected": sell_price_tenths(purchase + rise, purchase, sell_on_fee=fee),
        }
        for purchase in (40, 41, 100)
        for rise in (-5, -1, 0, 1, 2, 3, 11)
        for fee in (0.0, 0.5, 1.0, 0.335, 0.325, 0.495, 0.505)
    ]
    parsed = entry_transfers(_bytes(bought_back["transfers"]), entry_id=ENTRY)
    return {
        "reference": "rebuild_purchase_prices, held_squad_from_picks and sell_price_tenths",
        "entry_id": ENTRY,
        "cases": cases,
        "sales": sales,
        "parsed_transfers": [asdict(row) for row in parsed],
        "timestamps": [
            {
                "input": [transfer := _transfer(2, 1, 16, time=stamp)],
                "expected": [
                    asdict(row) for row in entry_transfers(_bytes([transfer]), entry_id=ENTRY)
                ],
            }
            for stamp in (
                "2026-08-02T12:00:00+00:00",
                "2026-08-02T12:00:00.1Z",
                "2026-08-02T12:00:00.000001-00:00",
                "1960-01-01T00:00:00.000001Z",
            )
        ],
    }


def main():
    FIXTURE.parent.mkdir(parents=True, exist_ok=True)
    FIXTURE.write_text(
        json.dumps(build_vectors(), indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
