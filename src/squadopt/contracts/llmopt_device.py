"""Optional browser-private device computation fields; public advice identity is unchanged."""

from squadopt.contracts.preference_bundle import preference_bundle_schema, priority_result_schema
from squadopt.contracts.preferences import preferences_schema


def device_extension_schema() -> dict[str, object]:
    choice = {
        "type": "object",
        "not": {"anyOf": [{"required": ["alternatives"]}, {"required": ["device_alternatives"]}]},
    }
    component = {
        "type": "object",
        "additionalProperties": False,
        "required": ["status", "answer", "error_code"],
        "properties": {
            "status": {"type": "string", "enum": ["done", "failed", "exhausted", "unavailable"]},
            "answer": {
                "anyOf": [
                    {
                        "type": "object",
                        "not": {
                            "anyOf": [
                                {"required": ["preference_bundle"]},
                                {"required": ["alternatives"]},
                            ]
                        },
                    },
                    {"type": "null"},
                ]
            },
            "error_code": {"type": ["string", "null"], "pattern": "^[A-Z][A-Z0-9_]{0,63}$"},
        },
    }
    return {
        "type": "object",
        "$defs": {
            "work_receipt": {
                "type": "object",
                "additionalProperties": False,
                "required": ["binding", "units", "closed"],
                "properties": {
                    "binding": {"type": "string"},
                    "units": {"type": "integer", "minimum": 0, "maximum": 84, "multipleOf": 4},
                    "closed": {"type": "boolean"},
                },
            },
            "confirmation_extension": {
                "type": "object",
                "properties": {
                    "deviceRun": {"type": "boolean"},
                    "deviceAlternatives": {"type": "boolean"},
                    "bundleMode": {"type": "boolean"},
                },
            },
            "capabilities_extension": {
                "type": "object",
                "properties": {"devicePreferenceBundles": {"type": "boolean", "const": True}},
            },
        },
        "description": (
            "Extension fields only; core device input and advice validation still applies."
        ),
        "properties": {
            "preferences": preferences_schema(),
            "priorityMain": {"type": "boolean", "const": True},
            "priorityReference": {
                "type": "object",
                "additionalProperties": False,
                "required": ["squad", "startingXi", "captain", "proved"],
                "properties": {
                    **{
                        name: {
                            "type": "array",
                            "items": {"type": "integer", "minimum": 1},
                            "uniqueItems": True,
                            "minItems": 1,
                            "maxItems": limit,
                        }
                        for name, limit in (("squad", 15), ("startingXi", 11))
                    },
                    "captain": {"type": "integer", "minimum": 1},
                    "proved": {"type": "boolean"},
                },
            },
            "preferenceBundle": preference_bundle_schema(),
            "priority_preferences": priority_result_schema(),
            "expected_points_cost": {"type": "number"},
            "preference_bundle": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "contract_version",
                    "request",
                    "components",
                    "selected",
                    "accepted",
                    "applied",
                    "budget_exhausted",
                ],
                "properties": {
                    "contract_version": {"type": "string", "const": "llmopt_device_preference_v1"},
                    "request": preference_bundle_schema(),
                    "components": {"type": "array", "maxItems": 2, "items": component},
                    "selected": {"anyOf": [component, {"type": "null"}]},
                    "accepted": {"type": "integer", "minimum": 0, "maximum": 65535},
                    "applied": {
                        "type": "array",
                        "maxItems": 16,
                        "uniqueItems": True,
                        "items": {"type": "integer", "minimum": 0, "maximum": 15},
                    },
                    "budget_exhausted": {"type": "boolean"},
                },
            },
            "alternatives": {"type": ["boolean", "array"], "maxItems": 2, "items": choice},
            "restricted": {"type": "boolean"},
            "bank_after_tenths": {"type": "integer", "minimum": 0},
            "free_transfers_before": {"type": "integer", "minimum": 0, "maximum": 5},
            "free_transfers_after": {"type": "integer", "minimum": 0, "maximum": 5},
            "device_alternatives": {"type": "array", "maxItems": 2, "items": choice},
            "device_input_fingerprint": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
        },
    }
