"""Intent preparation validates the model output without submitting a solve."""

import json
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime
from types import SimpleNamespace
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


@pytest.mark.parametrize(
    ("header", "expected"),
    [("27", 27), (None, 60), ("invalid", 60), ("http-date", 90)],
)
def test_upstream_rate_limit_returns_retry_after(
    monkeypatch: pytest.MonkeyPatch, header: str | None, expected: int
) -> None:
    retry_after = (
        format_datetime(datetime.now(UTC) + timedelta(seconds=expected), usegmt=True)
        if header == "http-date"
        else header
    )

    def connection(*_args: Any, **_kwargs: Any) -> SimpleNamespace:
        return SimpleNamespace(
            request=lambda *_args, **_kwargs: None,
            getresponse=lambda: SimpleNamespace(
                status=429, getheader={"Retry-After": retry_after}.get
            ),
            close=lambda: None,
        )

    monkeypatch.setattr("squadopt.platform.llmopt_intent.HTTPSConnection", connection)
    provider = OpenAIIntentProvider(api_key="test-key", model="test-model", provider="gemini")
    with TestClient(create_app(llmopt_intent=IntentService(provider))) as client:
        response = client.post(URL, json=_request())
    assert response.status_code == 429
    assert response.json()["error"]["code"] == "RATE_LIMITED"
    assert response.headers["cache-control"] == "no-store"
    seconds = int(response.headers["retry-after"])
    if header == "http-date":
        assert expected - 5 <= seconds <= expected
    else:
        assert seconds == expected


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


@pytest.mark.parametrize("reference_weeks", [[1, 2, 3], [2], []])
def test_revision_interprets_a_frozen_week_and_a_bank_floor(reference_weeks: list[int]) -> None:
    def provider(request: IntentRequest) -> object:
        assert request.reference_weeks == tuple(reference_weeks)
        return {
            "status": "draft",
            "draft": {
                "hard": [{"kind": "no_hits", "player_id": None}],
                "soft": [],
                "comparison": None,
                "window": None,
                "keep_weeks": [1],
                "min_bank": {"tenths": 5, "week": 2},
            },
            "message": None,
        }

    body = {
        **_request(),
        "message": "İlk haftay\u0131 koru, ikinci hafta sonunda £0,5m kals\u0131n.",
        "reference_weeks": reference_weeks,
    }
    with TestClient(create_app(llmopt_intent=IntentService(provider))) as client:
        response = client.post(URL, json=body)
    assert response.status_code == 200
    if 1 in reference_weeks:
        assert response.json() == {
            "status": "draft",
            "draft": {
                "hard": [{"kind": "no_hits"}],
                "soft": [],
                "window": 3,
                "keep_weeks": [1],
                "min_bank": {"tenths": 5, "week": 2},
            },
        }
    else:
        assert response.json()["status"] == "clarification"
        assert "hesaplayal" in response.json()["message"]


@pytest.mark.parametrize(
    ("kind", "week", "tenths", "canonical"),
    [
        ("unavailable", None, None, {"kind": "unavailable", "player_id": 1}),
        (
            "price_increase",
            2,
            1,
            {"kind": "price_increase", "player_id": 1, "week": 2, "tenths": 1},
        ),
    ],
)
def test_interprets_a_scenario_using_the_captured_reference(
    kind: str, week: int | None, tenths: int | None, canonical: dict[str, object]
) -> None:
    def provider(request: IntentRequest) -> object:
        assert request.reference_captains == ((1, 1),)
        return {
            "status": "draft",
            "draft": {
                "hard": [],
                "soft": [],
                "comparison": None,
                "window": 3,
                "scenario": {"kind": kind, "week": week, "tenths": tenths, "player_id": 1},
            },
            "message": None,
        }

    body = {
        **_request(),
        "reference_weeks": [1, 2, 3],
        "reference_captains": [{"week": 1, "player_id": 1}],
    }
    with TestClient(create_app(llmopt_intent=IntentService(provider))) as client:
        response = client.post(URL, json=body)
        assert response.status_code == 200
        assert response.json()["draft"]["scenario"] == canonical
        unknown = body | {"reference_captains": [{"week": 1, "player_id": 2}]}
        assert client.post(URL, json=unknown).status_code == 422


