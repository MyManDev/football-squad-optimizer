"""Public official injury rows: source text and coverage, never participation estimates."""

from typing import Any

# Acquisition and redistribution are not enabled. This is deliberately a code
# capability, with no configuration, environment or command-line override.
OFFICIAL_INJURY_SOURCE_ENABLED = False


def require_official_injury_source() -> None:
    """Refuse operational use while retaining offline parser/schema support."""
    if not OFFICIAL_INJURY_SOURCE_ENABLED:
        raise ValueError("The central official injury source is disabled.")


OFFICIAL_INJURIES_VERSION = "official_pl_injuries_v1"
OFFICIAL_INJURIES_URL = "https://www.premierleague.com/en/latest-player-injuries"
OFFICIAL_INJURIES_LIMIT = (
    "Editorial injury rows do not establish absence, expected minutes, or complete squad health."
)


def official_injuries_schema() -> dict[str, Any]:
    """The bounded public subset emitted by OfficialInjuryReport.public_record."""
    names = {"type": "array", "items": {"type": "string", "minLength": 1}, "uniqueItems": True}
    fact = {
        "player_id": {"type": "integer", "minimum": 1},
        "club": {"type": "string", "minLength": 1},
        "injury": {"type": ["string", "null"]},
        "source_date": {"type": ["string", "null"]},
        "details_urls": {
            "type": "array",
            "maxItems": 5,
            "uniqueItems": True,
            "items": {"type": "string", "pattern": r"^https://[^/@\s]+(?:/[^\s]*)?$"},
        },
    }
    fields = {
        "contract_version": {"const": OFFICIAL_INJURIES_VERSION},
        "season": {"type": "string", "pattern": r"^20[0-9]{2}-[0-9]{2}$"},
        "source_url": {"const": OFFICIAL_INJURIES_URL},
        "source_updated_at": {"type": ["string", "null"], "format": "date-time"},
        "observed_at": {"type": "string", "format": "date-time"},
        "roster_clubs": names,
        "received_clubs": names,
        "missing_clubs": names,
        "incomplete_clubs": names,
        "unknown_source_clubs": names,
        "listed_rows": {"type": "integer", "minimum": 0, "maximum": 200},
        "mapped_rows": {"type": "integer", "minimum": 0, "maximum": 200},
        "facts": {
            "type": "array",
            "maxItems": 200,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": fact,
                "required": list(fact),
            },
        },
        "limit": {"const": OFFICIAL_INJURIES_LIMIT},
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": fields,
        "required": list(fields),
    }
