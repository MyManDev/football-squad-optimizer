"""The capture provider rebuilds a member's purchase prices, or keeps the stated worth.

With the transfers list and the opening picks in the capture, the picks carry what was paid
for each held player and the fifteen's selling value under the game's rule at the capture's
prices. Without either document, or with one the rebuild cannot use, every field is what it
was before the rebuild existed: the parser's ``value - bank`` and no purchase prices. The
last test holds the page's budget to the planner's on the same capture.
"""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import tests.unit.test_live_transfers as world_module
import tests.unit.test_source_fpl_live as payload_module
from tests.unit.test_league_views import _legal_squad, _world_context

from squadopt.application.capture_entries import CapturePicksProvider
from squadopt.application.entries import EntryRegistration, held_squad_from_picks
from squadopt.application.league_publication import purchase_prices_note
from squadopt.application.league_views import build_league_views
from squadopt.data.snapshots import read_snapshot
from squadopt.data.sources.fpl_live import BOOTSTRAP_PAYLOAD, fpl_entry_picks
from squadopt.live.transfers import member_planning_inputs
from squadopt.planning.pricing import sell_price_tenths

ENTRY = 11
SEASON = "2026-27"
OPENING = list(range(101, 116))
START = dict(
    zip(OPENING, (45, 40, 55, 50, 45, 45, 40, 120, 85, 80, 65, 55, 110, 80, 80), strict=True)
)
# What the capture prices them at: 102 fell by 0.2, 108 rose by 0.5, 113 by 0.3, and 201,
# bought at 4.7 in gameweek 2, rose by 0.2. Everyone else is at his start price.
NOW = {**START, 102: 38, 108: 125, 113: 113, 201: 49, 202: 60, 203: 80}
HELD = [201, *OPENING[1:]]
_FIRST_DEADLINE = datetime(2026, 8, 21, 17, 30, tzinfo=UTC)

world = world_module._world  # re-register the fixture in this module


def _iso(moment: datetime) -> str:
    return moment.isoformat().replace("+00:00", "Z")


def _bootstrap(**rules: Any) -> bytes:
    elements = [
        {
            "id": element,
            "code": element + 1000,
            "now_cost": price,
            "cost_change_start": price - START.get(element, price),
        }
        for element, price in NOW.items()
    ]
    events = [
        {
            "id": week,
            "deadline_time": _iso(_FIRST_DEADLINE + timedelta(weeks=week - 1)),
            "finished": week < 4,
        }
        for week in range(1, 6)
    ]
    settings = {
        "squad_total_spend": 1000,
        "transfers_sell_on_fee": 0.5,
        "element_sell_at_purchase_price": False,
        "max_extra_free_transfers": 4,
    }
    settings.update(rules)
    document = {"elements": elements, "events": events, "game_config": {"rules": settings}}
    return json.dumps(document).encode("utf-8")


def _picks(squad: list[int], *, bank: int, value: int, chip: str | None = None) -> bytes:
    document = json.loads(payload_module._picks_payload(squad=squad, bank=bank, value=value))
    document["active_chip"] = chip
    return json.dumps(document).encode("utf-8")


def _history(
    weeks: dict[int, tuple[int, int]], chips: list[tuple[str, int]] | None = None
) -> bytes:
    return payload_module._history_payload(
        chips=[{"name": name, "event": event} for name, event in chips or []],
        current=[
            {**payload_module._row(week, transfers), "bank": bank}
            for week, (transfers, bank) in weeks.items()
        ],
    )


def _transfer(event: int, out: int, out_cost: int, into: int, in_cost: int) -> dict[str, Any]:
    made = _FIRST_DEADLINE + timedelta(weeks=event - 2, hours=1)
    return {
        "element_in": into,
        "element_in_cost": in_cost,
        "element_out": out,
        "element_out_cost": out_cost,
        "entry": ENTRY,
        "event": event,
        "time": _iso(made),
    }


# Gameweek 2 sold 101 for 4.6 and bought 201 at 4.7: the bank goes 5, 4, 4.
TRANSFERS = [_transfer(2, 101, 46, 201, 47)]
WEEKS = {1: (0, 5), 2: (1, 4), 3: (0, 4)}


