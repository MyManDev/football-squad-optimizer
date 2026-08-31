"""The write side of on-demand advice: one POST becomes a job record, nothing more.

The api process's whole write privilege is creating a job record. It computes nothing,
touches no ledger, and writes no advice — the worker does that. What this module owns
is the discipline around that one write:

- **Three identities, kept apart.** The ``Idempotency-Key`` is the client's retry
  intent; the ``request_fingerprint`` is the normalized request (built by
  ``backend_api_v1``'s own ``league.advise`` command, so the API contract and the
  queue agree about what "the same request" means); the cache key is the answer's
  address. Reusing one idempotency key for a *different* fingerprint is a conflict,
  answered as one; a new key for the same fingerprint is a distinct attempt that
  deduplicates onto the same open job.
- **A hit is a hit.** If the cache already holds the answer, the POST returns it and
  no job exists — the queue is for work, not for bookkeeping about work already done.
- **Rate limits are honest refusals.** Two buckets guard the POST — one per client
  address, one per (capture, entry) — because a solve costs seconds of CPU and a
  browser retry loop must not become a denial of service on the league's own worker.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Final, Protocol

from squadopt.platform.advice_queue import JobQueue
from squadopt.platform.advice_read import AdviceReadStore
from squadopt.platform.api_contract import ApiCommandRequest
from squadopt.platform.jobs_contract import AdviceJob

_DEFAULT_IDEMPOTENCY_PREFIX: Final = "auto"


class IdempotencyConflictError(ValueError):
    """One idempotency key was reused for a different normalized request."""


class RateLimitedError(ValueError):
    """The client or the entry has exhausted its request budget for the window."""


class RateLimiter(Protocol):
    """Whether one more request in ``bucket`` is allowed right now."""

    def allow(self, bucket: str) -> bool: ...


class FixedWindowRateLimiter:
    """A small in-memory fixed window: enough for one api process, honestly named.

    Replicas each carry their own window, so the effective limit scales with the
    replica count; the plan's scaling order says to read the cache hit rate before
    adding replicas, and this limiter is part of why that stays true.
    """

    def __init__(
        self, limit: int, window_seconds: float, clock: Callable[[], float] = time.monotonic
    ) -> None:
        if limit < 1:
            raise ValueError("limit must be at least 1.")
        self._limit = limit
        self._window = float(window_seconds)
        self._clock = clock
        self._counts: dict[str, tuple[float, int]] = {}

    def allow(self, bucket: str) -> bool:
        now = self._clock()
        started, count = self._counts.get(bucket, (now, 0))
        if now - started >= self._window:
            started, count = now, 0
        if count >= self._limit:
            self._counts[bucket] = (started, count)
            return False
        self._counts[bucket] = (started, count + 1)
        return True


@dataclass(frozen=True, slots=True)
class SubmitOutcome:
    """What one POST produced: the cached answer, or the job to poll."""

    kind: str
    """``hit`` | ``job``"""
    payload: bytes | None = None
    job: AdviceJob | None = None


class AdviceSubmitService:
    """Turn a validated request into a cache hit or exactly one open job."""

    def __init__(
        self,
        reader: AdviceReadStore,
        queue: JobQueue,
        *,
        rate_limiter: RateLimiter | None = None,
    ) -> None:
        self._reader = reader
        self._queue = queue
        self._limiter = rate_limiter

    def job(self, job_id: str) -> AdviceJob | None:
        return self._queue.load(job_id)

    def public_job_view(self, job_id: str) -> dict[str, object] | None:
        """The job as the world may see it: progress and a coded reason, nothing else.

        The stored record carries the client's idempotency key and the worker's
        failure text; neither belongs on a public endpoint, so the view names the
        fields it serves instead of serving the record.
        """

        record = self._queue.load(job_id)
        if record is None:
            return None
        return {
            "contract_version": "advice_job_view_v1",
            "job_id": record.job_id,
            "status": record.status,
            "created_at_utc": record.created_at_utc,
            "updated_at_utc": record.updated_at_utc,
            "attempt": record.attempt,
            "error_code": record.error.code if record.error is not None else None,
        }

    def submit(
        self,
        *,
        league_id: int,
        entry_id: int,
        strategy: str,
        window: int,
        rival_entry_id: int | None,
        idempotency_key: str | None,
        client_bucket: str,
        at_utc: str,
    ) -> SubmitOutcome:
        """Validate, rate-limit, dedupe, and enqueue — in that order.

        Validation runs before the rate limit so a malformed request never spends a
        token, and the rate limit runs before the cache read so a hammering client is
        refused cheaply. Deduplication scans open jobs by fingerprint: at most one
        open job exists per normalized request, however many keys or clients ask.
        """

        cache_key, context = self._reader.resolve_key(
            league_id=league_id,
            entry_id=entry_id,
            strategy=strategy,
            window=window,
            rival_entry_id=rival_entry_id,
        )
        if self._limiter is not None:
            entry_bucket = f"entry:{context.capture_snapshot_id}:{entry_id}"
            if not self._limiter.allow(f"ip:{client_bucket}") or not self._limiter.allow(
                entry_bucket
            ):
                raise RateLimitedError("Too many advice requests; try again shortly.")
        cached = self._reader.cached(cache_key)
        if cached is not None:
            return SubmitOutcome(kind="hit", payload=cached)

        command = ApiCommandRequest(
            operation="league.advise",
            idempotency_key=idempotency_key or f"{_DEFAULT_IDEMPOTENCY_PREFIX}:{cache_key[:32]}",
            season=context.season,
            gameweek=context.gameweek,
            league_id=int(league_id),
            entry_id=int(entry_id),
            strategy=strategy,
            window=int(window),
            rival_entry_id=rival_entry_id,
            # Server-resolved: the same client fields on a newer capture become a
            # different fingerprint, so dedup cannot serve stale work (review, #288).
            capture_snapshot_id=context.capture_snapshot_id,
        )
        fingerprint = command.request_fingerprint

        history = self._queue.jobs()
        if idempotency_key is not None:
            # Idempotency history survives terminal state: a key reused for a
            # different request is a conflict whether or not the first job finished.
            for job in history:
                if job.idempotency_key == idempotency_key:
                    if job.request_fingerprint != fingerprint:
                        raise IdempotencyConflictError(
                            "This Idempotency-Key was already used for a different request."
                        )
                    if not job.is_terminal:
                        return SubmitOutcome(kind="job", job=job)
                    # Terminal replay of the same request: the cache answers when it
                    # can; a failed job means the same key may honestly try again.
                    replay = self._reader.cached(cache_key)
                    if replay is not None:
                        return SubmitOutcome(kind="hit", payload=replay)
                    break

        attempt_ordinal = sum(1 for job in history if job.request_fingerprint == fingerprint)
        record = AdviceJob(
            job_id=f"advice-{fingerprint[:16]}-{attempt_ordinal + 1}",
            status="queued",
            request_fingerprint=fingerprint,
            cache_key=cache_key,
            created_at_utc=at_utc,
            updated_at_utc=at_utc,
            idempotency_key=command.idempotency_key,
        )
        # At-most-one open job is the queue's atomic guarantee, not a scan's promise:
        # two api processes racing here converge on one winner.
        winner, _created = self._queue.submit_unique(record)
        return SubmitOutcome(kind="job", job=winner)
