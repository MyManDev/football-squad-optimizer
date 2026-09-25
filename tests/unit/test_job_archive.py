"""Finished jobs are archived after the retention window, and nothing that matters is lost.

Archived records are still found by their id and by their idempotency key, their ids are
never given out again, open work is never moved, and after a process's first scan the
queue reads only open records.
"""

import hashlib
import json
import logging
import os
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from tests.unit.test_api_advice_post import (
    ADVICE_URL,
    BODY,
    _valid_advice_document,
    _world,
)

from squadopt.platform import file_advice_queue
from squadopt.platform.advice_cache import FileAdviceCache
from squadopt.platform.advice_observability import AdviceLog
from squadopt.platform.advice_queue import AdviceQueueError, FileJobQueue
from squadopt.platform.advice_worker import run_advice_worker
from squadopt.platform.jobs_contract import AdviceJob, JobError
from squadopt.platform.queue_contracts import DEFAULT_ARCHIVE_AFTER_SECONDS

FINGERPRINT = "a" * 64
OLD = "2026-08-01T10:00:00Z"
RECENT = "2026-09-09T10:00:00Z"
NOW = "2026-09-10T10:00:00Z"  # OLD is 40 days back, RECENT one day back


def _key(number: int) -> str:
    return format(number, "064x")


def _finish(
    queue: FileJobQueue,
    cache: FileAdviceCache,
    job_id: str,
    key: str,
    *,
    at: str,
    status: str = "completed",
    idempotency_key: str | None = None,
) -> AdviceJob:
    """File, claim and finish one job; only one job is queued at a time, so it is the one."""

    queue.submit_unique(
        AdviceJob(job_id, "queued", FINGERPRINT, key, at, at, idempotency_key=idempotency_key)
    )
    running = queue.claim(at_utc=at)
    assert running is not None and running.job_id == job_id
    if status == "completed":
        return queue.complete(running, cache=cache, payload=b"answer", at_utc=at)
    failed = running.transition("failed", at_utc=at, error=JobError("ADVICE_FAILED", "fixture"))
    queue.store(failed)
    return failed


def test_the_retention_window_is_seven_days() -> None:
    assert DEFAULT_ARCHIVE_AFTER_SECONDS == 7 * 24 * 3600


def test_old_finished_jobs_move_to_the_archive_and_are_still_found(tmp_path: Path) -> None:
    root = tmp_path / "jobs"
    queue = FileJobQueue(root)
    cache = FileAdviceCache(tmp_path / "cache")
    done = _finish(queue, cache, "old-done", _key(1), at=OLD, idempotency_key="client:1")
    failed = _finish(queue, cache, "old-failed", _key(2), at=OLD, status="failed")
    recent = _finish(queue, cache, "recent-done", _key(3), at=RECENT)
    before = {name: (root / f"{name}.json").read_bytes() for name in ("old-done", "old-failed")}

    moved = queue.archive(now_utc=NOW)

    assert [job.job_id for job in moved] == ["old-done", "old-failed"]
    assert queue.jobs() == (recent,)  # the recent one stays among the records
    for name, raw in before.items():
        assert not (root / f"{name}.json").exists()
        assert (root / "archive" / f"{name}.json").read_bytes() == raw  # moved unchanged
    assert queue.load("old-done") == done and queue.load("old-failed") == failed
    by_answer = json.loads((root / "archive" / "answers" / f"{_key(1)}.json").read_text())
    assert by_answer == {"cache_key": _key(1), "job_ids": ["old-done"]}
    digest = hashlib.sha256(b"client:1").hexdigest()
    by_key = json.loads((root / "archive" / "idempotency" / f"{digest}.json").read_text())
    assert by_key == {"idempotency_key": "client:1", "job_ids": ["old-done"]}
    assert queue.archive(now_utc=NOW) == ()  # nothing is moved twice

    # An archived id stays taken, and history still counts it for its answer's address.
    with pytest.raises(AdviceQueueError, match="already exists"):
        queue.submit(AdviceJob("old-done", "queued", FINGERPRINT, _key(9), NOW, NOW))
    with pytest.raises(AdviceQueueError, match="already exists"):
        queue.submit_unique(AdviceJob("old-failed", "queued", FINGERPRINT, _key(9), NOW, NOW))
    assert queue.history(idempotency_key="client:1", cache_key=_key(3)) == (done, recent)
    assert queue.history(idempotency_key=None, cache_key=_key(2)) == (failed, recent)


