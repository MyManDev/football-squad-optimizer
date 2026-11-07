"""An uncaptured team is computed only on request, through the real durable worker."""

import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime
from unittest.mock import Mock

import jsonschema
import pytest
from fastapi.testclient import TestClient
from tests.fixtures.backend_app import app_for_capture
from tests.unit import test_advice_worker as worker_tests

from squadopt.api.runtime import app_for_backend
from squadopt.platform.advice_documents import league_capabilities_schema
from squadopt.platform.advice_queue import run_advice_worker_once
from squadopt.platform.advice_read import AdviceBackendNotReadyError
from squadopt.platform.advice_submit import FixedWindowRateLimiter
from squadopt.platform.advice_worker import build_advice_compute
from squadopt.platform.public_entry_inputs import MAX_BUNDLE_BYTES

ENTRY = 987654
BODY = {"strategy": "saf-puan", "window": 1}


def bundle(entry_id=ENTRY, gameweek=2):
    held = worker_tests._entry_payloads(entry_id, gameweek - 1)
    picks = json.loads(held[f"entry-{entry_id}-picks-gw{gameweek - 1:02d}.json"])
    picks["entry_history"]["event"] = gameweek - 1
    return {
        "contract_version": "fpl_entry_bundle_v1",
        "entry_id": entry_id,
        "gameweek": gameweek,
        "entry": {"id": entry_id},
        "history": json.loads(held[f"entry-{entry_id}-history.json"]),
        "transfers": [],
        "picks": [picks],
    }


@pytest.fixture
def public(tmp_path, monkeypatch):
    world = worker_tests._deployment(tmp_path, monkeypatch, public_entries=True)
    backend = world["backend"]
    fetch = Mock(side_effect=lambda entry, week: json.dumps(bundle(entry, week)).encode())
    monkeypatch.setattr(backend.public_inputs, "_fetch", fetch)
    client = TestClient(app_for_capture(backend, worker_tests.world_module.GW2_CAPTURED_AT))
    return backend, client, fetch


@pytest.mark.parametrize("league", [239, 0])
def test_public_team_get_does_no_work_post_deduplicates_and_worker_answers(public, league):
    backend, client, fetch = public
    route = f"/api/v1/public/leagues/{league}/entries/{ENTRY}/advice"
    context = backend.contexts.current()
    identity = backend.contexts.identity()
    before = dict(identity.snapshot.payloads)
    assert not backend.contexts.capture(context).provider.holds(ENTRY, 1)
    assert client.get(route, params=BODY).status_code == 404
    fetch.assert_not_called()
    assert backend.queue_depth() == 0

    accepted = client.post(route, json=BODY, headers={"Idempotency-Key": "first"})
    assert accepted.status_code == 202, accepted.text
    again = client.post(route, json=BODY, headers={"Idempotency-Key": "second"})
    assert again.json()["job_id"] == accepted.json()["job_id"]
    fetch.assert_called_once_with(ENTRY, 2)
    assert backend.queue_depth() == 1

    completed = run_advice_worker_once(
        backend.queue,
        backend.cache,
        build_advice_compute(
            backend.contexts, backend.job_specs, public_inputs=backend.public_inputs
        ),
        at_utc=worker_tests.world_module.GW2_CAPTURED_AT,
    )
    assert completed.status == "completed", completed
    served = client.get(route, params=BODY)
    assert served.status_code == 200, served.text
    payload = served.json()["payload"]
    assert payload["entry_id"] == ENTRY
    assert payload["league_id"] == league
    assert payload["source_snapshot_id"] == context.capture_snapshot_id
    assert payload["solver_status"] in {"OPTIMAL", "FEASIBLE"}
    assert len(payload["starting_xi"]) == 11
    assert client.post(route, json=BODY).content == served.content
    assert len(backend.queue.jobs()) == 1
    fetch.assert_called_once()
    assert dict(identity.snapshot.payloads) == before
    assert not backend.contexts.capture(context).provider.holds(ENTRY, 1)


def test_public_input_preparation_is_shared_across_simultaneous_requests(public):
    backend, _, fetch = public
    context = backend.contexts.current()
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda _: backend.public_inputs.prepare(context, ENTRY), range(8)))
    fetch.assert_called_once()
    assert backend.public_inputs.fingerprint(context, ENTRY)
    assert backend.queue_depth() == 0