def _payloads(**overrides: bytes | None) -> dict[str, bytes]:
    """A capture for the gameweek 4 deadline: picks for gameweek 3 and everything a rebuild
    reads. ``value`` is the fifteen at the capture's prices plus the bank, a market value."""

    payloads: dict[str, bytes | None] = {
        BOOTSTRAP_PAYLOAD: _bootstrap(),
        f"entry-{ENTRY}-picks-gw03.json": _picks(
            HELD, bank=4, value=4 + sum(NOW[element] for element in HELD)
        ),
        f"entry-{ENTRY}-picks-gw01.json": _picks(OPENING, bank=5, value=1000),
        f"entry-{ENTRY}-history.json": _history(WEEKS),
        f"entry-{ENTRY}-transfers.json": json.dumps(TRANSFERS).encode("utf-8"),
    }
    payloads.update(overrides)
    return {name: payload for name, payload in payloads.items() if payload is not None}


def _provider(payloads: dict[str, bytes]) -> CapturePicksProvider:
    return CapturePicksProvider(SimpleNamespace(payloads=payloads), "fpl-live-20261005T141457Z")


def _rule_sum(paid: dict[int, int]) -> int:
    return sum(
        sell_price_tenths(NOW[element], price, sell_on_fee=0.5) for element, price in paid.items()
    )


def _fallback(payloads: dict[str, bytes]) -> None:
    """The picks are what the parser alone gives: no purchase prices and ``value - bank``."""

    picks = _provider(payloads).picks(ENTRY, SEASON, 3)
    parsed = fpl_entry_picks(
        payloads[f"entry-{ENTRY}-picks-gw03.json"],
        payloads[f"entry-{ENTRY}-history.json"],
        entry_id=ENTRY,
        season=SEASON,
        gameweek=3,
    )
    assert dict(picks.purchase_prices) == {}
    assert picks.purchase_prices_known is False
    assert picks.squad_sell_value_tenths == parsed.squad_sell_value_tenths


def test_both_documents_rebuild_the_prices_and_the_selling_value_under_the_rule() -> None:
    picks = _provider(_payloads()).picks(ENTRY, SEASON, 3)
    paid = {**{element: START[element] for element in OPENING[1:]}, 201: 47}
    assert picks.purchase_prices_known is True
    assert dict(picks.purchase_prices) == {element + 1000: price for element, price in paid.items()}
    # 102 sells at its fallen price, 108 and 113 keep half their rises rounded down, and
    # 201 half of its 0.2: 99.9 against the 100.5 the fifteen are worth at market prices.
    assert picks.squad_sell_value_tenths == _rule_sum(paid) == 999
    assert sum(NOW[element] for element in HELD) == 1005
    assert picks.bank_tenths == 4
    result = _provider(_payloads()).purchase_prices_for(ENTRY, SEASON, 3)
    assert (result.known, result.applied, result.reason) == (True, 1, None)


def test_without_the_transfers_list_the_picks_are_the_parsers_byte_for_byte() -> None:
    without = _payloads(**{f"entry-{ENTRY}-transfers.json": None})
    _fallback(without)
    neither = _payloads(
        **{f"entry-{ENTRY}-transfers.json": None, f"entry-{ENTRY}-picks-gw01.json": None}
    )
    assert _provider(without).picks(ENTRY, SEASON, 3) == _provider(neither).picks(ENTRY, SEASON, 3)
    reason = _provider(without).purchase_prices_for(ENTRY, SEASON, 3).reason
    assert f"entry-{ENTRY}-transfers.json" in str(reason)


def test_without_the_opening_picks_the_stated_worth_stands() -> None:
    payloads = _payloads(**{f"entry-{ENTRY}-picks-gw01.json": None})
    _fallback(payloads)
    reason = _provider(payloads).purchase_prices_for(ENTRY, SEASON, 3).reason
    assert f"entry-{ENTRY}-picks-gw01.json" in str(reason)


def test_an_unreadable_transfers_list_falls_back_and_names_the_error() -> None:
    payloads = _payloads(**{f"entry-{ENTRY}-transfers.json": b'{"read": "x"}'})
    _fallback(payloads)
    reason = _provider(payloads).purchase_prices_for(ENTRY, SEASON, 3).reason
    assert "must be a JSON array" in str(reason)


