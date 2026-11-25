"""Compare seven device-eligible hard-rule families with a cold real server worker.

Build and run only in an isolated local measurement window. --check-inputs performs no solves.
"""

import argparse
import hashlib
import json
import re
import subprocess
from collections import Counter
from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter
from unittest.mock import patch

import ortools
from docs.research.llmopt_phase1.benchmark import snapshots
from docs.research.llmopt_phase2.frozen_capture import make_capture
from docs.research.llmopt_phase2.measure_named_chip import json_digest, run_arm
from docs.research.llmopt_phase3.measure import digest
from docs.research.llmopt_phase4.rule_cases import FAMILIES, check_decision, rule_cases
from docs.research.llmopt_phase4.rule_readout import comparison, write_results

from squadopt.contracts.preferences import DecisionPreferences
from squadopt.live import transfers

ROOT = Path(__file__).resolve().parents[3]
RESEARCH = ROOT / "docs/research"
CHECKPOINT = ROOT / ".codex-tmp/phase4-rule-checkpoint.json"
OUTPUT = RESEARCH / "llmopt_phase4_rule_families.json"
SOURCE_NAMES = (
    "docs/research/llmopt_phase4/rule_measure.py",
    "docs/research/llmopt_phase4/rule_cases.py",
    "docs/research/llmopt_phase4/rule_readout.py",
    "docs/research/llmopt_phase4/rule_probe.ts",
    "docs/research/llmopt_phase4/rule_bundle.mjs",
    "docs/research/llmopt_phase2/measure_named_chip.py",
    "docs/research/llmopt_phase2/frozen_capture.py",
    "docs/research/llmopt_phase3/measure.py",
    "docs/research/llmopt_phase1/benchmark.py",
    "scripts/measure_window_solver_highs.py",
    "src/squadopt/live/transfers.py",
    "src/squadopt/planning/optimizer.py",
    "src/squadopt/application/advice.py",
    "src/squadopt/platform/advice_worker.py",
    "web/src/features/league/device/requests.ts",
    "web/src/features/league/device/selection.ts",
    "web/src/features/league/device/alternatives.ts",
    "web/src/features/league/device/preferences.ts",
    "web/src/features/league/device/lp/memberWeek.ts",
    "web/src/features/league/device/solve/week.ts",
    "web/src/features/league/device/solve/ceiling.ts",
    "web/package-lock.json",
)
INPUT_NAMES = (
    "llmopt_phase1/inputs.json",
    "llmopt_phase1_baseline.json",
    "llmopt_phase4_scope_audit.json",
)


def fixtures():
    baseline = json.loads((RESEARCH / "llmopt_phase1_baseline.json").read_bytes())
    original = {row["case"]: row for row in baseline["rows"]}
    scope = json.loads((RESEARCH / "llmopt_phase4_scope_audit.json").read_bytes())
    controls = {
        row["case"]: row for row in scope["rows"] if row["profile"] == "served_no_added_rule"
    }
    expected = {
        f"gw{inputs.gameweek}-{entry}" for _, inputs in snapshots() for entry in inputs.members
    }
    if len(expected) != 20 or original.keys() != expected or controls.keys() != expected:
        raise ValueError("The three source populations do not cover the same twenty member-weeks.")
    for frozen, inputs in snapshots():
        for entry in sorted(inputs.members):
            case = f"gw{inputs.gameweek}-{entry}"
            scenario = original[case]["scenario"]
            block = dict(inputs.members[entry])
            if scenario == "tight_bank":
                block["bank_tenths"] = 0
            ref = controls[case]
            if ref["capture"] != inputs.capture or ref["bank_tenths"] != block["bank_tenths"]:
                raise ValueError(f"Reference basis mismatch for {case}.")
            week = ref["server"]["weeks"][0]
            cases, expectations = rule_cases(inputs.table, block, week, inputs.gameweek)
            for family in FAMILIES:
                rules = DecisionPreferences.parse(dict(net_points_priority=True, **cases[family]))
                rules.validate_selection("saf-puan", False, None)
                rules.validate_window(1)
                yield (
                    case,
                    family,
                    frozen,
                    inputs,
                    entry,
                    block,
                    scenario,
                    rules.payload(),
                    expectations[family],
                )


