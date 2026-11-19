"""Joining existing advice never transfers its original consumer's ownership."""

import json
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest
from fastapi.testclient import TestClient
from tests.fixtures.backend_app import app_for_capture
from tests.unit import test_advice_worker as world

from squadopt.platform import advice_worker


def test_abandoning_a_run_cannot_cancel_the_original_legacy_consumer(tmp_path, monkeypatch):
    backend = world._deployment(tmp_path, monkeypatch)["backend"]
    client = TestClient(app_for_capture(backend, world.world_module.GW2_CAPTURED_AT))
    route = f"/api/v1/leagues/{world.LEAGUE_ID}/entries/{world.ENTRY_ID}/advice"
    body = {"strategy": "saf-puan", "window": 1}
    original = client.post(route, json=body)
    assert original.status_code == 202, original.text
    identifier = original.json()["job_id"]
    assert backend.queue.load(identifier).contract_version == "backend_jobs_v1"
    joined = client.post(
        route,
        json={
            **body,
            "run": {
                "contract_version": "llmopt_run_v1",
                "run_id": "d" * 32,
                "stage": "base",
            },
        },
    )
    assert joined.status_code == 202, joined.text
    assert joined.json()["job_id"] == identifier
    assert len(backend.queue.jobs()) == 1
    assert client.post(f"/api/v1/llmopt/runs/{'d' * 32}/cancel", json={}).status_code == 200
    assert backend.queue.load(identifier).status == "queued"
    assert world._work(backend) == 1
    finished = backend.queue.load(identifier)
    assert finished.status == "completed", finished.error
    assert client.get(route, params=body).status_code == 200
    assert len(backend.queue.jobs()) == 1


def _abandon_actual_job(tmp_path, monkeypatch, *, running, legacy):
    backend = world._deployment(tmp_path, monkeypatch)["backend"]
    client = TestClient(app_for_capture(backend, world.world_module.GW2_CAPTURED_AT))
    route = f"/api/v1/leagues/{world.LEAGUE_ID}/entries/{world.ENTRY_ID}/advice"
    body = {"strategy": "saf-puan", "window": 1}
    reference = {"contract_version": "llmopt_run_v1", "run_id": "e" * 32, "stage": "base"}
    posted = client.post(route, json={**body, "run": reference})
    assert posted.status_code == 202, posted.text
    identifier = posted.json()["job_id"]
    assert backend.queue.load(identifier).contract_version == "backend_jobs_v2"
    entered, release = Event(), Event()
    original = advice_worker.advise_menu_entry

    def blocked(*args, **kwargs):
        entered.set()
        assert release.wait(30)
        return original(*args, **kwargs)

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = None
        if running:
            monkeypatch.setattr(advice_worker, "advise_menu_entry", blocked)
            future = pool.submit(world._work, backend)
        try:
            if running:
                assert entered.wait(30)
                assert backend.queue.load(identifier).status == "running"
            if legacy:
                joined = client.post(route, json=body)
                assert joined.status_code == 202, joined.text
                assert joined.json()["job_id"] == identifier
                with backend.runs.transaction() as tx:
                    assert tx.state["jobs"][identifier]["legacy_consumer"] is True
            assert client.post(f"/api/v1/llmopt/runs/{'e' * 32}/cancel", json={}).status_code == 200
            assert backend.queue.load(identifier).status == ("running" if running else "queued")
        finally:
            release.set()
        assert (future.result(timeout=60) if future is not None else world._work(backend)) == 1
    completed = backend.queue.load(identifier)
    assert completed.status == "completed", completed.error
    assert client.post(route, json={**body, "run": reference}).status_code == 409
    another = {**reference, "run_id": "f" * 32}
    answer = client.post(route, json={**body, "run": another})
    assert answer.status_code == 200, answer.text
    assert client.post(route, json=body).content == answer.content
    assert len(backend.queue.jobs()) == 1
    with backend.runs.transaction() as tx:
        assert tx.state["runs"]["f" * 32]["reserved"] == 0
        receipt = tx.state["jobs"][identifier]["receipt"]
        assert set(receipt) == {"cp_used", "native_reserved", "calls"}
        assert receipt["calls"] > 0
    assert json.loads(answer.content)["payload"]["entry_id"] == world.ENTRY_ID


@pytest.mark.parametrize("running", [False, True])
def test_abandoning_a_run_cannot_cancel_a_later_legacy_consumer(tmp_path, monkeypatch, running):
    _abandon_actual_job(tmp_path, monkeypatch, running=running, legacy=True)


def test_closed_running_result_is_cached_for_another_run(tmp_path, monkeypatch):
    _abandon_actual_job(tmp_path, monkeypatch, running=True, legacy=False)
