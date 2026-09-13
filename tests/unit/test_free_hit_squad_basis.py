"""A Free Hit squad lasts one week: the advice must stand on the squad held before it.

Two real entries (4287206 and 5662073, capture ``fpl-live-20260910T190430Z-369360398135``)
played their Free Hit in gameweek 3. Their gameweek-4 squad is their gameweek-2 squad
with the gameweek-2 bank; the fifteen in ``picks-gw03.json`` are void at the deadline.
Before this fix the provider read the Free Hit squad as the held one and the site advised
transfers from a squad the member did not have.

Three seams are covered: the parser reports the chip, the capture reads the week before
a Free Hit week (and walks back while that week was a Free Hit too), and the provider
resolves the basis or refuses with a reason when the earlier document is not on disk.
A Wildcard, Bench Boost or Triple Captain week keeps the captured squad.

A fourth seam asks the same question of our own record: the ledger path and the member
path share one walk-back (``live.free_hit``) and are pinned here to the same squad on the
same input, because a ledger that stepped back exactly once resolved two Free Hits in a
row to a squad that never existed.
"""

import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import tests.unit.test_league_views as league_module
import tests.unit.test_public_probability_guards as guards_module
import tests.unit.test_source_fpl_live as payload_module

from squadopt.application.capture_entries import CapturePicksProvider
from squadopt.application.entries import (
    CAPTURED_SQUAD_BASIS,
    EntryError,
    EntryPicks,
    EntryRegistration,
    pre_free_hit_basis,
)
from squadopt.application.league_views import build_league_views
from squadopt.data.sources.fpl_live import entry_active_chip, fpl_entry_picks
from squadopt.live import LedgerEntry, LedgerError, ledger
from squadopt.platform import fpl_capture

ENTRY = 11
SNAPSHOT = "fpl-live-20260910T190430Z-369360398135"

world = league_module.world  # re-register the fixture in this module
FREE_HIT_SQUAD = list(range(201, 216))
HELD_SQUAD = list(range(101, 116))
OLDER_SQUAD = list(range(301, 316))


def _picks(squad: list[int], *, chip: str | None, bank: int) -> bytes:
    document = json.loads(payload_module._picks_payload(squad=squad, bank=bank))
    document["active_chip"] = chip
    return json.dumps(document).encode("utf-8")


def _history(chips: list[tuple[str, int]]) -> bytes:
    return payload_module._history_payload(
        chips=[
            {"name": name, "time": "2026-08-31T23:32:45Z", "event": event} for name, event in chips
        ],
        current=[
            {
                "event": event,
                "points": 50,
                "total_points": 50 * event,
                "event_transfers": 0,
                "event_transfers_cost": 0,
                "points_on_bench": 3,
                "bank": bank,
            }
            for event, bank in ((1, 30), (2, 20), (3, 5))
        ],
    )


def _bootstrap() -> bytes:
    elements = [
        {"id": element, "code": element + 1000}
        for element in FREE_HIT_SQUAD + HELD_SQUAD + OLDER_SQUAD
    ]
    return json.dumps({"elements": elements}).encode("utf-8")


def _provider(payloads: dict[str, bytes]) -> CapturePicksProvider:
    payloads = {"bootstrap-static.json": _bootstrap(), **payloads}
    return CapturePicksProvider(SimpleNamespace(payloads=payloads), SNAPSHOT)


def _codes(elements: list[int]) -> tuple[int, ...]:
    return tuple(element + 1000 for element in elements)


# --- the parser reports the chip ------------------------------------------------------


def test_the_parser_reports_the_active_chip_and_a_null_as_none() -> None:
    assert entry_active_chip(_picks(HELD_SQUAD, chip=None, bank=5), entry_id=1, gameweek=1) is None
    assert (
        entry_active_chip(_picks(HELD_SQUAD, chip="freehit", bank=5), entry_id=1, gameweek=3)
        == "freehit"
    )
    record = fpl_entry_picks(
        _picks(FREE_HIT_SQUAD, chip="freehit", bank=5),
        _history([("freehit", 3)]),
        entry_id=ENTRY,
        season="2026-27",
        gameweek=3,
    )
    assert record.active_chip == "freehit"


