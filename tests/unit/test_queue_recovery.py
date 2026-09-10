"""Real process-death prefixes, ownership fencing and isolated corruption."""

import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier, Event

import pytest

from squadopt.platform.advice_cache import FileAdviceCache
from squadopt.platform.advice_queue import (
    AdviceLeaseLostError,
    AdviceQueueIntegrityError,
    FileJobQueue,
    run_advice_worker_once,
)
from squadopt.platform.jobs_contract import AdviceJob

KEY = "b" * 64
START = "2026-08-27T12:00:00Z"
LATER = "2026-08-27T12:10:00Z"


def job(name: str = "job-one", *, key: str = KEY) -> AdviceJob:
    return AdviceJob(name, "queued", "a" * 64, key, START, START)


CRASH = r"""
import os, sys
from pathlib import Path
from squadopt.platform.advice_queue import FileJobQueue
from squadopt.platform.advice_cache import FileAdviceCache
from squadopt.platform.jobs_contract import AdviceJob
root, boundary = Path(sys.argv[1]), sys.argv[2]
q = FileJobQueue(root / 'jobs')
c = FileAdviceCache(root / 'cache')
j = AdviceJob('job-one', 'queued', 'a'*64, 'b'*64,
              '2026-08-27T12:00:00Z', '2026-08-27T12:00:00Z')
if boundary == 'intent':
    q.submit = lambda job: os._exit(73)
q.submit_unique(j)
if boundary == 'claim':
    q._write = lambda path, job: os._exit(73)
running = q.claim(at_utc='2026-08-27T12:00:01Z')
if boundary == 'requeue':
    write = q._write
    def stop_after_write(path, job):
        write(path, job)
        os._exit(73)
    q._write = stop_after_write
    q.recover(at_utc='2026-08-27T12:00:02Z', lease_seconds=0)
if boundary == 'cache':
    put = c.put
    def stop_after_cache(key, payload):
        put(key, payload)
        os._exit(73)
    c.put = stop_after_cache
if boundary == 'terminal':
    q._cleanup = lambda job: os._exit(73)
q.complete(running, cache=c, payload=b'answer', at_utc='2026-08-27T12:00:02Z')
raise AssertionError('crash boundary not reached')
"""


POLL_WITH_OPEN_HANDLE = r"""
import sys
from pathlib import Path
from unittest.mock import patch
from squadopt.platform.advice_queue import FileJobQueue
root = Path(sys.argv[1])
target = root / 'jobs' / 'job-one.json'
original_read = Path.read_bytes
def held_read(path):
    if path != target:
        return original_read(path)
    with path.open('rb') as handle:
        print('handle-open', flush=True)
        if sys.stdin.readline().strip() != 'release':
            raise AssertionError('poll was not released')
        return handle.read()
with patch.object(Path, 'read_bytes', held_read):
    observed = FileJobQueue(root / 'jobs').load('job-one')
assert observed.status == 'running'
"""


