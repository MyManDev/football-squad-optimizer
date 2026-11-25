"""Bounded decision-only catalogue for conversations about computed plans."""

from __future__ import annotations

import re
from typing import Any

_DIGEST = re.compile(r"[0-9a-f]{64}")
ACTIONS = ("select", "freeze_transfer", "freeze_week", "substitute")
PLAN_LABELS = tuple(f"P{i}" for i in range(1, 13))
MAX_PLAYER_ID = 2**53 - 1


def _digest(value: object) -> str:
    if not isinstance(value, str) or _DIGEST.fullmatch(value) is None:
        raise ValueError("Invalid plan identity.")
    return value


def _valid_player(value: object, roster: set[int] | None) -> bool:
    return type(value) is int and 0 < value <= MAX_PLAYER_ID and (roster is None or value in roster)


def _ids(value: object, roster: set[int] | None) -> list[int]:
    if (
        not isinstance(value, list)
        or len(value) > 15
        or any(not _valid_player(item, roster) for item in value)
        or len(set(value)) != len(value)
    ):
        raise ValueError("Invalid plan players.")
    return sorted(value)


def checked_plan_context(value: object, roster: set[int] | None) -> dict[str, Any]:
    if not isinstance(value, dict) or value.keys() != {
        "data_id",
        "kind",
        "selected_plan_id",
        "plans",
    }:
        raise ValueError("Invalid plan context.")
    data_id = _digest(value["data_id"])
    if value["kind"] not in ("server", "device"):
        raise ValueError("Invalid plan data kind.")
    plans = value["plans"]
    if not isinstance(plans, list) or not 1 <= len(plans) <= len(PLAN_LABELS):
        raise ValueError("Invalid plan catalogue.")
    result = []
    seen = set()
    for plan in plans:
        if not isinstance(plan, dict) or plan.keys() != {"plan_id", "data_id", "weeks"}:
            raise ValueError("Invalid catalogue plan.")
        plan_id = _digest(plan["plan_id"])
        if plan_id in seen or plan["data_id"] != data_id:
            raise ValueError("Duplicate or stale catalogue plan.")
        seen.add(plan_id)
        weeks = plan["weeks"]
        if not isinstance(weeks, list) or len(weeks) not in (1, 3):
            raise ValueError("Invalid catalogue weeks.")
        checked = []
        for index, week in enumerate(weeks, 1):
            if (
                not isinstance(week, dict)
                or week.keys()
                != {"week", "transfers_in", "transfers_out", "chip", "captain", "players"}
                or type(week["week"]) is not int
                or week["week"] != index
                or week["chip"] not in (None, "wildcard", "freehit", "bboost", "3xc")
                or (week["captain"] is not None and not _valid_player(week["captain"], roster))
            ):
                raise ValueError("Invalid catalogue week.")
            squad = _ids(week["players"], roster)
            if len(squad) not in (0, 15):
                raise ValueError("Invalid catalogue squad.")
            incoming = _ids(week["transfers_in"], roster)
            outgoing = _ids(week["transfers_out"], roster)
            if len(incoming) != len(outgoing) or set(incoming) & set(outgoing):
                raise ValueError("Invalid catalogue transfers.")
            checked.append(
                {**week, "players": squad, "transfers_in": incoming, "transfers_out": outgoing}
            )
        result.append({"plan_id": plan_id, "data_id": data_id, "weeks": checked})
    selected = value["selected_plan_id"]
    if selected is not None:
        selected = _digest(selected)
    if selected is not None and selected not in seen:
        raise ValueError("Selected plan is outside the catalogue.")
    return {
        "data_id": data_id,
        "kind": value["kind"],
        "selected_plan_id": selected,
        "plans": result,
    }


def provider_plan_context(context: dict[str, Any]) -> dict[str, Any]:
    """Expose only the short labels and decisions for the exact ordered catalogue."""
    selected = None
    plans = []
    for label, plan in zip(PLAN_LABELS, context["plans"], strict=False):
        if plan["plan_id"] == context["selected_plan_id"]:
            selected = label
        plans.append({"plan_label": label, "weeks": plan["weeks"]})
    return {"selected_plan_label": selected, "plans": plans}


def plan_players_current(plan: dict[str, Any], roster: set[int]) -> bool:
    for week in plan["weeks"]:
        if week["captain"] is not None and week["captain"] not in roster:
            return False
        if any(
            not roster.issuperset(week[field])
            for field in ("players", "transfers_in", "transfers_out")
        ):
            return False
    return True


