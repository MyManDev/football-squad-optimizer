"""Model identity survives the real API/queue/worker/planner path at every member window."""

import json
from dataclasses import replace

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from tests.fixtures.backend_app import app_for_capture
from tests.unit.test_advice_worker import ENTRY_ID, LEAGUE_ID, _deployment, world_module
from tests.unit.test_api_advice_switches import COUNTS
from tests.unit.test_football_development import football_fixture  # noqa: F401
from tests.unit.test_member_windows import _web_literal

from squadopt.application.football_live import causal_training
from squadopt.application.strategies.catalog import FORBIDDEN_TEXT_PATTERN
from squadopt.data.sources.football_history import normalize_history
from squadopt.live.football_artifact import (
    ARTIFACT_CONTRACT,
    SHARES_BEFORE_AVAILABILITY_LIMIT,
    football_artifact_path,
    forecast_digest,
    read_football_forecast,
)
from squadopt.platform.advice_queue import run_advice_worker_once
from squadopt.platform.advice_switches import AdviceSwitchInputs
from squadopt.platform.advice_worker import build_advice_compute
from squadopt.platform.api_contract import ApiCommandRequest
from squadopt.prediction.football import FOOTBALL_MODEL_VERSION
from squadopt.prediction.football_contextual import CONTEXTUAL_MODEL_VERSION
from squadopt.prediction.football_features import BASE_FEATURES


def test_live_training_does_not_use_same_week_or_later_labels(football_fixture):  # noqa: F811
    history = football_fixture[1]
    before = causal_training(history)
    poisoned = history.copy()
    poisoned.loc[poisoned.GW.ge(10), ["goals_scored", "expected_goals", "total_points"]] = 999
    after = causal_training(poisoned)
    pd.testing.assert_frame_equal(
        before.loc[before.GW.le(10), list(BASE_FEATURES)],
        after.loc[after.GW.le(10), list(BASE_FEATURES)],
    )
    with pytest.raises(ValueError):
        normalize_history(history.assign(expected_goals=float("inf")))
    with pytest.raises(ValueError):
        normalize_history(history.assign(expected_assists=-1))


def _forecast(inputs, *, contextual=False):
    frames = []
    for week in range(2, 7):
        table = inputs.players.copy()
        table["gameweek"] = week
        table["expected_points"] = 2.0 + week / 10 + table.player_id.mod(4)
        table["appearance_probability"] = 0.8
        table["fixture_count"] = 1
        table["home_fixture_count"] = 0
        frames.append(table)
    result = {
        "contract_version": ARTIFACT_CONTRACT,
        "model_version": FOOTBALL_MODEL_VERSION,
        "season": inputs.season,
        "gameweek": 2,
        "source_snapshot_id": inputs.snapshot_id,
        "captured_at_utc": inputs.captured_at_utc,
        "rows": pd.concat(frames).to_dict("records"),
    }
    if contextual:
        result.update(
            model_version=CONTEXTUAL_MODEL_VERSION,
            availability_application="before_team_shares_v1",
            projection_contract="projection_horizon_appearance_v2",
        )
    result["fingerprint"] = forecast_digest(result)
    return result