def test_a_late_joiner_keeps_the_stated_worth() -> None:
    payloads = _payloads(**{f"entry-{ENTRY}-history.json": _history({3: (0, 4)})})
    _fallback(payloads)
    assert "gameweek 3" in str(_provider(payloads).purchase_prices_for(ENTRY, SEASON, 3).reason)


def test_a_replay_that_misses_the_bank_keeps_the_stated_worth() -> None:
    sold_higher = [_transfer(2, 101, 47, 201, 47)]
    payloads = _payloads(**{f"entry-{ENTRY}-transfers.json": json.dumps(sold_higher).encode()})
    _fallback(payloads)
    reason = _provider(payloads).purchase_prices_for(ENTRY, SEASON, 3).reason
    assert "after gameweek 2" in str(reason)


def test_a_free_hit_in_the_captured_week_prices_the_squad_held_before_it() -> None:
    """The captured week is the chip's: its fifteen and bank revert, so the selling value
    is the gameweek 2 fifteen's, with the chip week's two rows set aside."""

    chip_squad = [202, 203, *OPENING[2:], 201][:15]
    payloads = _payloads(
        **{
            f"entry-{ENTRY}-picks-gw03.json": _picks(
                chip_squad, bank=0, value=1009, chip="freehit"
            ),
            f"entry-{ENTRY}-picks-gw02.json": _picks(HELD, bank=4, value=1009),
            f"entry-{ENTRY}-transfers.json": json.dumps(
                [*TRANSFERS, _transfer(3, 201, 49, 202, 60), _transfer(3, 102, 38, 203, 80)]
            ).encode("utf-8"),
        }
    )
    picks = _provider(payloads).picks(ENTRY, SEASON, 3)
    assert picks.squad_basis == "pre_free_hit_gw02"
    assert picks.purchase_prices_known is True
    assert picks.squad == tuple(element + 1000 for element in HELD)
    assert picks.squad_sell_value_tenths == 999 and picks.bank_tenths == 4
    result = _provider(payloads).purchase_prices_for(ENTRY, SEASON, 3)
    assert (result.applied, result.free_hit_skipped) == (1, 2)


@pytest.mark.parametrize("field", ["now_cost", "cost_change_start"])
def test_a_bootstrap_without_the_prices_keeps_the_stated_worth(field: str) -> None:
    document = json.loads(_bootstrap())
    for element in document["elements"]:
        del element[field]
    payloads = _payloads(**{BOOTSTRAP_PAYLOAD: json.dumps(document).encode("utf-8")})
    _fallback(payloads)
    assert field in str(_provider(payloads).purchase_prices_for(ENTRY, SEASON, 3).reason)


@pytest.mark.parametrize(
    "rules",
    [
        {"transfers_sell_on_fee": None},
        {"element_sell_at_purchase_price": True},
        {"squad_total_spend": None},
    ],
)
def test_a_capture_without_a_fee_or_budget_the_planner_reads_keeps_the_stated_worth(
    rules: dict[str, Any],
) -> None:
    _fallback(_payloads(**{BOOTSTRAP_PAYLOAD: _bootstrap(**rules)}))


# --- the operator's line ----------------------------------------------------------------


def test_the_operator_line_counts_the_rebuilt_members_and_names_the_others() -> None:
    """A member the capture does not hold is not counted; one it holds without a rebuild
    is named with the reason; a transfer for the open deadline is counted, not applied."""

    pending = [*TRANSFERS, _transfer(4, 102, 38, 202, 60)]
    payloads = _payloads(**{f"entry-{ENTRY}-transfers.json": json.dumps(pending).encode()})
    payloads["entry-22-picks-gw03.json"] = payloads[f"entry-{ENTRY}-picks-gw03.json"]
    payloads["entry-22-history.json"] = payloads[f"entry-{ENTRY}-history.json"]
    registrations = [
        EntryRegistration(entry, f"member-{entry}", "2026-08-23T00:00:00Z")
        for entry in (ENTRY, 22, 33)
    ]
    note = purchase_prices_note(_provider(payloads), registrations, season=SEASON, gameweek=3)
    assert note == (
        "rebuilt for 1 of 2; 1 transfer(s) for the open deadline left out; "
        "22: the capture holds no entry-22-transfers.json"
    )
    assert (
        purchase_prices_note(_provider(payloads), registrations[2:], season=SEASON, gameweek=3)
        == ""
    )


