"""Tests for the purchase prices rebuilt from the public transfers list.

The rebuild replays a member's transfers over the fifteen it opened the season with
(``rebuild_purchase_prices``). Every case here is a small synthetic season: elements 101 to
115 opened at start prices that cost 99.5 with 0.5 in the bank, against the season's budget
of 100.0, and the deadlines fall weekly. The last two cases are real members of the
2026-10-05 capture, written inline with their prices and rows and with synthetic times that
keep each row's order and gameweek.
"""

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from types import MappingProxyType
from typing import Any

import pytest

from squadopt.data.sources.fpl_live import EntryTransfer, EntryTransferHistory, EntryTransferWeek
from squadopt.live.purchase_prices import RebuiltPurchasePrices, rebuild_purchase_prices
from squadopt.planning.pricing import sell_price_tenths

OPENING = tuple(range(101, 116))
START: dict[int, int] = dict(
    zip(OPENING, (45, 40, 55, 50, 45, 45, 40, 120, 85, 80, 65, 55, 110, 80, 80), strict=True)
)
OPENING_BANK = 5
BUDGET = 1000
_FIRST_DEADLINE = datetime(2026, 8, 21, 17, 30, tzinfo=UTC)


def _iso(moment: datetime) -> str:
    return moment.isoformat().replace("+00:00", "Z")


DEADLINES: dict[int, str] = {
    week: _iso(_FIRST_DEADLINE + timedelta(weeks=week - 1)) for week in range(1, 39)
}


def _at(event: int, minutes: int = 60) -> str:
    """An instant inside gameweek ``event``'s transfer window, ``minutes`` after it opens."""

    return _iso(_FIRST_DEADLINE + timedelta(weeks=event - 2, minutes=minutes))


def _transfer(
    event: int, out: int, out_cost: int, into: int, in_cost: int, *, minutes: int = 60
) -> EntryTransfer:
    return EntryTransfer(
        event=event,
        element_in=into,
        element_in_cost=in_cost,
        element_out=out,
        element_out_cost=out_cost,
        time_utc=_at(event, minutes),
    )


def _history(
    weeks: Mapping[int, tuple[int, int | None]], chips: Mapping[str, Sequence[int]] | None = None
) -> EntryTransferHistory:
    """Gameweek to (transfers counted, bank), as the season history states them."""

    return EntryTransferHistory(
        entry_id=11,
        weeks=MappingProxyType(
            {
                week: EntryTransferWeek(transfers=count, cost=0, bank=bank)
                for week, (count, bank) in weeks.items()
            }
        ),
        chips_used=MappingProxyType(
            {name: tuple(events) for name, events in (chips or {}).items()}
        ),
    )


def _rebuild(
    transfers: Sequence[EntryTransfer],
    weeks: Mapping[int, tuple[int, int | None]],
    *,
    held: Sequence[int],
    bank: int,
    chips: Mapping[str, Sequence[int]] | None = None,
    active_chip: str | None = None,
    **overrides: Any,
) -> RebuiltPurchasePrices:
    arguments: dict[str, Any] = {
        "history": _history(weeks, chips),
        "opening_squad": OPENING,
        "opening_bank_tenths": OPENING_BANK,
        "budget_tenths": BUDGET,
        "start_prices": START,
        "deadlines": DEADLINES,
        "through_gameweek": max(weeks),
        "active_chip": active_chip,
        "held_squad": held,
        "held_bank_tenths": bank,
        "sell_on_fee": 0.5,
    }
    arguments.update(overrides)
    return rebuild_purchase_prices(transfers, **arguments)


def _swap(squad: Sequence[int], out: Sequence[int], into: Sequence[int]) -> tuple[int, ...]:
    return tuple(element for element in squad if element not in out) + tuple(into)


def _refused(result: RebuiltPurchasePrices, *fragments: str) -> None:
    assert result.known is False
    assert dict(result.prices) == {}
    for fragment in fragments:
        assert fragment in str(result.reason), result.reason


def test_the_synthetic_opening_costs_exactly_the_budget() -> None:
    assert sum(START.values()) + OPENING_BANK == BUDGET


# --- what a replay gives --------------------------------------------------------------


def test_a_squad_held_since_the_opening_deadline_was_bought_at_its_start_prices() -> None:
    result = _rebuild([], {1: (0, 5)}, held=OPENING, bank=5)
    assert result.known is True and result.reason is None
    assert dict(result.prices) == START