@pytest.mark.parametrize("window", [1, 3, 5])
@pytest.mark.parametrize("weight", [0, 20])
@pytest.mark.parametrize("contextual", [False, True])
def test_football_api_worker_windows_and_top100(tmp_path, monkeypatch, window, weight, contextual):
    artifacts = tmp_path / "artifacts"
    world = _deployment(tmp_path, monkeypatch, artifact_root=artifacts)
    backend = world["backend"]
    identity = backend.contexts.identity()
    path = football_artifact_path(artifacts, world["snapshot_id"])
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(_forecast(identity.inputs, contextual=contextual)))
    football = read_football_forecast(path, identity.inputs)
    capture = backend.contexts.capture(identity.context)
    capture = replace(capture, switches=AdviceSwitchInputs(football=football, top100_counts=COUNTS))
    monkeypatch.setattr(
        backend.contexts,
        "capture",
        lambda context: capture if context == identity.context else None,
    )
    client = TestClient(app_for_capture(backend, world_module.GW2_CAPTURED_AT))
    capabilities = client.get(f"/api/v1/leagues/{LEAGUE_ID}/capabilities")
    assert capabilities.json()["models"] == ["current", "football"]
    route = f"/api/v1/leagues/{LEAGUE_ID}/entries/{ENTRY_ID}/advice"
    body = {"strategy": "saf-puan", "window": window, "model": "football", "top100_weight": weight}
    accepted = client.post(route, json=body)
    assert accepted.status_code == 202, accepted.text
    job = run_advice_worker_once(
        backend.queue,
        backend.cache,
        build_advice_compute(backend.contexts, backend.job_specs, cache=backend.cache),
        at_utc="2026-09-01T10:01:00Z",
    )
    assert job.status == "completed", job.error
    served = client.get(route, params=body)
    assert served.status_code == 200, served.text
    result = served.json()["payload"]
    assert result["prediction_model"]["fingerprint"] == football.fingerprint
    assert result["prediction_model"]["version"] == (
        CONTEXTUAL_MODEL_VERSION if contextual else FOOTBALL_MODEL_VERSION
    )
    if contextual:
        assert football.horizon.table.appearance_probability.eq(0.8).all()
    # v1 splits goal and assist shares before availability and says so on every answer it
    # decides, one week or a window; v3 applies availability first and must not say it.
    assert result["stated_limits"].count(SHARES_BEFORE_AVAILABILITY_LIMIT) == (
        0 if contextual else 1
    )
    assert result["window"] == window
    assert result.get("top100", {}).get("weight", 0) == weight
    if window > 1:
        assert len(result["plan_weeks"]) == window
        assert not any("stays at zero" in s for s in result["stated_limits"])
    other = client.get(route, params={**body, "model": "current"})
    assert other.status_code == 404  # football must not fill current model's address


def test_the_site_holds_the_share_limit_verbatim_and_it_passes_the_honesty_guard() -> None:
    """The page translates a limit by exact lookup, so the producer and the site must agree.

    The sentence states a mechanism and no number: no committed measurement sizes the loss.
    """

    assert _web_literal("FOOTBALL_SHARE_STATED_LIMIT") == SHARES_BEFORE_AVAILABILITY_LIMIT
    assert not FORBIDDEN_TEXT_PATTERN.search(SHARES_BEFORE_AVAILABILITY_LIMIT)
    assert not any(character.isdigit() for character in SHARES_BEFORE_AVAILABILITY_LIMIT)


def test_football_missing_and_unknown_refused_before_queue(tmp_path, monkeypatch):
    world = _deployment(tmp_path, monkeypatch)
    client = TestClient(app_for_capture(world["backend"], world_module.GW2_CAPTURED_AT))
    route = f"/api/v1/leagues/{LEAGUE_ID}/entries/{ENTRY_ID}/advice"
    for model, code in [("football", "MODEL_INPUTS_UNAVAILABLE"), ("unknown", "VALIDATION_FAILED")]:
        for method in ("get", "post"):
            body = {"strategy": "saf-puan", "window": 3, "model": model}
            response = (
                client.post(route, json=body)
                if method == "post"
                else client.get(route, params=body)
            )
            assert response.status_code == 422, response.text
            assert response.json()["error"]["code"] == code
    assert world["backend"].queue.jobs() == ()


def test_model_request_identity_roundtrip():
    fields = dict(
        operation="league.advise",
        idempotency_key="test-model",
        season="2026-27",
        gameweek=5,
        league_id=1,
        entry_id=2,
        strategy="saf-puan",
        window=5,
        capture_snapshot_id="test-capture",
    )
    old = ApiCommandRequest(**fields)
    new = ApiCommandRequest(**fields, model="football")
    assert new.request_fingerprint != old.request_fingerprint
    assert ApiCommandRequest.from_dict(new.to_dict()) == new
    assert "model" not in old.to_dict()


def test_forecast_hash_capture_roster_and_blank_guards(tmp_path, monkeypatch):
    world = _deployment(tmp_path, monkeypatch)
    inputs = world["backend"].contexts.identity().inputs
    doc = _forecast(inputs)
    path = tmp_path / "forecast.json"
    path.write_text(json.dumps(doc))
    loaded = read_football_forecast(path, inputs)
    assert len(loaded.build_horizon((2, 3, 4)).table) == 3 * len(inputs.players)
    with pytest.raises(ValueError):
        loaded.build_horizon((6, 7))
    for field, value in [("source_snapshot_id", "other"), ("model_version", "other")]:
        altered = {**doc, field: value}
        altered["fingerprint"] = forecast_digest(altered)
        path.write_text(json.dumps(altered))
        with pytest.raises(ValueError):
            read_football_forecast(path, inputs)
    doc["rows"][0]["expected_points"] += 1
    path.write_text(json.dumps(doc))
    with pytest.raises(ValueError, match="fingerprint"):
        read_football_forecast(path, inputs)