def checked_plan_command(value: object, context: dict[str, Any]) -> dict[str, Any]:
    fields = {"plan_label", "action", "week", "player_id", "replacement_id"}
    if (
        not isinstance(value, dict)
        or not {"plan_label", "action"} <= value.keys()
        or value.keys() - fields
    ):
        raise ValueError("Invalid plan command.")
    labels = PLAN_LABELS[: len(context["plans"])]
    if value["plan_label"] not in labels:
        raise ValueError("Unknown catalogue label.")
    plan = context["plans"][labels.index(value["plan_label"])]
    if plan["data_id"] != context["data_id"]:
        raise ValueError("Stale catalogue plan.")
    action = value["action"]
    if action not in ACTIONS:
        raise ValueError("Unknown plan action.")
    command = {key: item for key, item in value.items() if item is not None}
    needed = {"plan_label", "action"}
    if action in ("freeze_week", "freeze_transfer", "substitute"):
        needed.add("week")
        week = value.get("week")
        if type(week) is not int or not 1 <= week <= len(plan["weeks"]):
            raise ValueError("Unknown plan week.")
        if action == "freeze_transfer":
            needed.add("player_id")
            if (
                type(value.get("player_id")) is not int
                or value["player_id"] not in plan["weeks"][week - 1]["transfers_in"]
            ):
                raise ValueError("Unknown plan transfer.")
        if action == "substitute":
            needed.update(("player_id", "replacement_id"))
            if (
                any(
                    type(value.get(key)) is not int or value[key] <= 0
                    for key in ("player_id", "replacement_id")
                )
                or value["player_id"] == value["replacement_id"]
            ):
                raise ValueError("Invalid substitution.")
            selected = plan["weeks"][week - 1]["players"]
            if value["player_id"] not in selected or value["replacement_id"] in selected:
                raise ValueError("Substitution does not match the selected squad.")
    if command.keys() != needed:
        raise ValueError("Unexpected plan command fields.")
    del command["plan_label"]
    return {**command, "plan_id": plan["plan_id"]}


def plan_command_schema(plan_count: int = len(PLAN_LABELS)) -> dict[str, Any]:
    properties = {
        "plan_label": {"type": "string", "enum": list(PLAN_LABELS[:plan_count])},
        "action": {"type": "string", "enum": list(ACTIONS)},
        "week": {"anyOf": [{"type": "integer", "enum": [1, 2, 3]}, {"type": "null"}]},
        "player_id": {"anyOf": [{"type": "integer"}, {"type": "null"}]},
        "replacement_id": {"anyOf": [{"type": "integer"}, {"type": "null"}]},
    }
    return {
        "anyOf": [
            {
                "type": "object",
                "properties": properties,
                "required": list(properties),
                "additionalProperties": False,
            },
            {"type": "null"},
        ]
    }


def plan_conversation_schema() -> dict[str, Any]:
    """The optional decision catalogue and checked selection command."""
    digest = {"type": "string", "pattern": "^[0-9a-f]{64}$"}
    ids = {
        "type": "array",
        "maxItems": 15,
        "uniqueItems": True,
        "items": {"type": "integer", "minimum": 1, "maximum": MAX_PLAYER_ID},
    }

    def closed(properties: dict[str, Any]) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": properties,
            "required": list(properties),
            "additionalProperties": False,
        }

    week = closed(
        {
            "week": {"type": "integer", "enum": [1, 2, 3]},
            "transfers_in": ids,
            "transfers_out": ids,
            "players": ids,
            "chip": {
                "type": ["string", "null"],
                "enum": [None, "wildcard", "freehit", "bboost", "3xc"],
            },
            "captain": {"type": ["integer", "null"], "minimum": 1, "maximum": MAX_PLAYER_ID},
        }
    )
    plan = closed(
        {
            "plan_id": digest,
            "data_id": digest,
            "weeks": {"type": "array", "minItems": 1, "maxItems": 3, "items": week},
        }
    )
    context = closed(
        {
            "data_id": digest,
            "kind": {"type": "string", "enum": ["device", "server"]},
            "selected_plan_id": {"type": ["string", "null"], "pattern": "^[0-9a-f]{64}$"},
            "plans": {"type": "array", "minItems": 1, "maxItems": 12, "items": plan},
        }
    )
    label = {"type": "string", "enum": list(PLAN_LABELS)}
    provider_context = closed(
        {
            "selected_plan_label": {"anyOf": [label, {"type": "null"}]},
            "plans": {
                "type": "array",
                "minItems": 1,
                "maxItems": len(PLAN_LABELS),
                "items": closed({"plan_label": label, "weeks": plan["properties"]["weeks"]}),
            },
        }
    )
    checked_command = closed(
        {
            "plan_id": digest,
            "action": {"type": "string", "enum": list(ACTIONS)},
            "week": {"type": "integer", "enum": [1, 2, 3]},
            "player_id": {"type": "integer", "minimum": 1},
            "replacement_id": {"type": "integer", "minimum": 1},
        }
    )
    checked_command["required"] = ["plan_id", "action"]
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://squadopt.dev/contracts/llmopt_plans_v1.schema.json",
        "title": "LLMOPT computed-plan conversation",
        "$defs": {
            "context": context,
            "provider_context": provider_context,
            "command": plan_command_schema(),
            "checked_selection": closed(
                {
                    "status": {"type": "string", "const": "plan"},
                    "plan_label": label,
                    "command": checked_command,
                }
            ),
            "session_extension": {
                "type": "object",
                "properties": {"compareOnly": {"type": "boolean"}, "explicit": {"type": "boolean"}},
                "additionalProperties": True,
            },
        },
        "oneOf": [
            {"$ref": f"#/$defs/{name}"}
            for name in ("context", "provider_context", "command", "checked_selection")
        ],
    }