# GW2 sells 101 (bought at 4.5) for 4.5 and buys 201 at 4.7; GW4 sells 108 (bought at
# 12.0) for 12.3 and buys 202 at 11.8. The bank goes 5, 3, 3, 8.
SINGLES = (_transfer(2, 101, 45, 201, 47), _transfer(4, 108, 123, 202, 118))
SINGLES_WEEKS = {1: (0, 5), 2: (1, 3), 3: (0, 3), 4: (1, 8)}
SINGLES_HELD = _swap(OPENING, (101, 108), (201, 202))


def test_a_bought_player_carries_the_price_paid_and_a_sold_one_leaves() -> None:
    result = _rebuild(SINGLES, SINGLES_WEEKS, held=SINGLES_HELD, bank=8)
    assert result.known is True
    assert result.prices[201] == 47 and result.prices[202] == 118
    assert 101 not in result.prices and 108 not in result.prices
    assert {element: result.prices[element] for element in OPENING if element in result.prices} == {
        element: START[element] for element in OPENING if element not in (101, 108)
    }
    assert (result.applied, result.free_hit_skipped, result.pending) == (2, 0, 0)


# A Wildcard in GW3, made in two batches a day apart; the history counts no transfers in a
# Wildcard week. The bank goes 5 + 0 - 2 + 5 - 2 + 1 + 0 = 7.
WILDCARD = (
    _transfer(3, 101, 45, 201, 45, minutes=60),
    _transfer(3, 102, 40, 202, 42, minutes=61),
    _transfer(3, 103, 55, 203, 50, minutes=62),
    _transfer(3, 104, 50, 204, 52, minutes=1500),
    _transfer(3, 105, 45, 205, 44, minutes=1501),
    _transfer(3, 106, 45, 206, 45, minutes=1502),
)
WILDCARD_HELD = _swap(OPENING, range(101, 107), range(201, 207))


def test_every_row_of_a_wildcard_is_kept_because_its_squad_persists() -> None:
    weeks = {1: (0, 5), 2: (0, 5), 3: (0, 7)}
    result = _rebuild(WILDCARD, weeks, held=WILDCARD_HELD, bank=7, chips={"wildcard": [3]})
    assert result.known is True and result.applied == 6
    assert [result.prices[element] for element in range(201, 207)] == [45, 42, 50, 52, 44, 45]
    # The captured week's own Wildcard is read from the picks, before the history lists it.
    assert _rebuild(WILDCARD, weeks, held=WILDCARD_HELD, bank=7, active_chip="wildcard").known
    # Without the chip the history's count of none contradicts the six rows.
    _refused(
        _rebuild(WILDCARD, weeks, held=WILDCARD_HELD, bank=7),
        "gameweek 3 lists 6 transfers and the history counts 0",
    )


# A Free Hit in GW3 reverts after its week: its two rows are set aside, and GW4's transfer
# sells 101 again from the squad held before the chip. The history states the bank from
# before the chip in the chip week, 5, then 5 + 46 - 48 = 3.
FREE_HIT = (
    _transfer(3, 101, 45, 201, 50),
    _transfer(3, 102, 40, 202, 60, minutes=90),
    _transfer(4, 101, 46, 203, 48),
)
FREE_HIT_WEEKS = {1: (0, 5), 2: (0, 5), 3: (0, 5), 4: (1, 3)}
FREE_HIT_HELD = _swap(OPENING, (101,), (203,))


def test_a_free_hit_weeks_rows_are_skipped_because_the_chip_reverts_them() -> None:
    result = _rebuild(FREE_HIT, FREE_HIT_WEEKS, held=FREE_HIT_HELD, bank=3, chips={"freehit": [3]})
    assert result.known is True
    assert (result.applied, result.free_hit_skipped) == (1, 2)
    assert result.prices[203] == 48 and result.prices[102] == START[102]


def test_the_same_rows_without_the_free_hit_are_refused() -> None:
    """Replayed as ordinary transfers the chip week's rows leave a squad and a bank the
    member never held, which is what the skip is for."""

    counted = {**FREE_HIT_WEEKS, 3: (2, 5)}
    _refused(_rebuild(FREE_HIT, counted, held=FREE_HIT_HELD, bank=3), "after gameweek 3")


# GW2 sells 101 for 4.5 and buys 201 at 4.7 (bank 3); GW4 is a Free Hit whose two rows the
# captured picks show, but the member holds the GW3 squad and bank at the next deadline.
CAPTURED_FREE_HIT = (
    _transfer(2, 101, 45, 201, 47),
    _transfer(4, 102, 40, 202, 40),
    _transfer(4, 103, 55, 203, 80, minutes=61),
)
CAPTURED_FREE_HIT_HELD = _swap(OPENING, (101,), (201,))


