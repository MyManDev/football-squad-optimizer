"""Read member picks from one captured response, using canonical player codes.

This offline application adapter implements EntryPicksProvider. Network transport and
backend context/cache assembly remain in the platform layer.
"""

import json
from collections.abc import Mapping
from dataclasses import dataclass

from squadopt.application.entries import (
    CAPTURED_SQUAD_BASIS,
    EntryError,
    EntryPicks,
    pre_free_hit_basis,
)
from squadopt.data.errors import DataError, format_examples
from squadopt.data.sources.fpl_live import (
    BOOTSTRAP_PAYLOAD,
    EntryPicksRecord,
    element_prices,
    entry_history_payload,
    entry_picks_payload,
    entry_transfer_history,
    entry_transfers,
    entry_transfers_payload,
    fpl_entry_picks,
    gameweek_deadlines,
)
from squadopt.live.banking import BankedFreeTransfers, banked_free_transfers
from squadopt.live.free_hit import FIRST_GAMEWEEK, FREE_HIT_CHIP, free_hit_basis_gameweek
from squadopt.live.purchase_prices import RebuiltPurchasePrices, rebuild_purchase_prices
from squadopt.live.rules import free_transfer_cap, squad_budget_tenths, transfer_sell_on_fee
from squadopt.planning.pricing import sell_price_tenths


def capture_element_codes(payloads: object) -> dict[int, int]:
    """Map the capture's per-season element ids onto the codes everything else uses."""

    document = json.loads(payloads["bootstrap-static.json"].decode("utf-8"))  # type: ignore[index]
    elements = document.get("elements")
    if not isinstance(elements, list):
        raise DataError("The capture's bootstrap payload carries no elements list.")
    return {
        int(element["id"]): int(element["code"])
        for element in elements
        if isinstance(element, dict) and "id" in element and "code" in element
    }


@dataclass(frozen=True, slots=True)
class _RebuildInputs:
    """What every member's purchase-price rebuild reads from the capture's bootstrap."""

    start_prices: Mapping[int, int]
    current_prices: Mapping[int, int]
    sell_on_fee: float
    budget_tenths: int
    deadlines: Mapping[int, str]


@dataclass(frozen=True, slots=True)
class _PricedSquad:
    """A member's rebuilt purchase prices and, where they are known, the selling value of
    the held fifteen at the capture's prices under the planner's own rule and fee."""

    rebuilt: RebuiltPurchasePrices
    squad_sell_value_tenths: int | None = None


def _unknown(reason: str) -> _PricedSquad:
    return _PricedSquad(RebuiltPurchasePrices(reason=reason))


