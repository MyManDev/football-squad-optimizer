"""Worker clocks are sampled at the locked transition, not before waiting for it."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from threading import Event

import pytest

from squadopt.platform.advice_cache import FileAdviceCache
from squadopt.platform.advice_queue import FileJobQueue
from squadopt.platform.advice_worker import run_advice_worker
from squadopt.platform.jobs_contract import AdviceJob, BackendJobsContractError

BEFORE = datetime(2026, 9, 1, 10, 0, tzinfo=UTC)
AFTER = datetime(2026, 9, 1, 10, 1, tzinfo=UTC)
FINISHED = datetime(2026, 9, 1, 10, 2, tzinfo=UTC)
BEFORE_STAMP = "2026-09-01T10:00:00Z"
AFTER_STAMP = "2026-09-01T10:01:00Z"


def queued() -> AdviceJob:
    return AdviceJob("job-later", "queued", "a" * 64, "b" * 64, BEFORE_STAMP, BEFORE_STAMP)


@pytest.mark.parametrize("boundary", ["claim-new", "claim-requeued", "recover-running"])
def test_worker_samples_time_after_waiting_for_the_transition_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, boundary: str
) -> None:
    worker_queue = FileJobQueue(tmp_path / "jobs")
    owner_queue = FileJobQueue(tmp_path / "jobs")
    cache = FileAdviceCache(tmp_path / "cache")
    if boundary == "claim-requeued":
        owner_queue.submit(queued())
        assert owner_queue.claim(at_utc=BEFORE_STAMP) is not None
    clock = [BEFORE]
    entering = Event()
    operation = "recover" if boundary == "recover-running" else "claim"
    original = getattr(worker_queue, operation)

    def observed(**kwargs):
        entering.set()
        return original(**kwargs)

    monkeypatch.setattr(worker_queue, operation, observed)
    claims = []

    def compute(job: AdviceJob) -> bytes:
        claims.append(job)
        clock[0] = FINISHED
        return b"answer"

    with ThreadPoolExecutor(max_workers=1) as pool:
        # A distinct adapter owns the actual OS lock, just as another API/worker does.
        with owner_queue._lock.hold():
            future = pool.submit(
                run_advice_worker,
                worker_queue,
                cache,
                compute,
                should_stop=lambda: False,
                now=lambda: clock[0],
                max_jobs=1,
                heartbeat_seconds=None,
                recover_every_seconds=0 if boundary == "recover-running" else float("inf"),
                lease_seconds=0,
            )
            assert entering.wait(timeout=5)
            clock[0] = AFTER
            if boundary == "claim-requeued":
                assert owner_queue.recover(at_utc=AFTER_STAMP, lease_seconds=0)
            else:
                owner_queue.submit(
                    replace(queued(), created_at_utc=AFTER_STAMP, updated_at_utc=AFTER_STAMP)
                )
                if boundary == "recover-running":
                    assert owner_queue.claim(at_utc=AFTER_STAMP) is not None
        assert future.result(timeout=10) == 1

    assert len(claims) == 1
    assert claims[0].updated_at_utc == AFTER_STAMP
    assert claims[0].attempt == (1 if boundary == "claim-new" else 2)
    terminal = owner_queue.load("job-later")
    assert terminal is not None and terminal.status == "completed"
    assert terminal.updated_at_utc == "2026-09-01T10:02:00Z"
    assert cache.get(terminal.cache_key) == b"answer"


@pytest.mark.parametrize("use_clock", [False, True])
@pytest.mark.parametrize("operation", ["claim", "recover"])
def test_queue_does_not_clamp_a_clock_that_really_moves_backwards(
    tmp_path: Path, use_clock: bool, operation: str
) -> None:
    queue = FileJobQueue(tmp_path / "jobs")
    queue.submit(replace(queued(), created_at_utc=AFTER_STAMP, updated_at_utc=AFTER_STAMP))
    if operation == "recover":
        assert queue.claim(at_utc=AFTER_STAMP) is not None
    transition = queue.claim if operation == "claim" else queue.recover
    options = {} if operation == "claim" else {"lease_seconds": 0}
    with pytest.raises(BackendJobsContractError, match="move time backwards"):
        if use_clock:
            transition(clock=lambda: BEFORE_STAMP, **options)
        else:
            transition(at_utc=BEFORE_STAMP, **options)
    assert queue.load("job-later").status == ("queued" if operation == "claim" else "running")
    assert (tmp_path / "jobs" / "job-later.claim").exists() == (operation == "recover")
