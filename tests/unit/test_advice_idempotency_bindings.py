"""A client joining open work keeps its own durable retry identity."""

import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from threading import Barrier

import pytest
from tests.unit.test_api_advice_post import ADVICE_URL, BODY, _valid_advice_document, _world

from squadopt.platform.advice_submit import AdviceSubmitService, IdempotencyConflictError
from squadopt.platform.jobs_contract import JobError
from squadopt.platform.queue_contracts import AdviceQueueIntegrityError


def _service(root: Path):
    services: list[AdviceSubmitService] = []
    _client, cache, queue = _world(root, submit_services=services)
    return services[0], cache, queue


def _submit(service: AdviceSubmitService, key: str, *, window: int = 1):
    return service.submit(
        league_id=352490,
        entry_id=313686,
        strategy="saf-puan",
        window=window,
        rival_entry_id=None,
        idempotency_key=key,
        client_bucket="joining-client",
        at_utc="2026-08-27T12:00:00Z",
    )


@pytest.mark.parametrize(
    "phase", ["queued", "running", "failed", "completed", "archived-failed", "archived-completed"]
)
def test_joined_key_survives_restart_terminal_state_and_archive(tmp_path: Path, phase: str):
    service, cache, queue = _service(tmp_path)
    original = _submit(service, "owner").job
    assert original is not None
    assert _submit(service, "joiner").job == original
    assert len(queue.jobs()) == 1

    if phase != "queued":
        running = queue.claim(at_utc="2026-08-27T12:01:00Z")
        assert running is not None
        if phase.endswith("failed"):
            queue.store(
                running.transition(
                    "failed",
                    at_utc="2026-08-27T12:02:00Z",
                    error=JobError("ADVICE_FAILED", "fixture"),
                )
            )
        elif phase.endswith("completed"):
            queue.complete(
                running,
                cache=cache,
                payload=_valid_advice_document(),
                at_utc="2026-08-27T12:02:00Z",
            )
    if phase.startswith("archived-"):
        assert len(queue.archive(now_utc="2026-09-10T00:00:00Z")) == 1
        assert queue.jobs() == ()

    # A fresh service/queue has no process-local memory of the joining request.
    restarted, _cache, reopened = _service(tmp_path)
    with pytest.raises(IdempotencyConflictError):
        _submit(restarted, "joiner", window=3)
    replay = _submit(restarted, "joiner")
    if phase.endswith("completed"):
        assert replay.kind == "hit"
        assert replay.payload == _valid_advice_document()
    else:
        assert replay.job is not None
        if phase.endswith("failed"):
            assert replay.job.job_id != original.job_id
            assert replay.job.job_id.endswith("-2")
        else:
            assert replay.job.job_id == original.job_id
        # Another client's own key joins the same attempt without creating work.
        assert _submit(restarted, "another-joiner").job == replay.job
        with pytest.raises(IdempotencyConflictError):
            _submit(restarted, "another-joiner", window=3)
        assert len([job for job in reopened.jobs() if not job.is_terminal]) == 1


def test_reusing_joined_key_cannot_replace_the_original_request(tmp_path: Path):
    service, _cache, queue = _service(tmp_path)
    original = _submit(service, "owner").job
    assert _submit(service, "joiner").job == original
    with pytest.raises(IdempotencyConflictError):
        _submit(service, "joiner", window=3)
    assert _submit(service, "joiner").job == original
    assert len(queue.jobs()) == 1


def test_http_joiner_keeps_its_key_after_a_conflicting_request(tmp_path: Path):
    client, _cache, queue = _world(tmp_path)
    owner = client.post(ADVICE_URL, json=BODY, headers={"Idempotency-Key": "http-owner"})
    joined = client.post(ADVICE_URL, json=BODY, headers={"Idempotency-Key": "http-joiner"})
    conflict = client.post(
        ADVICE_URL, json={**BODY, "window": 3}, headers={"Idempotency-Key": "http-joiner"}
    )
    replay = client.post(ADVICE_URL, json=BODY, headers={"Idempotency-Key": "http-joiner"})
    assert [owner.status_code, joined.status_code, conflict.status_code, replay.status_code] == [
        202,
        202,
        409,
        202,
    ]
    assert owner.json() == joined.json() == replay.json()
    assert len(queue.jobs()) == 1


