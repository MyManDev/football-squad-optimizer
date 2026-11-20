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
  The budget is for work: a request the cache already answers costs one small read and
  spends no token, so opening a computed plan again never uses up a member's asks.
  The two buckets are charged at different moments because they protect different
  things. The address bucket is the client's own, spent on every miss it sends. The
  entry bucket is shared by everyone who asks about that member, so it is spent only
  when a new job is admitted: a request that joins an open job, or that its own address
  may not open, starts no work, and charging it let one client use up a named member's
  budget for everyone else.
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
import math
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Final, Protocol

from squadopt.contracts.llmopt_run import RunReference as RunReference
from squadopt.contracts.preference_bundle import BUNDLE_SWITCH, PreferenceBundle
from squadopt.contracts.preferences import NO_PREFERENCES, DecisionPreferences
from squadopt.platform.advice_job_spec import AdviceJobSpec, AdviceJobSpecStore
from squadopt.platform.advice_queue import JobQueue
from squadopt.platform.advice_read import (
    AdviceBackendNotReadyError,
    AdviceInputsNotPreparedError,
    AdviceReadStore,
    AdviceRequestContext,
    ResolvedAdviceRequest,
)
from squadopt.platform.advice_runs import FileRunStore, RunTransaction
from squadopt.platform.advice_runs import RunAdmissionError as RunAdmissionError
from squadopt.platform.api_contract import (
    ApiCommandRequest,
    BackendApiContractError,
    validate_idempotency_key,
)
from squadopt.platform.backend.advice_repairs import (
    current_repair_answer,
    replays_witness,
    same_repair_scope,
    single_rule_edit,
)
from squadopt.platform.jobs_contract import AdviceJob
from squadopt.platform.queue_contracts import IdempotencyConflictError as IdempotencyConflictError
from squadopt.platform.queue_contracts import JobProgress
from squadopt.platform.worker_heartbeat import LivenessLook

_DEFAULT_IDEMPOTENCY_PREFIX: Final = "auto"


class RateLimitedError(ValueError):
    """The client or the entry has exhausted its request budget for the window.

    ``retry_after_seconds`` is what the refusal tells the client to wait: the limiter's
    own window, after which a fixed window has certainly started again.
    """

    def __init__(self, message: str, *, retry_after_seconds: int = 60) -> None:
        super().__init__(message)
        self.retry_after_seconds = max(1, int(retry_after_seconds))


class OpenJobLimitedError(ValueError):
    """This address already owns the allowed queued and running work."""


class DeadlinePassedError(ValueError):
    """The resolved capture's gameweek no longer accepts new work."""


class MalformedIdempotencyKeyError(ValueError):
    """The ``Idempotency-Key`` header is not one the contract accepts."""


class RateLimiter(Protocol):
    """A request budget per bucket: ask whether one is left, and spend one."""

    def allow(self, bucket: str) -> bool:
        """Spend one request in ``bucket`` if one is left; whether it was spent."""
        ...

    def has_room(self, bucket: str) -> bool:
        """Whether ``allow`` would spend one now, spending nothing."""
        ...


_IPV6_CLIENT_PREFIX: Final = 64


def client_address_bucket(host: str) -> str:
    """The bucket one client address is counted in: IPv4 by address, IPv6 by its /64.

    One IPv6 subscriber is normally handed a whole /64, and every address in it is theirs
    to use, so counting each address apart gave one client as many budgets and open-job
    slots as it cared to pick addresses. An IPv4 address written in IPv6 form is the IPv4
    address. Anything that is not an address (a test client's name, ``unknown``) is its
    own bucket, as before.
    """

    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return host
    if isinstance(address, ipaddress.IPv4Address):
        return str(address)
    if address.ipv4_mapped is not None:
        return str(address.ipv4_mapped)
    shift = 128 - _IPV6_CLIENT_PREFIX
    network = ipaddress.IPv6Network(((int(address) >> shift) << shift, _IPV6_CLIENT_PREFIX))
    return str(network)


