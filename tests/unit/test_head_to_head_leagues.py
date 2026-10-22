"""A listed head-to-head league is refused with its reason, and a classic league reads as before.

The capture reads classic standings only. These tests run the real ``fetch`` against a fake
``_read`` on synthetic answers, so an HTTP 404 reaches the refusal the way FPL's would. The
head-to-head answers carry only the ``league`` declaration the classic page reader already
requires; no other field is read from them, so none is invented here.
"""

import json
import urllib.error
from pathlib import Path

import pytest

from squadopt.data.errors import DataSourceError
from squadopt.data.snapshots import read_snapshot
from squadopt.data.sources.fpl_live import league_standings_payload
from squadopt.platform import fpl_capture

CLASSIC = 77
HEAD_TO_HEAD = 4242
BASE = fpl_capture.BASE_URL


def classic_url(league_id: int) -> str:
    return f"{BASE}/leagues-classic/{league_id}/standings/"


def head_to_head_url(league_id: int) -> str:
    return f"{BASE}/leagues-h2h/{league_id}/standings/"


def classic_page(league_id: int = CLASSIC) -> bytes:
    return json.dumps(
        {
            "league": {"id": league_id, "name": "Synthetic Classic"},
            "last_updated_data": "2026-10-21T20:00:00Z",
            "standings": {
                "page": 1,
                "has_next": False,
                "results": [
                    {
                        "entry": 1001,
                        "entry_name": "Team 1",
                        "player_name": "Manager 1",
                        "rank": 1,
                        "rank_sort": 1,
                        "last_rank": 1,
                    }
                ],
            },
        }
    ).encode()


def declaration(league_id: int = HEAD_TO_HEAD) -> bytes:
    return json.dumps({"league": {"id": league_id}}).encode()


def serve(monkeypatch: pytest.MonkeyPatch, answers: dict[str, bytes | int]) -> list[str]:
    """Answer each URL with its bytes or HTTP status; anything unnamed is an empty object."""

    calls: list[str] = []

    def read(url: str) -> bytes:
        calls.append(url)
        answer = answers.get(url, b"{}")
        if isinstance(answer, int):
            raise urllib.error.HTTPError(url, answer, "Refused", {}, None)  # type: ignore[arg-type]
        return answer

    monkeypatch.setattr(fpl_capture, "_read", read)
    return calls


def test_a_head_to_head_league_is_refused_with_its_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = serve(
        monkeypatch,
        {classic_url(HEAD_TO_HEAD): 404, head_to_head_url(HEAD_TO_HEAD): declaration()},
    )
    with pytest.raises(fpl_capture.HeadToHeadLeagueError) as refused:
        fpl_capture.classic_standings(HEAD_TO_HEAD, classic_url(HEAD_TO_HEAD))
    reason = str(refused.value)
    assert f"League {HEAD_TO_HEAD} is a head-to-head league" in reason
    assert "publishes classic leagues only" in reason
    assert f"Remove league {HEAD_TO_HEAD} from the leagues this run names" in reason
    assert "config/leagues.json or --league" in reason
    assert calls == [classic_url(HEAD_TO_HEAD), head_to_head_url(HEAD_TO_HEAD)]


@pytest.mark.parametrize(
    "answer",
    [
        404,
        declaration(league_id=99),
        json.dumps({"league": {"id": str(HEAD_TO_HEAD)}}).encode(),
        json.dumps({"league": None}).encode(),
        json.dumps([{"league": {"id": HEAD_TO_HEAD}}]).encode(),
        b"<html>blocked</html>",
    ],
    ids=["no-league", "another-league", "id-as-text", "no-declaration", "array", "html"],
)
def test_an_id_fpl_does_not_confirm_as_head_to_head_is_refused_without_that_name(
    monkeypatch: pytest.MonkeyPatch, answer: bytes | int
) -> None:
    calls = serve(
        monkeypatch, {classic_url(HEAD_TO_HEAD): 404, head_to_head_url(HEAD_TO_HEAD): answer}
    )
    with pytest.raises(DataSourceError) as refused:
        fpl_capture.classic_standings(HEAD_TO_HEAD, classic_url(HEAD_TO_HEAD))
    assert not isinstance(refused.value, fpl_capture.HeadToHeadLeagueError)
    reason = str(refused.value)
    assert f"League {HEAD_TO_HEAD} has no classic standings" in reason
    assert "did not confirm it as a head-to-head league" in reason
    assert f"check league {HEAD_TO_HEAD} where this run names it" in reason
    assert calls == [classic_url(HEAD_TO_HEAD), head_to_head_url(HEAD_TO_HEAD)]


