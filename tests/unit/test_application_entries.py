"""Phase C seam: entry picks, the registry, and the held squad the planner starts from."""

import json
from pathlib import Path

import pytest

from squadopt.application.entries import (
    ENTRY_REGISTRY_CONTRACT_VERSION,
    EntryError,
    EntryPicks,
    EntryPicksProvider,
    EntryRegistry,
    held_squad_from_picks,
)

SQUAD = tuple(range(1001, 1016))
XI = SQUAD[:11]


def _picks(**overrides: object) -> EntryPicks:
    base: dict[str, object] = {
        "entry_id": 123456,
        "season": "2026-27",
        "gameweek": 1,
        "squad": SQUAD,
        "starting_xi": XI,
        "captain": XI[0],
        "bank_tenths": 5,
        "free_transfers": 1,
        "chips_used": {"wildcard": (1,)},
        "purchase_prices": {1001: 55},
        "purchase_prices_known": True,
    }
    base.update(overrides)
    return EntryPicks(**base)  # type: ignore[arg-type]


def test_picks_validate_the_shape_of_a_team() -> None:
    picks = _picks()
    assert picks.captain == XI[0]
    with pytest.raises(EntryError, match="fifteen"):
        _picks(squad=SQUAD[:14])
    with pytest.raises(EntryError, match="eleven"):
        _picks(starting_xi=XI[:10])
    with pytest.raises(EntryError, match="captain"):
        _picks(captain=SQUAD[14])
    with pytest.raises(EntryError, match="positive"):
        _picks(entry_id=0)
    with pytest.raises(EntryError, match="negative"):
        _picks(bank_tenths=-1)


def test_the_held_squad_uses_purchase_prices_and_falls_back_to_current_ones() -> None:
    picks = _picks()
    prices = {p: 50 for p in SQUAD}
    held = held_squad_from_picks(picks, current_prices=prices)
    assert held.squad_player_ids == SQUAD
    assert held.purchase_prices[1001] == 55  # what was paid
    assert held.purchase_prices[1002] == 50  # fallback: current price
    assert held.bank_tenths == 5 and held.free_transfers == 1
    assert dict(held.chips_used) == {"wildcard": (1,)}
    with pytest.raises(EntryError, match="current price"):
        held_squad_from_picks(picks, current_prices={p: 50 for p in SQUAD[:10]})


def test_the_registry_loads_unique_entries_or_is_empty(tmp_path: Path) -> None:
    assert EntryRegistry.load(tmp_path / "missing.json").ids() == ()
    path = tmp_path / "registry.json"
    path.write_text(
        json.dumps(
            {
                "contract_version": ENTRY_REGISTRY_CONTRACT_VERSION,
                "entries": [
                    {"entry_id": 42, "label": "us", "registered_at_utc": "2026-08-19T10:00:00Z"},
                    {"entry_id": 7, "label": "a friend"},
                ],
            }
        ),
        encoding="utf-8",
    )
    registry = EntryRegistry.load(path)
    assert registry.ids() == (7, 42)
    assert registry.entries[0].label == "us"
    path.write_text(
        json.dumps(
            {
                "contract_version": ENTRY_REGISTRY_CONTRACT_VERSION,
                "entries": [{"entry_id": 1}, {"entry_id": 1}],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(EntryError, match="twice"):
        EntryRegistry.load(path)
    path.write_text(json.dumps({"contract_version": "other"}), encoding="utf-8")
    with pytest.raises(EntryError, match="registry"):
        EntryRegistry.load(path)


def test_a_provider_is_any_object_with_picks() -> None:
    class Fake:
        def picks(self, entry_id: int, season: str, gameweek: int) -> EntryPicks:
            return _picks(entry_id=entry_id, season=season, gameweek=gameweek)

    provider: EntryPicksProvider = Fake()
    assert provider.picks(9, "2026-27", 3).gameweek == 3


def test_purchase_prices_present_but_flagged_unknown_are_refused() -> None:
    """A consumer could not tell whether to trust them, so the pair is contradictory."""

    with pytest.raises(EntryError, match="flagged unknown"):
        _picks(purchase_prices={1: 50}, purchase_prices_known=False)


def test_known_purchase_prices_carry_the_flag() -> None:
    picks = _picks(purchase_prices={1: 50}, purchase_prices_known=True)
    assert picks.purchase_prices_known is True
    assert picks.free_transfers_known is True  # the default states the optimistic case


def test_capture_built_picks_state_their_two_unknowns() -> None:
    """The shape the data side will build: floor-of-one transfers, current-price selling."""

    picks = _picks(
        free_transfers=1,
        free_transfers_known=False,
        purchase_prices={},
        purchase_prices_known=False,
    )
    assert picks.free_transfers == 1
    assert picks.free_transfers_known is False
    assert picks.purchase_prices_known is False
    assert dict(picks.purchase_prices) == {}
