"""The queue and the worker loop: claims are exclusive, failures become records."""

import errno
import functools
import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any

import pytest

from squadopt.data import atomic
from squadopt.platform.advice_cache import FileAdviceCache
from squadopt.platform.advice_observability import AdviceLog
from squadopt.platform.advice_queue import (
    AdviceComputeRefused,
    AdviceQueueError,
    FileJobQueue,
    run_advice_worker_once,
)
from squadopt.platform.jobs_contract import AdviceJob
from squadopt.platform.queue_contracts import QueueLockTimeout

FINGERPRINT = "a" * 64
CACHE_KEY = "b" * 64


def _job(job_id: str = "job-0001", created: str = "2026-08-27T12:00:00Z") -> AdviceJob:
    return AdviceJob(
        job_id=job_id,
        status="queued",
        request_fingerprint=FINGERPRINT,
        cache_key=CACHE_KEY,
        created_at_utc=created,
        updated_at_utc=created,
    )


def test_the_worker_completes_a_job_and_the_answer_lands_in_the_cache(
    tmp_path: Path,
) -> None:
    queue = FileJobQueue(tmp_path / "jobs")
    cache = FileAdviceCache(tmp_path / "cache")
    queue.submit(_job())

    done = run_advice_worker_once(
        queue, cache, lambda job: b'{"advice": 1}', at_utc="2026-08-27T12:00:30Z"
    )

    assert done is not None and done.status == "completed"
    assert done.result_ref == CACHE_KEY
    assert cache.get(CACHE_KEY) == b'{"advice": 1}'
    assert queue.load("job-0001") == done  # the record on disk is the terminal one
    assert (
        run_advice_worker_once(queue, cache, lambda j: b"x", at_utc="2026-08-27T12:01:00Z") is None
    )


def test_oldest_job_first_and_a_claim_is_exclusive(tmp_path: Path) -> None:
    queue = FileJobQueue(tmp_path / "jobs")
    queue.submit(_job("job-b", created="2026-08-27T12:00:10Z"))
    queue.submit(_job("job-a", created="2026-08-27T12:00:00Z"))

    first = queue.claim(at_utc="2026-08-27T12:01:00Z")
    second = queue.claim(at_utc="2026-08-27T12:01:00Z")
    third = queue.claim(at_utc="2026-08-27T12:01:00Z")

    assert first is not None and first.job_id == "job-a"  # oldest first
    assert second is not None and second.job_id == "job-b"
    assert third is None  # both claimed; the markers hold


def test_a_failing_compute_becomes_a_failed_record_with_the_reason(tmp_path: Path) -> None:
    queue = FileJobQueue(tmp_path / "jobs")
    cache = FileAdviceCache(tmp_path / "cache")
    queue.submit(_job())

    def explode(job: AdviceJob) -> bytes:
        raise RuntimeError("the projection handoff is stale")

    failed = run_advice_worker_once(queue, cache, explode, at_utc="2026-08-27T12:00:30Z")

    assert failed is not None and failed.status == "failed"
    assert failed.error is not None and failed.error.code == "ADVICE_FAILED"
    assert "stale" in failed.error.message
    assert cache.get(CACHE_KEY) is None


def test_a_conflicting_answer_is_a_determinism_defect_not_a_retry(tmp_path: Path) -> None:
    queue = FileJobQueue(tmp_path / "jobs")
    cache = FileAdviceCache(tmp_path / "cache")
    cache.put(CACHE_KEY, b'{"advice": 1}')
    queue.submit(_job())

    failed = run_advice_worker_once(
        queue, cache, lambda job: b'{"advice": 2}', at_utc="2026-08-27T12:00:30Z"
    )

    assert failed is not None and failed.status == "failed"
    assert failed.error is not None and failed.error.code == "DETERMINISM_DEFECT"
    assert cache.get(CACHE_KEY) == b'{"advice": 1}'  # the first answer stands


def test_an_identical_answer_from_a_retry_completes_quietly(tmp_path: Path) -> None:
    queue = FileJobQueue(tmp_path / "jobs")
    cache = FileAdviceCache(tmp_path / "cache")
    cache.put(CACHE_KEY, b'{"advice": 1}')
    queue.submit(_job())

    done = run_advice_worker_once(
        queue, cache, lambda job: b'{"advice": 1}', at_utc="2026-08-27T12:00:30Z"
    )

    assert done is not None and done.status == "completed"


