"""Wire shapes for role forecasts and completed-policy comparisons."""

from typing import Any


def _object(fields: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": fields,
        "required": list(fields),
        "additionalProperties": False,
    }


def role_forecast_schema() -> dict[str, Any]:
    identity = {"type": "integer", "minimum": 1}
    row = _object(
        {
            "player_id": identity,
            "name": {"type": "string"},
            "fixture_id": identity,
            "gameweek": identity,
            "kickoff": {"type": "string"},
            "status": {"enum": ["fitted_known_start_labels", "unavailable_no_known_start_labels"]},
            # This multiplier quotes captured FPL eligibility, not a model role estimate.
            "captured_eligibility_multiplier": {"type": "number", "minimum": 0, "maximum": 1},
            "expected_minutes": {"type": "number", "minimum": 0, "maximum": 120},
            "news_applied": {"type": "boolean"},
        }
    )
    # Optional for already published role rows; a supplied breakdown is complete.
    row["properties"]["point_components"] = _object(
        {
            **{
                key: {"type": "number", "minimum": 0}
                for key in (
                    "appearance",
                    "goals",
                    "assists",
                    "clean_sheet",
                    "defcon",
                    "clipping",
                    "total",
                )
            },
            "other": {"type": "number"},
        }
    )
    return _object(
        {
            "version": {"const": "football_role_forecast_v1"},
            "model_version": {
                "enum": [
                    "football_joint_role_minutes_v1",
                    "football_joint_role_retained_history_v1",
                ]
            },
            "calibration": {"const": "not_independently_verified"},
            "scope": {"const": "current_gameweek_fixtures"},
            "rows": {"type": "array", "items": row},
        }
    )


def policy_comparison_schema() -> dict[str, Any]:
    count = {"type": "integer", "minimum": 0}
    number = {"type": "number"}
    candidate = _object(
        {
            "index": count,
            "action_kind": {"enum": ["hold", "move", "chip"]},
            "first_state": _object({"bank_tenths": count, "free_transfers": count}),
            **{
                key: number
                for key in (
                    "scenario_min",
                    "scenario_max",
                    "minimum_gap_vs_baseline",
                    "maximum_gap_vs_baseline",
                )
            },
            "branch_gaps_vs_baseline": {"type": "object", "additionalProperties": number},
            "dominates_baseline": {"type": "boolean"},
            "dominated_by": {"type": "array", "items": count},
        }
    )
    return _object(
        {
            "version": {"const": "completed_policy_comparison_v1"},
            "basis": {"const": "expected_own_points"},
            "baseline_index": count,
            "scenario_ids": {"type": "array", "items": {"type": "string"}},
            "news_arrival_probability": {"type": "null"},
            "scope": {"const": "supplied_conditional_scenarios_only"},
            "terminal_resource_value_added": {"const": False},
            "candidates": {"type": "array", "items": candidate},
        }
    )
