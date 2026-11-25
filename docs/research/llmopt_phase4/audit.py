"""Replay the actual frozen controls and the served preference profile independently.

Run serially, without tests or any live endpoint. Never alter Phase 1 records.
python -m docs.research.llmopt_phase4.audit
"""

import hashlib
import json
import subprocess
from dataclasses import replace
from pathlib import Path

from docs.research.llmopt_phase1.benchmark import scenario_control, snapshots
from scripts.measure_window_solver_highs import one_week_call

ROOT = Path(__file__).resolve().parents[3]
PROFILES = ("frozen_control", "served_control", "served_no_added_rule")


def source_hash(path):
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def same_number(left, right):
    if left is None or right is None:
        return left is None and right is None
    return abs(left - right) < 1e-8


def main():
    baseline = json.loads((ROOT / "docs/research/llmopt_phase1_baseline.json").read_bytes())
    controls = {row["case"]: row for row in baseline["rows"]}
    rows, cases = [], []
    subprocess.run(["node", "docs/research/llmopt_phase4/audit_bundle.mjs"], cwd=ROOT, check=True)
    for _, inputs in snapshots():
        for entry in sorted(inputs.members):
            key = f"gw{inputs.gameweek}-{entry}"
            original = controls[key]
            for profile in PROFILES:
                call = one_week_call(inputs, entry)
                call = replace(
                    call,
                    policy=replace(call.policy.for_net_points(), max_transfers_per_gameweek=None),
                )
                scenario = original["scenario"]
                if profile != "frozen_control":
                    call = replace(
                        call,
                        settings=replace(
                            call.settings,
                            solver_time_limit_seconds=1800,
                            solver_deterministic_time_limit=20,
                        ),
                        linearization_level=2,
                    )
                if profile == "served_no_added_rule" and scenario != "tight_bank":
                    scenario = "normal"
                result = scenario_control(call, scenario)
                identifier = f"{key}:{profile}"
                preferences = dict(net_points_priority=True, save_chips=True)
                if scenario == "conflicting_instructions":
                    outsiders = sorted(
                        set(call.horizon.table.player_id) - set(call.state.squad_player_ids)
                    )
                    preferences.update(hold_transfers=True, include_players=[int(outsiders[0])])
                chip = scenario if scenario in ("wildcard", "freehit") else None
                if chip:
                    preferences["save_chips"] = False
                block = dict(inputs.members[entry])
                if scenario == "tight_bank":
                    block["bank_tenths"] = 0
                frozen = original["windows"]["1"]["control"]
                rows.append(
                    dict(
                        id=identifier,
                        case=key,
                        capture=inputs.capture,
                        profile=profile,
                        frozen_scenario=original["scenario"],
                        applied_scenario=scenario,
                        preferences=preferences,
                        chip=chip,
                        bank_tenths=block["bank_tenths"],
                        server=result,
                        frozen_objective=frozen["objective"],
                        frozen_status=frozen["solver_status"],
                    )
                )
                cases.append(
                    dict(
                        id=identifier,
                        document=inputs.table,
                        entry=block,
                        preferences=preferences,
                        chip=chip,
                    )
                )
                print(
                    f"server {identifier}: {result['solver_status']} {result['objective']}",
                    flush=True,
                )
    response = subprocess.run(
        ["node", ".codex-tmp/phase4-audit.mjs"],
        input=json.dumps(cases),
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=True,
    )
    devices = {row["id"]: row for row in json.loads(response.stdout)}
    for row, case in zip(rows, cases, strict=True):
        device = devices[row["id"]]
        answer = device.get("answer")
        value = answer["expected_own_points"] - answer["transfer_hit_points"] if answer else None
        server = row["server"]
        server_feasible = server["has_solution"]
        device_feasible = answer is not None
        infeasible_equal = (
            server["solver_status"] == "INFEASIBLE" and device["status"] == "Infeasible"
        )
        numeric_equal = (
            server_feasible and device_feasible and abs(value - server["objective"]) < 1e-8
        )
        server_squad = server["weeks"][0]["squad"] if server_feasible else None
        squad = (
            sorted(
                (set(case["entry"]["held"]) - set(answer["transfers_out"]))
                | set(answer["transfers_in"])
            )
            if answer
            else None
        )
        row.update(
            device=device,
            device_net_points=value,
            feasibility_equal=(server_feasible and device_feasible) or infeasible_equal,
            numeric_objective_equal=numeric_equal,
            same_transfer_decision=server_squad == squad if answer else None,
            objective_difference=value - server["objective"]
            if answer and server_feasible
            else None,
            frozen_replay_equal=(
                server["solver_status"] == row["frozen_status"]
                and same_number(server["objective"], row["frozen_objective"])
            ),
        )
    counts = {}
    for profile in PROFILES:
        subset = [row for row in rows if row["profile"] == profile]
        counts[profile] = dict(
            comparisons=len(subset),
            feasible_server=sum(row["server"]["has_solution"] for row in subset),
            equal_feasibility=sum(row["feasibility_equal"] for row in subset),
            equal_numeric_objective=sum(row["numeric_objective_equal"] for row in subset),
            both_proved_infeasible=sum(
                row["server"]["solver_status"] == "INFEASIBLE"
                and row["device"]["status"] == "Infeasible"
                for row in subset
            ),
            same_transfer_decision=sum(row["same_transfer_decision"] is True for row in subset),
            different_equal_score_decision=sum(
                row["same_transfer_decision"] is False and row["numeric_objective_equal"]
                for row in subset
            ),
            frozen_replay_equal=sum(row["frozen_replay_equal"] for row in subset),
        )
    report = dict(
        contract_version="llmopt_phase4_scope_audit_v1",
        producer_repository_commit=subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        source_sha256={
            str(path.relative_to(ROOT)): source_hash(path)
            for path in (
                Path(__file__),
                ROOT / "docs/research/llmopt_phase4/audit_probe.ts",
                ROOT / "docs/research/llmopt_phase4/audit_bundle.mjs",
                ROOT / "src/squadopt/planning/optimizer.py",
                ROOT / "web/src/features/league/device/solve/week.ts",
                ROOT / "web/src/features/league/device/lp/memberWeek.ts",
                ROOT / "web/src/features/league/device/preferences.ts",
            )
        },
        frozen_manifest_sha256=source_hash(ROOT / "docs/research/llmopt_phase1/inputs.json"),
        baseline_record_sha256=source_hash(ROOT / "docs/research/llmopt_phase1_baseline.json"),
        execution=(
            "Sequential offline local function calls and the production device solvePlan; "
            "no test overlap."
        ),
        scope=(
            "Frozen published coefficients, not unavailable served football bundles. "
            "No extra keep rule. Cumulative device ceiling 120 seconds per complete answer. "
            "Frozen profile retains its original default linearization and 20 units; "
            "served profile uses linearization 2 and 20 units. "
            "No warm-start or enlarged work limit."
        ),
        server_jobs_opened=0,
        network_calls=0,
        member_weeks=20,
        comparisons=len(rows),
        summary=counts,
        rows=rows,
    )
    output = ROOT / "docs/research/llmopt_phase4_scope_audit.json"
    output.write_text(
        json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8", newline="\n"
    )
    print(json.dumps(counts), flush=True)


if __name__ == "__main__":
    main()
