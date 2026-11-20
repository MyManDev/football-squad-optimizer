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
        "plan_command": {"plan_label": "P1", "action": "select", **command},
    }


def test_plan_catalogue_carries_decisions_and_explicit_types_without_metrics() -> None:
    call = prompt_for(parse_intent_request(request()))
    context = json.loads(call.user)["plan_context"]
    assert context["plans"][0]["plan_label"] == context["selected_plan_label"] == "P1"
    assert DATA not in call.user and PLAN not in call.user
    assert "plan_id" not in call.user and "data_id" not in call.user
    assert not any(key in call.user for key in ("expected_points", "bank_after", "net_points"))

    def visit(schema: Any) -> None:
        if "anyOf" in schema:
            assert set(schema) == {"anyOf"}
            assert schema["anyOf"]
            for branch in schema["anyOf"]:
                visit(branch)
        else:
            assert "type" in schema, schema
        for field in schema.get("properties", {}).values():
            visit(field)
        if "items" in schema:
            visit(schema["items"])

    visit(call.schema)
    assert check_reply(parse_intent_request(request()), reply()) == {
        "status": "plan",
        "plan_label": "P1",
        "command": {"plan_id": PLAN, "action": "select"},
    }


def test_three_plans_use_message_local_labels_for_all_three_weeks() -> None:
    body = request()
    context = body["plan_context"]
    template = context["plans"][0]
    context["plans"] = [
        {
            **template,
            "plan_id": digit * 64,
            "weeks": [{**template["weeks"][0], "week": w} for w in (1, 2, 3)],
        }
        for digit in ("b", "c", "d")
    ]
    context["selected_plan_id"] = "c" * 64
    intent = parse_intent_request(body)
    call = prompt_for(intent)
    visible = json.loads(call.user)["plan_context"]
    contract = plan_conversation_schema()
    jsonschema.validate(visible, contract)
    assert visible["selected_plan_label"] == "P2"
    expected = ["P1", "P2", "P3"]
    assert [p["plan_label"] for p in visible["plans"]] == expected
    object_schema = call.schema["properties"]["plan_command"]["anyOf"][0]
    assert object_schema["properties"]["plan_label"] == {"type": "string", "enum": expected}
    for label, plan in zip(expected, context["plans"], strict=True):
        assert plan["plan_id"] not in call.user
        checked = check_reply(intent, reply(plan_label=label, action="freeze_week", week=3))
        assert checked == {
            "status": "plan",
            "plan_label": label,
            "command": {"plan_id": plan["plan_id"], "action": "freeze_week", "week": 3},
        }
        jsonschema.validate(checked, contract)
    with pytest.raises(IntentValidationError):
        check_reply(intent, reply(plan_label="P4"))


def test_last_retained_plan_still_has_one_unambiguous_label() -> None:
    body = request()
    context = body["plan_context"]
    context["plans"] = [{**context["plans"][0], "plan_id": f"{i:064x}"} for i in range(12)]
    context["selected_plan_id"] = context["plans"][-1]["plan_id"]
    intent = parse_intent_request(body)
    visible = json.loads(prompt_for(intent).user)["plan_context"]
    assert visible["selected_plan_label"] == "P12"
    assert check_reply(intent, reply(plan_label="P12"))["command"]["plan_id"] == f"{11:064x}"


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
        {"plan_label": "P2"},
        {"plan_label": PLAN},
        {"plan_label": "P01"},
        {"plan_label": ["P1"]},
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
        assert stale.json()["error"]["code"] == "PLAN_DATA_CHANGED"


def test_stale_catalogue_allows_rules_and_questions_without_a_version_read() -> None:
    def unexpected_read() -> str:
        raise AssertionError("Only selecting a server plan requires its current data.")

    app = FastAPI()
    app.include_router(intent_routes(server_data_id=unexpected_read, llmopt_vnext=True))
    with TestClient(app) as client:
        req = request("server")
        assert client.post("/api/v1/llmopt/prompt", json=req).status_code == 200
        for reply_body in (
            {"status": "draft", "draft": {"hard": [{"kind": "no_hits"}], "soft": []}},
            {"status": "clarification", "message": "Which week?"},
        ):
            response = client.post(
                "/api/v1/llmopt/check", json={"request": req, "reply": reply_body}
            )
            assert response.status_code == 200, response.json()
            assert response.json()["status"] == reply_body["status"]