def test_nothing_open_is_archived_however_old(tmp_path: Path) -> None:
    root = tmp_path / "jobs"
    queue = FileJobQueue(root)
    cache = FileAdviceCache(tmp_path / "cache")
    queue.submit_unique(AdviceJob("working", "queued", FINGERPRINT, _key(1), OLD, OLD))
    assert queue.claim(at_utc=OLD) is not None
    queue.submit_unique(AdviceJob("waiting", "queued", FINGERPRINT, _key(2), OLD, OLD))
    # Finished, but a crash before cleanup left its reservation naming it.
    left = _finish(queue, cache, "left-reserved", _key(3), at=OLD)
    reservation = root / f"open-{_key(3)}.idx"
    reservation.write_text("left-reserved", encoding="utf-8")
    # Finished, with a reservation at its key that cannot be read.
    _finish(queue, cache, "unreadable-reservation", _key(4), at=OLD)
    (root / f"open-{_key(4)}.idx").write_bytes(b"{not json")
    open_bytes = {name: (root / f"{name}.json").read_bytes() for name in ("working", "waiting")}

    moved = queue.archive(now_utc="2027-01-01T00:00:00Z", retention_seconds=0.0)

    assert [job.job_id for job in moved] == ["left-reserved"]
    assert not reservation.exists()  # removed first: recovery no longer scans the record
    assert {job.job_id: job.status for job in queue.jobs()} == {
        "working": "running",
        "waiting": "queued",
        "unreadable-reservation": "completed",
    }
    assert {name: (root / f"{name}.json").read_bytes() for name in open_bytes} == open_bytes
    queue.recover(at_utc="2027-01-01T00:00:00Z")
    assert queue.load("left-reserved") == left


def test_one_call_is_bounded_and_oldest_goes_first(tmp_path: Path) -> None:
    queue = FileJobQueue(tmp_path / "jobs")
    cache = FileAdviceCache(tmp_path / "cache")
    for number in range(5):
        _finish(queue, cache, f"done-{number}", _key(number), at=f"2026-08-0{number + 1}T10:00:00Z")

    assert queue.archive(now_utc=NOW, budget_seconds=0.0) == ()
    first = queue.archive(now_utc=NOW, max_records=2)
    second = queue.archive(now_utc=NOW, max_records=2)
    third = queue.archive(now_utc=NOW, max_records=2)

    assert [job.job_id for job in first] == ["done-0", "done-1"]
    assert [job.job_id for job in second] == ["done-2", "done-3"]
    assert [job.job_id for job in third] == ["done-4"]
    assert queue.jobs() == ()


def test_an_interrupted_move_is_finished_by_the_next_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "jobs"
    queue = FileJobQueue(root)
    cache = FileAdviceCache(tmp_path / "cache")
    done = _finish(queue, cache, "old-done", _key(1), at=OLD, idempotency_key="client:1")
    real_replace = os.replace

    def fail_into_the_archive(source: Any, target: Any) -> None:
        if Path(target).parent == root / "archive":
            raise OSError("the process died here")
        real_replace(source, target)

    with monkeypatch.context() as patch:
        patch.setattr(file_advice_queue.os, "replace", fail_into_the_archive)
        with pytest.raises(OSError, match="died"):
            queue.archive(now_utc=NOW)

    # The indexes already name it and the record is still live: found once, not twice.
    assert queue.history(idempotency_key="client:1", cache_key=_key(1)) == (done,)
    assert [job.job_id for job in queue.archive(now_utc=NOW)] == ["old-done"]
    assert queue.history(idempotency_key="client:1", cache_key=_key(1)) == (done,)
    assert queue.jobs() == ()