# --- the provider resolves the basis --------------------------------------------------


def test_a_free_hit_week_resolves_to_the_squad_and_bank_held_before_it() -> None:
    provider = _provider(
        {
            f"entry-{ENTRY}-picks-gw03.json": _picks(FREE_HIT_SQUAD, chip="freehit", bank=5),
            f"entry-{ENTRY}-picks-gw02.json": _picks(HELD_SQUAD, chip=None, bank=20),
            f"entry-{ENTRY}-history.json": _history([("freehit", 3)]),
        }
    )
    picks = provider.picks(ENTRY, "2026-27", 3)
    assert picks.gameweek == 3, "the picks still answer for the captured week"
    assert picks.squad == _codes(HELD_SQUAD)
    assert picks.starting_xi == _codes(HELD_SQUAD[:11])
    assert picks.captain == HELD_SQUAD[0] + 1000
    assert picks.bank_tenths == 20, "the bank is the pre-Free-Hit week's"
    assert picks.chips_used == {"freehit": (3,)}, "the chip still counts as played"
    assert picks.active_chip == "freehit"
    assert picks.squad_basis == pre_free_hit_basis(2) == "pre_free_hit_gw02"
    assert picks.source_snapshot_id == SNAPSHOT


def test_without_the_earlier_document_the_provider_refuses_rather_than_guessing() -> None:
    provider = _provider(
        {
            f"entry-{ENTRY}-picks-gw03.json": _picks(FREE_HIT_SQUAD, chip="freehit", bank=5),
            f"entry-{ENTRY}-history.json": _history([("freehit", 3)]),
        }
    )
    with pytest.raises(EntryError) as raised:
        provider.picks(ENTRY, "2026-27", 3)
    message = str(raised.value)
    assert f"Entry {ENTRY}" in message
    assert "Free Hit in gameweek 3" in message
    assert f"entry-{ENTRY}-picks-gw02.json" in message


def test_two_free_hits_in_a_row_walk_back_to_the_week_before_both() -> None:
    provider = _provider(
        {
            f"entry-{ENTRY}-picks-gw03.json": _picks(FREE_HIT_SQUAD, chip="freehit", bank=5),
            f"entry-{ENTRY}-picks-gw02.json": _picks(HELD_SQUAD, chip="freehit", bank=20),
            f"entry-{ENTRY}-picks-gw01.json": _picks(OLDER_SQUAD, chip=None, bank=30),
            f"entry-{ENTRY}-history.json": _history([("freehit", 2), ("freehit", 3)]),
        }
    )
    picks = provider.picks(ENTRY, "2026-27", 3)
    assert picks.squad == _codes(OLDER_SQUAD)
    assert picks.bank_tenths == 30
    assert picks.squad_basis == "pre_free_hit_gw01"


def test_a_free_hit_in_the_opening_week_has_nothing_to_fall_back_on() -> None:
    provider = _provider(
        {
            f"entry-{ENTRY}-picks-gw01.json": _picks(FREE_HIT_SQUAD, chip="freehit", bank=5),
            f"entry-{ENTRY}-history.json": _history([("freehit", 1)]),
        }
    )
    with pytest.raises(EntryError, match="no earlier gameweek"):
        provider.picks(ENTRY, "2026-27", 1)


@pytest.mark.parametrize("chip", ["wildcard", "bboost", "3xc", None])
def test_every_other_chip_keeps_the_captured_squad(chip: str | None) -> None:
    """A Wildcard squad *is* the new base; Bench Boost and Triple Captain move nothing."""

    provider = _provider(
        {
            f"entry-{ENTRY}-picks-gw03.json": _picks(FREE_HIT_SQUAD, chip=chip, bank=5),
            # Present and different, to prove it is not read.
            f"entry-{ENTRY}-picks-gw02.json": _picks(HELD_SQUAD, chip=None, bank=20),
            f"entry-{ENTRY}-history.json": _history([] if chip is None else [(chip, 3)]),
        }
    )
    picks = provider.picks(ENTRY, "2026-27", 3)
    assert picks.squad == _codes(FREE_HIT_SQUAD)
    assert picks.bank_tenths == 5
    assert picks.active_chip == chip
    assert picks.squad_basis == CAPTURED_SQUAD_BASIS == "captured"


