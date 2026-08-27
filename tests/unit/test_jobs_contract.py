"""backend_jobs_v1: the lifecycle is the contract, and every edge is a rule."""

import pytest

from squadopt.platform.jobs_contract import (
    ALLOWED_TRANSITIONS,
    AdviceJob,
    BackendJobsContractError,
    JobError,
)

FINGERPRINT = "a" * 64
CACHE_KEY = "b" * 64
RESULT = "c" * 64


def _job(**overrides: object) -> AdviceJob:
    fields: dict[str, object] = {
        "job_id": "job-0001",
        "status": "queued",
        "request_fingerprint": FINGERPRINT,
        "cache_key": CACHE_KEY,
        "created_at_utc": "2026-08-27T12:00:00Z",
        "updated_at_utc": "2026-08-27T12:00:00Z",
    }
    fields.update(overrides)
    return AdviceJob(**fields)  # type: ignore[arg-type]


def test_the_happy_path_walks_the_machine_and_round_trips() -> None:
    queued = _job()
    running = queued.transition("running", at_utc="2026-08-27T12:00:05Z")
    done = running.transition("completed", at_utc="2026-08-27T12:00:35Z", result_ref=RESULT)

    assert (queued.status, running.status, done.status) == ("queued", "running", "completed")
    assert done.is_terminal and not running.is_terminal
    assert done.result_ref == RESULT and done.error is None
    assert done.attempt == 1
    assert AdviceJob.from_payload(done.as_payload()) == done


def test_a_failed_job_says_why() -> None:
    running = _job().transition("running", at_utc="2026-08-27T12:00:05Z")
    failed = running.transition(
        "failed",
        at_utc="2026-08-27T12:00:10Z",
        error=JobError(code="SOLVER_ERROR", message="CP-SAT rejected the model."),
    )
    assert failed.is_terminal
    assert failed.error is not None and failed.error.code == "SOLVER_ERROR"
    assert AdviceJob.from_payload(failed.as_payload()) == failed


def test_the_disposable_worker_edge_requeues_and_counts_the_attempt() -> None:
    running = _job().transition("running", at_utc="2026-08-27T12:00:05Z")
    requeued = running.transition("queued", at_utc="2026-08-27T12:01:00Z")
    assert requeued.status == "queued"
    assert requeued.attempt == 2  # a crash-looping job is visible as one
    assert requeued.result_ref is None and requeued.error is None
    second = requeued.transition("running", at_utc="2026-08-27T12:01:05Z")
    assert second.attempt == 2


def test_terminal_states_are_terminal_and_shortcuts_are_refused() -> None:
    queued = _job()
    with pytest.raises(BackendJobsContractError, match="No edge"):
        queued.transition("completed", at_utc="2026-08-27T12:01:00Z", result_ref=RESULT)
    done = queued.transition("running", at_utc="2026-08-27T12:00:05Z").transition(
        "completed", at_utc="2026-08-27T12:00:35Z", result_ref=RESULT
    )
    for target in ("queued", "running", "failed"):
        with pytest.raises(BackendJobsContractError, match="terminal"):
            done.transition(target, at_utc="2026-08-27T13:00:00Z")  # type: ignore[arg-type]


def test_state_invariants_bind_result_and_error_to_their_states() -> None:
    with pytest.raises(BackendJobsContractError, match="completed job must carry"):
        _job(status="completed")
    with pytest.raises(BackendJobsContractError, match="failed job must carry"):
        _job(status="failed")
    with pytest.raises(BackendJobsContractError, match="neither"):
        _job(status="queued", result_ref=RESULT)
    running = _job().transition("running", at_utc="2026-08-27T12:00:05Z")
    with pytest.raises(BackendJobsContractError, match="completed job must carry"):
        running.transition("completed", at_utc="2026-08-27T12:00:35Z")  # no result_ref
    with pytest.raises(BackendJobsContractError, match="failed job must carry"):
        running.transition("failed", at_utc="2026-08-27T12:00:35Z")  # no error


def test_time_and_identity_are_validated() -> None:
    with pytest.raises(BackendJobsContractError, match="UTC"):
        _job(created_at_utc="2026-08-27T12:00:00+03:00")
    with pytest.raises(BackendJobsContractError, match="precede"):
        _job(updated_at_utc="2026-08-27T11:59:59Z")
    with pytest.raises(BackendJobsContractError, match="SHA-256"):
        _job(cache_key="not-a-digest")
    with pytest.raises(BackendJobsContractError, match="job_id"):
        _job(job_id="")
    running = _job().transition("running", at_utc="2026-08-27T12:00:05Z")
    with pytest.raises(BackendJobsContractError, match="backwards"):
        running.transition("queued", at_utc="2026-08-27T11:00:00Z")


def test_the_machine_is_exactly_the_declared_edges() -> None:
    assert (
        frozenset(
            {
                ("queued", "running"),
                ("running", "completed"),
                ("running", "failed"),
                ("running", "queued"),
            }
        )
        == ALLOWED_TRANSITIONS
    )


def test_a_malformed_payload_is_refused_loudly() -> None:
    with pytest.raises(BackendJobsContractError, match="JSON object"):
        AdviceJob.from_payload([])
    with pytest.raises(BackendJobsContractError, match="missing"):
        AdviceJob.from_payload({"job_id": "x"})
    good = _job().as_payload()
    good["status"] = "paused"
    with pytest.raises(BackendJobsContractError, match="Unknown job status"):
        AdviceJob.from_payload(good)
