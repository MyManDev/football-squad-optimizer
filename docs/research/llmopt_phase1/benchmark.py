"""Offline Phase 1 replay. Run sequentially on one solver thread; never use a service.

python -m docs.research.llmopt_phase1.benchmark [--limit 1] [--output DIRECTORY]
Build schedule.ts first with bundle.mjs. The checked-in inputs need no private data.
"""

import argparse
import hashlib
import json
import platform
import subprocess
import sys
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter
from unittest.mock import patch

import ortools
from docs.research.llmopt_phase1.freeze import digest
from docs.research.llmopt_phase1.pairs import propose_pairs
from ortools.sat.python import cp_model
from scripts.measure_window_solver_highs import PublishedInputs, one_week_call, window_call

from squadopt.contracts.preferences import DecisionPreferences
from squadopt.planning import (
    ChipAvailability,
    PlanningHorizon,
    expected_window,
    optimize_transfer_plan,
)
from squadopt.planning.native_highs import native_window_executor
from squadopt.platform.advice_queue import FileJobQueue
from squadopt.platform.jobs_contract import AdviceJob
from squadopt.platform.native_windows import execute_native_window, native_window_version

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
SCENARIOS = ("normal", "wildcard", "freehit", "tight_bank", "conflicting_instructions")


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def snapshots():
    manifest = json.loads((HERE / "inputs.json").read_text())
    for item in manifest["snapshots"]:
        value = json.loads((HERE / item["path"]).read_text())
        if digest(value) != item["sha256"]:
            raise ValueError(f"Frozen input changed: {item['path']}")
        table = value["table"]
        inputs = PublishedInputs(
            table,
            {int(k): v for k, v in value["members"].items()},
            {int(k): v for k, v in value["fixture_counts"].items()},
            HERE,
            table["source_snapshot_id"],
        )
        yield value, inputs


@contextmanager
def capture_solves():
    """Observe every CP solve, including certificates and tie breaks, without model copies."""
    calls = []
    original = cp_model.CpSolver.solve

    def solve(solver, model, solution_callback=None):
        started = perf_counter()
        status = original(solver, model, solution_callback)
        response = solver.response_proto
        found = str(status.name) in ("OPTIMAL", "FEASIBLE")
        calls.append(
            dict(
                backend="cp-sat",
                status=status.name,
                seconds=perf_counter() - started,
                deterministic_units=float(response.deterministic_time),
                objective_raw=float(response.objective_value) if found else None,
                best_bound_raw=float(response.best_objective_bound) if found else None,
                threads=int(solver.parameters.num_search_workers),
            )
        )
        return status

    def native(packet, seconds):
        started = perf_counter()
        result = execute_native_window(packet, seconds)
        calls.append(
            dict(
                backend="highs-native",
                status=result["status"],
                seconds=perf_counter() - started,
                objective_raw=result["objective"],
                best_bound_raw=result["bound"],
                threads=result["threads"],
                wall_cap_seconds=seconds,
            )
        )
        return result

    with patch.object(cp_model.CpSolver, "solve", solve), native_window_executor(native):
        yield calls


def summary(plan, seconds, calls):
    diagnostics = plan.diagnostics
    expected = diagnostics.get("expected_lineup_window")
    # The surrogate CP bound cannot certify the rescored expected-lineup objective.
    bound = None if expected else diagnostics.get("best_objective_bound")
    gap = None if expected else diagnostics.get("absolute_optimality_gap")
    return dict(
        seconds=seconds,
        has_solution=plan.has_solution,
        solver_status=plan.solver_status.name,
        proof="not_proven"
        if expected
        else (
            "optimal"
            if plan.solver_status.name == "OPTIMAL"
            else "infeasible"
            if plan.solver_status.name == "INFEASIBLE"
            else "not_proven"
        ),
        objective=plan.objective_value,
        best_bound=bound,
        absolute_gap_points=gap,
        bound_scope="no_global_expected_lineup_bound" if expected else "planner_model",
        expected_net_points=sum(w.projected_score - w.transfer_hit_points for w in plan.weeks)
        if plan.has_solution
        else None,
        solver_calls=len(calls),
        cp_sat_calls=sum(c["backend"] == "cp-sat" for c in calls),
        native_calls=sum(c["backend"] == "highs-native" for c in calls),
        calls=calls,
        weeks=[
            dict(
                gameweek=w.gameweek,
                squad=sorted(int(p) for p in w.selected_squad.player_id),
                transfers_in=sorted(int(p) for p in w.transfers_in.player_id),
                transfers_out=sorted(int(p) for p in w.transfers_out.player_id),
                bank=w.bank_after_tenths,
                hit=w.transfer_hit_points,
                next_free_transfers=w.free_transfers_for_next_gameweek,
                chip=w.chip,
            )
            for w in plan.weeks
        ],
        expected_window=expected,
    )


