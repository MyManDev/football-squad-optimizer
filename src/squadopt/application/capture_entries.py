"""Read member picks from one captured response, using canonical player codes.

This offline application adapter implements EntryPicksProvider. Network transport and
backend context/cache assembly remain in the platform layer.
"""

import json

from squadopt.application.entries import EntryPicks
from squadopt.data.errors import DataError
from squadopt.data.sources.fpl_live import fpl_entry_picks


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

    def _code(self, element: int) -> int:
        code = self._code_by_element.get(int(element))
        if code is None:
            raise DataError(
                f"The capture's bootstrap does not name element {element}, so the squad "
                "cannot be resolved to the ids the projection uses."
            )
        return code

    def picks(self, entry_id: int, season: str, gameweek: int) -> EntryPicks:
        picks_name = f"entry-{entry_id}-picks-gw{gameweek:02d}.json"
        history_name = f"entry-{entry_id}-history.json"
        for name in (picks_name, history_name):
            if name not in self._payloads:
                raise DataError(f"The capture holds no {name}; re-capture with --entries.")
        record = fpl_entry_picks(
            self._payloads[picks_name],
            self._payloads[history_name],
            entry_id=entry_id,
            season=season,
            gameweek=gameweek,
            source_snapshot_id=self._snapshot_id,
        )
        # The data record and the application type are twins by design: same field names,
        # no translation table, so a drift on either side is a type error rather than a
        # silently wrong squad.
        return EntryPicks(
            entry_id=record.entry_id,
            season=record.season,
            gameweek=record.gameweek,
            squad=tuple(self._code(player) for player in record.squad),
            starting_xi=tuple(self._code(player) for player in record.starting_xi),
            captain=self._code(record.captain),
            vice_captain=self._code(record.vice_captain),
            bank_tenths=record.bank_tenths,
            free_transfers=record.free_transfers,
            free_transfers_known=record.free_transfers_known,
            chips_used=record.chips_used,
            purchase_prices={
                self._code(player): price for player, price in record.purchase_prices.items()
            },
            purchase_prices_known=record.purchase_prices_known,
            source_snapshot_id=record.source_snapshot_id,
        )