def test_a_free_hit_in_the_captured_week_is_read_from_the_picks() -> None:
    """The history lists a chip only once its week is over; the picks report it now. The
    chip week's own bank row is not compared, so whatever it states is not a refusal."""

    for chip_week_bank in (3, 0):
        result = _rebuild(
            CAPTURED_FREE_HIT,
            {1: (0, 5), 2: (1, 3), 3: (0, 3), 4: (0, chip_week_bank)},
            held=CAPTURED_FREE_HIT_HELD,
            bank=3,
            active_chip="freehit",
        )
        assert result.known is True
        assert (result.applied, result.free_hit_skipped) == (1, 2)


def test_two_free_hits_in_a_row_are_both_skipped() -> None:
    """The game forbids a Free Hit in consecutive gameweeks, so this is a damaged record
    rather than a season; the replay still lands on the squad held before both."""

    rows = (
        _transfer(2, 101, 45, 201, 47),
        _transfer(3, 102, 40, 202, 40),
        _transfer(4, 103, 55, 203, 50),
    )
    result = _rebuild(
        rows,
        {1: (0, 5), 2: (1, 3), 3: (0, 3), 4: (0, 3)},
        held=CAPTURED_FREE_HIT_HELD,
        bank=3,
        chips={"freehit": [3]},
        active_chip="freehit",
    )
    assert result.known is True and result.free_hit_skipped == 2


def test_a_player_bought_twice_carries_the_last_price_paid() -> None:
    """Bought at 5.0 in GW2, sold in GW3, bought again at 5.3 in GW4: the 5.3 stands."""

    rows = (
        _transfer(2, 101, 45, 201, 50),
        _transfer(3, 201, 51, 203, 46),
        _transfer(4, 103, 55, 201, 53),
    )
    result = _rebuild(
        rows,
        {1: (0, 5), 2: (1, 0), 3: (1, 5), 4: (1, 7)},
        held=_swap(OPENING, (101, 103), (203, 201)),
        bank=7,
    )
    assert result.known is True and result.prices[201] == 53


def test_a_player_sold_and_bought_back_was_bought_at_the_later_price() -> None:
    """Held from the start at 11.0, sold for 11.0 in GW3, bought back at 11.1 in GW4: what
    he sells for is reckoned from 11.1, not from the start price."""

    rows = (_transfer(3, 113, 110, 201, 100), _transfer(4, 201, 100, 113, 111))
    result = _rebuild(rows, {1: (0, 5), 2: (0, 5), 3: (1, 15), 4: (1, 4)}, held=OPENING, bank=4)
    assert result.known is True
    assert result.prices[113] == 111 != START[113]


def test_a_row_for_a_later_deadline_is_pending_and_left_out() -> None:
    rows = (_transfer(2, 101, 45, 201, 47), _transfer(3, 102, 40, 202, 41))
    result = _rebuild(rows, {1: (0, 5), 2: (1, 3)}, held=_swap(OPENING, (101,), (201,)), bank=3)
    assert result.known is True
    assert (result.applied, result.pending) == (1, 1)
    assert 102 in result.prices and 202 not in result.prices


def test_a_sale_bought_back_at_the_next_deadline_is_checked_and_left_out() -> None:
    """GW3 is the next deadline: 108, bought for 12.0, is sold for 12.2 and bought back at
    12.5 at one instant, which is checked on a copy. The held prices do not move."""

    rows = (
        _transfer(2, 101, 45, 201, 47),
        _transfer(3, 108, 122, 202, 41),
        _transfer(3, 113, 110, 108, 125),
    )
    result = _rebuild(rows, {1: (0, 5), 2: (1, 3)}, held=_swap(OPENING, (101,), (201,)), bank=3)
    assert result.known is True
    assert (result.applied, result.pending, result.sales_checked) == (1, 2, 1)
    assert result.prices[108] == START[108] and result.prices[113] == START[113]
    assert 202 not in result.prices


