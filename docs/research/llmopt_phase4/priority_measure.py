"""Sequential offline server/device priority comparison; never run beside tests.

python -m docs.research.llmopt_phase4.priority_measure
"""

import json
import subprocess
from dataclasses import asdict, replace
from pathlib import Path

from docs.research.llmopt_phase1.benchmark import planner, snapshots, summary
from docs.research.llmopt_phase3.measure import bundles, digest
from scripts.measure_window_solver_highs import one_week_call

from squadopt.contracts.preferences import DecisionPreferences
from squadopt.contracts.priority_preferences import PriorityProgram
from squadopt.optimization.work_budget import WorkBudget, work_budget
from squadopt.planning import ChipAvailability
from squadopt.planning.optimizer import optimize_priority_preferences

ROOT = Path(__file__).resolve().parents[3]
SOURCES = (
    "docs/research/llmopt_phase4/priority_measure.py",
    "docs/research/llmopt_phase4/priority_probe.ts",
    "docs/research/llmopt_phase4/priority_bundle.mjs",
    "src/squadopt/planning/optimizer.py",
    "web/src/features/league/device/priority.ts",
    "web/src/features/league/device/preferenceBundle.ts",
    "web/src/features/league/device/requests.ts",
    "web/src/features/league/device/lp/memberWeek.ts",
    "web/src/features/league/device/preferences.ts",
    "web/src/features/league/device/solve/week.ts",
    "web/src/features/league/device/solve/ceiling.ts",
    "web/src/features/league/advice/preferenceBundle.ts",
    "web/src/features/league/advice/decisionPreferences.ts",
)


def main():
    controls = json.loads((ROOT / "docs/research/llmopt_phase1_baseline.json").read_bytes())
    controls = {row["case"]: row for row in controls["rows"]}
    rows, cases = [], []
    subprocess.run(
        ["node", "docs/research/llmopt_phase4/priority_bundle.mjs"], cwd=ROOT, check=True
    )
    for _, inputs in snapshots():
        for entry in sorted(inputs.members):
            key = f"gw{inputs.gameweek}-{entry}"
            scenario = controls[key]["scenario"]
            call = one_week_call(inputs, entry)
            call = replace(
                call,
                settings=replace(
                    call.settings,
                    solver_time_limit_seconds=1800,
                    solver_deterministic_time_limit=20,
                ),
                policy=call.policy.for_net_points(),
                linearization_level=2,
            )
            block = dict(inputs.members[entry])
            if scenario == "tight_bank":
                block["bank_tenths"] = 0
                call = replace(call, state=replace(call.state, bank_tenths=0))
            preferences = dict(net_points_priority=True, save_chips=True)
            if scenario == "conflicting_instructions":
                outsiders = sorted(set(call.horizon.table.player_id) - set(block["held"]))
                preferences.update(hold_transfers=True, include_players=[int(outsiders[0])])
            chip = scenario if scenario in ("wildcard", "freehit") else None
            if chip:
                preferences["save_chips"] = False
            bundle = dict(bundles(block["held"], chip))["priority_total"]
            budgets = [WorkBudget(21), WorkBudget(21)]
            with work_budget(budgets[0]):
                main_plan = planner(call, dict(preferences=preferences, chip=chip))
            result = None
            if main_plan.has_solution:
                week = call.horizon.gameweeks[0]
                rights = ChipAvailability({chip: frozenset([week])}, {week: chip}) if chip else None
                with work_budget(budgets[1]):
                    outcome = optimize_priority_preferences(
                        call.horizon,
                        call.state,
                        call.settings,
                        call.policy,
                        main_plan,
                        PriorityProgram.parse(bundle["program"]),
                        hard=DecisionPreferences.parse(preferences),
                        chips=rights,
                        work_limit=20,
                    )
                result = dict(
                    plan=summary(outcome.plan, 0, []),
                    satisfied=list(outcome.satisfied),
                    completed_priorities=list(outcome.completed_priorities),
                    total_cost=outcome.total_cost,
                    budget_exhausted=outcome.budget_exhausted,
                )
            rows.append(
                dict(
                    case=key,
                    scenario=scenario,
                    server_main=summary(main_plan, 0, []),
                    server=result,
                    receipts=[asdict(budget) for budget in budgets],
                )
            )
            cases.append(
                dict(
                    id=key,
                    document=inputs.table,
                    entry=block,
                    preferences=preferences,
                    chip=chip,
                    preferenceBundle=bundle,
                )
            )
            print(f"server {key}: {main_plan.solver_status.name}", flush=True)
    response = subprocess.run(
        ["node", ".codex-tmp/phase4-priority.mjs"],
        input=json.dumps(cases),
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=True,
    )
    devices = {row["id"]: row for row in json.loads(response.stdout)}
    for row in rows:
        device = devices[row["case"]]
        row["device"] = device
        answer = device.get("answer")
        server = row["server"]
        if server is None:
            row["equal"] = (
                row["server_main"]["solver_status"] == "INFEASIBLE"
                and device["status"] == "Infeasible"
            )
            continue
        selected = answer["preference_bundle"]["selected"]["answer"] if answer else None
        metadata = selected.get("priority_preferences") if selected else None
        same_points = selected is not None and round(selected["objective_scaled"]) == round(
            server["plan"]["objective"] * cases[0]["document"]["rules"]["expected_points_scale"]
        )
        same_counts = metadata is not None and sorted(metadata["satisfied"]) == sorted(
            server["satisfied"]
        )
        row["equal"] = (
            same_points
            and same_counts
            and metadata["completed_priorities"] == server["completed_priorities"]
        )
        row["same_transfer_decision"] = (
            selected is not None
            and sorted(selected["squad"]) == server["plan"]["weeks"][0]["squad"]
        )
        row["different_equal_score_decision"] = row["equal"] and not row["same_transfer_decision"]
    report = dict(
        contract_version="llmopt_phase4_priority_audit_v1",
        producer_repository_commit=subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        source_sha256={name: digest(ROOT / name) for name in SOURCES},
        frozen_manifest_sha256=digest(ROOT / "docs/research/llmopt_phase1/inputs.json"),
        scope=(
            "Original twenty controls, active 20-unit linearization-2 preference profile. "
            "Offline core calls and production device bundle; no tests or CI overlap. "
            "Named-chip combinations remain server-routed in the page."
        ),
        server_jobs_opened=0,
        network_calls=0,
        member_weeks=len(rows),
        equal=sum(row["equal"] for row in rows),
        feasible=sum(row["server"] is not None for row in rows),
        different_equal_score_decisions=sum(
            row.get("different_equal_score_decision", False) for row in rows
        ),
        max_device_seconds=max(row["device"]["seconds"] for row in rows),
        rows=rows,
    )
    (ROOT / "docs/research/llmopt_phase4_priority_audit.json").write_text(
        json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8", newline="\n"
    )
    print(
        json.dumps(
            {key: value for key, value in report.items() if key not in ("rows", "source_sha256")}
        ),
        flush=True,
    )
    if report["equal"] != 20:
        raise SystemExit("Priority equality acceptance failed.")


if __name__ == "__main__":
    main()
