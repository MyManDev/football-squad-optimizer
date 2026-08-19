"""The ``ui_view_v1`` contract: what the static JSON tree promises a frontend.

The schema is written by hand and committed at ``docs/contracts/ui_view_v1.schema.json``;
the frontend generates its types from it, and the tests assert that every view model's
``to_dict()`` validates against it. A change to a view is therefore a change here first,
and a change here is a contract version decision (see docs/architecture/decisions/0002).
"""

import json
from pathlib import Path
from typing import Any, Final

UI_VIEW_CONTRACT_VERSION: Final = "ui_view_v1"
UI_VIEW_SCHEMA_PATH: Final = Path("docs") / "contracts" / "ui_view_v1.schema.json"

_STR = {"type": "string"}
_INT = {"type": "integer"}
_NUM = {"type": "number"}
_BOOL = {"type": "boolean"}


def _nullable(schema: dict[str, Any]) -> dict[str, Any]:
    kind = schema.get("type")
    if isinstance(kind, str):
        return {**schema, "type": [kind, "null"]}
    return {"anyOf": [schema, {"type": "null"}]}


def _interval() -> dict[str, Any]:
    return {"type": "array", "items": _NUM, "minItems": 2, "maxItems": 2}


def _obj(properties: dict[str, Any], *, required: list[str] | None = None) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": sorted(properties) if required is None else required,
        "additionalProperties": False,
    }


def _ref(name: str) -> dict[str, Any]:
    return {"$ref": f"#/$defs/{name}"}


def _array(item: dict[str, Any]) -> dict[str, Any]:
    return {"type": "array", "items": item}


def _free_object() -> dict[str, Any]:
    return {"type": "object"}


