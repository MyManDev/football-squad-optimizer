"""The keyless LLMOPT routes send the site provider's call and give prepare()'s verdict."""

import json
import logging
from typing import Any

import pytest
from fastapi.testclient import TestClient

from squadopt.api.app import create_app
from squadopt.platform.llmopt_intent import (
    INTENT_BODY_MAX_BYTES,
    IntentRequest,
    IntentService,
    IntentUnavailable,
    OpenAIIntentProvider,
    intent_service_from_environment,
    parse_intent_request,
)

PROMPT = "/api/v1/llmopt/prompt"
CHECK = "/api/v1/llmopt/check"
INTENT = "/api/v1/llmopt/intent"
_SECRET_TEXT = "Salah ile ve Salah olmadan karsilastir"


def _request(*, roster: int = 1) -> dict[str, Any]:
    """An intent request; a roster above the shortlist's size puts unnamed players outside it."""
    others = [
        {"id": player_id, "name": f"Other {player_id}", "team": "ARS"}
        for player_id in range(2, roster + 1)
    ]
    return {
        "message": _SECRET_TEXT,
        "locale": "tr",
        "draft": {"hard": [{"kind": "no_hits"}], "soft": [], "window": 1},
        "players": [*others, {"id": 1, "name": "Mohamed Salah", "team": "LIV", "held": True}],
        "clarification": {"message": "Compare Salah in and out", "question": "Which player?"},
    }


def _draft(player_id: int = 1, **extra: Any) -> dict[str, Any]:
    return {
        "status": "draft",
        "draft": {
            "hard": [{"kind": "no_hits", "player_id": None}],
            "soft": [],
            "comparison": {"kind": "include_player", "player_id": player_id, "both": True},
            **extra,
        },
        "message": None,
    }


