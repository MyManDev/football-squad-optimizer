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
import math
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

    player = {
        "type": "object",
        "properties": {
            "player_id": {"type": "integer", "minimum": 1},
            "name": {"type": "string"},
            "short_name": {"type": "string"},
            "position": {"enum": ["GK", "DEF", "MID", "FWD"]},
            "team": {"type": "string"},
            "expected_points": {"type": "number"},
        },
        "required": ["player_id", "name", "short_name", "position", "team"],
    }
    chip = {"enum": [None, "bboost", "3xc", "wildcard", "freehit"]}
    plan_week = {
        "type": "object",
        "properties": {
            "gameweek": {"type": "integer", "minimum": 1},
            "transfers_in": {"type": "array", "items": player},
            "transfers_out": {"type": "array", "items": player},
            "transfer_hit_points": {"type": "number"},
            "chip": chip,
            "free_transfers_before": {"type": "integer", "minimum": 0},
            "free_transfers_after": {"type": "integer", "minimum": 0},
            "expected_points": {"type": "number"},
        },
        "required": [
            "gameweek",
            "transfers_in",
            "transfers_out",
            "transfer_hit_points",
            "chip",
            "free_transfers_before",
            "free_transfers_after",
            "expected_points",
        ],
    }
    nullable_number = {"type": ["number", "null"]}
    comparison_fields: dict[str, Any] = {
        "policy_id": {"const": "first_week_rival_horizon_v1"},
        "rival_entry_id": {"type": "integer", "minimum": 1},
        "rival_gameweek": {"type": "integer", "minimum": 1},
        "overlap_scope": {"const": "first_week_squad_vs_captured_rival_xi"},
        "overlap_minimum": {"enum": [None, 9]},
        "overlap_maximum": {"enum": [None, 5]},
        "overlap_actual": {"type": "integer", "minimum": 0, "maximum": 11},
        **{
            name: {"type": "number"}
            for name in (
                "first_week_net_points",
                "control_first_week_net_points",
                "total_net_points",
                "control_total_net_points",
                "net_points_difference",
            )
        },
        **{
            name: {"enum": ["OPTIMAL", "FEASIBLE"]}
            for name in (
                "solver_status",
                "control_solver_status",
            )
        },
        "optimality_gap": nullable_number,
        "control_optimality_gap": nullable_number,
    }
    optional_fields: dict[str, Any] = {
        name: {"type": "number"}
        for name in (
            "transfer_hit_points",
            "expected_points_cost",
            "expected_points_cost_ceiling",
            "overlap_count",
            "expected_gap_vs_rival",
            "transfer_cap",
            "overlap_target",
            "overlap_applied",
        )
    }
    optional_fields.update(
        {
            "source_snapshot_id": {"type": ["string", "null"]},
            "top100_weight_percent": {"type": "integer", "enum": [0, 5, 10, 20, 30, 40, 50]},
            "top100_weight_source": {"enum": ["published", "personal"]},
            "window_comparison": {
                "type": "object",
                "properties": comparison_fields,
                "required": list(comparison_fields),
                "additionalProperties": False,
            },
            "rival_label": {"type": ["string", "null"]},
            "rival_entry_id": {"type": "integer", "minimum": 1},
            "solver_status": {"type": ["string", "null"]},
            "control_solver_status": {"type": ["string", "null"]},
            "optimality_gap": nullable_number,
            "control_optimality_gap": nullable_number,
            "expected_own_points": nullable_number,
            # Null where the comparison against holding could not be walked, which is
            # not the same fact as a plan that gains nothing.
            "expected_gain_vs_hold": nullable_number,
            "captain_agreement": {"type": "boolean"},
            "captain": {"anyOf": [player, {"type": "null"}]},
            "vice_captain": {"anyOf": [player, {"type": "null"}]},
            "starting_xi": {"type": ["array", "null"], "items": player},
            "bench": {"type": ["array", "null"], "items": player},
            "chip": chip,
            "plan_weeks": {"type": ["array", "null"], "items": plan_week},
            "stated_limits": {"type": ["array", "null"], "items": {"type": "string"}},
            "squad_basis": {"type": "string"},
            "plan_kind": {"enum": ["within_free_transfers", "with_hits"]},
            "alternative_plan": {
                "type": ["object", "null"],
                "properties": {
                    "kind": {"enum": ["within_free_transfers", "with_hits"]},
                    "overlap_applied": {"type": "number"},
                    "transfer_hit_points": nullable_number,
                    "expected_points_cost": {"type": "number"},
                    "expected_points_cost_ceiling": {"type": "number"},
                },
                "required": [
                    "kind",
                    "overlap_applied",
                    "transfer_hit_points",
                    "expected_points_cost",
                ],
            },
        }
    )
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://squadopt.dev/contracts/advice_read_v1.schema.json",
        "title": "SquadOpt served advice document",
        "type": "object",
        "properties": {
            "contract_version": {"type": "string", "const": "provisional_league_ui_v1"},
            "generated_at_utc": {"type": "string", "pattern": "Z$"},
            "source_kind": {"enum": ["live", "example"]},
            "payload": {
                "type": "object",
                "properties": {
                    "season": {"type": "string"},
                    "gameweek": {"type": "integer", "minimum": 1},
                    "entry_id": {"type": "integer", "minimum": 1},
                    "league_id": {"type": "integer", "minimum": 1},
                    "mode": {"type": "string"},
                    "window": {"type": "integer", "enum": [1, 3, 5]},
                    "moves": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "move_id": {"type": "string"},
                                "player_out": {"anyOf": [player, {"type": "null"}]},
                                "player_in": {"anyOf": [player, {"type": "null"}]},
                                # Null where the row's share of the plan's gain could
                                # not be measured; the row still names the swap.
                                "expected_points_delta": nullable_number,
                                "reason_code": {
                                    "enum": ["window_value", "mode_tradeoff", "points_gain"]
                                },
                            },
                            "required": [
                                "move_id",
                                "player_out",
                                "player_in",
                                "expected_points_delta",
                                "reason_code",
                            ],
                        },
                    },
                    "data_quality": {"enum": ["complete", "partial", "empty"]},
                    "missing_fields": {"type": "array", "items": {"type": "string"}},
                    **optional_fields,
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
                "dependentRequired": {
                    "top100_weight_percent": ["top100_weight_source"],
                    "top100_weight_source": ["top100_weight_percent"],
                },
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
        document = json.loads(raw, parse_constant=_invalid_number, parse_float=_finite_float)
    except (UnicodeDecodeError, ValueError) as error:
        raise AdviceDocumentError("The advice document is not valid JSON.") from error
    errors = sorted(_ADVICE_VALIDATOR.iter_errors(document), key=str)
    if errors:
        raise AdviceDocumentError(
            f"The advice document violates advice_read_v1: {errors[0].message}"
        )
    payload = document["payload"]
    if ("top100_weight_percent" in payload) != ("top100_weight_source" in payload):
        raise AdviceDocumentError("Top-100 weight and source must be supplied together.")
    _validate_window_comparison(payload)


