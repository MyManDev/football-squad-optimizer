"""Named-chip work preserves capacity for the requested model, not auxiliary seeds."""

import json

import pytest
from fastapi.testclient import TestClient
from tests.fixtures.backend_app import app_for_capture, confirmed_request
from tests.unit import test_advice_worker as world

from squadopt.platform.advice_queue import run_advice_worker_once
from squadopt.platform.advice_worker import build_advice_compute


@pytest.mark.parametrize("chip", ["wildcard", "freehit"])
def test_named_chip_auxiliary_work_cannot_displace_the_admitted_main_search(
    tmp_path, monkeypatch, chip
):
    backend = world._deployment(tmp_path, monkeypatch, last_gameweek=5)["backend"]
    client = TestClient(app_for_capture(backend, world.world_module.GW2_CAPTURED_AT))
    route = f"/api/v1/leagues/{world.LEAGUE_ID}/entries/{world.ENTRY_ID}/advice"
    body = confirmed_request(
        {
            "strategy": "saf-puan",
            "window": 3,
            "chip": chip,
            "preferences": {
                "net_points_priority": True,
                "include_players": [1007],
                "no_hits": True,
            },
        }
    )
    response = client.post(route, json=body)
    assert response.status_code == 202, response.text
    fields = {}
    compute = build_advice_compute(
        backend.contexts,
        backend.job_specs,
        cache=backend.cache,
        runs=backend.runs,
        job_log_fields=fields,
    )
    assert run_advice_worker_once(backend.queue, backend.cache, compute, at_utc=world._now_stamp())
    job = backend.queue.load(response.json()["job_id"])
    assert job.status == "completed", job.error
    for outcome in fields["window_solvers"]:
        assert "The native solve cannot fit the admitted work." not in outcome["fallback_reasons"]
    ledger = json.loads(backend.runs.path.read_bytes())
    allocation = ledger["jobs"][job.job_id]
    receipt = allocation["receipt"]
    assert receipt["cp_used"] + receipt["native_reserved"] <= allocation["limit"] == 122
    payload = json.loads(backend.cache.get(job.cache_key))["payload"]
    assert payload["plan_weeks"][0]["chip"] == chip
    for week in payload["plan_weeks"]:
        assert week["transfer_hit_points"] == 0
        assert week["bank_after_tenths"] >= 0
        ids = {row["player_id"] for row in week["lineup"]["starting_xi"] + week["lineup"]["bench"]}
        assert 1007 in ids
