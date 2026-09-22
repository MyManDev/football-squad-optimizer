"""The complete FPL roster for browsing, independent of the optimizer's pool."""

import json
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from squadopt.data.errors import DataError
from squadopt.data.snapshots import CapturedSnapshot
from squadopt.data.sources.fpl_live import BOOTSTRAP_PAYLOAD, FPL_LIVE_SOURCE
from squadopt.data.timestamps import normalize_utc_timestamp
from squadopt.live import infer_season

POSITIONS = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}


def validate_catalog(document: Any) -> dict[str, Any]:
    """Reject incomplete identities instead of silently reducing the roster."""
    positive = {"type": "integer", "minimum": 1}
    text = {"type": "string", "minLength": 1}

    def closed(properties: dict[str, Any]) -> dict[str, Any]:
        return {
            "type": "object",
            "required": list(properties),
            "additionalProperties": False,
            "properties": properties,
        }

    schema = closed(
        {
            "contract_version": {"const": "player_catalog_v1"},
            "season": {"type": "string", "pattern": r"^[0-9]{4}-[0-9]{2}$"},
            "source_snapshot_id": {"type": "string", "pattern": "^fpl-live-"},
            "captured_at_utc": {"type": "string", "format": "date-time"},
            "teams": {
                "type": "array",
                "minItems": 1,
                "items": closed({"id": positive, "name": text}),
            },
            "players": {
                "type": "array",
                "minItems": 1,
                "items": closed(
                    {
                        "id": positive,
                        "name": text,
                        "team_id": positive,
                        "team": text,
                        "position": {"enum": list(POSITIONS.values())},
                    }
                ),
            },
        }
    )
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(document)
    # JSON Schema's optional RFC3339 checker is not installed in every runtime.
    try:
        normalize_utc_timestamp(document["captured_at_utc"], label="Roster capture time")
    except DataError as exc:
        raise ValueError("Invalid roster capture time") from exc
    teams = {row["id"]: row["name"] for row in document["teams"]}
    players = document["players"]
    if len(teams) != len(document["teams"]) or len({p["id"] for p in players}) != len(players):
        raise ValueError("Duplicate roster identity")
    if any(teams.get(p["team_id"]) != p["team"] for p in players):
        raise ValueError("Unknown or inconsistent roster team")
    return dict(document)


def player_catalog(snapshot: CapturedSnapshot) -> dict[str, Any]:
    if snapshot.metadata.source != FPL_LIVE_SOURCE:
        raise DataError("Player catalog requires an FPL capture")
    bootstrap = json.loads(snapshot.payloads[BOOTSTRAP_PAYLOAD])
    teams = [{"id": row["id"], "name": row["name"]} for row in bootstrap["teams"]]
    names = {row["id"]: row["name"] for row in teams}
    players = [
        {
            # Persist the cross-season player code used by existing comments, not element id.
            "id": row["code"],
            "name": f"{row['first_name']} {row['second_name']}".strip(),
            "team_id": row["team"],
            "team": names[row["team"]],
            "position": POSITIONS[row["element_type"]],
        }
        for row in bootstrap["elements"]
    ]
    return validate_catalog(
        {
            "contract_version": "player_catalog_v1",
            "season": infer_season(snapshot),
            "source_snapshot_id": snapshot.metadata.snapshot_id,
            "captured_at_utc": snapshot.metadata.captured_at_utc,
            "teams": sorted(teams, key=lambda row: row["name"]),
            "players": sorted(players, key=lambda row: (row["name"], row["id"])),
        }
    )
