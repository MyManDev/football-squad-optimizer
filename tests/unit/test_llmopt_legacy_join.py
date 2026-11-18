"""Joining existing advice never transfers its original consumer's ownership."""

from fastapi.testclient import TestClient
from tests.fixtures.backend_app import app_for_capture
from tests.unit import test_advice_worker as world


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
