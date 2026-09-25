"""Tests for the capture adapter's retry policy and its registered-entry endpoints.

Nothing here touches a network: `fetch` is exercised against a fake opener and `capture`
against a fake `fetch`. The sleeps are injected so the backoff is asserted rather than
waited out. The one test whose claim is about what http.client itself does with a body
cut off talks to a server on the loopback interface, in this process, instead.
"""

import http.client
import json
import re
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from tests.fixtures.loopback_http import DIRECT_OPENER, serving, status_head

from squadopt.application.entries import ENTRY_REGISTRY_CONTRACT_VERSION
from squadopt.data.errors import DataError, DataSourceError
from squadopt.data.snapshots import read_snapshot
from squadopt.data.sources.football_history import captured_history
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


#: What urllib raises raw once the request is sent: a read that times out, a host that
#: hangs up before answering, and a body shorter than its declared length.
TRANSPORT_FAILURES: dict[str, Callable[[], Exception]] = {
    "timeout": lambda: TimeoutError("timed out"),
    "hang-up": lambda: http.client.RemoteDisconnected(
        "Remote end closed connection without response"
    ),
    "short body": lambda: http.client.IncompleteRead(b"{", 900),
}


@pytest.mark.parametrize("failure", TRANSPORT_FAILURES.values(), ids=TRANSPORT_FAILURES.keys())
def test_a_dropped_response_is_retried_and_then_succeeds(
    failure: Callable[[], Exception], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The host was reached, so like a 503 this says "later" rather than ending the capture."""

    calls: list[int] = []

    def reader(url: str) -> bytes:
        calls.append(len(calls))
        if len(calls) < 3:
            raise failure()
        return b"ok"

    monkeypatch.setattr(fpl_capture, "_read", reader)
    slept: list[float] = []
    assert fpl_capture.fetch(URL, sleeper=slept.append) == b"ok"
    assert len(calls) == 3
    assert slept == [2.0, 4.0]


@pytest.mark.parametrize("failure", TRANSPORT_FAILURES.values(), ids=TRANSPORT_FAILURES.keys())
def test_a_response_that_keeps_failing_is_a_data_error_naming_the_url(
    failure: Callable[[], Exception], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The capture commands catch DataError only; a raw one used to end them in a traceback."""

    calls: list[int] = []

    def reader(url: str) -> bytes:
        calls.append(len(calls))
        raise failure()

    monkeypatch.setattr(fpl_capture, "_read", reader)
    slept: list[float] = []
    with pytest.raises(DataSourceError, match="on all 3 attempts") as raised:
        fpl_capture.fetch(URL, attempts=3, sleeper=slept.append)
    assert URL in str(raised.value)
    assert type(failure()).__name__ in str(raised.value)
    assert len(calls) == 3
    assert slept == [2.0, 4.0]


def test_a_body_cut_short_inside_the_real_reader_is_a_data_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Through `_read` itself, so the read after a successful open is covered, not a stub."""

    opened: list[str] = []

    class _CutShort:
        def __enter__(self) -> "_CutShort":
            return self

        def __exit__(self, *_: object) -> None:
            return None

        def read(self) -> bytes:
            raise http.client.IncompleteRead(b"{", 900)

    def urlopen(request: urllib.request.Request, timeout: float) -> _CutShort:
        opened.append(request.full_url)
        return _CutShort()

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    with pytest.raises(DataSourceError, match="IncompleteRead"):
        fpl_capture.fetch(URL, attempts=2, sleeper=lambda _: None)
    assert opened == [URL, URL]


#: The same two bytes of a payload, sent under each framing a body can have, and cut off.
CUT_OFF_ANSWERS: dict[str, bytes] = {
    "content-length": status_head(Content_Type="application/json", Content_Length="900") + b'{"',
    "chunked": status_head(Content_Type="application/json", Transfer_Encoding="chunked")
    + b'384\r\n{"',
}


@pytest.mark.parametrize("answer", CUT_OFF_ANSWERS.values(), ids=CUT_OFF_ANSWERS.keys())
def test_a_body_cut_off_under_http_client_is_a_data_error(
    answer: bytes, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Through http.client itself, on a loopback server.

    `_read` reads with no amount, so a body sent with a Content-Length and cut off raises
    `IncompleteRead` just as a chunked one does, and the capture needs no length check.
    """

    monkeypatch.setattr(urllib.request, "urlopen", DIRECT_OPENER.open)
    slept: list[float] = []

    with (
        serving(answer) as server,
        pytest.raises(DataSourceError, match="IncompleteRead") as raised,
    ):
        fpl_capture.fetch(f"{server.url}/api/bootstrap-static/", attempts=2, sleeper=slept.append)

    assert server.url in str(raised.value)
    assert len(server.answered) == 2
    assert slept == [2.0]


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


def _deadline(week: int) -> str:
    """A weekly calendar from the opening deadline, the shape of a real season."""

    opening = datetime(2026, 8, 21, 17, 30, tzinfo=UTC)
    return (opening + timedelta(weeks=week - 1)).isoformat().replace("+00:00", "Z")


def _season_events(open_week: int, *, weeks: int = 38) -> list[dict[str, Any]]:
    return [
        {"id": week, "deadline_time": _deadline(week), "finished": week < open_week}
        for week in range(1, weeks + 1)
    ]


def test_a_gw7_capture_reads_every_played_week_not_only_the_last_five() -> None:
    """The football history reads GW1 onward, so the GW7 capture must hold GW1 too."""

    bootstrap = json.dumps({"events": _season_events(7)}).encode("utf-8")

    endpoints = fpl_capture.live_history_endpoints(bootstrap, as_of_utc="2026-09-29T12:00:00Z")

    assert tuple(endpoints) == tuple(f"event-gw{week:02d}-live.json" for week in range(1, 7))
    assert endpoints["event-gw01-live.json"] == (
        "https://fantasy.premierleague.com/api/event/1/live/"
    )


def test_the_last_capture_of_a_season_reads_37_live_documents() -> None:
    """The cost the wider history adds is bounded: the GW38 capture is the largest."""

    bootstrap = json.dumps({"events": _season_events(38)}).encode("utf-8")

    endpoints = fpl_capture.live_history_endpoints(bootstrap, as_of_utc=_deadline(37))

    assert tuple(endpoints) == tuple(f"event-gw{week:02d}-live.json" for week in range(1, 38))


def test_live_history_reads_nothing_before_the_opening_deadline() -> None:
    assert fpl_capture.live_history_endpoints(_bootstrap(), as_of_utc="2026-08-20T09:00:00Z") == {}


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
        "event-gw01-live.json",
        "league-352490-standings.json",
        "entry-11.json",
        "entry-11-history.json",
        "entry-11-picks-gw01.json",
    }
    assert json.loads(snapshot.payloads["entry-11-picks-gw01.json"])["read"].endswith(
        "/entry/11/event/1/picks/"
    )


