"""Each advice worker says it is alive, and readiness asks whether any worker is.

A worker whose loop has stopped cannot report that itself, and the api kept answering 202
to jobs nobody would claim while ``/ready`` said nothing about workers (audit M13). So
every worker keeps a small document under the store's ``workers/`` directory, rewritten on
every round of its loop with its process id and the time, and readiness counts a worker as
alive while that document is recent. The queue and cache documents are not touched: a
heartbeat is a statement about now, and they are records.

Both bounds are stated here, so the worker, the endpoint and the runbook cannot drift.

``WORKER_STALE_AFTER_SECONDS`` is 60 idle waits: 120 s at the 2 s every deployment runs
with. A live loop writes at the top of every round. An idle round is one idle wait plus
its queue transactions, and each of those gives up on the lock after 5 s. A round that
raised waits out a backoff capped at 60 s (30 idle waits). A round that holds a job also
writes every ``PULSE_SECONDS`` from the first compute call to the end of the round, so a
long solve and a slow completion do not read as silence. The longest gap a live worker
leaves is therefore the 60 s backoff cap plus one round's lock waits. A worker silent for
twice that cap has stopped.

``QUEUED_JOB_LIMIT_SECONDS`` is the 300 s claim lease. An idle worker claims a queued job
within one idle wait. A job waits longer only while every worker is busy, and the longest
job in the live worker logs to 2026-09-25 took 245.5 s (31 completed jobs). A job still
queued after a whole lease is not being picked up. The wait is counted from the moment the
job last entered the queue (``updated_at_utc`` of a queued job): a job walked back by
recovery starts waiting again then, and the question is whether the queue moves now.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import secrets
import threading
import time
from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

from squadopt.data.atomic import replace_retrying
from squadopt.platform.jobs_contract import AdviceJob
from squadopt.platform.queue_contracts import DEFAULT_LEASE_SECONDS, JobQueue

__all__ = [
    "HEARTBEAT_CONTRACT_VERSION",
    "IDLE_WAIT_SECONDS",
    "PRUNE_AFTER_SECONDS",
    "PULSE_SECONDS",
    "QUEUED_JOB_LIMIT_SECONDS",
    "READINESS_RECHECK_SECONDS",
    "WORKER_DIRECTORY",
    "WORKER_STALE_AFTER_SECONDS",
    "WorkerHeartbeat",
    "WorkerLiveness",
    "freshest_heartbeat_age",
    "oldest_queued_wait",
    "prune_stale_heartbeats",
]

HEARTBEAT_CONTRACT_VERSION: Final = "advice_worker_heartbeat_v1"
WORKER_DIRECTORY: Final = "workers"
"""The heartbeats' directory under the store root, beside ``jobs``, ``cache`` and ``specs``."""

IDLE_WAIT_SECONDS: Final = 2.0
"""The wait an idle worker takes between rounds (``advice_worker.DEFAULT_IDLE_SECONDS``)."""
WORKER_STALE_AFTER_SECONDS: Final = 60 * IDLE_WAIT_SECONDS
PULSE_SECONDS: Final = 15 * IDLE_WAIT_SECONDS
QUEUED_JOB_LIMIT_SECONDS: Final = DEFAULT_LEASE_SECONDS
READINESS_RECHECK_SECONDS: Final = 5.0
"""How long one look at the heartbeats and the queue answers ``/ready``. The endpoint is
public, and the queue scan holds the queue's lock, so a burst of probes costs one scan per
five seconds rather than one per request. Five seconds is noise against both bounds."""
PRUNE_AFTER_SECONDS: Final = 24 * 60 * 60.0
"""A document nobody has rewritten for a day belongs to a worker that is gone. A launcher
that stops a worker by ending its process leaves the document behind, so each worker clears
these out when it starts."""

