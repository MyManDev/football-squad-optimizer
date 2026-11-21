"""Named-chip work preserves capacity for the requested model, not auxiliary seeds."""

import json
import math
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from tests.fixtures.backend_app import app_for_capture, confirmed_request
from tests.unit import test_advice_worker as world

from squadopt.platform.advice_queue import run_advice_worker_once
from squadopt.platform.advice_worker import build_advice_compute


def _cold_worker_answer(backend, body):
    client = TestClient(app_for_capture(backend, world.world_module.GW2_CAPTURED_AT))
    route = f"/api/v1/leagues/{world.LEAGUE_ID}/entries/{world.ENTRY_ID}/advice"
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
    return job, backend.cache.get(job.cache_key)


@pytest.mark.parametrize("chip", ["wildcard", "freehit"])
def test_named_chip_auxiliary_work_cannot_displace_the_admitted_main_search(
    tmp_path, monkeypatch, chip
):
    body = {
        "strategy": "saf-puan",
        "window": 3,
        "chip": chip,
        "preferences": {
            "net_points_priority": True,
            "include_players": [1007],
            "no_hits": True,
        },
    }
    backend = world._deployment(tmp_path / "run", monkeypatch, last_gameweek=5, llmopt_vnext=True)[
        "backend"
    ]
    job, bound_answer = _cold_worker_answer(backend, confirmed_request(body))
    assert job.contract_version == "backend_jobs_v2"
    ledger = json.loads(backend.runs.path.read_bytes())
    allocation = ledger["jobs"][job.job_id]
    receipt = allocation["receipt"]
    assert receipt["cp_used"] + receipt["native_reserved"] <= allocation["limit"] == 122
    payload = json.loads(bound_answer)["payload"]
    assert payload["plan_weeks"][0]["chip"] == chip
    for week in payload["plan_weeks"]:
        assert week["transfer_hit_points"] == 0
        assert week["bank_after_tenths"] >= 0
        ids = {row["player_id"] for row in week["lineup"]["starting_xi"] + week["lineup"]["bench"]}
        assert 1007 in ids

    legacy = world._deployment(tmp_path / "legacy", monkeypatch, last_gameweek=5)["backend"]
    original, legacy_answer = _cold_worker_answer(legacy, body)
    assert original.contract_version == "backend_jobs_v1"
    assert original.cache_key == job.cache_key
    assert legacy.job_specs.get(original.cache_key) == backend.job_specs.get(job.cache_key)
    previous = json.loads(legacy_answer)["payload"]
    assert payload["solver_status"] == previous["solver_status"]
    assert len(payload["plan_weeks"]) == len(previous["plan_weeks"]) == body["window"]
    for actual, expected in zip(payload["plan_weeks"], previous["plan_weeks"], strict=True):
        for key in ("gameweek", "chip", "transfer_hit_points", "expected_points"):
            assert actual[key] == expected[key], key
        for key in ("transfers_in", "transfers_out"):
            assert sorted(player["player_id"] for player in actual[key]) == sorted(
                player["player_id"] for player in expected[key]
            ), key


def test_shared_named_chip_answers_match_on_every_frozen_control():
    research = Path(__file__).resolve().parents[2] / "docs" / "research"
    baseline = json.loads((research / "llmopt_phase1_baseline.json").read_bytes())
    controls = {
        (row["case"], int(window)): row["scenario"]
        for row in baseline["rows"]
        if row["scenario"] in {"wildcard", "freehit"}
        for window in row["windows"]
    }
    assert len(controls) == 16
    record = json.loads((research / "llmopt_phase2_named_chip.json").read_bytes())
    rows = record["rows"]
    assert len(rows) == len(controls)
    assert {(row["case"], row["window"]): row["scenario"] for row in rows} == controls
    frozen = {row["case"]: row["windows"] for row in baseline["rows"]}

    for row in rows:
        case = (row["case"], row["window"])
        gameweek, entry = row["case"].removeprefix("gw").split("-")
        assert row["entry_id"] == int(entry), case
        assert row["request"]["window"] == row["window"], case
        assert row["request"]["chip"] == row["scenario"], case
        assert row["request"]["preferences"]["net_points_priority"] is True, case
        assert not row["request"]["preferences"].get("save_chips", False), case
        assert "run" not in row["request"], case
        reference = frozen[row["case"]][str(row["window"])]["control"]
        for key in ("solver_status", "objective", "decision_sha256"):
            assert row["frozen_control"][key] == reference[key], (case, key)
        bound, legacy = row["run_bound"], row["legacy"]
        assert bound["contract_version"] == "backend_jobs_v2", case
        assert legacy["contract_version"] == "backend_jobs_v1", case
        assert bound["allocation"] == {1: 21, 3: 122}[row["window"]], case
        assert legacy["allocation"] is None and legacy["receipt"] is None, case
        for arm in (bound, legacy):
            assert arm["api_status"] == 202 and arm["job_status"] == "completed", (case, arm)
            assert arm["named_chip_calls"] and arm["solver_calls"], case
            assert all(
                call["run_allocation_active"] == (arm is bound) for call in arm["named_chip_calls"]
            ), case
            for call in arm["solver_calls"]:
                assert call["backend"] in {"cp-sat", "highs-native"}, case
                if call["backend"] == "cp-sat":
                    assert (
                        math.isfinite(call["deterministic_units"])
                        and call["deterministic_units"] >= 0
                    ), case
                else:
                    assert (
                        math.isfinite(call["wall_cap_seconds"]) and call["wall_cap_seconds"] > 0
                    ), case
            assert arm["solver_status"] in {"OPTIMAL", "FEASIBLE"}, case
            assert math.isfinite(arm["objective"]), case
            assert arm["objective"] == arm["named_chip_calls"][-1]["objective"], case
            assert math.isfinite(arm["published_net_points"]), case
            assert [week["gameweek"] for week in arm["transfers"]] == list(
                range(int(gameweek), int(gameweek) + row["window"])
            ), case
            assert arm["transfers"][0]["chip"] == row["scenario"], case
            for key in ("cache_key", "spec_sha256", "payload_sha256"):
                assert len(bytes.fromhex(arm[key])) == 32, (case, key)
        receipt = bound["receipt"]
        assert receipt["calls"] > 0, case
        assert 0 < receipt["cp_used"] + receipt["native_reserved"] <= bound["allocation"], case
        native_units = sum(
            math.ceil(call["wall_cap_seconds"] / 30)
            for call in bound["solver_calls"]
            if call["backend"] == "highs-native"
        )
        assert native_units == receipt["native_reserved"], case
        for key in (
            "cache_key",
            "spec_sha256",
            "solver_status",
            "objective",
            "published_net_points",
            "transfers",
        ):
            assert bound[key] == legacy[key], (case, key, bound[key], legacy[key])
