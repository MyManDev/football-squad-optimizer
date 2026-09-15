"""Personal weights replace the published uplift and remain part of request identity."""

import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import pytest
import tests.unit.test_advice_worker as worker_fixture
import tests.unit.test_backend_runtime as deployment_fixture
import tests.unit.test_elite_evidence as evidence_fixture
from fastapi.testclient import TestClient

from squadopt.api.runtime import app_for_backend
from squadopt.application.top100_weight import Top100InputsUnavailable, weighted_member_inputs
from squadopt.data.errors import DataSourceError
from squadopt.live.recommendation import read_projection_handoff, write_projection_handoff
from squadopt.platform.advice_documents import AdviceDocumentError, validate_advice_document
from squadopt.platform.advice_queue import run_advice_worker_once
from squadopt.platform.advice_worker import build_advice_compute
from squadopt.platform.backend_runtime import BackendConfig, build_backend
from squadopt.prediction.elite_evidence import (
    ELITE_EVIDENCE_FEATURE_CONTRACT_VERSION,
    ELITE_EVIDENCE_MODEL_VERSION,
    TOP100_WEIGHT_PERCENTAGES,
    apply_elite_evidence,
    validate_top100_weight,
)


def evidence_handoff(root: Path, snapshot_id: str) -> Path:
    path = deployment_fixture._handoff(root, snapshot_id)
    original = read_projection_handoff(path)
    counts = {
        code: 100 if code in worker_fixture.STARTING_ELEVEN else 0
        for code in original.expected_points
    }
    return write_projection_handoff(
        path,
        replace(
            original,
            model_version=ELITE_EVIDENCE_MODEL_VERSION,
            feature_contract_version=ELITE_EVIDENCE_FEATURE_CONTRACT_VERSION,
            evidence_fingerprint="a" * 64,
            elite_start_counts=counts,
            expected_points={
                p: points * (1 + 0.05 * counts[p] / 100)
                for p, points in original.expected_points.items()
            },
        ),
    )


@pytest.fixture
def backend(tmp_path, monkeypatch):
    monkeypatch.setenv("SQUADOPT_REPOSITORY_COMMIT", "c" * 40)
    config = BackendConfig(
        store_root=tmp_path / "store",
        site_data_root=tmp_path / "site",
        snapshot_root=tmp_path / "snapshots",
        handoff_root=tmp_path / "handoffs",
    )
    config.store_root.mkdir()
    snapshot_id = worker_fixture._capture_with_entries(config.snapshot_root, multiweek=True)
    evidence_handoff(config.handoff_root, snapshot_id)
    deployment_fixture._publish_members(config.site_data_root, worker_fixture.RIVAL_ID)
    return build_backend(config)


@pytest.mark.parametrize("weight", TOP100_WEIGHT_PERCENTAGES)
def test_every_weight_scales_support_without_mutating_the_input(weight):
    projection = evidence_fixture._projection()
    result = apply_elite_evidence(
        projection,
        evidence_fixture._evidence(),
        season=evidence_fixture.SEASON,
        target_gameweek=evidence_fixture.GAMEWEEK,
        deadline_timestamp_utc=evidence_fixture.DEADLINE,
        decision_captured_at_utc=evidence_fixture.DECISION_CAPTURED_AT,
        top100_weight_percent=weight,
    )
    assert result.table.expected_points.tolist() == pytest.approx(
        [4, *([5 * (1 + weight / 100)] * 11)]
    )
    assert result.diagnostics["elite_evidence_players_uplifted"] == (11 if weight else 0)
    pd.testing.assert_frame_equal(projection, evidence_fixture._projection())


@pytest.mark.parametrize("weight", TOP100_WEIGHT_PERCENTAGES)
def test_same_weight_replaces_uplift_in_every_horizon_week(backend, weight):
    capture = backend.contexts.capture(backend.contexts.current())
    projection = capture.projection
    adjusted, horizon = weighted_member_inputs(
        projection,
        capture.horizon_builder,
        source_weight=5,
        requested_weight=weight,
        counts=capture.elite_start_counts,
    )
    support = projection.table.player_id.map(capture.elite_start_counts) / 100
    expected = (
        projection.table.expected_points * (1 + weight / 100 * support) / (1 + 0.05 * support)
    )
    assert adjusted.table.expected_points.tolist() == pytest.approx(expected.tolist())
    old = capture.horizon_builder((2, 3, 4, 5, 6)).table
    new = horizon((2, 3, 4, 5, 6)).table
    shares = old.player_id.map(capture.elite_start_counts) / 100
    assert new.expected_points.tolist() == pytest.approx(
        (old.expected_points * (1 + weight / 100 * shares) / (1 + 0.05 * shares)).tolist()
    )
    assert new.loc[old.expected_points.eq(0), "expected_points"].eq(0).all()


