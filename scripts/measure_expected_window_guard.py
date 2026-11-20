"""Replay the frozen Phase 1 expected-window control on one local solver thread."""

import argparse
import hashlib
import json
import socket
import traceback
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from docs.research.llmopt_phase1 import benchmark
from ortools.sat.python import cp_model
from scripts.measure_window_solver_highs import window_call

from squadopt.planning import expected_window
from squadopt.planning.models import PlanningHorizon

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = ROOT / "docs/research/llmopt_phase1_baseline.json"
FAILURES = ("gw8-3832237", "gw9-3832237")
ERROR = "Invalid deterministic-work accounting for expected windows."
RESULT_FIELDS = (
    "has_solution",
    "solver_status",
    "objective",
    "decision_sha256",
    "weekly_points",
    "raw_xi_net_points",
    "expected_lineup_net_points",
    "selection_utility",
)


def canonical(record):
    return {key: record[key] for key in RESULT_FIELDS}


def run_case(case, frozen, inputs, call):
    projection = frozen["projection"]
    counts = frozen["fixture_counts"]
    first = counts[str(inputs.gameweek)]
    table = call.horizon.table.loc[
        call.horizon.table.player_id.map(str).isin(projection["appearance_probability"])
    ].copy()
    if not set(call.state.squad_player_ids) <= set(table.player_id):
        raise ValueError("A frozen member's held player is missing.")
    for index, row in table.iterrows():
        player, team = str(row.player_id), str(row.team_id)
        count = counts[str(row.gameweek)].get(team, 0)
        table.at[index, "expected_points"] = (
            projection["expected_points"][player] * count / max(1, first.get(team, 0))
        )
        table.at[index, "appearance_probability"] = projection["appearance_probability"][player]
    horizon = PlanningHorizon(table)
    policy = replace(call.policy, allow_two_free_transfers=True)
    stacks = []
    solve = cp_model.CpSolver.solve

    def traced(solver, model, solution_callback=None):
        if case in FAILURES:
            stacks.append(
                [
                    frame.name
                    for frame in traceback.extract_stack()
                    if "squadopt" in Path(frame.filename).parts
                ]
            )
        return solve(solver, model, solution_callback)

    with benchmark.accounting_checks() as checks, patch.object(cp_model.CpSolver, "solve", traced):
        observed = benchmark.timed(
            lambda: expected_window.optimize_expected_window(
                horizon, call.state, call.settings, policy
            ),
            capture_expected_failure=True,
        )
    summary = benchmark.compact_plan(observed)
    calls = []
    stack = iter(stacks)
    for event in observed["calls"]:
        item = {
            key: event[key]
            for key in (
                "backend",
                "status",
                "configured_deterministic_units",
                "deterministic_units",
                "wall_cap_seconds",
                "threads",
            )
            if key in event
        }
        if case in FAILURES and event["backend"] == "cp-sat":
            item["call_path"] = next(stack)
        calls.append(item)
    return {
        **canonical(summary),
        "error": summary["error"],
        "accounting_failures": checks,
        "actual_units": summary["actual_units"],
        "phase_work": [
            {key: phase[key] for key in ("phase", "cap", "actual", "status") if key in phase}
            for phase in observed["expected_window"].get("ledger", [])
        ],
        "solver_calls": calls,
        "seconds": summary["seconds"],
    }


def failed_at_24(outcome):
    return (
        outcome["solver_status"] == "ERROR"
        and outcome["error"] == {"type": "ValueError", "message": ERROR}
        and any(
            item["cap"] == 24 and item["actual"] > 24 for item in outcome["accounting_failures"]
        )
    )


