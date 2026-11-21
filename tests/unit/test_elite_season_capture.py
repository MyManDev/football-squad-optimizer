"""The season archive adds what the store lacks and repeats nothing it already holds."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from tests.unit.test_benchmark_v2_measurement import _top100_page

from squadopt.data.errors import DataSourceError
from squadopt.data.snapshots import list_snapshot_ids, read_snapshot, write_snapshot
from squadopt.data.sources.fpl_live import (
    entry_history_payload,
    entry_picks_payload,
    entry_transfers_payload,
    league_standings_page_payload,
)
from squadopt.platform import elite_season_capture as capture

FIRST_ENTRY = 1001
LAST_ENTRY = 1100
_PICKS_URL = re.compile(r"/entry/(\d+)/event/(\d+)/picks/$")
_HISTORY_URL = re.compile(r"/entry/(\d+)/history/$")
_TRANSFERS_URL = re.compile(r"/entry/(\d+)/transfers/$")


def _cohort(root: Path, stamp: str = "2026-09-12T08:00:00Z", pages: dict[int, bytes] | None = None):
    documents = {1: _top100_page(1, 1), 2: _top100_page(2, 51)} if pages is None else pages
    return write_snapshot(
        root,
        source="fpl-top100",
        captured_at_utc=stamp,
        payloads={league_standings_page_payload(314, page): raw for page, raw in documents.items()},
    )


class World:
    """A stand-in for the game's API that records every address it is asked for."""

    def __init__(self, scored: tuple[int, ...] = (1, 2), unfinished: tuple[int, ...] = (3,)):
        self.scored = scored
        self.unfinished = unfinished
        self.played: dict[int, tuple[int, ...]] = {}
        self.refused: set[str] = set()
        self.asked: list[str] = []

    def __call__(self, url: str) -> bytes:
        self.asked.append(url)
        if any(url.endswith(suffix) for suffix in self.refused):
            raise DataSourceError(f"{url} returned HTTP 503.")
        if url.endswith("/bootstrap-static/"):
            events = [{"id": week, "finished": True, "data_checked": True} for week in self.scored]
            events += [
                {"id": week, "finished": True, "data_checked": False} for week in self.unfinished
            ]
            return json.dumps({"events": events}).encode()
        if (match := _HISTORY_URL.search(url)) is not None:
            weeks = self.played.get(int(match.group(1)), self.scored + self.unfinished)
            return json.dumps(
                {"current": [{"event": week} for week in weeks], "chips": []}
            ).encode()
        if _TRANSFERS_URL.search(url) is not None:
            return b"[]"
        if (match := _PICKS_URL.search(url)) is not None:
            return json.dumps({"entry": int(match.group(1)), "event": int(match.group(2))}).encode()
        raise AssertionError(f"unexpected request: {url}")

    def picks_asked(self) -> set[tuple[int, int]]:
        found = (_PICKS_URL.search(url) for url in self.asked)
        return {(int(match.group(1)), int(match.group(2))) for match in found if match}

    def histories_asked(self) -> set[int]:
        found = (_HISTORY_URL.search(url) for url in self.asked)
        return {int(match.group(1)) for match in found if match}


def _run(root: Path, world: World, *extra: str, stamp: str = "2026-09-20T10:00:00Z") -> int:
    world.asked.clear()
    return capture.main(
        ["--snapshot-root", str(root), *extra],
        fetcher=world,
        sleeper=lambda _seconds: None,
        now=lambda: stamp,
    )


def _archives(root: Path) -> tuple[str, ...]:
    return list_snapshot_ids(root, source=capture.SNAPSHOT_SOURCE)


def test_the_first_run_keeps_history_transfers_and_every_scored_week(tmp_path: Path) -> None:
    _cohort(tmp_path)
    world = World()

    assert _run(tmp_path, world) == 0

    (archive,) = _archives(tmp_path)
    payloads = read_snapshot(tmp_path, archive).payloads
    for entry in (FIRST_ENTRY, LAST_ENTRY):
        assert entry_history_payload(entry) in payloads
        assert entry_transfers_payload(entry) in payloads
        assert entry_picks_payload(entry, 1) in payloads
        assert entry_picks_payload(entry, 2) in payloads
        assert entry_picks_payload(entry, 3) not in payloads
    manifest = json.loads(payloads[capture.MANIFEST_PAYLOAD])
    assert manifest["contract"] == capture.CONTRACT
    assert manifest["managers_known"] == manifest["managers_read"] == 100
    assert manifest["picks_added"] == 200
    assert manifest["scored_gameweeks"] == [1, 2]
    assert manifest["requests"] == 400
    assert len(world.asked) == 401


def test_a_second_run_with_no_new_week_requests_no_manager_and_writes_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _cohort(tmp_path)
    world = World()
    assert _run(tmp_path, world) == 0

    assert _run(tmp_path, world, stamp="2026-09-21T10:00:00Z") == 0

    assert len(_archives(tmp_path)) == 1
    assert len(world.asked) == 1
    assert "Nothing to add" in capsys.readouterr().out


