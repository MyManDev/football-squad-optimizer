"""Compare complete device answers using the full document's original rank indices."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


def parity_coverage(
    required: set[tuple[str, int, int]], observed: dict[tuple[str, int, int], str]
) -> dict[str, Any]:
    """A timeout or absent reduced answer is never a successful parity comparison."""
    counts = {
        state: sum(observed.get(key) == state for key in required)
        for state in ("passed", "different", "incomplete")
    }
    missing = len(required - observed.keys())
    return {
        "passed": bool(required) and counts["passed"] == len(required) and missing == 0,
        "required_attempts": len(required),
        "passed_comparisons": counts["passed"],
        "different_comparisons": counts["different"],
        "incomplete_answers": counts["incomplete"],
        "missing_attempts": missing,
    }


def rank_sums(answer: dict[str, Any], document: dict[str, Any]) -> list[int]:
    """The exact c/x/s coefficients w * original_count + original_solver_index."""
    ordered = sorted(document["players"], key=lambda player: player["id"])
    rank = {player["id"]: index for index, player in enumerate(ordered)}
    count = len(ordered)
    totals = [0, 0, 0]
    for w, week in enumerate(answer["plan_weeks"]):
        for family, ids in enumerate(([week["captain"]], week["starting_xi"], week["squad"])):
            totals[family] += sum(w * count + rank[identifier] for identifier in ids)
    return totals


def compare_full_pool_answer(
    answer: dict[str, Any],
    full: dict[str, Any],
    document: dict[str, Any],
    *,
    unique_moves: bool = False,
) -> dict[str, Any]:
    difference = answer["objective"] - full["objective"]
    scaled_equal = answer["objective_scaled"] == full["objective_scaled"]
    actual_ranks, expected_ranks = rank_sums(answer, document), rank_sums(full, document)
    same_length = len(answer["plan_weeks"]) == len(full["plan_weeks"])
    moves_equal = None
    if unique_moves:
        moves_equal = same_length and all(
            actual["transfers_in"] == expected["transfers_in"]
            and actual["transfers_out"] == expected["transfers_out"]
            for actual, expected in zip(answer["plan_weeks"], full["plan_weeks"], strict=True)
        )
    passed = (
        same_length
        and abs(difference) <= 1e-6
        and scaled_equal
        and actual_ranks == expected_ranks
        and moves_equal is not False
    )
    return {
        "passed": passed,
        "objective": answer["objective"],
        "unreduced_objective": full["objective"],
        "objective_scaled": answer["objective_scaled"],
        "unreduced_objective_scaled": full["objective_scaled"],
        "objective_difference": difference,
        "scaled_equal": scaled_equal,
        "rank_sums": actual_ranks,
        "unreduced_rank_sums": expected_ranks,
        "rank_sums_equal": actual_ranks == expected_ranks,
        "certified_moves_equal": moves_equal,
    }


def load_full_pool_controls(
    paths: list[Path], problem: dict[str, Any], problem_sha256: str
) -> tuple[dict[tuple[str, int], dict[str, Any]], list[dict[str, Any]]]:
    """Refuse cross-cohort controls or inconsistent OPTIMAL answers across repeats."""
    controls: dict[tuple[str, int], dict[str, Any]] = {}
    manifests = []
    for path in paths:
        raw = path.read_bytes()
        rows = [json.loads(line) for line in raw.splitlines()]
        protocol = next(row for row in rows if row["event"] == "protocol")
        if (
            protocol["in_memory_problem_sha256"] != problem_sha256
            or protocol.get("pool_mode") != "full"
            or any(row["event"] == "run_failed" for row in rows)
            or rows[-1]
            != {"event": "cleanup", "owned_processes_remaining": 0, "node_exit": 0, "errors": []}
        ):
            raise ValueError("The unreduced control uses another cohort or failed run")
        answers = 0
        for row in rows:
            if row["event"] != "sample" or not row["completed"]:
                continue
            answer = row["reply"]["answer"]
            key = row["member"], row["window"]
            if (
                key in controls
                and not compare_full_pool_answer(answer, controls[key], problem["document"])[
                    "passed"
                ]
            ):
                raise ValueError("Unreduced optimal answers disagree on primary or rank sums")
            controls[key] = answer
            answers += 1
        manifests.append({"sha256": hashlib.sha256(raw).hexdigest(), "completed_answers": answers})
    return controls, manifests
