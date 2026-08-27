"""The queue and the worker loop: claims are exclusive, failures become records."""

from pathlib import Path

import pytest

from squadopt.platform.advice_cache import FileAdviceCache
from squadopt.platform.advice_queue import (
    AdviceQueueError,
    FileJobQueue,
    run_advice_worker_once,
)
from squadopt.platform.jobs_contract import AdviceJob

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

    queue.heartbeat("job-0001")  # A is still alive
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