def timed(function):
    started = perf_counter()
    with capture_solves() as calls:
        plan = function()
    return summary(plan, perf_counter() - started, calls)


def planner(call, request, *, state=None):
    preferences = DecisionPreferences.parse(request["preferences"])
    chip = request.get("chip")
    chips = None
    if chip:
        week = call.horizon.gameweeks[0]
        chips = ChipAvailability({chip: frozenset([week])}, {week: chip})
    return optimize_transfer_plan(
        call.horizon,
        state or call.state,
        call.settings,
        call.policy,
        chips=chips,
        preferences=preferences,
        linearization_level=call.linearization_level,
        protect_hold=True,
    )


def schedule(payload):
    result = subprocess.run(
        ["node", str(ROOT / ".codex-tmp/phase1-schedule.cjs")],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        check=True,
    )
    return json.loads(result.stdout)


def pricing(call, inputs, entry_id):
    """Cold-cache local queue admissions from the actual web-generated requests."""
    held = list(call.state.squad_player_ids)
    payload = dict(
        held=held,
        request=dict(
            leagueId=352490,
            entryId=entry_id,
            strategy="saf-puan",
            window=len(call.horizon.gameweeks),
            season="2026-27",
            gameweek=inputs.gameweek,
        ),
        draft=dict(
            hard=[],
            soft=[
                dict(kind="keep_player", player_id=held[0]),
                dict(kind="keep_player", player_id=held[1]),
                dict(kind="no_hits"),
            ],
            window=len(call.horizon.gameweeks),
        ),
    )
    run = schedule(payload)
    jobs = []
    admissions = []
    with TemporaryDirectory(prefix="llmopt-phase1-", dir=ROOT / ".codex-tmp") as temporary:
        queue = FileJobQueue(Path(temporary))

        def submit(request, label):
            identity = digest(request)
            stamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
            job = AdviceJob(f"phase1-{len(jobs)}", "queued", identity, identity, stamp, stamp)
            _, created = queue.submit_unique(job)
            admissions.append(created)
            result = timed(lambda: planner(call, request))
            jobs.append(dict(slot=label, request=request, created=created, **result))
            return result

        base = submit(run["base"], "base")
        if base["has_solution"]:
            results = [
                submit(slot["request"], f"priced-{i}") for i, slot in enumerate(run["slots"])
            ]
            run = schedule({**payload, "results": results})
            if run["combined"] and run["combined"]["request"]:
                submit(run["combined"]["request"], "combined")
    return dict(
        backend_jobs=sum(admissions),
        job_requests=len(admissions),
        solver_calls=sum(j["solver_calls"] for j in jobs),
        cp_sat_calls=sum(j["cp_sat_calls"] for j in jobs),
        native_calls=sum(j["native_calls"] for j in jobs),
        total_seconds=sum(j["seconds"] for j in jobs),
        prices=run["prices"],
        jobs=jobs,
    )


def scenario_control(call, scenario):
    held = list(call.state.squad_player_ids)
    outsiders = sorted(set(call.horizon.table.player_id) - set(held))
    state = replace(call.state, bank_tenths=0) if scenario == "tight_bank" else call.state
    preferences = dict(net_points_priority=True, save_chips=True)
    if scenario == "conflicting_instructions":
        preferences.update(hold_transfers=True, include_players=[outsiders[0]])
    request = dict(preferences=preferences)
    if scenario in ("wildcard", "freehit"):
        preferences["save_chips"] = False
        request["chip"] = scenario
    return timed(lambda: planner(call, request, state=state))


def expected_comparison(call, frozen):
    projection = frozen["projection"]
    table = call.horizon.table.loc[
        call.horizon.table.player_id.map(str).isin(projection["appearance_probability"])
    ].copy()
    # Matching capture's saved forecast, not the later publication's different model.
    first_counts = frozen["fixture_counts"][str(call.horizon.gameweeks[0])]
    for index, row in table.iterrows():
        player = str(row.player_id)
        count = frozen["fixture_counts"][str(row.gameweek)].get(str(row.team_id), 0)
        divisor = max(1, first_counts.get(str(row.team_id), 0))
        table.at[index, "expected_points"] = projection["expected_points"][player] * count / divisor
        table.at[index, "appearance_probability"] = projection["appearance_probability"][player]
    horizon = PlanningHorizon(table)
    settings = call.settings
    policy = replace(call.policy, allow_two_free_transfers=True)

    def run():
        return expected_window.optimize_expected_window(horizon, call.state, settings, policy)

    single = timed(run)
    with patch.object(expected_window, "propose_expected_swap", propose_pairs):
        pair = timed(run)
    a, b = single["expected_window"], pair["expected_window"]
    selected_a = next((p["utility"] for p in a["candidates"] if p["proposal"] == a["chosen"]), None)
    selected_b = next((p["utility"] for p in b["candidates"] if p["proposal"] == b["chosen"]), None)
    return dict(
        configured_deterministic_units=settings.solver_deterministic_time_limit,
        wall_safety_seconds=settings.solver_time_limit_seconds,
        excluded_missing_appearance_ids=sorted(
            set(call.horizon.table.player_id) - set(table.player_id)
        ),
        lineup_evaluation_cap=1153,
        forecast_model=projection["model_name"],
        forecast_fingerprint=projection["fingerprint"],
        selection_utility_gain_points=None
        if selected_a is None or selected_b is None
        else selected_b - selected_a,
        expected_net_gain_points=None
        if not single["has_solution"] or not pair["has_solution"]
        else pair["expected_net_points"] - single["expected_net_points"],
        single=single,
        up_to_two=pair,
    )