def ui_view_schema() -> dict[str, Any]:
    """The JSON Schema (draft 2020-12) of every file the site writes."""

    player = _obj(
        {
            "player_id": _INT,
            "name": _STR,
            "team": _STR,
            "position": {"type": "string", "enum": ["GK", "DEF", "MID", "FWD", "UNK"]},
            "price_tenths": _INT,
            "expected_points": _NUM,
            "role": {"type": "string", "enum": ["starter", "bench", "out", "in"]},
            "is_captain": _BOOL,
            "bench_order": _nullable(_INT),
        }
    )
    transfer = _obj(
        {
            "previous_gameweek": _INT,
            "transfers_in": _array(_ref("PlayerView")),
            "transfers_out": _array(_ref("PlayerView")),
            "transfer_count": _INT,
            "paid_transfer_count": _INT,
            "transfer_hit_points": _NUM,
            "free_transfers_before": _INT,
            "free_transfers_after": _INT,
            "bank_before_tenths": _INT,
            "bank_after_tenths": _INT,
            "squad_sell_value_tenths": _INT,
            "chip": _nullable(_STR),
            "chips_available": _array(_STR),
            "planner_solver_status": _STR,
            "max_free_transfers": _INT,
            "transfer_hit_cost_points": _NUM,
        }
    )
    rival = _obj(
        {
            "rival": _STR,
            "probability_ahead": _NUM,
            "probability_ahead_interval": _interval(),
            "mean_difference": _NUM,
            "shared_starters": _INT,
        }
    )
    risk = _obj(
        {
            "status": {"type": "string", "enum": ["available", "unavailable", "not_requested"]},
            "reason": _STR,
            "blockers": _array(_STR),
            "scenario_count": _nullable(_INT),
            "lower_quantile_probability": _nullable(_NUM),
            "lower_quantile_score": _nullable(_NUM),
            "mean_score": _nullable(_NUM),
            "mean_worst_fraction_score": _nullable(_NUM),
            "worst_fraction": _nullable(_NUM),
            "points_threshold": _nullable(_NUM),
            "probability_below_threshold": _nullable(_NUM),
            "probability_below_threshold_interval": _nullable(_interval()),
            "location_shift_points": _nullable(_NUM),
            "stated_limits": _array(_STR),
            "rivals": _array(_ref("RivalComparisonView")),
            "residual_source": _nullable(_STR),
        }
    )
    recommendation = _obj(
        {
            "season": _STR,
            "gameweek": _INT,
            "deadline_utc": _STR,
            "snapshot_id": _STR,
            "captured_at_utc": _STR,
            "model_name": _STR,
            "model_version": _STR,
            "feature_contract_version": _STR,
            "prediction_fingerprint": _STR,
            "report_contract_version": _STR,
            "solver_status": _STR,
            "solver_proved_optimal": _BOOL,
            "decision_kind": {"type": "string", "enum": ["opening", "transfer"]},
            "squad": _array(_ref("PlayerView")),
            "starting_xi": _array(_ref("PlayerView")),
            "bench": _array(_ref("PlayerView")),
            "captain_player_id": _INT,
            "total_cost_tenths": _INT,
            "projected_score": _NUM,
            "unavailable_player_count": _INT,
            "risk": _ref("RiskView"),
            "transfers": _nullable(_ref("TransferView")),
            "outcome_realized_score": _nullable(_NUM),
            "outcome_net_score": _nullable(_NUM),
            "settled": _BOOL,
            "metadata": _free_object(),
        }
    )
    ledger_row = _obj(
        {
            "gameweek": _INT,
            "snapshot_id": _STR,
            "deadline_utc": _STR,
            "solver_status": _STR,
            "decision_kind": {"type": "string", "enum": ["opening", "transfer"]},
            "captain_player_id": _INT,
            "projected_score": _NUM,
            "realized_score": _nullable(_NUM),
            "projection_error": _nullable(_NUM),
            "transfer_count": _INT,
            "transfer_hit_points": _NUM,
            "realized_net_score": _nullable(_NUM),
            "chip": _nullable(_STR),
            "unavailable_player_count": _INT,
            "settled": _BOOL,
        }
    )
    ledger = _obj(
        {
            "season": _STR,
            "rows": _array(_ref("LedgerRowView")),
            "decided_gameweeks": _INT,
            "settled_gameweeks": _INT,
            "total_projected_score": _NUM,
            "total_realized_score": _nullable(_NUM),
            "total_realized_net_score": _nullable(_NUM),
            "total_transfer_hit_points": _NUM,
            "chips_played": _array(_STR),
        }
    )
    tick_action = _obj(
        {
            "kind": {"type": "string", "enum": ["capture", "decide", "settle", "wait"]},
            "reason": _STR,
            "gameweek": _nullable(_INT),
            "snapshot_id": _nullable(_STR),
            "handoff_path": _nullable(_STR),
        }
    )
    run_log_event = _obj(
        {"ts": _STR, "level": _STR, "message": _STR, "run_id": _STR, "fields": _free_object()}
    )
    status = _obj(
        {
            "now_utc": _STR,
            "season": _nullable(_STR),
            "latest_capture": _nullable(_STR),
            "next_gameweek": _nullable(_INT),
            "next_deadline_utc": _nullable(_STR),
            "hours_to_deadline": _nullable(_NUM),
            "actions": _array(_ref("TickActionView")),
            "is_idle": _BOOL,
            "decided_gameweeks": _array(_INT),
            "settled_gameweeks": _array(_INT),
            "recent_events": _array(_ref("RunLogEventView")),
            "tick_contract_version": _STR,
        }
    )
    index = _obj(
        {
            "generated_at_utc": _STR,
            "seasons": _array(_STR),
            "gameweeks": {"type": "object", "additionalProperties": _array(_INT)},
            "latest": _nullable(
                _obj({"season": _STR, "gameweek": _INT, "path": _STR}),
            ),
            "schema_path": _STR,
            "files": _array(_STR),
        }
    )
    envelope = _obj(
        {
            "contract_version": {"type": "string", "const": UI_VIEW_CONTRACT_VERSION},
            "generated_at_utc": _STR,
            "payload": {
                "oneOf": [
                    _ref("RecommendationView"),
                    _ref("LedgerView"),
                    _ref("StatusView"),
                    _ref("SiteIndex"),
                ]
            },
        }
    )
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": f"https://squadopt.dev/contracts/{UI_VIEW_CONTRACT_VERSION}.schema.json",
        "title": "SquadOpt UI view contract",
        "description": (
            "Every JSON file the site writes is a ViewEnvelope whose payload is one of the "
            "view models. Produced by squadopt.application; the frontend renders, never "
            "computes."
        ),
        "$defs": {
            "PlayerView": player,
            "TransferView": transfer,
            "RivalComparisonView": rival,
            "RiskView": risk,
            "RecommendationView": recommendation,
            "LedgerRowView": ledger_row,
            "LedgerView": ledger,
            "TickActionView": tick_action,
            "RunLogEventView": run_log_event,
            "StatusView": status,
            "SiteIndex": index,
            "ViewEnvelope": envelope,
        },
        **envelope,
    }


def write_ui_view_schema(path: Path | None = None) -> Path:
    """Write the schema to ``path`` (default: the committed contract file)."""

    target = Path(path) if path is not None else UI_VIEW_SCHEMA_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(ui_view_schema(), indent=2, sort_keys=True) + "\n", "utf-8")
    return target
