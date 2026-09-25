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
answer itself is not computed here: ``advise_menu_entry`` dispatches to the producers
that decide what advice is, and a plain request is ``advise_entry`` byte for byte. A
switched-on request is computed only against the very input it was accepted against: the
spec records that input's identity, and a capture whose input has since changed refuses
the job by name rather than filing one export's answer at another's address.

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
import traceback
from collections.abc import Callable, Sequence
from contextlib import ExitStack
from datetime import UTC, datetime
from types import FrameType
from typing import Final

from squadopt.application.advice_capabilities import menu_capabilities
from squadopt.application.advice_menu import (
    PLAN_NOT_FOUND_ERRORS,
    ChipUnavailable,
    ManagersWordNotSolved,
    MenuRequest,
    advise_menu_entry,
)
from squadopt.application.league_views import LEAGUE_VIEW_CONTRACT_VERSION
from squadopt.contracts.preferences import DecisionPreferences
from squadopt.live.football_artifact import SHARES_BEFORE_AVAILABILITY_LIMIT
from squadopt.platform.advice_cache import AdviceCacheRepository, advice_cache_key
from squadopt.platform.advice_documents import AdviceDocumentError, validate_advice_document
from squadopt.platform.advice_job_spec import AdviceJobSpec, AdviceJobSpecError, AdviceJobSpecStore
from squadopt.platform.advice_observability import (
    WORKER_COUNTER_FAMILIES,
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
from squadopt.platform.advice_switches import (
    CHIP_SWITCH,
    MANAGERS_WORD_SWITCH,
    MODEL_SWITCH,
    TOP100_SWITCH,
    SwitchInputUnavailable,
    switch_identity,
)
from squadopt.platform.backend_runtime import (
    AdviceBackend,
    CaptureContextProvider,
    backend_from_environment,
)
from squadopt.platform.capture_context import AdviceCaptureContext
from squadopt.platform.jobs_contract import AdviceJob
from squadopt.platform.queue_contracts import QueueLockTimeout
from squadopt.platform.worker_metrics import serve_worker_metrics
from squadopt.prediction.football import FOOTBALL_MODEL_VERSION

__all__ = [
    "DEFAULT_HEARTBEAT_SECONDS",
    "DEFAULT_IDLE_SECONDS",
    "DEFAULT_MAX_ATTEMPTS",
    "DEFAULT_MAX_BACKOFF_SECONDS",
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
# The longest wait after rounds that keep raising: a lasting fault is retried and logged
# once a minute rather than every idle, and a passing one costs at most this much.
DEFAULT_MAX_BACKOFF_SECONDS: Final = 60.0


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _stamp(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


#: The switches this worker computes, and the code a job fails with when the capture has
#: no input for one. A switch that needs no per-capture input is added to the first only.
_KNOWN_SWITCHES: Final = frozenset(
    {TOP100_SWITCH, MANAGERS_WORD_SWITCH, CHIP_SWITCH, MODEL_SWITCH, "preferences"}
)
_SWITCH_REFUSAL_CODES: Final = {
    MODEL_SWITCH: "MODEL_INPUTS_UNAVAILABLE",
    TOP100_SWITCH: "TOP100_INPUTS_UNAVAILABLE",
    MANAGERS_WORD_SWITCH: "MANAGERS_WORD_UNAVAILABLE",
}


def _menu_request(spec: AdviceJobSpec, capture: AdviceCaptureContext) -> MenuRequest:
    """The spec as the menu's request, after proving its switch inputs are still these.

    The identity recorded at submission is rebuilt from what this process holds and the
    two must be equal, field for field. A different export (or none) means the key this
    job would be filed under names an input the answer was not computed from.
    """

    try:
        preference_value = spec.switch("preferences").get("value", "{}")
        if not isinstance(preference_value, str):
            raise ValueError("Invalid preference identity.")
        preferences = DecisionPreferences.parse(json.loads(preference_value))
    except (ValueError, TypeError) as error:
        raise AdviceComputeRefused("REQUEST_UNREADABLE", "Invalid preferences.") from error
    model = spec.switch(MODEL_SWITCH).get("name", "current")
    if model not in ("current", "football"):
        raise AdviceComputeRefused("REQUEST_UNREADABLE", "Unknown prediction model.")
    top100 = spec.switch(TOP100_SWITCH).get("weight", 0)
    weight = top100 if isinstance(top100, int) and not isinstance(top100, bool) else -1
    word = MANAGERS_WORD_SWITCH in spec.switches
    chip = spec.switch(CHIP_SWITCH).get("chip")
    if CHIP_SWITCH in spec.switches and not isinstance(chip, str):
        raise AdviceComputeRefused("REQUEST_UNREADABLE", "The chip choice is unreadable.")
    unknown = set(spec.switches) - _KNOWN_SWITCHES
    if unknown or (TOP100_SWITCH in spec.switches and weight < 1):
        raise AdviceComputeRefused(
            "REQUEST_UNREADABLE",
            "The recorded request names a switch this worker does not compute.",
        )
    try:
        held = switch_identity(
            capture.switches,
            top100_weight=weight,
            managers_word=word,
            chip=chip if isinstance(chip, str) else None,
            model=str(model),
            preferences=preferences,
        )
    except SwitchInputUnavailable as error:
        raise AdviceComputeRefused(_SWITCH_REFUSAL_CODES[error.switch], str(error)) from error
    if held != {name: dict(value) for name, value in spec.switches.items()}:
        raise AdviceComputeRefused(
            "SWITCH_INPUTS_CHANGED",
            "The Top 100 counts or the club news this job was accepted against have been "
            "replaced since; ask again to be answered from the current ones.",
        )
    return MenuRequest(
        season=spec.context.season,
        gameweek=spec.context.gameweek,
        league_id=spec.league_id,
        entry_id=spec.entry_id,
        strategy=spec.strategy,
        window=spec.window,
        rival_entry_id=spec.rival_entry_id,
        top100_weight=weight,
        managers_word=word,
        preferences=preferences,
        chip=chip if isinstance(chip, str) else None,
    )


def build_advice_compute(
    contexts: CaptureContextProvider,
    specs: AdviceJobSpecStore,
    *,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    cache: AdviceCacheRepository | None = None,
    job_log_fields: dict[str, object] | None = None,
) -> Callable[[AdviceJob], bytes]:
    """Return the callback that turns one claimed job into the bytes it will be served as.

    ``cache`` is optional and read-only here. A switched-on or windowed document is priced
    and compared against the member's plain documents (the pure-points window, the
    strategy at setting 0); when the cache already holds one under this same context it
    is the very payload the computation would produce again, so it is read back instead
    of solved a second time. A window solve is minutes, and this is most of what a
    switched-on window costs.
    """

    uses_rival = {slug: value.requires_rival for slug, value in menu_capabilities().items()}

    def cached_plain(spec: AdviceJobSpec, address: MenuRequest) -> dict[str, object] | None:
        if cache is None or not address.is_plain or address.strategy not in uses_rival:
            return None
        key = advice_cache_key(
            advice_contract_version=spec.context.advice_contract_version,
            capture_snapshot_id=spec.context.capture_snapshot_id,
            season=spec.context.season,
            gameweek=spec.context.gameweek,
            league_id=address.league_id,
            entry_id=address.entry_id,
            strategy=address.strategy,
            window=address.window,
            projection_handoff_fingerprint=spec.context.projection_handoff_fingerprint,
            repository_commit=spec.context.repository_commit,
            configuration_fingerprint=spec.context.configuration_fingerprint,
            rival_entry_id=address.rival_entry_id,
            strategy_uses_rival=uses_rival[address.strategy],
            switches={MODEL_SWITCH: spec.switches[MODEL_SWITCH]}
            if MODEL_SWITCH in spec.switches
            else {},
        )
        held = cache.get(key)
        if held is None:
            return None
        try:
            validate_advice_document(held)
        except AdviceDocumentError:
            return None  # an entry the read side would refuse is not a prerequisite
        payload = json.loads(held).get("payload")
        return payload if isinstance(payload, dict) else None

    def compute(job: AdviceJob) -> bytes:
        # One worker computes one job at a time. Share only the validated spec's
        # coordinates with the terminal logger; a later unreadable spec stays absent.
        if job_log_fields is not None:
            job_log_fields.clear()
        if job.attempt > max_attempts:
            raise AdviceComputeRefused(
                "TOO_MANY_ATTEMPTS",
                f"This job has been attempted {job.attempt} times; a job that cannot "
                "finish is a fault to look at, not work to repeat.",
            )
        try:
            spec = specs.get(job.cache_key)
        except AdviceJobSpecError as error:
            # A spec that is there and cannot be read is the same fact as one that is
            # not there: what to compute cannot be known. It used to be recorded as a
            # failed computation, which it never was.
            raise AdviceComputeRefused(
                "REQUEST_UNREADABLE",
                "The request recorded at this job's address cannot be read. Ask again "
                "to file a fresh one.",
            ) from error
        if spec is None:
            raise AdviceComputeRefused(
                "REQUEST_UNREADABLE",
                "No request is recorded at this job's address, so what to compute "
                "cannot be known. Ask again to file a fresh one.",
            )
        if job_log_fields is not None:
            job_log_fields.update(window=spec.window, strategy=spec.strategy)
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
        request = _menu_request(spec, capture)
        football = capture.switches.football if MODEL_SWITCH in spec.switches else None
        projection = football.projection if football is not None else capture.projection
        horizon_builder = (
            football.build_horizon if football is not None else capture.horizon_builder
        )
        for label, entry in (("Entry", spec.entry_id), ("Rival", spec.rival_entry_id)):
            if entry is not None and not capture.provider.holds(entry, spec.context.gameweek - 1):
                # The member directory and the capture are published separately, so a
                # member can be listed before a capture holds their squad.
                raise AdviceComputeRefused(
                    "ENTRY_NOT_IN_CAPTURE",
                    f"{label} {entry} is not in the capture this backend answers from, so "
                    "there is no squad to advise from yet.",
                )
        try:
            advice = advise_menu_entry(
                request,
                provider=capture.provider,
                inputs=capture.inputs,
                projection=projection,
                rules=capture.rules,
                horizon_builder=horizon_builder,
                top100_counts=capture.top100_counts,
                manager_words=capture.manager_words,
                chip_forecast_source=capture.chip_forecast_source if football is None else None,
                prerequisite=lambda address: cached_plain(spec, address),
            )
        except ChipUnavailable as error:
            raise AdviceComputeRefused(error.code, str(error)) from error
        except ManagersWordNotSolved as error:
            # One member's outcome, not a fault and not a missing input: the capture has
            # the club news, and this member's plan under the word and the setting could
            # not be produced. The same request without the word still answers.
            raise AdviceComputeRefused("MANAGERS_WORD_NOT_SOLVED", str(error)) from error
        except PLAN_NOT_FOUND_ERRORS as error:
            # One member's outcome, not a fault: the planner found no plan for this
            # selection. Its own text is a solver's diagnostic and the job record travels
            # out through the jobs endpoint, so the record names the outcome and the log
            # line (the refusal's cause) keeps the text for the operator.
            raise AdviceComputeRefused(
                "PLAN_NOT_FOUND",
                "No plan was found for this selection from this capture.",
            ) from error
        if football is not None:
            advice["prediction_model"] = {
                "id": "football",
                "version": football.horizon.model_version,
                "experimental": True,
                "fingerprint": football.fingerprint,
            }
            existing_limits = advice.get("stated_limits")
            advice["stated_limits"] = [
                *(existing_limits if isinstance(existing_limits, list) else []),
                "Experimental football model; independent predictive superiority is unverified.",
                # Only the version that splits attacking shares before availability.
                *(
                    [SHARES_BEFORE_AVAILABILITY_LIMIT]
                    if football.horizon.model_version == FOOTBALL_MODEL_VERSION
                    else []
                ),
            ]
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
    max_backoff_seconds: float = DEFAULT_MAX_BACKOFF_SECONDS,
    store_ready: Callable[[], bool] | None = None,
    contexts: CaptureContextProvider | None = None,
    max_jobs: int | None = None,
    metrics: AdviceMetrics | None = None,
    log: AdviceLog | None = None,
    job_log_fields: dict[str, object] | None = None,
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

    A round that raises anything else (the store refusing a claim, a failure record that
    could not be written, a clock that stepped back behind a job's stamp) is logged with
    its trace and waited out, from one idle doubling up to ``max_backoff_seconds``, and
    the next round that works resets the wait. Such an error used to end the process
    while the api kept accepting jobs. Whatever job that round held stays with the queue,
    and recovery walks it back after its lease. ``KeyboardInterrupt`` and ``SystemExit``
    are not caught.
    """

    processed = 0
    recovered_at = 0.0
    waiting_on_store = False
    warmed = None
    failed_rounds = 0
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
        if contexts is not None:
            context = None
            try:
                context = contexts.current()
                if context is not None and context != warmed:
                    warmed = context
                    started = time.monotonic()
                    if contexts.capture(context) is None:
                        raise ValueError("The capture changed while warming the worker.")
                    if log is not None:
                        log.event(
                            "advice_worker_warmed",
                            snapshot_id=context.capture_snapshot_id,
                            seconds=round(time.monotonic() - started, 3),
                        )
                elif context is None:
                    warmed = None
            except Exception as error:
                if log is not None:
                    log.event(
                        "advice_worker_warm_failed",
                        reason=str(error),
                        snapshot_id=None if context is None else context.capture_snapshot_id,
                    )
        try:
            if elapsed - recovered_at >= recover_every_seconds:
                recovered = queue.recover(clock=lambda: _stamp(now()), lease_seconds=lease_seconds)
                recovered_at = elapsed
                if recovered and log is not None:
                    log.event("advice_jobs_recovered", count=len(recovered))
            job = run_advice_worker_once(
                queue,
                cache,
                compute,
                claim_at_utc=lambda: _stamp(now()),
                terminal_at_utc=lambda: _stamp(now()),
                heartbeat_seconds=heartbeat_seconds,
                metrics=metrics,
                log=log,
                job_log_fields=job_log_fields,
            )
        except QueueLockTimeout:
            # Contention on the queue's lock is a busy moment, not a reason to stop
            # being a worker: it used to end the process, and the deployment's only
            # solver with it. Back off one idle and ask again. A recovery that could not
            # run is retried on the next round rather than a whole interval later.
            if metrics is not None:
                metrics.increment("advice_worker_queue_busy_total")
            if log is not None:
                log.event("advice_worker_queue_busy")
            _wait(sleep, should_stop, idle_seconds, poll_seconds)
            continue
        except Exception as error:
            failed_rounds += 1
            backoff = min(idle_seconds * 2.0 ** min(failed_rounds - 1, 16), max_backoff_seconds)
            if metrics is not None:
                metrics.increment("advice_worker_round_failed_total")
            if log is not None:
                log.event(
                    "advice_worker_round_failed",
                    error_type=type(error).__name__,
                    detail=str(error) or None,
                    consecutive=failed_rounds,
                    backoff_seconds=round(backoff, 3),
                    trace="".join(traceback.format_exception(error)),
                )
            _wait(sleep, should_stop, backoff, poll_seconds)
            continue
        failed_rounds = 0
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
    parser.add_argument("--metrics-port", type=int, default=None)
    parser.add_argument("--metrics-host", default="127.0.0.1")
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
    if arguments.metrics_port is not None and not 0 <= arguments.metrics_port <= 65535:
        parser.error("--metrics-port must be between 0 and 65535.")
    configure_advice_logging()
    running = (
        backend
        if backend is not None
        else backend_from_environment(metrics=AdviceMetrics(zero_counters=WORKER_COUNTER_FAMILIES))
    )
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
    with ExitStack() as stack:
        if arguments.metrics_port is not None:
            server = stack.enter_context(
                serve_worker_metrics(
                    lambda: running.metrics.render(
                        queue_depth=sum(not job.is_terminal for job in running.queue.jobs())
                    ),
                    host=arguments.metrics_host,
                    port=arguments.metrics_port,
                )
            )
            running.log.event("advice_worker_metrics_started", port=server.server_port)
        job_log_fields: dict[str, object] = {}
        processed = run_advice_worker(
            running.queue,
            running.cache,
            build_advice_compute(
                running.contexts,
                running.job_specs,
                max_attempts=arguments.max_attempts,
                cache=running.cache,
                job_log_fields=job_log_fields,
            ),
            should_stop=flag,
            # The same TTL'd gate the api submits behind, asked again before every round.
            store_ready=running.probe.passed,
            contexts=running.contexts,
            idle_seconds=arguments.idle_seconds,
            max_jobs=arguments.max_jobs,
            metrics=running.metrics,
            log=running.log,
            job_log_fields=job_log_fields,
        )
    running.log.event("advice_worker_stopped", processed=processed)
    return 0


if __name__ == "__main__":  # pragma: no cover - process entry point
    raise SystemExit(main())