def test_rows_for_a_deadline_after_the_next_are_counted_and_not_replayed() -> None:
    """Picks of GW3 read from a capture whose list runs to GW6, where GW5 was a Free Hit:
    GW6 sells 102 again from the squad the chip reverted to, which a replay of every
    pending row on one copy would call a player not held."""

    rows = (
        _transfer(4, 101, 45, 201, 45),
        _transfer(5, 102, 40, 202, 40),
        _transfer(6, 102, 40, 203, 40),
    )
    weeks = {1: (0, 5), 2: (0, 5), 3: (0, 5)}
    result = _rebuild(rows, weeks, held=OPENING, bank=5, chips={"freehit": [5]})
    assert result.known is True
    assert (result.applied, result.pending, result.sales_checked) == (0, 3, 0)
    assert dict(result.prices) == START


def test_rows_made_at_one_instant_apply_in_any_order_when_none_crosses_another() -> None:
    rows = (_transfer(2, 101, 45, 201, 47), _transfer(2, 102, 40, 202, 40))
    result = _rebuild(
        rows, {1: (0, 5), 2: (2, 3)}, held=_swap(OPENING, (101, 102), (201, 202)), bank=3
    )
    assert result.known is True and result.applied == 2


def test_rows_at_one_instant_apply_in_the_order_the_holdings_allow() -> None:
    """Listed selling 201 before buying him: a player not held is bought before he is sold,
    and the buy states the price of the instant, so the sale is checked against it."""

    rows = (_transfer(2, 201, 47, 202, 47), _transfer(2, 101, 45, 201, 47))
    result = _rebuild(rows, {1: (0, 5), 2: (2, 3)}, held=_swap(OPENING, (101,), (202,)), bank=3)
    assert result.known is True
    assert (result.applied, result.sales_checked) == (2, 1)
    assert result.prices[202] == 47 and 201 not in result.prices


# 108, bought for 12.0 at the opening, is sold and bought back at one instant in GW2: the
# buy states the instant's price, 12.5, and at 12.5 the rule gives 12.2. 113 leaves for
# 11.0 to pay for it, and 201 comes in at 4.7. The bank goes 5 + 122 - 47 + 110 - 125 = 65.
REBUY_HELD = _swap(OPENING, (113,), (201,))


def test_a_sale_bought_back_at_the_same_instant_is_checked_against_the_rule() -> None:
    rows = (_transfer(2, 113, 110, 108, 125), _transfer(2, 108, 122, 201, 47))
    result = _rebuild(rows, {1: (0, 5), 2: (2, 65)}, held=REBUY_HELD, bank=65)
    assert result.known is True
    assert (result.applied, result.sales_checked) == (2, 1)
    assert result.prices[108] == 125 and result.prices[201] == 47


def test_a_buy_back_at_another_instant_does_not_price_the_sale() -> None:
    """The same rows a day apart, with 108 risen to 12.7 overnight. The sale's price is not
    known, so the 12.2 it raised is not checked against the 12.3 the rule would give at
    12.7; the replay is trusted on its other checks."""

    rows = (
        _transfer(2, 108, 122, 201, 47, minutes=60),
        _transfer(2, 113, 110, 108, 127, minutes=1500),
    )
    result = _rebuild(rows, {1: (0, 5), 2: (2, 63)}, held=REBUY_HELD, bank=63)
    assert result.known is True
    assert (result.applied, result.sales_checked) == (2, 0)
    assert result.prices[108] == 127


def test_a_free_hit_weeks_rows_are_checked_on_a_copy_and_let_go() -> None:
    """The chip week sells 108 and buys him back at one instant, which is checked, then
    sells 201, whom only the chip week bought. None of it survives the week: GW4 sells 101
    from the squad held before the chip, and 108 is still held at his opening price."""

    rows = (
        _transfer(3, 108, 122, 201, 47),
        _transfer(3, 113, 110, 108, 125),
        _transfer(3, 201, 47, 202, 60, minutes=90),
        FREE_HIT[2],
    )
    result = _rebuild(rows, FREE_HIT_WEEKS, held=FREE_HIT_HELD, bank=3, chips={"freehit": [3]})
    assert result.known is True
    assert (result.applied, result.free_hit_skipped, result.sales_checked) == (1, 3, 1)
    assert result.prices[108] == START[108] and result.prices[113] == START[113]
    assert not {201, 202} & set(result.prices)


def test_a_second_free_hit_in_the_season_is_set_aside_like_the_first() -> None:
    """The game allows one of each chip in each half of the season; the synthetic history
    puts the second at gameweek 5 to stay short. Both chip weeks' rows revert."""

    rows = (
        _transfer(3, 101, 45, 201, 50),
        _transfer(4, 102, 40, 202, 41),
        _transfer(5, 101, 45, 203, 60),
        _transfer(5, 103, 55, 204, 30, minutes=61),
    )
    result = _rebuild(
        rows,
        {1: (0, 5), 2: (0, 5), 3: (0, 5), 4: (1, 4), 5: (0, 4)},
        held=_swap(OPENING, (102,), (202,)),
        bank=4,
        chips={"freehit": [3, 5]},
    )
    assert result.known is True
    assert (result.applied, result.free_hit_skipped) == (1, 3)
    assert result.prices[101] == START[101] and result.prices[202] == 41