def test_the_head_to_head_question_is_asked_once_and_not_retried(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = serve(
        monkeypatch, {classic_url(HEAD_TO_HEAD): 404, head_to_head_url(HEAD_TO_HEAD): 503}
    )
    with pytest.raises(DataSourceError, match="HTTP 503"):
        fpl_capture.classic_standings(HEAD_TO_HEAD, classic_url(HEAD_TO_HEAD))
    assert calls == [classic_url(HEAD_TO_HEAD), head_to_head_url(HEAD_TO_HEAD)]


def test_a_classic_league_is_read_as_before_and_the_head_to_head_endpoint_is_not_asked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = serve(monkeypatch, {classic_url(CLASSIC): classic_page()})
    assert fpl_capture.classic_standings(CLASSIC, classic_url(CLASSIC)) == classic_page()
    assert calls == [classic_url(CLASSIC)]


@pytest.mark.parametrize("code", [400, 403])
def test_other_refusals_of_the_classic_endpoint_are_reported_as_before(
    monkeypatch: pytest.MonkeyPatch, code: int
) -> None:
    calls = serve(monkeypatch, {classic_url(CLASSIC): code})
    with pytest.raises(DataSourceError) as refused:
        fpl_capture.classic_standings(CLASSIC, classic_url(CLASSIC))
    assert str(refused.value) == f"{classic_url(CLASSIC)} returned HTTP {code} Refused."
    assert calls == [classic_url(CLASSIC)]


def test_a_listed_head_to_head_league_stops_the_capture_before_anything_is_written(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bootstrap = json.dumps(
        {"events": [{"id": 1, "deadline_time": "2026-08-21T17:30:00Z", "finished": False}]}
    ).encode()
    calls = serve(
        monkeypatch,
        {
            f"{BASE}/bootstrap-static/": bootstrap,
            f"{BASE}/fixtures/": b"[]",
            classic_url(CLASSIC): classic_page(),
            classic_url(HEAD_TO_HEAD): 404,
            head_to_head_url(HEAD_TO_HEAD): declaration(),
        },
    )
    monkeypatch.setattr(fpl_capture, "_utc_now", lambda: "2026-08-20T09:00:00Z")
    monkeypatch.setattr(fpl_capture, "live_history_endpoints", lambda *_a, **_k: {})
    snapshots = tmp_path / "snapshots"
    with pytest.raises(fpl_capture.HeadToHeadLeagueError, match="head-to-head league"):
        fpl_capture.capture(snapshots, league_ids=[CLASSIC, HEAD_TO_HEAD])
    assert not snapshots.exists()
    assert calls[-2:] == [classic_url(HEAD_TO_HEAD), head_to_head_url(HEAD_TO_HEAD)]


def test_a_capture_of_classic_leagues_asks_nothing_of_the_head_to_head_endpoint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bootstrap = json.dumps(
        {"events": [{"id": 1, "deadline_time": "2026-08-21T17:30:00Z", "finished": False}]}
    ).encode()
    calls = serve(
        monkeypatch,
        {
            f"{BASE}/bootstrap-static/": bootstrap,
            f"{BASE}/fixtures/": b"[]",
            classic_url(CLASSIC): classic_page(),
        },
    )
    monkeypatch.setattr(fpl_capture, "_utc_now", lambda: "2026-08-20T09:00:00Z")
    monkeypatch.setattr(fpl_capture, "live_history_endpoints", lambda *_a, **_k: {})
    monkeypatch.setattr(fpl_capture, "summarise", lambda *_a, **_k: None)
    written = fpl_capture.capture(tmp_path / "snapshots", league_ids=[CLASSIC])
    assert written is not None
    assert not any("leagues-h2h" in url for url in calls)
    snapshot = read_snapshot(tmp_path / "snapshots", written.snapshot_id)
    assert snapshot.payloads[league_standings_payload(CLASSIC)] == classic_page()
