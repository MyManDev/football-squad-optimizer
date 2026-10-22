"""Publication reads shared immutable inputs once without changing output bytes."""

import json
import shutil
from collections import Counter
from collections.abc import Mapping
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
import tests.unit.test_backend_runtime as handoff_fixture
from tests.unit.test_build_scoreboard import _settlement_world
from tests.unit.test_weekly_operations import TWO, world
from tests.unit.test_weekly_suggestion_eval import SEASON, recorded, snapshot

from squadopt.application.advice_record import record_member_advice
from squadopt.application.league_publication import (
    LeaguePublicationRequest,
    LeaguePublicationResult,
    publish_league,
)
from squadopt.application.scoreboard import publish_scoreboard
from squadopt.application.weekly_suggestion_eval import publish_suggestion_histories
from squadopt.data import snapshots as snapshot_store
from squadopt.data.snapshots import CapturedSnapshot, read_snapshot, write_snapshot
from squadopt.data.sources.club_news import ClaimResponse, RawDocument
from squadopt.data.sources.club_news_capture import CodedClub, write_club_news_capture
from squadopt.data.sources.club_news_coding import (
    ROTATION_CLAIM_CODING_CONTRACT_VERSION,
    coding_prompt_sha256,
)
from squadopt.data.sources.fpl_live import BOOTSTRAP_PAYLOAD, FIXTURES_PAYLOAD
from squadopt.platform import weekly_operations as weekly

NEWS_URL = "https://club.example/club-1/news"
QUOTE = "P1001 will miss the next Premier League match."
PUBLISHED_AT = "2026-08-27T07:00:00Z"
#: The members' pages carry their build time; both arms of a byte comparison share one.
BUILT_AT = datetime(2026, 8, 27, 12, 0, tzinfo=UTC)


def _club_news_run(tmp_path: Path) -> weekly.WeeklyOperations:
    """Two listed leagues with club news on, as the owner runs every week.

    The synthetic decision capture is captured again with what the rotation export reads
    (each player's short name and scout fields) and with its fixtures dated, so the one
    coded claim binds to Club 1's next match. The club-news capture sits under the same
    snapshot root, and the real rotation stage exports the evidence table both leagues read.
    """

    base = world(
        tmp_path,
        league_ids=TWO,
        pages={352490: (101,), 7: (101,)},
        seeded_from=TWO,
        record_advice=True,
    )
    snapshots = base.paths.snapshots
    assert base.request.snapshot_id is not None
    decision = read_snapshot(snapshots, base.request.snapshot_id)
    bootstrap = json.loads(decision.payloads[BOOTSTRAP_PAYLOAD])
    for element in bootstrap["elements"]:
        element.update(web_name=f"P{element['code']}", scout_risks=[], scout_news_link=None)
    kickoffs = {1: "2026-08-22T14:00:00Z", 2: "2026-08-29T14:00:00Z", 3: "2026-09-13T14:00:00Z"}
    fixtures = json.loads(decision.payloads[FIXTURES_PAYLOAD])
    for fixture in fixtures:
        fixture["kickoff_time"] = kickoffs[fixture["event"]]
    named = write_snapshot(
        snapshots,
        source="fpl-live",
        captured_at_utc=decision.metadata.captured_at_utc,
        payloads={
            **decision.payloads,
            BOOTSTRAP_PAYLOAD: json.dumps(bootstrap).encode("utf-8"),
            FIXTURES_PAYLOAD: json.dumps(fixtures).encode("utf-8"),
        },
    ).snapshot_id
    shutil.rmtree(snapshots / base.request.snapshot_id)
    content = f"Published: {PUBLISHED_AT}\n{QUOTE}".encode()
    document = RawDocument(
        club="Club 1",
        requested_url=NEWS_URL,
        final_url=NEWS_URL,
        http_status=200,
        content_type="text/plain",
        byte_length=len(content),
        fetched_at_utc="2026-08-27T08:00:00Z",
        content=content,
        readable=content,
    )
    claim = {
        "player_name": "P1001",
        "team_name": "Club 1",
        "disposition": "stated_expected_absent",
        "speaker": "manager",
        "source_url": NEWS_URL,
        "quote": QUOTE,
        "paraphrase": "The source reports an absence for this league match.",
        "fixture_scope": "upcoming_premier_league",
    }
    response = ClaimResponse(
        text=json.dumps(
            {
                "contract_version": ROTATION_CLAIM_CODING_CONTRACT_VERSION,
                "documents": [
                    {
                        "url": NEWS_URL,
                        "published_at_utc": PUBLISHED_AT,
                        "published_precision": "instant",
                    }
                ],
                "claims": [claim],
            }
        ),
        model_identifier="synthetic-stub",
        model_version="fixture-2",
    )
    news = write_club_news_capture(
        snapshots,
        documents=(document,),
        coded=(
            CodedClub(
                "Club 1",
                response,
                ROTATION_CLAIM_CODING_CONTRACT_VERSION,
                coding_prompt_sha256("synthetic-stub"),
            ),
        ),
        clubs_declared=("Club 1",),
        clubs_covered=("Club 1",),
        captured_at_utc="2026-08-27T08:30:00Z",
    ).snapshot_id
    operation = weekly.WeeklyOperations(
        replace(base.request, snapshot_id=named, rotation=True, rotation_capture=news),
        base.paths,
        run_id="synthetic",
        repository_commit="b" * 40,
        handoff=handoff_fixture._handoff(tmp_path / "named-handoffs", named),
        record_advice=True,
    )
    operation.run.directory.mkdir(parents=True, exist_ok=True)
    operation.values["capture"] = {"snapshot_id": named, "deadline_utc": "2026-08-28T17:30:00Z"}
    operation.values["handoff"] = {"path": str(operation.supplied_handoff)}
    operation.values["rotation"] = operation._rotation().value
    return operation


