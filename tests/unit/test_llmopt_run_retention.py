"""Capture retirement and cancellation floods never buy fresh run capacity."""

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from tests.unit import test_api_advice_post as api

from squadopt.contracts.llmopt_run import RunReference, run_ledger_schema
from squadopt.platform.advice_queue import FileJobQueue, run_advice_worker_once
from squadopt.platform.advice_runs import (
    CANCEL_TTL_SECONDS,
    MAX_CANCELLED_IDS,
    FileRunStore,
    RunAdmissionError,
)
from squadopt.platform.advice_submit import FixedWindowRateLimiter


def test_cancel_uses_the_existing_ip_budget_and_does_not_create_unknown_runs(tmp_path):
    runs = FileRunStore(tmp_path / "runs")
    client, _, _ = api._world(tmp_path, runs=runs, rate_limiter=FixedWindowRateLimiter(3, 60))
    for index in range(3):
        assert client.post(f"/api/v1/llmopt/runs/{index:032x}/cancel", json={}).status_code == 200
    refused = client.post(f"/api/v1/llmopt/runs/{3:032x}/cancel", json={})
    assert refused.status_code == 429, refused.text
    assert int(refused.headers["Retry-After"]) > 0
    state = json.loads(runs.path.read_bytes())
    assert state["runs"] == state["jobs"] == {}
    assert len(state["cancelled"]) == 3


def test_unknown_cancellations_have_a_count_and_lifetime_bound(tmp_path):
    runs = FileRunStore(tmp_path / "runs")
    queue = FileJobQueue(tmp_path / "queue")
    now = datetime(2026, 11, 19, tzinfo=UTC)
    for index in range(MAX_CANCELLED_IDS + 2):
        runs.cancel(f"{index:032x}", queue, now.isoformat())
    state = json.loads(runs.path.read_bytes())
    assert len(state["cancelled"]) == MAX_CANCELLED_IDS
    assert state["runs"] == state["jobs"] == {}
    assert runs.path.stat().st_size < 100_000
    reference = RunReference(f"{MAX_CANCELLED_IDS + 1:032x}", "base")
    with (
        runs.transaction(at_utc=now.isoformat()) as tx,
        pytest.raises(RunAdmissionError, match="ended"),
    ):
        tx.bind(reference, "b" * 64, 1, "c" * 64, queue, capture="capture")
    expired = (now + timedelta(seconds=CANCEL_TTL_SECONDS + 1)).isoformat()
    with runs.transaction(at_utc=expired) as tx:
        assert tx.state["cancelled"] == {}
    assert runs.path.stat().st_size < 150


def test_multiple_captures_keep_only_the_current_inactive_runs(tmp_path, monkeypatch):
    current = [api.CONTEXT]
    monkeypatch.setattr(api._Context, "current", lambda _: current[0])
    runs = FileRunStore(tmp_path / "runs")
    client, cache, queue = api._world(tmp_path, runs=runs)
    sizes = []
    for capture in range(8):
        current[0] = replace(
            api.CONTEXT, capture_snapshot_id=f"fpl-live-20260826T083133Z-{capture:012x}"
        )
        for number in range(5):
            identifier = f"{capture * 5 + number:032x}"
            response = client.post(
                api.ADVICE_URL, json={**api.BODY, "run": api._run_ref(identifier)}
            )
            assert response.status_code == (202 if number == 0 else 200), response.text
            if number == 0:
                run_advice_worker_once(
                    queue,
                    cache,
                    lambda _: api._valid_advice_document(),
                    at_utc="2026-08-27T12:01:00Z",
                )
        state = json.loads(runs.path.read_bytes())
        assert len(state["runs"]) == 5
        assert len(state["jobs"]) == 1
        assert {row["capture"] for row in state["runs"].values()} == {
            current[0].capture_snapshot_id
        }
        sizes.append(runs.path.stat().st_size)
    assert max(sizes) < 4000