def test_a_newly_scored_week_is_the_only_week_requested(tmp_path: Path) -> None:
    _cohort(tmp_path)
    world = World()
    assert _run(tmp_path, world) == 0

    world.scored, world.unfinished = (1, 2, 3), ()
    assert _run(tmp_path, world, stamp="2026-09-27T10:00:00Z") == 0

    assert {week for _, week in world.picks_asked()} == {3}
    assert len(world.picks_asked()) == 100
    assert len(_archives(tmp_path)) == 2


def test_a_spent_budget_defers_managers_and_the_next_run_starts_with_them(tmp_path: Path) -> None:
    _cohort(tmp_path)
    world = World()

    assert _run(tmp_path, world, "--request-budget", "40") == 0
    first = world.histories_asked()
    assert len(first) == 10
    (archive,) = _archives(tmp_path)
    manifest = json.loads(read_snapshot(tmp_path, archive).payloads[capture.MANIFEST_PAYLOAD])
    assert manifest["managers_deferred"] == 90

    assert _run(tmp_path, world, "--request-budget", "40", stamp="2026-09-21T10:00:00Z") == 0
    second = world.histories_asked()
    assert len(second) == 10
    assert first.isdisjoint(second)


def test_a_week_the_manager_did_not_play_is_not_requested(tmp_path: Path) -> None:
    _cohort(tmp_path)
    world = World()
    world.played[FIRST_ENTRY] = (2,)

    assert _run(tmp_path, world) == 0

    assert (FIRST_ENTRY, 1) not in world.picks_asked()
    assert (FIRST_ENTRY, 2) in world.picks_asked()

    # The unplayed week stays missing for good; a later run reads that manager's history,
    # finds nothing new and stores nothing.
    assert _run(tmp_path, world, stamp="2026-09-21T10:00:00Z") == 0
    assert world.histories_asked() == {FIRST_ENTRY}
    assert world.picks_asked() == set()
    assert len(_archives(tmp_path)) == 1


def test_unreadable_picks_are_counted_and_asked_for_again(tmp_path: Path) -> None:
    _cohort(tmp_path)
    world = World()
    world.refused.add(f"/entry/{FIRST_ENTRY}/event/2/picks/")

    assert _run(tmp_path, world) == 0
    (archive,) = _archives(tmp_path)
    payloads = read_snapshot(tmp_path, archive).payloads
    assert entry_picks_payload(FIRST_ENTRY, 2) not in payloads
    assert json.loads(payloads[capture.MANIFEST_PAYLOAD])["picks_unreadable"] == 1

    world.refused.clear()
    assert _run(tmp_path, world, stamp="2026-09-21T10:00:00Z") == 0
    assert world.picks_asked() == {(FIRST_ENTRY, 2)}


def test_an_unreadable_history_leaves_the_manager_for_the_next_run(tmp_path: Path) -> None:
    _cohort(tmp_path)
    world = World()
    world.refused.add(f"/entry/{FIRST_ENTRY}/history/")

    assert _run(tmp_path, world) == 0

    (archive,) = _archives(tmp_path)
    payloads = read_snapshot(tmp_path, archive).payloads
    assert entry_history_payload(FIRST_ENTRY) not in payloads
    assert not any(pair[0] == FIRST_ENTRY for pair in world.picks_asked())
    assert json.loads(payloads[capture.MANIFEST_PAYLOAD])["managers_unreadable"] == 1


def test_plan_only_requests_the_calendar_alone_and_writes_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _cohort(tmp_path)
    world = World()

    assert _run(tmp_path, world, "--plan-only") == 0

    assert len(world.asked) == 1
    assert _archives(tmp_path) == ()
    output = capsys.readouterr().out
    assert "managers known    100" in output
    assert "requests at most  400" in output


def test_managers_of_every_cohort_capture_are_kept_and_a_damaged_one_is_skipped(
    tmp_path: Path,
) -> None:
    _cohort(tmp_path)
    later = json.loads(_top100_page(1, 1))
    later["standings"]["results"][0]["entry"] = 5000
    _cohort(
        tmp_path,
        stamp="2026-09-19T08:00:00Z",
        pages={1: json.dumps(later).encode(), 2: _top100_page(2, 51)},
    )
    _cohort(tmp_path, stamp="2026-09-26T08:00:00Z", pages={1: b"not a standings page"})

    cohorts = capture.stored_cohorts(tmp_path)

    assert len(cohorts.entry_ids) == 101
    assert 5000 in cohorts.entry_ids
    assert (cohorts.captures_read, cohorts.captures_unreadable) == (2, 1)


def test_a_store_without_a_cohort_capture_is_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _run(tmp_path, World()) == 1
    assert "refused" in capsys.readouterr().out
    assert _archives(tmp_path) == ()


def test_through_gameweek_caps_the_weeks_kept(tmp_path: Path) -> None:
    _cohort(tmp_path)
    world = World()

    assert _run(tmp_path, world, "--through-gameweek", "1") == 0

    assert {week for _, week in world.picks_asked()} == {1}
