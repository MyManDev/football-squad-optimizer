"""Validated internal priority program, deliberately separate from advice admission."""

from dataclasses import dataclass

from squadopt.contracts.preferences import DecisionPreferences, preferences_schema


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


def priority_program_schema() -> dict[str, object]:
    """Internal interchange proposal; not accepted by the public advice API yet."""
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
