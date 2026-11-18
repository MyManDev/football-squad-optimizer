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
from docs.research.llmopt_phase1 import pairs as pair_module
from docs.research.llmopt_phase1.freeze import digest
from docs.research.llmopt_phase1.pairs import propose_pairs
from ortools.sat.python import cp_model
from scripts.measure_window_solver_highs import PublishedInputs, one_week_call, window_call

from squadopt.contracts.preferences import DecisionPreferences
from squadopt.optimization import SolverExecutionError, wall_clock_stopped_the_search
from squadopt.planning import (
    ChipAvailability,
    PlanningHorizon,
    expected_swap,
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
DEFAULT_OUTPUT = ROOT / "artifacts/llmopt_phase1_v2"
GAIN_KEYS = (
    "raw_xi_net_gain_points",
    "expected_lineup_net_gain_points",
    "selection_utility_gain_points",
)


@contextmanager
def accounting_checks():
    checks = []
    original = expected_swap.checked_work

    def checked(value, cap):
        try:
            return original(value, cap)
        except ValueError:
            checks.append(dict(actual=value, cap=cap))
            raise

    with (
        patch.object(expected_window, "checked_work", checked),
        patch.object(expected_swap, "checked_work", checked),
        patch.object(pair_module, "checked_work", checked),
    ):
        yield checks


def call_counts(calls):
    return dict(
        solver_calls=len(calls),
        cp_sat_calls=sum(c["backend"] == "cp-sat" for c in calls),
        native_calls=sum(c["backend"] == "highs-native" for c in calls),
        reported_thread_counts=sorted({c["threads"] for c in calls if c["threads"] is not None}),
        unknown_thread_calls=sum(c["threads"] is None for c in calls),
    )


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def provenance():
    return dict(
        repository_commit=subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        source_sha256={
            p.name: hashlib.sha256(p.read_bytes().replace(b"\r\n", b"\n")).hexdigest()
            for p in sorted(HERE.iterdir())
            if p.suffix in (".py", ".mjs", ".ts")
        },
        input_manifest_sha256=digest(json.loads((HERE / "inputs.json").read_text())),
        protocol_revision=2,
    )


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
                configured_deterministic_units=float(solver.parameters.max_deterministic_time),
                configured_wall_seconds=float(solver.parameters.max_time_in_seconds),
            )
        )
        return status

    def native(packet, seconds):
        started = perf_counter()
        try:
            result = execute_native_window(packet, seconds)
        except (RuntimeError, OSError, ValueError) as error:
            calls.append(
                dict(
                    backend="highs-native",
                    status="ERROR",
                    error=type(error).__name__,
                    seconds=perf_counter() - started,
                    objective_raw=None,
                    best_bound_raw=None,
                    threads=None,
                    wall_cap_seconds=seconds,
                )
            )
            raise
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
        raw_xi_net_points=sum(w.projected_score - w.transfer_hit_points for w in plan.weeks)
        if plan.has_solution
        else None,
        expected_lineup_net_points=sum(
            float(w.lineup_expectation["expected_net_points"]) for w in plan.weeks
        )
        if plan.has_solution and all(w.lineup_expectation is not None for w in plan.weeks)
        else None,
        selection_utility=next(
            (c["utility"] for c in expected["candidates"] if c["proposal"] == expected["chosen"]),
            None,
        )
        if expected
        else None,
        solver_limits={
            key: diagnostics.get(key)
            for key in (
                "solver_time_limit_seconds",
                "wall_time_limit_seconds",
                "solver_deterministic_time_limit",
                "deterministic_budget_source",
                "deterministic_time_used",
                "deterministic_time_budget_exhausted",
                "primary_deterministic_time",
            )
        },
        wall_clock_stopped=wall_clock_stopped_the_search(plan.solver_status, diagnostics),
        **call_counts(calls),
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
                starting_xi=sorted(int(p) for p in w.starting_xi.player_id),
                bench=[int(p) for p in w.bench.player_id],
                captain=int(w.captain.player_id),
                vice_captain=None if w.vice_captain_id is None else int(w.vice_captain_id),
                raw_xi_net_points=w.projected_score - w.transfer_hit_points,
                expected_lineup_net_points=None
                if w.lineup_expectation is None
                else float(w.lineup_expectation["expected_net_points"]),
            )
            for w in plan.weeks
        ],
        expected_window=expected,
    )