def test_polling_read_and_terminal_replace_share_the_process_lock(tmp_path: Path) -> None:
    """A held poll handle must close before another process publishes completion.

    On Windows an overlapping os.replace raises WinError 5. On other platforms the
    same test checks the serialization contract, without relying on handle semantics.
    """

    queue = FileJobQueue(tmp_path / "jobs")
    cache = FileAdviceCache(tmp_path / "cache")
    queue.submit_unique(job())
    running = queue.claim(at_utc=START)
    assert running is not None
    child = subprocess.Popen(
        [sys.executable, "-B", "-c", POLL_WITH_OPEN_HANDLE, str(tmp_path)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    started = Event()

    def complete() -> AdviceJob:
        started.set()
        return queue.complete(running, cache=cache, payload=b"answer", at_utc=LATER)

    try:
        assert child.stdin is not None and child.stdout is not None
        with ThreadPoolExecutor(max_workers=2) as pool:
            try:
                assert (
                    pool.submit(child.stdout.readline).result(timeout=10).strip() == "handle-open"
                )
                future = pool.submit(complete)
                assert started.wait(timeout=5)
                with pytest.raises(TimeoutError):
                    future.result(timeout=0.2)
            finally:
                child.stdin.write("release\n")
                child.stdin.flush()
            completed = future.result(timeout=10)
        assert completed.status == "completed"
        assert cache.get(KEY) == b"answer"
        assert queue.load("job-one") == completed
        _stdout, stderr = child.communicate(timeout=10)
        assert child.returncode == 0, stderr
    finally:
        if child.poll() is None:
            child.kill()
        child.communicate(timeout=10)


@pytest.mark.parametrize("boundary", ["intent", "claim", "requeue", "cache", "terminal"])
def test_process_death_prefix_is_recoverable(tmp_path: Path, boundary: str) -> None:
    child = subprocess.run(
        [sys.executable, "-B", "-c", CRASH, str(tmp_path), boundary],
        capture_output=True,
        timeout=30,
    )
    assert child.returncode == 73, child.stderr.decode(errors="replace")
    queue = FileJobQueue(tmp_path / "jobs")
    cache = FileAdviceCache(tmp_path / "cache")
    queue.recover(at_utc=LATER, lease_seconds=0)
    if boundary == "terminal":
        done = queue.load("job-one")
        assert done is not None and done.status == "completed"
        assert not (tmp_path / "jobs" / f"open-{KEY}.idx").exists()
        assert not (tmp_path / "jobs" / "job-one.claim").exists()
        assert queue.submit_unique(job("next"))[1]
    else:
        winner, created = queue.submit_unique(job("retry"))
        assert not created and winner.job_id == "job-one"
        done = run_advice_worker_once(
            queue, cache, lambda _: b"answer", at_utc=LATER, terminal_at_utc=lambda: LATER
        )
        assert done is not None and done.status == "completed"
        assert done.attempt == (2 if boundary in {"cache", "requeue"} else 1)
    assert cache.get(KEY) == b"answer"


def test_old_attempt_cannot_heartbeat_store_or_publish(tmp_path: Path) -> None:
    queue = FileJobQueue(tmp_path / "jobs")
    cache = FileAdviceCache(tmp_path / "cache")
    queue.submit_unique(job())
    old = queue.claim(at_utc=START)
    assert old is not None
    queue.recover(at_utc=LATER, lease_seconds=0)
    current = queue.claim(at_utc=LATER)
    assert current is not None and current.attempt == 2
    marker = tmp_path / "jobs" / "job-one.claim"
    marker_before = marker.stat().st_mtime_ns
    with pytest.raises(AdviceLeaseLostError):
        queue.heartbeat(old.job_id, attempt=old.attempt)
    with pytest.raises(AdviceLeaseLostError):
        queue.store(old.transition("completed", at_utc=LATER, result_ref=KEY))
    with pytest.raises(AdviceLeaseLostError):
        queue.complete(old, cache=cache, payload=b"obsolete", at_utc=LATER)
    assert marker.stat().st_mtime_ns == marker_before
    assert cache.get(KEY) is None
    assert queue.load(old.job_id) == current
    queue.complete(current, cache=cache, payload=b"current", at_utc=LATER)
    assert cache.get(KEY) == b"current"


def test_worker_discarding_a_lost_attempt_does_not_fail_the_replacement(tmp_path: Path) -> None:
    queue = FileJobQueue(tmp_path / "jobs")
    cache = FileAdviceCache(tmp_path / "cache")
    queue.submit_unique(job())

    def overtaken(_: AdviceJob) -> bytes:
        queue.recover(at_utc=LATER, lease_seconds=0)
        assert queue.claim(at_utc=LATER) is not None
        return b"obsolete"

    assert (
        run_advice_worker_once(queue, cache, overtaken, at_utc=START, terminal_at_utc=lambda: LATER)
        is None
    )
    replacement = queue.load("job-one")
    assert replacement is not None and replacement.attempt == 2 and replacement.status == "running"
    assert cache.get(KEY) is None


def test_two_recoverers_increment_the_attempt_once(tmp_path: Path) -> None:
    queue = FileJobQueue(tmp_path)
    queue.submit_unique(job())
    queue.claim(at_utc=START)
    barrier = Barrier(2)

    def recover(_: int) -> int:
        other = FileJobQueue(tmp_path)
        barrier.wait(timeout=5)
        return len(other.recover(at_utc=LATER, lease_seconds=0))

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(recover, range(2))) == [0, 1]
    recovered = queue.load("job-one")
    assert recovered is not None and recovered.attempt == 2


def test_corrupt_job_is_retained_and_blocks_only_its_own_reservation(tmp_path: Path) -> None:
    queue = FileJobQueue(tmp_path)
    queue.submit_unique(job("broken"))
    queue.submit_unique(job("healthy", key="c" * 64))
    path = tmp_path / "broken.json"
    path.write_bytes(b'{"truncated":')
    assert [j.job_id for j in queue.jobs()] == ["healthy"]
    queue.recover(at_utc=LATER)
    claimed = queue.claim(at_utc=LATER)
    assert claimed is not None and claimed.job_id == "healthy"
    with pytest.raises(AdviceQueueIntegrityError):
        queue.submit_unique(job("duplicate"))
    assert queue.load("duplicate") is None
    assert path.read_bytes() == b'{"truncated":'
    assert queue.integrity_issues()
    assert any(p.read_bytes() == path.read_bytes() for p in (tmp_path / "integrity").glob("*.bin"))


def test_corrupt_identity_is_not_trusted_by_the_scan(tmp_path: Path) -> None:
    queue = FileJobQueue(tmp_path)
    queue.submit(job())
    payload = job("another-id").as_payload()
    (tmp_path / "job-one.json").write_text(json.dumps(payload), encoding="utf-8")
    assert queue.jobs() == ()
    with pytest.raises(AdviceQueueIntegrityError):
        queue.load("job-one")


def test_legacy_incomplete_reservation_is_retained_before_retry(tmp_path: Path) -> None:
    queue = FileJobQueue(tmp_path)
    index = tmp_path / f"open-{KEY}.idx"
    index.write_text("legacy-job", encoding="utf-8")
    queue.recover(at_utc=LATER)
    assert queue.submit_unique(job())[1]
    assert any(p.read_bytes() == b"legacy-job" for p in (tmp_path / "integrity").glob("*.bin"))


def test_processes_cannot_claim_the_same_attempt(tmp_path: Path) -> None:
    queue = FileJobQueue(tmp_path)
    queue.submit_unique(job())
    code = (
        "import sys; from squadopt.platform.advice_queue import FileJobQueue; "
        f"j=FileJobQueue(sys.argv[1]).claim(at_utc={START!r}); "
        "print(j.job_id if j else 'empty')"
    )
    children = [
        subprocess.Popen(
            [sys.executable, "-B", "-c", code, str(tmp_path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=dict(os.environ),
        )
        for _ in range(2)
    ]
    output = []
    for child in children:
        stdout, stderr = child.communicate(timeout=30)
        assert child.returncode == 0, stderr.decode(errors="replace")
        output.append(stdout.decode().strip())
    assert sorted(output) == ["empty", "job-one"]
