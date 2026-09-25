"""Worker orchestration and compatibility imports for the advice queue.

Queue protocols and ownership errors live in ``queue_contracts``; the recoverable file
adapter lives in ``file_advice_queue``. API, worker and publication remain independent
process responsibilities. A worker computes outside the metadata lock, then the queue
checks attempt ownership before publishing immutable cache bytes and terminal state.
Conflicting bytes remain a determinism defect; lost ownership never mutates a newer job.
A finished answer that cannot get the metadata lock within its budget is written to the
cache alone and its job is left to recovery: contention never becomes a failed job.
"""

from __future__ import annotations

import contextlib
import re
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Final

from squadopt.platform.advice_cache import AdviceCacheError, AdviceCacheRepository
from squadopt.platform.advice_observability import AdviceLog, AdviceMetrics

# Compatibility exports: consumers keep their existing import paths.
from squadopt.platform.file_advice_queue import FileJobQueue as FileJobQueue
from squadopt.platform.jobs_contract import (
    AdviceJob,
    BackendJobsContractError,
    JobError,
)
from squadopt.platform.queue_contracts import (
    DEFAULT_LEASE_SECONDS as DEFAULT_LEASE_SECONDS,
)
from squadopt.platform.queue_contracts import (
    AdviceLeaseLostError as AdviceLeaseLostError,
)
from squadopt.platform.queue_contracts import (
    AdviceQueueError as AdviceQueueError,
)
from squadopt.platform.queue_contracts import (
    AdviceQueueIntegrityError as AdviceQueueIntegrityError,
)
from squadopt.platform.queue_contracts import (
    JobQueue as JobQueue,
)
from squadopt.platform.queue_contracts import (
    QueueLockTimeout,
)

#: How long a finished answer keeps asking for the queue's lock to record its completion.
#: A tenth of the lease. The heartbeat needs the same lock, so it cannot refresh the claim
#: while the lock is busy; the margin keeps it instead. An attempt that starts before the
#: deadline still waits the lock's own 5 s (10 s when the heartbeat holds the in-process
#: lock), so the whole wait stays under 40 s; 31.3 s was measured with the default
#: heartbeat and 36.0 s with one every 0.5 s. A claim last refreshed at most one heartbeat
#: interval (100 s) earlier stays inside the 300 s lease. If recovery walks a claim back
#: first anyway, ``complete`` finds the lease lost and publishes nothing.
DEFAULT_COMPLETE_RETRY_SECONDS: Final = DEFAULT_LEASE_SECONDS / 10.0
_COMPLETE_RETRY_PAUSE_SECONDS: Final = 0.25

_SANITIZE_PATTERNS: Final = (
    re.compile(r"[A-Za-z]:[\\/][^\s'\"]*"),  # windows paths
    re.compile(r"/(?:home|tmp|var|usr|etc)/[^\s'\"]*"),  # unix paths
)


def sanitize_error_message(message: str, *, limit: int = 200) -> str:
    """A failure reason fit for a public record: no host paths, one line, bounded.

    The stored job record travels out through the jobs endpoint, so whatever a worker
    exception carries — file locations, mount points, usernames inside paths — must
    not be persisted verbatim.
    """

    first_line = message.splitlines()[0] if message.strip() else "unspecified failure"
    for pattern in _SANITIZE_PATTERNS:
        first_line = pattern.sub("<path>", first_line)
    trimmed = first_line.strip()[:limit]
    return trimmed or "unspecified failure"


