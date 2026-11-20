"""Serial full-pool replay of the twenty frozen Phase 1 member-weeks.

PYTHONPATH=src python -m docs.research.llmopt_phase6.measure
No service, network, tests, or realized scores are used during this run.
"""

import argparse
import hashlib
import json
import socket
import subprocess
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from docs.research.llmopt_phase1 import benchmark
from scripts.measure_window_solver_highs import window_call

from squadopt.optimization.work_budget import WorkBudget, WorkBudgetExhausted, work_budget
from squadopt.planning.expected_window import extend_expected_packages, optimize_expected_window
from squadopt.planning.models import PlanningHorizon
from squadopt.platform.native_windows import execute_native_window

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
METRICS = ("raw_xi_net_points", "expected_lineup_net_points", "selection_utility")
ARMS = (("disabled", False, False), ("packages", True, False), ("opened_gate", True, True))
SOURCES = (
    Path(__file__).relative_to(ROOT),
    *(
        Path("src/squadopt/planning") / name
        for name in ("expected_window.py", "expected_swap.py", "expected_packages.py", "models.py")
    ),
)


def clean(value):
    return json.loads(json.dumps(value, default=lambda item: item.item(), allow_nan=False))


def measure(output, limit=None):
    stamp = {
        **benchmark.provenance(),
        "phase6_source_sha256": {
            path.as_posix(): hashlib.sha256(
                (ROOT / path).read_bytes().replace(b"\r\n", b"\n")
            ).hexdigest()
            for path in SOURCES
        },
        "comparison": "shared_retained_prefix_charged_in_full_per_arm",
        "producer_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
    }
    rows = []
    network_attempts = 0

    def refuse_network(*args, **kwargs):
        nonlocal network_attempts
        network_attempts += 1
        raise RuntimeError("The Phase 6 replay is offline.")

    for frozen, inputs in benchmark.snapshots():
        for entry in sorted(inputs.members):
            if limit is not None and len(rows) >= limit:
                break
            call = window_call(inputs, entry, 3)
            projection = frozen["projection"]
            table = call.horizon.table.loc[
                call.horizon.table.player_id.map(str).isin(projection["appearance_probability"])
            ].copy()
            if not set(call.state.squad_player_ids) <= set(table.player_id):
                raise ValueError("The frozen appearance pool omitted a held player.")
            first_counts = frozen["fixture_counts"][str(inputs.gameweek)]
            for index, player in table.iterrows():
                identity = str(player.player_id)
                count = frozen["fixture_counts"][str(player.gameweek)].get(str(player.team_id), 0)
                divisor = max(1, first_counts.get(str(player.team_id), 0))
                table.at[index, "expected_points"] = (
                    projection["expected_points"][identity] * count / divisor
                )
                table.at[index, "appearance_probability"] = projection["appearance_probability"][
                    identity
                ]
            horizon = PlanningHorizon(table)
            row = {
                "case": f"gw{inputs.gameweek}-{entry}",
                "capture": inputs.capture,
                "pool_size": len(table) // 3,
                "forecast_fingerprint": projection["fingerprint"],
                "configured_deterministic_units": call.settings.solver_deterministic_time_limit,
                "wall_safety_seconds": call.settings.solver_time_limit_seconds,
                "arms": {},
            }
            retained_plan = None
            prefix_measure = None
            prefix_allocation = None
            for name, packages, gate in ARMS:
                experiment = None
                allocation = (
                    WorkBudget(122) if prefix_allocation is None else replace(prefix_allocation)
                )
                policy = replace(
                    call.policy,
                    allow_two_free_transfers=True,
                    transfer_packages=packages,
                    package_gate=gate,
                )

                def run(
                    horizon=horizon,
                    call=call,
                    policy=policy,
                    name=name,
                    retained_plan=retained_plan,
                    prefix_measure=prefix_measure,
                ):
                    nonlocal experiment
                    if name == "disabled":
                        plan = optimize_expected_window(horizon, call.state, call.settings, policy)
                    else:
                        plan = extend_expected_packages(
                            horizon,
                            call.state,
                            call.settings,
                            policy,
                            retained_plan,
                            elapsed_seconds=prefix_measure["seconds"],
                        )
                    experiment = plan.diagnostics.get("transfer_packages_v1")
                    return plan

                def save_prefix(horizon=horizon, call=call, policy=policy):
                    nonlocal retained_plan
                    retained_plan = optimize_expected_window(
                        horizon, call.state, call.settings, policy
                    )
                    return retained_plan

                def bounded_native(model, seconds, allocation=allocation):
                    # Same non-refundable reservation and CP fallback as the worker.
                    try:
                        allocation.reserve_native(seconds)
                    except WorkBudgetExhausted as error:
                        raise RuntimeError(str(error)) from error
                    return execute_native_window(model, seconds)

                if name != "disabled" and retained_plan is None:
                    measured = {**prefix_measure}
                    checks = measured["accounting_failures"]
                else:
                    with (
                        patch.object(socket.socket, "connect", refuse_network),
                        patch.object(socket.socket, "connect_ex", refuse_network),
                        benchmark.accounting_checks() as checks,
                        work_budget(allocation),
                        patch.object(benchmark, "execute_native_window", bounded_native),
                    ):
                        measured = benchmark.timed(
                            save_prefix if name == "disabled" else run,
                            capture_expected_failure=True,
                        )
                    if name != "disabled":
                        combined_calls = prefix_measure["calls"] + measured["calls"]
                        measured = {
                            **measured,
                            **benchmark.call_counts(combined_calls),
                            "calls": combined_calls,
                            "seconds": prefix_measure["seconds"] + measured["seconds"],
                        }
                measured["accounting_failures"] = checks.copy()
                if name == "disabled":
                    prefix_measure = measured
                    prefix_allocation = replace(allocation)
                row["arms"][name] = clean(
                    {
                        **benchmark.compact_plan(measured),
                        "seconds": measured["seconds"],
                        "experiment": experiment,
                        "admitted_work_limit": allocation.limit,
                        "cp_work_charged": allocation.cp_used,
                        "native_work_reserved": allocation.native_reserved,
                        "admitted_work_remaining": allocation.remaining,
                        "actual_cp_work": sum(
                            c.get("deterministic_units", 0) for c in measured["calls"]
                        ),
                        "calls": measured["calls"],
                    }
                )
                baseline = row["arms"]["disabled"]
                current = row["arms"][name]
                current["gain_points"] = {
                    key: None
                    if baseline[key] is None or current[key] is None
                    else current[key] - baseline[key]
                    for key in METRICS
                }
                print(
                    f"{row['case']} {name} {current['solver_status']} {current['gain_points']}",
                    flush=True,
                )
            rows.append(row)
            benchmark.write(
                output,
                clean(
                    {
                        "provenance": stamp,
                        "network_attempts": network_attempts,
                        "rows": rows,
                        "complete": len(rows) == 20,
                    }
                ),
            )
    return rows


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output", type=Path, default=ROOT / "artifacts/llmopt_phase6/results.json"
    )
    parser.add_argument("--limit", type=int)
    arguments = parser.parse_args()
    measure(arguments.output, arguments.limit)
