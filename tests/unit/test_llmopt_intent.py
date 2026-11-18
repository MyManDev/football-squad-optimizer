"""A model's reply becomes a draft only through the check, which submits no solve.

Each test speaks as the page does: it asks for the prompt, lets a stand-in model answer the
request that prompt carries, and has the reply checked.
"""

import json
from collections.abc import Callable
from dataclasses import replace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from squadopt.api.app import create_app
from squadopt.api.llmopt import intent_routes
from squadopt.platform.llmopt_intent import (
    IntentClarification,
    IntentRequest,
    parse_intent_request,
)

PROMPT = "/api/v1/llmopt/prompt"
CHECK = "/api/v1/llmopt/check"


def _interpret(body: dict[str, Any], model: Callable[[IntentRequest], object]) -> Any:
    """One message as the page sends it: the prompt, the model's reply to it, the check.

    ``model`` gets the request as the prompt carries it, its players the shortlist. A body
    the prompt refuses never reaches the model, and that refusal is the answer.
    """
    with TestClient(create_app()) as client:
        prompt = client.post(PROMPT, json=body)
        if prompt.status_code != 200:
            return prompt
        shortlist = tuple(json.loads(prompt.json()["user"])["players"])
        asked = replace(parse_intent_request(body), players=shortlist)
        return client.post(CHECK, json={"request": body, "reply": model(asked)})


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

    response = _interpret(_request(), provider)
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

    response = _interpret(_request(), provider)
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
    response = _interpret(body, provider)
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
    response = _interpret(body, provider)
    assert response.status_code == 200
    assert response.json()["draft"]["scenario"] == canonical
    unknown = body | {"reference_captains": [{"week": 1, "player_id": 2}]}
    assert _interpret(unknown, provider).status_code == 422


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
    response = _interpret(body, provider)
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
    response = _interpret(body, provider)
    assert response.status_code == 200
    assert response.json() == {"status": "draft", "draft": expected}
    follow_up = _interpret(
        {
            **body,
            "message": "Üçüncü hafta chip kullanma",
            "draft": response.json()["draft"],
        },
        provider,
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

    response = _interpret({**_request(), "draft": {"soft": [], **draft}}, provider)
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

    response = _interpret({**_request(), "draft": draft}, provider)
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
    response = _interpret(body, provider)
    assert response.status_code == 200
    assert response.json() == {"status": "draft", "draft": expected}
    follow_up = _interpret(
        {
            **body,
            "message": "Saka için hiç puan kaybetme, diğer tercihler ayn\u0131.",
            "draft": response.json()["draft"],
        },
        provider,
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
    response = _interpret({**_request(), "draft": draft}, provider)
    assert response.status_code == 422


@pytest.mark.parametrize("section", ["hard", "comparison"])
def test_provider_must_not_attach_cost_to_a_requirement_or_comparison(section: str) -> None:
    def provider(_request: IntentRequest) -> object:
        result = _proposed()
        draft = result["draft"]
        rule = draft[section] if section == "comparison" else draft[section][0]
        rule["max_cost_tenths"] = 15
        return result

    response = _interpret(_request(), provider)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "REPLY_REFUSED"


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

    response = _interpret(body, provider)
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
        {"scope": "bench"},
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

    response = _interpret(_request(), provider)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "REPLY_REFUSED"


def test_confirmed_club_rules_stay_canonical_and_conflicting_hard_counts_are_refused() -> None:
    body = _request()
    first = {"kind": "club_count", "club": "LIV", "count": 3}
    second = {**first, "count": 2}
    new_arrivals = {**second, "scope": "transfers_in"}
    body["draft"] = {"hard": [first, new_arrivals], "soft": [second]}

    def provider(request: IntentRequest) -> object:
        assert request.draft == body["draft"]
        return {"status": "clarification", "draft": None, "message": "Which plan?"}

    assert _interpret(body, provider).status_code == 200
    conflicted = {**body, "draft": {"hard": [first, second], "soft": []}}
    assert _interpret(conflicted, provider).status_code == 422


@pytest.mark.parametrize("kind", ["keep_player", "avoid_player"])
def test_model_comparison_accepts_either_side_for_a_held_player(kind: str) -> None:
    def provider(_request: IntentRequest) -> object:
        result = _proposed()
        result["draft"]["comparison"]["kind"] = kind
        return result

    response = _interpret(_request(), provider)
    assert response.status_code == 200
    assert response.json()["draft"] == {
        "hard": [{"kind": "no_hits"}],
        "soft": [],
        "comparison": {"kind": "include_player", "player_id": 1, "both": True},
    }
    invalid = _request()
    invalid["draft"]["comparison"] = {"kind": kind, "player_id": 1, "both": True}
    assert _interpret(invalid, provider).status_code == 422


@pytest.mark.parametrize(
    "comparison",
    [
        {"kind": "include_player", "player_id": 2, "both": True},
        {"kind": "include_player", "player_id": True, "both": False},
        {"kind": "execute", "player_id": None, "both": False},
    ],
)
def test_rejects_invalid_provider_draft(comparison: dict[str, Any]) -> None:
    def provider(_request: IntentRequest) -> object:
        result = _proposed()
        result["draft"]["comparison"] = comparison
        return result

    response = _interpret(_request(), provider)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "REPLY_REFUSED"


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

    response = _interpret(body, provider)
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

    response = _interpret(body, provider)
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

    response = _interpret(body, provider)
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

    response = _interpret({**_request(), "clarification": clarification}, provider)
    assert response.status_code == 422


def test_refuses_constraint_repeated_across_strengths() -> None:
    def provider(_request: IntentRequest) -> object:
        proposal = _proposed()
        proposal["draft"]["soft"] = list(proposal["draft"]["hard"])
        return proposal

    response = _interpret(_request(), provider)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "REPLY_REFUSED"


def test_a_request_that_does_not_hold_gets_no_prompt() -> None:
    headers = {"Content-Type": "application/json"}
    with TestClient(create_app()) as client:
        repeated = client.post(PROMPT, content='{"draft":{},"draft":{}}', headers=headers)
        assert repeated.status_code == 422
        assert client.post(PROMPT, json={**_request(), "model": "arbitrary"}).status_code == 422
        assert client.post(PROMPT, json=_request()).status_code == 200


# Cloudflare appends the visitor's address to X-Forwarded-For, cloudflared passes it on,
# and Docker's port proxy makes the Compose network's gateway the api's TCP peer.
# deploy/compose.yaml runs uvicorn with --proxy-headers, and the host's FORWARDED_ALLOW_IPS
# names that gateway (deploy/weekly-schedule/README.md, "Members' addresses").
_GATEWAY = "172.18.0.1"


def _one_a_minute(peer: str) -> TestClient:
    """The keyless routes at one request a minute per visitor, behind the trusted gateway."""
    routes = FastAPI()
    routes.include_router(intent_routes(keyless_per_minute=1))
    return TestClient(ProxyHeadersMiddleware(routes, trusted_hosts=_GATEWAY), client=(peer, 43210))


def test_visitors_behind_the_trusted_proxy_get_separate_buckets() -> None:
    with _one_a_minute(_GATEWAY) as proxy:

        def post(forwarded_for: str) -> int:
            return proxy.post(
                PROMPT, json=_request(), headers={"X-Forwarded-For": forwarded_for}
            ).status_code

        assert post("198.51.100.7") == 200
        assert post("203.0.113.8") == 200
        assert post("198.51.100.7") == 429
        # A visitor's own header comes first; Cloudflare's appended address decides.
        assert post("203.0.113.99, 198.51.100.7") == 429
        assert post("2001:db8:1:1::5") == 200
        # One IPv6 subscriber holds a whole /64.
        assert post("2001:db8:1:1::6") == 429


def test_forwarded_header_from_an_untrusted_peer_is_ignored() -> None:
    with _one_a_minute("192.0.2.50") as direct:
        first = direct.post(PROMPT, json=_request(), headers={"X-Forwarded-For": "198.51.100.60"})
        spoofed = direct.post(PROMPT, json=_request(), headers={"X-Forwarded-For": "198.51.100.61"})
    assert first.status_code == 200
    assert spoofed.status_code == 429


_FILLED: dict[str, Any] = {"club": None, "count": None, "scope": None, "week": None, "points": None}


@pytest.mark.parametrize(
    ("part", "rule", "expected"),
    [
        # What gemini-3.1-flash-lite sent on 17 Nov for a soft wish to hold Saka.
        (
            "soft",
            {**_FILLED, "kind": "include_player", "player_id": 1, "scope": "squad"}
            | {"max_cost_tenths": None},
            {"kind": "include_player", "player_id": 1},
        ),
        ("hard", {**_FILLED, "kind": "wildcard", "player_id": 1, "week": 1}, None),
        (
            "hard",
            {**_FILLED, "kind": "no_hits", "player_id": None, "club": "LIV", "count": 2},
            None,
        ),
        ("hard", {**_FILLED, "kind": "keep_player", "player_id": 1, "points": 4}, None),
        (
            "hard",
            {**_FILLED, "kind": "hit_budget", "player_id": None, "points": 4, "week": 1},
            {"kind": "hit_budget", "points": 4},
        ),
    ],
)
def test_a_field_with_no_meaning_for_the_rule_is_dropped_from_a_model_reply(
    part: str, rule: dict[str, Any], expected: dict[str, Any] | None
) -> None:
    def provider(_request: IntentRequest) -> object:
        result = _proposed()
        result["draft"]["hard"] = []
        result["draft"]["soft"] = []
        result["draft"]["comparison"] = None
        result["draft"][part] = [rule]
        return result

    response = _interpret(_request(), provider)
    assert response.status_code == 200
    kept = {key: value for key, value in rule.items() if key in ("kind", "player_id", "week")}
    if rule["kind"] in ("wildcard", "no_hits"):
        kept.pop("player_id")
    if kept.get("week") is None:
        kept.pop("week", None)
    assert response.json()["draft"][part] == [expected or kept]


@pytest.mark.parametrize("kind", ["wildcard", "no_hits"])
def test_with_and_without_a_rule_that_is_no_player_is_its_plain_comparison(kind: str) -> None:
    # What gemini-3.1-flash-lite sent for a with-and-without-Wildcard request.
    def provider(_request: IntentRequest) -> object:
        result = _proposed()
        result["draft"]["hard"] = []
        result["draft"]["comparison"] = {**_FILLED, "kind": kind, "player_id": 1, "both": True}
        return result

    response = _interpret(_request(), provider)
    assert response.status_code == 200
    assert response.json()["draft"]["comparison"] == {"kind": kind}


def test_the_page_own_request_is_still_held_to_the_exact_shape() -> None:
    body = _request()
    body["draft"] = {"hard": [{"kind": "no_hits", "scope": "squad"}], "soft": []}
    response = _interpret(body, lambda _request: _proposed())
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_FAILED"