@pytest.mark.parametrize("enabled", [False, True])
def test_plan_catalogue_and_commands_require_the_server_setting(enabled: bool) -> None:
    def current_data():
        assert enabled, "A closed plan catalogue must not read server data."
        return DATA

    app = FastAPI()
    app.include_router(intent_routes(server_data_id=current_data, llmopt_vnext=enabled))
    with TestClient(app) as client:
        body = request("server")
        plain = {key: value for key, value in body.items() if key != "plan_context"}
        ordinary = client.post("/api/v1/llmopt/prompt", json=plain)
        assert ordinary.status_code == 200
        fields = ordinary.json()["schema"]["properties"]
        assert (
            set(fields) == {"status", "draft", "message"} and "plan" not in fields["status"]["enum"]
        )
        clarification = client.post(
            "/api/v1/llmopt/check",
            json={
                "request": plain,
                "reply": {"status": "clarification", "message": "Week 2 or 3?"},
            },
        )
        assert clarification.json() == {"status": "clarification", "message": "Week 2 or 3?"}
        extra = client.post(
            "/api/v1/llmopt/check",
            json={
                "request": body if enabled else plain,
                "reply": {
                    "status": "clarification",
                    "message": "Week 2 or 3?",
                    "plan_command": None,
                },
            },
        )
        if enabled:
            assert extra.json() == clarification.json()
        else:
            assert extra.status_code == 422
            assert extra.json()["error"]["code"] == "REPLY_REFUSED"
        call = client.post("/api/v1/llmopt/prompt", json=body)
        checked = client.post("/api/v1/llmopt/check", json={"request": body, "reply": reply()})
        assert (
            client.post(
                "/api/v1/llmopt/check", json={"request": plain, "reply": reply()}
            ).status_code
            == 422
        )
        if enabled:
            assert call.status_code == 200 and "plan_command" in call.json()["schema"]["properties"]
            assert checked.json() == {
                "status": "plan",
                "plan_label": "P1",
                "command": {"plan_id": PLAN, "action": "select"},
            }
        else:
            assert call.status_code == checked.status_code == 422


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


