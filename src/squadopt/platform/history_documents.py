"""The additive public shape of recorded weekly history, without computing any score."""

import json
from pathlib import Path
from typing import Any

from squadopt.application.advice_capabilities import TOP100_WEIGHTS
from squadopt.application.mode_selection import MODE_SLUGS
from squadopt.application.strategies import STRATEGY_CATALOG
from squadopt.application.weekly_suggestion_eval import CONTRACT_VERSION, SUPPORTED_LEAGUE_ID
from squadopt.live.rules import CHIP_NAMES


def history_schema() -> dict[str, Any]:
    text = {"type": "string", "minLength": 1}
    nullable_text = {"type": ["string", "null"], "minLength": 1}
    number = {"type": "number"}
    nullable_number = {"type": ["number", "null"]}
    identifier = {"type": "integer", "minimum": 1}
    chip = {"enum": [None, *CHIP_NAMES]}
    score: dict[str, Any] = {
        "type": "object",
        "properties": {
            key: number for key in ("gross_points", "transfer_hit_points", "net_points")
        },
        "required": ["gross_points", "transfer_hit_points", "net_points"],
    }
    suggested = {
        **score,
        "properties": {
            **score["properties"],
            "captain_bonus_points": number,
            "autosub_points": number,
            "chip": chip,
        },
        "required": [*score["required"], "captain_bonus_points", "autosub_points", "chip"],
    }
    player = {
        "player_id": identifier,
        "name": text,
        "position": {"enum": ["GK", "DEF", "MID", "FWD"]},
        "role": {"enum": ["starter", "bench"]},
        "captain": {"type": "boolean"},
        "vice_captain": {"type": "boolean"},
        "expected_points": nullable_number,
        "realized_points": number,
        "minutes": {"type": "integer", "minimum": 0},
        "multiplier": {"type": "integer", "minimum": 0, "maximum": 3},
        "counted_points": number,
        "forecast_error": nullable_number,
    }
    plan = {
        "published_path": {"type": "string", "pattern": "^advice/[1-9][0-9]*/"},
        "strategy": {"enum": [*STRATEGY_CATALOG, *MODE_SLUGS.values()]},
        "window": {"const": 1},
        "rival_entry_id": {"type": ["integer", "null"], "minimum": 1},
        "chip": chip,
        "captain": nullable_text,
        "moves": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"player_out": nullable_text, "player_in": nullable_text},
                "required": ["player_out", "player_in"],
                "additionalProperties": False,
            },
        },
        "top100_weight": {"enum": list(TOP100_WEIGHTS)},
        "managers_word": {"const": True},
        "expected_points_cost": number,
        "expected_points_cost_ceiling": number,
    }
    week: dict[str, Any] = {
        "gameweek": identifier,
        "status": {"enum": ["available", "unsettled", "unavailable"]},
        "reason": nullable_text,
        "actual_reason": nullable_text,
        **{
            key: {"type": ["string", "null"], "pattern": "Z$"}
            for key in (
                "deadline_utc",
                "advice_captured_at_utc",
                "advice_generated_at_utc",
                "outcome_captured_at_utc",
            )
        },
        "advice_snapshot_id": nullable_text,
        "outcome_snapshot_id": nullable_text,
        "advice_sha256": {"type": ["string", "null"], "pattern": "^[a-f0-9]{64}$"},
        "expected_own_points": nullable_number,
        "net_difference": nullable_number,
        "suggested": {"anyOf": [{"type": "null"}, suggested]},
        "actual": {"anyOf": [{"type": "null"}, score]},
        "players": {
            "type": "array",
            "items": {"type": "object", "properties": player, "required": list(player)},
        },
    }
    required_week = list(week)
    week["recorded_plans"] = {
        "type": "array",
        "items": {
            "type": "object",
            "properties": plan,
            "required": [
                "published_path",
                "strategy",
                "window",
                "rival_entry_id",
                "chip",
                "captain",
                "moves",
            ],
            "additionalProperties": False,
        },
    }
    payload = {
        "league_id": {"const": SUPPORTED_LEAGUE_ID},
        "entry_id": identifier,
        "season": {"type": "string", "pattern": "^[0-9]{4}-[0-9]{2}$"},
        "as_of_snapshot_id": text,
        "weeks": {
            "type": "array",
            "items": {"type": "object", "properties": week, "required": required_week},
        },
    }
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://squadopt.dev/contracts/weekly_suggestion_history_v1.schema.json",
        "type": "object",
        "properties": {
            "contract_version": {"const": CONTRACT_VERSION},
            "generated_at_utc": {"type": "string", "pattern": "Z$"},
            "payload": {"type": "object", "properties": payload, "required": list(payload)},
        },
        "required": ["contract_version", "generated_at_utc", "payload"],
    }


def write_history_schema() -> Path:
    path = Path("docs/contracts/weekly_suggestion_history_v1.schema.json")
    path.write_text(
        json.dumps(history_schema(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return path
