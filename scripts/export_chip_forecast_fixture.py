"""Generate synthetic Python chip-rule answers for the unwired device port."""

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from squadopt.application.chip_forecast import (
    MEASURED_RESERVATION,
    MEASURED_THRESHOLD_POLICY,
    PROTOCOL_HOLDING_VALUES,
    ChipForecastError,
    ChipForecastInputs,
    GameweekFixtures,
    HeldChip,
    SquadRow,
    chip_forecast,
)
from squadopt.live.rules import CHIP_NAMES

FIXTURE = Path(__file__).resolve().parents[1] / "web/src/fixtures/chip-forecast/cases.json"


def reference(raw: dict[str, Any]) -> dict[str, Any]:
    inputs = ChipForecastInputs(
        decision_gameweek=raw["decision_gameweek"],
        chips=[HeldChip(**chip) for chip in raw["chips"]],
        squad=[SquadRow(**row) for row in raw["squad"]],
        calendar=[
            GameweekFixtures(
                week["gameweek"],
                {int(club): count for club, count in week["fixture_count_by_club"].items()},
            )
            for week in raw["calendar"]
        ],
        holding_values=raw["holding_values"],
        threshold=raw["threshold"],
        reserve=raw["reserve"],
    )
    document = chip_forecast(inputs)
    document.pop("limits")
    return document


def base_inputs() -> dict[str, Any]:
    return {
        "decision_gameweek": 6,
        "chips": [
            {"name": name, "first_gameweek": 1, "last_gameweek": 8, "gain_this_week": 1.0}
            for name in CHIP_NAMES
        ],
        "squad": [
            {
                "player_id": 100 + slot,
                "club_id": slot,
                "position": "GK" if slot in (1, 12) else "DEF",
                "expected_points": 8.0 if slot == 1 else 2.0,
                "bench_order": slot - 11 if slot >= 12 else None,
                "is_captain": slot == 1,
            }
            for slot in range(1, 16)
        ],
        "calendar": [
            {"gameweek": week, "fixture_count_by_club": {str(club): 1 for club in range(1, 21)}}
            for week in range(6, 9)
        ],
        "holding_values": dict(PROTOCOL_HOLDING_VALUES),
        "threshold": MEASURED_THRESHOLD_POLICY,
        "reserve": MEASURED_RESERVATION,
    }