class CapturePicksProvider:
    """Serves each member's picks from the capture's own payloads.

    Implements ``application.entries.EntryPicksProvider`` structurally: the protocol is
    declared by the application layer; this adapter only reads captured bytes.
    """

    def __init__(self, snapshot: object, snapshot_id: str) -> None:
        self._payloads = getattr(snapshot, "payloads", {})
        self._snapshot_id = snapshot_id
        self._code_by_element = capture_element_codes(self._payloads)
        # The banking cap the season's settings state; None leaves the count unknown.
        self._max_free_transfers = free_transfer_cap(self._payloads["bootstrap-static.json"])
        # Read on the first member who has both documents of a rebuild, never before: a
        # capture from before the transfers list was read, and the minimal bootstraps the
        # tests build, carry no prices this would have to parse. A string is why not.
        self._rebuild_inputs: _RebuildInputs | str | None = None
        self._priced: dict[tuple[int, str, int], _PricedSquad] = {}

    def _code(self, element: int) -> int:
        code = self._code_by_element.get(int(element))
        if code is None:
            raise DataError(
                f"The capture's bootstrap does not name element {element}, so the squad "
                "cannot be resolved to the ids the projection uses."
            )
        return code

    def _record(self, entry_id: int, season: str, gameweek: int) -> EntryPicksRecord:
        picks_name = f"entry-{entry_id}-picks-gw{gameweek:02d}.json"
        history_name = f"entry-{entry_id}-history.json"
        for name in (picks_name, history_name):
            if name not in self._payloads:
                raise DataError(f"The capture holds no {name}; re-capture with --entries.")
        return fpl_entry_picks(
            self._payloads[picks_name],
            self._payloads[history_name],
            entry_id=entry_id,
            season=season,
            gameweek=gameweek,
            source_snapshot_id=self._snapshot_id,
        )

    def holds(self, entry_id: int, gameweek: int) -> bool:
        """Whether the capture carries this entry's picks and history for ``gameweek``.

        A question rather than a caught error, so a caller can tell "this member was not
        captured" apart from every other way reading a squad can fail.
        """

        return all(
            name in self._payloads
            for name in (
                f"entry-{entry_id}-picks-gw{gameweek:02d}.json",
                f"entry-{entry_id}-history.json",
            )
        )

    def _banked(self, record: EntryPicksRecord) -> BankedFreeTransfers:
        """The free transfers the member holds at the deadline after the captured week.

        The parser reports the rule floor with the flag down; the banking model derives
        the count from the same history under the season's cap, and the captured week's
        own chip is read from the picks document because the history lists a chip only
        once its week is over.
        """

        history = self._payloads[f"entry-{record.entry_id}-history.json"]
        return banked_free_transfers(
            entry_transfer_history(history, entry_id=record.entry_id),
            gameweek=record.gameweek,
            max_free_transfers=self._max_free_transfers,
            active_chip=record.active_chip,
        )

    def _basis(self, captured: EntryPicksRecord) -> tuple[EntryPicksRecord, str]:
        """The record whose squad and bank the member actually holds after ``gameweek``.

        A Free Hit squad lasts its own week: at the next deadline the member's real
        fifteen, and bank, are the ones from before the chip, and the chip week costs
        no transfer. So a Free Hit week's basis is the previous week's picks — walked
        back once more if that week was a Free Hit too (two chip sets a season make it
        possible), never below gameweek 1. The walk itself is ``live.free_hit``'s, shared
        with the ledger path so that one rule keeps one answer. A Wildcard is the opposite
        case: its squad *is* the new base and persists, so it keeps the captured basis, as
        do Bench Boost and Triple Captain, which change no squad.

        When the earlier document is not in the capture the answer is a stated refusal,
        not the Free Hit squad: advice built on fifteen players the member does not
        hold is wrong advice wearing the same shape as right advice.
        """

        if captured.active_chip != FREE_HIT_CHIP:
            return captured, CAPTURED_SQUAD_BASIS
        entry_id, season = captured.entry_id, captured.season
        read: dict[int, EntryPicksRecord] = {}

        def was_free_hit(week: int) -> bool:
            name = f"entry-{entry_id}-picks-gw{week:02d}.json"
            if name not in self._payloads:
                raise EntryError(
                    f"Entry {entry_id} played a Free Hit in gameweek {week + 1}, so its "
                    f"squad for the coming deadline is the one held before it, but the "
                    f"capture holds no {name}. Re-capture with --entries."
                )
            read[week] = self._record(entry_id, season, week)
            return read[week].active_chip == FREE_HIT_CHIP

        week = free_hit_basis_gameweek(captured.gameweek, was_free_hit=was_free_hit)
        if week is None:
            raise EntryError(
                f"Entry {entry_id} played a Free Hit in gameweek {FIRST_GAMEWEEK} with no "
                "earlier gameweek to fall back on; its squad cannot be resolved."
            )
        return read[week], pre_free_hit_basis(week)

    def _rebuild_reads(self) -> _RebuildInputs | str:
        """The bootstrap's prices, fee, budget and deadlines, or why a rebuild cannot use them.

        The fee and the budget are the fields ``read_season_rules`` reads, so the selling
        value a member's page states is the one the planner's own rule and fee give.
        """

        if self._rebuild_inputs is None:
            bootstrap = self._payloads[BOOTSTRAP_PAYLOAD]
            fee = transfer_sell_on_fee(bootstrap)
            budget = squad_budget_tenths(bootstrap)
            try:
                prices = element_prices(bootstrap)
                deadlines = gameweek_deadlines(bootstrap)
            except DataError as error:
                self._rebuild_inputs = f"the capture's bootstrap cannot price it: {error}"
            else:
                if fee is None:
                    self._rebuild_inputs = "the capture states no sell-on fee the planner applies"
                elif budget is None:
                    self._rebuild_inputs = "the capture states no squad budget"
                else:
                    self._rebuild_inputs = _RebuildInputs(
                        start_prices={e: price.start_tenths for e, price in prices.items()},
                        current_prices={e: price.current_tenths for e, price in prices.items()},
                        sell_on_fee=fee,
                        budget_tenths=budget,
                        deadlines={week.gameweek: week.deadline_utc for week in deadlines},
                    )
        return self._rebuild_inputs

    def _priced_squad(self, record: EntryPicksRecord, basis: EntryPicksRecord) -> _PricedSquad:
        """The held squad's purchase prices, rebuilt from the transfers list, and what the
        fifteen sell for at the capture's prices.

        Every way this can fail is a fallback, never an error: a capture without the
        transfers list or the opening picks (every capture before they were read, and a
        member whose documents the capture could not fetch), an unreadable document, a
        late joiner, or a check of the replay that does not hold. The member then keeps the
        parser's aggregate, as before; the reason is for the operator
        (``purchase_prices_for``).
        """

        key = (record.entry_id, record.season, record.gameweek)
        if key not in self._priced:
            self._priced[key] = self._rebuild(record, basis)
        return self._priced[key]

    def _rebuild(self, record: EntryPicksRecord, basis: EntryPicksRecord) -> _PricedSquad:
        entry_id = record.entry_id
        transfers_name = entry_transfers_payload(entry_id)
        opening_name = entry_picks_payload(entry_id, FIRST_GAMEWEEK)
        for name in (transfers_name, opening_name):
            if name not in self._payloads:
                return _unknown(f"the capture holds no {name}")
        reads = self._rebuild_reads()
        if isinstance(reads, str):
            return _unknown(reads)
        try:
            transfers = entry_transfers(self._payloads[transfers_name], entry_id=entry_id)
            opening = self._record(entry_id, record.season, FIRST_GAMEWEEK)
            history = entry_transfer_history(
                self._payloads[entry_history_payload(entry_id)], entry_id=entry_id
            )
        except DataError as error:
            return _unknown(f"a document the rebuild reads is unusable: {error}")
        rebuilt = rebuild_purchase_prices(
            transfers,
            history=history,
            opening_squad=opening.squad,
            opening_bank_tenths=opening.bank_tenths,
            budget_tenths=reads.budget_tenths,
            start_prices=reads.start_prices,
            deadlines=reads.deadlines,
            through_gameweek=record.gameweek,
            active_chip=record.active_chip,
            held_squad=basis.squad,
            held_bank_tenths=basis.bank_tenths,
        )
        if not rebuilt.known:
            return _PricedSquad(rebuilt)
        # The replay's squad identity already says this. It is asked again because a held
        # player without a price would not be refused downstream: ``held_squad_from_picks``
        # prices a missing one at the market, which is the overstatement this replaces.
        if set(rebuilt.prices) != set(basis.squad):
            return _unknown("the rebuilt prices do not cover exactly the held fifteen")
        unpriced = [element for element in basis.squad if element not in reads.current_prices]
        if unpriced:
            return _unknown(
                f"the capture states no current price for elements {format_examples(unpriced)}"
            )
        sell_value = sum(
            sell_price_tenths(
                reads.current_prices[element],
                rebuilt.prices[element],
                sell_on_fee=reads.sell_on_fee,
            )
            for element in basis.squad
        )
        return _PricedSquad(rebuilt, sell_value)

    def purchase_prices_for(
        self, entry_id: int, season: str, gameweek: int
    ) -> RebuiltPurchasePrices:
        """Whether this member's purchase prices were rebuilt for ``gameweek``, and if not, why.

        A question in the style of ``holds``, for the operator's line: the picks carry the
        flag only. Reading the member's picks or Free Hit basis raises exactly as ``picks``
        does; everything after that is an answer, not an error.
        """

        record = self._record(entry_id, season, gameweek)
        basis, _ = self._basis(record)
        return self._priced_squad(record, basis).rebuilt

    def picks(self, entry_id: int, season: str, gameweek: int) -> EntryPicks:
        record = self._record(entry_id, season, gameweek)
        basis, squad_basis = self._basis(record)
        banked = self._banked(record)
        priced = self._priced_squad(record, basis)
        if priced.rebuilt.known and priced.squad_sell_value_tenths is not None:
            # What was paid for each held player, so the planner applies the rule player by
            # player; and the fifteen's selling value under that rule at the capture's
            # prices, so the budget a page states is the budget the plan was held to.
            purchase_prices = {
                self._code(player): price for player, price in priced.rebuilt.prices.items()
            }
            purchase_prices_known = True
            squad_sell_value = priced.squad_sell_value_tenths
        else:
            purchase_prices = {
                self._code(player): price for player, price in basis.purchase_prices.items()
            }
            purchase_prices_known = basis.purchase_prices_known
            squad_sell_value = basis.squad_sell_value_tenths
        # The data record and the application type are twins by design: same field names,
        # no translation table, so a drift on either side is a type error rather than a
        # silently wrong squad. Identity, chips and the active chip come from the captured
        # week, and so do the free transfers, derived here rather than read off the record
        # (the bank of free transfers runs through a Free Hit week untouched, so the
        # captured week's derivation is the one for the coming deadline); the squad and
        # bank from the basis week (the same record unless a Free Hit voided the captured
        # one), and so do the purchase prices, set above in the parser's place where the
        # rebuild held, as the free transfers are.
        return EntryPicks(
            entry_id=record.entry_id,
            season=record.season,
            gameweek=record.gameweek,
            squad=tuple(self._code(player) for player in basis.squad),
            starting_xi=tuple(self._code(player) for player in basis.starting_xi),
            captain=self._code(basis.captain),
            vice_captain=self._code(basis.vice_captain),
            bank_tenths=basis.bank_tenths,
            # The selling value of the basis week's fifteen: after a Free Hit the squad and
            # the bank both belong to the week before the chip, so a budget taken from the
            # chip week's squad would price a squad the member does not hold. Rebuilt, it
            # is the rule's sum over that fifteen; otherwise the parser's ``value - bank``
            # from the same document as the bank, a market value that overstates it.
            squad_sell_value_tenths=squad_sell_value,
            free_transfers=banked.count,
            free_transfers_known=banked.known,
            chips_used=record.chips_used,
            purchase_prices=purchase_prices,
            purchase_prices_known=purchase_prices_known,
            source_snapshot_id=record.source_snapshot_id,
            active_chip=record.active_chip,
            squad_basis=squad_basis,
        )
