"""A worker says it is alive, and ``/ready`` says whether any worker is (audit M13, M27).

What these pin: the worker's document is its host, its pid, the job it holds and the time,
named by host and pid so workers sharing a pid stay apart, written whole through the
repository's publishing rename on every round and kept going while a round holds a job;
readiness is false when every document is older than 120 s or when a queued job has waited
longer than the 300 s lease; and the public body stays six booleans with no path in it,
while ``/health`` still asks nothing of anybody. The same held look counts the workers
alive and busy and the queued jobs ahead of each one, for the job view.
"""

from __future__ import annotations

import errno
import inspect
import json
import os
import signal
import socket
import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from tests.unit.test_backend_runtime import _deployment  # noqa: F401 - the "deployment" fixture

import squadopt.platform.advice_worker as worker_module
import squadopt.platform.worker_heartbeat as heartbeat_module
from squadopt.api.runtime import app_for_backend
from squadopt.data.atomic import replace_retrying
from squadopt.platform import ApiServiceInfo
from squadopt.platform.advice_cache import FileAdviceCache
from squadopt.platform.advice_observability import AdviceLog
from squadopt.platform.advice_queue import FileJobQueue
from squadopt.platform.advice_worker import (
    DEFAULT_IDLE_SECONDS,
    DEFAULT_MAX_BACKOFF_SECONDS,
    run_advice_worker,
)
from squadopt.platform.backend_runtime import BackendConfig, build_backend
from squadopt.platform.jobs_contract import AdviceJob
from squadopt.platform.queue_contracts import DEFAULT_LEASE_SECONDS
from squadopt.platform.storage._queue_lock import QueueFileLock, QueueLockTimeout
from squadopt.platform.worker_heartbeat import (
    HEARTBEAT_CONTRACT_VERSION,
    PULSE_SECONDS,
    QUEUED_JOB_LIMIT_SECONDS,
    WORKER_STALE_AFTER_SECONDS,
    WorkerCounts,
    WorkerHeartbeat,
    WorkerLiveness,
    freshest_heartbeat_age,
    host_label,
    oldest_queued_wait,
    prune_stale_heartbeats,
    worker_counts,
)

NOW = datetime(2026, 9, 25, 12, 0, tzinfo=UTC)
CHECKS = (
    "capture_context",
    "league_tree",
    "cache_store",
    "league_tree_matches_capture",
    "worker_heartbeat",
    "queue_wait",
)


def _at(seconds_ago: float) -> Callable[[], datetime]:
    return lambda: NOW - timedelta(seconds=seconds_ago)


