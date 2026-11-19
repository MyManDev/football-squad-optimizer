"""Real Phase 1 controls under durable 21/122-unit job allocations.

Run serially without tests: python -m docs.research.llmopt_phase2.measure_solver_budget
The separate admission replay measures orchestration. This runner measures actual
planner calls and their charged work, not a live service or synthetic solver answer.
"""

import hashlib
import json
import subprocess
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import ortools
from docs.research.llmopt_phase1 import benchmark
from scripts.measure_window_solver_highs import one_week_call, window_call

from squadopt.contracts.llmopt_run import RunReference, job_capacity
from squadopt.optimization.work_budget import work_budget
from squadopt.platform.advice_cache import FileAdviceCache
from squadopt.platform.advice_queue import FileJobQueue
from squadopt.platform.advice_runs import FileRunStore
from squadopt.platform.jobs_contract import AdviceJob

ROOT = Path(__file__).resolve().parents[3]
STAMP = "2026-11-19T00:00:00Z"
SOURCES = (
    Path(__file__).relative_to(ROOT),
    Path("src/squadopt/platform/advice_runs.py"),
    Path("src/squadopt/optimization/work_budget.py"),
    Path("src/squadopt/optimization/cpsat.py"),
    Path("src/squadopt/planning/optimizer.py"),
    Path("src/squadopt/planning/models.py"),
    Path("src/squadopt/contracts/llmopt_run.py"),
)


def digest(path):
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def run_case(root, inputs, entry, original, window):
    key = hashlib.sha256(f"{inputs.capture}:{entry}:{window}".encode()).hexdigest()
    queue, runs = FileJobQueue(root / "queue"), FileRunStore(root / "runs")
    reference = RunReference(key[:32], "base")
    job = AdviceJob(
        job_id=f"advice-{key[:16]}-1",
        status="queued",
        request_fingerprint=key,
        cache_key=key,
        created_at_utc=STAMP,
        updated_at_utc=STAMP,
        contract_version="backend_jobs_v2",
    )
    with runs.transaction(at_utc=STAMP) as tx:
        tx.bind(reference, key, window, key, queue, capture=inputs.capture)
        tx.reserve(reference, key, job.job_id)
    queue.submit_unique(job)
    claimed = queue.claim(at_utc=STAMP)
    assert claimed is not None and claimed.job_id == job.job_id
    budget = runs.allocation(job.job_id)
    assert budget is not None and budget.limit == job_capacity(window)
    call = one_week_call(inputs, entry) if window == 1 else window_call(inputs, entry, 3)
    call = replace(
        call, policy=replace(call.policy.for_net_points(), max_transfers_per_gameweek=None)
    )
    native = benchmark.execute_native_window

    def charged_native(packet, seconds):
        budget.reserve_native(seconds)
        return native(packet, seconds)

    try:
        with work_budget(budget), patch.object(benchmark, "execute_native_window", charged_native):
            result = benchmark.scenario_control(call, original["scenario"])
    finally:
        runs.finish(job.job_id, budget)
    queue.complete(
        claimed,
        cache=FileAdviceCache(root / "answers"),
        payload=json.dumps(result, allow_nan=False).encode(),
        at_utc=STAMP,
    )
    expected = original["windows"][str(window)]["control"]
    compact = benchmark.compact_plan(result)
    feasible = result["has_solution"]
    numeric_equal = (
        feasible
        and expected["has_solution"]
        and abs(result["objective"] - expected["objective"]) < 1e-8
    )
    both_infeasible = result["solver_status"] == expected["solver_status"] == "INFEASIBLE"
    state = json.loads(runs.path.read_bytes())
    return dict(
        case=original["case"],
        capture=inputs.capture,
        entry_id=entry,
        scenario=original["scenario"],
        window=window,
        allocation=budget.limit,
        charged_units=budget.cp_used + budget.native_reserved,
        cp_units=budget.cp_used,
        native_units=budget.native_reserved,
        within_allocation=budget.cp_used + budget.native_reserved <= budget.limit,
        same_status=result["solver_status"] == expected["solver_status"],
        same_numeric_objective=numeric_equal,
        both_infeasible=both_infeasible,
        same_decision=compact["decision_sha256"] == expected["decision_sha256"],
        frozen_objective=expected["objective"],
        frozen_status=expected["solver_status"],
        work_receipt=state["jobs"][job.job_id]["receipt"],
        admitted_local_jobs=len(queue.jobs()),
        result=compact,
        solver_calls=result["calls"],
    )


def main():
    baseline_path = ROOT / "docs/research/llmopt_phase1_baseline.json"
    baseline = json.loads(baseline_path.read_bytes())
    by_case = {row["case"]: row for row in baseline["rows"]}
    rows = []
    with TemporaryDirectory(prefix="llmopt-budget-controls-", dir=ROOT / ".codex-tmp") as folder:
        for _, inputs in benchmark.snapshots():
            for entry in sorted(inputs.members):
                original = by_case[f"gw{inputs.gameweek}-{entry}"]
                for window in (1, 3):
                    path = Path(folder) / f"{inputs.gameweek}-{entry}-{window}"
                    row = run_case(path, inputs, entry, original, window)
                    rows.append(row)
                    print(
                        f"{row['case']} window={window} {row['result']['solver_status']} "
                        f"units={row['charged_units']:.6f}/{row['allocation']} "
                        f"same={row['same_numeric_objective'] or row['both_infeasible']}",
                        flush=True,
                    )
    report = dict(
        contract_version="llmopt_phase2_real_solver_budget_v1",
        producer_repository_commit=subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        source_sha256={path.as_posix(): digest(ROOT / path) for path in SOURCES},
        frozen_manifest_sha256=digest(ROOT / "docs/research/llmopt_phase1/inputs.json"),
        baseline_record_sha256=digest(baseline_path),
        solver_version=ortools.__version__,
        execution=(
            "Sequential local production planner controls under real durable V2 job "
            "allocations. Admission is measured separately; no live endpoint or test overlap."
        ),
        local_only=True,
        network_calls=0,
        member_weeks=20,
        windows={
            str(window): dict(
                controls=sum(row["window"] == window for row in rows),
                equal_numeric_objectives=sum(
                    row["window"] == window and row["same_numeric_objective"] for row in rows
                ),
                equal_infeasibilities=sum(
                    row["window"] == window and row["both_infeasible"] for row in rows
                ),
                equal_statuses=sum(row["window"] == window and row["same_status"] for row in rows),
                equal_decisions=sum(
                    row["window"] == window and row["same_decision"] for row in rows
                ),
                maximum_charged_units=max(
                    row["charged_units"] for row in rows if row["window"] == window
                ),
                allocation=job_capacity(window),
                internal_solver_calls=sum(
                    len(row["solver_calls"]) for row in rows if row["window"] == window
                ),
            )
            for window in (1, 3)
        },
        all_within_allocation=all(row["within_allocation"] for row in rows),
        all_frozen_results_equal=all(
            row["same_status"]
            and (row["same_numeric_objective"] or row["both_infeasible"])
            and row["same_decision"]
            for row in rows
        ),
        rows=rows,
    )
    output = ROOT / "docs/research/llmopt_phase2_solver_budget.json"
    output.write_text(
        json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8", newline="\n"
    )
    print(json.dumps(report["windows"]), flush=True)


if __name__ == "__main__":
    main()