@pytest.mark.parametrize("weight", TOP100_WEIGHT_PERCENTAGES)
def test_api_job_worker_and_cache_keep_the_selected_weight(backend, weight):
    client = TestClient(app_for_backend(backend))
    route = f"/api/v1/leagues/{worker_fixture.LEAGUE_ID}/entries/{worker_fixture.ENTRY_ID}/advice"
    body = {"strategy": "saf-puan", "window": 1, "top100_weight_percent": weight}
    first = client.post(route, json=body)
    assert first.status_code == 202, first.text
    assert client.post(route, json=body).json() == first.json()
    job = run_advice_worker_once(
        backend.queue,
        backend.cache,
        build_advice_compute(backend.contexts, backend.job_specs),
        at_utc=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    assert job.status == "completed", job.error
    spec = backend.job_specs.get(job.cache_key)
    assert spec.top100_weight_percent == weight
    assert type(spec).from_payload(spec.as_payload()) == spec
    served = client.get(route, params=body)
    assert served.status_code == 200, served.text
    assert served.json()["payload"]["top100_weight_percent"] == weight
    assert served.json()["payload"]["top100_weight_source"] == "personal"
    payload = served.json()["payload"]
    price = payload["top100_price"]
    assert not any(key.startswith("_top100") for key in payload)
    assert price["expected_points_cost"] == pytest.approx(
        max(0, price["reference_net_points"] - price["selected_net_points"])
    )
    assert price["expected_points_cost_ceiling"] >= price["expected_points_cost"] >= 0
    if weight == 0:
        assert price["expected_points_cost_ceiling"] == 0
    for missing in ("top100_price", "expected_points_cost_ceiling"):
        damaged_price = json.loads(served.content)
        if missing == "top100_price":
            del damaged_price["payload"][missing]
        else:
            del damaged_price["payload"]["top100_price"][missing]
        with pytest.raises(AdviceDocumentError):
            validate_advice_document(json.dumps(damaged_price).encode())
    assert client.post(route, json=body).content == served.content
    assert client.get(route, params={"strategy": "saf-puan", "window": 1}).status_code == 404
    for other in TOP100_WEIGHT_PERCENTAGES:
        if other != weight:
            assert (
                client.get(route, params={**body, "top100_weight_percent": other}).status_code
                == 404
            )
    damaged = served.json()
    del damaged["payload"]["top100_weight_source"]
    with pytest.raises(AdviceDocumentError):
        validate_advice_document(json.dumps(damaged).encode())


@pytest.mark.parametrize("invalid", [-5, 1, 15, 60, True, "20", 20.0])
def test_bad_weights_are_refused_before_queueing(backend, invalid):
    with pytest.raises(ValueError):
        validate_top100_weight(invalid)
    client = TestClient(app_for_backend(backend))
    route = f"/api/v1/leagues/{worker_fixture.LEAGUE_ID}/entries/{worker_fixture.ENTRY_ID}/advice"
    assert (
        client.post(
            route, json={"strategy": "saf-puan", "window": 1, "top100_weight_percent": invalid}
        ).status_code
        == 422
    )
    assert backend.queue.jobs() == ()


def test_missing_counts_cannot_be_guessed(backend):
    capture = backend.contexts.capture(backend.contexts.current())
    with pytest.raises(Top100InputsUnavailable):
        weighted_member_inputs(
            capture.projection,
            capture.horizon_builder,
            source_weight=5,
            requested_weight=50,
            counts=None,
        )
    # The published setting remains usable without reweighting. An explicit personal
    # setting, even the same number, needs counts to undo the uplift and price it.
    with pytest.raises(Top100InputsUnavailable):
        weighted_member_inputs(
            capture.projection,
            capture.horizon_builder,
            source_weight=5,
            requested_weight=5,
            counts=None,
        )


@pytest.mark.parametrize("damage", ["count", "fingerprint", "shape", "boolean"])
def test_counts_are_verified_by_the_handoff_fingerprint(tmp_path, damage):
    path = evidence_handoff(tmp_path, "fpl-live-synthetic")
    original = read_projection_handoff(path)
    assert original.elite_start_counts is not None
    document = json.loads(path.read_text())
    if damage == "count":
        document["elite_start_counts"]["1001"] = 99
    elif damage == "fingerprint":
        del document["fingerprint"]
    elif damage == "shape":
        document["elite_start_counts"] = []
    else:
        document["elite_start_counts"]["1001"] = True
    path.write_text(json.dumps(document))
    with pytest.raises(DataSourceError):
        read_projection_handoff(path)


@pytest.mark.parametrize(
    "weight,expected_status", [(None, "completed"), (0, "completed"), (20, "failed")]
)
def test_an_old_plain_handoff_never_claims_top100_influence(backend, weight, expected_status):
    context = backend.contexts.current()
    deployment_fixture._handoff(backend.config.handoff_root, context.capture_snapshot_id)
    fresh = build_backend(backend.config)
    client = TestClient(app_for_backend(fresh))
    route = f"/api/v1/leagues/{worker_fixture.LEAGUE_ID}/entries/{worker_fixture.ENTRY_ID}/advice"
    body = {"strategy": "saf-puan", "window": 1, "top100_weight_percent": weight}
    accepted = client.post(route, json=body)
    assert accepted.status_code == 202, accepted.text
    job = run_advice_worker_once(
        fresh.queue,
        fresh.cache,
        build_advice_compute(fresh.contexts, fresh.job_specs),
        at_utc=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    assert job.status == expected_status, job.error
    if weight == 20:
        assert job.error.code == "TOP100_INPUTS_UNAVAILABLE"
        assert fresh.cache.get(job.cache_key) is None
    else:
        payload = json.loads(fresh.cache.get(job.cache_key))["payload"]
        assert payload["top100_weight_percent"] == 0
        assert payload["top100_weight_source"] == ("published" if weight is None else "personal")


def test_partial_support_scales_the_selected_maximum():
    evidence = evidence_fixture._evidence()
    evidence.loc[0, ["elite_start_count_lag1", "elite_start_share_lag1"]] = [40, 0.4]
    evidence.loc[1, ["elite_start_count_lag1", "elite_start_share_lag1"]] = [60, 0.6]
    result = apply_elite_evidence(
        evidence_fixture._projection(),
        evidence,
        season=evidence_fixture.SEASON,
        target_gameweek=evidence_fixture.GAMEWEEK,
        deadline_timestamp_utc=evidence_fixture.DEADLINE,
        decision_captured_at_utc=evidence_fixture.DECISION_CAPTURED_AT,
        top100_weight_percent=50,
    )
    assert result.table.expected_points.iloc[:2].tolist() == pytest.approx([4 * 1.2, 5 * 1.3])


@pytest.mark.parametrize("window", [3, 5])
def test_long_window_price_covers_the_whole_plan_and_has_a_ceiling(backend, window):
    client = TestClient(app_for_backend(backend))
    route = f"/api/v1/leagues/{worker_fixture.LEAGUE_ID}/entries/{worker_fixture.ENTRY_ID}/advice"
    body = {"strategy": "saf-puan", "window": window, "top100_weight_percent": 20}
    assert client.post(route, json=body).status_code == 202
    job = run_advice_worker_once(
        backend.queue,
        backend.cache,
        build_advice_compute(backend.contexts, backend.job_specs),
        at_utc=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    assert job.status == "completed", job.error
    payload = client.get(route, params=body).json()["payload"]
    assert len(payload["plan_weeks"]) == window
    price = payload["top100_price"]
    assert price["expected_points_cost_ceiling"] >= price["expected_points_cost"] >= 0
    assert (
        price["selected_net_points"]
        <= sum(
            week["expected_points"] - week["transfer_hit_points"] for week in payload["plan_weeks"]
        )
        + 1e-8
    )
    assert price["reference_solver_status"] in ("OPTIMAL", "FEASIBLE")
