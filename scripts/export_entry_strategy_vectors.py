"""Export synthetic answers from the accepted rival and strategy rules for the device."""

import json
import math
from pathlib import Path

from squadopt.application.mode_selection import ModeSelectionError, choose_rival
from squadopt.application.strategies.rule import (
    STRATEGY_RULE_ID,
    WEEKLY_POINTS_DIFFERENTIAL_POINTS,
    band_edge_points,
    gameweeks_remaining,
    suggest_strategy,
)
from squadopt.scenarios import RivalSquad

FIXTURE = (
    Path(__file__).resolve().parents[1] / "web/src/features/league/entryState/strategy-vectors.json"
)


def build_vectors():
    rivals = []
    for name, entry, ranks, candidates in (
        ("chaser", 30, {10: 1, 20: 2, 30: 3, 40: 4}, [10, 20, 40]),
        ("leader", 10, {10: 1, 20: 2, 30: 3}, [20, 30]),
        ("missing-member", 90, {10: 1, 20: 2}, [10, 20]),
        ("no-candidate", 10, {10: 1}, []),
        ("unranked-candidate", 10, {10: 1}, [20]),
        ("skip-ineligible-neighbour", 30, {10: 1, 20: 2, 30: 3}, [10]),
        ("tied-above", 30, {30: 2, 20: 1, 10: 1}, [10, 20]),
        ("tied-leaders", 30, {30: 1, 20: 1, 10: 1}, [20, 10]),
        ("tied-below", 10, {30: 2, 20: 2, 10: 1}, [30, 20]),
        ("self-candidate", 10, {10: 1, 20: 2}, [10, 20]),
    ):
        squads = {
            entry_id: RivalSquad(str(entry_id), tuple(range(1, 12)), 1) for entry_id in candidates
        }
        try:
            chosen = choose_rival(entry, ranks, squads)
            expected = {"entry_id": int(chosen.label) if chosen is not None else None}
        except ModeSelectionError:
            expected = {"refused": True}
        rivals.append(
            {
                "name": name,
                "entry_id": entry,
                "ranks": list(ranks.items()),
                "candidates": candidates,
                "expected": expected,
            }
        )

    suggestions = []
    for gameweek in range(1, 40):
        edge = band_edge_points(gameweeks_remaining(gameweek))
        inside, outside = math.floor(edge), math.floor(edge) + 1
        for gap in sorted({-outside, -inside, 0, inside, outside}):
            inputs = {
                "rival_entry_id": 20,
                "points_ahead_of_rival": gap,
                "gameweek": gameweek,
                "scored_gameweek": gameweek - 1,
            }
            suggestions.append({"input": inputs, "expected": suggest_strategy(**inputs).to_dict()})
    return {
        "rule_id": STRATEGY_RULE_ID,
        "weekly_points_differential_points": WEEKLY_POINTS_DIFFERENTIAL_POINTS,
        "rivals": rivals,
        "suggestions": suggestions,
    }


if __name__ == "__main__":
    FIXTURE.write_text(json.dumps(build_vectors(), indent=2) + "\n", encoding="utf-8")