def test_the_application_type_validates_the_basis_descriptor() -> None:
    base = dict(
        entry_id=1,
        season="2026-27",
        gameweek=3,
        squad=tuple(range(1, 16)),
        starting_xi=tuple(range(1, 12)),
        captain=1,
        vice_captain=2,
        bank_tenths=0,
        free_transfers=1,
    )
    assert EntryPicks(**base).squad_basis == "captured"  # type: ignore[arg-type]
    assert EntryPicks(**base).active_chip is None  # type: ignore[arg-type]
    with pytest.raises(EntryError, match="squad_basis"):
        EntryPicks(**base, squad_basis="")  # type: ignore[arg-type]
    with pytest.raises(EntryError, match="active_chip"):
        EntryPicks(**base, active_chip="")  # type: ignore[arg-type]


# --- the capture reads the week before a Free Hit -------------------------------------


def test_the_capture_names_the_week_before_each_free_hit_and_stops_at_a_kept_squad() -> None:
    payloads = {
        "bootstrap-static.json": b"{}",
        "entry-11-picks-gw03.json": _picks(FREE_HIT_SQUAD, chip="freehit", bank=5),
        "entry-22-picks-gw03.json": _picks(HELD_SQUAD, chip="wildcard", bank=5),
        "entry-33-picks-gw03.json": _picks(HELD_SQUAD, chip=None, bank=5),
        "entry-44-picks-gw03.json": b"not json",
    }
    assert dict(fpl_capture.free_hit_basis_endpoints(payloads)) == {
        "entry-11-picks-gw02.json": f"{fpl_capture.BASE_URL}/entry/11/event/2/picks/"
    }
    payloads["entry-11-picks-gw02.json"] = _picks(HELD_SQUAD, chip="freehit", bank=20)
    assert dict(fpl_capture.free_hit_basis_endpoints(payloads)) == {
        "entry-11-picks-gw01.json": f"{fpl_capture.BASE_URL}/entry/11/event/1/picks/"
    }
    payloads["entry-11-picks-gw01.json"] = _picks(OLDER_SQUAD, chip="freehit", bank=30)
    assert dict(fpl_capture.free_hit_basis_endpoints(payloads)) == {}, "never below gameweek 1"


