"""The public API and real worker execute preferences in one admitted follow-up."""

import json

import pytest
from fastapi.testclient import TestClient
from tests.fixtures.backend_app import app_for_capture
from tests.unit import test_advice_worker as world

from squadopt.contracts.preference_bundle import (
    BUNDLE_VERSION,
    preference_bundle_schema,
    preference_result_schema,
    priority_result_schema,
)
from squadopt.contracts.schema_paths import contract_schema_path
from squadopt.platform.advice_documents import advice_read_schema


def _started(tmp_path, monkeypatch, window=1, chip=None):
    backend = world._deployment(tmp_path, monkeypatch, last_gameweek=5)["backend"]
    client = TestClient(app_for_capture(backend, world.world_module.GW2_CAPTURED_AT))
    route = f"/api/v1/leagues/{world.LEAGUE_ID}/entries/{world.ENTRY_ID}/advice"
    body = {
        "strategy": "saf-puan",
        "window": window,
        "preferences": {"net_points_priority": True, "save_chips": True},
    }
    if chip is not None:
        body["chip"] = chip
        body["preferences"]["save_chips"] = False
    reference = {"contract_version": "llmopt_run_v1", "run_id": "a" * 32, "stage": "base"}
    response = client.post(route, json={**body, "run": reference})
    assert response.status_code == 202, response.text
    assert world._work(backend) == 1
    main = backend.queue.load(response.json()["job_id"])
    assert main.status == "completed", main.error
    scope = backend.contexts.preference_players(
        backend.contexts.current(), world.LEAGUE_ID, world.ENTRY_ID
    )
    return backend, client, route, body, {**reference, "stage": "followup"}, sorted(scope.squad)


@pytest.mark.parametrize("window", [1, 3])
@pytest.mark.parametrize("chip", [None, "freehit"])
def test_three_priority_rules_use_two_real_server_jobs_and_resume_from_cache(
    tmp_path, monkeypatch, window, chip
):
    backend, client, route, body, run, held = _started(tmp_path, monkeypatch, window, chip)
    program = {
        "preferences": [
            {"rules": {"keep_players": [held[0]]}, "priority": 1},
            {"rules": {"avoid_players": [held[1]]}, "priority": 2},
            {"rules": {"no_hits": True}, "priority": 3},
        ],
        "max_total_cost_tenths": 1000,
    }
    bundle = {
        "contract_version": BUNDLE_VERSION,
        "slots": [],
        "prices": [],
        "choices": [],
        "program": program,
    }
    request = {**body, "run": run, "preference_bundle": bundle}
    posted = client.post(route, json=request)
    assert posted.status_code == 202, posted.text
    assert len(backend.queue.jobs()) == 2
    job = backend.queue.load(posted.json()["job_id"])
    spec = backend.job_specs.get(job.cache_key)
    assert (
        json.loads(spec.switch("llmopt_preference_bundle")["request"])["program"][
            "max_total_cost_tenths"
        ]
        == 1000
    )
    assert "run_id" not in json.dumps(spec.as_payload())
    with backend.runs.transaction() as tx:
        assert tx.state["jobs"][job.job_id]["limit"] == (63 if window == 1 else 366)
        assert tx.state["runs"][run["run_id"]]["reserved"] == (84 if window == 1 else 488)
    assert world._work(backend) == 1
    finished = backend.queue.load(job.job_id)
    assert finished.status == "completed", finished.error
    cached = client.post(route, json=request)
    assert cached.status_code == 200, cached.text
    result = cached.json()["payload"]["preference_bundle_result"]
    assert result["components"] == []
    assert result["selected"]["status"] == "done", result
    selected = result["selected"]["payload"]
    metadata = selected["priority_preferences"]
    assert metadata["completed_priorities"] == [1, 2, 3]
    assert len(metadata["satisfied"]) + len(metadata["left_out"]) == 3
    assert metadata["total_cost"] <= 100
    assert metadata["reference_proved"] is (
        cached.json()["payload"].get("solver_status") == "OPTIMAL"
    )
    query = {
        **body,
        "preferences": json.dumps(body["preferences"]),
        "preference_bundle": json.dumps(bundle),
    }
    assert client.get(route, params=query).content == cached.content
    assert len(backend.queue.jobs()) == 2
    with backend.runs.transaction() as tx:
        assert tx.state["jobs"][job.job_id]["receipt"]["calls"] >= 5


def test_bundle_requires_the_original_completed_main_before_admission(tmp_path, monkeypatch):
    backend, client, route, body, run, held = _started(tmp_path, monkeypatch)
    bundle = {
        "contract_version": BUNDLE_VERSION,
        "slots": [],
        "prices": [],
        "choices": [],
        "program": {
            "preferences": [{"rules": {"keep_players": [held[0]]}}],
            "max_total_cost_tenths": 0,
        },
    }
    request = {**body, "preference_bundle": bundle}
    assert client.post(route, json=request).status_code == 409
    changed = client.post(
        route, json={**request, "run": run, "preferences": {**body["preferences"], "no_hits": True}}
    )
    assert changed.status_code == 409, changed.text
    assert changed.json()["error"]["code"] == "RUN_BASE_CHANGED"
    assert len(backend.queue.jobs()) == 1


