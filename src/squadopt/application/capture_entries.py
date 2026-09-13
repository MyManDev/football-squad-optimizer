"""Read member picks from one captured response, using canonical player codes.

This offline application adapter implements EntryPicksProvider. Network transport and
backend context/cache assembly remain in the platform layer.
"""

import json

from squadopt.application.entries import (
    CAPTURED_SQUAD_BASIS,
    EntryError,
    EntryPicks,
    pre_free_hit_basis,
)
from squadopt.data.errors import DataError
from squadopt.data.sources.fpl_live import (
    EntryPicksRecord,
    entry_transfer_history,
    fpl_entry_picks,
)
from squadopt.live.banking import BankedFreeTransfers, banked_free_transfers
from squadopt.live.free_hit import FIRST_GAMEWEEK, FREE_HIT_CHIP, free_hit_basis_gameweek
from squadopt.live.rules import free_transfer_cap


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

    def picks(self, entry_id: int, season: str, gameweek: int) -> EntryPicks:
        record = self._record(entry_id, season, gameweek)
        basis, squad_basis = self._basis(record)
        banked = self._banked(record)
        # The data record and the application type are twins by design: same field names,
        # no translation table, so a drift on either side is a type error rather than a
        # silently wrong squad. Identity, chips and the active chip come from the captured
        # week, and so do the free transfers, derived here rather than read off the record
        # (the bank of free transfers runs through a Free Hit week untouched, so the
        # captured week's derivation is the one for the coming deadline); the squad and
        # bank from the basis week (the same record unless a Free Hit voided the captured
        # one).
        return EntryPicks(
            entry_id=record.entry_id,
            season=record.season,
            gameweek=record.gameweek,
            squad=tuple(self._code(player) for player in basis.squad),
            starting_xi=tuple(self._code(player) for player in basis.starting_xi),
            captain=self._code(basis.captain),
            vice_captain=self._code(basis.vice_captain),
            bank_tenths=basis.bank_tenths,
            # The selling value of the basis week's fifteen, from the same document as
            # its bank: after a Free Hit both belong to the week before the chip, so a
            # budget taken from the chip week's squad would price a squad the member
            # does not hold.
            squad_sell_value_tenths=basis.squad_sell_value_tenths,
            free_transfers=banked.count,
            free_transfers_known=banked.known,
            chips_used=record.chips_used,
            purchase_prices={
                self._code(player): price for player, price in basis.purchase_prices.items()
            },
            purchase_prices_known=basis.purchase_prices_known,
            source_snapshot_id=record.source_snapshot_id,
            active_chip=record.active_chip,
            squad_basis=squad_basis,
        )
