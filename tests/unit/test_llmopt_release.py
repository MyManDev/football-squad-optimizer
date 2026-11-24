"""The server selects the workflow without changing shared answers or losing earlier jobs."""

from dataclasses import replace
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from tests.fixtures.backend_app import app_for_capture
from tests.unit import test_advice_worker as world
from tests.unit.test_llmopt_intent import _request
from tests.unit.test_llmopt_plan_context import request as catalog_request
from tests.unit.test_llmopt_preference_bundle import _started

from squadopt.api.app import create_app
from squadopt.platform import advice_worker
from squadopt.platform.backend_runtime import BackendConfig, BackendConfigError, build_backend


def test_master_is_default_closed_and_package_experiments_need_both_permissions(tmp_path):
    env = {
        f"SQUADOPT_BACKEND_{name}_ROOT": str(tmp_path / name)
        for name in ("STORE", "SITE_DATA", "SNAPSHOT", "HANDOFF")
    }
    assert BackendConfig.from_environment(env).llmopt_vnext is False
    assert BackendConfig.from_environment(env).llmopt_vnext_three_week is False
    with pytest.raises(BackendConfigError, match="0 or 1"):
        BackendConfig.from_environment({**env, "SQUADOPT_BACKEND_LLMOPT_VNEXT_THREE_WEEK": "yes"})
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


@pytest.mark.parametrize("one_week_open", [False, True])
def test_rollback_drains_existing_work_and_only_admits_new_legacy_jobs(
    tmp_path, monkeypatch, one_week_open
):
    opened = world._deployment(
        tmp_path, monkeypatch, last_gameweek=5, llmopt_vnext=True, llmopt_vnext_three_week=True
    )["backend"]
    closed = build_backend(
        replace(opened.config, llmopt_vnext=one_week_open, llmopt_vnext_three_week=False)
    )
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


@pytest.mark.parametrize(
    "master,three_week", [(False, False), (False, True), (True, False), (True, True)]
)
def test_window_permission_selects_the_original_prompt_and_checks_normalized_replies(
    master, three_week
):
    client = TestClient(create_app(llmopt_vnext=master, llmopt_vnext_three_week=three_week))
    off = TestClient(create_app())
    prompt, check = "/api/v1/llmopt/prompt", "/api/v1/llmopt/check"
    for window in (1, 3):
        incoming = _request()
        incoming["draft"]["window"] = window
        call = client.post(prompt, json=incoming)
        permission = master and (window == 1 or three_week)
        assert call.status_code == 200
        assert ("max_total_cost_tenths" in call.text) is permission
        if not permission:
            assert call.content == off.post(prompt, json=incoming).content
    dated = {"kind": "keep_player", "player_id": 1, "week": 2, "priority": 1}
    proposal = {
        "status": "draft",
        "draft": {"hard": [], "soft": [dated], "max_total_cost_tenths": 5},
    }
    answer = client.post(check, json={"request": _request(), "reply": proposal})
    assert answer.status_code == (200 if master and three_week else 422), answer.text
    catalog = catalog_request()
    weeks = catalog["plan_context"]["plans"][0]["weeks"]
    weeks.extend({**weeks[0], "week": week} for week in (2, 3))
    assert client.post(prompt, json=catalog).status_code == (200 if master and three_week else 422)


@pytest.mark.parametrize("all_off", [False, True], ids=["three_week_closed", "all_controls_closed"])
def test_package_run_can_read_its_own_three_week_job_after_window_rollback(
    tmp_path, monkeypatch, all_off
):
    old = world._deployment(tmp_path, monkeypatch, last_gameweek=5)["backend"]
    opened = build_backend(
        replace(
            old.config,
            llmopt_vnext=True,
            llmopt_vnext_three_week=True,
            transfer_packages=True,
            package_gate=True,
        )
    )
    closed = build_backend(
        replace(
            opened.config,
            llmopt_vnext=not all_off,
            llmopt_vnext_three_week=False,
            transfer_packages=not all_off,
            package_gate=not all_off,
            three_week_paths=False,
        )
    )
    on = TestClient(app_for_capture(opened, world.world_module.GW2_CAPTURED_AT))
    off = TestClient(app_for_capture(closed, world.world_module.GW2_CAPTURED_AT))
    route = f"/api/v1/leagues/{world.LEAGUE_ID}/entries/{world.ENTRY_ID}/advice"
    body = {"strategy": "saf-puan", "window": 3, "preferences": {"no_hits": True}}
    run = {"contract_version": "llmopt_run_v1", "run_id": "b" * 32, "stage": "base"}
    posted = on.post(route, json={**body, "run": run})
    assert posted.status_code == 202, posted.text
    job_id = posted.json()["job_id"]
    observed = off.post(route, json={**body, "run": run})
    assert observed.status_code == 202 and observed.json()["job_id"] == job_id
    admitted = closed.queue.load(job_id)
    spec = closed.job_specs.get(admitted.cache_key)
    pinned = closed.contexts.capture(spec.context)
    assert pinned.transfer_packages and pinned.package_gate
    with patch.object(
        advice_worker, "advise_menu_entry", wraps=advice_worker.advise_menu_entry
    ) as solve:
        assert world._work(closed) == 1
    request = solve.call_args.args[0]
    assert request.transfer_packages and request.package_gate
    assert off.get(f"/api/v1/advice-jobs/{job_id}").json()["status"] == "completed"
    answered = off.post(route, json={**body, "run": run})
    assert answered.status_code == 200 and "plan_data_id" not in answered.json()["payload"]
    assert answered.content == on.post(route, json={**body, "run": run}).content
    changed = off.post(route, json={**body, "preferences": {"save_chips": True}, "run": run})
    assert changed.status_code == 409
    assert len(closed.queue.jobs()) == 1
    ordinary = off.post(route, json=body)
    assert ordinary.status_code == 202
    legacy = closed.queue.load(ordinary.json()["job_id"])
    assert legacy.contract_version == "backend_jobs_v1"
    assert legacy.cache_key != admitted.cache_key
    fresh = closed.contexts.capture(closed.job_specs.get(legacy.cache_key).context)
    assert not fresh.transfer_packages and not fresh.package_gate