def test_a_second_wildcard_in_the_season_is_kept_like_the_first() -> None:
    """Two Wildcards, at gameweeks 3 and 5 as above, whose history counts no transfers in
    either week. The bank goes 5 + 0 - 2 = 3, then 3 + 5 - 2 = 6."""

    rows = (
        _transfer(3, 101, 45, 201, 45),
        _transfer(3, 102, 40, 202, 42, minutes=61),
        _transfer(5, 103, 55, 203, 50),
        _transfer(5, 104, 50, 204, 52, minutes=61),
    )
    result = _rebuild(
        rows,
        {1: (0, 5), 2: (0, 5), 3: (0, 3), 4: (0, 3), 5: (0, 6)},
        held=_swap(OPENING, range(101, 105), range(201, 205)),
        bank=6,
        chips={"wildcard": [3, 5]},
    )
    assert result.known is True and result.applied == 4
    assert [result.prices[element] for element in range(201, 205)] == [45, 42, 50, 52]


# --- what is refused, and why --------------------------------------------------------


def test_a_late_joiner_is_refused_because_the_opening_prices_are_unknown() -> None:
    result = _rebuild([], {3: (0, 5), 4: (0, 5)}, held=OPENING, bank=5)
    _refused(result, "gameweek 3")


def test_a_bank_the_replay_does_not_reproduce_names_the_week() -> None:
    """One sale stated a tenth higher: after GW2 the replay holds 4 where the history says 3."""

    rows = (_transfer(2, 101, 46, 201, 47), SINGLES[1])
    _refused(
        _rebuild(rows, SINGLES_WEEKS, held=SINGLES_HELD, bank=8),
        "after gameweek 2 the replayed bank is 4 tenths and the history states 3",
    )


def test_a_replay_that_ends_off_the_captured_bank_is_refused() -> None:
    _refused(
        _rebuild(SINGLES, SINGLES_WEEKS, held=SINGLES_HELD, bank=9),
        "ends with 8 tenths in the bank and the captured picks state 9",
    )


def test_a_replay_that_ends_off_the_captured_squad_names_the_difference() -> None:
    """A row the list lost, in a history that agrees with the list: the squad still differs."""

    weeks = {**SINGLES_WEEKS, 4: (0, 3)}
    _refused(
        _rebuild(SINGLES[:1], weeks, held=SINGLES_HELD, bank=3),
        "holding elements 108",
        "without elements 202",
    )


def test_an_opening_squad_that_does_not_cost_the_budget_is_refused() -> None:
    """A squad bought before a price was edited paid the old price: the start price is not
    what it cost, and the opening bank no longer closes the budget."""

    cheaper = {**START, 101: START[101] - 1}
    _refused(
        _rebuild([], {1: (0, 5)}, held=OPENING, bank=5, start_prices=cheaper),
        "cost 994 tenths",
        "budget of 1000",
    )


def test_an_opening_bank_the_history_contradicts_is_refused() -> None:
    _refused(_rebuild([], {1: (0, 6)}, held=OPENING, bank=6), "gameweek 1 bank is 6")


def test_a_week_counting_other_than_the_rows_listed_is_refused() -> None:
    _refused(
        _rebuild(SINGLES, {**SINGLES_WEEKS, 2: (2, 3)}, held=SINGLES_HELD, bank=8),
        "gameweek 2 lists 1 transfers and the history counts 2",
    )


def test_a_history_without_a_week_or_its_bank_is_refused() -> None:
    _refused(
        _rebuild([], {1: (0, 5), 3: (0, 5)}, held=OPENING, bank=5, through_gameweek=3),
        "no row for gameweek 2",
    )
    _refused(_rebuild([], {1: (0, 5), 2: (0, None)}, held=OPENING, bank=5), "no bank")


def test_selling_a_player_not_held_or_buying_one_held_is_refused_by_row() -> None:
    weeks = {1: (0, 5), 2: (1, 5)}
    _refused(
        _rebuild([_transfer(2, 301, 45, 201, 45)], weeks, held=OPENING, bank=5),
        "transfer of element 301 for element 201",
        "does not hold",
    )
    _refused(
        _rebuild([_transfer(2, 101, 45, 102, 45)], weeks, held=OPENING, bank=5),
        "transfer of element 101 for element 102",
        "already holds",
    )