@pytest.mark.parametrize("window", [1, 3])
def test_legacy_individual_prices_and_combination_share_one_real_job(tmp_path, monkeypatch, window):
    backend, client, route, body, run, held = _started(tmp_path, monkeypatch, window)
    keep = {"preferences": {"keep_players": [held[0]]}, "chip": None}
    avoid = {"preferences": {"avoid_players": [held[1]]}, "chip": None}
    choices = []
    for mask in range(4):
        patch = {"keep_players": [held[2]]}
        applied = []
        if mask & 1:
            patch["keep_players"] = [held[0], held[2]]
            applied.append(0)
        if mask & 2:
            patch["avoid_players"] = [held[1]]
            applied.append(1)
        choices.append(
            {
                "accepted": mask,
                "applied": [*applied, 2],
                "selection": {"preferences": patch, "chip": None},
            }
        )
    bundle = {
        "contract_version": BUNDLE_VERSION,
        "slots": [keep, avoid],
        "program": None,
        "prices": [
            {"outcome": 0, "ceiling": None},
            {"outcome": 1, "ceiling": None},
            {"outcome": "skipped", "ceiling": None},
        ],
        "choices": choices,
    }
    request = {**body, "run": run, "preference_bundle": bundle}
    response = client.post(route, json=request)
    assert response.status_code == 202, response.text
    assert world._work(backend) == 1
    job = backend.queue.load(response.json()["job_id"])
    assert job.status == "completed", job.error
    answer = client.post(route, json=request)
    result = answer.json()["payload"]["preference_bundle_result"]
    assert [row["status"] for row in result["components"]] == ["done", "done"]
    assert result["accepted"] == 3
    assert result["selected"]["status"] == "done", result["selected"]
    assert result["applied"] == [0, 1, 2]
    chosen = result["selected"]["payload"]
    assert "priority_preferences" not in chosen
    legacy = client.get(
        route,
        params={
            "strategy": "saf-puan",
            "window": window,
            "preferences": json.dumps(chosen["preferences"]),
        },
    )
    assert legacy.status_code == 200, legacy.text
    assert legacy.json()["payload"] == chosen
    assert len(backend.queue.jobs()) == 2
    with backend.runs.transaction() as tx:
        receipt = tx.state["jobs"][job.job_id]["receipt"]
        assert receipt["calls"] > 3
        assert receipt["cp_used"] + receipt["native_reserved"] < (63 if window == 1 else 366)


def test_missing_price_branch_is_rejected_before_opening_a_job(tmp_path, monkeypatch):
    backend, client, route, body, run, held = _started(tmp_path, monkeypatch)
    bundle = {
        "contract_version": BUNDLE_VERSION,
        "program": None,
        "slots": [{"preferences": {"keep_players": [held[0]]}, "chip": None}],
        "prices": [{"outcome": 0, "ceiling": 0}],
        "choices": [{"accepted": 0, "applied": [], "selection": None}],
    }
    refused = client.post(route, json={**body, "run": run, "preference_bundle": bundle})
    assert refused.status_code == 422
    assert len(backend.queue.jobs()) == 1


def test_component_cannot_remove_the_main_objective_before_admission(tmp_path, monkeypatch):
    backend, client, route, body, run, _ = _started(tmp_path, monkeypatch)
    bundle = {
        "contract_version": BUNDLE_VERSION,
        "program": None,
        "prices": [],
        "choices": [],
        "slots": [{"preferences": {"net_points_priority": False}, "chip": None}],
    }
    refused = client.post(route, json={**body, "run": run, "preference_bundle": bundle})
    assert refused.status_code == 422
    assert len(backend.queue.jobs()) == 1


def test_an_infeasible_component_keeps_its_legacy_repair_diagnosis(tmp_path, monkeypatch):
    backend, client, route, body, run, held = _started(tmp_path, monkeypatch)
    bundle = {
        "contract_version": BUNDLE_VERSION,
        "program": None,
        "slots": [{"preferences": {"avoid_players": [held[1]], "no_hits": True}, "chip": None}],
        "prices": [{"outcome": 0, "ceiling": None}],
        "choices": [{"accepted": mask, "applied": [], "selection": None} for mask in (0, 1)],
    }
    request = {**body, "run": run, "preference_bundle": bundle}
    admitted = client.post(route, json=request)
    assert admitted.status_code == 202, admitted.text
    assert world._work(backend) == 1
    job = backend.queue.load(admitted.json()["job_id"])
    assert job.status == "completed", job.error
    answer = client.post(route, json=request)
    component = answer.json()["payload"]["preference_bundle_result"]["components"][0]
    assert component["status"] == "failed"
    assert component["error_code"] == "PLAN_NOT_FOUND"
    assert isinstance(component["infeasibility"]["repairs"], list)
    assert len(backend.queue.jobs()) == 2


def test_preference_execution_contract_files_match_their_generators():
    advice = advice_read_schema()
    result = preference_result_schema({"$ref": "#/$defs/llmopt_component_payload"})
    result["$defs"] = advice["$defs"]
    for name, expected in {
        "llmopt_preference_bundle_v1": preference_bundle_schema(),
        "llmopt_preference_result_v1": result,
        "llmopt_priority_result_v1": priority_result_schema(),
    }.items():
        assert json.loads(contract_schema_path(name).read_text(encoding="utf-8")) == expected