class AdviceComputeRefused(ValueError):
    """The worker will not compute this job, and names a stable reason.

    Distinct from a bug. A bug is unexpected and lands as ``ADVICE_FAILED`` with a
    sanitized message; this is a decision the compute side reached deliberately — the
    capture the job was accepted under is gone, its request cannot be read back, it has
    been retried too often — and the operator (and the member's page) deserve to be told
    which. The code travels with the exception so the worker step stays the only place
    that writes a terminal record.
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _utc_stamp() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _complete_within_budget(
    queue: JobQueue,
    job: AdviceJob,
    *,
    cache: AdviceCacheRepository,
    payload: bytes,
    terminal_at_utc: Callable[[], str],
    budget_seconds: float,
    log: AdviceLog | None,
) -> AdviceJob:
    """Record a finished answer, waiting out a busy queue lock for a bounded time.

    A busy lock is contention, not a failed computation. ``complete`` writes nothing
    before it holds the lock, so asking again is safe. When the budget runs out the answer
    is still written to the cache (write-once and keyed by its whole identity, so it needs
    no metadata lock) and the timeout propagates: the job stays running, recovery walks it
    back after its lease, and the retry is served from the cache instead of solved again.
    """

    deadline = time.monotonic() + budget_seconds
    while True:
        try:
            return queue.complete(job, cache=cache, payload=payload, at_utc=terminal_at_utc())
        except QueueLockTimeout:
            remaining = deadline - time.monotonic()
            if remaining > 0.0:
                time.sleep(min(_COMPLETE_RETRY_PAUSE_SECONDS, remaining))
                continue
            cache.put(job.cache_key, payload)
            if log is not None:
                log.event(
                    "advice_job_completion_deferred",
                    job_id=job.job_id,
                    cache_key=job.cache_key,
                    attempt=job.attempt,
                )
            raise


def _run_advice_worker_once(
    queue: JobQueue,
    cache: AdviceCacheRepository,
    compute: Callable[[AdviceJob], bytes],
    *,
    at_utc: str | None = None,
    claim_at_utc: Callable[[], str] | None = None,
    terminal_at_utc: Callable[[], str] = _utc_stamp,
    heartbeat_seconds: float | None = None,
    complete_retry_seconds: float = DEFAULT_COMPLETE_RETRY_SECONDS,
    metrics: AdviceMetrics | None = None,
    log: AdviceLog | None = None,
    job_log_fields: dict[str, object] | None = None,
) -> AdviceJob | None:
    """Claim one job, compute it, cache the answer, record the terminal state.

    ``compute`` is injected — the worker knows how to run a job, not what advice is,
    and the api process that shares this module's import graph never receives a
    compute callable at all, which is how "the api imports no solver" stays a property
    of the composition rather than a hope. Returns the terminal record, or ``None``
    when the queue is empty.

    ``at_utc`` supplies a fixed claim instant for replay/tests. Live callers instead
    pass ``claim_at_utc``, sampled by the queue after acquiring its transition lock.
    ``terminal_at_utc`` is read after computation, so its outcome is not backdated.

    ``heartbeat_seconds`` refreshes the claim while ``compute`` runs. It belongs here
    because this function owns the claim's whole lifetime — from the owned claim to
    the terminal record — and nothing else can see when the computation starts and stops.
    One member's plan is not one solve: a rival strategy runs the control plan, the banded
    plan, and the payload's own plan, so the wall time that matters is a multiple of the
    single-solve measurement the lease was compared against. Without a heartbeat a
    long-running claim goes stale under a live worker and a second worker recovers work
    that was never abandoned; two solves then race for one immutable key.

    ``complete_retry_seconds`` bounds how long a finished answer waits for a busy queue
    lock (``_complete_within_budget``). A lock that stays busy raises ``QueueLockTimeout``
    to the caller with the answer already cached; it is never stored as a failure. A retried
    attempt whose key the cache already holds takes that answer rather than computing it
    again. A first attempt still computes and compares, which is how a determinism defect
    under an existing key is caught.
    """

    from time import perf_counter

    job = queue.claim(at_utc=at_utc, clock=claim_at_utc)
    if job is None:
        return None
    if job_log_fields is not None:
        job_log_fields.clear()
    if metrics is not None:
        from squadopt.platform.jobs_contract import _instant

        wait = (_instant(job.updated_at_utc) - _instant(job.created_at_utc)).total_seconds()
        metrics.job_wait_seconds(max(0.0, wait))
    if log is not None:
        log.event(
            "advice_job_claimed",
            job_id=job.job_id,
            cache_key=job.cache_key,
            request_fingerprint=job.request_fingerprint,
            attempt=job.attempt,
        )
    started = perf_counter()
    stop_beating = threading.Event()
    beating: threading.Thread | None = None
    if heartbeat_seconds is not None and heartbeat_seconds > 0.0:

        def beat() -> None:
            # Refuse to outlive the computation: the wait is the sleep, so a finished job
            # stops the thread immediately rather than after one more interval.
            while not stop_beating.wait(heartbeat_seconds):
                with contextlib.suppress(Exception):
                    queue.heartbeat(job.job_id, attempt=job.attempt)

        beating = threading.Thread(target=beat, name=f"advice-heartbeat-{job.job_id}", daemon=True)
        beating.start()
    try:
        # An earlier attempt of this job may have finished its answer and lost only the
        # record (a lock that stayed busy, or a crash between the two writes).
        held = cache.get(job.cache_key) if job.attempt > 1 else None
        if held is not None and log is not None:
            log.event("advice_job_answer_reused", job_id=job.job_id, attempt=job.attempt)
        payload = held if held is not None else compute(job)
        if not isinstance(payload, bytes) or not payload:
            raise AdviceQueueError("compute must return non-empty bytes.")
        completed = _complete_within_budget(
            queue,
            job,
            cache=cache,
            payload=payload,
            terminal_at_utc=terminal_at_utc,
            budget_seconds=complete_retry_seconds,
            log=log,
        )
    except AdviceCacheError as error:
        # Different bytes under a complete key: a determinism defect, recorded as
        # exactly that — never retried, never papered over.
        failed = job.transition(
            "failed",
            at_utc=terminal_at_utc(),
            error=JobError(code="DETERMINISM_DEFECT", message=sanitize_error_message(str(error))),
        )
        queue.store(failed)
        if metrics is not None:
            metrics.solve_seconds(perf_counter() - started)
            metrics.increment("advice_jobs_total", outcome="determinism_defect")
        if log is not None:
            log.event(
                "advice_job_failed",
                job_id=job.job_id,
                code="DETERMINISM_DEFECT",
                **(job_log_fields or {}),
            )
        return failed
    except (BackendJobsContractError, AdviceLeaseLostError, QueueLockTimeout):
        # A busy lock is contention, not a computation that failed: the job stays open
        # for recovery and the caller backs off.
        raise
    except AdviceComputeRefused as refusal:
        failed = job.transition(
            "failed",
            at_utc=terminal_at_utc(),
            error=JobError(code=refusal.code, message=sanitize_error_message(str(refusal))),
        )
        queue.store(failed)
        if metrics is not None:
            metrics.solve_seconds(perf_counter() - started)
            metrics.increment("advice_jobs_total", outcome="refused")
        if log is not None:
            # The cause stays on the operator's side: the job record above is what the
            # api serves, and it carries the code and a sanitized sentence only.
            log.event(
                "advice_job_refused",
                job_id=job.job_id,
                code=refusal.code,
                detail=str(refusal.__cause__) if refusal.__cause__ is not None else None,
                **(job_log_fields or {}),
            )
        return failed
    except Exception as error:
        failed = job.transition(
            "failed",
            at_utc=terminal_at_utc(),
            error=JobError(
                code="ADVICE_FAILED",
                message=sanitize_error_message(str(error) or type(error).__name__),
            ),
        )
        queue.store(failed)
        if metrics is not None:
            # Solve latency includes failures: omitting them biases the distribution
            # toward the happy path, exactly when the operator most needs the truth.
            metrics.solve_seconds(perf_counter() - started)
            metrics.increment("advice_jobs_total", outcome="failed")
        if log is not None:
            log.event(
                "advice_job_failed",
                job_id=job.job_id,
                code="ADVICE_FAILED",
                error_type=type(error).__name__,
                detail=str(error) or None,
                **(job_log_fields or {}),
            )
        return failed
    finally:
        # Every path out of the computation, including the re-raise: a heartbeat that
        # outlived its job would keep a finished claim looking alive to recovery.
        stop_beating.set()
        if beating is not None:
            beating.join(timeout=1.0)
    if metrics is not None:
        metrics.solve_seconds(perf_counter() - started)
        metrics.increment("advice_jobs_total", outcome="completed")
        # The FEASIBLE share is a product metric: a budget regression shows up here.
        # The completed payload is the served advice document, whose solver_status
        # field the read contract requires when present.
        import json as _json

        with contextlib.suppress(Exception):
            document = _json.loads(payload)
            status = document.get("payload", {}).get("solver_status")
            if isinstance(status, str) and status:
                metrics.solver_status(status)
    if log is not None:
        log.event(
            "advice_job_completed",
            job_id=job.job_id,
            cache_key=job.cache_key,
            wall_seconds=round(perf_counter() - started, 3),
            **(job_log_fields or {}),
        )
    return completed


def run_advice_worker_once(
    queue: JobQueue,
    cache: AdviceCacheRepository,
    compute: Callable[[AdviceJob], bytes],
    *,
    at_utc: str | None = None,
    claim_at_utc: Callable[[], str] | None = None,
    terminal_at_utc: Callable[[], str] = _utc_stamp,
    heartbeat_seconds: float | None = None,
    complete_retry_seconds: float = DEFAULT_COMPLETE_RETRY_SECONDS,
    metrics: AdviceMetrics | None = None,
    log: AdviceLog | None = None,
    job_log_fields: dict[str, object] | None = None,
) -> AdviceJob | None:
    """Run one attempt; a recovered attempt may no longer publish any outcome."""
    try:
        return _run_advice_worker_once(
            queue,
            cache,
            compute,
            at_utc=at_utc,
            claim_at_utc=claim_at_utc,
            terminal_at_utc=terminal_at_utc,
            heartbeat_seconds=heartbeat_seconds,
            complete_retry_seconds=complete_retry_seconds,
            metrics=metrics,
            log=log,
            job_log_fields=job_log_fields,
        )
    except AdviceLeaseLostError:
        if metrics is not None:
            metrics.increment("advice_jobs_total", outcome="lease_lost")
        if log is not None:
            log.event("advice_job_lease_lost")
        return None
