"""Plan selections are identifiers of checked decisions, never computed answers."""

import copy
import json
from dataclasses import replace
from typing import Any

import jsonschema
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from squadopt.api.llmopt import intent_routes
from squadopt.contracts.llmopt_plans import plan_conversation_schema
from squadopt.contracts.schema_paths import contract_schema_path
from squadopt.platform.advice_read import AdviceRequestContext, advice_context_identity
from squadopt.platform.llmopt_intent import (
    IntentValidationError,
    check_reply,
    intent_reply_schema,
    parse_intent_request,
    prompt_for,
)

DATA = "a" * 64
PLAN = "b" * 64


def request(kind: str = "device") -> dict[str, Any]:
    return {
        "message": "Use this plan",
        "locale": "en",
        "draft": {"hard": [], "soft": []},
        "players": [{"id": i, "name": f"Player {i}", "held": i < 16} for i in range(1, 18)],
        "plan_context": {
            "kind": kind,
            "data_id": DATA,
            "selected_plan_id": PLAN,
            "plans": [
                {
                    "plan_id": PLAN,
                    "data_id": DATA,
                    "weeks": [
                        {
                            "week": 1,
                            "transfers_in": [16],
                            "transfers_out": [1],
                            "players": list(range(2, 17)),
                            "chip": None,
                            "captain": 2,
                        }
                    ],
                }
            ],
        },
    }


def reply(**command: object) -> dict[str, object]:
    return {
        "status": "plan",
        "draft": None,
        "message": None,
        "plan_command": {"plan_id": PLAN, "action": "select", **command},
    }


def test_plan_catalogue_carries_decisions_and_explicit_types_without_metrics() -> None:
    call = prompt_for(parse_intent_request(request()))
    context = json.loads(call.user)["plan_context"]
    assert context["plans"][0]["plan_id"] == PLAN
    assert not any(key in call.user for key in ("expected_points", "bank_after", "net_points"))

    def visit(schema: Any) -> None:
        if isinstance(schema, dict):
            for field in schema.get("properties", {}).values():
                assert "type" in field, field
            for value in schema.values():
                visit(value)
        elif isinstance(schema, list):
            for value in schema:
                visit(value)

    visit(call.schema)
    assert check_reply(parse_intent_request(request()), reply()) == {
        "status": "plan",
        "command": {"plan_id": PLAN, "action": "select"},
    }


@pytest.mark.parametrize(
    "extra", [{"score": 999}, {"bank": 999}, {"cost": 0}, {"explanation": "999"}]
)
def test_computed_values_cannot_enter_a_plan_command(extra: dict[str, object]) -> None:
    with pytest.raises(IntentValidationError):
        check_reply(parse_intent_request(request()), reply(**extra))


@pytest.mark.parametrize(
    "action,fields",
    [
        ("freeze_week", {"week": 1}),
        ("freeze_transfer", {"week": 1, "player_id": 16}),
        ("substitute", {"week": 1, "player_id": 2, "replacement_id": 17}),
    ],
)
def test_checked_actions_only_refer_to_computed_decisions(
    action: str, fields: dict[str, int]
) -> None:
    result = check_reply(parse_intent_request(request()), reply(action=action, **fields))
    assert result["command"] == {"plan_id": PLAN, "action": action, **fields}


@pytest.mark.parametrize(
    "command",
    [
        {"plan_id": "c" * 64},
        {"action": "freeze_week", "week": 2},
        {"action": "freeze_transfer", "week": 1, "player_id": 1},
        {"action": "substitute", "week": 1, "player_id": 1, "replacement_id": 17},
        {"action": "substitute", "week": 1, "player_id": 2, "replacement_id": 3},
    ],
)
def test_unknown_plan_week_transfer_or_substitution_is_refused(command: dict[str, object]) -> None:
    with pytest.raises(IntentValidationError):
        check_reply(parse_intent_request(request()), reply(**command))


def test_superseded_server_identity_is_refused_by_check_route_without_a_solve() -> None:
    current = [DATA]
    app = FastAPI()
    app.include_router(intent_routes(server_data_id=lambda: current[0], llmopt_vnext=True))
    with TestClient(app) as client:
        body = {"request": request("server"), "reply": reply()}
        assert client.post("/api/v1/llmopt/check", json=body).status_code == 200
        current[0] = "d" * 64
        stale = client.post("/api/v1/llmopt/check", json=body)
        assert stale.status_code == 422
        assert stale.json()["error"]["code"] == "REPLY_REFUSED"


