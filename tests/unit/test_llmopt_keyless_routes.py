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


@pytest.mark.parametrize(
    ("name", "message", "locale"),
    [
        ("Martin Ødegaard", "Buy Odegaard", "en"),
        ("Martin Ødegaard", "Odegaardi al", "tr"),
        ("Martin Ødegaard", "Odegaardi al", "en"),
        ("Đorđe Petrović", "Buy Dorde", "en"),
        ("Łukasz Fabiański", "Buy Lukasz", "en"),
    ],
)
def test_unaccented_player_names_remain_available_to_prompt_and_check(
    name: str, message: str, locale: str
) -> None:
    body = _request(roster=300)
    body.pop("clarification")
    body.update(message=message, locale=locale, draft={"hard": [], "soft": []})
    body["players"][-1] = {"id": 1, "name": name, "team": "Arsenal", "held": False}
    with TestClient(create_app()) as client:
        prompt = client.post(PROMPT, json=body)
        assert prompt.status_code == 200
        assert [row["id"] for row in json.loads(prompt.json()["user"])["players"]] == [1]
        checked = client.post(CHECK, json={"request": body, "reply": _draft(1)})
    assert checked.status_code == 200
    assert checked.json()["draft"]["comparison"]["player_id"] == 1


@pytest.mark.parametrize("locale", ["en", "tr"])
@pytest.mark.parametrize(
    ("name", "short_name", "message"),
    [
        ("Norberto Bercique Gomes Betuncal", "Beto", "Buy Beto"),
        ("Norberto Bercique Gomes Betuncal", "Beto", "Betoyu al"),
        ("Felipe Rodrigues da Silva", "Morato", "Buy Morato"),
        ("Sávio Moreira de Oliveira", "Savinho", "Buy Savinho"),
        ("Eberechi Eze", "Eze", "Ezeyi al"),
        ("Eberechi Eze", "Eze", "Eze'yi al"),
        ("Bukayo Saka", "Saka", "Sakasiz ve Sakali karsilastir"),
        ("Norberto Bercique Gomes Betuncal", "Beto", "Betosuz kadro istiyorum"),
        ("Eberechi Eze", "Eze", "Ezeye yer ac"),
        ("Bukayo Saka", "Saka", "Sakadan vazgec"),
        ("Bukayo Saka", "Saka", "Sakanin maliyetini karsilastir"),
        ("Norberto Bercique Gomes Betuncal", "Beto", "Betoyla kadro istiyorum"),
        ("Eberechi Eze", "Eze", "Ezeyle kadro istiyorum"),
    ],
)
def test_published_player_short_names_reach_prompt_and_checked_draft(
    name: str, short_name: str, message: str, locale: str
) -> None:
    body = _request(roster=300)
    body.pop("clarification")
    body.update(message=message, locale=locale, draft={"hard": [], "soft": []})
    body["players"][-1] = {
        "id": 1,
        "name": name,
        "short_name": short_name,
        "team": "Everton",
        "held": False,
    }
    with TestClient(create_app()) as client:
        prompt = client.post(PROMPT, json=body)
        assert prompt.status_code == 200
        candidates = json.loads(prompt.json()["user"])["players"]
        assert candidates == [body["players"][-1]]
        checked = client.post(CHECK, json={"request": body, "reply": _draft(1)})
    assert checked.status_code == 200
    assert checked.json()["draft"]["comparison"]["player_id"] == 1


@pytest.mark.parametrize(
    ("players", "message"),
    [
        (
            [
                {"id": 1, "name": "Norberto Betuncal", "short_name": "Beto"},
                {"id": 1001, "name": "Another Player", "short_name": "Beto"},
            ],
            "Betoyu al",
        ),
        (
            [
                {"id": 1, "name": "Martin Ødegaard"},
                {"id": 1001, "name": "Another Odegaard"},
            ],
            "Buy Odegaard",
        ),
    ],
)
def test_name_collisions_keep_all_candidates_for_model_clarification(
    players: list[dict[str, Any]], message: str
) -> None:
    body = _request(roster=300)
    body.pop("clarification")
    body.update(message=message, locale="en", draft={"hard": [], "soft": []})
    body["players"][-1:] = players
    with TestClient(create_app()) as client:
        prompt = client.post(PROMPT, json=body)
    assert prompt.status_code == 200
    candidates = json.loads(prompt.json()["user"])["players"]
    assert {row["id"] for row in candidates} == {1, 1001}


def test_clarification_keeps_original_name_when_the_interface_language_changes() -> None:
    body = _request(roster=300)
    body.update(
        message="Everton",
        locale="en",
        draft={"hard": [], "soft": []},
        clarification={"message": "Betoyu al", "question": "Hangi tak\u0131mdaki oyuncu?"},
    )
    body["players"][-1] = {
        "id": 1,
        "name": "Norberto Bercique Gomes Betuncal",
        "short_name": "Beto",
        "team": "Everton",
        "held": False,
    }
    with TestClient(create_app()) as client:
        prompt = client.post(PROMPT, json=body)
        assert prompt.status_code == 200
        assert json.loads(prompt.json()["user"])["players"] == [body["players"][-1]]
        checked = client.post(CHECK, json={"request": body, "reply": _draft(1)})
    assert checked.status_code == 200
    assert checked.json()["draft"]["comparison"]["player_id"] == 1


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


