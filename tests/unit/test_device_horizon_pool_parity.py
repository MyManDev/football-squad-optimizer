"""A primary tie never excuses a changed original-index rank tier."""

import copy
import hashlib
import json
from collections import Counter
from pathlib import Path

from tests.unit.device_horizon_pool_parity import (
    compare_full_pool_answer,
    parity_coverage,
    rank_sums,
)
from tests.unit.device_horizon_replay import five_shape_members


def control() -> tuple[dict, dict]:
    document = {"players": [{"id": 30}, {"id": 10}, {"id": 20}]}
    answer = {
        "objective": 12.5,
        "objective_scaled": 125,
        "plan_weeks": [
            {
                "captain": 10,
                "starting_xi": [10, 20],
                "squad": [10, 20, 30],
                "transfers_in": [20],
                "transfers_out": [30],
            },
            {
                "captain": 20,
                "starting_xi": [10, 20],
                "squad": [10, 20, 30],
                "transfers_in": [],
                "transfers_out": [],
            },
        ],
    }
    return document, answer


def test_original_solver_rank_and_original_count_are_preserved() -> None:
    document, answer = control()
    assert rank_sums(answer, document) == [4, 8, 15]
    assert compare_full_pool_answer(answer, answer, document)["passed"]


def test_equal_primary_with_changed_rank_sum_is_a_failure() -> None:
    document, full = control()
    changed = copy.deepcopy(full)
    changed["plan_weeks"][0]["captain"] = 20
    result = compare_full_pool_answer(changed, full, document)
    assert result["scaled_equal"]
    assert not result["rank_sums_equal"]
    assert not result["passed"]


def test_move_comparison_only_claims_certified_uniqueness() -> None:
    document, full = control()
    changed = copy.deepcopy(full)
    changed["plan_weeks"][0]["transfers_in"] = [30]
    unknown = compare_full_pool_answer(changed, full, document)
    assert unknown["passed"]
    assert unknown["certified_moves_equal"] is None
    certified = compare_full_pool_answer(changed, full, document, unique_moves=True)
    assert not certified["passed"]
    assert certified["certified_moves_equal"] is False


def test_timeout_missing_answer_and_zero_comparisons_never_pass_coverage() -> None:
    required = {("synthetic", 3, 0), ("synthetic", 3, 1)}
    assert not parity_coverage(set(), {})["passed"]
    assert not parity_coverage(required, {})["passed"]
    partial = parity_coverage(required, {("synthetic", 3, 0): "passed"})
    assert not partial["passed"]
    assert partial["missing_attempts"] == 1
    timeout = parity_coverage(required, {key: "incomplete" for key in required})
    assert not timeout["passed"]
    assert timeout["incomplete_answers"] == 2
    assert parity_coverage(required, {key: "passed" for key in required})["passed"]


def test_five_real_pool_shapes_are_legal_distinct_and_fixed_before_timing() -> None:
    path = Path(__file__).parents[2] / (
        "web/public/data/device/fpl-live-20261127T103417Z-2907c387f11f/device-plan.json"
    )
    envelope = json.loads(path.read_bytes())
    document = envelope.get("payload", envelope)
    assert document["season"] == "2026-27"
    assert len(document["players"]) == 674
    by_id = {player["id"]: player for player in document["players"]}
    cohorts = [five_shape_members(document, 1000, free) for free in (0, 1, 5)]
    assert (
        [member["entry"]["held"] for member in cohorts[0]]
        == [member["entry"]["held"] for member in cohorts[1]]
        == [member["entry"]["held"] for member in cohorts[2]]
    )
    assert [member["entry"]["bank_tenths"] for member in cohorts[0]] == [382, 196, 103, 6, 0]
    expected_sha256 = [
        "319d27425f677354241fc8462c0c675ed0522f24942166c12f351995543cb86e",
        "855d3e57896639b12a79b6fd2ef6151b31d2ae2ab778c745c84190a430ba3fbb",
        "ede87dd2be2bbaaa989f194eba09f576f0bc80e291557e842154755f767fb726",
        "a57d77c17e34959587c62b859d40d150471adbf00dbc05efb00e1154ed44f41c",
        "ffdecb8f0acd051e236fb4bbc9f9aef1e4be5a2d1f0dcb3de17a0956bb624aec",
    ]
    assert [
        hashlib.sha256(json.dumps(member["entry"], sort_keys=True).encode()).hexdigest()
        for member in cohorts[0]
    ] == expected_sha256
    for cohort in cohorts:
        assert len({tuple(member["entry"]["held"]) for member in cohort}) == 5
        for member in cohort:
            entry = member["entry"]
            held = [by_id[identifier] for identifier in entry["held"]]
            assert len(held) == len(set(entry["held"])) == 15
            assert entry["bank_tenths"] + sum(player["buy_tenths"] for player in held) == 1000
            assert (
                Counter(player["position"] for player in held)
                == document["rules"]["squad_position_limits"]
            )
            assert max(Counter(player["team"] for player in held).values()) <= 3