def test_a_row_for_the_opening_gameweek_is_refused() -> None:
    row = EntryTransfer(
        event=1,
        element_in=201,
        element_in_cost=45,
        element_out=101,
        element_out_cost=45,
        time_utc="2026-08-20T10:00:00Z",
    )
    _refused(_rebuild([row], {1: (0, 5)}, held=OPENING, bank=5), "opening gameweek")


def test_a_row_outside_its_own_gameweeks_window_is_refused() -> None:
    """A GW3 row stamped before the GW2 deadline, or a GW2 row stamped after it or at
    either of its deadlines, is not where its gameweek says it is."""

    early = EntryTransfer(
        event=3,
        element_in=201,
        element_in_cost=47,
        element_out=101,
        element_out_cost=45,
        time_utc=_at(2),
    )
    _refused(
        _rebuild([early], {1: (0, 5), 2: (0, 5), 3: (1, 3)}, held=OPENING, bank=3),
        "outside its window",
    )
    late = EntryTransfer(
        event=2,
        element_in=201,
        element_in_cost=47,
        element_out=101,
        element_out_cost=45,
        time_utc=_at(3),
    )
    _refused(
        _rebuild(
            [late],
            {1: (0, 5), 2: (1, 3), 3: (0, 3)},
            held=_swap(OPENING, (101,), (201,)),
            bank=3,
        ),
        f"made at {_at(3)}, outside its window from {DEADLINES[1]} to {DEADLINES[2]}",
    )
    # The window is open at both ends, so a row stamped at a deadline itself is outside.
    for stamp in (DEADLINES[1], DEADLINES[2]):
        on_deadline = EntryTransfer(
            event=2,
            element_in=201,
            element_in_cost=47,
            element_out=101,
            element_out_cost=45,
            time_utc=stamp,
        )
        _refused(
            _rebuild(
                [on_deadline],
                {1: (0, 5), 2: (1, 3), 3: (0, 3)},
                held=_swap(OPENING, (101,), (201,)),
                bank=3,
            ),
            f"made at {stamp}, outside its window",
        )


def test_rows_at_one_instant_that_repeat_an_element_are_refused() -> None:
    """201 is bought twice at one instant: which purchase the sale is reckoned from, and
    which one stands, is an order no holding fixes and the document does not state."""

    rows = (
        _transfer(2, 101, 45, 201, 47),
        _transfer(2, 201, 47, 202, 47),
        _transfer(2, 102, 40, 201, 47),
    )
    _refused(
        _rebuild(rows, {1: (0, 5), 2: (3, 3)}, held=_swap(OPENING, (101, 102), (201, 202)), bank=3),
        "one instant",
        "201 more than once",
    )


def test_a_sale_the_rule_does_not_give_at_a_known_price_is_refused() -> None:
    """108, bought for 12.0, is sold for 12.3 and bought back at 12.5 at the same instant:
    at 12.5 the rule gives 12.2, so the row is not a sale the game made."""

    rows = (_transfer(2, 113, 110, 108, 125), _transfer(2, 108, 123, 201, 47))
    _refused(
        _rebuild(rows, {1: (0, 5), 2: (2, 66)}, held=_swap(OPENING, (113,), (201,)), bank=66),
        "transfer of element 108 for element 201 raised 123 tenths",
        "the 125 tenths a buy of element 108 at the same instant paid",
        "bought for 120 sells for 122",
    )


def test_a_free_hit_row_that_does_not_apply_to_the_squad_before_the_chip_is_refused() -> None:
    """The chip week's rows are checked on a copy of the squad held before it: a sale of a
    player it does not hold, a buy of one it holds, or a sale the rule does not give at a
    known price is a refusal, as in any other week."""

    weeks, chips = FREE_HIT_WEEKS, {"freehit": [3]}
    for first, fragments in (
        (_transfer(3, 301, 45, 201, 50), ("element 301 for element 201", "does not hold")),
        (_transfer(3, 101, 45, 102, 50), ("element 101 for element 102", "already holds")),
    ):
        rows = (first, FREE_HIT[2])
        _refused(_rebuild(rows, weeks, held=FREE_HIT_HELD, bank=3, chips=chips), *fragments)
    rebuy = (
        _transfer(3, 108, 123, 201, 47),
        _transfer(3, 113, 110, 108, 125),
        FREE_HIT[2],
    )
    _refused(
        _rebuild(rebuy, weeks, held=FREE_HIT_HELD, bank=3, chips=chips),
        "transfer of element 108 for element 201 raised 123 tenths",
    )


