"""Export synthetic finished-week answers from the production scoreboard scorer.

Run from the repository root, then format the JSON with Prettier from web.
No capture, archive, member, network or weekly-run input is read.
"""

from __future__ import annotations

import copy
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pandas as pd

from squadopt.data.errors import DataError
from squadopt.live.settlement import score_recorded_decision

FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "web"
    / "src"
    / "features"
    / "liveScore"
    / "officialScoring.vectors.json"
)
POSITIONS = ["GK", *(["DEF"] * 5), *(["MID"] * 5), "GK", *(["FWD"] * 3)]
PICK_ORDER = [1, 2, 3, 4, 7, 8, 9, 10, 13, 14, 15, 12, 11, 5, 6]


def _week() -> dict[str, Any]:
    return {
        "contract_version": "week_live_v1",
        "season": "2026-27",
        "gameweek": 6,
        "source_time": "2026-10-12T22:00:00Z",
        "fixtures": [{"id": 61, "home_club": 1, "away_club": 2, "finished": True}],
        "elements": [
            {
                "element_id": identifier,
                "points": 1,
                "minutes": 90,
                "card_shown": False,
                "position": position,
                "club": 1 if identifier <= 8 else 2,
            }
            for identifier, position in enumerate(POSITIONS, 1)
        ],
        "members": [
            {
                "entry_id": 101,
                "gameweek": 6,
                "pick_order": PICK_ORDER.copy(),
                "captain": 7,
                "vice": 13,
                "active_chip": None,
                "transfer_cost": 0,
            }
        ],
    }


def _answer(week: dict[str, Any]) -> dict[str, object]:
    member = week["members"][0]
    picks = member["pick_order"]
    decision = {
        "squad_player_ids": picks,
        "starting_xi_player_ids": picks[:11],
        "bench_player_ids": picks[11:],
        "ordered_bench_player_ids": picks[11:],
        "captain_player_id": member["captain"],
        "vice_captain_player_id": member["vice"],
        "completion_policy": "recorded_lineup",
        "transfers": {
            "chip": member["active_chip"],
            "transfer_hit_points": member["transfer_cost"],
        },
    }
    projections = pd.DataFrame(
        [{"player_id": row["element_id"], "position": row["position"]} for row in week["elements"]]
    )
    outcomes = pd.DataFrame(
        [
            {
                "player_id": row["element_id"],
                "total_points": row["points"],
                "minutes": row["minutes"],
                "card_participation": row["card_shown"],
            }
            for row in week["elements"]
        ]
    )
    try:
        scored = score_recorded_decision(decision, projections, outcomes)
    except DataError as error:
        if member["active_chip"] != "unknown" or "unsupported chip" not in str(error):
            raise
        return {"refused": True, "reason": "unsupported_chip"}
    return {
        "refused": False,
        "net": scored["net"],
        "gross": scored["xi"],
        "scoring_basis": scored["scoring_basis"],
    }


def build_vectors() -> dict[str, object]:
    cases: list[dict[str, object]] = []

    def case(
        name: str,
        changes: Mapping[int, Mapping[str, object]] | None = None,
        *,
        chip: str | None = None,
        hit: int = 0,
        double: bool = False,
        blank: bool = False,
    ) -> None:
        week = _week()
        member = week["members"][0]
        member.update(active_chip=chip, transfer_cost=hit)
        for row in week["elements"]:
            if blank and row["club"] == 1:
                row.update(points=0, minutes=0)
            if changes:
                row.update(changes.get(row["element_id"], {}))
        if double:
            week["fixtures"].append({"id": 62, "home_club": 1, "away_club": 3, "finished": True})
        if blank:
            week["fixtures"] = [{"id": 63, "home_club": 2, "away_club": 3, "finished": True}]
        cases.append({"name": name, "input": copy.deepcopy(week), "expected": _answer(week)})

    absent = {"minutes": 0, "points": 0}
    captain_absent = {7: absent, 13: {"points": 5}, 11: {"points": 3}}
    case("normal-week")
    case("goalkeeper-swap", {1: absent, 12: {"points": 5}})
    case(
        "outfield-bench-order",
        {8: absent, 9: absent, 11: {"points": 5}, 5: {"points": 6}, 6: {"points": 9}},
    )
    case("formation-minimum-skips-reserve", {2: absent, 11: {"points": 9}, 5: {"points": 4}})
    case(
        "zero-minute-card-participation",
        {2: {"minutes": 0, "points": -3, "card_shown": True}, 5: {"points": 5}},
    )
    case("absent-captain-vice-fallback", captain_absent)
    case("captain-and-vice-absent", {7: absent, 13: absent, 11: {"points": 3}, 5: {"points": 4}})
    case("triple-captain-absent", captain_absent, chip="3xc")
    case("bench-boost", chip="bboost")
    case("bench-boost-absent-starter", {8: absent, 11: {"points": 5}}, chip="bboost")
    case("bench-boost-absent-captain", {7: absent, 13: {"points": 5}}, chip="bboost")
    case(
        "zero-minute-vice-card",
        {7: absent, 13: {"minutes": 0, "points": -1, "card_shown": True}, 11: {"points": 3}},
    )
    case("free-hit", chip="freehit")
    case("wildcard", chip="wildcard")
    case("transfer-hit", hit=4)
    case("double-gameweek", {7: {"minutes": 180, "points": 10}}, double=True)
    case("club-with-no-fixture", blank=True)
    case("unknown-chip", chip="unknown")
    case("negative-captain-points", {7: {"points": -2}})
    case(
        "zero-minute-captain-card",
        {7: {"minutes": 0, "points": -3, "card_shown": True}, 13: {"points": 5}},
    )
    return {
        "reference": "score_recorded_decision",
        "scoring_basis": "official_autosub_captain_v2",
        "cases": cases,
    }


def main() -> None:
    FIXTURE.parent.mkdir(parents=True, exist_ok=True)
    FIXTURE.write_text(
        json.dumps(build_vectors(), indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