def test_wildcard_is_a_chip_instruction_with_no_player_id() -> None:
    def provider(request: IntentRequest) -> object:
        assert request.message == "Wildcard kullan, Salah kadroda kals\u0131n."
        return {
            "status": "draft",
            "draft": {
                "hard": [
                    {"kind": "wildcard", "player_id": None},
                    {"kind": "keep_player", "player_id": 1},
                ],
                "soft": [],
                "comparison": None,
            },
            "message": None,
        }

    body = _request()
    body["message"] = "Wildcard kullan, Salah kadroda kals\u0131n."
    with TestClient(create_app(llmopt_intent=IntentService(provider))) as client:
        response = client.post(URL, json=body)
    assert response.status_code == 200
    assert response.json()["draft"]["hard"] == [
        {"kind": "wildcard"},
        {"kind": "keep_player", "player_id": 1},
    ]


@pytest.mark.parametrize(
    ("target", "kind"),
    [("haftaya Saka'y\u0131 al", "buy_player"), ("haftaya Saka kadromda olsun", "include_player")],
)
def test_three_week_draft_preserves_exact_transfer_and_membership_intents(
    target: str, kind: str
) -> None:
    message = f"Bu hafta transferi sakla, {target}, üç haftada en fazla 4 puan ceza öde."
    expected: dict[str, Any] = {
        "hard": [
            {"kind": "hold_transfers", "week": 1},
            {"kind": kind, "player_id": 2, "week": 2},
            {"kind": "hit_budget", "points": 4},
        ],
        "soft": [],
        "window": 3,
    }

    def provider(request: IntentRequest) -> object:
        previous = expected if request.message != message else {"hard": [], "soft": [], "window": 1}
        assert request.draft == previous
        assert request.players[-1]["name"] == "Bukayo Saka"
        hard = [
            {"player_id": None, "week": None, "points": None, **rule} for rule in expected["hard"]
        ]
        if request.message != message:
            hard.append({"kind": "save_chips", "week": 3, "player_id": None})
        return {
            "status": "draft",
            "draft": {"hard": hard, "soft": [], "comparison": None, "window": None},
            "message": None,
        }

    body = {
        **_request(),
        "message": message,
        "draft": {"hard": [], "soft": [], "window": 1},
        "players": [*_request()["players"], {"id": 2, "name": "Bukayo Saka", "team": "Arsenal"}],
    }
    with TestClient(create_app(llmopt_intent=IntentService(provider))) as client:
        response = client.post(URL, json=body)
        assert response.status_code == 200
        assert response.json() == {"status": "draft", "draft": expected}
        follow_up = client.post(
            URL,
            json={
                **body,
                "message": "Üçüncü hafta chip kullanma",
                "draft": response.json()["draft"],
            },
        )
        assert follow_up.status_code == 200
        assert follow_up.json()["draft"] == {
            **expected,
            "hard": [*expected["hard"], {"kind": "save_chips", "week": 3}],
        }


@pytest.mark.parametrize(
    "draft",
    [
        {"hard": [], "window": 2},
        {"hard": [], "window": True},
        {"hard": [{"kind": "wildcard", "week": 4}]},
        {"hard": [{"kind": "wildcard", "week": True}]},
        {"hard": [{"kind": "wildcard", "week": 2}], "window": 1},
        {"hard": [{"kind": "buy_player", "player_id": 1}]},
        {"hard": [{"kind": "hit_budget", "points": 4, "week": 2}]},
        {"hard": [{"kind": "hit_budget", "points": -4}]},
        {"hard": [{"kind": "hit_budget", "points": 61}]},
        {"hard": [{"kind": "hit_budget", "points": False}]},
        {"hard": [{"kind": "hold_transfers", "points": 4}]},
    ],
)
def test_invalid_week_or_penalty_budget_never_reaches_provider(draft: dict[str, Any]) -> None:
    def provider(_request: IntentRequest) -> object:
        pytest.fail("Invalid scheduled draft reached the provider.")

    with TestClient(create_app(llmopt_intent=IntentService(provider))) as client:
        response = client.post(URL, json={**_request(), "draft": {"soft": [], **draft}})
    assert response.status_code == 422


