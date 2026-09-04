"""Tests for the capture adapter's retry policy and its registered-entry endpoints.

Nothing here touches a network: `fetch` is exercised against a fake opener and `capture`
against a fake `fetch`. The sleeps are injected so the backoff is asserted rather than
waited out.
"""

import json
import re
import urllib.error
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from squadopt.application.entries import ENTRY_REGISTRY_CONTRACT_VERSION
from squadopt.data.errors import DataError, DataSourceError
from squadopt.data.snapshots import read_snapshot
from squadopt.data.sources.fpl_live import BOOTSTRAP_PAYLOAD, FIXTURES_PAYLOAD
from squadopt.platform import fpl_capture

URL = "https://fantasy.premierleague.com/api/entry/11/"

EVENTS: list[dict[str, Any]] = [
    {"id": 1, "deadline_time": "2026-08-21T17:30:00Z", "finished": True},
    {"id": 2, "deadline_time": "2026-08-28T17:30:00Z", "finished": False},
]


def _http_error(code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(URL, code, "Nope", {}, None)  # type: ignore[arg-type]


def _bootstrap() -> bytes:
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
    return json.dumps({"events": EVENTS, "teams": teams, "elements": elements}).encode("utf-8")


def _registry(path: Path, ids: list[int]) -> Path:
    document = {
        "contract_version": ENTRY_REGISTRY_CONTRACT_VERSION,
        "entries": [
            {"entry_id": i, "label": f"Team {i}", "registered_at_utc": "2026-08-25T09:00:00Z"}
            for i in ids
        ],
    }
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


# --- retry policy ---------------------------------------------------------------------


def test_a_rate_limit_is_waited_out_rather_than_failing_the_capture(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[int] = []

    def reader(url: str) -> bytes:
        calls.append(len(calls))
        if len(calls) < 3:
            raise _http_error(429)
        return b"ok"

    monkeypatch.setattr(fpl_capture, "_read", reader)
    slept: list[float] = []
    assert fpl_capture.fetch(URL, sleeper=slept.append) == b"ok"
    assert len(calls) == 3
    assert slept == [2.0, 4.0]


def test_the_backoff_grows_and_is_capped(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(fpl_capture, "_read", lambda url: (_ for _ in ()).throw(_http_error(503)))
    slept: list[float] = []
    with pytest.raises(DataSourceError, match="on all 6 attempts"):
        fpl_capture.fetch(URL, attempts=6, sleeper=slept.append)
    assert slept == [2.0, 4.0, 8.0, 16.0, 16.0]


@pytest.mark.parametrize("code", [400, 403, 404])
def test_a_refusal_is_not_retried(code: int, monkeypatch: pytest.MonkeyPatch) -> None:
    """429 and 5xx say "later"; every other 4xx says "never" and waiting is rude."""

    calls: list[int] = []

    def reader(url: str) -> bytes:
        calls.append(len(calls))
        raise _http_error(code)

    monkeypatch.setattr(fpl_capture, "_read", reader)
    slept: list[float] = []
    with pytest.raises(DataSourceError, match=f"HTTP {code}"):
        fpl_capture.fetch(URL, sleeper=slept.append)
    assert len(calls) == 1
    assert slept == []


def test_an_unreachable_host_is_not_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    def reader(url: str) -> bytes:
        raise urllib.error.URLError("no route")

    monkeypatch.setattr(fpl_capture, "_read", reader)
    with pytest.raises(DataSourceError, match="Could not reach"):
        fpl_capture.fetch(URL, sleeper=lambda _: None)


# --- registered endpoints -------------------------------------------------------------


def test_no_registry_and_no_league_reads_nothing_extra() -> None:
    assert (
        fpl_capture.registered_endpoints(
            _bootstrap(),
            as_of_utc="2026-08-25T09:00:00Z",
            entry_registry=None,
            league_id=None,
        )
        == {}
    )


def test_a_league_alone_records_only_its_standings_page() -> None:
    endpoints = fpl_capture.registered_endpoints(
        _bootstrap(), as_of_utc="2026-08-25T09:00:00Z", entry_registry=None, league_id=352490
    )
    assert endpoints == {
        "league-352490-standings.json": (
            "https://fantasy.premierleague.com/api/leagues-classic/352490/standings/"
        )
    }


def test_each_registered_entry_contributes_three_documents_for_the_played_gameweek(
    tmp_path: Path,
) -> None:
    endpoints = fpl_capture.registered_endpoints(
        _bootstrap(),
        as_of_utc="2026-08-25T09:00:00Z",
        entry_registry=_registry(tmp_path / "registry.json", [11]),
        league_id=None,
    )
    assert endpoints == {
        "entry-11.json": "https://fantasy.premierleague.com/api/entry/11/",
        "entry-11-history.json": "https://fantasy.premierleague.com/api/entry/11/history/",
        "entry-11-picks-gw01.json": (
            "https://fantasy.premierleague.com/api/entry/11/event/1/picks/"
        ),
    }


def test_before_the_opening_deadline_no_picks_exist_to_read(tmp_path: Path) -> None:
    """The capture is open for gameweek 1, so gameweek 0 picks would be a 404."""

    endpoints = fpl_capture.registered_endpoints(
        _bootstrap(),
        as_of_utc="2026-08-20T09:00:00Z",
        entry_registry=_registry(tmp_path / "registry.json", [11]),
        league_id=None,
    )
    assert endpoints == {}


def test_an_empty_registry_reads_nothing_extra(tmp_path: Path) -> None:
    endpoints = fpl_capture.registered_endpoints(
        _bootstrap(),
        as_of_utc="2026-08-25T09:00:00Z",
        entry_registry=_registry(tmp_path / "registry.json", []),
        league_id=None,
    )
    assert endpoints == {}


# --- capture end to end ---------------------------------------------------------------


def test_the_extra_payloads_land_in_the_snapshot_and_survive_the_checksum(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(fpl_capture, "_utc_now", lambda: "2026-08-25T09:00:00Z")

    def fake_fetch(url: str, **_: Any) -> bytes:
        if url.endswith("bootstrap-static/"):
            return _bootstrap()
        if url.endswith("fixtures/"):
            return json.dumps([{"event": 1, "kickoff_time": "2026-08-21T19:00:00Z"}]).encode()
        return json.dumps({"read": url}).encode("utf-8")

    monkeypatch.setattr(fpl_capture, "fetch", fake_fetch)
    written = fpl_capture.capture(
        tmp_path / "snapshots",
        entry_registry=_registry(tmp_path / "registry.json", [11]),
        league_id=352490,
    )
    assert written is not None

    snapshot = read_snapshot(tmp_path / "snapshots", written.snapshot_id)
    assert set(snapshot.payloads) == {
        BOOTSTRAP_PAYLOAD,
        FIXTURES_PAYLOAD,
        "league-352490-standings.json",
        "entry-11.json",
        "entry-11-history.json",
        "entry-11-picks-gw01.json",
    }
    assert json.loads(snapshot.payloads["entry-11-picks-gw01.json"])["read"].endswith(
        "/entry/11/event/1/picks/"
    )


def test_a_capture_without_a_registry_is_the_two_endpoints_it_always_was(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The injected capture operation calls this with one argument; it must not grow one."""

    monkeypatch.setattr(fpl_capture, "_utc_now", lambda: "2026-08-25T09:00:00Z")

    def fake_fetch(url: str, **_: Any) -> bytes:
        if url.endswith("bootstrap-static/"):
            return _bootstrap()
        return json.dumps([{"event": 1, "kickoff_time": "2026-08-21T19:00:00Z"}]).encode()

    monkeypatch.setattr(fpl_capture, "fetch", fake_fetch)
    written = fpl_capture.capture(tmp_path / "snapshots")
    assert written is not None
    snapshot = read_snapshot(tmp_path / "snapshots", written.snapshot_id)
    assert set(snapshot.payloads) == {BOOTSTRAP_PAYLOAD, FIXTURES_PAYLOAD}


def test_a_dry_run_with_entries_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(fpl_capture, "_utc_now", lambda: "2026-08-25T09:00:00Z")

    def fake_fetch(url: str, **_: Any) -> bytes:
        if url.endswith("bootstrap-static/"):
            return _bootstrap()
        if url.endswith("fixtures/"):
            return json.dumps([{"event": 1, "kickoff_time": "2026-08-21T19:00:00Z"}]).encode()
        return b"{}"

    monkeypatch.setattr(fpl_capture, "fetch", fake_fetch)
    root = tmp_path / "snapshots"
    assert (
        fpl_capture.capture(
            root,
            dry_run=True,
            entry_registry=_registry(tmp_path / "registry.json", [11]),
        )
        is None
    )
    assert not root.exists()


# --- the registry error contract ------------------------------------------------------
#
# `EntryRegistry.load` raises what its own layer raises. None of it is a `DataError`, and the
# manual capture shell only catches `DataError`, so every one of these reached the operator as
# a traceback in the middle of a capture before this was translated.


@pytest.mark.parametrize(
    ("case", "body"),
    [
        ("malformed json", "{not json"),
        ("wrong contract", json.dumps({"contract_version": "other", "entries": []})),
        ("a list instead of an object", "[]"),
        (
            "null entries",
            json.dumps({"contract_version": ENTRY_REGISTRY_CONTRACT_VERSION, "entries": None}),
        ),
        (
            "missing entry id",
            json.dumps({"contract_version": ENTRY_REGISTRY_CONTRACT_VERSION, "entries": [{}]}),
        ),
        (
            "invalid entry id",
            json.dumps(
                {
                    "contract_version": ENTRY_REGISTRY_CONTRACT_VERSION,
                    "entries": [{"entry_id": "not-an-integer"}],
                }
            ),
        ),
        (
            "repeated entry",
            json.dumps(
                {
                    "contract_version": ENTRY_REGISTRY_CONTRACT_VERSION,
                    "entries": [{"entry_id": 11}, {"entry_id": 11}],
                }
            ),
        ),
    ],
)
def test_an_unusable_registry_is_reported_in_the_data_error_contract(
    case: str, body: str, tmp_path: Path
) -> None:
    path = tmp_path / "registry.json"
    path.write_text(body, encoding="utf-8")
    with pytest.raises(DataSourceError, match=re.escape(str(path))):
        fpl_capture.registered_entry_ids(path)


def test_a_missing_registry_is_not_silently_treated_as_an_empty_one(tmp_path: Path) -> None:
    path = tmp_path / "missing.json"
    with pytest.raises(DataSourceError, match="not a readable file"):
        fpl_capture.registered_entry_ids(path)


def test_a_registry_that_is_not_utf8_is_reported_in_the_data_error_contract(
    tmp_path: Path,
) -> None:
    path = tmp_path / "registry.json"
    path.write_bytes(b"\xff\xfe")
    with pytest.raises(DataSourceError, match=re.escape(str(path))):
        fpl_capture.registered_entry_ids(path)


def test_an_unusable_registry_stops_the_capture_rather_than_tracebacking(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The failure has to arrive as a capture failure, not as a JSON parser's exception."""

    monkeypatch.setattr(fpl_capture, "fetch", lambda url, **_: _bootstrap())
    registry = tmp_path / "registry.json"
    registry.write_text("{not json", encoding="utf-8")
    with pytest.raises(DataError):
        fpl_capture.capture(tmp_path / "snapshots", entry_registry=registry)


# --- when the recorded instant is taken -----------------------------------------------


def test_the_clock_preserves_subsecond_precision(monkeypatch: pytest.MonkeyPatch) -> None:
    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz: object = None) -> datetime:
            assert tz is UTC
            return cls(2026, 8, 25, 0, 0, 11, 987654, tzinfo=UTC)

    monkeypatch.setattr(fpl_capture, "datetime", FixedDateTime)
    assert fpl_capture._utc_now() == "2026-08-25T00:00:11.987654Z"


def test_the_recorded_instant_is_taken_after_every_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No payload may have been fetched later than the instant the snapshot claims.

    An earlier stamp was the original design, justified as "under-claiming freshness". It is
    not safe: a document read after the stamp can contain events from after it, so the
    snapshot would assert knowledge at a time that knowledge did not exist.
    """

    events: list[str] = []
    ticks = iter(f"2026-08-25T00:00:{second:02d}Z" for second in range(10, 60))

    def fake_fetch(url: str, **_: Any) -> bytes:
        events.append("fetch")
        if url.endswith("bootstrap-static/"):
            return _bootstrap()
        if url.endswith("fixtures/"):
            return json.dumps([{"event": 1, "kickoff_time": "2026-08-21T19:00:00Z"}]).encode()
        return b"{}"

    def fake_now() -> str:
        events.append("clock")
        return next(ticks)

    monkeypatch.setattr(fpl_capture, "fetch", fake_fetch)
    monkeypatch.setattr(fpl_capture, "_utc_now", fake_now)

    written = fpl_capture.capture(
        tmp_path / "snapshots",
        entry_registry=_registry(tmp_path / "registry.json", [11, 22]),
        league_id=352490,
    )
    assert written is not None

    # The clock is read twice: once provisionally to choose which gameweek's picks to read,
    # and once to stamp the snapshot. Only the second is recorded, and it comes last.
    assert events.count("clock") == 2
    assert events[-1] == "clock", events
    assert events.index("fetch") < len(events) - 1

    last_read = max(index for index, event in enumerate(events) if event == "fetch")
    stamped = max(index for index, event in enumerate(events) if event == "clock")
    assert stamped > last_read

    # And the value written is the later tick, not the provisional one.
    assert written.captured_at_utc == "2026-08-25T00:00:11Z"