def test_prompt_is_the_call_the_site_provider_sends(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[dict[str, Any]] = []

    def post(_provider: OpenAIIntentProvider, payload: bytes, _deadline: float) -> bytes:
        sent.append(json.loads(payload))
        content = json.dumps(_draft())
        return json.dumps(
            {"choices": [{"finish_reason": "stop", "message": {"content": content}}]}
        ).encode()

    monkeypatch.setattr(OpenAIIntentProvider, "_post", post)
    service = intent_service_from_environment(
        {"SQUADOPT_LLMOPT_API_KEY": "server-key", "SQUADOPT_LLMOPT_MODEL": "m"}
    )
    body = _request(roster=300)
    with TestClient(create_app(llmopt_intent=service)) as client:
        assert client.post(INTENT, json=body).status_code == 200
        prompt = client.post(PROMPT, json=body)
    assert prompt.status_code == 200
    assert prompt.headers["cache-control"] == "no-store"
    call = prompt.json()
    assert set(call) == {"system", "user", "schema", "schema_name", "max_output_tokens"}
    wire = sent[0]
    assert call["system"] == wire["messages"][0]["content"]
    assert call["user"] == wire["messages"][1]["content"]
    assert call["schema"] == wire["response_format"]["json_schema"]["schema"]
    assert call["schema_name"] == wire["response_format"]["json_schema"]["name"]
    assert call["schema_name"] == "llmopt_intent_v1"
    assert call["max_output_tokens"] == wire["max_completion_tokens"]
    # The user message carries the shortlist, not the full roster.
    assert [player["id"] for player in json.loads(call["user"])["players"]] == [1]


def _verdict_from_prepare(body: dict[str, Any], reply: object) -> dict[str, Any] | None:
    service = IntentService(lambda _request: reply)
    try:
        return service.prepare(parse_intent_request(body), "visitor")
    except IntentUnavailable:
        return None


@pytest.mark.parametrize(
    ("name", "reply"),
    [
        ("valid draft", _draft()),
        ("clarification", {"status": "clarification", "draft": None, "message": "Hangi?"}),
        ("kept week not solved", _draft(keep_weeks=[1])),
        # Player 200 is on the roster but outside the shortlist the model was offered.
        ("id outside shortlist", _draft(200)),
        ("id outside roster", _draft(5000)),
        ("missing field", {"status": "draft", "draft": None}),
        ("wrong status", {**_draft(), "status": "done"}),
        ("not an object", ["draft"]),
    ],
)
@pytest.mark.parametrize("as_text", [False, True])
def test_check_gives_the_same_verdict_as_prepare(name: str, reply: object, as_text: bool) -> None:
    body = _request(roster=300)
    expected = _verdict_from_prepare(body, reply)
    with TestClient(create_app()) as client:
        checked = client.post(
            CHECK, json={"request": body, "reply": json.dumps(reply) if as_text else reply}
        )
    if expected is None:
        assert checked.status_code == 422, name
        assert checked.json()["error"]["code"] == "REPLY_REFUSED"
    else:
        assert checked.status_code == 200, checked.text
        assert checked.json() == expected
    assert checked.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("reply", ["{not json", '{"status":"draft","status":"draft"}', ""])
def test_check_refuses_reply_text_that_is_not_json(reply: str) -> None:
    with TestClient(create_app()) as client:
        checked = client.post(CHECK, json={"request": _request(), "reply": reply})
    assert checked.status_code == 422
    assert checked.json()["error"]["code"] == "REPLY_REFUSED"


@pytest.mark.parametrize(
    "body",
    [
        {"request": {"message": "x"}, "reply": _draft()},
        {"request": _request()},
        {"request": _request(), "reply": _draft(), "key": "sk-test"},
        [],
    ],
)
def test_check_refuses_a_malformed_body(body: object) -> None:
    with TestClient(create_app()) as client:
        checked = client.post(CHECK, json=body)
    assert checked.status_code == 422
    assert checked.json()["error"]["code"] == "VALIDATION_FAILED"


@pytest.mark.parametrize("route", [PROMPT, CHECK])
@pytest.mark.parametrize(
    "header",
    [
        {"Authorization": "Bearer sk-test"},
        {"authorization": "Basic dGVzdA=="},
        {"x-api-key": "sk-ant-test"},
        {"X-Goog-Api-Key": "AIza-test"},
    ],
)
def test_a_request_carrying_a_key_is_refused(route: str, header: dict[str, str]) -> None:
    body = {"request": _request(), "reply": _draft()} if route == CHECK else _request()
    with TestClient(create_app()) as client:
        refused = client.post(route, json=body, headers=header)
    assert refused.status_code == 400
    assert refused.json()["error"]["code"] == "CREDENTIAL_REFUSED"
    assert refused.headers["cache-control"] == "no-store"
    assert "test" not in refused.text


def test_keyless_routes_work_without_a_site_key_and_leave_intent_disabled() -> None:
    assert intent_service_from_environment({}) is None
    with TestClient(create_app(llmopt_intent=intent_service_from_environment({}))) as client:
        assert client.post(INTENT, json=_request()).json()["error"]["code"] == "LLMOPT_DISABLED"
        assert client.post(PROMPT, json=_request()).status_code == 200
        checked = client.post(CHECK, json={"request": _request(), "reply": _draft()})
    assert checked.status_code == 200
    assert checked.json()["draft"]["comparison"] == {
        "kind": "include_player",
        "player_id": 1,
        "both": True,
    }


@pytest.mark.parametrize("route", [PROMPT, CHECK])
def test_keyless_routes_cap_the_body_and_need_json(route: str) -> None:
    with TestClient(create_app()) as client:
        assert client.post(route, content="{}").status_code == 415
        oversized = client.post(
            route,
            content=b"x" * (INTENT_BODY_MAX_BYTES + 1),
            headers={"Content-Type": "application/json"},
        )
    assert oversized.status_code == 413
    assert oversized.json()["error"]["code"] == "PAYLOAD_TOO_LARGE"


def test_each_keyless_route_has_its_own_per_visitor_minute() -> None:
    with TestClient(create_app()) as client:
        for _ in range(20):
            assert client.post(PROMPT, json=_request()).status_code == 200
        limited = client.post(PROMPT, json=_request())
        assert limited.status_code == 429
        assert limited.json()["error"]["code"] == "RATE_LIMITED"
        assert limited.headers["retry-after"] == "60"
        check = {"request": _request(), "reply": _draft()}
        assert client.post(CHECK, json=check).status_code == 200


def test_keyless_routes_never_use_the_site_budget_or_provider() -> None:
    calls = 0

    def provider(request: IntentRequest) -> object:
        nonlocal calls
        calls += 1
        assert request.locale == "tr"
        return _draft()

    service = IntentService(provider, per_minute=1, per_day=1)
    with TestClient(create_app(llmopt_intent=service)) as client:
        for _ in range(5):
            assert client.post(PROMPT, json=_request()).status_code == 200
            check = {"request": _request(), "reply": _draft()}
            assert client.post(CHECK, json=check).status_code == 200
        assert calls == 0
        assert client.post(INTENT, json=_request()).status_code == 200
        assert client.post(INTENT, json=_request()).status_code == 429
    assert calls == 1


def test_keyless_routes_never_log_the_member_text(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    with TestClient(create_app()) as client:
        client.post(PROMPT, json=_request())
        client.post(CHECK, json={"request": _request(), "reply": _draft(5000)})
        client.post(CHECK, json={"request": _request(), "reply": "{not json"})
    assert "Salah" not in caplog.text
    assert _SECRET_TEXT not in caplog.text


def _without_type(schema: object, path: str = "$") -> list[str]:
    """Every object schema below ``schema`` that names neither a type nor alternatives."""
    if isinstance(schema, list):
        return [found for item in schema for found in _without_type(item, path)]
    if not isinstance(schema, dict):
        return []
    missing = [] if {"type", "anyOf"} & schema.keys() else [path]
    children = [
        *((f"{path}.{name}", child) for name, child in schema.get("properties", {}).items()),
        *((f"{path}[]", child) for child in [schema.get("items")] if child is not None),
        *((f"{path}|", child) for child in schema.get("anyOf", [])),
    ]
    return missing + [found for where, child in children for found in _without_type(child, where)]


def test_every_schema_in_the_prompt_names_its_type() -> None:
    # A provider's strict mode refuses a property schema with no type (OpenAI: "schema must
    # have a 'type' key"), and the member's own provider gets this schema as it is.
    with TestClient(create_app()) as client:
        schema = client.post(PROMPT, json=_request()).json()["schema"]
    assert _without_type(schema) == []


@pytest.mark.parametrize(
    ("reply", "expected"),
    [
        # A provider that does not enforce the schema leaves out what it has nothing for.
        (
            {"status": "clarification", "message": "Hangi oyuncu?"},
            {"status": "clarification", "message": "Hangi oyuncu?"},
        ),
        (
            {"status": "draft", "draft": {"hard": [{"kind": "no_hits"}]}},
            {"status": "draft", "draft": {"hard": [{"kind": "no_hits"}], "soft": [], "window": 1}},
        ),
        (
            {
                "status": "draft",
                "message": "Tamam.",
                "draft": {
                    "hard": [{"kind": "keep_player", "player_id": 1, "max_cost_tenths": None}],
                    "soft": None,
                    "comparison": None,
                    "keep_weeks": None,
                },
            },
            {
                "status": "draft",
                "draft": {
                    "hard": [{"kind": "keep_player", "player_id": 1}],
                    "soft": [],
                    "window": 1,
                },
            },
        ),
        (
            {
                "status": "draft",
                "draft": {"hard": [], "comparison": {"kind": "include_player", "player_id": 1}},
            },
            {
                "status": "draft",
                "draft": {
                    "hard": [],
                    "soft": [],
                    "comparison": {"kind": "include_player", "player_id": 1},
                    "window": 1,
                },
            },
        ),
    ],
)
def test_check_reads_a_reply_that_leaves_out_its_empty_parts(
    reply: dict[str, Any], expected: dict[str, Any]
) -> None:
    with TestClient(create_app()) as client:
        checked = client.post(CHECK, json={"request": _request(), "reply": reply})
    assert checked.status_code == 200, checked.text
    assert checked.json() == expected


@pytest.mark.parametrize(
    "reply",
    [
        {"draft": {"hard": [], "soft": []}},
        {"status": "draft"},
        {"status": "draft", "draft": {"hard": [], "soft": []}, "note": "extra"},
        {"status": "draft", "draft": {"hard": [{"player_id": 1}], "soft": []}},
        {"status": "draft", "draft": {"hard": [{"kind": "keep_player"}], "soft": []}},
        {
            "status": "draft",
            "draft": {"hard": [{"kind": "no_hits", "max_cost_tenths": 15}], "soft": []},
        },
        {"status": "clarification"},
    ],
)
def test_check_still_refuses_a_reply_without_its_meaning(reply: dict[str, Any]) -> None:
    with TestClient(create_app()) as client:
        checked = client.post(CHECK, json={"request": _request(), "reply": reply})
    assert checked.status_code == 422
    assert checked.json()["error"]["code"] == "REPLY_REFUSED"