def test_same_rule_in_two_weeks_and_zero_total_budget_are_preserved() -> None:
    draft: dict[str, Any] = {
        "hard": [
            {"kind": "hold_transfers", "week": 1},
            {"kind": "hold_transfers", "week": 2},
            {"kind": "hit_budget", "points": 0},
        ],
        "soft": [],
        "window": 3,
    }

    def provider(request: IntentRequest) -> object:
        assert request.draft == draft
        return {
            "status": "draft",
            "draft": {
                **draft,
                "hard": [{"player_id": None, **item} for item in draft["hard"]],
                "comparison": None,
            },
            "message": None,
        }

    with TestClient(create_app(llmopt_intent=IntentService(provider))) as client:
        response = client.post(URL, json={**_request(), "draft": draft})
    assert response.status_code == 200
    assert response.json() == {"status": "draft", "draft": draft}


def test_prices_one_named_soft_rule_without_weakening_hard_wildcard_and_club_requirements() -> None:
    message = (
        "Wildcard kullan, Brighton'dan 3 oyuncu al. Saka'y\u0131 tutmak üç haftada en fazla "
        "1,5 beklenen puana mal oluyorsa tut. Tercihen üçüncü hafta transferi sakla."
    )
    expected: dict[str, Any] = {
        "window": 3,
        "hard": [
            {"kind": "wildcard"},
            {
                "kind": "club_count",
                "club": "Brighton",
                "count": 3,
                "scope": "transfers_in",
                "week": 1,
            },
        ],
        "soft": [
            {"kind": "keep_player", "player_id": 2, "max_cost_tenths": 15},
            {"kind": "hold_transfers", "week": 3},
        ],
    }

    def provider(request: IntentRequest) -> object:
        follow_up = request.message != message
        assert request.draft == (expected if follow_up else {"hard": [], "soft": []})
        assert request.clubs == ("Arsenal", "Brighton")
        price = 0 if follow_up else 15
        return {
            "status": "draft",
            "draft": {
                **expected,
                "hard": [{"player_id": None, **rule} for rule in expected["hard"]],
                "soft": [
                    {**expected["soft"][0], "max_cost_tenths": price},
                    {**expected["soft"][1], "player_id": None, "max_cost_tenths": None},
                ],
                "comparison": None,
            },
            "message": None,
        }

    body = {
        "locale": "tr",
        "message": message,
        "draft": {"hard": [], "soft": []},
        "players": [
            {"id": 2, "name": "Bukayo Saka", "team": "Arsenal", "held": True},
            {"id": 3, "name": "Brighton Player", "team": "Brighton"},
        ],
    }
    with TestClient(create_app(llmopt_intent=IntentService(provider))) as client:
        response = client.post(URL, json=body)
        assert response.status_code == 200
        assert response.json() == {"status": "draft", "draft": expected}
        follow_up = client.post(
            URL,
            json={
                **body,
                "message": "Saka için hiç puan kaybetme, diğer tercihler ayn\u0131.",
                "draft": response.json()["draft"],
            },
        )
        assert follow_up.status_code == 200
        assert follow_up.json()["draft"] == {
            **expected,
            "soft": [{**expected["soft"][0], "max_cost_tenths": 0}, expected["soft"][1]],
        }


@pytest.mark.parametrize(
    ("section", "allowance"),
    [
        ("hard", 15),
        ("comparison", 15),
        ("soft", True),
        ("soft", "15"),
        ("soft", 1.5),
        ("soft", -1),
        ("soft", 1001),
        ("soft", None),
    ],
)
def test_refuses_misplaced_or_invalid_wish_cost_in_confirmed_draft(
    section: str, allowance: Any
) -> None:
    def provider(_request: IntentRequest) -> object:
        pytest.fail("Invalid cost reached the provider.")

    preference = {"kind": "keep_player", "player_id": 1, "max_cost_tenths": allowance}
    draft: dict[str, Any] = {"hard": [], "soft": []}
    draft[section] = preference if section == "comparison" else [preference]
    with TestClient(create_app(llmopt_intent=IntentService(provider))) as client:
        response = client.post(URL, json={**_request(), "draft": draft})
    assert response.status_code == 422