def build_fixture() -> dict[str, Any]:
    cases = []

    def add(name: str, raw: dict[str, Any]) -> None:
        cases.append({"name": name, "inputs": raw, "reference": reference(raw)})

    add("measured-rule", base_inputs())
    raw = base_inputs()
    raw["calendar"][0]["fixture_count_by_club"]["1"] = 0
    raw["squad"][0]["expected_points"] = 0.0
    raw["calendar"][1]["fixture_count_by_club"].update({"2": 2, "3": 0})
    add("blank-and-double", raw)
    raw = base_inputs()
    raw["reserve"] = True
    add("reservation", raw)
    raw = base_inputs()
    raw["reserve"] = True
    raw["calendar"][0]["fixture_count_by_club"].update({"2": 2})
    add("reservation-allows-double", raw)
    raw = base_inputs()
    raw["reserve"] = True
    raw["calendar"][0]["fixture_count_by_club"]["20"] = 0
    add("reservation-blank-only", raw)
    raw = base_inputs()
    raw.update(decision_gameweek=8, calendar=raw["calendar"][-1:], reserve=True)
    add("reservation-lifted-at-last-week", raw)
    raw = base_inputs()
    raw["threshold"] = "fixed"
    raw["calendar"][1]["fixture_count_by_club"].update({"1": 3, "12": 4, "13": 4})
    add("fixed", raw)
    raw = base_inputs()
    for chip in raw["chips"]:
        chip.update(first_gameweek=7, gain_this_week=None)
    add("window-not-open", raw)
    raw = base_inputs()
    for chip in raw["chips"]:
        chip.update(last_gameweek=5, gain_this_week=None)
    add("expired-window", raw)
    raw = base_inputs()
    for chip in raw["chips"]:
        chip["gain_this_week"] = None
    add("unknown-gain", raw)
    raw = base_inputs()
    for row in raw["squad"][-4:]:
        raw["calendar"][0]["fixture_count_by_club"][str(row["club_id"])] = 0
        row["expected_points"] = 0.0
    add("bench-with-no-current-fixture", raw)
    raw = base_inputs()
    for chip in raw["chips"]:
        chip.update(first_gameweek=6, last_gameweek=6)
    raw["calendar"] = raw["calendar"][:1]
    add("one-gameweek-window", raw)
    raw = base_inputs()
    for chip in raw["chips"]:
        chip["gain_this_week"] = raw["holding_values"][chip["name"]] * 2 / 7
    add("exact-threshold", raw)
    raw = base_inputs()
    raw["threshold"] = "fixed"
    raw["holding_values"]["bboost"] = 0.6
    raw["chips"][2]["gain_this_week"] = None
    for row, points in zip(raw["squad"][-4:], (0.1, 0.2, 0.3, 0.0), strict=True):
        row["expected_points"] = points
    add("bench-sum-at-threshold", raw)
    raw = base_inputs()
    raw["threshold"] = "fixed"
    raw["holding_values"]["bboost"] = 1.0
    raw["chips"][2]["gain_this_week"] = None
    for row, points in zip(raw["squad"][-4:], (1.0, 2**-53, 2**-106, 0.0), strict=True):
        row["expected_points"] = points
    add("bench-sum-half-even", raw)
    raw = base_inputs()
    raw["squad"][11]["expected_points"] = 9.0
    add("triple-captain-best-on-bench", raw)
    raw = base_inputs()
    raw["squad"][1]["expected_points"] = raw["squad"][0]["expected_points"]
    raw["squad"].reverse()
    add("triple-captain-tie", raw)
    raw = base_inputs()
    raw["chips"] = []
    add("no-held-chips", raw)

    refusals = []

    def refuse(name: str, raw: dict[str, Any]) -> None:
        try:
            reference(raw)
        except ChipForecastError:
            refusals.append({"name": name, "inputs": raw})
        else:
            raise AssertionError(f"The Python rule accepted refusal {name}.")

    mutations = [
        ("decision-gameweek-boolean", ("decision_gameweek",), True),
        ("threshold", ("threshold",), "other"),
        ("reserve", ("reserve",), 1),
        ("chip-name", ("chips", 0, "name"), "other"),
        ("first-week", ("chips", 0, "first_gameweek"), 0),
        ("last-week-boolean", ("chips", 0, "last_gameweek"), True),
        ("last-week-fraction", ("chips", 0, "last_gameweek"), 7.5),
        ("reversed-window", ("chips", 0, "first_gameweek"), 9),
        ("gain-boolean", ("chips", 0, "gain_this_week"), True),
        ("gain-outside-window", ("chips", 0, "first_gameweek"), 7),
        ("holding-negative", ("holding_values", "wildcard"), -1),
        ("holding-boolean", ("holding_values", "wildcard"), True),
        ("player-id", ("squad", 0, "player_id"), 0),
        ("club-id", ("squad", 0, "club_id"), 0),
        ("position", ("squad", 0, "position"), "other"),
        ("points-boolean", ("squad", 0, "expected_points"), True),
        ("bench-order", ("squad", 12, "bench_order"), 5),
        ("bench-order-boolean", ("squad", 12, "bench_order"), True),
        ("bench-order-text", ("squad", 12, "bench_order"), "2"),
        ("captain-flag", ("squad", 0, "is_captain"), 1),
        ("no-captain", ("squad", 0, "is_captain"), False),
        ("calendar-start", ("calendar", 0, "gameweek"), 5),
        ("calendar-count", ("calendar", 0, "fixture_count_by_club", "1"), -1),
        ("calendar-count-boolean", ("calendar", 0, "fixture_count_by_club", "1"), True),
        ("calendar-count-fraction", ("calendar", 0, "fixture_count_by_club", "1"), 0.5),
        ("blank-with-projection", ("calendar", 0, "fixture_count_by_club", "1"), 0),
    ]
    for name, keys, value in mutations:
        raw = base_inputs()
        target: Any = raw
        for key in keys[:-1]:
            target = target[key]
        target[keys[-1]] = value
        refuse(name, raw)
    for name in (
        "duplicate-chip",
        "missing-holding",
        "unknown-holding",
        "short-squad",
        "duplicate-player",
        "duplicate-bench",
        "bench-captain",
        "empty-calendar",
        "calendar-gap",
        "duplicate-week",
        "empty-clubs",
        "other-clubs",
        "missing-squad-club",
        "short-calendar",
        # Each of these trips one check only; the neighbour it extends also trips a later one.
        "threshold-without-held-chip",
        "reversed-window-without-gain",
        "calendar-club-zero",
    ):
        raw = base_inputs()
        if name == "duplicate-chip":
            raw["chips"].append(deepcopy(raw["chips"][0]))
        elif name == "missing-holding":
            raw["holding_values"].pop("wildcard")
        elif name == "unknown-holding":
            raw["holding_values"]["other"] = 1
        elif name == "short-squad":
            raw["squad"].pop()
        elif name == "duplicate-player":
            raw["squad"][1]["player_id"] = raw["squad"][0]["player_id"]
        elif name == "duplicate-bench":
            raw["squad"][-1]["bench_order"] = 3
        elif name == "bench-captain":
            raw["squad"][0]["is_captain"] = False
            raw["squad"][-1]["is_captain"] = True
        elif name == "empty-calendar":
            raw["calendar"] = []
        elif name == "calendar-gap":
            raw["calendar"].pop(1)
        elif name == "duplicate-week":
            raw["calendar"][1]["gameweek"] = 6
        elif name == "empty-clubs":
            raw["calendar"][0]["fixture_count_by_club"] = {}
        elif name == "other-clubs":
            raw["calendar"][1]["fixture_count_by_club"].pop("20")
        elif name == "missing-squad-club":
            for week in raw["calendar"]:
                week["fixture_count_by_club"].pop("1")
        elif name == "short-calendar":
            raw["calendar"].pop()
        elif name == "threshold-without-held-chip":
            raw.update(threshold="other", chips=[])
        elif name == "reversed-window-without-gain":
            raw["chips"][0].update(first_gameweek=9, gain_this_week=None)
        elif name == "calendar-club-zero":
            for week in raw["calendar"]:
                week["fixture_count_by_club"]["0"] = 1
        refuse(name, raw)
    return {
        "constants": {
            "chip_names": list(CHIP_NAMES),
            "holding_values": dict(PROTOCOL_HOLDING_VALUES),
            "threshold_policy": MEASURED_THRESHOLD_POLICY,
            "reserve": MEASURED_RESERVATION,
        },
        "cases": cases,
        "refusals": refusals,
    }


def main() -> None:
    FIXTURE.parent.mkdir(parents=True, exist_ok=True)
    FIXTURE.write_text(
        json.dumps(build_fixture(), indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