def test_a_capture_stores_the_pre_free_hit_picks_beside_the_played_week(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from squadopt.data.snapshots import read_snapshot

    events = [
        {
            "id": week,
            "deadline_time": f"2026-09-{7 * week:02d}T17:30:00Z",
            "finished": week < 4,
        }
        for week in range(1, 5)
    ]
    teams = [{"id": 1, "code": 3, "name": "Arsenal", "short_name": "ARS"}]
    elements = [
        {
            "id": 1,
            "code": 100,
            "first_name": "A",
            "second_name": "Player",
            "team": 1,
            "element_type": 3,
            "now_cost": 55,
            "status": "a",
            "chance_of_playing_next_round": 100,
            "news": "",
        }
    ]
    reads: list[str] = []

    def fake_fetch(url: str, **_: Any) -> bytes:
        reads.append(url)
        if url.endswith("bootstrap-static/"):
            return json.dumps({"events": events, "teams": teams, "elements": elements}).encode()
        if url.endswith("fixtures/"):
            return json.dumps([{"event": 1, "kickoff_time": "2026-08-21T19:00:00Z"}]).encode()
        if url.endswith("/entry/11/event/3/picks/"):
            return _picks(FREE_HIT_SQUAD, chip="freehit", bank=5)
        if url.endswith("/entry/11/event/2/picks/"):
            return _picks(HELD_SQUAD, chip=None, bank=20)
        if url.endswith("/entry/22/event/3/picks/"):
            return _picks(HELD_SQUAD, chip="wildcard", bank=5)
        if url.endswith("/entry/11/history/"):
            return _history([("freehit", 3)])
        return json.dumps({"read": url}).encode("utf-8")

    monkeypatch.setattr(fpl_capture, "_utc_now", lambda: "2026-09-25T19:00:00Z")
    monkeypatch.setattr(fpl_capture, "fetch", fake_fetch)
    registry = tmp_path / "registry.json"
    registry.write_text(
        json.dumps(
            {
                "contract_version": "entry_registry_v1",
                "entries": [
                    {
                        "entry_id": i,
                        "label": f"Team {i}",
                        "registered_at_utc": "2026-08-25T09:00:00Z",
                    }
                    for i in (11, 22)
                ],
            }
        ),
        encoding="utf-8",
    )
    written = fpl_capture.capture(tmp_path / "snapshots", entry_registry=registry)
    assert written is not None
    snapshot = read_snapshot(tmp_path / "snapshots", written.snapshot_id)
    entry_documents = {name for name in snapshot.payloads if name.startswith("entry-")}
    assert entry_documents == {
        "entry-11.json",
        "entry-11-history.json",
        "entry-11-picks-gw03.json",
        "entry-11-picks-gw02.json",
        "entry-22.json",
        "entry-22-history.json",
        "entry-22-picks-gw03.json",
    }
    assert reads.count(f"{fpl_capture.BASE_URL}/entry/11/event/2/picks/") == 1
    assert not any(url.endswith("/entry/22/event/2/picks/") for url in reads)
    # The stored earlier document is what the provider then resolves on.
    provider = CapturePicksProvider(
        SimpleNamespace(payloads={**snapshot.payloads, "bootstrap-static.json": _bootstrap()}),
        written.snapshot_id,
    )
    assert provider.picks(11, "2026-27", 3).squad_basis == "pre_free_hit_gw02"


def test_the_free_transfers_are_the_captured_weeks_not_the_basis_weeks() -> None:
    """A Free Hit voids the squad, not the bank of free transfers: the count for the GW4
    deadline is derived through the chip week (none at GW1, one for GW2, one saved into
    GW3 whose own transfer paid for the chip, then one more for GW4), while the GW2 basis
    document would not know the chip week at all."""

    bootstrap = {
        **json.loads(_bootstrap()),
        "game_config": {"rules": {"max_extra_free_transfers": 4}},
    }
    provider = CapturePicksProvider(
        SimpleNamespace(
            payloads={
                "bootstrap-static.json": json.dumps(bootstrap).encode("utf-8"),
                f"entry-{ENTRY}-picks-gw03.json": _picks(FREE_HIT_SQUAD, chip="freehit", bank=5),
                f"entry-{ENTRY}-picks-gw02.json": _picks(HELD_SQUAD, chip=None, bank=20),
                f"entry-{ENTRY}-history.json": _history([("freehit", 3)]),
            }
        ),
        SNAPSHOT,
    )
    picks = provider.picks(ENTRY, "2026-27", 3)
    assert picks.squad_basis == pre_free_hit_basis(2)
    assert (picks.free_transfers, picks.free_transfers_known) == (2, True)


# --- one rule, one answer, on both walk-back paths ------------------------------------

FIRST_FREE_HIT, SECOND_FREE_HIT = 19, 20
BASIS_WEEK = FIRST_FREE_HIT - 1


def _history_through(week: int, chips: list[tuple[str, int]]) -> bytes:
    return payload_module._history_payload(
        chips=[
            {"name": name, "time": "2026-12-27T11:00:00Z", "event": event} for name, event in chips
        ],
        current=[
            {
                "event": event,
                "points": 50,
                "total_points": 50 * event,
                "event_transfers": 0,
                "event_transfers_cost": 0,
                "points_on_bench": 3,
                "bank": 20,
            }
            for event in range(1, week + 1)
        ],
    )


def _ledger_entry(gameweek: int, squad: list[int], *, chip: str | None, bank: int) -> LedgerEntry:
    """One recorded decision, in the shape ``held_squad_from_ledger`` reads."""

    players = list(_codes(squad))
    return LedgerEntry(
        season="2026-27",
        gameweek=gameweek,
        decision={
            "squad_player_ids": players,
            "total_cost_tenths": 1000 - bank,
            "transfers": {
                "chip": chip,
                "bank_after_tenths": bank,
                "free_transfers_after": 2 if chip == "freehit" else 1,
                "purchase_prices": {str(player): 50 for player in players},
            },
        },
        outcome=None,
        directory=Path("recorded"),
    )


def _held_from_ledger(
    monkeypatch: pytest.MonkeyPatch, entries: tuple[LedgerEntry, ...], *, before: int
) -> Any:
    monkeypatch.setattr(ledger, "load_ledger", lambda root, season: entries)
    return ledger.held_squad_from_ledger(
        Path("recorded"), "2026-27", before_gameweek=before, budget_tenths=1000
    )


def test_both_walk_back_paths_resolve_two_free_hits_to_the_same_squad(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A member's captured picks and our own ledger answer the same question, so they
    must give the same answer. Gameweeks 19 and 20 are the only consecutive pair the
    halves allow, and the rule now forbids even that, so two in a row can only reach
    either path as a damaged record: the honest answer is still the squad held before
    both, never the void fifteen of the earlier chip week.
    """

    provider = _provider(
        {
            f"entry-{ENTRY}-picks-gw{SECOND_FREE_HIT}.json": _picks(
                FREE_HIT_SQUAD, chip="freehit", bank=5
            ),
            f"entry-{ENTRY}-picks-gw{FIRST_FREE_HIT}.json": _picks(
                HELD_SQUAD, chip="freehit", bank=15
            ),
            f"entry-{ENTRY}-picks-gw{BASIS_WEEK}.json": _picks(OLDER_SQUAD, chip=None, bank=30),
            f"entry-{ENTRY}-history.json": _history_through(
                SECOND_FREE_HIT, [("freehit", FIRST_FREE_HIT), ("freehit", SECOND_FREE_HIT)]
            ),
        }
    )
    picks = provider.picks(ENTRY, "2026-27", SECOND_FREE_HIT)

    held = _held_from_ledger(
        monkeypatch,
        (
            _ledger_entry(BASIS_WEEK, OLDER_SQUAD, chip=None, bank=30),
            _ledger_entry(FIRST_FREE_HIT, HELD_SQUAD, chip="freehit", bank=15),
            _ledger_entry(SECOND_FREE_HIT, FREE_HIT_SQUAD, chip="freehit", bank=5),
        ),
        before=SECOND_FREE_HIT + 1,
    )

    assert held.squad_player_ids == picks.squad == _codes(OLDER_SQUAD)
    assert held.bank_tenths == picks.bank_tenths == 30
    assert picks.squad_basis == pre_free_hit_basis(BASIS_WEEK) == "pre_free_hit_gw18"
    assert held.decided_gameweek == SECOND_FREE_HIT
    # The squad walks back; the free transfers are the chip week's own and do not.
    assert held.free_transfers == 2


def test_the_ledger_names_the_week_it_walked_to_rather_than_using_a_free_hit_squad(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Stepping back exactly once landed on the earlier Free Hit week and took its squad,
    a fifteen the manager never held. With nothing before the pair recorded, the refusal
    names gameweek 18, the week the walk actually needs.
    """

    entries = (
        _ledger_entry(FIRST_FREE_HIT, HELD_SQUAD, chip="freehit", bank=15),
        _ledger_entry(SECOND_FREE_HIT, FREE_HIT_SQUAD, chip="freehit", bank=5),
    )
    with pytest.raises(LedgerError) as raised:
        _held_from_ledger(monkeypatch, entries, before=SECOND_FREE_HIT + 1)
    assert f"GW{BASIS_WEEK}'s" in str(raised.value)


# --- one member's refusal does not sink the league ------------------------------------


class _RefusingProvider:
    """Member 999 is the pre-fix capture: a Free Hit week with no earlier document."""

    def __init__(self, picks: EntryPicks) -> None:
        self._picks = picks

    def picks(self, entry_id: int, season: str, gameweek: int) -> EntryPicks:
        if entry_id == 999:
            raise EntryError(
                "Entry 999 played a Free Hit in gameweek 3, so its squad for the coming "
                "deadline is the one held before it, but the capture holds no "
                "entry-999-picks-gw02.json. Re-capture with --entries."
            )
        return self._picks


def test_a_members_free_hit_refusal_renders_as_unavailable_with_its_reason(
    world: dict[str, Any], tmp_path: Path
) -> None:
    inputs, projection, rules = league_module._world_context(world)
    squad = league_module._legal_squad(world)
    provider = _RefusingProvider(league_module._member_picks(world, 101, squad))
    report = build_league_views(
        provider,
        (
            EntryRegistration(101, "member-a", "2026-08-23T00:00:00Z"),
            EntryRegistration(999, "member-free-hit", "2026-08-23T00:00:00Z"),
        ),
        inputs,
        projection,
        rules,
        league_id=352490,
        league_name="Test League",
        out_dir=tmp_path / "league",
    )
    assert report.rendered_count == 1
    by_entry = {member.entry_id: member for member in report.members}
    assert by_entry[101].rendered
    assert not by_entry[999].rendered
    assert "entry-999-picks-gw02.json" in by_entry[999].reason
    assert (tmp_path / "league" / "advice" / "101" / "saf-puan" / "1.json").is_file()
    # The refused member used to get no advice directory at all, so the page could only
    # say "unavailable". Now it gets an index and nothing else: the index is where the
    # page reads reasons, and the reason it carries is the one the build report names.
    refused_dir = tmp_path / "league" / "advice" / "999"
    assert sorted(path.name for path in refused_dir.iterdir()) == ["index.json"]
    index = json.loads((refused_dir / "index.json").read_text(encoding="utf-8"))["payload"]
    assert {item["reason"] for item in index["unavailable"]} == {by_entry[999].reason}
    assert index["computed"] == []
    members = json.loads((tmp_path / "league" / "members.json").read_text(encoding="utf-8"))
    rows = {row["entry_id"]: row for row in members["payload"]["members"]}
    assert rows[999]["data_quality"] == "empty"
    assert rows[101]["data_quality"] != "empty"


def _assert_index_under_contract(index: dict[str, Any], entry_id: int) -> None:
    """The rules ``web/src/features/league/publicationShape.ts`` ``assertAdviceIndex`` applies."""

    def positive(value: object) -> bool:
        return isinstance(value, int) and not isinstance(value, bool) and value > 0

    assert index["entry_id"] == entry_id
    assert positive(index["league_id"]) and positive(index["gameweek"])
    assert isinstance(index["season"], str)
    assert index["window"] in (1, 3, 5)
    assert index["strategies"] and all(isinstance(s, str) for s in index["strategies"])
    assert all(positive(rival) for rival in index["rival_entry_ids"])
    assert index["default_rival_entry_id"] is None or positive(index["default_rival_entry_id"])
    assert isinstance(index["computed"], list)
    for item in index["unavailable"]:
        assert isinstance(item["strategy"], str) and isinstance(item["reason"], str)
        assert item["rival_entry_id"] is None or positive(item["rival_entry_id"])
        assert item.get("window", 1) in (1, 3, 5)
    assert all(
        isinstance(windows, list) and all(w in (1, 3, 5) for w in windows)
        for windows in index["windows"].values()
    )
    assert index["suggested_strategy"] is None


def _build_with_refusal(world: dict[str, Any], out: Path, *members: int) -> Any:
    inputs, projection, rules = league_module._world_context(world)
    provider = _RefusingProvider(
        league_module._member_picks(world, 101, league_module._legal_squad(world))
    )
    return build_league_views(
        provider,
        tuple(EntryRegistration(m, f"member-{m}", "2026-08-23T00:00:00Z") for m in members),
        inputs,
        projection,
        rules,
        league_id=352490,
        league_name="Test League",
        out_dir=out,
        now=datetime(2026, 8, 23, 12, tzinfo=UTC),
    )


def test_a_refused_members_index_keeps_the_published_contract_and_the_sweep(
    world: dict[str, Any], tmp_path: Path
) -> None:
    """One entry per declared strategy, no rival, nothing computed, no window promised;
    the reason is text we generated, so it must pass the tree's own honesty sweep."""

    out = tmp_path / "league"
    _build_with_refusal(world, out, 101, 999)
    index = json.loads((out / "advice" / "999" / "index.json").read_text(encoding="utf-8"))
    assert index["contract_version"] == "provisional_league_ui_v1"
    payload = index["payload"]
    _assert_index_under_contract(payload, 999)
    assert [item["strategy"] for item in payload["unavailable"]] == payload["strategies"]
    assert all(item["rival_entry_id"] is None for item in payload["unavailable"])
    assert payload["windows"] == {strategy: [] for strategy in payload["strategies"]}
    assert payload["rival_entry_ids"] == [101]
    assert guards_module._sweep(out) == []


def test_pruning_keeps_the_refused_index_and_removes_last_weeks_documents(
    world: dict[str, Any], tmp_path: Path
) -> None:
    """A publish into last week's tree: the refused member's old documents go, the index stays."""

    out = tmp_path / "league"
    stale = out / "advice" / "999" / "saf-puan" / "1.json"
    stale.parent.mkdir(parents=True)
    stale.write_text("{}", encoding="utf-8")
    (out / "entries").mkdir()
    (out / "entries" / "999.json").write_text("{}", encoding="utf-8")
    report = _build_with_refusal(world, out, 101, 999)
    assert report.removed == ("entries/999.json", "advice/999/saf-puan/")
    assert sorted(p.name for p in (out / "advice" / "999").iterdir()) == ["index.json"]
    assert not (out / "entries" / "999.json").exists()


def test_a_refusal_beside_a_member_leaves_that_members_documents_byte_identical(
    world: dict[str, Any], tmp_path: Path
) -> None:
    """Publishing a refused member's index changes nothing a rendered member is served."""

    alone = tmp_path / "alone"
    _build_with_refusal(world, alone, 101)
    beside = tmp_path / "beside"
    _build_with_refusal(world, beside, 101, 999)
    documents = [
        path.relative_to(alone)
        for path in sorted(alone.rglob("*.json"))
        if path.relative_to(alone).parts[:2] in (("advice", "101"), ("entries", "101.json"))
    ]
    assert Path("advice", "101", "saf-puan", "1.json") in documents
    assert Path("entries", "101.json") in documents
    for relative in documents:
        assert (alone / relative).read_bytes() == (beside / relative).read_bytes(), relative


def test_the_squad_basis_travels_to_the_published_advice_document(
    world: dict[str, Any], tmp_path: Path
) -> None:
    """The page needs to say which squad the advice stands on; the record carries it."""

    from dataclasses import replace

    from squadopt.platform.advice_documents import validate_advice_document

    inputs, projection, rules = league_module._world_context(world)
    picks = replace(
        league_module._member_picks(world, 101, league_module._legal_squad(world)),
        active_chip="freehit",
        squad_basis="pre_free_hit_gw01",
    )
    build_league_views(
        league_module._Provider({101: picks}),
        (EntryRegistration(101, "member-a", "2026-08-23T00:00:00Z"),),
        inputs,
        projection,
        rules,
        league_id=352490,
        league_name="Test League",
        out_dir=tmp_path / "league",
    )
    raw = (tmp_path / "league" / "advice" / "101" / "saf-puan" / "1.json").read_bytes()
    validate_advice_document(raw)
    assert json.loads(raw)["payload"]["squad_basis"] == "pre_free_hit_gw01"