@pytest.mark.parametrize("section", ["hard", "comparison"])
def test_provider_must_not_attach_cost_to_a_requirement_or_comparison(section: str) -> None:
    def provider(_request: IntentRequest) -> object:
        result = _proposed()
        draft = result["draft"]
        rule = draft[section] if section == "comparison" else draft[section][0]
        rule["max_cost_tenths"] = 15
        return result

    with TestClient(create_app(llmopt_intent=IntentService(provider))) as client:
        response = client.post(URL, json=_request())
    assert response.status_code == 503


@pytest.mark.parametrize(
    ("user_message", "scope", "expected_scope"),
    [
        ("Brighton'dan 3 oyuncu al", "transfers_in", {"scope": "transfers_in"}),
        ("Kadromda 3 Brighton oyuncusu olsun", "squad", {}),
    ],
)
def test_club_request_uses_canonical_name_and_keeps_both_scopes_distinct(
    user_message: str, scope: str, expected_scope: dict[str, str]
) -> None:
    body = _request()
    body["message"] = user_message
    # All the Brighton names are unheld and absent from the player shortlist.
    body["players"] = [
        {"id": player_id, "name": f"Other {player_id}", "team": "Brighton"}
        for player_id in range(2, 900)
    ] + _request()["players"]

    def provider(request: IntentRequest) -> object:
        assert request.message == user_message
        assert request.clubs == ("Brighton", "LIV")
        assert tuple(player["id"] for player in request.players) == (1,)
        return {
            "status": "draft",
            "draft": {
                "hard": [
                    {
                        "kind": "no_hits",
                        "player_id": None,
                        "club": None,
                        "count": None,
                        "scope": None,
                    },
                    {
                        "kind": "club_count",
                        "player_id": None,
                        "club": "brighton",
                        "count": 3,
                        "scope": scope,
                    },
                ],
                "soft": [],
                "comparison": None,
            },
            "message": None,
        }

    with TestClient(create_app(llmopt_intent=IntentService(provider))) as client:
        response = client.post(URL, json=body)
    assert response.status_code == 200
    assert response.json()["draft"]["hard"] == [
        {"kind": "no_hits"},
        {"kind": "club_count", "club": "Brighton", "count": 3, **expected_scope},
    ]


@pytest.mark.parametrize(
    "override",
    [
        {"club": "Invented FC"},
        {"count": False},
        {"count": 0},
        {"count": 4},
        {"count": "2"},
        {"player_id": 1},
        {"scope": "bench"},
        {"both": True},
    ],
)
def test_club_constraint_refuses_invented_or_invalid_fields(override: dict[str, Any]) -> None:
    def provider(_request: IntentRequest) -> object:
        result = _proposed()
        result["draft"]["comparison"] = {
            "kind": "club_count",
            "club": "LIV",
            "count": 3,
            "scope": "squad",
            "player_id": None,
            "both": False,
            **override,
        }
        return result

    with TestClient(create_app(llmopt_intent=IntentService(provider))) as client:
        response = client.post(URL, json=_request())
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "LLMOPT_UNAVAILABLE"


def test_confirmed_club_rules_stay_canonical_and_conflicting_hard_counts_are_refused() -> None:
    body = _request()
    first = {"kind": "club_count", "club": "LIV", "count": 3}
    second = {**first, "count": 2}
    new_arrivals = {**second, "scope": "transfers_in"}
    body["draft"] = {"hard": [first, new_arrivals], "soft": [second]}

    def provider(request: IntentRequest) -> object:
        assert request.draft == body["draft"]
        return {"status": "clarification", "draft": None, "message": "Which plan?"}

    with TestClient(create_app(llmopt_intent=IntentService(provider))) as client:
        assert client.post(URL, json=body).status_code == 200
        conflicted = {**body, "draft": {"hard": [first, second], "soft": []}}
        assert client.post(URL, json=conflicted).status_code == 422