def server_probe(root, frozen, inputs, entry, scenario, preferences, revision):
    capture, stamp = make_capture(frozen, inputs, entry, scenario, revision)
    settings = []
    original = transfers.optimize_transfer_plan

    def observe(horizon, state, config, policy, *args, **kwargs):
        # Observe the actual planner selected by transport, without changing its budget or output.
        answer = original(horizon, state, config, policy, *args, **kwargs)
        settings.append(
            dict(
                deterministic_limit=config.solver_deterministic_time_limit,
                wall_seconds=config.solver_time_limit_seconds,
                linearization=kwargs.get("linearization_level"),
                protect_hold=kwargs.get("protect_hold"),
                net_points=kwargs["preferences"].net_points_priority,
                status=answer.solver_status.name,
                model_points=answer.diagnostics.get("scaled_model_objective_value"),
                best_bound=answer.diagnostics.get("best_objective_bound"),
            )
        )
        return answer

    with patch.object(transfers, "optimize_transfer_plan", observe):
        log, _ = run_arm(
            root,
            capture,
            stamp,
            inputs,
            entry,
            dict(strategy="saf-puan", window=1, preferences=preferences),
            bound=True,
        )
    status = log["solver_status"] or log["job_error"] or log["job_status"]
    primary = settings[0] if settings else None
    if status == "PLAN_NOT_FOUND" and primary and primary["status"] == "INFEASIBLE":
        status = "INFEASIBLE"
    decision = None
    if log["published_weeks"]:
        (week,) = log["published_weeks"]
        (moves,) = log["transfers"]
        scale = inputs.table["rules"]["expected_points_scale"]
        decision = {
            "in": moves["transfers_in"],
            "out": moves["transfers_out"],
            "squad": sorted(week["starting_xi"] + week["bench"]),
            "xi": week["starting_xi"],
            "captain": week["captain"],
            "chip": moves["chip"],
            "bank": week["bank_after_tenths"],
            "hit": week["transfer_hit_points"],
            "objective_scaled": primary["model_points"] * scale
            if primary and primary["model_points"] is not None
            else None,
            "published_net_scaled": log["published_net_points"] * scale,
        }
    cp = [c for c in log["solver_calls"] if c["backend"] == "cp-sat"]
    other = [c for c in log["solver_calls"] if c["backend"] != "cp-sat"]
    # The journal adds each binary float in call order. Replay those additions exactly.
    observed = 0.0
    for call in cp:
        observed += call["deterministic_units"]
    return dict(
        status=status,
        decision=decision,
        job_status=log["job_status"],
        error=log["job_error"],
        allocation=log["allocation"],
        settings=primary,
        cp_statuses=[c["status"] for c in cp],
        observed_cp_units=observed,
        other_solver_calls=other,
        cp_used=(log["receipt"] or {}).get("cp_used"),
        native_reserved=(log["receipt"] or {}).get("native_reserved"),
        receipt_calls=(log["receipt"] or {}).get("calls"),
    )


def device_probe(inputs, entry, block, preferences, case, family):
    item = dict(
        document=inputs.table,
        entry=block,
        preferences=preferences,
        request=dict(
            leagueId=inputs.table["league_id"],
            entryId=entry,
            season=inputs.table["season"],
            gameweek=inputs.gameweek,
            window=1,
            strategy="saf-puan",
            run=dict(
                contract_version="llmopt_run_v1",
                run_id=json_digest([case, family])[:32],
                stage="base",
            ),
        ),
    )
    result = subprocess.run(
        ["node", ".codex-tmp/phase4-rule-probe.mjs"],
        cwd=ROOT,
        input=json.dumps(item),
        encoding="utf-8",
        capture_output=True,
        check=True,
    )
    return json.loads(result.stdout)