def timed(function, *, capture_expected_failure=False):
    started = perf_counter()
    with capture_solves() as calls:
        try:
            plan = function()
        except (ValueError, SolverExecutionError) as error:
            known = isinstance(error, SolverExecutionError) or str(error) == (
                "Invalid deterministic-work accounting for expected windows."
            )
            if not capture_expected_failure or not known:
                raise
            return dict(
                seconds=perf_counter() - started,
                has_solution=False,
                solver_status="ERROR",
                proof="not_proven",
                objective=None,
                best_bound=None,
                absolute_gap_points=None,
                raw_xi_net_points=None,
                expected_lineup_net_points=None,
                selection_utility=None,
                solver_limits=None,
                wall_clock_stopped=None,
                **call_counts(calls),
                calls=calls,
                error=dict(type=type(error).__name__, message=str(error)),
                expected_window=dict(
                    chosen=None,
                    candidates=[],
                    actual_total=None,
                    optional_swap=dict(status="not_run", reason="expected_window_failed"),
                ),
            )
    return summary(plan, perf_counter() - started, calls)


def compact_plan(result):
    """Enough committed evidence to check every reported difference without raw receipts."""
    keys = (
        "seconds",
        "has_solution",
        "solver_status",
        "proof",
        "objective",
        "best_bound",
        "absolute_gap_points",
        "bound_scope",
        "raw_xi_net_points",
        "expected_lineup_net_points",
        "selection_utility",
        "solver_limits",
        "wall_clock_stopped",
        "solver_calls",
        "cp_sat_calls",
        "native_calls",
        "reported_thread_counts",
        "unknown_thread_calls",
        "error",
        "accounting_failures",
    )
    compact = {key: result.get(key) for key in keys}
    compact["decision_sha256"] = digest(result.get("weeks", []))
    compact["weekly_points"] = [
        {
            key: w[key]
            for key in (
                "gameweek",
                "raw_xi_net_points",
                "expected_lineup_net_points",
                "bank",
                "hit",
                "next_free_transfers",
                "chip",
            )
        }
        for w in result.get("weeks", [])
    ]
    review = result.get("expected_window")
    if review:
        optional = dict(review["optional_swap"])
        search = optional.pop("lineup_search", None)
        if search:
            optional["lineup_summary"] = dict(
                evaluations=search["evaluations"],
                budget_exhausted_weeks=[
                    w["gameweek"] for w in search["weeks"] if w["budget_exhausted"]
                ],
            )
        compact.update(
            chosen=review["chosen"],
            actual_units=review["actual_total"],
            optional=optional,
            lineup_evaluations=review.get("lineup_evaluations"),
            lineup_evaluation_cap=review.get("lineup_evaluation_cap"),
            selection_policy=review.get("selection_policy"),
        )
    return compact


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
    requests = []
    computed = {}
    with TemporaryDirectory(prefix="llmopt-phase1-", dir=ROOT / ".codex-tmp") as temporary:
        queue = FileJobQueue(Path(temporary))

        def submit(request, label):
            identity = digest(request)
            stamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
            job = AdviceJob(f"phase1-{len(jobs)}", "queued", identity, identity, stamp, stamp)
            _, created = queue.submit_unique(job)
            admissions.append(created)
            requests.append(dict(slot=label, fingerprint=identity, created=created))
            if not created:
                if identity not in computed:
                    raise ValueError("A cold queue join has no completed local result.")
                return computed[identity]
            result = timed(lambda: planner(call, request))
            computed[identity] = result
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
        deduplicated_requests=len(admissions) - sum(admissions),
        solver_calls=sum(j["solver_calls"] for j in jobs),
        cp_sat_calls=sum(j["cp_sat_calls"] for j in jobs),
        native_calls=sum(j["native_calls"] for j in jobs),
        total_seconds=sum(j["seconds"] for j in jobs),
        prices=run["prices"],
        jobs=jobs,
        requests=requests,
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
    if not set(call.state.squad_player_ids) <= set(table.player_id):
        raise ValueError("Expected-window support must retain every held player.")
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

    with accounting_checks() as checks:
        single = timed(run, capture_expected_failure=True)
    single["accounting_failures"] = checks.copy()
    with (
        patch.object(expected_window, "propose_expected_swap", propose_pairs),
        accounting_checks() as checks,
    ):
        pair = timed(run, capture_expected_failure=True)
    pair["accounting_failures"] = checks.copy()

    def difference(key):
        a, b = single.get(key), pair.get(key)
        return None if a is None or b is None else b - a

    return dict(
        configured_deterministic_units=settings.solver_deterministic_time_limit,
        wall_safety_seconds=settings.solver_time_limit_seconds,
        excluded_missing_appearance_ids=sorted(
            set(call.horizon.table.player_id) - set(table.player_id)
        ),
        lineup_evaluation_cap=next(
            (
                p["expected_window"]["lineup_evaluation_cap"]
                for p in (single, pair)
                if "lineup_evaluation_cap" in p["expected_window"]
            ),
            None,
        ),
        forecast_model=projection["model_name"],
        forecast_fingerprint=projection["fingerprint"],
        selection_utility_gain_points=difference("selection_utility"),
        raw_xi_net_gain_points=difference("raw_xi_net_points"),
        expected_lineup_net_gain_points=difference("expected_lineup_net_points"),
        single=single,
        up_to_two=pair,
    )


