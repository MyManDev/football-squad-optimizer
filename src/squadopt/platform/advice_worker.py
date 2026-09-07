"""The worker process: what one job means, and the loop that keeps claiming them.

``run_advice_worker_once`` already knows how to run *a* job — claim it, compute it, cache
the answer, record the terminal state, and treat two different answers under one complete
key as the determinism defect it is. Two things were missing around it: something that
turns a claimed job back into the question it came from, and something that keeps calling
it until the process is told to stop.

**The compute callback.** A job carries digests, not fields, so the request is read back
from the spec written beside it at submission. The capture that spec names must be the one
this process can still answer from; if the deployment has moved to a newer capture, the job
is refused with a stated reason rather than computed from inputs nobody asked about. The
answer itself is not computed here — ``advise_entry`` is, and stays, the only place that
decides what advice is.

**The loop.** One computation at a time per worker, because CP-SAT runs a single search
worker by design and a replica scales by replication (ADR 0006). An empty queue waits
rather than spins. A shutdown signal is honoured *after* the job in hand finishes, so a
member never loses a solve to a deployment. Abandoned work is walked back periodically
rather than on every tick, and a job that has been retried past the limit is failed with a
code instead of crash-looping forever.

The claim is kept alive while the computation runs. One member's plan is not one solve —
a rival strategy runs the control plan, the banded plan and the payload's own plan — so the
wall time that matters is a multiple of the 3.0 to 29.6 s single-solve measurement the 300 s
lease was compared against, and the margin is thinner than it looks. ``queue.heartbeat``
already existed for exactly this; the loop now uses it rather than arguing that it will not
be needed.
"""

from __future__ import annotations

import argparse
import json
import signal
import time
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from types import FrameType
from typing import Final

from squadopt.application.advice import AdviseEntryRequest, advise_entry
from squadopt.application.league_views import LEAGUE_VIEW_CONTRACT_VERSION
from squadopt.platform.advice_cache import AdviceCacheRepository
from squadopt.platform.advice_documents import validate_advice_document
from squadopt.platform.advice_job_spec import AdviceJobSpecStore
from squadopt.platform.advice_observability import (
    AdviceLog,
    AdviceMetrics,
    configure_advice_logging,
)
from squadopt.platform.advice_queue import (
    DEFAULT_LEASE_SECONDS,
    AdviceComputeRefused,
    JobQueue,
    run_advice_worker_once,
)
from squadopt.platform.backend_runtime import (
    AdviceBackend,
    CaptureContextProvider,
    backend_from_environment,
)
from squadopt.platform.jobs_contract import AdviceJob

__all__ = [
    "DEFAULT_HEARTBEAT_SECONDS",
    "DEFAULT_IDLE_SECONDS",
    "DEFAULT_MAX_ATTEMPTS",
    "DEFAULT_RECOVER_EVERY_SECONDS",
    "build_advice_compute",
    "main",
    "run_advice_worker",
]

