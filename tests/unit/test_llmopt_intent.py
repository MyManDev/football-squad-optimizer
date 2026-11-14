"""Intent preparation validates the model output without submitting a solve."""

import json
from typing import Any

import pytest
from fastapi.testclient import TestClient

from squadopt.api.app import create_app
from squadopt.platform.llmopt_intent import (
    INTENT_BODY_MAX_BYTES,
    IntentClarification,
    IntentRequest,
    IntentService,
    OpenAIIntentProvider,
    intent_service_from_environment,
)

URL = "/api/v1/llmopt/intent"


def _request() -> dict[str, Any]:
    return {
        "message": "Salah ile ve Salah olmadan karş\u0131laşt\u0131r",
        "locale": "tr",
        "draft": {"hard": [{"kind": "no_hits"}], "soft": []},
        "players": [{"id": 1, "name": "Mohamed Salah", "team": "LIV", "held": True}],
    }


def _proposed(player_id: int = 1) -> dict[str, Any]:
    return {
        "status": "draft",
        "draft": {
            "hard": [{"kind": "no_hits", "player_id": None}],
            "soft": [],
            "comparison": {"kind": "include_player", "player_id": player_id, "both": True},
        },
        "message": None,
    }


def test_prepares_comparison_and_preserves_hard_constraints() -> None:
    def provider(request: IntentRequest) -> object:
        assert request.locale == "tr"
        assert request.draft == _request()["draft"]
        assert request.players == tuple(_request()["players"])
        return _proposed()

    with TestClient(create_app(llmopt_intent=IntentService(provider))) as client:
        response = client.post(URL, json=_request())
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {
        "status": "draft",
        "draft": {
            "hard": [{"kind": "no_hits"}],
            "soft": [],
            "comparison": {"kind": "include_player", "player_id": 1, "both": True},
        },
    }


def test_response_asks_a_question_instead_of_returning_a_partial_draft() -> None:
    def provider(_request: IntentRequest) -> object:
        return {"status": "clarification", "draft": None, "message": "Hangi oyuncu?"}

    with TestClient(create_app(llmopt_intent=IntentService(provider))) as client:
        response = client.post(URL, json=_request())
    assert response.status_code == 200
    assert response.json() == {"status": "clarification", "message": "Hangi oyuncu?"}


@pytest.mark.parametrize(
    "comparison",
    [
        {"kind": "include_player", "player_id": 2, "both": True},
        {"kind": "include_player", "player_id": True, "both": False},
        {"kind": "avoid_player", "player_id": 1, "both": True},
        {"kind": "no_hits", "player_id": 1, "both": False},
        {"kind": "execute", "player_id": None, "both": False},
    ],
)
def test_rejects_invalid_provider_draft(comparison: dict[str, Any]) -> None:
    def provider(_request: IntentRequest) -> object:
        result = _proposed()
        result["draft"]["comparison"] = comparison
        return result

    with TestClient(create_app(llmopt_intent=IntentService(provider))) as client:
        response = client.post(URL, json=_request())
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "LLMOPT_UNAVAILABLE"


def test_full_roster_is_shortlisted_before_provider_call() -> None:
    body = _request()
    body["players"] = [
        {"id": player_id, "name": f"Other {player_id}", "team": "ARS"}
        for player_id in range(2, 900)
    ]
    body["players"].append(_request()["players"][0])

    def provider(request: IntentRequest) -> object:
        assert tuple(player["id"] for player in request.players) == (1,)
        return _proposed()

    with TestClient(create_app(llmopt_intent=IntentService(provider))) as client:
        response = client.post(URL, json=body)
    assert response.status_code == 200


def test_answer_uses_original_request_and_reply_in_shortlist() -> None:
    body = _request()
    body["message"] = "The Chelsea player"
    body["clarification"] = {"message": "Compare James in and out", "question": "Which James?"}
    body["players"] = [
        {"id": player_id, "name": f"Other {player_id}", "team": "Arsenal"}
        for player_id in range(3, 100)
    ] + [
        {"id": 1, "name": "James Tarkowski", "team": "Everton"},
        {"id": 2, "name": "Reece James", "team": "Chelsea"},
    ]

    def provider(request: IntentRequest) -> object:
        assert request.message == "The Chelsea player"
        assert request.clarification == IntentClarification(
            "Compare James in and out", "Which James?"
        )
        assert tuple(player["id"] for player in request.players) == (2, 1)
        return _proposed(2)

    with TestClient(create_app(llmopt_intent=IntentService(provider))) as client:
        response = client.post(URL, json=body)
    assert response.status_code == 200
    assert response.json()["draft"]["comparison"]["player_id"] == 2


