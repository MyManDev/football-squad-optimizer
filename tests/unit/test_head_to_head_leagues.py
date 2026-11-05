"""A listed head-to-head league is refused with its reason, and a classic league reads as before.

The capture reads classic standings only. These tests run the real ``fetch`` against a fake
``_read`` on synthetic answers, so an HTTP 404 reaches the refusal the way FPL's would. The
head-to-head answers carry only the ``league`` declaration the classic page reader already
requires; no other field is read from them, so none is invented here.

The answers encode two FPL behaviours that no capture in this repository records: HTTP 404
from the classic endpoint for a head-to-head id, and an anonymous read of the head-to-head
endpoint that declares ``league.id``. The refusal test below pins exactly that pair, so a
recorded real answer pair can be checked against it; the 401 and 403 cases pin what happens
if FPL refuses the anonymous read instead.

The last two tests count a whole capture's requests. The listed leagues' first pages are read
before the registered members' documents, so a refused league costs no member request, and a
classic league's snapshot is the same bytes whichever order its documents were read in.
"""

import json
import urllib.error
from collections.abc import Sequence
from pathlib import Path

import pytest

from squadopt.application.entries import ENTRY_REGISTRY_CONTRACT_VERSION
from squadopt.data.errors import DataSourceError
from squadopt.data.snapshots import read_snapshot, write_snapshot
from squadopt.data.sources.fpl_live import FPL_LIVE_SOURCE, league_standings_payload
from squadopt.platform import fpl_capture

CLASSIC = 77
HEAD_TO_HEAD = 4242
BASE = fpl_capture.BASE_URL

#: The league the site serves today, and five registered members of it.
LEAGUE = 352490
MEMBERS = (1001, 1002, 1003, 1004, 1005)

#: A capture open for gameweek 2, so every member's gameweek 1 picks are read.
OPEN_FOR_SECOND_WEEK = json.dumps(
    {
        "events": [
            {"id": 1, "deadline_time": "2026-08-21T17:30:00Z", "finished": True},
            {"id": 2, "deadline_time": "2026-08-28T17:30:00Z", "finished": False},
        ]
    }
).encode()
CAPTURED_AT = "2026-08-25T09:00:00Z"


def classic_url(league_id: int) -> str:
    return f"{BASE}/leagues-classic/{league_id}/standings/"


def head_to_head_url(league_id: int) -> str:
    return f"{BASE}/leagues-h2h/{league_id}/standings/"


def classic_page(league_id: int = CLASSIC, members: Sequence[int] = (1001,)) -> bytes:
    return json.dumps(
        {
            "league": {"id": league_id, "name": "Synthetic Classic"},
            "last_updated_data": "2026-10-21T20:00:00Z",
            "standings": {
                "page": 1,
                "has_next": False,
                "results": [
                    {
                        "entry": entry,
                        "entry_name": f"Team {rank}",
                        "player_name": f"Manager {rank}",
                        "rank": rank,
                        "rank_sort": rank,
                        "last_rank": rank,
                    }
                    for rank, entry in enumerate(members, start=1)
                ],
            },
        }
    ).encode()


def declaration(league_id: int = HEAD_TO_HEAD) -> bytes:
    return json.dumps({"league": {"id": league_id}}).encode()


Answer = bytes | int


def serve(monkeypatch: pytest.MonkeyPatch, answers: dict[str, Answer | list[Answer]]) -> list[str]:
    """Answer each URL with its bytes or HTTP status; anything unnamed is an empty object.

    A list answers one entry per request, in order, and keeps answering with its last entry.
    """

    calls: list[str] = []

    def read(url: str) -> bytes:
        calls.append(url)
        given = answers.get(url, b"{}")
        if isinstance(given, list):
            answer = given.pop(0) if len(given) > 1 else given[0]
        else:
            answer = given
        if isinstance(answer, int):
            raise urllib.error.HTTPError(url, answer, "Refused", {}, None)  # type: ignore[arg-type]
        return answer

    monkeypatch.setattr(fpl_capture, "_read", read)
    return calls


