"""The same corrupted chip evidence is refused by producer and served-read boundaries."""

import json
from copy import deepcopy
from typing import Any

import pytest
from tests.unit.test_api_advice_routes import _valid_advice_document
from tests.unit.test_scoreboard_diagnostics import decision_inputs

from squadopt.application.chip_contract import validate_chip_recommendations
from squadopt.data.errors import DataError
from squadopt.platform.advice_documents import AdviceDocumentError, validate_advice_document


def block() -> dict[str, Any]:
    decision, projections, _ = decision_inputs()
    players = {
        row["player_id"]: {
            **row,
            "name": str(row["player_id"]),
            "short_name": str(row["player_id"]),
            "team": "1",
        }
        for row in projections.to_dict("records")
    }
    return {
        "contract_version": "member_chip_recommendations_v1",
        "planning_policy_id": "member_planning_policy_v3",
        "gameweeks": [3],
        "control_solver_status": "OPTIMAL",
        "control_optimality_gap": 0,
        "comparisons": [
            {
                "chip": "bboost",
                "available_from_gameweek": 1,
                "last_usable_gameweek": 19,
                "remaining": 1,
                "action": "play",
                "gameweek": 3,
                "expected_points_gain": 5,
                "reason": "window_gain",
                "solver_status": "FEASIBLE",
                "optimality_gap": 0.1,
                "decision": {
                    "gameweek": 3,
                    "chip": "bboost",
                    "expected_own_points": 160,
                    "transfer_hit_points": 4,
                    "starting_xi": [players[code] for code in decision["starting_xi_player_ids"]],
                    "bench": [players[code] for code in decision["bench_player_ids"]],
                    "captain": players[8],
                    "vice_captain": players[9],
                },
            }
        ],
    }


def served(value: Any) -> bytes:
    document = json.loads(_valid_advice_document())
    document["payload"]["chip_recommendations"] = value
    return json.dumps(document).encode()


def test_complete_frozen_chip_decision_passes_both_boundaries() -> None:
    validate_chip_recommendations(block(), gameweeks=[3])
    validate_advice_document(served(block()))


@pytest.mark.parametrize(
    "problem",
    [
        "no_decision",
        "wrong_week",
        "expired",
        "hold_with_decision",
        "duplicate_window",
        "duplicate_player",
        "captain_on_bench",
        "wrong_chip",
        "positive_hold",
        "nan",
        "missing_price",
        "wrong_horizon",
        "wrong_formation",
    ],
)
def test_corrupted_chip_evidence_cannot_be_published(problem: str) -> None:
    value = deepcopy(block())
    row = value["comparisons"][0]
    if problem == "no_decision":
        row["decision"] = None
    elif problem == "wrong_week":
        row["decision"]["gameweek"] = 4
    elif problem == "expired":
        row["last_usable_gameweek"] = 2
    elif problem == "hold_with_decision":
        row["action"] = "hold"
    elif problem == "duplicate_window":
        value["comparisons"].append(deepcopy(row))
    elif problem == "duplicate_player":
        row["decision"]["bench"][0] = row["decision"]["starting_xi"][0]
    elif problem == "captain_on_bench":
        row["decision"]["captain"] = row["decision"]["bench"][0]
    elif problem == "wrong_chip":
        row["decision"]["chip"] = "3xc"
    elif problem == "positive_hold":
        row.update(action="hold", gameweek=None, decision=None, reason="no_positive_gain")
    elif problem == "nan":
        row["expected_points_gain"] = float("nan")
    elif problem == "missing_price":
        del row["expected_points_gain"]
    elif problem == "wrong_horizon":
        value["gameweeks"] = [4]
    elif problem == "wrong_formation":
        row["decision"]["starting_xi"][0]["position"] = "FWD"
    with pytest.raises(DataError):
        validate_chip_recommendations(value, gameweeks=[3])
    with pytest.raises(AdviceDocumentError):
        validate_advice_document(served(value))