def _stamp(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def _queued(job_id: str, *, waited: float, key: str = "2") -> AdviceJob:
    stamp = _stamp(NOW - timedelta(seconds=waited))
    return AdviceJob(
        job_id=job_id,
        status="queued",
        request_fingerprint="1" * 64,
        cache_key=key * 64,
        created_at_utc=stamp,
        updated_at_utc=stamp,
    )


def _stop_after(rounds: int) -> Callable[[], bool]:
    remaining = [rounds]

    def stop() -> bool:
        remaining[0] -= 1
        return remaining[0] < 0

    return stop


class _Log(AdviceLog):
    def __init__(self) -> None:
        super().__init__("test")
        self.events: list[dict[str, object]] = []

    def event(self, name: str, **fields: object) -> None:
        self.events.append({"event": name, **fields})


# The bounds.


def test_the_bounds_are_stated_from_the_idle_wait_and_the_lease() -> None:
    """120 s is 60 idle waits; it covers the longest gap a live loop leaves between beats."""

    lock_wait = inspect.signature(QueueFileLock.__init__).parameters["timeout_seconds"].default
    assert DEFAULT_IDLE_SECONDS == 2.0
    assert WORKER_STALE_AFTER_SECONDS == 60 * DEFAULT_IDLE_SECONDS == 120.0
    # A round that raised waits out the backoff cap, then recovers and claims, each of which
    # may wait out the queue lock before it gives up.
    assert DEFAULT_MAX_BACKOFF_SECONDS + 2 * lock_wait < WORKER_STALE_AFTER_SECONDS
    # A round holding a job beats at least four times within the bound.
    assert 4 * PULSE_SECONDS <= WORKER_STALE_AFTER_SECONDS
    assert QUEUED_JOB_LIMIT_SECONDS == DEFAULT_LEASE_SECONDS == 300.0


# The worker's document.


def test_a_beat_writes_the_host_pid_job_and_time_and_replaces_the_last_one(
    tmp_path: Path,
) -> None:
    root = tmp_path / "workers"
    moments = [NOW - timedelta(seconds=30), NOW, NOW]
    heartbeat = WorkerHeartbeat(root, pid=4242, host="box-1", clock=lambda: moments.pop(0))

    heartbeat.beat()
    heartbeat.beat()

    assert sorted(path.name for path in root.iterdir()) == ["worker-box-1-4242.json"]
    assert json.loads(heartbeat.path.read_bytes()) == {
        "at_utc": "2026-09-25T12:00:00Z",
        "contract_version": HEARTBEAT_CONTRACT_VERSION,
        "host": "box-1",
        "job_id": None,
        "pid": 4242,
    }
    heartbeat.hold("advice-0123456789abcdef-1")
    heartbeat.beat()
    assert json.loads(heartbeat.path.read_bytes())["job_id"] == "advice-0123456789abcdef-1"


def test_workers_sharing_a_pid_on_two_hosts_keep_two_documents(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Under Docker every worker container gives its worker the same pid (7 on the host)."""

    root = tmp_path / "workers"
    hosts = iter(["3f2a9c1b0d4e", "8be7d6c5a4f3"])
    monkeypatch.setattr(heartbeat_module.socket, "gethostname", lambda: next(hosts))
    first = WorkerHeartbeat(root, pid=7, clock=_at(0))
    second = WorkerHeartbeat(root, pid=7, clock=_at(0))
    for heartbeat in (first, second, first):
        heartbeat.beat()

    assert sorted(path.name for path in root.iterdir()) == [
        "worker-3f2a9c1b0d4e-7.json",
        "worker-8be7d6c5a4f3-7.json",
    ]
    assert worker_counts(root, now=NOW) == WorkerCounts(busy=0, total=2)
    second.clear()
    assert [path.name for path in root.iterdir()] == ["worker-3f2a9c1b0d4e-7.json"]


def test_a_host_name_is_made_fit_for_a_file_name() -> None:
    assert host_label("3f2a9c1b0d4e") == "3f2a9c1b0d4e"
    assert host_label("My Host_01.local") == "My-Host-01.local"
    assert host_label("-.box.-") == "box"
    assert host_label("") == host_label("///") == "host"
    assert host_label("a" * 80) == "a" * 63
    assert host_label(socket.gethostname()) == host_label(host_label(socket.gethostname()))


def test_a_beat_lands_through_the_repository_publishing_rename(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Staged in a sibling and moved whole, so a reader sees the old document or the new."""

    renames: list[tuple[str, str]] = []

    def recorded(source: Path, destination: Path) -> None:
        renames.append((source.name, destination.name))
        assert source.parent == destination.parent
        replace_retrying(source, destination)

    monkeypatch.setattr(heartbeat_module, "replace_retrying", recorded)
    WorkerHeartbeat(tmp_path / "workers", pid=7, host="box", clock=_at(0)).beat()

    assert len(renames) == 1
    staged, landed = renames[0]
    assert landed == "worker-box-7.json"
    assert staged.startswith(".worker-box-7.json.") and staged.endswith(".tmp")
    assert sorted(path.name for path in (tmp_path / "workers").iterdir()) == ["worker-box-7.json"]


def test_a_failed_rename_leaves_no_staging_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refused(_source: Path, _destination: Path) -> None:
        raise PermissionError("held")

    monkeypatch.setattr(heartbeat_module, "replace_retrying", refused)
    with pytest.raises(PermissionError):
        WorkerHeartbeat(tmp_path / "workers", pid=7, clock=_at(0)).beat()
    assert list((tmp_path / "workers").iterdir()) == []


def test_a_beat_never_creates_a_missing_store_root(tmp_path: Path) -> None:
    """The heartbeat must not paper over a forgotten volume the store probe would catch."""

    with pytest.raises(FileNotFoundError):
        WorkerHeartbeat(tmp_path / "never-mounted" / "workers", pid=7).beat()
    assert not (tmp_path / "never-mounted").exists()


def test_clear_removes_only_this_workers_document(tmp_path: Path) -> None:
    root = tmp_path / "workers"
    mine = WorkerHeartbeat(root, pid=1, host="box", clock=_at(0))
    other = WorkerHeartbeat(root, pid=2, host="box", clock=_at(0))
    mine.beat()
    other.beat()
    mine.clear()
    mine.clear()  # a second stop finds nothing and says nothing
    assert sorted(path.name for path in root.iterdir()) == ["worker-box-2.json"]


def test_prune_removes_only_heartbeat_files_nobody_touched_for_a_day(tmp_path: Path) -> None:
    root = tmp_path / "workers"
    root.mkdir()
    now = time.time()
    day_old = now - 24 * 60 * 60 - 60
    files = {
        "worker-11.json": day_old,
        "worker-12.json": now - 60,
        ".worker-11.json.0123456789abcdef.tmp": day_old,
        "worker-box-11.json": day_old,
        "worker-box-12.json": now - 60,
        ".worker-box-11.json.0123456789abcdef.tmp": day_old,
        "notes.json": day_old,
    }
    for name, modified in files.items():
        (root / name).write_text("{}", encoding="utf-8")
        os.utime(root / name, (modified, modified))

    assert prune_stale_heartbeats(root, clock=lambda: now) == 4
    assert sorted(path.name for path in root.iterdir()) == [
        "notes.json",
        "worker-12.json",
        "worker-box-12.json",
    ]
    assert prune_stale_heartbeats(tmp_path / "absent") == 0


# Reading the documents.


def test_the_freshest_readable_heartbeat_decides_and_unreadable_ones_count_for_nothing(
    tmp_path: Path,
) -> None:
    root = tmp_path / "workers"
    assert freshest_heartbeat_age(root, now=NOW) is None
    WorkerHeartbeat(root, pid=1, clock=_at(300)).beat()
    WorkerHeartbeat(root, pid=2, clock=_at(90)).beat()
    (root / "worker-3.json").write_text("not json", encoding="utf-8")
    (root / "worker-4.json").write_text(
        json.dumps({"contract_version": "other", "pid": 4, "at_utc": _stamp(NOW)}),
        encoding="utf-8",
    )
    (root / "worker-5.json").write_text(
        json.dumps(
            {"contract_version": HEARTBEAT_CONTRACT_VERSION, "pid": True, "at_utc": _stamp(NOW)}
        ),
        encoding="utf-8",
    )
    (root / "unrelated.json").write_text(
        json.dumps({"contract_version": HEARTBEAT_CONTRACT_VERSION, "pid": 6, "at_utc": "x"}),
        encoding="utf-8",
    )
    assert freshest_heartbeat_age(root, now=NOW) == 90.0


def test_workers_alive_and_busy_are_counted_by_the_readiness_rule(tmp_path: Path) -> None:
    root = tmp_path / "workers"
    assert worker_counts(root, now=NOW) == WorkerCounts(busy=0, total=0)  # none ever beat
    WorkerHeartbeat(root, pid=7, host="idle", clock=_at(10)).beat()
    busy = WorkerHeartbeat(root, pid=7, host="busy", clock=_at(WORKER_STALE_AFTER_SECONDS))
    busy.hold("advice-0123456789abcdef-1")
    busy.beat()
    gone = WorkerHeartbeat(root, pid=7, host="gone", clock=_at(WORKER_STALE_AFTER_SECONDS + 1))
    gone.hold("advice-fedcba9876543210-1")
    gone.beat()
    WorkerHeartbeat(root, pid=8, host="ahead", clock=_at(-3600)).beat()
    (root / "worker-9.json").write_text(  # a worker from before the host name: never busy
        json.dumps(
            {"at_utc": _stamp(NOW), "contract_version": HEARTBEAT_CONTRACT_VERSION, "pid": 9}
        ),
        encoding="utf-8",
    )
    (root / "worker-damaged-10.json").write_text("not json", encoding="utf-8")

    assert worker_counts(root, now=NOW) == WorkerCounts(busy=1, total=3)
    busy.hold(None)
    busy.beat()
    assert worker_counts(root, now=NOW) == WorkerCounts(busy=0, total=3)
    assert WorkerCounts(busy=1, total=3).as_view() == {"busy": 1, "total": 3}


def test_a_heartbeat_stamped_ahead_of_the_clock_is_not_fresh_for_ever(tmp_path: Path) -> None:
    """A clock that stepped back must not keep a stopped worker's document looking fresh."""

    root = tmp_path / "workers"
    WorkerHeartbeat(root, pid=1, clock=_at(-3600)).beat()
    assert freshest_heartbeat_age(root, now=NOW) == 3600.0


def test_the_queued_wait_counts_queued_jobs_only_from_when_they_entered_the_queue() -> None:
    running = _queued("advice-running-1", waited=900).transition(
        "running", at_utc=_stamp(NOW - timedelta(seconds=800))
    )
    requeued = running.transition("queued", at_utc=_stamp(NOW - timedelta(seconds=20)))
    jobs = [running, requeued, _queued("advice-waiting-1", waited=45, key="3")]
    assert oldest_queued_wait(jobs, now=NOW) == 45.0
    assert oldest_queued_wait([running], now=NOW) is None
    assert oldest_queued_wait([_queued("advice-ahead-1", waited=-30)], now=NOW) == 0.0


# The two readiness checks.


def test_no_worker_heartbeat_fresher_than_the_bound_is_not_ready(tmp_path: Path) -> None:
    root = tmp_path / "workers"
    queue = FileJobQueue(tmp_path / "jobs")

    def liveness() -> WorkerLiveness:
        return WorkerLiveness(root, queue, clock=lambda: NOW, recheck_seconds=0.0)

    assert liveness().checks() == (False, True)  # no worker has ever beaten
    WorkerHeartbeat(root, pid=1, clock=_at(WORKER_STALE_AFTER_SECONDS + 1)).beat()
    assert liveness().checks() == (False, True)
    WorkerHeartbeat(root, pid=2, clock=_at(WORKER_STALE_AFTER_SECONDS)).beat()
    assert liveness().checks() == (True, True)  # one live worker is enough


def test_a_queued_job_older_than_the_bound_is_not_ready(tmp_path: Path) -> None:
    root = tmp_path / "workers"
    WorkerHeartbeat(root, pid=1, clock=_at(0)).beat()
    queue = FileJobQueue(tmp_path / "jobs")
    liveness = WorkerLiveness(root, queue, clock=lambda: NOW, recheck_seconds=0.0)

    queue.submit(_queued("advice-waiting-1", waited=QUEUED_JOB_LIMIT_SECONDS))
    assert liveness.checks() == (True, True)
    queue.submit(_queued("advice-waiting-2", waited=QUEUED_JOB_LIMIT_SECONDS + 1, key="3"))
    assert liveness.checks() == (True, False)

    # A long-running claim is a busy worker, not a stuck queue.
    claimed = queue.claim(at_utc=_stamp(NOW))
    assert claimed is not None and claimed.job_id == "advice-waiting-2"
    assert liveness.checks() == (True, True)


def test_a_queue_that_cannot_be_read_is_not_a_queue_that_moves(tmp_path: Path) -> None:
    class _BusyQueue:
        def jobs(self) -> tuple[AdviceJob, ...]:
            raise QueueLockTimeout("Queue metadata transaction is busy.")

    root = tmp_path / "workers"
    WorkerHeartbeat(root, pid=1, clock=_at(0)).beat()
    liveness = WorkerLiveness(
        root,
        _BusyQueue(),  # type: ignore[arg-type]
        clock=lambda: NOW,
        recheck_seconds=0.0,
    )
    assert liveness.checks() == (True, False)
    look = liveness.look()
    assert look.queued is None
    assert look.queue_position(_queued("advice-waiting-1", waited=0)) is None
    assert look.workers == WorkerCounts(busy=0, total=1)


def test_a_damaged_queue_record_is_set_aside_by_the_scan_and_not_counted(
    tmp_path: Path,
) -> None:
    """The scan keeps the record's bytes as evidence and skips it; the look still succeeds."""

    root = tmp_path / "workers"
    WorkerHeartbeat(root, pid=1, clock=_at(0)).beat()
    queue = FileJobQueue(tmp_path / "jobs")
    queue.submit(_queued("advice-waiting-1", waited=QUEUED_JOB_LIMIT_SECONDS))
    (tmp_path / "jobs" / "advice-damaged-1.json").write_text("not json", encoding="utf-8")
    liveness = WorkerLiveness(root, queue, clock=lambda: NOW, recheck_seconds=0.0)

    assert liveness.checks() == (True, True)
    assert len(list((tmp_path / "jobs" / "integrity").glob("*.bin"))) == 1


@pytest.mark.parametrize("fails", ["at_the_call", "partway"])
def test_a_heartbeat_directory_that_cannot_be_listed_is_not_a_live_worker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fails: str
) -> None:
    """A listing that raises is a check that could not be made, not an error for ``/ready``."""

    root = tmp_path / "workers"
    WorkerHeartbeat(root, pid=1, clock=_at(0)).beat()
    WorkerHeartbeat(root, pid=2, clock=_at(0)).beat()
    listing = Path.iterdir

    def refuse(self: Path) -> Iterator[Path]:
        if self != root:
            return listing(self)
        if fails == "at_the_call":
            raise OSError(errno.EIO, "The heartbeat directory cannot be read")

        def first_then_fail() -> Iterator[Path]:
            yield next(iter(listing(self)))
            raise OSError(errno.EIO, "The heartbeat directory cannot be read")

        return first_then_fail()

    monkeypatch.setattr(Path, "iterdir", refuse)
    liveness = WorkerLiveness(
        root, FileJobQueue(tmp_path / "jobs"), clock=lambda: NOW, recheck_seconds=0.0
    )
    assert liveness.checks() == (False, True)
    assert liveness.look().workers is None  # not "no workers": a count that could not be made


def test_one_look_answers_readiness_for_the_recheck_interval(tmp_path: Path) -> None:
    """``/ready`` is public, so a burst of probes costs one queue scan, not one each."""

    scans: list[int] = []

    class _CountingQueue(FileJobQueue):
        def jobs(self) -> tuple[AdviceJob, ...]:
            scans.append(1)
            return super().jobs()

    root = tmp_path / "workers"
    clock = [0.0]
    liveness = WorkerLiveness(
        root, _CountingQueue(tmp_path / "jobs"), clock=lambda: NOW, monotonic=lambda: clock[0]
    )
    assert liveness.checks() == (False, True)
    WorkerHeartbeat(root, pid=1, clock=_at(0)).beat()
    clock[0] = 4.9
    assert liveness.checks() == (False, True)
    assert len(scans) == 1
    clock[0] = 5.0
    assert liveness.checks() == (True, True)
    assert len(scans) == 2


def test_a_queued_jobs_place_is_counted_in_the_order_the_queue_claims(tmp_path: Path) -> None:
    root = tmp_path / "workers"
    queue = FileJobQueue(tmp_path / "jobs")
    clock = [0.0]
    liveness = WorkerLiveness(root, queue, clock=lambda: NOW, monotonic=lambda: clock[0])
    # Named against their arrival: by file name the first to arrive would be the last.
    first = _queued("advice-zz-1", waited=30, key="2")
    second = _queued("advice-mm-1", waited=20, key="3")
    third = _queued("advice-aa-1", waited=10, key="4")
    for job in (third, first, second):
        queue.submit(job)

    look = liveness.look()
    assert [look.queue_position(job) for job in (first, second, third)] == [0, 1, 2]
    claimed = queue.claim(at_utc=_stamp(NOW))
    assert claimed is not None and claimed.job_id == first.job_id  # next is what it said
    assert look.queue_position(claimed) is None  # a running job has no place

    clock[0] = 5.0
    look = liveness.look()
    assert [look.queue_position(job) for job in (second, third)] == [0, 1]
    # One that arrived after the look counts the jobs that look saw ahead of it.
    fourth = _queued("advice-00-1", waited=0, key="5")
    queue.submit(fourth)
    assert liveness.look().queue_position(fourth) == 2

    # The first job's worker dies: recovery puts it back where it arrived, ahead of the rest.
    (requeued,) = queue.recover(at_utc=_stamp(NOW), lease_seconds=0.0)
    clock[0] = 10.0
    look = liveness.look()
    current = [queue.load(job.job_id) for job in (first, second, third, fourth)]
    assert [look.queue_position(job) for job in current if job is not None] == [0, 1, 2, 3]
    assert requeued.attempt == 2 and queue.claim(at_utc=_stamp(NOW)) == requeued.transition(
        "running", at_utc=_stamp(NOW)
    )


def test_one_look_answers_the_job_view_for_the_recheck_interval(tmp_path: Path) -> None:
    """Every waiting member polls; the look they read costs one scan per five seconds."""

    scans: list[int] = []

    class _CountingQueue(FileJobQueue):
        def jobs(self) -> tuple[AdviceJob, ...]:
            scans.append(1)
            return super().jobs()

    root = tmp_path / "workers"
    queue = _CountingQueue(tmp_path / "jobs")
    queue.submit(_queued("advice-early-1", waited=60))
    clock = [0.0]
    liveness = WorkerLiveness(root, queue, clock=lambda: NOW, monotonic=lambda: clock[0])
    held = liveness.look()
    assert held.workers == WorkerCounts(busy=0, total=0)

    busy = WorkerHeartbeat(root, pid=7, host="box", clock=_at(0))
    busy.hold("advice-early-1")
    busy.beat()
    late = _queued("advice-late-1", waited=0, key="3")
    queue.submit(_queued("advice-between-1", waited=30, key="4"))
    queue.submit(late)
    clock[0] = 4.9
    assert liveness.look() is held
    assert liveness.checks() == (False, True)
    assert held.queue_position(late) == 1  # the look still sees one job ahead, not two
    assert len(scans) == 1

    clock[0] = 5.0
    fresh = liveness.look()
    assert fresh.workers == WorkerCounts(busy=1, total=1)
    assert fresh.queue_position(late) == 2
    assert liveness.checks() == (True, True)
    assert len(scans) == 2


# The worker loop.


def test_every_round_the_store_lets_begin_beats_once(tmp_path: Path) -> None:
    states = [False, True, True]
    beats: list[int] = []
    run_advice_worker(
        FileJobQueue(tmp_path / "jobs"),
        FileAdviceCache(tmp_path / "cache"),
        lambda _job: b"{}",
        should_stop=_stop_after(3),
        idle_seconds=0.0,
        store_ready=lambda: states.pop(0),
        heartbeat=lambda: beats.append(1),
    )
    assert states == []
    assert len(beats) == 2  # the round the store refused wrote nothing to it


def test_a_heartbeat_that_fails_is_logged_once_and_never_ends_the_loop(tmp_path: Path) -> None:
    outcomes: list[Exception | None] = [OSError("store gone"), OSError("store gone"), None]
    calls: list[int] = []

    def heartbeat() -> None:
        calls.append(1)
        outcome = outcomes.pop(0)
        if outcome is not None:
            raise outcome

    log = _Log()
    run_advice_worker(
        FileJobQueue(tmp_path / "jobs"),
        FileAdviceCache(tmp_path / "cache"),
        lambda _job: b"{}",
        should_stop=_stop_after(3),
        idle_seconds=0.0,
        heartbeat=heartbeat,
        log=log,
    )
    assert len(calls) == 3
    named = [event for event in log.events if "heartbeat" in str(event["event"])]
    assert named == [
        {
            "event": "advice_worker_heartbeat_failed",
            "error_type": "OSError",
            "detail": "store gone",
        },
        {"event": "advice_worker_heartbeat_recovered"},
    ]


def test_a_round_holding_a_job_keeps_beating_until_the_round_ends(tmp_path: Path) -> None:
    """A solve longer than the bound must not read as a stopped worker."""

    queue = FileJobQueue(tmp_path / "jobs")
    queue.submit(_queued("advice-long-1", waited=0))
    computing = threading.Event()
    beats: list[str] = []

    def heartbeat() -> None:
        beats.append("computing" if computing.is_set() else "round")

    def compute(_job: AdviceJob) -> bytes:
        computing.set()
        deadline = time.monotonic() + 10.0
        while beats.count("computing") < 3 and time.monotonic() < deadline:
            time.sleep(0.005)
        computing.clear()
        return b'{"contract_version":"x"}'

    processed = run_advice_worker(
        queue,
        FileAdviceCache(tmp_path / "cache"),
        compute,
        should_stop=_stop_after(3),
        idle_seconds=0.0,
        max_jobs=1,
        heartbeat=heartbeat,
        pulse_seconds=0.01,
    )
    assert processed == 1
    assert beats[0] == "round"
    assert beats.count("computing") >= 3
    after = len(beats)
    time.sleep(0.1)
    assert len(beats) == after  # the pulse ended with its round


def test_a_worker_names_the_job_it_holds_from_the_start_of_its_solve_to_the_end(
    tmp_path: Path,
) -> None:
    """A solve shorter than a pulse still shows its worker busy, and only while it runs."""

    root = tmp_path / "workers"
    queue = FileJobQueue(tmp_path / "jobs")
    queue.submit(_queued("advice-held-1", waited=0))
    heartbeat = WorkerHeartbeat(root, pid=7, host="box", clock=_at(0))
    seen: list[object] = []

    def compute(_job: AdviceJob) -> bytes:
        seen.append(worker_counts(root, now=NOW))
        seen.append(json.loads(heartbeat.path.read_bytes())["job_id"])
        return b'{"contract_version":"x"}'

    processed = run_advice_worker(
        queue,
        FileAdviceCache(tmp_path / "cache"),
        compute,
        should_stop=_stop_after(3),
        idle_seconds=0.0,
        max_jobs=1,
        heartbeat=heartbeat.beat,
        holding=heartbeat.hold,
        pulse_seconds=60.0,
    )
    assert processed == 1
    assert seen == [WorkerCounts(busy=1, total=1), "advice-held-1"]
    assert json.loads(heartbeat.path.read_bytes())["job_id"] is None
    assert worker_counts(root, now=NOW) == WorkerCounts(busy=0, total=1)


def test_the_worker_process_beats_through_its_loop_and_clears_when_it_stops(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SQUADOPT_REPOSITORY_COMMIT", "c" * 40)
    store = tmp_path / "store"
    store.mkdir()
    backend = build_backend(
        BackendConfig(
            store_root=store,
            site_data_root=tmp_path / "site",
            snapshot_root=tmp_path / "snapshots",
            handoff_root=tmp_path / "handoffs",
        )
    )
    root = backend.config.worker_root
    assert root == store / "workers"
    root.mkdir()
    day_old = time.time() - 2 * 24 * 60 * 60
    for name in ("worker-999999.json", "notes.json"):
        (root / name).write_text("{}", encoding="utf-8")
        os.utime(root / name, (day_old, day_old))
    seen: dict[str, Any] = {}
    name = f"worker-{host_label(socket.gethostname())}-{os.getpid()}.json"

    def loop(
        *_args: object,
        heartbeat: Callable[[], None],
        holding: Callable[[str | None], None],
        **_kwargs: object,
    ) -> int:
        heartbeat()
        seen["names"] = sorted(path.name for path in root.iterdir())
        seen["document"] = json.loads((root / name).read_bytes())
        holding("advice-0123456789abcdef-1")
        heartbeat()
        seen["holding"] = json.loads((root / name).read_bytes())["job_id"]
        return 0

    monkeypatch.setattr(worker_module, "run_advice_worker", loop)
    monkeypatch.setattr(signal, "signal", lambda *_args: None)

    assert worker_module.main([], backend=backend) == 0
    assert seen["names"] == sorted(["notes.json", name])
    assert seen["document"]["pid"] == os.getpid()
    assert seen["document"]["host"] == host_label(socket.gethostname())
    assert seen["document"]["job_id"] is None
    assert seen["holding"] == "advice-0123456789abcdef-1"
    assert sorted(path.name for path in root.iterdir()) == ["notes.json"]


# The API.


def _only_live_heartbeat(config: BackendConfig, *, seconds_ago: float) -> None:
    for path in config.worker_root.glob("worker-*.json"):
        path.unlink()
    WorkerHeartbeat(config.worker_root, pid=31, clock=_at(seconds_ago)).beat()


def _client(deployment: dict[str, Any]) -> tuple[TestClient, Any]:
    config = deployment["config"]
    backend = build_backend(config)
    backend = replace(
        backend,
        liveness=WorkerLiveness(
            config.worker_root, backend.queue, clock=lambda: NOW, recheck_seconds=0.0
        ),
    )
    return TestClient(app_for_backend(backend)), backend


def test_ready_is_six_booleans_and_no_path(deployment: dict[str, Any]) -> None:
    _only_live_heartbeat(deployment["config"], seconds_ago=1)
    client, _backend = _client(deployment)
    response = client.get("/ready")
    assert response.status_code == 200
    assert response.json() == {"ready": True, "checks": dict.fromkeys(CHECKS, True)}
    assert len(response.content) < 256
    assert "/" not in response.text and "\\" not in response.text


def test_ready_answers_503_naming_the_worker_check_when_every_heartbeat_is_stale(
    deployment: dict[str, Any],
) -> None:
    _only_live_heartbeat(deployment["config"], seconds_ago=WORKER_STALE_AFTER_SECONDS + 1)
    client, _backend = _client(deployment)
    response = client.get("/ready")
    assert response.status_code == 503
    assert response.json() == {
        "ready": False,
        "checks": {**dict.fromkeys(CHECKS, True), "worker_heartbeat": False},
    }
    assert "/" not in response.text and "\\" not in response.text


def test_ready_answers_503_naming_the_queue_check_when_a_job_waits_too_long(
    deployment: dict[str, Any],
) -> None:
    _only_live_heartbeat(deployment["config"], seconds_ago=1)
    client, backend = _client(deployment)
    backend.queue.submit(_queued("advice-stuck-1", waited=QUEUED_JOB_LIMIT_SECONDS + 1))
    response = client.get("/ready")
    assert response.status_code == 503
    assert response.json() == {
        "ready": False,
        "checks": {**dict.fromkeys(CHECKS, True), "queue_wait": False},
    }


def test_ready_answers_503_naming_the_worker_check_when_the_heartbeats_cannot_be_listed(
    deployment: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    config = deployment["config"]
    _only_live_heartbeat(config, seconds_ago=1)
    client, _backend = _client(deployment)
    listing = Path.iterdir

    def refuse(self: Path) -> Iterator[Path]:
        if self == config.worker_root:
            raise OSError(errno.EIO, "The heartbeat directory cannot be read")
        return listing(self)

    monkeypatch.setattr(Path, "iterdir", refuse)
    response = client.get("/ready")
    assert response.status_code == 503
    assert response.json() == {
        "ready": False,
        "checks": {**dict.fromkeys(CHECKS, True), "worker_heartbeat": False},
    }
    assert "/" not in response.text and "\\" not in response.text


def test_the_job_view_reads_the_held_look_of_the_deployment(deployment: dict[str, Any]) -> None:
    """Wired by ``build_backend``: the place in line and the worker counts, beside the job."""

    config = deployment["config"]
    for path in config.worker_root.glob("worker-*.json"):
        path.unlink()
    WorkerHeartbeat(config.worker_root, pid=31, host="box").beat()  # now, by the real clock
    backend = build_backend(config)
    client = TestClient(app_for_backend(backend))
    backend.queue.submit(_queued("advice-first-1", waited=20))
    backend.queue.submit(_queued("advice-second-1", waited=10, key="3"))

    view = client.get("/api/v1/advice-jobs/advice-second-1").json()
    assert view["status"] == "queued"
    assert view["queue_position"] == 1
    assert view["progress"] is None
    assert view["workers"] == {"busy": 0, "total": 1}


def test_health_stays_liveness_and_asks_no_dependency(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SQUADOPT_REPOSITORY_COMMIT", "c" * 40)
    store = tmp_path / "store"
    store.mkdir()
    backend = build_backend(
        BackendConfig(
            store_root=store,
            site_data_root=tmp_path / "site",
            snapshot_root=tmp_path / "snapshots",
            handoff_root=tmp_path / "handoffs",
        )
    )
    client = TestClient(app_for_backend(backend))
    assert client.get("/ready").status_code == 503  # nothing published and no worker

    def refuse(_self: WorkerLiveness) -> tuple[bool, bool]:
        raise AssertionError("/health asked a readiness check")

    monkeypatch.setattr(WorkerLiveness, "checks", refuse)
    health = client.get("/health")
    assert health.status_code == 200
    assert health.json() == ApiServiceInfo().to_dict()