def digest_file(path):
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def measure(output, selected, before_file):
    archive = json.loads(ARCHIVE.read_text(encoding="utf-8"))
    frozen_rows = {row["case"]: row["expected_comparison"]["single"] for row in archive["rows"]}
    cases = {
        f"gw{inputs.gameweek}-{entry}": (frozen, inputs, entry)
        for frozen, inputs in benchmark.snapshots()
        for entry in sorted(inputs.members)
    }
    if set(cases) != set(frozen_rows) or not set(selected) <= set(cases):
        raise ValueError("Selected or archived member-weeks differ from the frozen population.")
    current = benchmark.provenance()
    record = {
        "repository_commit": current["repository_commit"],
        "runner_sha256": digest_file(Path(__file__)),
        "phase1_archive_sha256": digest_file(ARCHIVE),
        "input_manifest_sha256": current["input_manifest_sha256"],
        "frozen_route": "Phase 1 expected_comparison.single, full available-appearance pool",
        "source_sha256": {
            path.relative_to(ROOT).as_posix(): digest_file(path)
            for path in (
                ROOT / "src/squadopt/planning/expected_window.py",
                ROOT / "src/squadopt/planning/expected_swap.py",
                ROOT / "src/squadopt/planning/guarded.py",
                ROOT / "src/squadopt/planning/segmented.py",
                ROOT / "src/squadopt/planning/optimizer.py",
            )
        },
        "network_attempts": 0,
        "complete": False,
        "rows": [],
    }
    before = None
    if before_file:
        prior = json.loads(before_file.read_text(encoding="utf-8"))
        if (
            prior["runner_sha256"] != record["runner_sha256"]
            or prior["input_manifest_sha256"] != record["input_manifest_sha256"]
            or prior["phase1_archive_sha256"] != record["phase1_archive_sha256"]
            or not prior["complete"]
        ):
            raise ValueError("The before record must cover all twenty cases on the same protocol.")
        before = {row["case"]: row for row in prior["rows"]}
        if set(before) != set(cases):
            raise ValueError("The before record does not match the frozen population.")
        record["before_repository_commit"] = prior["repository_commit"]
        record["before_source_sha256"] = prior["source_sha256"]

    def offline(*args, **kwargs):
        record["network_attempts"] += 1
        raise RuntimeError("This replay is offline.")

    with (
        patch.object(socket.socket, "connect", offline),
        patch.object(socket.socket, "connect_ex", offline),
    ):
        for case in (*FAILURES, *(case for case in cases if case not in FAILURES)):
            if selected and case not in selected:
                continue
            frozen, inputs, entry = cases[case]
            archived = frozen_rows[case]
            call = window_call(inputs, entry, 3)
            outcome = run_case(case, frozen, inputs, call)
            original = before[case]["before"] if before is not None else outcome
            match = canonical(original) == canonical(archived)
            if case in FAILURES:
                match = match and failed_at_24(original)
            row = {
                "case": case,
                "capture": inputs.capture,
                "forecast_model": frozen["projection"]["model_name"],
                "forecast_fingerprint": frozen["projection"]["fingerprint"],
                "free_transfers": call.state.free_transfers,
                "configured_deterministic_units": call.settings.solver_deterministic_time_limit,
                "wall_safety_seconds": call.settings.solver_time_limit_seconds,
                "before": original,
                "frozen_match_before": match,
                "criteria_met": match,
            }
            if before is not None:
                unchanged = canonical(original) == canonical(outcome)
                passed = (
                    outcome["has_solution"]
                    and len(outcome["weekly_points"]) == 3
                    and not outcome["error"]
                    and not outcome["accounting_failures"]
                )
                row.update(
                    after=outcome,
                    unchanged=unchanged,
                    criteria_met=match and passed and (case in FAILURES or unchanged),
                )
            record["rows"].append(row)
            record["complete"] = len(record["rows"]) == len(cases)
            benchmark.write(output, record)
            print(
                f"{case} {outcome['solver_status']} {outcome['seconds']:.1f}s "
                f"criteria={row['criteria_met']}",
                flush=True,
            )
    return all(row["criteria_met"] for row in record["rows"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--before", type=Path)
    parser.add_argument("--case", action="append", default=[])
    args = parser.parse_args()
    raise SystemExit(0 if measure(args.output, args.case, args.before) else 1)