@pytest.mark.parametrize("defect", ["entry", "week", "missing_picks", "duplicate", "oversize"])
def test_untrusted_public_inputs_never_enter_the_queue(public, defect):
    backend, client, fetch = public
    value = bundle()
    if defect == "entry":
        value["entry"]["id"] += 1
    elif defect == "week":
        value["gameweek"] += 1
    elif defect == "missing_picks":
        value["picks"] = []
    elif defect == "duplicate":
        value["picks"] *= 2
    fetch.side_effect = None
    fetch.return_value = (
        b" " * (MAX_BUNDLE_BYTES + 1) if defect == "oversize" else json.dumps(value).encode()
    )
    response = client.post(f"/api/v1/public/leagues/239/entries/{ENTRY}/advice", json=BODY)
    assert response.status_code == 503, response.text
    assert backend.queue_depth() == 0
    assert backend.public_inputs.fingerprint(backend.contexts.current(), ENTRY) is None


def test_closed_week_refuses_before_fetching_public_inputs(public):
    backend, _, fetch = public
    client = TestClient(app_for_backend(backend, utc_now=lambda: datetime(2999, 1, 1, tzinfo=UTC)))
    response = client.post(f"/api/v1/public/leagues/239/entries/{ENTRY}/advice", json=BODY)
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "DEADLINE_PASSED"
    fetch.assert_not_called()
    assert backend.queue_depth() == 0


def test_full_queue_refuses_new_team_before_fetch_but_still_joins_existing_job(public):
    backend, client, fetch = public
    backend.public_submit._max_open_jobs = 1
    route = f"/api/v1/public/leagues/239/entries/{ENTRY}/advice"
    first = client.post(route, json=BODY)
    assert first.status_code == 202
    refused = client.post(f"/api/v1/public/leagues/239/entries/{ENTRY + 1}/advice", json=BODY)
    assert refused.status_code == 429, refused.text
    assert client.post(route, json=BODY).json()["job_id"] == first.json()["job_id"]
    fetch.assert_called_once()


def test_pinned_inputs_cannot_be_reused_under_a_changed_capture_or_fingerprint(public):
    backend, _, _ = public
    context = backend.contexts.current()
    inputs = backend.public_inputs
    inputs.prepare(context, ENTRY)
    assert (
        inputs.fingerprint(replace(context, capture_snapshot_id="another-capture"), ENTRY) is None
    )
    with pytest.raises(AdviceBackendNotReadyError):
        inputs.provider(context, ENTRY, "0" * 64, backend.contexts.identity().snapshot.payloads)


def test_normal_routes_still_require_a_real_league(public):
    _, client, fetch = public
    route = f"/api/v1/leagues/0/entries/{ENTRY}/advice"
    assert client.get(route, params=BODY).status_code == 422
    assert client.post(route, json=BODY).status_code == 422
    fetch.assert_not_called()


def test_public_routes_are_disabled_until_the_deployment_opts_in(tmp_path, monkeypatch):
    backend = worker_tests._deployment(tmp_path, monkeypatch)["backend"]
    client = TestClient(app_for_capture(backend, worker_tests.world_module.GW2_CAPTURED_AT))
    route = f"/api/v1/public/leagues/239/entries/{ENTRY}/advice"
    assert client.get(route, params=BODY).status_code == 503
    assert client.post(route, json=BODY).status_code == 503
    assert backend.queue_depth() == 0


def test_rate_limit_rejects_another_public_fetch_before_touching_upstream(public):
    backend, client, fetch = public
    backend.public_submit._limiter = FixedWindowRateLimiter(1, 60)
    route = f"/api/v1/public/leagues/239/entries/{ENTRY}/advice"
    assert client.post(route, json=BODY).status_code == 202
    refused = client.post(f"/api/v1/public/leagues/239/entries/{ENTRY + 1}/advice", json=BODY)
    assert refused.status_code == 429
    fetch.assert_called_once()


@pytest.mark.parametrize(
    ("selection", "code"),
    [
        ({"model": "football"}, "MODEL_INPUTS_UNAVAILABLE"),
        ({"top100_weight": 20}, "TOP100_INPUTS_UNAVAILABLE"),
        ({"managers_word": True}, "MANAGERS_WORD_UNAVAILABLE"),
        ({"strategy": "fark-yarat", "rival_entry_id": 1}, "UNSUPPORTED_ADVICE_REQUEST"),
        ({"window": 2}, "VALIDATION_FAILED"),
    ],
)
def test_a_selection_this_capture_cannot_answer_is_refused_before_any_fetch(
    public, selection, code
):
    """A switch without its input, a rival, or a window nobody computes: refused by name."""
    backend, client, fetch = public
    response = client.post(
        f"/api/v1/public/leagues/239/entries/{ENTRY}/advice", json={**BODY, **selection}
    )
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == code
    fetch.assert_not_called()
    assert backend.queue_depth() == 0