def test_stale_rows_are_not_accepted_as_the_current_catalogue() -> None:
    body = request()
    body["plan_context"]["plans"][0]["data_id"] = "d" * 64
    with pytest.raises(IntentValidationError):
        parse_intent_request(body)


@pytest.mark.parametrize("selected", [[], {}, False, 17])
def test_malformed_selected_id_is_a_validation_refusal(selected: object) -> None:
    body = request()
    body["plan_context"]["selected_plan_id"] = selected
    with pytest.raises(IntentValidationError):
        parse_intent_request(body)


@pytest.mark.parametrize(
    "locale,question",
    [
        ("en", "Which plan or player do you mean?"),
        ("tr", "Hangi plan\u0131 ya da oyuncuyu kastediyorsun?"),
    ],
)
def test_model_numbers_in_clarifications_are_never_forwarded(locale: str, question: str) -> None:
    body = request()
    body["locale"] = locale
    result = check_reply(
        parse_intent_request(body), {"status": "clarification", "message": "999 points?"}
    )
    assert result == {"status": "clarification", "message": question}


@pytest.mark.parametrize("catalogue", [False, True])
@pytest.mark.parametrize(
    "locale,question",
    [
        ("tr", "Hangi oyuncuyu tutmak istersin?"),
        ("en", "Which player would you like to keep?"),
        ("tr", "Bu kural 2. hafta m\u0131 3. hafta m\u0131 geçerli olsun?"),
        ("en", "Should this rule apply in week 2 or 3?"),
        ("tr", "1. ve 3. hafta ayn\u0131 kural geçerli olsun mu?"),
        ("en", "Should the same rule apply in the 1st and 3rd weeks?"),
        ("tr", "Bu kural 2. haftada geçerli olsun mu?"),
        ("tr", "1-3. haftalar için ayn\u0131 kural m\u0131?"),
        ("en", "Should it apply in weeks 1-3?"),
    ],
)
def test_clarification_preserves_questions_and_week_numbers(catalogue, locale, question):
    body = request()
    body["locale"] = locale
    if not catalogue:
        body.pop("plan_context")
    assert check_reply(
        parse_intent_request(body), {"status": "clarification", "message": question}
    ) == {"status": "clarification", "message": question}


@pytest.mark.parametrize("catalogue", [False, True])
@pytest.mark.parametrize(
    "locale,question",
    [
        ("tr", "Bu plan 999 puan getirsin mi?"),
        ("en", "Should this plan score 999 points?"),
        ("tr", "2 puan için 3. hafta bu kural\u0131 kullanay\u0131m m\u0131?"),
        ("en", "Should this rule cost 2 points in week 3?"),
        ("tr", "4. hafta m\u0131 geçerli olsun?"),
        ("en", "Should it apply in week 4?"),
        ("tr", "2,5. hafta m\u0131 geçerli olsun?"),
        ("en", "Should it apply in week 2.5?"),
        ("tr", "-2. hafta m\u0131 geçerli olsun?"),
        ("en", "Should it apply in week -2?"),
    ],
)
def test_clarification_filters_numeric_claims_only_with_a_catalogue(catalogue, locale, question):
    body = request()
    body["locale"] = locale
    if not catalogue:
        body.pop("plan_context")
    fixed = (
        "Hangi plan\u0131 ya da oyuncuyu kastediyorsun?"
        if locale == "tr"
        else "Which plan or player do you mean?"
    )
    assert check_reply(
        parse_intent_request(body), {"status": "clarification", "message": question}
    ) == {"status": "clarification", "message": fixed if catalogue else question}


def test_every_existing_server_context_field_changes_the_data_identity() -> None:
    context = AdviceRequestContext("v1", "capture", "2026-27", 8, "handoff", "commit", "config")
    identity = advice_context_identity(context)
    assert identity == advice_context_identity(copy.copy(context))
    for field in context.__dataclass_fields__:
        value = getattr(context, field)
        changed = value + 1 if isinstance(value, int) else value + "-next"
        assert advice_context_identity(replace(context, **{field: changed})) != identity


def test_committed_conversation_schema_matches_the_runtime_writer() -> None:
    schema = plan_conversation_schema()
    jsonschema.Draft202012Validator.check_schema(schema)
    assert json.loads(contract_schema_path("llmopt_plans_v1").read_text(encoding="utf-8")) == schema
    jsonschema.validate(request()["plan_context"], schema)
    reply_schema = intent_reply_schema(with_plans=True)
    jsonschema.Draft202012Validator.check_schema(reply_schema)
    assert (
        json.loads(contract_schema_path("llmopt_intent_v1").read_text(encoding="utf-8"))
        == reply_schema
    )