def test_a_pending_row_that_does_not_apply_to_the_held_squad_is_refused() -> None:
    """A row for the next deadline was made from the squad held now: one selling a player
    that squad does not hold, or buying one it holds, is not a row of this member's."""

    weeks, held = {1: (0, 5), 2: (1, 3)}, _swap(OPENING, (101,), (201,))
    for pending, fragments in (
        (_transfer(3, 101, 45, 202, 41), ("element 101 for element 202", "held squad does not")),
        (_transfer(3, 102, 40, 201, 47), ("element 102 for element 201", "already holds")),
    ):
        rows = (_transfer(2, 101, 45, 201, 47), pending)
        _refused(_rebuild(rows, weeks, held=held, bank=3), *fragments)
    rebuy = (
        _transfer(2, 101, 45, 201, 47),
        _transfer(3, 108, 123, 202, 41),
        _transfer(3, 113, 110, 108, 125),
    )
    _refused(_rebuild(rebuy, weeks, held=held, bank=3), "raised 123 tenths")


def test_a_wildcard_weeks_bank_is_still_read_against_the_history() -> None:
    """A Wildcard week counts no transfers, but its rows persist, so its bank is checked:
    the six rows leave 7 and a history stating 8 is refused."""

    _refused(
        _rebuild(
            WILDCARD,
            {1: (0, 5), 2: (0, 5), 3: (0, 8)},
            held=WILDCARD_HELD,
            bank=7,
            chips={"wildcard": [3]},
        ),
        "after gameweek 3 the replayed bank is 7 tenths and the history states 8",
    )


def test_an_opening_player_without_a_start_price_is_refused() -> None:
    unpriced = {element: price for element, price in START.items() if element != 115}
    _refused(
        _rebuild([], {1: (0, 5)}, held=OPENING, bank=5, start_prices=unpriced),
        "no start price for opening elements 115",
    )


def test_a_gameweek_before_the_first_is_an_error_not_a_refusal() -> None:
    with pytest.raises(ValueError, match="positive"):
        _rebuild([], {1: (0, 5)}, held=OPENING, bank=5, through_gameweek=0)


# --- two real members ------------------------------------------------------------------
#
# From the capture of 2026-10-05 (fpl-live-20261005T141457Z-ee8a1c799131) and the
# transfers lists and opening picks read beside it. Each row is (gameweek, element sold,
# price received, element bought, price paid) in the order the member made them; the
# times are synthetic, one minute apart inside each gameweek's window. Prices in tenths.

REAL_DEADLINES = DEADLINES


def _real_rows(rows: Sequence[tuple[int, int, int, int, int]]) -> list[EntryTransfer]:
    made: dict[int, int] = {}
    transfers: list[EntryTransfer] = []
    for event, out, out_cost, into, in_cost in rows:
        made[event] = made.get(event, 0) + 1
        transfers.append(_transfer(event, out, out_cost, into, in_cost, minutes=made[event]))
    return transfers


# Entry 313686: a Wildcard in GW4 made in five batches over six days, in which element 411
# was bought, sold and bought again, element 148 the same, and elements 109 and 368 were
# sold and bought back. Element 154 left in GW3 for 9.5 and came back in GW4 at 9.6.
WILDCARD_MEMBER: dict[str, Any] = {
    "opening": {
        1: 60,
        8: 55,
        423: 45,
        534: 45,
        334: 50,
        368: 70,
        426: 120,
        427: 80,
        106: 80,
        346: 60,
        165: 75,
        109: 45,
        387: 65,
        124: 55,
        154: 95,
    },
    "opening_bank": 0,
    "rows": (
        (3, 154, 95, 399, 77),
        (4, 106, 80, 26, 75),
        (4, 387, 65, 277, 40),
        (4, 427, 79, 367, 71),
        (4, 423, 45, 31, 44),
        (4, 1, 60, 496, 45),
        (4, 26, 75, 411, 155),
        (4, 346, 60, 272, 45),
        (4, 109, 45, 301, 40),
        (4, 368, 70, 154, 96),
        (4, 411, 155, 379, 91),
        (4, 367, 71, 12, 95),
        (4, 496, 45, 109, 45),
        (4, 534, 45, 148, 45),
        (4, 148, 45, 449, 51),
        (4, 334, 50, 115, 48),
        (4, 449, 51, 148, 45),
        (4, 12, 95, 368, 70),
        (4, 399, 77, 557, 64),
        (4, 379, 91, 411, 155),
        (5, 557, 64, 480, 80),
        (5, 165, 76, 249, 56),
    ),
    "weeks": {1: (0, 0), 2: (0, 0), 3: (1, 18), 4: (0, 2), 5: (2, 6)},
    "chips": {"bboost": [1], "wildcard": [4]},
    "held": {
        109: 45,
        8: 58,
        31: 46,
        277: 41,
        154: 97,
        426: 119,
        368: 69,
        480: 80,
        124: 59,
        249: 57,
        411: 156,
        301: 40,
        115: 50,
        148: 45,
        272: 45,
    },
    "bank": 6,
    "stated_worth": 1010,
}

