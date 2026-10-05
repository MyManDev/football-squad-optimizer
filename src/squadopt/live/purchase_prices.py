"""The price each held player was bought for, rebuilt from the public transfers list.

The picks document publishes no purchase price, and the worth it does publish is a market
value, not a selling value: the game keeps half of every rise since a player was bought
(``planning.pricing.sell_price_tenths``). Two other public documents together state what
was paid. The opening picks (``entry/{id}/event/1/picks/``) name the fifteen a member held
at the opening deadline, and no price moves before it, so each of them was bought at his
start price. The transfers list (``entry/{id}/transfers/``) names every later transfer
with the price paid and the price the sale raised. Replaying the list over the opening
fifteen leaves the price paid for every player still held.

The replay is trusted only where it agrees with what the source states elsewhere: the
opening fifteen and bank cost exactly the season's budget, every week's transfer count and
bank match the season history, and the replay ends on the squad and bank the captured
picks hold. Any disagreement returns ``known=False`` with the reason, and the provider
keeps the aggregate the picks document states. Parsing the documents is the data layer's
job (``entry_transfers``, ``element_prices``, ``entry_transfer_history``); this module is
the replay, and the application provider that builds a member's picks calls it.

One check is deliberately absent. A single sale cannot validate a single purchase price:
the sale price is the rule applied to the market price at the moment of the sale, no
captured document states that price, and for any purchase price some market price
reproduces any sale price.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from itertools import groupby
from types import MappingProxyType

from squadopt.data.errors import format_examples
from squadopt.data.sources.fpl_live import FREE_HIT_CHIP, EntryTransfer, EntryTransferHistory
from squadopt.data.timestamps import as_instant
from squadopt.live.banking import TRANSFER_CHIPS
from squadopt.live.free_hit import FIRST_GAMEWEEK


@dataclass(frozen=True, slots=True)
class RebuiltPurchasePrices:
    """What each held player was bought for, or why that is not known.

    ``prices`` maps the held fifteen's element ids to the tenths paid, and is empty unless
    ``known``. ``reason`` says why not, for the operator: a member's page carries the flag
    and nothing else. ``applied`` counts the rows the replay used, ``free_hit_skipped`` the
    Free Hit rows it set aside, and ``pending`` the rows for a deadline after the captured
    week, which it leaves out because the captured squad does not hold them yet.
    """

    prices: Mapping[int, int] = field(default_factory=lambda: MappingProxyType({}))
    known: bool = False
    reason: str | None = None
    applied: int = 0
    free_hit_skipped: int = 0
    pending: int = 0


def _refused(reason: str) -> RebuiltPurchasePrices:
    return RebuiltPurchasePrices(MappingProxyType({}), False, reason)


def _row(transfer: EntryTransfer) -> str:
    return (
        f"the gameweek {transfer.event} transfer of element {transfer.element_out} for "
        f"element {transfer.element_in}"
    )


def rebuild_purchase_prices(
    transfers: Sequence[EntryTransfer],
    *,
    history: EntryTransferHistory,
    opening_squad: Sequence[int],
    opening_bank_tenths: int,
    budget_tenths: int,
    start_prices: Mapping[int, int],
    deadlines: Mapping[int, str],
    through_gameweek: int,
    active_chip: str | None,
    held_squad: Sequence[int],
    held_bank_tenths: int,
) -> RebuiltPurchasePrices:
    """Replay the transfers over the opening fifteen and return what each held player cost.

    ``opening_squad`` and ``opening_bank_tenths`` come from the gameweek 1 picks,
    ``start_prices`` and ``deadlines`` from the capture's bootstrap (element id to start
    price, gameweek to deadline), and ``budget_tenths`` is the season's
    ``squad_total_spend``. ``through_gameweek`` is the captured picks' gameweek and
    ``active_chip`` the chip those picks report. ``held_squad`` and ``held_bank_tenths``
    are what the member holds going into the next deadline: the captured picks, or the
    picks from before a Free Hit in the captured week.

    The checks, in order, each a refusal with its reason:

    * A history that does not start at gameweek 1 is a late joiner, whose opening squad was
      bought at a later deadline's prices that no captured document states. The history
      must also hold every week through the captured one, each with its bank, and its
      gameweek 1 bank must be the opening picks' bank.
    * The opening fifteen at their start prices plus the opening bank must be exactly the
      season's budget. This is the one check that touches the inferred prices: every
      later purchase price is ``element_in_cost``, which the source states.
    * Every row must lie inside its own gameweek's transfer window, after the previous
      deadline and before its own, and no row may be for gameweek 1. Rows made at one
      instant must not sell a player another of them buys, so their order cannot matter.
    * Rows after the captured week are pending and left out. Rows in a Free Hit week are
      skipped, because the chip reverts the squad and the bank after its week; a
      Wildcard's rows are kept, because its squad persists.
    * Each week the replay must sell only players it holds and buy only players it does
      not. Outside a Wildcard or Free Hit week, whose history counts no transfers, the
      week's row count must be the history's ``event_transfers``; outside a Free Hit week
      the replayed bank must be the history's bank for that week. A Free Hit week leaves
      the replayed bank where it was, so comparing its own row would check the source
      rather than the replay; it is skipped, which also spares a Free Hit in the captured
      week, whose row was not among the weeks the source was read against (the history
      reported the bank from before the chip for both earlier Free Hits on 2026-10-05).
    * The replay must end on the held squad and the held bank.
    """

    through = int(through_gameweek)
    if through < FIRST_GAMEWEEK:
        raise ValueError(f"through_gameweek must be positive, got {through_gameweek}.")
    weeks = history.weeks
    if not weeks:
        return _refused("the history lists no gameweek")
    opening = min(weeks)
    if opening != FIRST_GAMEWEEK:
        return _refused(
            f"the history starts at gameweek {opening}: a squad opened at a later deadline "
            "was bought at that deadline's prices, which no captured document states"
        )
    missing = [week for week in range(FIRST_GAMEWEEK, through + 1) if week not in weeks]
    if missing:
        return _refused(f"the history has no row for gameweek {format_examples(missing)}")
    unbanked = [week for week in range(FIRST_GAMEWEEK, through + 1) if weeks[week].bank is None]
    if unbanked:
        return _refused(f"the history states no bank for gameweek {format_examples(unbanked)}")
    if weeks[FIRST_GAMEWEEK].bank != opening_bank_tenths:
        return _refused(
            f"the history's gameweek 1 bank is {weeks[FIRST_GAMEWEEK].bank} tenths and the "
            f"opening picks state {opening_bank_tenths}"
        )

    unpriced = [element for element in opening_squad if element not in start_prices]
    if unpriced:
        return _refused(f"no start price for opening elements {format_examples(unpriced)}")
    opening_cost = sum(start_prices[element] for element in opening_squad)
    if opening_cost + opening_bank_tenths != budget_tenths:
        return _refused(
            f"the opening fifteen at their start prices cost {opening_cost} tenths and the "
            f"opening bank is {opening_bank_tenths}, which is not the season's budget of "
            f"{budget_tenths}: they were not bought at the start prices"
        )

    for transfer in transfers:
        if transfer.event <= FIRST_GAMEWEEK:
            return _refused(
                f"{_row(transfer)} is listed for the opening gameweek, whose squad is built "
                "without transfers"
            )
        before, until = deadlines.get(transfer.event - 1), deadlines.get(transfer.event)
        if before is None or until is None:
            return _refused(f"the capture states no deadline around {_row(transfer)}")
        if not as_instant(before) < as_instant(transfer.time_utc) < as_instant(until):
            return _refused(
                f"{_row(transfer)} was made at {transfer.time_utc}, outside its window from "
                f"{before} to {until}"
            )
    ordered = sorted(transfers, key=lambda transfer: as_instant(transfer.time_utc))
    for instant, tied in groupby(ordered, key=lambda transfer: as_instant(transfer.time_utc)):
        rows = list(tied)
        crossing = {row.element_out for row in rows} & {row.element_in for row in rows}
        if crossing:
            return _refused(
                f"transfers made at one instant ({instant.isoformat()}) sell and buy elements "
                f"{format_examples(sorted(crossing))}, so the order they were made in decides "
                "the squad and the document does not state it"
            )

    free_hits = set(history.chips_used.get(FREE_HIT_CHIP, ()))
    chip_weeks = {
        event
        for name, events in history.chips_used.items()
        if name in TRANSFER_CHIPS
        for event in events
    }
    if active_chip == FREE_HIT_CHIP:
        free_hits.add(through)
    if active_chip in TRANSFER_CHIPS:
        chip_weeks.add(through)

    by_week: dict[int, list[EntryTransfer]] = {}
    pending = 0
    for transfer in ordered:
        if transfer.event > through:
            pending += 1
        else:
            by_week.setdefault(transfer.event, []).append(transfer)

    prices = {int(element): start_prices[element] for element in opening_squad}
    bank = int(opening_bank_tenths)
    applied = skipped = 0
    for week in range(FIRST_GAMEWEEK + 1, through + 1):
        rows = by_week.get(week, [])
        counted = weeks[week].transfers
        if week not in chip_weeks and len(rows) != counted:
            return _refused(
                f"gameweek {week} lists {len(rows)} transfers and the history counts {counted}"
            )
        if week in free_hits:
            skipped += len(rows)
            continue
        for transfer in rows:
            if transfer.element_out not in prices:
                return _refused(f"{_row(transfer)} sells a player the replay does not hold")
            if transfer.element_in in prices:
                return _refused(f"{_row(transfer)} buys a player the replay already holds")
            del prices[transfer.element_out]
            # A player bought again after a sale was bought at the new price, so the last
            # purchase is the one that stands.
            prices[transfer.element_in] = transfer.element_in_cost
            bank += transfer.element_out_cost - transfer.element_in_cost
            applied += 1
        if bank != weeks[week].bank:
            return _refused(
                f"after gameweek {week} the replayed bank is {bank} tenths and the history "
                f"states {weeks[week].bank}"
            )

    held = {int(element) for element in held_squad}
    if set(prices) != held:
        surplus = sorted(set(prices) - held)
        absent = sorted(held - set(prices))
        return _refused(
            f"the replay ends holding elements {format_examples(surplus)} that the captured "
            f"squad does not, and without elements {format_examples(absent)} that it does"
        )
    if bank != held_bank_tenths:
        return _refused(
            f"the replay ends with {bank} tenths in the bank and the captured picks state "
            f"{held_bank_tenths}"
        )
    return RebuiltPurchasePrices(
        prices=MappingProxyType(dict(prices)),
        known=True,
        applied=applied,
        free_hit_skipped=skipped,
        pending=pending,
    )