DEFAULT_IDLE_SECONDS: Final = 2.0
DEFAULT_POLL_SECONDS: Final = 0.25
DEFAULT_RECOVER_EVERY_SECONDS: Final = 30.0
# A third of the lease: two refreshes may be missed before a live claim looks stale.
DEFAULT_HEARTBEAT_SECONDS: Final = DEFAULT_LEASE_SECONDS / 3.0
DEFAULT_MAX_ATTEMPTS: Final = 3


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _stamp(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_advice_compute(
    contexts: CaptureContextProvider,
    specs: AdviceJobSpecStore,
    *,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
) -> Callable[[AdviceJob], bytes]:
    """Return the callback that turns one claimed job into the bytes it will be served as."""

    def compute(job: AdviceJob) -> bytes:
        if job.attempt > max_attempts:
            raise AdviceComputeRefused(
                "TOO_MANY_ATTEMPTS",
                f"This job has been attempted {job.attempt} times; a job that cannot "
                "finish is a fault to look at, not work to repeat.",
            )
        spec = specs.get(job.cache_key)
        if spec is None:
            raise AdviceComputeRefused(
                "REQUEST_UNREADABLE",
                "No request is recorded at this job's address, so what to compute "
                "cannot be known. Ask again to file a fresh one.",
            )
        capture = contexts.capture(spec.context)
        if capture is None:
            # The whole context, not just the capture: the key this answer will be filed
            # under names the commit, the configuration and the handoff too, and computing
            # under any other value of them is the silent corruption this check prevents.
            raise AdviceComputeRefused(
                "CONTEXT_UNAVAILABLE",
                f"The context this job was accepted under (capture "
                f"{spec.context.capture_snapshot_id}) is no longer the one this backend "
                "answers from; ask again to be answered from the current one.",
            )
        advice = advise_entry(
            AdviseEntryRequest(
                season=spec.context.season,
                gameweek=spec.context.gameweek,
                league_id=spec.league_id,
                entry_id=spec.entry_id,
                strategy=spec.strategy,
                window=spec.window,
                rival_entry_id=spec.rival_entry_id,
            ),
            provider=capture.provider,
            inputs=capture.inputs,
            projection=capture.projection,
            rules=capture.rules,
        )
        document = {
            "contract_version": LEAGUE_VIEW_CONTRACT_VERSION,
            # The capture's instant, not the clock's. These bytes live at a
            # content-addressed key whose immutability is checked on every write, so a
            # wall-clock field would make an honest recomputation — after a recovered
            # claim, say — look exactly like a determinism defect. The answer is
            # determined by the capture, so the capture is when it was generated.
            "generated_at_utc": capture.inputs.captured_at_utc,
            "source_kind": "live",
            "payload": advice,
        }
        payload = json.dumps(document, sort_keys=True, separators=(",", ":")).encode("utf-8")
        # Validated here rather than at read time: a document that would be refused on the
        # way out must never reach the cache, where it would be an unanswerable key.
        validate_advice_document(payload)
        return payload

    return compute


def run_advice_worker(
    queue: JobQueue,
    cache: AdviceCacheRepository,
    compute: Callable[[AdviceJob], bytes],
    *,
    should_stop: Callable[[], bool],
    now: Callable[[], datetime] = _utc_now,
    sleep: Callable[[float], None] = time.sleep,
    idle_seconds: float = DEFAULT_IDLE_SECONDS,
    poll_seconds: float = DEFAULT_POLL_SECONDS,
    recover_every_seconds: float = DEFAULT_RECOVER_EVERY_SECONDS,
    lease_seconds: float = DEFAULT_LEASE_SECONDS,
    heartbeat_seconds: float | None = DEFAULT_HEARTBEAT_SECONDS,
    store_ready: Callable[[], bool] | None = None,
    max_jobs: int | None = None,
    metrics: AdviceMetrics | None = None,
    log: AdviceLog | None = None,
) -> int:
    """Claim and compute until told to stop; return how many jobs reached a terminal state.

    ``should_stop`` is injected rather than read from a signal handler here, so a test
    drives the loop deterministically and the process entry point owns the signals.

    ``store_ready`` is asked before **each** round rather than once at startup. A store
    that was healthy when the process began can stop working later, and a worker that kept
    recovering and claiming against it would walk live jobs back to queued and take work it
    cannot finish. An unready store means no new work: the loop idles and keeps asking, so
    a passing mount brings it back without a restart. Nothing here manages a computation
    already in progress — a round is entered or it is not.
    """

    processed = 0
    recovered_at = 0.0
    waiting_on_store = False
    while not should_stop():
        if store_ready is not None and not store_ready():
            if not waiting_on_store and log is not None:
                # Once per outage, not once per round: an unreachable store would
                # otherwise write a log line every couple of seconds for as long as it
                # stays unreachable.
                log.event("advice_worker_waiting_on_store")
            waiting_on_store = True
            _wait(sleep, should_stop, idle_seconds, poll_seconds)
            continue
        if waiting_on_store:
            waiting_on_store = False
            if log is not None:
                log.event("advice_worker_store_recovered")
        elapsed = time.monotonic()
        if elapsed - recovered_at >= recover_every_seconds:
            recovered_at = elapsed
            recovered = queue.recover(at_utc=_stamp(now()), lease_seconds=lease_seconds)
            if recovered and log is not None:
                log.event("advice_jobs_recovered", count=len(recovered))
        job = run_advice_worker_once(
            queue,
            cache,
            compute,
            at_utc=_stamp(now()),
            heartbeat_seconds=heartbeat_seconds,
            metrics=metrics,
            log=log,
        )
        if job is not None:
            processed += 1
            if max_jobs is not None and processed >= max_jobs:
                return processed
            continue
        _wait(sleep, should_stop, idle_seconds, poll_seconds)
    return processed


def _wait(
    sleep: Callable[[float], None],
    should_stop: Callable[[], bool],
    idle_seconds: float,
    poll_seconds: float,
) -> None:
    """Wait out an empty queue in slices, so a shutdown is not held for a whole idle."""

    remaining = idle_seconds
    while remaining > 0.0 and not should_stop():
        slice_seconds = min(poll_seconds, remaining)
        sleep(slice_seconds)
        remaining -= slice_seconds


class _ShutdownFlag:
    """Set by SIGTERM/SIGINT; read between jobs, never inside one.

    A container stop must not lose a solve that is already running, and it must not need
    a second signal to be believed: the flag is idempotent and the loop checks it before
    each claim.
    """

    def __init__(self) -> None:
        self._stop = False

    def __call__(self) -> bool:
        return self._stop

    def request(self, _signal: int, _frame: FrameType | None) -> None:
        self._stop = True


def main(argv: Sequence[str] | None = None, *, backend: AdviceBackend | None = None) -> int:
    """The worker process: the same image as the api, a different command.

        python -m squadopt.platform.advice_worker

    A module entry point rather than a console script on purpose: ``pyproject.toml`` is a
    shared boundary needing every role's approval, and one line of deployment convenience
    is not worth spending that.
    """

    parser = argparse.ArgumentParser(description="Compute queued SquadOpt advice jobs.")
    parser.add_argument(
        "--max-jobs",
        type=int,
        default=None,
        help="stop after this many jobs; the default runs until signalled",
    )
    parser.add_argument("--idle-seconds", type=float, default=DEFAULT_IDLE_SECONDS)
    parser.add_argument("--max-attempts", type=int, default=DEFAULT_MAX_ATTEMPTS)
    arguments = parser.parse_args(argv)
    # A zero idle turns the loop into a busy wait against the shared mount, which is a
    # deployment footgun rather than a tuning choice; the injected loop below still accepts
    # zero, because a test drives it a fixed number of times.
    if arguments.idle_seconds <= 0.0:
        parser.error("--idle-seconds must be positive; an empty queue is waited on, not spun on.")
    if arguments.max_attempts < 1:
        parser.error("--max-attempts must be at least one.")

    # Before anything that logs. The store check below is the first thing an operator needs
    # to read, and without a handler on the advice logger it was formatted and discarded.
    configure_advice_logging()
    running = backend if backend is not None else backend_from_environment()
    probe = running.probe.result()
    if not probe.ok:
        # Loudly, and at once. A worker that cannot reach its store would otherwise spend
        # its life claiming nothing while the deployment looks healthy.
        running.log.event(
            "advice_worker_store_unavailable",
            root=str(running.config.store_root),
            failed=",".join(probe.failures()),
        )
        return 1
    flag = _ShutdownFlag()
    for name in ("SIGTERM", "SIGINT"):
        handled = getattr(signal, name, None)
        if handled is not None:
            signal.signal(handled, flag.request)
    running.log.event("advice_worker_started", store=str(running.config.store_root))
    processed = run_advice_worker(
        running.queue,
        running.cache,
        build_advice_compute(
            running.contexts, running.job_specs, max_attempts=arguments.max_attempts
        ),
        should_stop=flag,
        # The same TTL'd gate the api submits behind, asked again before every round.
        store_ready=running.probe.passed,
        idle_seconds=arguments.idle_seconds,
        max_jobs=arguments.max_jobs,
        metrics=running.metrics,
        log=running.log,
    )
    running.log.event("advice_worker_stopped", processed=processed)
    return 0


if __name__ == "__main__":  # pragma: no cover - process entry point
    raise SystemExit(main())