@pytest.mark.parametrize("changed", ["request_fingerprint", "cache_key"])
def test_join_binding_checks_both_request_and_answer_identity(tmp_path: Path, changed: str):
    service, _cache, queue = _service(tmp_path)
    original = _submit(service, "owner").job
    assert original is not None
    _submit(service, "joiner")
    conflicting = replace(
        original, job_id="different-intent", idempotency_key="joiner", **{changed: "e" * 64}
    )
    with pytest.raises(IdempotencyConflictError):
        queue.submit_unique(conflicting)
    assert len(queue.jobs()) == 1


@pytest.mark.parametrize("damage", ["torn", "foreign-key", "bad-digest", "extra-field", "array"])
def test_unreadable_join_binding_stays_reserved(tmp_path: Path, damage: str):
    service, _cache, queue = _service(tmp_path)
    _submit(service, "owner")
    _submit(service, "joiner")
    path = queue._idempotency_binding("joiner")
    binding = json.loads(path.read_bytes())
    if damage == "foreign-key":
        binding["idempotency_key"] = "another-key"
    elif damage == "bad-digest":
        binding["cache_key"] = 3
    elif damage == "extra-field":
        binding["unexpected"] = True
    raw = b"{" if damage == "torn" else json.dumps([] if damage == "array" else binding).encode()
    path.write_bytes(raw)

    restarted, _cache, reopened = _service(tmp_path)
    with pytest.raises(AdviceQueueIntegrityError, match="idempotency binding"):
        _submit(restarted, "joiner", window=3)
    assert path.read_bytes() == raw
    assert len(reopened.jobs()) == 1
    evidence = (tmp_path / "jobs" / "integrity").glob("*.bin")
    assert raw in [path.read_bytes() for path in evidence]


def test_separate_services_bind_one_key_atomically(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    first, _cache, first_queue = _service(tmp_path)
    second, _cache, second_queue = _service(tmp_path)
    barrier = Barrier(2)
    for queue in (first_queue, second_queue):
        original = queue.history

        def stale_history(*, idempotency_key, cache_key, original=original):
            result = original(idempotency_key=idempotency_key, cache_key=cache_key)
            barrier.wait(timeout=5)
            return result

        monkeypatch.setattr(queue, "history", stale_history)

    def send(service, window):
        try:
            return _submit(service, "racing-key", window=window)
        except IdempotencyConflictError as error:
            return error

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(send, first, 1), pool.submit(send, second, 3)]
        results = [future.result(timeout=10) for future in futures]
    assert sum(isinstance(result, IdempotencyConflictError) for result in results) == 1
    assert len(first_queue.jobs()) == 1


@pytest.mark.parametrize("archived", [False, True])
def test_atomic_check_respects_owner_keys_from_before_bindings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, archived: bool
):
    service, _cache, queue = _service(tmp_path)
    _submit(service, "legacy-owner")
    # Emulate a pre-upgrade owner record, whose key lived only on the job.
    queue._idempotency_binding("legacy-owner").unlink()
    if archived:
        running = queue.claim(at_utc="2026-08-27T12:01:00Z")
        assert running is not None
        queue.store(
            running.transition(
                "failed", at_utc="2026-08-27T12:02:00Z", error=JobError("ADVICE_FAILED", "fixture")
            )
        )
        assert len(queue.archive(now_utc="2026-09-10T00:00:00Z")) == 1
    # A second process can hold a stale pre-enqueue history; the final transaction
    # must still protect the old key's identity, including archived records.
    monkeypatch.setattr(queue, "history", lambda **_kwargs: ())
    with pytest.raises(IdempotencyConflictError):
        _submit(service, "legacy-owner", window=3)
