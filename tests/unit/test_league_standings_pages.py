"""A published league includes every page, from one coherent standings update."""

import json
from pathlib import Path

import pytest
from scripts import seed_entry_registry

from squadopt.application.entries import EntryRegistry
from squadopt.data.errors import DataError
from squadopt.data.snapshots import read_snapshot
from squadopt.data.sources.fpl_live import (
    fpl_captured_league_standings,
    fpl_league_standings,
    league_standings_page_payload,
    league_standings_payload,
)
from squadopt.platform import fpl_capture

LEAGUE = 77
FIRST = league_standings_payload(LEAGUE)
SECOND = league_standings_page_payload(LEAGUE, 2)


def page(number: int, start: int, stop: int, *, more: bool = False) -> bytes:
    return json.dumps(
        {
            "league": {"id": LEAGUE},
            "last_updated_data": "2026-10-21T20:00:00Z",
            "standings": {
                "page": number,
                "has_next": more,
                "results": [
                    {
                        "entry": rank + 1000,
                        "entry_name": f"Team {rank}",
                        "player_name": f"Manager {rank}",
                        "rank": rank,
                        "rank_sort": rank,
                        "last_rank": rank,
                    }
                    for rank in range(start, stop + 1)
                ],
            },
        }
    ).encode()


def test_all_77_members_are_read_and_old_single_page_answers_are_identical() -> None:
    payloads = {FIRST: page(1, 1, 50, more=True), SECOND: page(2, 51, 77)}
    members = fpl_captured_league_standings(payloads, league_id=LEAGUE)
    assert [member.entry_id for member in members] == list(range(1001, 1078))
    old = page(1, 1, 15)
    assert fpl_captured_league_standings({FIRST: old}, league_id=LEAGUE) == (
        fpl_league_standings(old, league_id=LEAGUE)
    )


@pytest.mark.parametrize(
    "fault", ["missing", "league", "page", "stamp", "duplicate", "gap", "empty"]
)
def test_incomplete_or_inconsistent_pages_refuse_the_entire_league(fault: str) -> None:
    second = json.loads(page(2, 51, 77))
    if fault == "league":
        second["league"]["id"] = 99
    elif fault == "page":
        second["standings"]["page"] = 1
    elif fault == "stamp":
        second["last_updated_data"] = "2026-10-21T21:00:00Z"
    elif fault == "duplicate":
        second["standings"]["results"][0]["entry"] = 1001
    elif fault == "gap":
        second["standings"]["results"][0]["rank_sort"] = 78
    elif fault == "empty":
        second["standings"]["results"] = []
    payloads = {FIRST: page(1, 1, 50, more=True)}
    if fault != "missing":
        payloads[SECOND] = json.dumps(second).encode()
    with pytest.raises(DataError):
        fpl_captured_league_standings(payloads, league_id=LEAGUE)


def test_the_capture_reads_each_page_once_even_when_the_league_is_named_twice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def fetch(url: str) -> bytes:
        calls.append(url)
        return page(2, 51, 77)

    monkeypatch.setattr(fpl_capture, "fetch", fetch)
    payloads = {FIRST: page(1, 1, 50, more=True)}
    added = fpl_capture.complete_league_standings(payloads, [LEAGUE, LEAGUE])
    assert calls == [f"{fpl_capture.BASE_URL}/leagues-classic/{LEAGUE}/standings/?page_standings=2"]
    assert list(added) == [SECOND]
    assert len(fpl_captured_league_standings(payloads, league_id=LEAGUE)) == 77


def test_a_1001st_member_is_refused_without_fetching_more(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(fpl_capture, "fetch", lambda url: calls.append(url))
    for first in (page(1, 1, 1001), page(1, 1, 1000, more=True)):
        with pytest.raises(DataError, match="1000-member"):
            fpl_capture.complete_league_standings({FIRST: first}, [LEAGUE])
    assert calls == []


def test_an_endless_page_chain_stops_at_twenty_pages(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def fetch(url: str) -> bytes:
        calls.append(url)
        number = int(url.rsplit("=", 1)[1])
        return page(number, number, number, more=True)

    monkeypatch.setattr(fpl_capture, "fetch", fetch)
    with pytest.raises(DataError, match="20-page"):
        fpl_capture.complete_league_standings({FIRST: page(1, 1, 1, more=True)}, [LEAGUE])
    assert len(calls) == 19


def test_pagination_is_captured_before_the_stamp_and_the_offline_seed_reads_every_member(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    events: list[str] = []

    def fetch(url: str) -> bytes:
        events.append(url)
        if "page_standings=2" in url:
            return page(2, 51, 77)
        if "standings/" in url:
            return page(1, 1, 50, more=True)
        return b"{}"

    def clock() -> str:
        events.append("clock")
        return "2026-10-21T21:00:00Z"

    monkeypatch.setattr(fpl_capture, "fetch", fetch)
    monkeypatch.setattr(fpl_capture, "_utc_now", clock)
    monkeypatch.setattr(fpl_capture, "live_history_endpoints", lambda *_a, **_k: {})
    monkeypatch.setattr(fpl_capture, "summarise", lambda *_a, **_k: None)
    snapshots = tmp_path / "snapshots"
    written = fpl_capture.capture(snapshots, league_ids=[LEAGUE])
    assert written is not None
    assert events[-1] == "clock"
    assert any("page_standings=2" in event for event in events[:-1])
    snapshot = read_snapshot(snapshots, written.snapshot_id)
    assert snapshot.payloads[SECOND] == page(2, 51, 77)

    registry_path = tmp_path / "registry.json"
    monkeypatch.setattr(seed_entry_registry, "SNAPSHOT_ROOT", snapshots)
    monkeypatch.setattr(seed_entry_registry, "REGISTRY_PATH", registry_path)
    monkeypatch.setattr(
        "sys.argv", ["seed", "--league", str(LEAGUE), "--snapshot-id", written.snapshot_id]
    )
    assert seed_entry_registry.main() == 0
    registry = EntryRegistry.load(registry_path)
    assert len(registry.entries) == 77
    assert registry.in_league(snapshot.payloads, LEAGUE).ids() == registry.ids()