def _count_capture_reads(monkeypatch: pytest.MonkeyPatch) -> Counter[tuple[Path, str]]:
    """Count every capture read inside the snapshot store, whoever asked for it.

    Every module binds ``read_snapshot`` under its own name, so replacing one module's
    binding sees only that module's reads. ``read_snapshot`` checks a capture's recorded
    checksums once per read, so a counter there sees each read whichever module made it.
    """

    reads: Counter[tuple[Path, str]] = Counter()
    checked = snapshot_store._require_checksums

    def counting(document: Mapping[str, object], path: Path) -> dict[str, str]:
        reads[(path.parent.parent.resolve(), path.parent.name)] += 1
        return checked(document, path)

    monkeypatch.setattr(snapshot_store, "_require_checksums", counting)
    return reads


def _published(operation: weekly.WeeklyOperations) -> dict[str, bytes]:
    """Every file the league stage wrote, by its path under the site and record roots."""

    return {
        f"{name}/{path.relative_to(root).as_posix()}": path.read_bytes()
        for name, root in (("site", operation.paths.out), ("records", operation.paths.records))
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_leagues_histories_and_scoreboards_share_one_capture_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With club news on, each league reads the manager's word through the run's cache.

    Without the run's reader, each league's manager's word reads the club-news capture
    twice (its documents, then its coding) and the roster capture its evidence names once,
    which is this run's decision capture. Through it, both leagues and both scoreboards
    together read each of the two captures once.
    """

    operation = _club_news_run(tmp_path)
    reads = _count_capture_reads(monkeypatch)
    operation._league()
    operation._scoreboard()
    snapshots = operation.paths.snapshots.resolve()
    assert reads == {
        (snapshots, operation._capture_id()): 1,
        (snapshots, str(operation.request.rotation_capture)): 1,
    }
    data = operation.paths.out / "data/leagues"
    for league in TWO:
        words = json.loads((data / f"{league}/advice/101/saf-puan/1/hoca-sozu.json").read_bytes())
        assert [word["words"] for word in words["payload"]["evidence"]["applied"]] == [QUOTE]
        assert (data / str(league) / "scoreboard.json").is_file()
    assert (data / "352490/history/101.json").is_file()


def test_reused_club_news_capture_preserves_league_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Both leagues publish the same bytes whether each read goes to disk or to the cache.

    The disk arm publishes each league without a reader, as ``build_league_site`` does, so
    the manager's word takes its default reads. Handing that arm ``read_snapshot`` as the
    reader would run the same reader path as the cached arm, and a break in that path
    alone would leave both arms equal. The disk arm must also show the quote, or two
    equally broken arms would still compare equal.
    """

    def without_reader(
        request: LeaguePublicationRequest, **options: Any
    ) -> LeaguePublicationResult:
        options.pop("read_capture", None)
        return publish_league(request, **options)

    published = []
    for name in ("disk", "cached"):
        operation = _club_news_run(tmp_path / name)
        request = operation._league_request
        monkeypatch.setattr(
            operation,
            "_league_request",
            lambda league, record, request=request: replace(request(league, record), now=BUILT_AT),
        )
        with monkeypatch.context() as patch:
            if name == "disk":
                patch.setattr(weekly, "publish_league", without_reader)
            operation._league()
        # Only the cached arm reads through the run's reader.
        assert bool(operation._publication_captures) is (name == "cached")
        published.append(_published(operation))
    disk, cached = published
    for league in TWO:
        page = f"site/data/leagues/{league}/advice/101/saf-puan/1/hoca-sozu.json"
        words = json.loads(disk[page])
        assert [word["words"] for word in words["payload"]["evidence"]["applied"]] == [QUOTE]
    assert cached == disk
    assert sum(path.endswith("/hoca-sozu.json") for path in cached) == len(TWO)


def test_reused_capture_preserves_scoreboard_and_history_bytes(tmp_path: Path) -> None:
    operation = world(tmp_path / "run")
    score_request, _ = _settlement_world(tmp_path / "score")
    score_request = replace(score_request, now_utc="2026-09-20T10:00:00Z")
    plain_score = publish_scoreboard(score_request).target.read_bytes()
    cached_score = publish_scoreboard(
        replace(score_request, out_dir=tmp_path / "cached-score"),
        read_capture=operation._capture_for_publication,
    ).target.read_bytes()
    assert cached_score == plain_score

    records, snapshots = tmp_path / "records", tmp_path / "snapshots"
    record_member_advice(records, recorded())
    snapshot(snapshots, captured="2026-09-13T09:00:00Z", finished=False, checked=False)
    anchor = snapshot(snapshots)
    outputs = []
    for name, reader in (("plain", None), ("cached", operation._capture_for_publication)):
        target = tmp_path / name
        written = publish_suggestion_histories(
            record_root=records,
            snapshot_root=snapshots,
            as_of_snapshot=anchor,
            season=SEASON,
            league_id=352490,
            entry_ids=[101, 202],
            out_dir=target,
            published={(101, 4): "capture-a"},
            read_capture=reader,
        )
        outputs.append({p.relative_to(target): p.read_bytes() for p in written})
    assert outputs[0] == outputs[1]


def test_cache_is_scoped_to_operation_and_resolved_archive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first, second = world(tmp_path / "first"), world(tmp_path / "second")
    calls = []

    def counting(root: Path, identifier: str) -> CapturedSnapshot:
        calls.append((root.resolve(), identifier))
        return read_snapshot(root, identifier)

    monkeypatch.setattr(weekly, "read_snapshot", counting)
    identifier = first.request.snapshot_id
    assert identifier is not None and identifier == second.request.snapshot_id
    one = first._capture_for_publication(first.paths.snapshots, identifier)
    assert first._capture_for_publication(first.paths.snapshots / ".", identifier) is one
    assert first._capture_for_publication(second.paths.snapshots, identifier) is not one
    assert second._capture_for_publication(first.paths.snapshots, identifier) is not one
    assert len(calls) == 3