_HEARTBEAT_NAME: Final = re.compile(r"^worker-([0-9]{1,10})\.json$")
_STAGING_NAME: Final = re.compile(r"^\.worker-[0-9]{1,10}\.json\.[0-9a-f]{16}\.tmp$")


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _stamp(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _instant(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("A heartbeat time must state UTC.")
    return parsed


class WorkerHeartbeat:
    """One worker's document: ``workers/worker-<pid>.json``, replaced whole on each beat."""

    def __init__(
        self,
        root: Path,
        *,
        pid: int | None = None,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._root = root
        self._pid = os.getpid() if pid is None else pid
        self._clock = clock

    @property
    def path(self) -> Path:
        return self._root / f"worker-{self._pid}.json"

    def beat(self) -> None:
        """Write this worker's pid and the time, so a reader sees the old document or the new.

        The bytes are staged in a sibling and moved into place by the repository's one
        publishing rename, which rides out a reader's handle on Windows. They are not
        fsynced: a heartbeat lost to a power cut is replaced by the next round, and one a
        reader cannot parse counts as absent, which is what a lost worker looks like anyway.

        Only the ``workers`` directory itself is created. The store root must already
        exist, exactly as the store probe requires, so a forgotten volume is never
        papered over by a directory made on the container's own disk.
        """

        document = {
            "at_utc": _stamp(self._clock()),
            "contract_version": HEARTBEAT_CONTRACT_VERSION,
            "pid": self._pid,
        }
        self._root.mkdir(exist_ok=True)
        staging = self._root / f".{self.path.name}.{secrets.token_hex(8)}.tmp"
        try:
            staging.write_bytes(json.dumps(document, sort_keys=True).encode("utf-8"))
            replace_retrying(staging, self.path)
        finally:
            with contextlib.suppress(OSError):
                staging.unlink(missing_ok=True)

    def clear(self) -> None:
        """Remove this worker's own document when it stops, so it stops counting at once."""

        with contextlib.suppress(FileNotFoundError):
            self.path.unlink()


def prune_stale_heartbeats(
    root: Path,
    *,
    older_than_seconds: float = PRUNE_AFTER_SECONDS,
    clock: Callable[[], float] = time.time,
) -> int:
    """Remove heartbeat documents and staging files nobody has touched for a day.

    Only names this module writes are considered, and only by their modification time: a
    live worker rewrites its own document every round, so it can never be this old.
    Returns how many files were removed.
    """

    if not root.is_dir():
        return 0
    removed = 0
    cutoff = clock() - older_than_seconds
    for path in root.iterdir():
        if not (_HEARTBEAT_NAME.match(path.name) or _STAGING_NAME.match(path.name)):
            continue
        with contextlib.suppress(OSError):
            if path.stat().st_mtime < cutoff:
                path.unlink()
                removed += 1
    return removed


def freshest_heartbeat_age(root: Path, *, now: datetime) -> float | None:
    """Seconds since the most recent readable heartbeat, or ``None`` when there is none.

    An unreadable or malformed document is skipped: it is not evidence of a live worker.
    The age is taken as a magnitude. A document stamped ahead of ``now`` means the clock
    moved back after it was written. A live worker rewrites its document on its next
    round, so a document that stays far ahead belongs to a worker that stopped before the
    clock moved, and must not read as fresh.
    """

    if not root.is_dir():
        return None
    ages: list[float] = []
    for path in root.iterdir():
        if not _HEARTBEAT_NAME.match(path.name):
            continue
        try:
            document = json.loads(path.read_bytes())
            if (
                not isinstance(document, dict)
                or document.get("contract_version") != HEARTBEAT_CONTRACT_VERSION
                or isinstance(document.get("pid"), bool)
                or not isinstance(document.get("pid"), int)
                or not isinstance(document.get("at_utc"), str)
            ):
                continue
            ages.append(abs((now - _instant(document["at_utc"])).total_seconds()))
        except (OSError, ValueError, TypeError):
            continue
    return min(ages) if ages else None


def oldest_queued_wait(jobs: Iterable[AdviceJob], *, now: datetime) -> float | None:
    """Seconds the longest-waiting queued job has been in the queue, or ``None`` if none is.

    A job stamped ahead of ``now`` has not waited at all.
    """

    waits = [
        max(0.0, (now - _instant(job.updated_at_utc)).total_seconds())
        for job in jobs
        if job.status == "queued"
    ]
    return max(waits) if waits else None


class WorkerLiveness:
    """Whether a worker is alive and whether the queue moves, as two readiness checks."""

    def __init__(
        self,
        heartbeat_root: Path,
        queue: JobQueue,
        *,
        clock: Callable[[], datetime] = _utc_now,
        monotonic: Callable[[], float] = time.monotonic,
        recheck_seconds: float = READINESS_RECHECK_SECONDS,
        stale_after_seconds: float = WORKER_STALE_AFTER_SECONDS,
        queued_limit_seconds: float = QUEUED_JOB_LIMIT_SECONDS,
    ) -> None:
        self._root = heartbeat_root
        self._queue = queue
        self._clock = clock
        self._monotonic = monotonic
        self._recheck = recheck_seconds
        self._stale_after = stale_after_seconds
        self._queued_limit = queued_limit_seconds
        self._lock = threading.Lock()
        self._held: tuple[bool, bool] | None = None
        self._held_at = 0.0

    def checks(self) -> tuple[bool, bool]:
        """``(worker_heartbeat, queue_wait)``, held for ``recheck_seconds``.

        ``worker_heartbeat`` holds when some worker's document is at most
        ``stale_after_seconds`` old. ``queue_wait`` holds when no queued job has waited
        longer than ``queued_limit_seconds``; a queue that cannot be read (its lock stayed
        busy for the whole bounded wait, or a record is damaged) does not hold, because a
        check that could not be made has not passed.
        """

        with self._lock:
            if self._held is not None and self._monotonic() - self._held_at < self._recheck:
                return self._held
            now = self._clock()
            age = freshest_heartbeat_age(self._root, now=now)
            worker_alive = age is not None and age <= self._stale_after
            try:
                wait = oldest_queued_wait(self._queue.jobs(), now=now)
            except (OSError, ValueError):
                # QueueLockTimeout is an OSError; AdviceQueueError is a ValueError.
                queue_moving = False
            else:
                queue_moving = wait is None or wait <= self._queued_limit
            self._held = (worker_alive, queue_moving)
            self._held_at = self._monotonic()
            return self._held