def test_a_capture_without_a_registry_adds_only_the_live_history(
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
    assert set(snapshot.payloads) == {
        BOOTSTRAP_PAYLOAD,
        FIXTURES_PAYLOAD,
        "event-gw01-live.json",
    }


def _gw7_world() -> dict[str, bytes]:
    """A season six weeks in: one settled fixture a week between two clubs.

    Each club fields one player, so every week yields two player-fixture rows. The
    documents carry the fields the football history reads and nothing it does not.
    """

    teams = [
        {"id": 1, "code": 3, "name": "Arsenal", "short_name": "ARS"},
        {"id": 2, "code": 7, "name": "Aston Villa", "short_name": "AVL"},
    ]
    elements = [
        {
            "id": identifier,
            "code": 100 + identifier,
            "first_name": "A",
            "second_name": f"Player {identifier}",
            "team": identifier,
            "element_type": element_type,
            "now_cost": 55,
            "status": "a",
            "chance_of_playing_next_round": 100,
            "news": "",
        }
        for identifier, element_type in ((1, 3), (2, 2))
    ]
    bootstrap = {"events": _season_events(7), "teams": teams, "elements": elements}
    fixtures = [
        {
            "id": week,
            "event": week,
            "team_h": 1,
            "team_a": 2,
            "kickoff_time": (
                datetime.fromisoformat(_deadline(week).replace("Z", "+00:00")) + timedelta(hours=2)
            )
            .isoformat()
            .replace("+00:00", "Z"),
            "team_h_score": 1,
            "team_a_score": 0,
            "finished": True,
        }
        for week in range(1, 7)
    ]
    stats = {
        1: {"minutes": 90, "goals_scored": 1, "assists": 0, "clean_sheets": 1, "total_points": 9},
        2: {"minutes": 90, "goals_scored": 0, "assists": 0, "clean_sheets": 0, "total_points": 1},
    }
    documents = {
        "bootstrap-static/": json.dumps(bootstrap).encode("utf-8"),
        "fixtures/": json.dumps(fixtures).encode("utf-8"),
    }
    for week in range(1, 7):
        live = {
            "elements": [
                {
                    "id": identifier,
                    "stats": {
                        **line,
                        "expected_goals": "0.40",
                        "expected_assists": "0.10",
                        "starts": 1,
                        "defensive_contribution": 11,
                    },
                    "explain": [{"fixture": week}],
                }
                for identifier, line in stats.items()
            ]
        }
        documents[f"event/{week}/live/"] = json.dumps(live).encode("utf-8")
    return documents


def test_a_gw7_capture_builds_the_football_history(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The reader walks GW1 to GW6 and refuses a gap, so the capture must hold all six.

    A capture that kept only the component model's five weeks (GW2 to GW6) held no GW1,
    and the football forecast could not be built from any capture after the GW6 deadline.
    """

    documents = _gw7_world()
    requested: list[str] = []

    def fake_fetch(url: str, **_: Any) -> bytes:
        requested.append(url)
        return documents[url.removeprefix(f"{fpl_capture.BASE_URL}/")]

    monkeypatch.setattr(fpl_capture, "_utc_now", lambda: "2026-09-29T12:00:00Z")
    monkeypatch.setattr(fpl_capture, "fetch", fake_fetch)
    written = fpl_capture.capture(tmp_path / "snapshots")
    assert written is not None

    live = [url for url in requested if url.endswith("/live/")]
    assert live == [f"{fpl_capture.BASE_URL}/event/{week}/live/" for week in range(1, 7)]
    snapshot = read_snapshot(tmp_path / "snapshots", written.snapshot_id)
    history = captured_history(snapshot, season="2026-27", gameweek=7)
    assert sorted(set(history["GW"])) == [1, 2, 3, 4, 5, 6]
    assert len(history) == 12

    without_gw01 = replace(
        snapshot,
        payloads={
            name: content
            for name, content in snapshot.payloads.items()
            if name != "event-gw01-live.json"
        },
    )
    with pytest.raises(ValueError, match="Missing captured football history GW1"):
        captured_history(without_gw01, season="2026-27", gameweek=7)


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