def test_after_one_scan_claim_and_recover_read_only_open_records(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "jobs"
    writer = FileJobQueue(root)
    cache = FileAdviceCache(tmp_path / "cache")
    finished = [f"done-{number:02d}" for number in range(20)]
    for number, name in enumerate(finished):
        _finish(writer, cache, name, _key(number), at=RECENT)
    writer.submit_unique(AdviceJob("open-one", "queued", FINGERPRINT, _key(99), NOW, NOW))
    worker = FileJobQueue(root)  # another process's view of the same store
    reads: list[str] = []
    real_read = Path.read_bytes

    def counted(path: Path) -> bytes:
        if path.parent == root and path.suffix == ".json":
            reads.append(path.stem)
        return real_read(path)

    monkeypatch.setattr(Path, "read_bytes", counted)

    worker.recover(at_utc=NOW)
    assert set(reads) == {*finished, "open-one"}  # the first scan reads each record once

    reads.clear()
    claimed = worker.claim(at_utc=NOW)
    worker.recover(at_utc=NOW)
    worker.jobs()
    assert claimed is not None and claimed.job_id == "open-one"
    assert set(reads) == {"open-one"}

    # A finished record that changed on disk is read again rather than trusted.
    path = root / "done-03.json"
    status = path.stat()
    os.utime(path, ns=(status.st_atime_ns, status.st_mtime_ns + 10_000_000))
    reads.clear()
    worker.jobs()
    assert set(reads) == {"open-one", "done-03"}


def test_a_repeated_post_still_finds_its_archived_job(tmp_path: Path) -> None:
    client, cache, queue = _world(tmp_path)
    failed_key = {"Idempotency-Key": "client:archived:1"}
    first = client.post(ADVICE_URL, json=BODY, headers=failed_key)
    assert first.status_code == 202
    claimed = queue.claim(at_utc="2026-08-27T12:01:00Z")
    assert claimed is not None
    queue.store(
        claimed.transition(
            "failed", at_utc="2026-08-27T12:01:01Z", error=JobError("ADVICE_FAILED", "fixture")
        )
    )
    done_key = {"Idempotency-Key": "client:archived:2"}
    other = {**BODY, "window": 3}
    assert client.post(ADVICE_URL, json=other, headers=done_key).status_code == 202
    claimed = queue.claim(at_utc="2026-08-27T12:02:00Z")
    assert claimed is not None
    queue.complete(
        claimed, cache=cache, payload=_valid_advice_document(), at_utc="2026-08-27T12:02:01Z"
    )

    archived = queue.archive(now_utc="2026-09-10T00:00:00Z")
    assert len(archived) == 2 and queue.jobs() == ()

    # The same key for another request that is not cached is still a conflict, found
    # through the archive. (A cached request is answered before any key is looked at.)
    for key, body in ((failed_key, {**BODY, "window": 5}), (done_key, BODY)):
        conflict = client.post(ADVICE_URL, json=body, headers=key)
        assert conflict.status_code == 409
        assert conflict.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"
    # The same key for the same request: the finished answer, or a new try after a failure
    # whose id is not the archived one's.
    assert client.post(ADVICE_URL, json=other, headers=done_key).status_code == 200
    retry = client.post(ADVICE_URL, json=BODY, headers=failed_key)
    assert retry.status_code == 202
    first_id, retry_id = first.json()["job_id"], retry.json()["job_id"]
    assert retry_id != first_id and retry_id.endswith("-2")
    polled = client.get(f"/api/v1/advice-jobs/{first_id}")
    assert polled.status_code == 200 and polled.json()["status"] == "failed"


def _stop_after(rounds: int) -> Callable[[], bool]:
    remaining = [rounds]

    def stop() -> bool:
        remaining[0] -= 1
        return remaining[0] < 0

    return stop


class _Counted:
    """The real queue, with its archive calls counted and the first ones made to fail."""

    def __init__(self, queue: FileJobQueue, failures: int = 0) -> None:
        self._queue = queue
        self._failures = failures
        self.calls = 0

    def __getattr__(self, name: str) -> Any:
        return getattr(self._queue, name)

    def archive(self, **kwargs: Any) -> Any:
        self.calls += 1
        if self._failures:
            self._failures -= 1
            raise OSError("share unavailable")
        return self._queue.archive(**kwargs)


def test_an_idle_worker_archives_at_most_once_per_interval(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    root = tmp_path / "jobs"
    cache = FileAdviceCache(tmp_path / "cache")
    queue = FileJobQueue(root)
    _finish(queue, cache, "old-done", _key(1), at=OLD)
    now = datetime(2026, 9, 10, 10, tzinfo=UTC)
    caplog.set_level(logging.INFO, logger="advice.worker")

    failing = _Counted(queue, failures=1)
    run_advice_worker(
        failing,
        cache,
        lambda _job: b"x",
        should_stop=_stop_after(10),
        now=lambda: now,
        sleep=lambda _seconds: None,
        idle_seconds=0.5,
        poll_seconds=0.5,
        archive_every_seconds=0.0,
        heartbeat_seconds=None,
        log=AdviceLog("worker"),
    )
    assert failing.calls >= 2  # a failed call is logged and the worker carries on
    assert not (root / "old-done.json").exists()

    once = _Counted(queue)
    run_advice_worker(
        once,
        cache,
        lambda _job: b"x",
        should_stop=_stop_after(10),
        now=lambda: now,
        sleep=lambda _seconds: None,
        idle_seconds=0.5,
        poll_seconds=0.5,
        archive_every_seconds=3600.0,
        heartbeat_seconds=None,
    )
    assert once.calls == 1  # the first idle round, then not again within the hour

    events = [
        json.loads(record.getMessage())
        for record in caplog.records
        if record.name == "advice.worker"
    ]
    names = [event["event"] for event in events]
    assert "advice_jobs_archive_failed" in names
    archived = [event for event in events if event["event"] == "advice_jobs_archived"]
    assert [event["count"] for event in archived] == [1]
