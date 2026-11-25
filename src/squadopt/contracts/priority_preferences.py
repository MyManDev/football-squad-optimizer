"""Validated priority programs shared by admitted preference work and the planner."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from squadopt.contracts.preferences import DecisionPreferences, FrozenPlanWeek, preferences_schema


@dataclass(frozen=True, slots=True)
class PriorityReference:
    """Server-owned cached decisions, without a client-supplied objective."""

    weeks: tuple[FrozenPlanWeek, ...]
    proved: bool = False


@dataclass(frozen=True, slots=True)
class PriorityPreference:
    rules: DecisionPreferences
    priority: int = 2

    def __post_init__(self) -> None:
        if type(self.priority) is not int or not 1 <= self.priority <= 3:
            raise ValueError("Priority must be an integer from 1 through 3.")
        if not isinstance(self.rules, DecisionPreferences) or not self.rules.active:
            raise ValueError("A preference requires an active rule.")
        if self.rules.net_points_priority:
            raise ValueError("Objective selection is not a soft rule.")

    @property
    def identity(self) -> str:
        return self.rules.canonical()


@dataclass(frozen=True, slots=True)
class PriorityProgram:
    preferences: tuple[PriorityPreference, ...]
    max_total_cost_tenths: int

    def __post_init__(self) -> None:
        if (
            type(self.max_total_cost_tenths) is not int
            or not 0 <= self.max_total_cost_tenths <= 1000
        ):
            raise ValueError("Total concession must be integer tenths from 0 through 1000.")
        if (
            not isinstance(self.preferences, tuple)
            or not 1 <= len(self.preferences) <= 16
            or not all(isinstance(row, PriorityPreference) for row in self.preferences)
            or len({row.identity for row in self.preferences}) != len(self.preferences)
        ):
            raise ValueError("Supply between one and sixteen distinct preferences.")
        object.__setattr__(
            self, "preferences", tuple(sorted(self.preferences, key=lambda row: row.identity))
        )

    @classmethod
    def parse(cls, value: object) -> PriorityProgram:
        if not isinstance(value, dict) or set(value) != {"preferences", "max_total_cost_tenths"}:
            raise ValueError("Invalid priority program.")
        rows = value["preferences"]
        if not isinstance(rows, list):
            raise ValueError("Invalid preference list.")
        parsed = []
        for row in rows:
            if (
                not isinstance(row, dict)
                or "rules" not in row
                or row.keys() - {"rules", "priority"}
            ):
                raise ValueError("Invalid priority preference.")
            rules = DecisionPreferences.parse(row["rules"])
            if rules.wildcard_week is not None or rules.frozen_weeks or rules.scenario is not None:
                raise ValueError("Unsupported priority rule.")
            parsed.append(PriorityPreference(rules, row.get("priority", 2)))
        return cls(tuple(parsed), value["max_total_cost_tenths"])

    def payload(self) -> dict[str, Any]:
        return {
            "preferences": [
                {"rules": row.rules.payload(), "priority": row.priority} for row in self.preferences
            ],
            "max_total_cost_tenths": self.max_total_cost_tenths,
        }

    def canonical(self) -> str:
        return json.dumps(self.payload(), sort_keys=True, separators=(",", ":"))


def priority_program_schema() -> dict[str, object]:
    """The priority program carried by the public preference execution contract."""
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["preferences", "max_total_cost_tenths"],
        "properties": {
            "max_total_cost_tenths": {"type": "integer", "minimum": 0, "maximum": 1000},
            "preferences": {
                "type": "array",
                "minItems": 1,
                "maxItems": 16,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["rules"],
                    "properties": {
                        "rules": preferences_schema(),
                        "priority": {"type": "integer", "minimum": 1, "maximum": 3},
                    },
                },
            },
        },
    }
