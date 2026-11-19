"""One immutable, bounded preference execution after a trusted main answer."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, cast

from squadopt.contracts.plan_infeasibility import infeasibility_schema
from squadopt.contracts.preferences import DecisionPreferences, preferences_schema
from squadopt.contracts.priority_preferences import PriorityProgram, priority_program_schema

BUNDLE_VERSION = "llmopt_preference_bundle_v1"
BUNDLE_SWITCH = "llmopt_preference_bundle"


def _preference_properties() -> dict[str, Any]:
    return cast(dict[str, Any], preferences_schema()["properties"])


def _integer(value: object, low: int, high: int) -> int:
    if type(value) is not int or not low <= value <= high:
        raise ValueError("Invalid preference execution integer.")
    return value


@dataclass(frozen=True, slots=True)
class PreferenceSelection:
    """Preference overrides; null removes a field inherited from the main request."""

    patch_json: str
    chip: str | None

    @classmethod
    def parse(cls, value: object) -> PreferenceSelection:
        if not isinstance(value, dict) or set(value) != {"preferences", "chip"}:
            raise ValueError("Invalid preference component.")
        patch = value["preferences"]
        if not isinstance(patch, dict) or patch.keys() - _preference_properties().keys():
            raise ValueError("Invalid preference overrides.")
        chip = value["chip"]
        if chip is not None and chip not in ("wildcard", "freehit", "3xc", "bboost"):
            raise ValueError("Unsupported preference component chip.")
        return cls(json.dumps(patch, sort_keys=True, separators=(",", ":"), allow_nan=False), chip)

    def expand(self, main: DecisionPreferences) -> DecisionPreferences:
        value = main.payload()
        for key, item in json.loads(self.patch_json).items():
            if item is None:
                value.pop(key, None)
            else:
                value[key] = item
        return DecisionPreferences.parse(value)

    def payload(self) -> dict[str, Any]:
        return {"preferences": json.loads(self.patch_json), "chip": self.chip}


@dataclass(frozen=True, slots=True)
class BundlePrice:
    outcome: int | str
    ceiling: int | None

    @classmethod
    def parse(cls, value: object, slots: int) -> BundlePrice:
        if not isinstance(value, dict) or set(value) != {"outcome", "ceiling"}:
            raise ValueError("Invalid bundled price.")
        outcome = value["outcome"]
        if type(outcome) is int:
            _integer(outcome, 0, slots - 1)
        elif outcome not in ("same", "conflict", "unavailable", "skipped"):
            raise ValueError("Invalid bundled price outcome.")
        ceiling = value["ceiling"]
        if ceiling is not None:
            _integer(ceiling, 0, 1000)
        return cls(outcome, ceiling)

    def payload(self) -> dict[str, Any]:
        return {"outcome": self.outcome, "ceiling": self.ceiling}


def _reachable_price_masks(prices: tuple[BundlePrice, ...], slots: int) -> set[int]:
    masks = {sum(1 << index for index, price in enumerate(prices) if price.outcome == "same")}
    for slot in range(slots):
        thresholds = {
            price.ceiling / 10
            for price in prices
            if price.outcome == slot and price.ceiling is not None
        }
        costs = (0.0, *(threshold + 1e-6 for threshold in thresholds), float("inf"))
        patterns = {0}
        patterns.update(
            sum(
                1 << index
                for index, price in enumerate(prices)
                if price.outcome == slot
                and (price.ceiling is None or cost - price.ceiling / 10 <= 1e-9)
            )
            for cost in costs
        )
        masks = {mask | pattern for mask in masks for pattern in patterns}
    return masks


@dataclass(frozen=True, slots=True)
class BundleChoice:
    accepted: int
    applied: tuple[int, ...]
    selection: PreferenceSelection | None

    @classmethod
    def parse(cls, value: object, prices: int) -> BundleChoice:
        if not isinstance(value, dict) or set(value) != {"accepted", "applied", "selection"}:
            raise ValueError("Invalid bundled combination.")
        accepted = _integer(value["accepted"], 0, (1 << prices) - 1)
        applied = value["applied"]
        if not isinstance(applied, list) or len(applied) > prices:
            raise ValueError("Invalid applied preferences.")
        indexes = tuple(_integer(index, 0, prices - 1) for index in applied)
        if len(set(indexes)) != len(indexes):
            raise ValueError("Duplicate applied preference.")
        selection = value["selection"]
        return cls(
            accepted, indexes, None if selection is None else PreferenceSelection.parse(selection)
        )

    def payload(self) -> dict[str, Any]:
        return {
            "accepted": self.accepted,
            "applied": list(self.applied),
            "selection": None if self.selection is None else self.selection.payload(),
        }


@dataclass(frozen=True, slots=True)
class PreferenceBundle:
    slots: tuple[PreferenceSelection | None, ...]
    prices: tuple[BundlePrice, ...]
    choices: tuple[BundleChoice, ...]
    program: PriorityProgram | None = None

    @classmethod
    def parse(cls, value: object) -> PreferenceBundle:
        if (
            not isinstance(value, dict)
            or set(value) != {"contract_version", "slots", "prices", "choices", "program"}
            or value["contract_version"] != BUNDLE_VERSION
        ):
            raise ValueError("Invalid preference bundle.")
        slots, prices, choices = value["slots"], value["prices"], value["choices"]
        if (
            not isinstance(slots, list)
            or len(slots) > 2
            or not isinstance(prices, list)
            or len(prices) > 16
            or not isinstance(choices, list)
            or len(choices) > 289
        ):
            raise ValueError("Preference execution exceeds its component bounds.")
        parsed_slots = tuple(
            None if row is None else PreferenceSelection.parse(row) for row in slots
        )
        parsed_prices = tuple(BundlePrice.parse(row, len(slots)) for row in prices)
        parsed_choices = tuple(
            sorted(
                (BundleChoice.parse(row, len(prices)) for row in choices),
                key=lambda row: row.accepted,
            )
        )
        if len({row.accepted for row in parsed_choices}) != len(parsed_choices):
            raise ValueError("Duplicate preference combination.")
        if parsed_prices and {row.accepted for row in parsed_choices} != _reachable_price_masks(
            parsed_prices, len(parsed_slots)
        ):
            raise ValueError("The preference combinations do not cover every reachable price.")
        for choice in parsed_choices:
            if choice.selection is None and choice.applied:
                raise ValueError("Applied preferences require a computed selection.")
            for index in choice.applied:
                price = parsed_prices[index]
                if (
                    price.outcome in ("conflict", "unavailable")
                    or (price.outcome == "skipped" and price.ceiling is not None)
                    or (price.outcome != "skipped" and not choice.accepted & (1 << index))
                ):
                    raise ValueError("An unaccepted preference cannot enter the combined plan.")
        program = None if value["program"] is None else PriorityProgram.parse(value["program"])
        if program is not None and (prices or choices):
            raise ValueError("A total allowance cannot start individual price calculations.")
        return cls(parsed_slots, parsed_prices, parsed_choices, program)

    def selections(self) -> tuple[PreferenceSelection, ...]:
        return tuple(
            row
            for row in (*self.slots, *(choice.selection for choice in self.choices))
            if row is not None
        )

    def payload(self) -> dict[str, Any]:
        return {
            "contract_version": BUNDLE_VERSION,
            "slots": [None if row is None else row.payload() for row in self.slots],
            "prices": [row.payload() for row in self.prices],
            "choices": [row.payload() for row in self.choices],
            "program": None if self.program is None else self.program.payload(),
        }

    def canonical(self) -> str:
        return json.dumps(self.payload(), sort_keys=True, separators=(",", ":"), allow_nan=False)


def priority_result_schema() -> dict[str, Any]:
    properties = {
        "contract_version": {"type": "string", "const": "llmopt_priority_result_v1"},
        "satisfied": {
            "type": "array",
            "maxItems": 16,
            "items": {"type": "string"},
            "uniqueItems": True,
        },
        "left_out": {
            "type": "array",
            "maxItems": 16,
            "items": {"type": "string"},
            "uniqueItems": True,
        },
        "total_cost": {"type": "number"},
        "completed_priorities": {
            "type": "array",
            "maxItems": 3,
            "uniqueItems": True,
            "items": {"type": "integer", "minimum": 1, "maximum": 3},
        },
        "reference_proved": {"type": "boolean"},
        "budget_exhausted": {"type": "boolean"},
    }
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


def preference_result_schema(payload_schema: dict[str, Any]) -> dict[str, Any]:
    component_properties = {
        "status": {"type": "string", "enum": ["done", "failed", "exhausted", "unavailable"]},
        "payload": {"anyOf": [payload_schema, {"type": "null"}]},
        "error_code": {"type": ["string", "null"], "pattern": "^[A-Z][A-Z0-9_]{0,63}$"},
    }
    component_properties["infeasibility"] = infeasibility_schema()
    component = {
        "type": "object",
        "properties": component_properties,
        "required": ["status", "payload", "error_code"],
        "additionalProperties": False,
    }
    properties = {
        "contract_version": {"type": "string", "const": "llmopt_preference_result_v1"},
        "request": preference_bundle_schema(),
        "components": {"type": "array", "maxItems": 2, "items": component},
        "selected": {"anyOf": [component, {"type": "null"}]},
        "applied": {
            "type": "array",
            "maxItems": 16,
            "uniqueItems": True,
            "items": {"type": "integer", "minimum": 0, "maximum": 15},
        },
        "accepted": {"type": "integer", "minimum": 0, "maximum": 65535},
        "budget_exhausted": {"type": "boolean"},
    }
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


def preference_bundle_schema() -> dict[str, Any]:
    """The public request contract, also retained in immutable job switches."""

    def closed(properties: dict[str, Any]) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": properties,
            "required": list(properties),
            "additionalProperties": False,
        }

    selection = closed(
        {
            "preferences": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    key: {"anyOf": [schema, {"type": "null"}]}
                    for key, schema in _preference_properties().items()
                },
            },
            "chip": {
                "type": ["string", "null"],
                "enum": ["wildcard", "freehit", "3xc", "bboost", None],
            },
        }
    )
    optional_selection = {"anyOf": [selection, {"type": "null"}]}
    return closed(
        {
            "contract_version": {"type": "string", "const": BUNDLE_VERSION},
            "slots": {"type": "array", "maxItems": 2, "items": optional_selection},
            "prices": {
                "type": "array",
                "maxItems": 16,
                "items": closed(
                    {
                        "outcome": {
                            "anyOf": [
                                {"type": "integer", "minimum": 0, "maximum": 1},
                                {
                                    "type": "string",
                                    "enum": ["same", "conflict", "unavailable", "skipped"],
                                },
                            ]
                        },
                        "ceiling": {"type": ["integer", "null"], "minimum": 0, "maximum": 1000},
                    }
                ),
            },
            "choices": {
                "type": "array",
                "maxItems": 289,
                "items": closed(
                    {
                        "accepted": {"type": "integer", "minimum": 0, "maximum": 65535},
                        "applied": {
                            "type": "array",
                            "maxItems": 16,
                            "uniqueItems": True,
                            "items": {"type": "integer", "minimum": 0, "maximum": 15},
                        },
                        "selection": optional_selection,
                    }
                ),
            },
            "program": {"anyOf": [priority_program_schema(), {"type": "null"}]},
        }
    )
