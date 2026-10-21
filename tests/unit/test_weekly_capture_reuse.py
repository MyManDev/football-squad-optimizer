"""Publication reads shared immutable inputs once without changing output bytes."""

from collections import Counter
from dataclasses import replace
from pathlib import Path

import pytest
from tests.unit.test_build_scoreboard import _settlement_world
from tests.unit.test_weekly_operations import TWO, world
from tests.unit.test_weekly_suggestion_eval import SEASON, recorded, snapshot

from squadopt.application.advice_record import record_member_advice
from squadopt.application.scoreboard import publish_scoreboard
from squadopt.application.weekly_suggestion_eval import publish_suggestion_histories
from squadopt.data.snapshots import CapturedSnapshot, read_snapshot
from squadopt.platform import weekly_operations as weekly


def test_leagues_histories_and_scoreboards_share_one_capture_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    operation = world(
        tmp_path,
        league_ids=TWO,
        pages={352490: (101,), 7: (101,)},
        seeded_from=TWO,
        record_advice=True,
    )
    operation.values["capture"] = {"snapshot_id": operation.request.snapshot_id}
    operation.values["handoff"] = {"path": str(operation.supplied_handoff)}
    reads: Counter[tuple[Path, str]] = Counter()

    def counting(root: Path, identifier: str) -> CapturedSnapshot:
        reads[(root.resolve(), identifier)] += 1
        return read_snapshot(root, identifier)

    monkeypatch.setattr(weekly, "read_snapshot", counting)
    operation._league()
    operation._scoreboard()
    assert reads == {(operation.paths.snapshots.resolve(), operation.request.snapshot_id): 1}
    data = operation.paths.out / "data/leagues"
    assert (data / "352490/history/101.json").is_file()
    assert all((data / str(league) / "scoreboard.json").is_file() for league in TWO)


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