def run_pair(args, vals):
    case, family, frozen, inputs, entry, block, scenario, preferences, expectation = vals
    start = perf_counter()
    with TemporaryDirectory(dir=args.checkpoint.parent, prefix="rule-worker-") as temp:
        server = server_probe(
            Path(temp), frozen, inputs, entry, scenario, preferences, args.producer
        )
    server_seconds = perf_counter() - start
    start = perf_counter()
    device = device_probe(inputs, entry, block, preferences, case, family)
    device_seconds = perf_counter() - start
    for decision in [server["decision"], device["decision"], *device["alternatives"]]:
        if decision:
            decision["audit"] = check_decision(inputs.table, block, preferences, decision)
    row = dict(
        case=case,
        family=family,
        scenario=scenario,
        bank_tenths=block["bank_tenths"],
        capture=inputs.capture,
        preferences=preferences,
        expectation=expectation,
        server=server,
        device=device,
        seconds=dict(server=round(server_seconds, 3), device=round(device_seconds, 3)),
    )
    row.update(comparison(server, device, expectation["feasible"], fixed_week=family == "frozen"))
    return row


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-inputs", action="store_true")
    parser.add_argument(
        "--producer", help="Full immutable producing commit, required for measurement"
    )
    parser.add_argument("--checkpoint", type=Path, default=CHECKPOINT)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    cases = list(fixtures())
    coverage = Counter(x[1] for x in cases)
    if len(cases) != 140 or coverage != {family: 20 for family in FAMILIES}:
        raise ValueError("Incomplete seven-family population.")
    if args.check_inputs:
        print(f"{dict(coverage)}; validated inputs only, zero solves.")
        return
    if not args.producer or not re.fullmatch("[0-9a-f]{40}", args.producer):
        parser.error("--producer requires a full commit ID")
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    if head != args.producer:
        raise ValueError("The requested immutable producer is not the checked-out revision.")
    subprocess.run(
        [
            "git",
            "diff",
            "--quiet",
            "HEAD",
            "--",
            "src",
            "web/src",
            "scripts",
            "docs/research/llmopt_phase1",
            *SOURCE_NAMES,
            *[str((RESEARCH / n).relative_to(ROOT)) for n in INPUT_NAMES],
        ],
        cwd=ROOT,
        check=True,
    )
    sources = {n: digest(ROOT / n) for n in SOURCE_NAMES}
    wasm = ROOT / "web/node_modules/highs/build/highs.wasm"
    provenance = dict(
        producer_repository_commit=head,
        source_sha256=sources,
        input_sha256={n: digest(RESEARCH / n) for n in INPUT_NAMES},
        ortools_version=ortools.__version__,
        highs_wasm_sha256=hashlib.sha256(wasm.read_bytes()).hexdigest(),
        fixture_set_sha256=json_digest([[c[0], c[1], c[7], c[8]] for c in cases]),
        node_version=subprocess.check_output(["node", "--version"], text=True).strip(),
    )
    args.checkpoint.parent.mkdir(parents=True, exist_ok=True)
    state = dict(provenance=provenance, rows=[])
    if args.checkpoint.exists():
        if not args.resume:
            raise ValueError("Checkpoint exists; explicitly resume or choose a fresh location.")
        state = json.loads(args.checkpoint.read_bytes())
        if state["provenance"] != provenance:
            raise ValueError("Run inputs, dependencies or producer differ from checkpoint.")
    prefix = [(r["case"], r["family"], r["preferences"], r["expectation"]) for r in state["rows"]]
    if prefix != [(c[0], c[1], c[7], c[8]) for c in cases[: len(prefix)]]:
        raise ValueError("Incomplete, duplicated or reordered checkpoint prefix.")
    subprocess.run(["node", "docs/research/llmopt_phase4/rule_bundle.mjs"], cwd=ROOT, check=True)
    for vals in cases[len(prefix) :]:
        row = run_pair(args, vals)
        state["rows"].append(row)
        partial = args.checkpoint.with_suffix(".tmp")
        partial.write_text(json.dumps(state, allow_nan=False), encoding="utf-8")
        partial.replace(args.checkpoint)
        print(
            f"{len(state['rows'])}/140 {row['case']} {row['family']} "
            f"{row['server']['status']}/{row['device']['status']}: {row['outcome']}",
            flush=True,
        )
    write_results(provenance, state["rows"], args.output)
    if any(row["outcome"] == "mismatch" for row in state["rows"]):
        raise SystemExit("The record includes mismatches; see the family report.")


if __name__ == "__main__":
    main()
