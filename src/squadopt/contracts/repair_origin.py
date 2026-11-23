"""Hard-rule identities for a three-week conflict found before its first solve."""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass

from squadopt.contracts.preferences import DecisionPreferences, preferences_schema

# One fact retains the scope, field and canonical JSON value. A contradictory
# pair of counts remains two facts, while repeated identical requirements agree.
RuleFact = tuple[int, str, str]
# Sixteen explicit rules plus comparison, objective, three fixed weeks and their chips.
MAX_ORIGINAL_FACTS = 32


def _facts(preferences: Iterable[DecisionPreferences], wildcards: Iterable[int]) -> set[RuleFact]:
    facts: set[RuleFact] = {(week, "wildcard", "true") for week in wildcards}
    for preference in preferences:
        for scope, rules in [(0, preference), *((r.week, r.rules) for r in preference.week_rules)]:
            for field, value in rules.payload().items():
                if field == "week_rules" or value is False or value == []:
                    continue
                if field == "wildcard_week":
                    facts.add((int(str(value)), "wildcard", "true"))
                    continue
                for item in value if isinstance(value, list) else [value]:
                    facts.add(
                        (scope, field, json.dumps(item, sort_keys=True, separators=(",", ":")))
                    )
    return facts


@dataclass(frozen=True, slots=True)
class RepairOrigin:
    facts: tuple[RuleFact, ...]

    @classmethod
    def parse(cls, raw: object) -> RepairOrigin:
        if not isinstance(raw, dict) or set(raw) != {"preferences", "wildcard_weeks"}:
            raise ValueError("Invalid original repair rules.")
        parts, weeks = raw["preferences"], raw["wildcard_weeks"]
        if (
            not isinstance(parts, list)
            or len(parts) > MAX_ORIGINAL_FACTS
            or not isinstance(weeks, list)
            or len(weeks) > 3
            or any(type(w) is not int or w not in (1, 2, 3) for w in weeks)
            or len(set(weeks)) != len(weeks)
            or any(not isinstance(p, dict) for p in parts)
        ):
            raise ValueError("Invalid original repair rules.")
        facts = _facts((DecisionPreferences.parse(p) for p in parts), weeks)
        if not 1 <= len(facts) <= MAX_ORIGINAL_FACTS:
            raise ValueError("The original repair rules exceed the supported draft.")
        return cls(tuple(sorted(facts)))

    def permits(self, preferences: DecisionPreferences, chip: object) -> bool:
        if chip not in (None, "wildcard"):
            return False
        before = set(self.facts)
        implied_chips = {
            (frozen["week"], "wildcard", "true")
            for _, field, value in self.facts
            if field == "frozen_weeks" and (frozen := json.loads(value))["chip"] == "wildcard"
        }
        before.update(implied_chips)
        after = _facts([preferences], [1] if chip == "wildcard" else [])
        removed, added = before - after, after - before
        chips = {r for r in removed if r[1] == "wildcard"}
        if chips:
            # Removing the last forced Wildcard restores the compiler's chip-saving default.
            if not any(r[1] == "wildcard" for r in after):
                added.discard((0, "save_chips", "true"))
            if len(chips) == 1 and removed == chips:
                return not added
            # A frozen week can itself have supplied that week's forced Wildcard.
            for rule in removed - chips:
                if rule[1] == "frozen_weeks":
                    frozen = json.loads(rule[2])
                    implied = (frozen["week"], "wildcard", "true")
                    if frozen["chip"] == "wildcard" and implied not in self.facts:
                        removed.discard(implied)
        if len(removed) != 1 or len(added) > 1:
            return False
        scope, field, old = removed.pop()
        if not added:
            return field in {"no_hits", "max_hit_points", "min_bank", "club_counts", "frozen_weeks"}
        next_scope, next_field, new = added.pop()
        if (scope, field) != (next_scope, next_field):
            return False
        original, replacement = json.loads(old), json.loads(new)
        if field == "max_hit_points":
            return bool(replacement > original)
        if field == "min_bank":
            return bool(
                original.get("week") == replacement.get("week")
                and replacement["tenths"] < original["tenths"]
            )
        if field == "club_counts":
            return bool(
                original["club"] == replacement["club"]
                and original.get("scope", "squad") == replacement.get("scope", "squad")
            )
        return False


def repair_origin_schema() -> dict[str, object]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["preferences", "wildcard_weeks"],
        "properties": {
            "preferences": {
                "type": "array",
                "maxItems": MAX_ORIGINAL_FACTS,
                "items": preferences_schema(),
            },
            "wildcard_weeks": {
                "type": "array",
                "maxItems": 3,
                "uniqueItems": True,
                "items": {"type": "integer", "enum": [1, 2, 3]},
            },
        },
    }
