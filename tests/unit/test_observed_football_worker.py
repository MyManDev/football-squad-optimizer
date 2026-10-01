"""Conditional information travels through the actual HTTP, worker and cache boundary."""

import json
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient
from tests.fixtures.backend_app import app_for_capture
from tests.unit.test_advice_worker import ENTRY_ID, LEAGUE_ID, _deployment, world_module
from tests.unit.test_api_advice_switches import COUNTS
from tests.unit.test_live_football_model import _forecast

from squadopt.live.football_artifact import football_artifact_path, read_football_forecast
from squadopt.planning.observed import OBSERVED_WINDOW_VERSION
from squadopt.platform.advice_queue import run_advice_worker_once
from squadopt.platform.advice_switches import AdviceSwitchInputs, switch_identity
from squadopt.platform.advice_worker import build_advice_compute


@pytest.mark.parametrize("window,weight", [(3, 0), (5, 20)])
def test_observed_worker_preserves_member_choices(tmp_path, monkeypatch, window, weight):
    artifacts = tmp_path / "artifacts"
    world = _deployment(tmp_path, monkeypatch, artifact_root=artifacts)
    backend = world["backend"]
    identity = backend.contexts.identity()
    availability = identity.inputs.availability.copy()
    assert availability.player_id.eq(1004).any()
    availability.loc[availability.player_id.eq(1004), "chance_of_playing"] = 50
    inputs = replace(identity.inputs, availability=availability)
    path = football_artifact_path(artifacts, world["snapshot_id"])
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(_forecast(inputs)), encoding="utf-8")
    football = read_football_forecast(path, inputs)
    switches = AdviceSwitchInputs(football=football, top100_counts=COUNTS)
    capture = replace(backend.contexts.capture(identity.context), inputs=inputs, switches=switches)
    monkeypatch.setattr(
        backend.contexts,
        "capture",
        lambda context: capture if context == identity.context else None,
    )
    key = switch_identity(switches, model="football")
    assert key["model"]["planner_version"] == OBSERVED_WINDOW_VERSION
    assert switch_identity(switches, model="current") == {}
    client = TestClient(app_for_capture(backend, world_module.GW2_CAPTURED_AT))
    route = f"/api/v1/leagues/{LEAGUE_ID}/entries/{ENTRY_ID}/advice"
    preferences = {
        "keep_players": [1001, 1004],
        "avoid_players": [1007],
        "no_hits": True,
        "save_chips": True,
    }
    body = {
        "strategy": "saf-puan",
        "window": window,
        "model": "football",
        "top100_weight": weight,
        "preferences": preferences,
    }
    accepted = client.post(route, json=body)
    assert accepted.status_code == 202, accepted.text
    job = run_advice_worker_once(
        backend.queue,
        backend.cache,
        build_advice_compute(backend.contexts, backend.job_specs, cache=backend.cache),
        at_utc="2026-09-01T10:01:00Z",
    )
    assert job.status == "completed", job.error
    served = client.get(route, params={**body, "preferences": json.dumps(preferences)})
    assert served.status_code == 200, served.text
    result = served.json()["payload"]
    assert result["window"] == window
    assert result.get("selection_top100_weight", 0) == weight
    assert result["preferences"] == preferences
    assert {1001, 1004} <= {p["player_id"] for p in result["starting_xi"] + result["bench"]}
    review = result["information_review"]
    assert review["status"] == "compared", review["reason"]
    assert review["source_playing_chance_percent"] == 50
    assert review["source_snapshot_id"] == world["snapshot_id"]
    assert review["information_gameweek"] == 3
    assert result["solver_status"] == "FEASIBLE"
    assert len(result["plan_weeks"]) == window
    assert any(c["selected"] for c in review["candidates"])
    for candidate in review["candidates"]:
        assert candidate["chip"] is None
        assert candidate["expected_net_points"] is not None
        assert {b["state"] for b in candidate["branches"]} == {"eligible", "unavailable"}
        for branch in candidate["branches"]:
            assert branch["hit_points"] == 0
            assert len(branch["weeks"]) == window - 1
            assert all(w["chip"] is None and w["bank_tenths"] >= 0 for w in branch["weeks"])
            assert all(review["player_name"] not in w["transfers_out"] for w in branch["weeks"])
            assert all("Player 1007" not in w["transfers_in"] for w in branch["weeks"])
    assert (
        client.get(
            route, params={**body, "preferences": json.dumps(preferences), "model": "current"}
        ).status_code
        == 404
    )
