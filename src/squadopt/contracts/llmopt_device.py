"""Optional browser-private device computation fields; public advice identity is unchanged."""

from squadopt.contracts.preferences import preferences_schema


def device_extension_schema() -> dict[str, object]:
    choice = {
        "type": "object",
        "not": {"anyOf": [{"required": ["alternatives"]}, {"required": ["device_alternatives"]}]},
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
                },
            },
        },
        "description": (
            "Extension fields only; core device input and advice validation still applies."
        ),
        "properties": {
            "preferences": preferences_schema(),
            "alternatives": {"type": ["boolean", "array"], "maxItems": 2, "items": choice},
            "restricted": {"type": "boolean"},
            "bank_after_tenths": {"type": "integer", "minimum": 0},
            "free_transfers_before": {"type": "integer", "minimum": 0, "maximum": 5},
            "free_transfers_after": {"type": "integer", "minimum": 0, "maximum": 5},
            "device_alternatives": {"type": "array", "maxItems": 2, "items": choice},
            "device_input_fingerprint": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
        },
    }