@pytest.mark.parametrize("as_text", [False, True])
@pytest.mark.parametrize("hard_mode", ["omitted", "null", "clear", "replace"])
def test_model_reply_preserves_omitted_required_rules_and_allows_explicit_edits(
    hard_mode: str, as_text: bool
) -> None:
    required = [
        {"kind": "wildcard"},
        {"kind": "no_hits"},
        {"kind": "club_count", "club": "Brighton", "count": 3, "scope": "transfers_in"},
    ]
    body: dict[str, Any] = {
        "message": "Mümkünse Salah da olsun.",
        "locale": "tr",
        "draft": {"hard": required, "soft": [], "window": 3},
        "players": [{"id": 1, "name": "Mohamed Salah", "team": "Brighton", "held": True}],
    }
    revised: dict[str, Any] = {"soft": [{"kind": "include_player", "player_id": 1}]}
    expected_hard = required
    if hard_mode == "null":
        revised["hard"] = None
    elif hard_mode == "clear":
        body["message"] = (
            "Kesin kurallar\u0131n tamam\u0131n\u0131 kald\u0131r. Mümkünse Salah olsun."
        )
        revised["hard"] = expected_hard = []
    elif hard_mode == "replace":
        body["message"] = "Wildcard ve Brighton şartlar\u0131n\u0131 kald\u0131r, ceza alma."
        revised["hard"] = expected_hard = [{"kind": "no_hits"}]
    reply = {"status": "draft", "draft": revised}
    service = IntentService(lambda _request: reply)
    with TestClient(create_app(llmopt_intent=service)) as client:
        checked = client.post(
            CHECK,
            json={"request": body, "reply": json.dumps(reply) if as_text else reply},
        )
        prepared = client.post(INTENT, json=body)
    assert checked.status_code == prepared.status_code == 200
    assert (
        checked.json()
        == prepared.json()
        == {
            "status": "draft",
            "draft": {
                "hard": expected_hard,
                "soft": [{"kind": "include_player", "player_id": 1}],
                "window": 3,
            },
        }
    )
    assert body["draft"]["hard"] == required


@pytest.mark.parametrize("hard", [None, "keep the rules", {}])
def test_confirmed_request_still_needs_a_valid_required_rule_list(hard: object) -> None:
    body = _request()
    body["draft"]["hard"] = hard
    with TestClient(create_app()) as client:
        checked = client.post(CHECK, json={"request": body, "reply": _draft()})
    assert checked.status_code == 422
    assert checked.json()["error"]["code"] == "VALIDATION_FAILED"


def test_confirmed_request_cannot_omit_its_required_rule_list() -> None:
    body = _request()
    del body["draft"]["hard"]
    with TestClient(create_app()) as client:
        checked = client.post(CHECK, json={"request": body, "reply": _draft()})
    assert checked.status_code == 422
    assert checked.json()["error"]["code"] == "VALIDATION_FAILED"


@pytest.mark.parametrize("null_lists", [False, True])
def test_partial_hard_rule_edit_preserves_wish_cost_bank_floor_and_frozen_weeks(
    null_lists: bool,
) -> None:
    original = {
        "hard": [{"kind": "no_hits"}],
        "soft": [{"kind": "keep_player", "player_id": 1, "max_cost_tenths": 15}],
        "keep_weeks": [1],
        "min_bank": {"tenths": 5, "week": 2},
        "window": 3,
    }
    hard = [*original["hard"], {"kind": "include_player", "player_id": 2}]
    revised = {"hard": hard}
    if null_lists:
        revised.update({"soft": None, "keep_weeks": None})
    body = {
        **_request(roster=2),
        "message": "Also require Other 2 in the squad.",
        "draft": original,
        "reference_weeks": [1, 2, 3],
    }
    reply = {"status": "draft", "draft": revised}
    with TestClient(create_app(llmopt_intent=IntentService(lambda _request: reply))) as client:
        checked = client.post(CHECK, json={"request": body, "reply": reply})
        prepared = client.post(INTENT, json=body)
    assert checked.status_code == prepared.status_code == 200
    expected = {"status": "draft", "draft": {**original, "hard": hard}}
    assert checked.json() == prepared.json() == expected