class FixedWindowRateLimiter:
    """A small in-memory fixed window: enough for one api process, honestly named.

    Replicas each carry their own window, so the effective limit scales with the
    replica count; the plan's scaling order says to read the cache hit rate before
    adding replicas, and this limiter is part of why that stays true.

    A bucket whose window has ended counts exactly like one that was never seen, so it is
    dropped. The sweep runs at most once a window, which keeps the table to the buckets
    used in about the last two windows however many addresses and entries have asked.
    """

    def __init__(
        self, limit: int, window_seconds: float, clock: Callable[[], float] = time.monotonic
    ) -> None:
        if limit < 1:
            raise ValueError("limit must be at least 1.")
        self._limit = limit
        self._window = float(window_seconds)
        #: Read by the submit service for ``Retry-After``; not part of the protocol.
        self.window_seconds = self._window
        self._clock = clock
        self._counts: dict[str, tuple[float, int]] = {}
        self._swept_at = clock()
        # The api runs submissions in its thread pool, so two requests can count one
        # bucket at once; without the lock both read the same count and one is lost.
        self._lock = threading.Lock()

    def _current(self, bucket: str, now: float) -> tuple[float, int]:
        """The bucket's window start and count at ``now``; the caller holds the lock."""
        if now - self._swept_at >= self._window:
            self._counts = {
                name: held for name, held in self._counts.items() if now - held[0] < self._window
            }
            self._swept_at = now
        started, count = self._counts.get(bucket, (now, 0))
        if now - started >= self._window:
            return now, 0
        return started, count

    def has_room(self, bucket: str) -> bool:
        with self._lock:
            _started, count = self._current(bucket, self._clock())
            return count < self._limit

    def allow(self, bucket: str) -> bool:
        with self._lock:
            now = self._clock()
            started, count = self._current(bucket, now)
            if count >= self._limit:
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
    """Turn a request into a cache hit or job, with ownership capped per API process."""

    def __init__(
        self,
        reader: AdviceReadStore,
        queue: JobQueue,
        *,
        rate_limiter: RateLimiter | None = None,
        specs: AdviceJobSpecStore | None = None,
        store_ready: Callable[[], bool] | None = None,
        max_open_jobs_per_client: int = 4,
        deadline_for: Callable[[AdviceRequestContext], str] | None = None,
        job_look: Callable[[], LivenessLook] | None = None,
        job_progress: Callable[[AdviceJob], JobProgress | None] | None = None,
        prepare_inputs: Callable[[AdviceRequestContext, int], None] | None = None,
        max_open_jobs: int | None = None,
        runs: FileRunStore | None = None,
    ) -> None:
        if max_open_jobs_per_client < 1:
            raise ValueError("max_open_jobs_per_client must be at least 1.")
        if max_open_jobs is not None and max_open_jobs < 1:
            raise ValueError("max_open_jobs must be at least 1.")
        self._reader = reader
        self._queue = queue
        self._limiter = rate_limiter
        self._specs = specs
        self._store_ready = store_ready
        self._max_open_jobs_per_client = max_open_jobs_per_client
        self._deadline_for = deadline_for
        self._job_look = job_look
        self._job_progress = job_progress
        self._prepare_inputs = prepare_inputs
        self._max_open_jobs = max_open_jobs
        self._runs = runs
        # Only the admission callback accesses this map, under the queue transaction.
        # Addresses never enter queue/spec documents; process restart forgets ownership.
        self._client_jobs: dict[str, str] = {}
        # Serializes the idempotency check with the enqueue it decides; see ``submit``.
        self._admission = threading.Lock()

    def job(self, job_id: str) -> AdviceJob | None:
        return self._queue.load(job_id)

    def _rate_limited(self) -> RateLimitedError:
        return RateLimitedError(
            "Too many advice requests; try again shortly.",
            retry_after_seconds=math.ceil(float(getattr(self._limiter, "window_seconds", 60.0))),
        )

    def public_job_view(self, job_id: str) -> dict[str, object] | None:
        """The public job view with progress, coded reasons and verified repairs.

        The stored record carries the client's idempotency key and the worker's
        failure text; neither belongs on a public endpoint, so the view names the
        fields it serves instead of serving the record.

        Three fields say how the wait is going, and each is ``null`` when it does not apply
        or cannot be read; the rest of the view never depends on them:

        - ``queue_position``: while the job is queued, how many queued jobs will be claimed
          before it (0 when it is next).
        - ``progress``: while it runs, ``{done, total}``, the documents its attempt has
          solved out of those it has to. ``null`` until the attempt has recorded its first
          count.
        - ``workers``: ``{busy, total}``, the workers alive now and how many hold a job.

        ``queue_position`` and ``workers`` come from the look ``/ready`` holds for five
        seconds, so they can be that much older than ``status``.
        """

        record = self._queue.load(job_id)
        if record is None:
            return None
        look = self._job_look() if self._job_look is not None else None
        progress = None
        if self._job_progress is not None and record.status == "running":
            try:
                progress = self._job_progress(record)
            except (OSError, ValueError):
                # A lock that stayed busy or a record that went as it was read: no count
                # this time, and the poll still answers.
                progress = None
        workers = look.workers if look is not None else None
        view: dict[str, object] = {
            "contract_version": "advice_job_view_v2"
            if record.contract_version == "backend_jobs_v2"
            else "advice_job_view_v1",
            "job_id": record.job_id,
            "status": record.status,
            "created_at_utc": record.created_at_utc,
            "updated_at_utc": record.updated_at_utc,
            "attempt": record.attempt,
            "error_code": record.error.code if record.error is not None else None,
            "queue_position": look.queue_position(record) if look is not None else None,
            "progress": progress.as_view() if progress is not None else None,
            "workers": workers.as_view() if workers is not None else None,
        }
        if record.error is not None and record.error.infeasibility is not None:
            view["infeasibility"] = record.error.infeasibility
        return view

    def cancel_run(self, run_id: str, *, at_utc: str, client_bucket: str = "unknown") -> None:
        # Reuse the strict reference parser so IDs can never become arbitrary store paths.
        RunReference.parse({"contract_version": "llmopt_run_v1", "run_id": run_id, "stage": "base"})
        if self._runs is None:
            raise RunAdmissionError("RUN_STORE_UNAVAILABLE", "Planning work is unavailable.")
        bucket = client_address_bucket(client_bucket)
        if self._limiter is not None and not self._limiter.allow(f"ip:{bucket}"):
            raise self._rate_limited()
        self._runs.cancel(
            run_id, self._queue, at_utc, capture=self._reader.current_capture_snapshot_id()
        )

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
        top100_weight: int = 0,
        managers_word: bool = False,
        chip: str | None = None,
        model: str = "current",
        preferences: DecisionPreferences = NO_PREFERENCES,
        preference_bundle: PreferenceBundle | None = None,
        run: RunReference | None = None,
        run_tx: RunTransaction | None = None,
        run_resolved: ResolvedAdviceRequest | None = None,
        admission_charged: bool = False,
    ) -> SubmitOutcome:
        """Submit work and durably acknowledge anonymous V2 consumers."""

        def ask(transaction: RunTransaction | None, charged: bool) -> SubmitOutcome:
            return self._submit(
                league_id=league_id,
                entry_id=entry_id,
                strategy=strategy,
                window=window,
                rival_entry_id=rival_entry_id,
                idempotency_key=idempotency_key,
                client_bucket=client_bucket,
                at_utc=at_utc,
                top100_weight=top100_weight,
                managers_word=managers_word,
                chip=chip,
                model=model,
                preferences=preferences,
                preference_bundle=preference_bundle,
                run=run,
                run_tx=transaction,
                run_resolved=run_resolved,
                admission_charged=charged,
            )

        outcome = ask(run_tx, admission_charged)
        if (
            run is not None
            or self._runs is None
            or outcome.job is None
            or outcome.job.contract_version != "backend_jobs_v2"
        ):
            return outcome
        # The queue/admission locks have been released. Preserve ledger -> queue
        # ordering without serializing independent legacy admissions on the ledger.
        with self._runs.transaction(at_utc=at_utc) as transaction:
            joined = self._queue.load(outcome.job.job_id)
            if joined is None:
                raise RunAdmissionError("RUN_REQUEST_INCOMPLETE", "Please retry this request.")
            if joined.status == "cancelled":
                # Cancellation won before the anonymous join was acknowledged.
                # Retry under the ledger lock: a new V2 producer cannot race this
                # admission, and a new V1 job keeps the legacy execution policy.
                outcome = ask(transaction, True)
            else:
                outcome = SubmitOutcome(kind="job", job=joined)
            if outcome.job is not None and outcome.job.contract_version == "backend_jobs_v2":
                if (
                    not outcome.job.is_terminal
                    and outcome.job.job_id not in transaction.state["jobs"]
                ):
                    raise RunAdmissionError(
                        "RUN_STORE_UNAVAILABLE", "The admitted work is unavailable."
                    )
                transaction.legacy_consumer(outcome.job.job_id)
        return outcome

    def _authorize_repair(
        self,
        run: RunReference,
        tx: RunTransaction,
        key: str,
        spec: AdviceJobSpec,
        preferences: DecisionPreferences,
    ) -> None:
        state = tx.state["runs"][run.run_id]
        candidates = state.get("repair_candidates", [])
        if key in candidates:
            return
        rejected = RunAdmissionError("RUN_REPAIR_INVALID", "This edit does not match the plan.")
        if self._specs is None or (base := self._specs.get(state["base"])) is None:
            raise rejected
        if not same_repair_scope(base, spec):
            raise rejected
        base_id = state["requests"].get(state["base"])
        job = self._queue.load(base_id) if base_id is not None else None
        base_ready = state["base_cached"] or (job is not None and job.status == "completed")
        # A selection must replay one of this run's completed candidate documents.
        sources = [*candidates, *([state["base"]] if base_ready else [])]
        for source in sources:
            answer = self._reader.cached(source)
            prior = self._specs.get(source)
            if answer is not None and prior is not None and replays_witness(prior, spec, answer):
                return
        if not base_ready:
            if (
                job is None
                or job.error is None
                or not single_rule_edit(
                    base,
                    spec,
                    known_chip_conflict=job.error.code == "CHIP_NOT_HELD",
                    diagnosed=job.error.infeasibility["repairs"] if job.error.infeasibility else (),
                )
            ):
                raise rejected
        elif len(preferences.frozen_weeks) == 3:
            # All-week selection pins must come from a witness, even for a static run.
            raise rejected
        # After a static conflict its first edited request was the successful base.
        if len(candidates) >= (1 if base_ready else 2):
            raise RunAdmissionError("RUN_BUDGET_EXHAUSTED", "The completed plans are available.")
        tx.repair_candidate = key

    def _submit(
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
        top100_weight: int = 0,
        managers_word: bool = False,
        chip: str | None = None,
        model: str = "current",
        preferences: DecisionPreferences = NO_PREFERENCES,
        preference_bundle: PreferenceBundle | None = None,
        run: RunReference | None = None,
        run_tx: RunTransaction | None = None,
        run_resolved: ResolvedAdviceRequest | None = None,
        admission_charged: bool = False,
    ) -> SubmitOutcome:
        """Validate, answer from the cache, rate-limit, dedupe, and enqueue, in that order.

        Validation runs before the rate limit so a malformed request never spends a
        token, and so does the cache read: a hit is one small file read that starts no
        work, and charging for it meant a member who opened an already computed plan a
        few times was refused the one request that needed a solve. Only a miss, which
        is a request for work, consults the limiter: the client's address bucket at once,
        the member's entry bucket only once the job is admitted. Deduplication scans open
        jobs by the complete answer key: at most one open job exists per answer, however
        many keys or clients ask. The queue retains each joining key's request identity.
        """

        if run is not None and self._runs is None:
            raise RunAdmissionError("RUN_STORE_UNAVAILABLE", "Planning work is unavailable.")
        if preference_bundle is not None and (run is None or run.stage != "followup"):
            raise RunAdmissionError("RUN_BASE_REQUIRED", "Compute the main plan first.")
        client_bucket = client_address_bucket(client_bucket)
        if self._store_ready is not None and not self._store_ready():
            # Refuse before validating: a queue write onto a store that has failed its
            # capability checks either errors, or lands on storage nothing will read
            # again. Both are worse than telling the caller the backend is not ready.
            raise AdviceBackendNotReadyError(
                "The advice store is not available; the backend cannot accept work."
            )
        if idempotency_key is not None:
            # Part of validation, so it runs before a token is spent: a malformed key is
            # the client's mistake, and it used to surface only when the command was
            # built, after the budget had been charged and as an unhandled error.
            try:
                validate_idempotency_key(idempotency_key)
            except BackendApiContractError as error:
                raise MalformedIdempotencyKeyError(
                    "The Idempotency-Key header is not a valid key."
                ) from error

        def resolve() -> ResolvedAdviceRequest:
            return self._reader.resolve(
                league_id=league_id,
                entry_id=entry_id,
                strategy=strategy,
                window=window,
                rival_entry_id=rival_entry_id,
                top100_weight=top100_weight,
                managers_word=managers_word,
                chip=chip,
                model=model,
                preferences=preferences,
                preference_bundle=preference_bundle,
            )

        limiter = self._limiter
        charged = admission_charged
        try:
            resolved = run_resolved if run_resolved is not None else resolve()
        except AdviceInputsNotPreparedError as missing:
            if self._prepare_inputs is None:
                raise
            if self._deadline_for is not None and datetime.fromisoformat(
                at_utc
            ) >= datetime.fromisoformat(self._deadline_for(missing.context)):
                raise DeadlinePassedError("This gameweek's deadline has passed.") from missing
            if (
                self._max_open_jobs is not None
                and sum(not job.is_terminal for job in self._queue.jobs()) >= self._max_open_jobs
            ):
                raise OpenJobLimitedError(
                    "The computation queue is full; try again shortly."
                ) from missing
            if limiter is not None and not limiter.allow(f"ip:{client_bucket}"):
                raise self._rate_limited() from missing
            charged = True
            # The member's inputs, and a rival's where the strategy names one: each is one
            # bounded read, pinned once per capture.
            for team in missing.entries or (entry_id,):
                self._prepare_inputs(missing.context, team)
            resolved = resolve()
        cache_key, context = resolved.key, resolved.context

        def request_spec() -> AdviceJobSpec:
            return AdviceJobSpec(
                league_id=int(league_id),
                entry_id=int(entry_id),
                strategy=strategy,
                window=int(window),
                context=context,
                rival_entry_id=rival_entry_id
                if self._reader.strategy_uses_rival(strategy)
                else None,
                switches=resolved.switches,
            )

        def record_hit(tx: RunTransaction, ref: RunReference, document: bytes) -> None:
            if window == 3 and ref.stage in ("base", "repair") and self._specs is not None:
                spec = request_spec()
                if ref.stage == "repair" and not current_repair_answer(
                    spec, json.loads(document)["payload"]
                ):
                    raise RunAdmissionError("RUN_CONTEXT_CHANGED", "The planning data changed.")
                # Imported answers may have no queue record. Store the immutable spec
                # before publishing the run's reference to its cached witness.
                self._specs.put(cache_key, spec)
            tx.cached(ref)

        if run is not None and run_tx is None:
            assert self._runs is not None
            binding = hashlib.sha256(
                json.dumps(
                    {
                        "context": asdict(context),
                        "league": league_id,
                        "entry": entry_id,
                        "window": window,
                    },
                    sort_keys=True,
                ).encode()
            ).hexdigest()
            with self._runs.transaction(at_utc=at_utc) as transaction:
                transaction.prune(context.capture_snapshot_id, self._queue)
                if run is not None:
                    transaction.bind(
                        run,
                        binding,
                        window,
                        cache_key,
                        self._queue,
                        capture=context.capture_snapshot_id,
                    )
                    if run.stage == "repair":
                        self._authorize_repair(
                            run, transaction, cache_key, request_spec(), preferences
                        )
                    if (
                        preference_bundle is not None
                        and transaction.state["runs"][run.run_id]["base"]
                        != resolved.switches[BUNDLE_SWITCH]["base_key"]
                    ):
                        raise RunAdmissionError(
                            "RUN_BASE_CHANGED", "The main request does not match this run."
                        )
                original = transaction.previous(run, cache_key) if run is not None else None
                if original is not None:
                    assert run is not None
                    held = self._reader.cached(cache_key)
                    if held is not None:
                        record_hit(transaction, run, held)
                        return SubmitOutcome(kind="hit", payload=held)
                    job = self._queue.load(original)
                    if job is None:
                        raise RunAdmissionError(
                            "RUN_REQUEST_INCOMPLETE", "Confirm a new planning run."
                        )
                    return SubmitOutcome(kind="job", job=job)
                return self.submit(
                    league_id=league_id,
                    entry_id=entry_id,
                    strategy=strategy,
                    window=window,
                    rival_entry_id=rival_entry_id,
                    idempotency_key=idempotency_key,
                    client_bucket=client_bucket,
                    at_utc=at_utc,
                    top100_weight=top100_weight,
                    managers_word=managers_word,
                    chip=chip,
                    model=model,
                    preferences=preferences,
                    preference_bundle=preference_bundle,
                    run=run,
                    run_tx=transaction,
                    run_resolved=resolved,
                    admission_charged=charged,
                )
        cached = self._reader.cached(cache_key)
        if cached is not None:
            if run is not None and run_tx is not None:
                record_hit(run_tx, run, cached)
            return SubmitOutcome(kind="hit", payload=cached)
        entry_bucket = f"entry:{context.capture_snapshot_id}:{entry_id}"
        if not charged and limiter is not None and not limiter.allow(f"ip:{client_bucket}"):
            raise self._rate_limited()

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
            top100_weight=top100_weight,
            managers_word=managers_word,
            chip=chip,
            model=model,
            preferences=preferences,
        )
        fingerprint = command.request_fingerprint

        # The key check reads the history and the enqueue writes it later, under the queue
        # lock but by cache key only. Two submissions from the api's thread pool could both
        # read a history without the other's job, so one key was accepted for two requests.
        # One lock per process holds the read through the write; resolving, the cache read
        # and the rate limit stay outside it. Separate API processes also check durable
        # key bindings inside the queue's final transaction.
        with self._admission:
            # Read before entering the queue transaction: jobs() takes that same lock.
            # Admission is serialized in this API process; duplicate jobs never call admit.
            open_jobs = (
                sum(not job.is_terminal for job in self._queue.jobs())
                if self._max_open_jobs is not None
                else 0
            )
            history = self._queue.history(idempotency_key=idempotency_key, cache_key=cache_key)
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
                            if run is not None and run_tx is not None:
                                run_tx.reserve(
                                    run,
                                    cache_key,
                                    job.job_id,
                                    preference_bundle=preference_bundle is not None,
                                )
                            if run_tx is not None and (
                                run is None or job.contract_version == "backend_jobs_v1"
                            ):
                                run_tx.legacy_consumer(job.job_id)
                            return SubmitOutcome(kind="job", job=job)
                        # Terminal replay of the same request: the cache answers when it
                        # can; a failed job means the same key may honestly try again.
                        replay = self._reader.cached(cache_key)
                        if replay is not None:
                            if run is not None and run_tx is not None:
                                record_hit(run_tx, run, replay)
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
                contract_version="backend_jobs_v2" if run is not None else "backend_jobs_v1",
            )

            @contextmanager
            def admit() -> Iterator[None]:
                if self._max_open_jobs is not None and open_jobs >= self._max_open_jobs:
                    raise OpenJobLimitedError("The computation queue is full; try again shortly.")
                self._client_jobs = {
                    identifier: owner
                    for identifier, owner in self._client_jobs.items()
                    if (owned := self._queue.load(identifier)) is not None and not owned.is_terminal
                }
                if (
                    sum(owner == client_bucket for owner in self._client_jobs.values())
                    >= self._max_open_jobs_per_client
                ):
                    raise OpenJobLimitedError(
                        "This connection already has the allowed open computations."
                    )
                # Looked at here and spent only once the job exists. This callback runs under
                # the queue transaction and the admission lock, so nothing in this process
                # can admit in between.
                if limiter is not None and not limiter.has_room(entry_bucket):
                    raise self._rate_limited()
                if run is not None and run_tx is not None:
                    run_tx.reserve(
                        run,
                        cache_key,
                        record.job_id,
                        preference_bundle=preference_bundle is not None,
                    )
                self._client_jobs[record.job_id] = client_bucket
                try:
                    yield
                except BaseException:
                    self._client_jobs.pop(record.job_id, None)
                    raise
                if limiter is not None:
                    limiter.allow(entry_bucket)

            def prepare() -> None:
                # Only new work reaches this callback: late cache hits and open-job
                # replays still answer after the deadline, without publishing a new spec.
                if self._deadline_for is not None and datetime.fromisoformat(
                    at_utc
                ) >= datetime.fromisoformat(self._deadline_for(context)):
                    raise DeadlinePassedError("This gameweek's deadline has passed.")
                if self._specs is not None:
                    # Before the job exists, never after: a worker may claim the instant the
                    # record lands, and a claimed job whose request cannot be read is a job
                    # nobody can answer. The rival is normalized exactly as the cache key
                    # normalizes it, so requests that share an address share a meaning.
                    self._specs.put(cache_key, request_spec())

            # Completion publishes cache bytes and removes the open reservation under the
            # same lock as this final cache check and enqueue decision. An earlier miss must
            # not create a second job after another worker has already answered it.
            winner = self._queue.submit_unless_cached(
                record, read_cached=self._reader.cached, admit=admit, prepare=prepare
            )
            if isinstance(winner, bytes):
                if run is not None and run_tx is not None:
                    record_hit(run_tx, run, winner)
                return SubmitOutcome(kind="hit", payload=winner)
            if run is not None and run_tx is not None:
                run_tx.reserve(
                    run, cache_key, winner.job_id, preference_bundle=preference_bundle is not None
                )
            if run_tx is not None and (run is None or winner.contract_version == "backend_jobs_v1"):
                run_tx.legacy_consumer(winner.job_id)
            return SubmitOutcome(kind="job", job=winner)
