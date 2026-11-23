"""The server selects the workflow without changing shared answers or losing earlier jobs."""

from dataclasses import replace

import pytest
from fastapi.testclient import TestClient
from tests.fixtures.backend_app import app_for_capture
from tests.unit import test_advice_worker as world
from tests.unit.test_llmopt_intent import _request
from tests.unit.test_llmopt_plan_context import request as catalog_request
from tests.unit.test_llmopt_preference_bundle import _started

from squadopt.api.app import create_app
from squadopt.platform.backend_runtime import BackendConfig, BackendConfigError, build_backend


def test_master_is_default_closed_and_package_experiments_need_both_permissions(tmp_path):
    env = {
        f"SQUADOPT_BACKEND_{name}_ROOT": str(tmp_path / name)
        for name in ("STORE", "SITE_DATA", "SNAPSHOT", "HANDOFF")
    }
    assert BackendConfig.from_environment(env).llmopt_vnext is False
    with pytest.raises(BackendConfigError, match="0 or 1"):
        BackendConfig.from_environment({**env, "SQUADOPT_BACKEND_LLMOPT_VNEXT": "yes"})
    closed = BackendConfig.from_environment(
        {**env, "SQUADOPT_BACKEND_TRANSFER_PACKAGES": "1", "SQUADOPT_BACKEND_PACKAGE_GATE": "1"}
    )
    assert not closed.enabled_packages and not closed.enabled_package_gate
    opened = replace(closed, llmopt_vnext=True)
    assert opened.enabled_packages and opened.enabled_package_gate
    assert not replace(opened, transfer_packages=False, package_gate=False).enabled_packages


def test_both_capabilities_report_the_server_setting_and_use_the_same_ordinary_key(
    tmp_path, monkeypatch
):
    opened = world._deployment(tmp_path, monkeypatch, public_entries=True, llmopt_vnext=True)[
        "backend"
    ]
    closed = build_backend(replace(opened.config, llmopt_vnext=False))
    league = f"/api/v1/leagues/{world.LEAGUE_ID}/capabilities"
    public = f"/api/v1/public/leagues/{world.LEAGUE_ID}/entries/{world.ENTRY_ID}/capabilities"
    for backend, active in [(closed, False), (opened, True)]:
        client = TestClient(app_for_capture(backend, world.world_module.GW2_CAPTURED_AT))
        for route in (league, public):
            response = client.get(route)
            assert response.status_code == 200, response.text
            for key in ("llmopt_vnext", "preference_bundles", "verified_repairs"):
                assert (key in response.json()) is active
            assert "transfer_packages" not in response.json()
            assert "three_week_paths" not in response.json()
    args = dict(
        league_id=world.LEAGUE_ID,
        entry_id=world.ENTRY_ID,
        strategy="saf-puan",
        window=1,
        rival_entry_id=None,
    )
    assert opened.reader.resolve_key(**args) == closed.reader.resolve_key(**args)


def test_rollback_drains_existing_work_and_only_admits_new_legacy_jobs(tmp_path, monkeypatch):
    opened = world._deployment(tmp_path, monkeypatch, last_gameweek=5, llmopt_vnext=True)["backend"]
    closed = build_backend(replace(opened.config, llmopt_vnext=False))
    on = TestClient(app_for_capture(opened, world.world_module.GW2_CAPTURED_AT))
    off = TestClient(app_for_capture(closed, world.world_module.GW2_CAPTURED_AT))
    route = f"/api/v1/leagues/{world.LEAGUE_ID}/entries/{world.ENTRY_ID}/advice"
    body = {"strategy": "saf-puan", "window": 3, "preferences": {"no_hits": True}}
    run = {"contract_version": "llmopt_run_v1", "run_id": "7" * 32, "stage": "base"}
    refused = off.post(route, json={**body, "run": run})
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "LLMOPT_VNEXT_DISABLED"
    assert not closed.runs.path.exists() and not closed.queue.jobs()
    admitted = on.post(route, json={**body, "run": run})
    assert admitted.status_code == 202, admitted.text
    job = admitted.json()["job_id"]
    assert off.post(route, json={**body, "run": run}).json()["job_id"] == job
    assert off.get(f"/api/v1/advice-jobs/{job}").json()["status"] == "queued"
    assert world._work(closed) == 1
    assert off.get(f"/api/v1/advice-jobs/{job}").json()["status"] == "completed"
    hit = off.post(route, json={**body, "run": {**run, "run_id": "8" * 32}})
    assert hit.status_code == 200 and hit.content == on.post(route, json=body).content
    followup = {"strategy": "saf-puan", "window": 3, "preferences": {"save_chips": True}}
    refused = off.post(route, json={**followup, "run": {**run, "stage": "followup"}})
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "LLMOPT_VNEXT_DISABLED"
    assert len(closed.queue.jobs()) == 1
    legacy = off.post(route, json=followup)
    assert legacy.status_code == 202, legacy.text
    assert closed.queue.load(legacy.json()["job_id"]).contract_version == "backend_jobs_v1"
    before = closed.runs.path.read_bytes()
    join = off.post(route, json={**followup, "run": {**run, "stage": "followup"}})
    assert join.status_code == 409 and join.json()["error"]["code"] == "LLMOPT_VNEXT_DISABLED"
    assert closed.runs.path.read_bytes() == before


def test_rollback_reads_a_completed_bundle_without_admitting_a_changed_bundle(
    tmp_path, monkeypatch
):
    opened, on, route, body, run, held = _started(tmp_path, monkeypatch)
    closed = build_backend(replace(opened.config, llmopt_vnext=False))
    off = TestClient(app_for_capture(closed, world.world_module.GW2_CAPTURED_AT))
    program = {"preferences": [{"rules": {"keep_players": [held[0]]}}], "max_total_cost_tenths": 5}
    bundle = {
        "contract_version": "llmopt_preference_bundle_v1",
        "slots": [],
        "choices": [],
        "prices": [],
        "program": program,
    }
    request = {**body, "run": run, "preference_bundle": bundle}
    posted = on.post(route, json=request)
    assert posted.status_code == 202, posted.text
    assert world._work(closed) == 1
    read = off.post(route, json=request)
    assert read.status_code == 200 and read.content == on.post(route, json=request).content
    changed = {**bundle, "program": {**program, "max_total_cost_tenths": 6}}
    refused = off.post(route, json={**request, "preference_bundle": changed})
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "LLMOPT_VNEXT_DISABLED"
    assert len(closed.queue.jobs()) == 2


def test_closed_keyless_prompt_and_check_keep_the_original_workflow():
    ordinary = _request()
    priority = {
        "status": "draft",
        "draft": {
            "hard": [],
            "soft": [{"kind": "keep_player", "player_id": 1, "priority": 1}],
            "max_total_cost_tenths": 5,
        },
    }
    for enabled in (False, True):
        with TestClient(create_app(llmopt_vnext=enabled)) as client:
            base = client.post("/api/v1/llmopt/prompt", json=ordinary)
            assert base.status_code == 200
            assert ("max_total_cost_tenths" in base.text) is enabled
            assert client.post("/api/v1/llmopt/prompt", json=catalog_request()).status_code == (
                200 if enabled else 422
            )
            answer = client.post(
                "/api/v1/llmopt/check", json={"request": ordinary, "reply": priority}
            )
            assert answer.status_code == (200 if enabled else 422), answer.text
