"""The write side of on-demand advice: one POST becomes a job record, nothing more.

The api process's whole write privilege is creating a job record. It computes nothing,
touches no ledger, and writes no advice — the worker does that. What this module owns
is the discipline around that one write:

- **Three identities, kept apart.** The ``Idempotency-Key`` is the client's retry
  intent; the ``request_fingerprint`` is the normalized request (built by
  ``backend_api_v1``'s own ``league.advise`` command, so the API contract and the
  queue agree about what "the same request" means); the cache key is the answer's
  address. Reusing one idempotency key for a *different* request is a conflict,
  answered as one; a new key for the same request is a distinct attempt that
  deduplicates onto the same open job.
- **Every "which answer is this" decision goes through the cache key.** The
  fingerprint deliberately omits the handoff, the repository commit and the
  configuration, so it cannot tell two contexts apart — it names a request, not a
  result. Deduplication, the job's id, its attempt count and idempotency replay are
  therefore all addressed by ``cache_key``; the fingerprint is left to do the one
  thing it is for, which is saying whether an idempotency key was reused for
  something else.
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

from squadopt.platform.advice_job_spec import AdviceJobSpec, AdviceJobSpecStore
from squadopt.platform.advice_queue import JobQueue
from squadopt.platform.advice_read import AdviceBackendNotReadyError, AdviceReadStore
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
        specs: AdviceJobSpecStore | None = None,
        store_ready: Callable[[], bool] | None = None,
    ) -> None:
        self._reader = reader
        self._queue = queue
        self._limiter = rate_limiter
        self._specs = specs
        self._store_ready = store_ready

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

        if self._store_ready is not None and not self._store_ready():
            # Refuse before validating: a queue write onto a store that has failed its
            # capability checks either errors, or lands on storage nothing will read
            # again. Both are worse than telling the caller the backend is not ready.
            raise AdviceBackendNotReadyError(
                "The advice store is not available; the backend cannot accept work."
            )
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
            #
            # "Different" is decided by the **cache key** as well as the fingerprint. The
            # fingerprint names the client's fields and the capture; it says nothing about
            # the handoff, the repository commit or the configuration. So a key replayed
            # after ops republished a handoff matched here, and the caller was handed the
            # older job with a 202 — it would poll that job to completion and then be told
            # its own answer had never been computed, because the completed answer lives at
            # an address this request does not read.
            for job in history:
                if job.idempotency_key == idempotency_key:
                    if job.request_fingerprint != fingerprint or job.cache_key != cache_key:
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

        # Addressed by the answer, not by the request. Two valid contexts — a redeploy is
        # enough — share a fingerprint, so counting and naming by it gave both the same
        # job id: the second submission reserved its own index, reached ``submit``, and
        # collided on a name that is create-once. One caller got 202 and the other a 500.
        attempt_ordinal = sum(1 for job in history if job.cache_key == cache_key)
        record = AdviceJob(
            job_id=f"advice-{cache_key[:16]}-{attempt_ordinal + 1}",
            status="queued",
            request_fingerprint=fingerprint,
            cache_key=cache_key,
            created_at_utc=at_utc,
            updated_at_utc=at_utc,
            idempotency_key=command.idempotency_key,
        )
        if self._specs is not None:
            # Before the job exists, never after: a worker may claim the instant the
            # record lands, and a claimed job whose request cannot be read is a job
            # nobody can answer. The rival is normalized exactly as the cache key
            # normalizes it, so requests that share an address share a meaning.
            self._specs.put(
                cache_key,
                AdviceJobSpec(
                    league_id=int(league_id),
                    entry_id=int(entry_id),
                    strategy=strategy,
                    window=int(window),
                    context=context,
                    rival_entry_id=(
                        rival_entry_id if self._reader.strategy_uses_rival(strategy) else None
                    ),
                ),
            )
        # Completion publishes cache bytes and removes the open reservation under the
        # same lock as this final cache check and enqueue decision. An earlier miss must
        # not create a second job after another worker has already answered it.
        winner = self._queue.submit_unless_cached(record, read_cached=self._reader.cached)
        if isinstance(winner, bytes):
            return SubmitOutcome(kind="hit", payload=winner)
        return SubmitOutcome(kind="job", job=winner)