@pytest.mark.parametrize("mode", ["off", "no_catalogue", "catalogue"])
@pytest.mark.parametrize("locale", ["en", "tr"])
@pytest.mark.parametrize(
    "english,turkish,claims_result",
    [
        ("Which player would you like to keep?", "Hangi oyuncuyu tutmak istersin?", False),
        (
            "How many weeks do you want, 3 or 5?",
            "Kaç hafta için plan istiyorsun, 3 mü 5 mi?",
            False,
        ),
        ("3 or 5?", "3 mü 5 mi?", False),
        ("999 points?", "999 puan m\u0131?", False),
        ("Gameweek 2 or gameweek 3?", "2'nci haftada m\u0131, 3'üncü haftada m\u0131?", False),
        ("GW2?", "GW2 mi?", False),
        (
            "Should the same rule apply in the 1st and 3rd weeks?",
            "1. ve 3. hafta ayn\u0131 kural m\u0131?",
            False,
        ),
        ("Should it apply in week 2.5?", "2,5. hafta m\u0131 geçerli olsun?", False),
        ("Should it apply in week -2?", "-2. hafta m\u0131 geçerli olsun?", False),
        (
            "Should this rule apply in week 2 or 3?",
            "Bu kural 2. hafta m\u0131 3. hafta m\u0131 geçerli olsun?",
            False,
        ),
        ("Should it apply in weeks 1-3?", "1-3. haftalar için ayn\u0131 kural m\u0131?", False),
        ("Should it apply in week 4?", "4. hafta m\u0131 geçerli olsun?", False),
        ("Should this plan score 999 points?", "Bu plan 999 puan getirsin mi?", False),
        ("Plan 2 or Plan 3?", "Plan 2 mi Plan 3 mü?", False),
        ("Plan 2: 61 points. Select it?", "Plan 2: 61 puan. Seçelim mi?", True),
        ("Do you want a projected score of 60 points?", "Beklenen puan 60 olsun mu?", False),
        (
            "Would you like a projected score of 60.5 points?",
            "Beklenen puan 60,5 olsun mu?",
            False,
        ),
        (
            "Plan 2 scores 61. Do you want a target of 60?",
            "Plan 2, 61 puan getiriyor. Hedef 60 olsun mu?",
            True,
        ),
        (
            "Do you want a projected score of 60 points? This plan scores 61.",
            "Beklenen puan 60 olsun mu? Bu plan 61 puan getiriyor.",
            True,
        ),
        (
            "Would you like the plan whose projected score is 60 points?",
            "Beklenen puan\u0131 60 olan plan\u0131 m\u0131 istiyorsun?",
            True,
        ),
        ("Should the plan last 3 weeks?", "Plan 3 hafta sürsün mü?", False),
        ("Is the allowance 2 points in week 3?", "3. haftada taviz 2 puan m\u0131 olsun?", False),
        (
            "Should this rule cost 2 points in week 3?",
            "2 puan için 3. hafta bu kural\u0131 kullanay\u0131m m\u0131?",
            False,
        ),
        ("Would you allow a bank of £1.5m?", "Kasada 1,5 milyon kals\u0131n m\u0131?", False),
        (
            "Should the price go up by £0.2m?",
            "Oyuncunun fiyat\u0131 0,2 milyon arts\u0131n m\u0131?",
            False,
        ),
        ("Would you accept a -4 hit?", "-4 puan cezay\u0131 kabul eder misin?", False),
        (
            "Should the plan allow 2 free transfers?",
            "Plan 2 ücretsiz transfere izin versin mi?",
            False,
        ),
        (
            "Should the club limit be 3 players?",
            "Kulüp s\u0131n\u0131r\u0131 3 oyuncu mu olsun?",
            False,
        ),
        (
            "If this plan leaves £1.5m, should we keep the same bank floor?",
            "Eğer kasada 1,5 milyon kal\u0131rsa ayn\u0131 alt s\u0131n\u0131r geçerli olsun mu?",
            False,
        ),
        ("This plan scores 999 points. Use it?", "Bu plan 999 puan getiriyor. Seçelim mi?", True),
        (
            "Plan 2's expected score is 63.25. Select it?",
            "Plan 2'nin beklenen puan\u0131 63,25. Seçelim mi?",
            True,
        ),
        (
            "The plan leaves £1.5m in the bank. Is that enough?",
            "Bu planda kasada 1,5 milyon kal\u0131yor. Yeterli mi?",
            True,
        ),
        (
            "The result costs 4 points. Continue?",
            "Bu plan 4 puan kaybettiriyor. Devam m\u0131?",
            True,
        ),
        (
            "Plan 3 uses 2 free transfers. Keep it?",
            "Plan 3, 2 ücretsiz transfer kullan\u0131yor. Kals\u0131n m\u0131?",
            True,
        ),
        (
            "This plan gives you 61 points. Should the limit be 3?",
            "Bu plan 61 puan getirecek. S\u0131n\u0131r 3 mü olsun?",
            True,
        ),
        (
            "Projected net points: 57.8. Apply the week 3 rule?",
            "Beklenen net puan: 57,8. 3. hafta kural\u0131 uygulans\u0131n m\u0131?",
            True,
        ),
    ],
)
def test_clarification_separates_rule_inputs_from_computed_outcomes(
    mode, locale, english, turkish, claims_result
):
    body = request()
    body["locale"] = locale
    if mode != "catalogue":
        body.pop("plan_context")
    message = turkish if locale == "tr" else english
    neutral = (
        "Hangi plan\u0131 ya da oyuncuyu kastediyorsun?"
        if locale == "tr"
        else "Which plan or player do you mean?"
    )
    result = check_reply(
        parse_intent_request(body),
        {"status": "clarification", "message": message},
        llmopt_vnext=mode != "off",
    )
    assert result == {
        "status": "clarification",
        "message": neutral if mode == "catalogue" and claims_result else message,
    }


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
    command = reply_schema["properties"]["plan_command"]
    assert set(command) == {"anyOf"}
    object_branch, null_branch = command["anyOf"]
    assert object_branch["type"] == "object" and object_branch["additionalProperties"] is False
    assert null_branch == {"type": "null"}
    assert (
        json.loads(contract_schema_path("llmopt_intent_v1").read_text(encoding="utf-8"))
        == reply_schema
    )
