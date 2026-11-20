"""Validate repair requests against the immutable failed request or a captured witness."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

from squadopt.contracts.plan_infeasibility import PlanRepair
from squadopt.contracts.preferences import DecisionPreferences, FrozenPlanWeek
from squadopt.platform.advice_job_spec import AdviceJobSpec
from squadopt.platform.advice_read import advice_context_identity


def same_repair_scope(original: AdviceJobSpec, candidate: AdviceJobSpec) -> bool:
    def fixed_switches(spec: AdviceJobSpec) -> dict[str, Mapping[str, object]]:
        return {
            name: identity
            for name, identity in spec.switches.items()
            if name not in {"chip", "preferences"}
        }

    return (
        original.league_id == candidate.league_id
        and original.entry_id == candidate.entry_id
        and original.strategy == candidate.strategy
        and original.window == candidate.window == 3
        and original.context == candidate.context
        and original.rival_entry_id == candidate.rival_entry_id
        and fixed_switches(original) == fixed_switches(candidate)
    )


def _preferences(spec: AdviceJobSpec) -> DecisionPreferences:
    value = spec.switch("preferences").get("value", "{}")
    if not isinstance(value, str):
        raise ValueError("Invalid preference identity.")
    return DecisionPreferences.parse(json.loads(value))


def _rules(prefs: DecisionPreferences) -> dict[tuple[Any, ...], Any]:
    """Decompose by rule identity so deleting the last dated rule is one edit."""
    result: dict[tuple[Any, ...], Any] = {}
    for week, local in [(0, prefs), *((row.week, row.rules) for row in prefs.week_rules)]:
        for field, value in local.payload().items():
            if field == "week_rules" or value is False or value == []:
                continue
            if field == "club_counts":
                for club in local.club_counts:
                    result[week, field, club.club, club.scope] = club.count
            elif field == "frozen_weeks":
                for frozen in local.frozen_weeks:
                    result[week, field, frozen.week] = frozen
            elif field == "buy_players":
                for player in local.buy_players:
                    result[week, field, player] = True
            else:
                result[week, field] = value
    return result


def single_rule_edit(
    original: AdviceJobSpec,
    candidate: AdviceJobSpec,
    *,
    known_chip_conflict: bool = False,
    diagnosed: Sequence[PlanRepair] = (),
) -> bool:
    if not same_repair_scope(original, candidate):
        return False
    original_preferences = _preferences(original)
    candidate_preferences = _preferences(candidate)
    before = _rules(original_preferences)
    after = _rules(candidate_preferences)
    old_chip = original.switch("chip").get("chip")
    new_chip = candidate.switch("chip").get("chip")
    dropped_chip = old_chip == "wildcard" and new_chip is None
    dropped_future = (0, "wildcard_week") in before and (0, "wildcard_week") not in after
    if old_chip != new_chip and not dropped_chip:
        return False
    if dropped_chip or dropped_future:
        # The normal request compiler reinstates its chip-saving default.
        if after.get((0, "save_chips")) is True and (0, "save_chips") not in before:
            del after[0, "save_chips"]
        before.pop((0, "wildcard_week"), None)
        if before == after:
            return True
        # A frozen Wildcard may itself have supplied the mandatory chip.
        if not any(
            week.chip == "wildcard" and week not in candidate_preferences.frozen_weeks
            for week in original_preferences.frozen_weeks
        ):
            return False
    elif known_chip_conflict:
        return False
    changed = [key for key in before.keys() | after.keys() if before.get(key) != after.get(key)]
    if len(changed) == 1:
        key = changed[0]
        old, new = before.get(key), after.get(key)
        field = key[1]
        if old is None:
            return False
        if field == "min_bank":
            return new is None or (
                old.get("week") == new.get("week") and new["tenths"] < old["tenths"]
            )
        if field == "max_hit_points":
            return new is None or new > old
        if field == "club_counts":
            return True  # One exact count, same club, scope and week.
        if field == "buy_players" and new is None:
            return {"kind": "release_purchase", "week": key[0], "player_id": key[2]} in diagnosed
        return field in {"no_hits", "frozen_weeks"} and new is None
    if len(changed) == 2:
        released, added = sorted(changed)
        return (
            released[1] == added[1] == "buy_players"
            and released[2] == added[2]
            and 0 < released[0] < added[0]
            and released in before
            and released not in after
            and added not in before
            and added in after
            and {
                "kind": "defer_purchase",
                "from_week": released[0],
                "to_week": added[0],
                "player_id": added[2],
            }
            in diagnosed
        )
    return False


def current_repair_answer(spec: AdviceJobSpec, payload: Mapping[str, Any]) -> bool:
    return (
        payload.get("source_snapshot_id") == spec.context.capture_snapshot_id
        and payload.get("plan_data_id") == advice_context_identity(spec.context)
        and payload.get("entry_id") == spec.entry_id
        and payload.get("window") == 3
    )


def replays_witness(original: AdviceJobSpec, candidate: AdviceJobSpec, document: bytes) -> bool:
    if not same_repair_scope(original, candidate) or original.switch("chip") != candidate.switch(
        "chip"
    ):
        return False
    before = _preferences(original).payload()
    after = _preferences(candidate)
    requested = after.payload()
    before.pop("frozen_weeks", None)
    requested.pop("frozen_weeks", None)
    if before != requested or len(after.frozen_weeks) != 3:
        return False
    try:
        payload = json.loads(document)["payload"]
        if not current_repair_answer(original, payload):
            return False
        weeks = payload["plan_weeks"]
        if len(weeks) != 3:
            return False
        pins = []
        for offset, row in enumerate(weeks, start=1):
            lineup = row.get("lineup") or (payload if offset == 1 else {})
            pins.append(
                FrozenPlanWeek(
                    offset,
                    tuple(player["player_id"] for player in row["transfers_in"]),
                    tuple(player["player_id"] for player in row["transfers_out"]),
                    row["chip"],
                    tuple(player["player_id"] for player in lineup["starting_xi"]),
                    lineup["captain"]["player_id"],
                )
            )
    except (KeyError, TypeError, ValueError):
        return False
    return tuple(pins) == after.frozen_weeks