@pytest.mark.parametrize("selection", [{"chip": "bboost"}, {"preferences": {"keep_players": []}}])
def test_a_public_team_gets_every_switch_the_capture_has(public, selection):
    """The pure-points menu a league's member has: a held chip, the member's preferences."""
    backend, client, fetch = public
    route = f"/api/v1/public/leagues/239/entries/{ENTRY}/advice"
    accepted = client.post(route, json={**BODY, **selection})
    assert accepted.status_code == 202, accepted.text
    fetch.assert_called_once_with(ENTRY, 2)
    completed = run_advice_worker_once(
        backend.queue,
        backend.cache,
        build_advice_compute(
            backend.contexts, backend.job_specs, public_inputs=backend.public_inputs
        ),
        at_utc=worker_tests.world_module.GW2_CAPTURED_AT,
    )
    assert completed.status == "completed", completed
    served = client.get(
        route,
        params={
            **BODY,
            **{k: json.dumps(v) if isinstance(v, dict) else v for k, v in selection.items()},
        },
    )
    assert served.status_code == 200, served.text
    payload = served.json()["payload"]
    assert payload["entry_id"] == ENTRY
    if "chip" in selection:
        assert payload["chip_choice"]["chip"] == "bboost"


def test_a_public_team_is_planned_over_a_longer_window(public):
    """A three-week window is accepted and reaches the menu solve as a league member's does.

    The test world's calendar ends at gameweek 3, so the solve itself stops at the horizon
    it cannot build; the refusal names that, not the request.
    """
    backend, client, fetch = public
    route = f"/api/v1/public/leagues/239/entries/{ENTRY}/advice"
    accepted = client.post(route, json={**BODY, "window": 3})
    assert accepted.status_code == 202, accepted.text
    fetch.assert_called_once_with(ENTRY, 2)
    outcome = run_advice_worker_once(
        backend.queue,
        backend.cache,
        build_advice_compute(
            backend.contexts, backend.job_specs, public_inputs=backend.public_inputs
        ),
        at_utc=worker_tests.world_module.GW2_CAPTURED_AT,
    )
    assert outcome.status == "failed", outcome
    assert "Projection horizon targets gameweeks absent" in str(outcome)
    assert "Unsupported public team request" not in str(outcome)


def test_a_chip_the_public_team_does_not_hold_is_refused_after_its_inputs_are_pinned(public):
    backend, client, fetch = public
    route = f"/api/v1/public/leagues/239/entries/{ENTRY}/advice"
    fetch.side_effect = lambda entry, week: json.dumps(
        {
            **bundle(entry, week),
            "history": {"current": [], "chips": [{"name": "bboost", "event": 1}]},
        }
    ).encode()
    response = client.post(route, json={**BODY, "chip": "bboost"})
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "CHIP_NOT_HELD"
    fetch.assert_called_once()
    assert backend.queue_depth() == 0


@pytest.mark.parametrize("league", [239, 0])
def test_public_capabilities_name_the_pure_points_menu_and_the_pinned_teams_chips(public, league):
    """Before a plan is asked the team's chips are unnamed; the first request pins them."""
    backend, client, fetch = public
    route = f"/api/v1/public/leagues/{league}/entries/{ENTRY}/capabilities"
    before = client.get(route)
    assert before.status_code == 200, before.text
    document = before.json()
    jsonschema.validate(document, league_capabilities_schema())
    assert document["league_id"] == league
    assert document["capture_snapshot_id"] == backend.contexts.current().capture_snapshot_id
    assert document["strategies"] == {"saf-puan": {"windows": [1, 3, 5], "requires_rival": False}}
    assert document["chips"]["held_by_entry"] == {}
    fetch.assert_not_called()

    accepted = client.post(f"/api/v1/public/leagues/{league}/entries/{ENTRY}/advice", json=BODY)
    assert accepted.status_code == 202, accepted.text
    after = client.get(route).json()
    assert "bboost" in after["chips"]["held_by_entry"][str(ENTRY)]
    fetch.assert_called_once()


def test_public_capabilities_are_disabled_until_the_deployment_opts_in(tmp_path, monkeypatch):
    backend = worker_tests._deployment(tmp_path, monkeypatch)["backend"]
    client = TestClient(app_for_capture(backend, worker_tests.world_module.GW2_CAPTURED_AT))
    response = client.get(f"/api/v1/public/leagues/239/entries/{ENTRY}/capabilities")
    assert response.status_code == 503
