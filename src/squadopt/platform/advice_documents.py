"""The public read contracts: what the advice route and the league route may serve.

The cache stores bytes and the api serves them verbatim — that is the design, and it
is exactly why the boundary needs its own contract: without one, a cache writer or a
corrupted disk entry could make the api publish arbitrary JSON while the route claims
a versioned answer. These schemas are that contract, committed beside the other wire
schemas, validated **at read** (a corrupted entry is an internal error, never a
published document) and by the compute adapter at write when the composition root
lands — the worker itself stays ignorant of document semantics by design.

The advice document is the league tree's own envelope — the same
``provisional_league_ui_v1`` bytes the static site serves — so the two distribution
paths cannot drift apart. The payload keeps ``additionalProperties`` open because the
producer grows honest fields (``solver_status`` arrived that way); the required core
and its types are the contract.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Final

import jsonschema

LEAGUE_STATE_CONTRACT_VERSION: Final = "league_state_v1"
ADVICE_READ_SCHEMA_PATH: Final = Path("docs") / "contracts" / "advice_read_v1.schema.json"
LEAGUE_STATE_SCHEMA_PATH: Final = Path("docs") / "contracts" / "league_state_v1.schema.json"


class AdviceDocumentError(ValueError):
    """Bytes that claim to be a versioned advice answer, and are not."""


def advice_read_schema() -> dict[str, Any]:
    """The strict shape of one served advice document."""

    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://squadopt.dev/contracts/advice_read_v1.schema.json",
        "title": "SquadOpt served advice document",
        "type": "object",
        "properties": {
            "contract_version": {"type": "string", "const": "provisional_league_ui_v1"},
            "generated_at_utc": {"type": "string", "pattern": "Z$"},
            "source_kind": {"type": "string"},
            "payload": {
                "type": "object",
                "properties": {
                    "season": {"type": "string"},
                    "gameweek": {"type": "integer", "minimum": 1},
                    "entry_id": {"type": "integer", "minimum": 1},
                    "league_id": {"type": "integer", "minimum": 1},
                    "mode": {"type": "string"},
                    "window": {"type": "integer", "enum": [1, 3, 5]},
                    "moves": {"type": "array"},
                    "data_quality": {"type": "string"},
                    "missing_fields": {"type": "array", "items": {"type": "string"}},
                },
                "required": [
                    "season",
                    "gameweek",
                    "entry_id",
                    "league_id",
                    "mode",
                    "window",
                    "moves",
                    "data_quality",
                    "missing_fields",
                ],
                "additionalProperties": True,
            },
        },
        "required": ["contract_version", "generated_at_utc", "source_kind", "payload"],
        "additionalProperties": False,
    }


def league_state_schema() -> dict[str, Any]:
    """The strict shape of the league-connection answer."""

    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://squadopt.dev/contracts/league_state_v1.schema.json",
        "title": "SquadOpt league connection state",
        "type": "object",
        "properties": {
            "contract_version": {"type": "string", "const": LEAGUE_STATE_CONTRACT_VERSION},
            "league_id": {"type": "integer", "minimum": 1},
            "connected": {"type": "boolean"},
            "league_name": {"anyOf": [{"type": "string"}, {"type": "null"}]},
            "season": {"anyOf": [{"type": "string"}, {"type": "null"}]},
            "gameweek": {"anyOf": [{"type": "integer"}, {"type": "null"}]},
            "member_count": {"type": "integer", "minimum": 0},
        },
        "required": ["contract_version", "league_id", "connected"],
        "additionalProperties": False,
    }


_ADVICE_VALIDATOR: Final = jsonschema.Draft202012Validator(advice_read_schema())
_LEAGUE_STATE_VALIDATOR: Final = jsonschema.Draft202012Validator(league_state_schema())


def validate_advice_document(raw: bytes) -> None:
    """Refuse bytes that do not carry the versioned advice shape."""

    try:
        document = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise AdviceDocumentError("The advice document is not valid JSON.") from error
    errors = sorted(_ADVICE_VALIDATOR.iter_errors(document), key=str)
    if errors:
        raise AdviceDocumentError(
            f"The advice document violates advice_read_v1: {errors[0].message}"
        )


def validate_league_state(document: dict[str, object]) -> None:
    errors = sorted(_LEAGUE_STATE_VALIDATOR.iter_errors(document), key=str)
    if errors:
        raise AdviceDocumentError(f"The league state violates league_state_v1: {errors[0].message}")


def write_public_read_schemas() -> tuple[Path, Path]:
    """Commit both schemas, the same way the other wire contracts are committed."""

    for path, schema in (
        (ADVICE_READ_SCHEMA_PATH, advice_read_schema()),
        (LEAGUE_STATE_SCHEMA_PATH, league_state_schema()),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(schema, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
    return ADVICE_READ_SCHEMA_PATH, LEAGUE_STATE_SCHEMA_PATH