def _validate_window_comparison(payload: dict[str, Any]) -> None:
    comparison = payload.get("window_comparison")
    multi_rival = payload["window"] in (3, 5) and payload["mode"] in (
        "ortak-koru",
        "fark-yarat",
    )
    if comparison is None and not multi_rival:
        return
    if comparison is None or not multi_rival:
        raise AdviceDocumentError("A window comparison requires a multiweek rival plan.")
    weeks = payload.get("plan_weeks")
    if not isinstance(weeks, list) or [w["gameweek"] for w in weeks] != list(
        range(payload["gameweek"], payload["gameweek"] + payload["window"])
    ):
        raise AdviceDocumentError("The comparison must carry the whole consecutive window.")
    minimum, maximum = (9, None) if payload["mode"] == "ortak-koru" else (None, 5)
    if (
        comparison["rival_entry_id"] != payload.get("rival_entry_id")
        or comparison["rival_entry_id"] == payload["entry_id"]
        or comparison["rival_gameweek"] != payload["gameweek"] - 1
        or comparison["overlap_minimum"] != minimum
        or comparison["overlap_maximum"] != maximum
        or (minimum is not None and comparison["overlap_actual"] < minimum)
        or (maximum is not None and comparison["overlap_actual"] > maximum)
        or comparison["solver_status"] != payload.get("solver_status")
        or comparison["optimality_gap"] != payload.get("optimality_gap")
    ):
        raise AdviceDocumentError("The comparison disagrees with the rival plan or policy.")
    nets = [w["expected_points"] - w["transfer_hit_points"] for w in weeks]
    for actual, expected in (
        (comparison["first_week_net_points"], nets[0]),
        (comparison["total_net_points"], sum(nets)),
        (comparison["net_points_difference"], sum(nets) - comparison["control_total_net_points"]),
    ):
        if not math.isclose(actual, expected, rel_tol=1e-9, abs_tol=1e-8):
            raise AdviceDocumentError("The comparison totals do not match the net plan points.")


def _invalid_number(value: str) -> None:
    raise ValueError(f"Non-finite JSON number: {value}.")


def _finite_float(value: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("The JSON number is outside the finite range.")
    return number


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