@pytest.mark.parametrize(
    "clarification",
    [
        None,
        {"message": "only the prior message"},
        {"message": "x" * 801, "question": "Which player?"},
        {"message": "Previous request", "question": "x" * 301},
        {"message": "Previous request", "question": "Question", "history": []},
    ],
)
def test_rejects_oversized_or_undeclared_clarification(clarification: object) -> None:
    def provider(_request: IntentRequest) -> object:
        pytest.fail("Malformed clarification reached the provider.")

    with TestClient(create_app(llmopt_intent=IntentService(provider))) as client:
        response = client.post(URL, json={**_request(), "clarification": clarification})
    assert response.status_code == 422


def test_refuses_constraint_repeated_across_strengths() -> None:
    def provider(_request: IntentRequest) -> object:
        proposal = _proposed()
        proposal["draft"]["soft"] = list(proposal["draft"]["hard"])
        return proposal

    with TestClient(create_app(llmopt_intent=IntentService(provider))) as client:
        response = client.post(URL, json=_request())
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "LLMOPT_UNAVAILABLE"


def test_validation_and_rate_limits_do_not_call_provider() -> None:
    calls = 0

    def provider(_request: IntentRequest) -> object:
        nonlocal calls
        calls += 1
        return _proposed()

    with TestClient(create_app(llmopt_intent=IntentService(provider, per_minute=1))) as client:
        assert client.post(URL, content="{}").status_code == 415
        headers = {"Content-Type": "application/json"}
        assert (
            client.post(
                URL, content=b"x" * (INTENT_BODY_MAX_BYTES + 1), headers=headers
            ).status_code
            == 413
        )
        assert (
            client.post(URL, content='{"draft":{},"draft":{}}', headers=headers).status_code == 422
        )
        assert client.post(URL, json={**_request(), "model": "arbitrary"}).status_code == 422
        assert calls == 0
        assert client.post(URL, json=_request()).status_code == 200
        limited = client.post(URL, json=_request())
        assert limited.status_code == 429
        assert limited.headers["retry-after"] == "60"
        assert calls == 1


def test_unconfigured_endpoint_leaves_backend_healthy() -> None:
    assert intent_service_from_environment({"OPENAI_API_KEY": "ambient-key"}) is None
    assert (
        intent_service_from_environment(
            {"SQUADOPT_LLMOPT_API_KEY": "invalid\nkey", "SQUADOPT_LLMOPT_MODEL": "test"}
        )
        is None
    )
    with TestClient(create_app()) as client:
        response = client.post(URL, json=_request())
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "LLMOPT_DISABLED"
        assert client.get("/health").status_code == 200


def test_provider_sends_strict_schema_and_handles_wire_without_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def post(_provider: OpenAIIntentProvider, payload: bytes) -> bytes:
        body = json.loads(payload)
        assert body["model"] == "selected-model"
        assert body["store"] is False
        schema = body["response_format"]["json_schema"]
        assert schema["strict"] is True
        assert "oneOf" not in schema["schema"]
        context = json.loads(body["messages"][1]["content"])
        assert context["message"] == "The Liverpool player"
        assert context["clarification"] == {
            "message": "Compare Salah in and out",
            "question": "Which player?",
        }
        return json.dumps(
            {
                "choices": [
                    {"finish_reason": "stop", "message": {"content": json.dumps(_proposed())}}
                ]
            }
        ).encode()

    monkeypatch.setattr(OpenAIIntentProvider, "_post", post)
    service = intent_service_from_environment(
        {"SQUADOPT_LLMOPT_API_KEY": "server-key", "SQUADOPT_LLMOPT_MODEL": "selected-model"}
    )
    body = {
        **_request(),
        "message": "The Liverpool player",
        "clarification": {"message": "Compare Salah in and out", "question": "Which player?"},
    }
    with TestClient(create_app(llmopt_intent=service)) as client:
        assert client.post(URL, json=body).status_code == 200
