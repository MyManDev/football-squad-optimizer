"""Retained decisions can outlive the player list available to the message."""

import json
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from squadopt.api.llmopt import intent_routes

DATA = "a" * 64
PROMPT = "/api/v1/llmopt/prompt"
CHECK = "/api/v1/llmopt/check"


def roster_request(kind: str) -> dict[str, Any]:
    archived = {
        "week": 1,
        "players": list(range(2, 17)),
        "transfers_in": [16],
        "transfers_out": [1],
        "captain": 16,
        "chip": None,
    }
    current = {
        "week": 1,
        "players": list(range(1, 16)),
        "transfers_in": [],
        "transfers_out": [],
        "captain": 1,
        "chip": None,
    }
    return {
        "message": "No hits.",
        "locale": "en",
        "draft": {"hard": [], "soft": []},
        "players": [{"id": i, "name": f"Player {i}"} for i in range(1, 81) if i != 16],
        "reference_weeks": [1],
        "reference_captains": [{"week": 1, "player_id": 16}],
        "plan_context": {
            "kind": kind,
            "data_id": DATA,
            "selected_plan_id": "b" * 64,
            "plans": [
                {"plan_id": key * 64, "data_id": DATA, "weeks": [week]}
                for key, week in (("b", archived), ("c", current))
            ],
        },
    }


def command(label: str, action: str = "select", **fields: int) -> dict[str, Any]:
    return {"status": "plan", "plan_command": {"plan_label": label, "action": action, **fields}}


@pytest.mark.parametrize("kind", ["device", "server"])
def test_unlisted_historical_player_allows_ordinary_messages_and_only_current_plans(
    kind: str,
) -> None:
    body = roster_request(kind)
    app = FastAPI()
    app.include_router(intent_routes(llmopt_vnext=True, server_data_id=lambda: DATA))
    with TestClient(app) as client:
        prompt = client.post(PROMPT, json=body)
        assert prompt.status_code == 200, prompt.text
        offered = json.loads(prompt.json()["user"])
        assert 16 not in {p["id"] for p in offered["players"]}
        assert not offered.get("reference_captains")
        for reply in (
            {"status": "draft", "draft": {"hard": [{"kind": "no_hits"}], "soft": []}},
            {"status": "clarification", "message": "Which week?"},
        ):
            assert client.post(CHECK, json={"request": body, "reply": reply}).json() == reply
        for reply in (command("P1"), command("P1", "freeze_transfer", week=1, player_id=16)):
            checked = client.post(CHECK, json={"request": body, "reply": reply})
            assert checked.status_code == 422
            assert checked.json()["error"]["code"] == "PLAN_DATA_CHANGED"
        selected = client.post(CHECK, json={"request": body, "reply": command("P2")})
        assert selected.status_code == 200
        assert selected.json()["command"]["plan_id"] == "c" * 64
        for reply in (
            command("P2", "substitute", week=1, player_id=1, replacement_id=16),
            command("P2", "substitute", week=1, player_id=1, replacement_id=80),
            {
                "status": "draft",
                "draft": {"hard": [{"kind": "keep_player", "player_id": 16}], "soft": []},
            },
            command("P3"),
        ):
            checked = client.post(CHECK, json={"request": body, "reply": reply})
            assert checked.status_code == 422
            assert checked.json()["error"]["code"] == "REPLY_REFUSED"


@pytest.mark.parametrize("enabled", [False, True])
def test_malformed_historical_ids_and_unrelated_reference_captains_still_fail_validation(
    enabled: bool,
) -> None:
    app = FastAPI()
    app.include_router(intent_routes(llmopt_vnext=enabled))
    with TestClient(app) as client:
        body = roster_request("device")
        body["reference_captains"][0]["player_id"] = 100
        assert client.post(PROMPT, json=body).json()["error"]["code"] == "VALIDATION_FAILED"
        for player in (False, 0, -1, 2**53, "16"):
            body = roster_request("device")
            body["plan_context"]["plans"][0]["weeks"][0]["players"][-1] = player
            refused = client.post(PROMPT, json=body)
            assert refused.status_code == 422
            assert refused.json()["error"]["code"] == "VALIDATION_FAILED"
        if not enabled:
            body = roster_request("device")
            checked = client.post(CHECK, json={"request": body, "reply": command("P1")})
            assert checked.status_code == 422
            assert checked.json()["error"]["code"] == "VALIDATION_FAILED"