@pytest.mark.parametrize("kind", ["keep_player", "avoid_player"])
def test_model_comparison_accepts_either_side_for_a_held_player(kind: str) -> None:
    def provider(_request: IntentRequest) -> object:
        result = _proposed()
        result["draft"]["comparison"]["kind"] = kind
        return result

    with TestClient(create_app(llmopt_intent=IntentService(provider))) as client:
        response = client.post(URL, json=_request())
        assert response.status_code == 200
        assert response.json()["draft"] == {
            "hard": [{"kind": "no_hits"}],
            "soft": [],
            "comparison": {"kind": "include_player", "player_id": 1, "both": True},
        }
        invalid = _request()
        invalid["draft"]["comparison"] = {"kind": kind, "player_id": 1, "both": True}
        assert client.post(URL, json=invalid).status_code == 422


@pytest.mark.parametrize(
    "comparison",
    [
        {"kind": "include_player", "player_id": 2, "both": True},
        {"kind": "include_player", "player_id": True, "both": False},
        {"kind": "no_hits", "player_id": None, "both": True},
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


@pytest.mark.parametrize(
    "message", ["Palmer\u2019\u0131 al", "Palmer'i al", "Palmer\u0131 al", "Palmeri al"]
)
def test_full_roster_includes_unheld_player_with_turkish_object_suffix(message: str) -> None:
    body = _request()
    body["message"] = message
    body["players"] = [
        {"id": player_id, "name": f"Other {player_id}", "team": "Arsenal"}
        for player_id in range(2, 67)
    ] + [{"id": 1, "name": "Cole Palmer", "team": "Chelsea", "held": False}]

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


@pytest.mark.parametrize("provider", ["openai", "gemini"])
def test_provider_sends_strict_schema_and_handles_wire_without_network(
    monkeypatch: pytest.MonkeyPatch,
    provider: str,
) -> None:
    def post(_provider: OpenAIIntentProvider, payload: bytes) -> bytes:
        body = json.loads(payload)
        assert body["model"] == "selected-model"
        if provider == "gemini":
            assert body["reasoning_effort"] == "minimal"
            assert "store" not in body
        else:
            assert body["store"] is False
            assert "reasoning_effort" not in body
        schema = body["response_format"]["json_schema"]
        assert schema["strict"] is True
        assert "oneOf" not in schema["schema"]
        draft_properties = schema["schema"]["properties"]["draft"]["anyOf"][0]["properties"]
        assert draft_properties["window"]["enum"] == [1, 3, None]
        constraint = draft_properties["hard"]["items"]
        assert {"club_count", "buy_player", "hit_budget"} <= set(
            constraint["properties"]["kind"]["enum"]
        )
        assert {"club", "count", "scope", "week", "points"} <= set(constraint["required"])
        soft_constraint = draft_properties["soft"]["items"]
        assert soft_constraint["properties"]["max_cost_tenths"] == {"type": ["integer", "null"]}
        assert "max_cost_tenths" in soft_constraint["required"]
        assert "max_cost_tenths" not in constraint["properties"]
        assert "max_cost_tenths" not in draft_properties["comparison"]["anyOf"][0]["properties"]
        context = json.loads(body["messages"][1]["content"])
        assert context["message"] == "The Liverpool player"
        assert context["clubs"] == ["LIV"]
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
        {
            "SQUADOPT_LLMOPT_API_KEY": "server-key",
            "SQUADOPT_LLMOPT_MODEL": "selected-model",
            "SQUADOPT_LLMOPT_PROVIDER": provider,
        }
    )
    body = {
        **_request(),
        "message": "The Liverpool player",
        "clarification": {"message": "Compare Salah in and out", "question": "Which player?"},
    }
    with TestClient(create_app(llmopt_intent=service)) as client:
        assert client.post(URL, json=body).status_code == 200