def test_a_member_whose_squad_is_refused_is_named_in_the_operator_line() -> None:
    payloads = _payloads(
        **{f"entry-{ENTRY}-picks-gw03.json": _picks(HELD, bank=4, value=1009, chip="freehit")}
    )
    registrations = [EntryRegistration(ENTRY, "member", "2026-08-23T00:00:00Z")]
    note = purchase_prices_note(_provider(payloads), registrations, season=SEASON, gameweek=3)
    assert note.startswith("rebuilt for 0 of 1; 11: the squad itself was refused")
    assert "entry-11-picks-gw02.json" in note


# --- the page's budget is the plan's --------------------------------------------------


def test_the_budget_a_page_states_is_the_budget_the_plan_is_held_to(
    world: dict[str, Any], tmp_path: Path
) -> None:
    """A member of the transfers world who has held the opening fifteen since gameweek 1:
    1001 rose by 0.3, 1012 by 0.1 and 1020 fell by 0.2 since the opening deadline. The
    entry page's budget and the device block are the planner's own numbers, and both sit
    0.3 below the fifteen at market prices."""

    inputs, projection, rules = _world_context(world)
    snapshot = read_snapshot(world["snapshot_root"], world["gw2_id"])
    bootstrap = json.loads(snapshot.payloads[BOOTSTRAP_PAYLOAD])
    shifts = {1001: 3, 1012: 1, 1020: -2}
    for element in bootstrap["elements"]:
        element["cost_change_start"] = shifts.get(element["code"], 0)
    now = {element["id"]: element["now_cost"] for element in bootstrap["elements"]}
    squad = [code - 1000 for code in _legal_squad(world)]
    start = {element: now[element] - shifts.get(element + 1000, 0) for element in squad}
    bank = 1000 - sum(start.values())
    market = sum(now[element] for element in squad)
    payloads = {
        **snapshot.payloads,
        BOOTSTRAP_PAYLOAD: json.dumps(bootstrap).encode("utf-8"),
        "entry-101-picks-gw01.json": _picks(squad, bank=bank, value=bank + market),
        "entry-101-history.json": payload_module._history_payload(
            current=[{**payload_module._row(1), "bank": bank}]
        ),
        "entry-101-transfers.json": b"[]",
    }
    provider = CapturePicksProvider(SimpleNamespace(payloads=payloads), world["gw2_id"])
    picks = provider.picks(101, SEASON, 1)
    assert picks.purchase_prices_known is True
    assert picks.squad_sell_value_tenths == market - 3

    build_league_views(
        provider,
        (EntryRegistration(101, "member-a", "2026-08-23T00:00:00Z"),),
        inputs,
        projection,
        rules,
        league_id=352490,
        league_name="Test League",
        out_dir=tmp_path / "league",
    )
    entry = json.loads((tmp_path / "league" / "entries" / "101.json").read_text("utf-8"))
    payload = entry["payload"]
    prices = {
        int(player): int(price)
        for player, price in zip(
            projection.table["player_id"], projection.table["price_tenths"], strict=True
        )
    }
    planned = member_planning_inputs(
        inputs, projection, held_squad_from_picks(picks, current_prices=prices), rules
    )
    assert payload["spendable_budget_tenths"] == planned.bank_tenths + sum(
        planned.sell_prices_tenths.values()
    )
    assert payload["spendable_budget_tenths"] == bank + market - 3
    assert payload["purchase_prices_known"] is True
    block = payload["device_plan"]
    assert block["bank_tenths"] == bank == planned.bank_tenths
    assert block["sell_tenths"] == {
        str(player): price for player, price in planned.sell_prices_tenths.items()
    }
    assert block["sell_tenths"]["1001"] == prices[1001] - 2