def test_old_capture_keeps_running_work_until_it_completes(tmp_path, monkeypatch):
    current = [api.CONTEXT]
    monkeypatch.setattr(api._Context, "current", lambda _: current[0])
    runs = FileRunStore(tmp_path / "runs")
    client, cache, queue = api._world(tmp_path, runs=runs)
    first = client.post(api.ADVICE_URL, json={**api.BODY, "run": api._run_ref()}).json()["job_id"]
    job = queue.claim(at_utc="2026-08-27T12:01:00Z")
    budget = runs.allocation(first)
    current[0] = replace(api.CONTEXT, capture_snapshot_id="fpl-live-20260826T083133Z-123456789abc")
    request = {**api.BODY, "run": api._run_ref("b" * 32)}
    assert client.post(api.ADVICE_URL, json=request).status_code == 202
    assert len(json.loads(runs.path.read_bytes())["runs"]) == 2
    runs.finish(first, budget)
    queue.complete(
        job, cache=cache, payload=api._valid_advice_document(), at_utc="2026-08-27T12:02:00Z"
    )
    assert client.post(api.ADVICE_URL, json=request).status_code == 202
    state = json.loads(runs.path.read_bytes())
    assert set(state["runs"]) == {"b" * 32}
    assert first not in state["jobs"]


def test_v1_migration_preserves_reservations_and_recovers_capture(tmp_path):
    runs = FileRunStore(tmp_path / "runs")
    client, _, _ = api._world(tmp_path, runs=runs)
    posted = client.post(api.ADVICE_URL, json={**api.BODY, "run": api._run_ref()})
    identifier = posted.json()["job_id"]
    old = json.loads(runs.path.read_bytes())
    old["contract_version"] = "llmopt_run_ledger_v1"
    old.pop("cancelled")
    for row in old["runs"].values():
        row.pop("capture")
    for row in old["jobs"].values():
        row.pop("legacy_consumer")
    runs.path.write_text(json.dumps(old), encoding="utf-8")
    restarted = FileRunStore(
        tmp_path / "runs", capture_for_key=lambda _: api.CONTEXT.capture_snapshot_id
    )
    with restarted.transaction() as tx:
        assert tx.state["runs"]["a" * 32]["reserved"] == 21
        assert tx.state["runs"]["a" * 32]["requests"] == old["runs"]["a" * 32]["requests"]
        assert tx.state["runs"]["a" * 32]["capture"] == api.CONTEXT.capture_snapshot_id
        assert tx.state["jobs"][identifier]["receipt"] is None
        assert tx.state["jobs"][identifier]["legacy_consumer"] is True
        Draft202012Validator(run_ledger_schema()).validate(tx.state)


def test_durable_ledger_schema_is_committed():
    schema = Path("docs/contracts/llmopt_run_ledger_v2.schema.json")
    assert json.loads(schema.read_text(encoding="utf-8")) == run_ledger_schema()


def test_cancellation_before_anonymous_join_acknowledgement_retries_as_legacy(
    tmp_path, monkeypatch
):
    runs = FileRunStore(tmp_path / "runs")
    services = []
    client, _, queue = api._world(tmp_path, runs=runs, submit_services=services)
    original = client.post(api.ADVICE_URL, json={**api.BODY, "run": api._run_ref()})
    original_id = original.json()["job_id"]
    submit = services[0]
    enqueue = submit._submit
    interrupted = False

    def close_between_queue_and_consumer(**fields):
        nonlocal interrupted
        outcome = enqueue(**fields)
        if fields.get("run") is None and not interrupted:
            interrupted = True
            runs.cancel("a" * 32, queue, "2026-08-27T12:00:00Z")
        return outcome

    monkeypatch.setattr(submit, "_submit", close_between_queue_and_consumer)
    anonymous = client.post(api.ADVICE_URL, json=api.BODY)
    assert anonymous.status_code == 202, anonymous.text
    assert interrupted
    assert queue.load(original_id).status == "cancelled"
    replacement = queue.load(anonymous.json()["job_id"])
    assert replacement.job_id != original_id
    assert replacement.contract_version == "backend_jobs_v1"
    assert replacement.status == "queued"