def record_waits(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """Run the real ``fetch`` and its retries, recording each pause instead of taking it."""

    slept: list[float] = []
    real_fetch = fpl_capture.fetch

    def fetch(url: str) -> bytes:
        return real_fetch(url, sleeper=slept.append)

    monkeypatch.setattr(fpl_capture, "fetch", fetch)
    return slept


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
    assert reason.endswith(
        f"Remove league {HEAD_TO_HEAD} from the league list or the --league options this run names."
    )
    assert "config/leagues.json" not in reason
    assert calls == [classic_url(HEAD_TO_HEAD), head_to_head_url(HEAD_TO_HEAD)]


@pytest.mark.parametrize(
    "answer",
    [
        404,
        401,
        403,
        declaration(league_id=99),
        json.dumps({"league": {"id": str(HEAD_TO_HEAD)}}).encode(),
        json.dumps({"league": None}).encode(),
        json.dumps([{"league": {"id": HEAD_TO_HEAD}}]).encode(),
        b"<html>blocked</html>",
    ],
    ids=[
        "no-league",
        "anonymous-401",
        "anonymous-403",
        "another-league",
        "id-as-text",
        "no-declaration",
        "array",
        "html",
    ],
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
    assert reason.endswith(
        f"check league {HEAD_TO_HEAD} in the league list or the --league options this run names."
    )
    assert calls == [classic_url(HEAD_TO_HEAD), head_to_head_url(HEAD_TO_HEAD)]


@pytest.mark.parametrize("later", [429, 503])
def test_a_head_to_head_question_that_says_later_is_retried_like_any_other_read(
    monkeypatch: pytest.MonkeyPatch, later: int
) -> None:
    calls = serve(
        monkeypatch,
        {
            classic_url(HEAD_TO_HEAD): 404,
            head_to_head_url(HEAD_TO_HEAD): [later, declaration()],
        },
    )
    slept = record_waits(monkeypatch)
    with pytest.raises(fpl_capture.HeadToHeadLeagueError):
        fpl_capture.classic_standings(HEAD_TO_HEAD, classic_url(HEAD_TO_HEAD))
    assert calls == [classic_url(HEAD_TO_HEAD)] + [head_to_head_url(HEAD_TO_HEAD)] * 2
    assert slept == [fpl_capture.RETRY_INITIAL_SECONDS]


def test_a_head_to_head_question_refused_after_every_retry_gives_the_general_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = serve(
        monkeypatch, {classic_url(HEAD_TO_HEAD): 404, head_to_head_url(HEAD_TO_HEAD): 503}
    )
    slept = record_waits(monkeypatch)
    with pytest.raises(DataSourceError) as refused:
        fpl_capture.classic_standings(HEAD_TO_HEAD, classic_url(HEAD_TO_HEAD))
    assert not isinstance(refused.value, fpl_capture.HeadToHeadLeagueError)
    attempts = fpl_capture.RETRY_ATTEMPTS
    assert f"HTTP 503 Refused on all {attempts} attempts." in str(refused.value)
    assert calls == [classic_url(HEAD_TO_HEAD)] + [head_to_head_url(HEAD_TO_HEAD)] * attempts
    assert len(slept) == attempts - 1


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


def registry(path: Path, members: Sequence[int] = MEMBERS) -> Path:
    document = {
        "contract_version": ENTRY_REGISTRY_CONTRACT_VERSION,
        "entries": [
            {"entry_id": entry, "label": f"Team {entry}", "registered_at_utc": CAPTURED_AT}
            for entry in members
        ],
    }
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def member_documents(members: Sequence[int] = MEMBERS) -> dict[str, bytes]:
    """Every document a gameweek 2 capture reads for each member, each with its own bytes.

    No history here is one the purchase-price rebuild can read, so it adds only the transfers
    lists; the gameweek 1 picks are the captured picks of a gameweek 2 capture anyway.
    """

    urls = [
        f"{BASE}/entry/{entry}/{path}"
        for entry in members
        for path in ("", "history/", "event/1/picks/", "transfers/")
    ]
    return {url: json.dumps({"served": url}).encode() for url in urls}


def stored_files(directory: Path) -> dict[str, bytes]:
    return {
        path.relative_to(directory).as_posix(): path.read_bytes()
        for path in sorted(directory.rglob("*"))
        if path.is_file()
    }


def test_a_listed_head_to_head_league_is_refused_before_any_member_is_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ibo's review of #1220: by name, every member's documents sort before the leagues."""

    members = registry(tmp_path / "registry.json")
    named = fpl_capture.registered_endpoints(
        OPEN_FOR_SECOND_WEEK,
        as_of_utc=CAPTURED_AT,
        entry_registry=members,
        league_ids=[HEAD_TO_HEAD, LEAGUE],
    )
    # In name order the fifteen member documents come first, and this capture reads them all.
    assert [name.split("-")[0] for name in named] == ["entry"] * 15 + ["league"] * 2
    calls = serve(
        monkeypatch,
        {
            f"{BASE}/bootstrap-static/": OPEN_FOR_SECOND_WEEK,
            f"{BASE}/fixtures/": b"[]",
            classic_url(LEAGUE): classic_page(LEAGUE, MEMBERS),
            classic_url(HEAD_TO_HEAD): 404,
            head_to_head_url(HEAD_TO_HEAD): declaration(),
        },
    )
    monkeypatch.setattr(fpl_capture, "_utc_now", lambda: CAPTURED_AT)
    snapshots = tmp_path / "snapshots"
    with pytest.raises(fpl_capture.HeadToHeadLeagueError, match="head-to-head league"):
        fpl_capture.capture(snapshots, entry_registry=members, league_ids=[HEAD_TO_HEAD, LEAGUE])
    assert not snapshots.exists()
    assert sum("/entry/" in url for url in calls) == 0
    # The leagues keep name order among themselves, not the order they were listed in.
    assert calls == [
        f"{BASE}/bootstrap-static/",
        f"{BASE}/fixtures/",
        f"{BASE}/event/1/live/",
        classic_url(LEAGUE),
        classic_url(HEAD_TO_HEAD),
        head_to_head_url(HEAD_TO_HEAD),
    ]


def test_a_classic_capture_is_the_same_bytes_whichever_order_it_was_read_in(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reading the leagues first changes the order of the requests and nothing stored.

    The snapshot keeps exactly the bytes served, and writing those payloads again in name
    order and in reverse name order gives the same snapshot id, fingerprint and checksums,
    and the same metadata file and payload files byte for byte: the store serialises the
    checksums and the fingerprint in sorted order, so no read order reaches the disk.
    """

    answers = {
        f"{BASE}/bootstrap-static/": OPEN_FOR_SECOND_WEEK,
        f"{BASE}/fixtures/": b"[]",
        f"{BASE}/event/1/live/": b'{"elements": []}',
        classic_url(LEAGUE): classic_page(LEAGUE, MEMBERS),
        **member_documents(),
    }
    calls = serve(monkeypatch, answers)
    monkeypatch.setattr(fpl_capture, "_utc_now", lambda: CAPTURED_AT)
    monkeypatch.setattr(fpl_capture, "summarise", lambda *_a, **_k: None)
    written = fpl_capture.capture(
        tmp_path / "captured",
        entry_registry=registry(tmp_path / "registry.json"),
        league_ids=[LEAGUE],
    )
    assert written is not None
    assert not any("leagues-h2h" in url for url in calls)
    assert sorted(calls) == sorted(answers)
    first_member = min(index for index, url in enumerate(calls) if "/entry/" in url)
    assert calls.index(classic_url(LEAGUE)) < first_member

    captured = read_snapshot(tmp_path / "captured", written.snapshot_id)
    assert sorted(captured.payloads.values()) == sorted(answers.values())
    files = stored_files(tmp_path / "captured" / written.snapshot_id)
    for label, reverse in (("name-order", False), ("reverse-name-order", True)):
        names = sorted(captured.payloads, reverse=reverse)
        again = write_snapshot(
            tmp_path / label,
            source=FPL_LIVE_SOURCE,
            captured_at_utc=CAPTURED_AT,
            payloads={name: captured.payloads[name] for name in names},
        )
        assert (again.snapshot_id, again.fingerprint) == (written.snapshot_id, written.fingerprint)
        assert dict(again.checksums) == dict(written.checksums)
        assert stored_files(tmp_path / label / again.snapshot_id) == files
