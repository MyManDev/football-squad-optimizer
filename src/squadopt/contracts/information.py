"""Public information facts: source observations never masquerade as new forecasts."""

from typing import Any


def decision_information_schema() -> dict[str, Any]:
    fields = {
        "version": {"const": "football_decision_information_v1"},
        "revision": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
        "source_snapshot_id": {"type": "string", "minLength": 1},
        "observed_at": {"type": ["string", "null"]},
        "coach_news_bound": {"type": "boolean"},
        "minute_components_bound": {"type": "boolean"},
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": fields,
        "required": list(fields),
    }


def official_information_schema() -> dict[str, Any]:
    player = {
        "player_id": {"type": "integer", "minimum": 1},
        "name": {"type": "string"},
        "team_name": {"type": "string"},
        "status": {"type": "string"},
        "source_chance_percent": {"type": ["integer", "null"], "minimum": 0, "maximum": 100},
        "source_added_at": {"type": ["string", "null"]},
        "news_state": {"enum": ["present", "cleared", "not_reported"]},
    }
    fields = {
        "version": {"const": "fpl_information_v1"},
        "season": {"type": "string", "minLength": 1},
        "gameweek": {"type": "integer", "minimum": 1},
        "source_snapshot_id": {"type": "string", "minLength": 1},
        "observed_at": {"type": "string"},
        "revision": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
        "source_url": {"const": "https://fantasy.premierleague.com/"},
        "player_count": {"type": "integer", "minimum": 0},
        "team_count": {"type": "integer", "minimum": 0},
        "declared_team_count": {"type": "integer", "minimum": 0},
        "players": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": player,
                "required": list(player),
            },
        },
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": fields,
        "required": list(fields),
    }