def test_explicit_empty_lists_clear_reviewed_wishes_and_frozen_weeks() -> None:
    body = {
        **_request(),
        "message": "Remove the wish and release the frozen week.",
        "draft": {
            "hard": [{"kind": "no_hits"}],
            "soft": [{"kind": "keep_player", "player_id": 1, "max_cost_tenths": 15}],
            "keep_weeks": [1],
            "window": 3,
        },
        "reference_weeks": [1],
    }
    reply = {"status": "draft", "draft": {"soft": [], "keep_weeks": []}}
    with TestClient(create_app()) as client:
        checked = client.post(CHECK, json={"request": body, "reply": reply})
    assert checked.status_code == 200
    assert checked.json() == {
        "status": "draft",
        "draft": {"hard": [{"kind": "no_hits"}], "soft": [], "window": 3},
    }


@pytest.mark.parametrize("clear", [False, True])
@pytest.mark.parametrize(
    ("field", "selection"),
    [
        ("comparison", {"kind": "include_player", "player_id": 1, "both": True}),
        ("min_bank", {"tenths": 12, "week": 2}),
        ("scenario", {"kind": "unavailable", "player_id": 1, "week": 2}),
    ],
)
def test_partial_reply_keeps_optional_selection_until_explicit_null(
    field: str, selection: dict[str, Any], clear: bool
) -> None:
    original = {"hard": [{"kind": "no_hits"}], "soft": [], "window": 3, field: selection}
    body = {
        **_request(),
        "message": "Remove that selection." if clear else "Keep the same requirements.",
        "draft": original,
        "reference_weeks": [1, 2, 3],
    }
    reply = {
        "status": "draft",
        "draft": {"hard": [{"kind": "no_hits"}], **({field: None} if clear else {})},
    }
    with TestClient(create_app(llmopt_intent=IntentService(lambda _request: reply))) as client:
        checked = client.post(CHECK, json={"request": body, "reply": reply})
        prepared = client.post(INTENT, json=body)
    assert checked.status_code == prepared.status_code == 200
    expected = {key: value for key, value in original.items() if not clear or key != field}
    assert checked.json() == prepared.json() == {"status": "draft", "draft": expected}


def test_retained_frozen_week_still_requires_a_solved_reference() -> None:
    body = {
        **_request(),
        "message": "Keep the reviewed plan.",
        "draft": {"hard": [{"kind": "no_hits"}], "soft": [], "keep_weeks": [2], "window": 3},
        "reference_weeks": [1],
    }
    with TestClient(create_app()) as client:
        checked = client.post(
            CHECK,
            json={"request": body, "reply": {"status": "draft", "draft": {"hard": []}}},
        )
    assert checked.status_code == 200
    assert checked.json()["status"] == "clarification"


@pytest.mark.parametrize("scope", ["squad", "transfers_in"])
@pytest.mark.parametrize("clarify", [False, True])
def test_conflicting_editable_club_counts_can_be_corrected_through_chat(
    scope: str, clarify: bool
) -> None:
    general = {"kind": "club_count", "club": "LIV", "count": 3}
    if scope == "transfers_in":
        general["scope"] = scope
    conflicting = {**general, "count": 2, "week": 2}
    body = {
        **_request(),
        "message": "Remove the second-week count and keep three players in every week.",
        "draft": {"hard": [general, conflicting], "soft": [], "window": 3},
    }
    reply = (
        {"status": "clarification", "message": "Which of the two counts should I keep?"}
        if clarify
        else {"status": "draft", "draft": {"hard": [general]}}
    )
    with TestClient(create_app(llmopt_intent=IntentService(lambda _request: reply))) as client:
        prompt = client.post(PROMPT, json=body)
        checked = client.post(CHECK, json={"request": body, "reply": reply})
        prepared = client.post(INTENT, json=body)
    assert prompt.status_code == checked.status_code == prepared.status_code == 200
    assert json.loads(prompt.json()["user"])["draft"] == body["draft"]
    assert checked.json() == prepared.json()
    if clarify:
        assert checked.json() == reply
    else:
        assert checked.json() == {
            "status": "draft",
            "draft": {"hard": [general], "soft": [], "window": 3},
        }


@pytest.mark.parametrize("scope", ["squad", "transfers_in"])
def test_a_model_must_resolve_conflicting_club_counts_before_the_draft_is_accepted(
    scope: str,
) -> None:
    general = {"kind": "club_count", "club": "LIV", "count": 3}
    if scope == "transfers_in":
        general["scope"] = scope
    body = {
        **_request(),
        "message": "Help me fix the conflicting club rules.",
        "draft": {"hard": [general, {**general, "count": 2, "week": 2}], "soft": [], "window": 3},
    }
    reply = {"status": "draft", "draft": {"hard": body["draft"]["hard"]}}
    with TestClient(create_app(llmopt_intent=IntentService(lambda _request: reply))) as client:
        checked = client.post(CHECK, json={"request": body, "reply": reply})
        prepared = client.post(INTENT, json=body)
    assert checked.status_code == 422
    assert checked.json()["error"]["code"] == "REPLY_REFUSED"
    assert prepared.status_code == 503
    assert prepared.json()["error"]["code"] == "LLMOPT_UNAVAILABLE"


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
