"""The public API and real worker execute preferences in one admitted follow-up."""

import hashlib
import json
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient
from tests.fixtures.backend_app import app_for_capture
from tests.unit import test_advice_worker as world

from squadopt.contracts.llmopt_run import RunReference
from squadopt.contracts.preference_bundle import (
    BUNDLE_VERSION,
    preference_bundle_schema,
    preference_result_schema,
    priority_result_schema,
)
from squadopt.contracts.schema_paths import contract_schema_path
from squadopt.platform.advice_documents import advice_read_schema, validate_advice_document
from squadopt.platform.backend_runtime import build_backend


def _started(tmp_path, monkeypatch, window=1, chip=None):
    backend = world._deployment(tmp_path, monkeypatch, last_gameweek=5, llmopt_vnext=True)[
        "backend"
    ]
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
    assert metadata["unsearched"] == []
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
    historical = cached.json()
    del historical["payload"]["preference_bundle_result"]["selected"]["payload"][
        "priority_preferences"
    ]["unsearched"]
    validate_advice_document(json.dumps(historical).encode())
    with backend.runs.transaction() as tx:
        assert tx.state["jobs"][job.job_id]["receipt"]["calls"] >= 5


@pytest.mark.parametrize("window", [1, 3])
def test_rollback_drains_and_reads_the_original_bundle_without_admitting_new_work(
    tmp_path, monkeypatch, window
):
    opened, on, route, body, run, held = _started(tmp_path, monkeypatch, window)
    closed = build_backend(replace(opened.config, llmopt_vnext=False))
    off = TestClient(app_for_capture(closed, world.world_module.GW2_CAPTURED_AT))
    program = {"preferences": [{"rules": {"keep_players": [held[0]]}}], "max_total_cost_tenths": 5}
    bundle = {
        "contract_version": BUNDLE_VERSION,
        "slots": [],
        "prices": [],
        "choices": [],
        "program": program,
    }
    request = {**body, "run": run, "preference_bundle": bundle}
    queued = on.post(route, json=request)
    assert queued.status_code == 202, queued.text
    previous = off.post(route, json=request)
    assert previous.status_code == 202 and previous.json() == queued.json()
    assert world._work(closed) == 1
    expected = on.post(route, json=request)
    assert expected.status_code == 200, expected.text
    query = {
        **body,
        "preferences": json.dumps(body["preferences"]),
        "preference_bundle": json.dumps(bundle),
    }
    assert (
        off.get(route, params=query).content
        == off.post(route, json=request).content
        == expected.content
    )
    job = opened.queue.load(queued.json()["job_id"])
    with opened.runs.transaction() as tx:
        ledger = tx.state["jobs"][job.job_id]
        receipt = ledger["receipt"]
        assert receipt["finished"] and receipt["attempt"] == 1 and receipt["calls"] > 0
        assert "answer_sha256" not in receipt
        if window == 3:
            # Earlier aggregate receipts could include an exact digest. They remain
            # readable but cannot certify an ordinary candidate from this run.
            assert ledger["limit"] == 366
            ledger["receipt"] = {
                "cp_used": receipt["cp_used"],
                "native_reserved": receipt["native_reserved"],
                "calls": receipt["calls"],
                "answer_sha256": hashlib.sha256(expected.content).hexdigest(),
            }
            assert not tx.completed_answer(
                RunReference(run["run_id"], "repair"), job.cache_key, expected.content, opened.queue
            )
    changed = {**bundle, "program": {**program, "max_total_cost_tenths": 6}}
    refused = off.post(route, json={**request, "preference_bundle": changed})
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "LLMOPT_VNEXT_DISABLED"
    assert len(closed.queue.jobs()) == 2


@pytest.mark.parametrize("enabled", [False, True])
def test_bundle_capability_follows_release_on_league_and_public_routes(
    tmp_path, monkeypatch, enabled
):
    backend = world._deployment(tmp_path, monkeypatch, public_entries=True, llmopt_vnext=enabled)[
        "backend"
    ]
    client = TestClient(app_for_capture(backend, world.world_module.GW2_CAPTURED_AT))
    for route in (
        f"/api/v1/leagues/{world.LEAGUE_ID}/capabilities",
        f"/api/v1/public/leagues/{world.LEAGUE_ID}/entries/{world.ENTRY_ID}/capabilities",
    ):
        response = client.get(route)
        assert response.status_code == 200, response.text
        state = response.json()
        if enabled:
            assert state["llmopt_vnext"] is True
            assert state["preference_bundles"] == {"version": BUNDLE_VERSION}
            assert state["plan_data_id"] == backend.reader.plan_data_id()
            assert state["verified_repairs"] is True
        else:
            assert "llmopt_vnext" not in state and "preference_bundles" not in state
            assert "plan_data_id" not in state
            assert "verified_repairs" not in state


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


def test_every_admitted_bundle_fits_the_result_query(tmp_path, monkeypatch):
    backend, client, route, body, run, held = _started(tmp_path, monkeypatch)
    rules = [{"keep_players": [held[0]]}, {"avoid_players": [held[1]]}]
    prices = [{"outcome": slot, "ceiling": ceiling} for slot in range(2) for ceiling in range(4)]
    choices = []
    # Four distinct ceilings per price produce five possible acceptance masks per slot.
    masks = [0, 0b1000, 0b1100, 0b1110, 0b1111]
    for first in masks:
        for second in masks:
            accepted = first | second << 4
            patch = {**(rules[0] if first else {}), **(rules[1] if second else {})}
            choices.append(
                {
                    "accepted": accepted,
                    "applied": [i for i in range(len(prices)) if accepted & (1 << i)],
                    "selection": {"preferences": patch, "chip": None} if patch else None,
                }
            )
    bundle = {
        "contract_version": BUNDLE_VERSION,
        "slots": [{"preferences": rule, "chip": None} for rule in rules],
        "prices": prices,
        "choices": choices,
        "program": None,
    }
    encoded = json.dumps(bundle, separators=(",", ":"))
    request = json.dumps({**body, "run": run, "preference_bundle": bundle}, separators=(",", ":"))
    assert 3000 < len(encoded) < len(request.encode()) <= 4096
    accepted = client.post(route, content=request, headers={"Content-Type": "application/json"})
    assert accepted.status_code == 202, accepted.text
    assert world._work(backend) == 1
    hit = client.post(route, content=request, headers={"Content-Type": "application/json"})
    assert hit.status_code == 200, hit.text
    params = {**body, "preferences": json.dumps(body["preferences"]), "preference_bundle": encoded}
    read = client.get(route, params=params)
    assert read.status_code == 200, read.text
    assert read.content == hit.content
    assert (
        client.get(route, params={**params, "preference_bundle": encoded.ljust(4097)}).status_code
        == 422
    )
    assert len(backend.queue.jobs()) == 2


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