def measure(output, limit):
    output.mkdir(parents=True, exist_ok=True)
    count = 0
    for frozen, inputs in snapshots():
        for member_index, entry_id in enumerate(sorted(inputs.members)):
            if limit is not None and count >= limit:
                return
            case = f"gw{inputs.gameweek}-{entry_id}"
            scenario = SCENARIOS[count % len(SCENARIOS)]
            target = output / f"{case}.json"
            receipt = dict(case=case, scenario=scenario, capture=inputs.capture, windows={})
            for window in (1, 3):
                call = (
                    one_week_call(inputs, entry_id)
                    if window == 1
                    else window_call(inputs, entry_id, 3)
                )
                call = replace(
                    call,
                    policy=replace(call.policy.for_net_points(), max_transfers_per_gameweek=None),
                )
                print(f"{case} window={window}", flush=True)
                prices = pricing(call, inputs, entry_id) if member_index == 0 else None
                control = (
                    prices["jobs"][0]
                    if scenario == "normal" and prices
                    else scenario_control(call, scenario)
                )
                receipt["windows"][str(window)] = dict(pricing=prices, control=control)
                write(target, receipt)
            print(f"{case} expected-window comparison", flush=True)
            # Keep the member policy's discount and resource utility in the separate experiment.
            receipt["expected_comparison"] = expected_comparison(
                window_call(inputs, entry_id, 3), frozen
            )
            write(target, receipt)
            count += 1
            print(f"{case} complete", flush=True)


def aggregate(output):
    rows = [json.loads(p.read_text()) for p in sorted(output.glob("gw*.json"))]
    record = dict(
        kind="llmopt_phase1_offline_replay",
        repository_commit=subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        measured_at_utc=datetime.now(UTC).isoformat(),
        python=sys.version,
        platform=platform.platform(),
        ortools=ortools.__version__,
        highs=native_window_version(),
        execution="sequential local queue admissions and planner replay; not production latency",
        input_manifest_sha256=digest(json.loads((HERE / "inputs.json").read_text())),
        runner_sha256={
            p.name: hashlib.sha256(p.read_bytes().replace(b"\r\n", b"\n")).hexdigest()
            for p in sorted(HERE.glob("*.py"))
        },
        member_weeks=len(rows),
        rows=[],
    )
    for row in rows:
        item = dict(case=row["case"], scenario=row["scenario"], windows={})
        for window, value in row["windows"].items():
            pricing_result = value["pricing"]
            item["windows"][window] = dict(
                pricing=None
                if pricing_result is None
                else {
                    k: pricing_result[k]
                    for k in (
                        "backend_jobs",
                        "solver_calls",
                        "cp_sat_calls",
                        "native_calls",
                        "total_seconds",
                    )
                },
                control={
                    k: value["control"][k]
                    for k in (
                        "seconds",
                        "solver_status",
                        "proof",
                        "objective",
                        "best_bound",
                        "absolute_gap_points",
                    )
                },
            )
        comparison = row["expected_comparison"]
        item["expected_comparison"] = {
            k: comparison[k]
            for k in (
                "selection_utility_gain_points",
                "expected_net_gain_points",
            )
        }
        for arm in ("single", "up_to_two"):
            result = comparison[arm]
            review = result["expected_window"]
            item["expected_comparison"][arm] = dict(
                seconds=result["seconds"],
                proof=result["proof"],
                solver_calls=result["solver_calls"],
                chosen=review["chosen"],
                actual_units=review["actual_total"],
                optional_status=review["optional_swap"]["status"],
                optional_reason=review["optional_swap"].get("reason"),
            )
        record["rows"].append(item)
    write(HERE.parent / "llmopt_phase1_baseline.json", record)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--output", type=Path, default=HERE / "receipts")
    parser.add_argument("--aggregate-only", action="store_true")
    args = parser.parse_args()
    if not args.aggregate_only:
        measure(args.output, args.limit)
    aggregate(args.output)
