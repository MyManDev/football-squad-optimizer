"""Offline one-week hard-rule parity on all twenty immutable Phase 1 member-weeks.

Run separately from tests. This uses frozen published coefficients, not a replacement
claim about the unavailable served football captures.
"""

import hashlib
import json
import subprocess
from dataclasses import replace
from pathlib import Path
from time import perf_counter

from docs.research.llmopt_phase1.benchmark import snapshots
from scripts.measure_window_solver_highs import one_week_call

from squadopt.contracts.preferences import DecisionPreferences
from squadopt.optimization import OptimizationConfig
from squadopt.planning import optimize_transfer_plan

ROOT = Path(__file__).resolve().parents[3]


def main():
    subprocess.run(["node", "docs/research/llmopt_phase4/bundle.mjs"], cwd=ROOT, check=True)
    rows, cases = [], []
    for _, inputs in snapshots():
        for entry, block in inputs.members.items():
            call = one_week_call(inputs, entry)
            for net in (False, True):
                preferences = DecisionPreferences(
                    keep_players=(block["held"][0],), net_points_priority=net
                )
                started = perf_counter()
                plan = optimize_transfer_plan(
                    call.horizon,
                    call.state,
                    replace(
                        OptimizationConfig(),
                        solver_time_limit_seconds=1800,
                        solver_deterministic_time_limit=20,
                    ),
                    call.policy,
                    linearization_level=2,
                    preferences=preferences,
                    protect_hold=True,
                )
                identifier = f"{inputs.capture}:{entry}:{'net' if net else 'selection'}"
                row = dict(
                    id=identifier,
                    capture=inputs.capture,
                    entry_id=entry,
                    gameweek=inputs.gameweek,
                    objective_kind="net_points" if net else "selection_utility",
                    server_status=plan.solver_status.name,
                    server_objective=plan.objective_value,
                    server_seconds=perf_counter() - started,
                    server_squad=sorted(int(v) for v in plan.weeks[0].selected_squad.player_id)
                    if plan.weeks
                    else None,
                )
                rows.append(row)
                cases.append(
                    dict(
                        id=identifier,
                        document=inputs.table,
                        entry=block,
                        preferences=preferences.payload(),
                    )
                )
                print(f"server {identifier} {plan.solver_status.name}", flush=True)
    completed = subprocess.run(
        ["node", ".codex-tmp/phase4-probe.mjs"],
        input=json.dumps(cases),
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=True,
    )
    device = {row["id"]: row for row in json.loads(completed.stdout)}
    for row in rows:
        result = device[row["id"]]
        answer = result.get("answer")
        value = (
            answer["objectiveScaled"] / cases[0]["document"]["rules"]["expected_points_scale"]
            if answer
            else None
        )
        row.update(
            device_status=result["status"],
            device_seconds=result["seconds"],
            device_objective=value,
            objective_equal=value is not None and abs(value - row["server_objective"]) < 1e-8,
            same_decision=answer is not None and answer["squad"] == row["server_squad"],
            device_error=result.get("error"),
        )
    result = dict(
        contract_version="llmopt_device_parity_v1",
        producer_repository_commit=subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        runner="docs/research/llmopt_phase4/measure.py",
        runner_sha256=hashlib.sha256(
            Path(__file__).read_bytes().replace(b"\r\n", b"\n")
        ).hexdigest(),
        input_manifest_sha256=hashlib.sha256(
            (ROOT / "docs/research/llmopt_phase1/inputs.json")
            .read_bytes()
            .replace(b"\r\n", b"\n")
        ).hexdigest(),
        member_weeks=20,
        comparisons=len(rows),
        equal_objectives=sum(row["objective_equal"] for row in rows),
        local_only=True,
        server_jobs_opened=0,
        rows=rows,
    )
    output = ROOT / "docs/research/llmopt_phase4_parity.json"
    output.write_text(
        json.dumps(result, indent=2, allow_nan=False) + "\n", encoding="utf-8", newline="\n"
    )


if __name__ == "__main__":
    main()