def test_recover_walks_a_dead_workers_job_back_to_queued(tmp_path: Path) -> None:
    """The disposable-worker rule, end to end: claim, die, lease expires, recover, redo."""

    queue = FileJobQueue(tmp_path / "jobs")
    cache = FileAdviceCache(tmp_path / "cache")
    queue.submit(_job())
    claimed = queue.claim(at_utc="2026-08-27T12:00:05Z")
    assert claimed is not None  # ... and the worker dies here, mid-compute

    recovered = queue.recover(at_utc="2026-08-27T12:05:00Z", lease_seconds=0.0)

    assert len(recovered) == 1
    assert recovered[0].status == "queued"
    assert recovered[0].attempt == 2  # the crash is counted
    done = run_advice_worker_once(
        queue, cache, lambda job: b'{"advice": 1}', at_utc="2026-08-27T12:05:30Z"
    )
    assert done is not None and done.status == "completed"
    assert done.attempt == 2


def test_submit_is_not_upsert_and_store_needs_an_existing_job(tmp_path: Path) -> None:
    queue = FileJobQueue(tmp_path / "jobs")
    queue.submit(_job())
    with pytest.raises(AdviceQueueError, match="already exists"):
        queue.submit(_job())
    with pytest.raises(AdviceQueueError, match="not in this queue"):
        queue.store(_job("job-elsewhere"))
    with pytest.raises(AdviceQueueError, match="queued job"):
        running = _job("job-x").transition("running", at_utc="2026-08-27T12:00:05Z")
        queue.submit(running)


def test_a_live_workers_claim_is_not_stolen_by_recovery(tmp_path: Path) -> None:
    """The reviewed two-worker case: B recovers while A's lease is fresh — nothing
    is requeued; A's heartbeat keeps the claim; after the lease lapses it is fair game."""

    queue = FileJobQueue(tmp_path / "jobs")
    queue.submit(_job())
    claimed = queue.claim(at_utc="2026-08-27T12:00:05Z")
    assert claimed is not None  # worker A, alive and computing

    assert queue.recover(at_utc="2026-08-27T12:00:10Z") == ()  # worker B starts up
    still = queue.load("job-0001")
    assert still is not None and still.status == "running" and still.attempt == 1

    queue.heartbeat("job-0001", attempt=claimed.attempt)  # A is still alive
    assert queue.recover(at_utc="2026-08-27T12:00:20Z") == ()

    stolen = queue.recover(at_utc="2026-08-27T12:10:00Z", lease_seconds=0.0)
    assert len(stolen) == 1 and stolen[0].attempt == 2  # only a lapsed lease is abandoned