# Entry 4287206: a Free Hit in GW3 whose twelve rows include one made before the chip was
# played, all reverted; one transfer in GW5 bought back element 399 the chip week had held.
FREE_HIT_MEMBER: dict[str, Any] = {
    "opening": {
        496: 45,
        532: 50,
        8: 55,
        11: 55,
        154: 95,
        428: 80,
        40: 75,
        427: 80,
        165: 75,
        411: 155,
        346: 60,
        57: 45,
        175: 40,
        212: 45,
        305: 40,
    },
    "opening_bank": 5,
    "rows": (
        (3, 346, 60, 464, 60),
        (3, 496, 45, 82, 50),
        (3, 532, 50, 87, 45),
        (3, 11, 55, 115, 47),
        (3, 175, 40, 327, 50),
        (3, 305, 40, 356, 65),
        (3, 427, 80, 454, 61),
        (3, 40, 75, 366, 75),
        (3, 428, 80, 398, 70),
        (3, 154, 95, 399, 77),
        (3, 165, 75, 379, 90),
        (3, 212, 45, 124, 55),
        (4, 427, 79, 15, 66),
        (4, 212, 45, 565, 57),
        (5, 428, 79, 399, 78),
    ),
    "weeks": {1: (0, 5), 2: (0, 5), 3: (0, 5), 4: (2, 6), 5: (1, 7)},
    "chips": {"freehit": [3]},
    "held": {
        496: 45,
        532: 49,
        305: 40,
        8: 58,
        565: 56,
        154: 97,
        40: 77,
        15: 68,
        399: 78,
        411: 156,
        346: 60,
        57: 45,
        165: 77,
        175: 40,
        11: 53,
    },
    "bank": 7,
    "stated_worth": 1008,
}


def _real(member: dict[str, Any]) -> RebuiltPurchasePrices:
    opening: dict[int, int] = member["opening"]
    return rebuild_purchase_prices(
        _real_rows(member["rows"]),
        history=_history(member["weeks"], member["chips"]),
        opening_squad=tuple(opening),
        opening_bank_tenths=member["opening_bank"],
        budget_tenths=BUDGET,
        start_prices=opening,
        deadlines=REAL_DEADLINES,
        through_gameweek=5,
        active_chip=None,
        held_squad=tuple(member["held"]),
        held_bank_tenths=member["bank"],
        sell_on_fee=0.5,
    )


def _budget(member: dict[str, Any], result: RebuiltPurchasePrices) -> int:
    current: dict[int, int] = member["held"]
    return int(member["bank"]) + sum(
        sell_price_tenths(current[element], result.prices[element], sell_on_fee=0.5)
        for element in current
    )


def test_the_real_wildcard_member_rebuilds_to_a_budget_below_the_stated_worth() -> None:
    result = _real(WILDCARD_MEMBER)
    assert result.known is True and result.applied == 22
    paid = {element: result.prices[element] for element in (154, 411, 368, 109, 148, 8)}
    assert paid == {154: 96, 411: 155, 368: 70, 109: 45, 148: 45, 8: 55}
    assert _budget(WILDCARD_MEMBER, result) == 1003
    assert WILDCARD_MEMBER["stated_worth"] == 1010


def test_the_real_free_hit_member_rebuilds_with_the_chip_weeks_rows_set_aside() -> None:
    result = _real(FREE_HIT_MEMBER)
    assert result.known is True
    assert (result.applied, result.free_hit_skipped) == (3, 12)
    assert result.prices[399] == 78 and result.prices[11] == 55
    assert _budget(FREE_HIT_MEMBER, result) == 999
    assert FREE_HIT_MEMBER["stated_worth"] == 1008