def measure(output, limit, resume=False, reuse_completed=False):
    output.mkdir(parents=True, exist_ok=True)
    stamp = provenance()
    count = 0
    for frozen, inputs in snapshots():
        for member_index, entry_id in enumerate(sorted(inputs.members)):
            if limit is not None and count >= limit:
                return
            case = f"gw{inputs.gameweek}-{entry_id}"
            scenario = SCENARIOS[count % len(SCENARIOS)]
            target = output / f"{case}.json"
            receipt = dict(
                case=case, scenario=scenario, capture=inputs.capture, windows={}, provenance=stamp
            )
            if reuse_completed and target.exists():
                prior = json.loads(target.read_text())
                prior_stamp = prior.get("provenance", {})
                if "expected_comparison" in prior:
                    if prior_stamp.get("protocol_revision") != stamp["protocol_revision"]:
                        raise ValueError(
                            "Completed-case reuse requires the same protocol revision."
                        )
                    if prior_stamp.get("input_manifest_sha256") != stamp["input_manifest_sha256"]:
                        raise ValueError("Completed-case reuse requires identical frozen inputs.")
                    prior_sources = prior_stamp["source_sha256"]
                    new_sources = stamp["source_sha256"]
                    if prior_sources != new_sources:
                        raise ValueError(
                            "Completed-case reuse changed a proposal, probe or input runner."
                        )
                    subprocess.run(
                        [
                            "git",
                            "diff",
                            "--exit-code",
                            prior_stamp["repository_commit"],
                            "--",
                            "src",
                            "web",
                            "scripts/measure_window_solver_highs.py",
                        ],
                        check=True,
                        capture_output=True,
                    )
                    print(
                        f"{case} reuse completed case at {prior_stamp['repository_commit']}",
                        flush=True,
                    )
                    count += 1
                    continue
            if resume and target.exists():
                receipt = json.loads(target.read_text())
                if receipt.get("provenance") != stamp:
                    raise ValueError("Resume requires the identical committed runner and inputs.")
            for window in (1, 3):
                if str(window) in receipt["windows"]:
                    continue
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
            if "expected_comparison" not in receipt:
                receipt["expected_comparison"] = expected_comparison(
                    window_call(inputs, entry_id, 3), frozen
                )
            write(target, receipt)
            count += 1
            print(f"{case} complete", flush=True)


def aggregate(output):
    rows = [json.loads(p.read_text()) for p in sorted(output.glob("gw*.json"))]
    if not rows or any("expected_comparison" not in row for row in rows):
        raise ValueError("Only completed cases can be aggregated.")
    stamp = provenance()
    if any(
        row["provenance"]["input_manifest_sha256"] != stamp["input_manifest_sha256"]
        or row["provenance"].get("protocol_revision") != stamp["protocol_revision"]
        for row in rows
    ):
        raise ValueError("Do not aggregate different frozen inputs.")
    record = dict(
        kind="llmopt_phase1_offline_replay",
        **stamp,
        measured_at_utc=datetime.now(UTC).isoformat(),
        python=sys.version,
        platform=platform.platform(),
        ortools=ortools.__version__,
        highs=native_window_version(),
        execution="sequential local queue admissions and planner replay; not production latency",
        member_weeks=len(rows),
        measurement_programs={digest(row["provenance"]): row["provenance"] for row in rows},
        rows=[],
    )
    for row in rows:
        item = dict(
            case=row["case"],
            scenario=row["scenario"],
            windows={},
            measurement_program=digest(row["provenance"]),
        )
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
                        "job_requests",
                        "deduplicated_requests",
                    )
                },
                control=compact_plan(value["control"]),
            )
        comparison = row["expected_comparison"]
        item["expected_comparison"] = {
            k: comparison[k]
            for k in (
                *GAIN_KEYS,
                "configured_deterministic_units",
                "wall_safety_seconds",
                "lineup_evaluation_cap",
                "excluded_missing_appearance_ids",
            )
        }
        for arm in ("single", "up_to_two"):
            result = comparison[arm]
            item["expected_comparison"][arm] = compact_plan(result)
        record["rows"].append(item)
    target = (
        HERE.parent / "llmopt_phase1_baseline.json"
        if output.resolve() == DEFAULT_OUTPUT.resolve()
        else output / "summary.json"
    )
    write(target, record)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--aggregate-only", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--reuse-completed", action="store_true")
    args = parser.parse_args()
    if args.limit is not None and args.output.resolve() == DEFAULT_OUTPUT.resolve():
        parser.error("A pilot requires a separate --output directory.")
    if not args.aggregate_only:
        measure(args.output, args.limit, args.resume, args.reuse_completed)
    aggregate(args.output)