def test_concurrent_submitters_cannot_both_create_one_id(tmp_path: Path) -> None:
    import threading

    queue = FileJobQueue(tmp_path / "jobs")
    barrier = threading.Barrier(2)
    outcomes: list[str] = []

    def submit() -> None:
        try:
            barrier.wait(timeout=5)
            queue.submit(_job())
            outcomes.append("ok")
        except AdviceQueueError:
            outcomes.append("refused")

    threads = [threading.Thread(target=submit) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
    assert sorted(outcomes) == ["ok", "refused"]  # at-most-one creation, atomically


def test_unique_submitter_waits_for_the_winners_job_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The index is the reservation; its record may appear a moment later."""

    import threading

    queue = FileJobQueue(tmp_path / "jobs")
    original_submit = queue.submit
    winner_reserved = threading.Event()
    release_winner = threading.Event()
    outcomes: list[tuple[str, bool]] = []

    def delayed_submit(job: AdviceJob) -> None:
        winner_reserved.set()
        assert release_winner.wait(timeout=5)
        original_submit(job)

    monkeypatch.setattr(queue, "submit", delayed_submit)

    def first() -> None:
        winner, created = queue.submit_unique(_job("job-first"))
        outcomes.append((winner.job_id, created))

    def second() -> None:
        winner, created = queue.submit_unique(_job("job-second"))
        outcomes.append((winner.job_id, created))

    first_thread = threading.Thread(target=first)
    first_thread.start()
    assert winner_reserved.wait(timeout=5)
    second_thread = threading.Thread(target=second)
    second_thread.start()
    release_winner.set()
    first_thread.join(timeout=10)
    second_thread.join(timeout=10)

    assert sorted(outcomes) == [("job-first", False), ("job-first", True)]
    assert queue.load("job-second") is None


def test_job_ids_are_validated_before_any_path_is_composed(tmp_path: Path) -> None:
    queue = FileJobQueue(tmp_path / "jobs")
    for hostile in ("../escape", "a/b", "..", "x" * 200):
        with pytest.raises(AdviceQueueError, match="invalid format"):
            queue.load(hostile)


def test_persisted_failure_reasons_carry_no_host_paths(tmp_path: Path) -> None:
    from squadopt.platform.advice_queue import sanitize_error_message

    queue = FileJobQueue(tmp_path / "jobs")
    cache = FileAdviceCache(tmp_path / "cache")
    queue.submit(_job())

    def explode(job: AdviceJob) -> bytes:
        raise RuntimeError(
            r"handoff missing at C:\Users\ertug\data\handoffs\gw03.json and /var/lib/squadopt/cache"
        )

    failed = run_advice_worker_once(queue, cache, explode, at_utc="2026-08-27T12:00:30Z")
    assert failed is not None and failed.error is not None
    assert "ertug" not in failed.error.message
    assert "/var/" not in failed.error.message
    assert "<path>" in failed.error.message
    assert sanitize_error_message("") == "unspecified failure"


def test_the_cause_of_a_refusal_is_logged_for_the_operator_and_not_served(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    queue = FileJobQueue(tmp_path / "jobs")
    cache = FileAdviceCache(tmp_path / "cache")
    queue.submit(_job())
    diagnostic = "deterministic time used was 12.0, relative gap was 0.31"

    def refuse(job: AdviceJob) -> bytes:
        try:
            raise ValueError(diagnostic)
        except ValueError as error:
            raise AdviceComputeRefused("WINDOW_INFEASIBLE", "WINDOW_INFEASIBLE") from error

    logger = logging.getLogger("test.advice.refusal")
    with caplog.at_level(logging.INFO, logger=logger.name):
        failed = run_advice_worker_once(
            queue, cache, refuse, at_utc="2026-08-27T12:00:30Z", log=AdviceLog("worker", logger)
        )

    assert failed is not None and failed.error is not None
    assert failed.error.code == "WINDOW_INFEASIBLE"
    # What the api serves names the code and nothing of the solver.
    assert "deterministic" not in failed.error.message
    events = [json.loads(record.getMessage()) for record in caplog.records]
    refused = next(event for event in events if event["event"] == "advice_job_refused")
    assert refused["code"] == "WINDOW_INFEASIBLE" and refused["detail"] == diagnostic


def test_a_crash_is_logged_with_its_type_and_text(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    queue = FileJobQueue(tmp_path / "jobs")
    cache = FileAdviceCache(tmp_path / "cache")
    queue.submit(_job())

    def explode(job: AdviceJob) -> bytes:
        raise RuntimeError("the projection handoff is stale")

    logger = logging.getLogger("test.advice.crash")
    with caplog.at_level(logging.INFO, logger=logger.name):
        run_advice_worker_once(
            queue, cache, explode, at_utc="2026-08-27T12:00:30Z", log=AdviceLog("worker", logger)
        )

    events = [json.loads(record.getMessage()) for record in caplog.records]
    crashed = next(event for event in events if event["event"] == "advice_job_failed")
    assert crashed["error_type"] == "RuntimeError" and "stale" in crashed["detail"]


# The worker's queue waits LOCK_TIMEOUT for the metadata lock rather than five seconds, so
# holding the real file lock past that timeout keeps these tests short.
LOCK_TIMEOUT = 0.3


def _worker_queue(root: Path, monkeypatch: pytest.MonkeyPatch) -> FileJobQueue:
    from squadopt.platform import file_advice_queue
    from squadopt.platform._queue_lock import QueueFileLock

    with monkeypatch.context() as patch:
        patch.setattr(
            file_advice_queue,
            "QueueFileLock",
            functools.partial(QueueFileLock, timeout_seconds=LOCK_TIMEOUT),
        )
        return FileJobQueue(root)


def _hold_the_lock(root: Path, seconds: float) -> threading.Thread:
    """Another process's transaction, as the OS sees it: the same lock file, held."""

    from squadopt.platform._queue_lock import QueueFileLock

    taken = threading.Event()

    def hold() -> None:
        with QueueFileLock(root / ".queue.lock").hold():
            taken.set()
            time.sleep(seconds)

    holder = threading.Thread(target=hold)
    holder.start()
    assert taken.wait(timeout=5)
    return holder


def test_a_busy_lock_at_completion_is_waited_out_and_the_solve_completes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "jobs"
    queue = _worker_queue(root, monkeypatch)
    cache = FileAdviceCache(tmp_path / "cache")
    queue.submit(_job())
    holders: list[threading.Thread] = []
    attempts: list[str] = []
    original_complete = queue.complete

    def counted_complete(job: AdviceJob, **kwargs: object) -> AdviceJob:
        attempts.append(job.job_id)
        return original_complete(job, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(queue, "complete", counted_complete)

    def compute(job: AdviceJob) -> bytes:
        holders.append(_hold_the_lock(root, LOCK_TIMEOUT * 3))
        return b'{"advice": 1}'

    done = run_advice_worker_once(
        queue, cache, compute, at_utc="2026-08-27T12:00:30Z", complete_retry_seconds=5.0
    )
    holders[0].join(timeout=5)

    assert len(attempts) >= 2  # the first completion timed out on the held lock
    assert done is not None and done.status == "completed" and done.error is None
    assert cache.get(CACHE_KEY) == b'{"advice": 1}'
    assert queue.load("job-0001") == done


def test_a_lock_busy_past_the_budget_keeps_the_answer_and_leaves_the_job_to_recovery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    root = tmp_path / "jobs"
    queue = _worker_queue(root, monkeypatch)
    cache = FileAdviceCache(tmp_path / "cache")
    queue.submit(_job())
    holders: list[threading.Thread] = []
    stored: list[str] = []
    real_store = queue.store

    def watched_store(job: AdviceJob) -> None:
        # Recorded before the lock is asked for: a failure record that is only attempted,
        # and then times out on the same busy lock, still counts.
        stored.append(job.status)
        real_store(job)

    monkeypatch.setattr(queue, "store", watched_store)

    def compute(job: AdviceJob) -> bytes:
        holders.append(_hold_the_lock(root, LOCK_TIMEOUT * 3))
        return b'{"advice": 1}'

    logger = logging.getLogger("test.advice.deferred")
    with (
        caplog.at_level(logging.INFO, logger=logger.name),
        pytest.raises(QueueLockTimeout),
    ):
        run_advice_worker_once(
            queue,
            cache,
            compute,
            at_utc="2026-08-27T12:00:30Z",
            complete_retry_seconds=0.0,
            log=AdviceLog("worker", logger),
        )
    holders[0].join(timeout=5)

    # Contention is not a failed computation: no failure record was even attempted, the job
    # is still open and the answer is kept.
    assert "failed" not in stored
    still = queue.load("job-0001")
    assert still is not None and still.status == "running" and still.error is None
    assert cache.get(CACHE_KEY) == b'{"advice": 1}'
    events = [json.loads(record.getMessage())["event"] for record in caplog.records]
    assert "advice_job_completion_deferred" in events
    assert "advice_job_failed" not in events

    recovered = queue.recover(at_utc="2026-08-27T12:10:00Z", lease_seconds=0.0)
    assert len(recovered) == 1 and recovered[0].attempt == 2

    def must_not_solve_again(job: AdviceJob) -> bytes:
        raise AssertionError("the retry must be served from the cache")

    done = run_advice_worker_once(queue, cache, must_not_solve_again, at_utc="2026-08-27T12:10:30Z")
    assert done is not None and done.status == "completed" and done.result_ref == CACHE_KEY
    assert cache.get(CACHE_KEY) == b'{"advice": 1}'


class _CompleteAlwaysBusy:
    """A queue whose lock is busy only for ``complete``; every other operation is real."""

    def __init__(self, queue: FileJobQueue) -> None:
        self._queue = queue

    def __getattr__(self, name: str) -> Any:
        return getattr(self._queue, name)

    def complete(self, job: AdviceJob, **_kwargs: Any) -> AdviceJob:
        raise QueueLockTimeout("Queue metadata transaction is busy.")


def test_contention_at_completion_is_never_stored_as_a_failure(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """No timing: only ``complete`` is busy, so a failure record would be stored if tried."""

    queue = FileJobQueue(tmp_path / "jobs")
    cache = FileAdviceCache(tmp_path / "cache")
    queue.submit(_job())

    logger = logging.getLogger("test.advice.contention")
    with (
        caplog.at_level(logging.INFO, logger=logger.name),
        pytest.raises(QueueLockTimeout),
    ):
        run_advice_worker_once(
            _CompleteAlwaysBusy(queue),
            cache,
            lambda job: b'{"advice": 1}',
            at_utc="2026-08-27T12:00:30Z",
            complete_retry_seconds=0.0,
            log=AdviceLog("worker", logger),
        )

    still = queue.load("job-0001")
    assert still is not None and still.status == "running" and still.error is None
    assert cache.get(CACHE_KEY) == b'{"advice": 1}'
    events = [json.loads(record.getMessage())["event"] for record in caplog.records]
    assert "advice_job_failed" not in events


def test_a_queue_record_refused_twice_while_a_reader_holds_it_lands_on_a_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Windows refuses the rename (WinError 5) while a reader outside the lock holds it."""

    queue = FileJobQueue(tmp_path / "jobs")
    cache = FileAdviceCache(tmp_path / "cache")
    queue.submit(_job())
    real_replace = os.replace
    refused: list[str] = []

    def held(source: str | Path, destination: str | Path) -> None:
        if str(destination).endswith("job-0001.json") and len(refused) < 2:
            refused.append(str(destination))
            raise PermissionError(errno.EACCES, "Access is denied")
        real_replace(source, destination)

    monkeypatch.setattr("squadopt.data.atomic.os.replace", held)
    monkeypatch.setattr("squadopt.data.atomic.time.sleep", lambda _seconds: None)
    done = run_advice_worker_once(
        queue, cache, lambda job: b'{"advice": 1}', at_utc="2026-08-27T12:00:30Z"
    )

    assert len(refused) == 2
    assert done is not None and done.status == "completed"
    assert queue.load("job-0001") == done
    assert not list((tmp_path / "jobs").glob("*.tmp"))


def test_a_terminal_record_refused_on_every_attempt_is_stored_as_a_failed_job(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A lasting refusal of the completion write stays inside the round, as ADVICE_FAILED.

    The claim lands, then the terminal record is refused on all ``RENAME_RETRY_ATTEMPTS``
    attempts (the first try and four retries, four pauses in between). The round's own
    ``except Exception`` stores the failure record, which lands, so the worker loop never
    sees the error. The answer was cached before the refused write.
    """

    queue = FileJobQueue(tmp_path / "jobs")
    cache = FileAdviceCache(tmp_path / "cache")
    queue.submit(_job())
    real_replace = os.replace
    calls: list[str] = []
    refused: list[str] = []
    pauses: list[float] = []

    def held(source: str | Path, destination: str | Path) -> None:
        if str(destination).endswith("job-0001.json"):
            calls.append(str(destination))
            # Call 1 is the claim; calls 2 to 6 are the terminal record; call 7 is the
            # failure record.
            if 2 <= len(calls) <= 1 + atomic.RENAME_RETRY_ATTEMPTS:
                refused.append(str(destination))
                raise PermissionError(errno.EACCES, "Access is denied")
        real_replace(source, destination)

    monkeypatch.setattr("squadopt.data.atomic.os.replace", held)
    monkeypatch.setattr("squadopt.data.atomic.time.sleep", pauses.append)
    done = run_advice_worker_once(
        queue, cache, lambda job: b'{"advice": 1}', at_utc="2026-08-27T12:00:30Z"
    )

    assert len(refused) == atomic.RENAME_RETRY_ATTEMPTS == 5
    assert pauses == [0.05, 0.1, 0.2, 0.4]
    assert done is not None and done.status == "failed"
    assert done.error is not None and done.error.code == "ADVICE_FAILED"
    assert "was refused on all 5 attempts over 0.75 s" in done.error.message
    assert queue.load("job-0001") == done
    assert cache.get(CACHE_KEY) == b'{"advice": 1}'
    assert not list((tmp_path / "jobs").glob("*.tmp"))
