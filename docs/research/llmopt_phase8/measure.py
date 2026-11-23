"""Sequential cold and warm workload on the twenty frozen members; no external HTTP."""

import argparse
import hashlib
import json
import subprocess
from collections import Counter
from datetime import datetime
from functools import cache as memoized
from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter
from unittest.mock import patch

from docs.research.llmopt_phase1.benchmark import snapshots
from docs.research.llmopt_phase2.frozen_capture import FrozenContexts, FrozenDirectory, make_capture
from docs.research.llmopt_phase2.measure_named_chip import observe_worker
from fastapi.testclient import TestClient

from squadopt.api.app import create_app
from squadopt.application.advice_capabilities import menu_capabilities
from squadopt.platform import advice_worker
from squadopt.platform.advice_job_spec import FileAdviceJobSpecStore
from squadopt.platform.advice_plan_cache import PlanAdviceCache
from squadopt.platform.advice_queue import FileJobQueue, run_advice_worker_once
from squadopt.platform.advice_read import AdviceReadStore, PreferencePlayers
from squadopt.platform.advice_runs import FileRunStore
from squadopt.platform.advice_submit import AdviceSubmitService, FixedWindowRateLimiter
from squadopt.platform.advice_worker import build_advice_compute
from squadopt.platform.backend_runtime import BackendConfig

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
RESEARCH = HERE.parent
OUTPUT = RESEARCH / "llmopt_phase8_load.json"
CHECKPOINT = ROOT / ".codex-tmp/phase8-checkpoint.json"
FLAG = "SQUADOPT_BACKEND_LLMOPT_VNEXT"


def sha(path):
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


@memoized
def publication(commit, name):
    # Phase 1 froze the solver columns only. Read the omitted display and roster
    # fields from the original, content-addressed local publication.
    path = f"web/public/data/leagues/352490/{name}.json"
    return json.loads(subprocess.check_output(["git", "show", f"{commit}:{path}"], cwd=ROOT))[
        "payload"
    ]


def write(path, data, *, compact=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    pending = path.with_suffix(".tmp")
    if compact:
        # One row per capture, window and release arm. Keep the evidence diff readable
        # without storing the indentation of every individual request and solver call.
        header = {key: value for key, value in data.items() if key != "rows"}
        rows = (
            json.dumps(row, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
            for row in data["rows"]
        )
        body = (
            json.dumps(header, indent=2).removesuffix("\n}")
            + ',\n  "rows": [\n'
            + ",\n".join(rows)
            + "\n  ]\n}"
        )
    else:
        body = json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False)
    pending.write_text(body + "\n", encoding="utf-8", newline="\n")
    pending.replace(path)


class ObservedQueue(FileJobQueue):
    """Measure successful publication and claim with one monotonic clock."""

    def __init__(self, path):
        super().__init__(path)
        self.enqueued = {}
        self.claimed = {}

    def submit(self, job):
        super().submit(job)
        self.enqueued[job.job_id] = perf_counter()

    def claim(self, **kwargs):
        job = super().claim(**kwargs)
        if job is not None:
            self.claimed[job.job_id] = perf_counter()
        return job


def complete(queue, cache, compute, runs, stamp, label):
    native_seconds = []
    original_native = advice_worker.execute_native_window

    def timed_native(packet, seconds):
        started = perf_counter()
        try:
            return original_native(packet, seconds)
        finally:
            native_seconds.append(perf_counter() - started)

    with (
        patch.object(advice_worker, "execute_native_window", timed_native),
        observe_worker() as (_, calls),
    ):
        terminal = run_advice_worker_once(
            queue, cache, compute, at_utc=stamp, terminal_at_utc=lambda: stamp
        )
    finished = perf_counter()
    if terminal is None:
        raise ValueError("A submitted job had no worker claim.")
    identifier = terminal.job_id
    ledger = (
        json.loads(runs.path.read_bytes())["jobs"].get(identifier, {}) if runs.path.exists() else {}
    )
    counts = Counter(row["backend"] for row in calls)
    return {
        "job_id": identifier,
        "stage": label,
        "worker_contract": terminal.contract_version,
        "status": terminal.status,
        "error": terminal.error.code if terminal.error else None,
        "queue_seconds": queue.claimed[identifier] - queue.enqueued[identifier],
        "worker_seconds": finished - queue.claimed[identifier],
        "solver_calls": len(calls),
        "cp_sat_calls": counts["cp-sat"],
        "native_calls": counts["highs-native"],
        "native_seconds": sum(native_seconds),
        "cp_seconds": sum(row["seconds"] for row in calls if row["backend"] == "cp-sat"),
        "cp_units": sum(row["deterministic_units"] for row in calls if row["backend"] == "cp-sat"),
        "native_wall_limits_seconds": [
            row["wall_cap_seconds"] for row in calls if row["backend"] == "highs-native"
        ],
        "allocated_units": ledger.get("limit"),
        "work_receipt": ledger.get("receipt"),
    }


def replay(root, frozen, inputs, entry, window, enabled, producer, *, setup_only=False):
    # Only the same three ordinary soft rules are compared between modes. The
    # Phase 1 standalone tight-bank and named-chip stress scenarios are different workloads.
    context, stamp = make_capture(frozen, inputs, entry, "normal", producer)
    contexts = FrozenContexts(context)
    table = inputs.table
    block = inputs.members[entry]
    config = BackendConfig.from_environment(
        {
            **{
                f"SQUADOPT_BACKEND_{key}_ROOT": str(root / key.lower())
                for key in ("STORE", "SITE_DATA", "SNAPSHOT", "HANDOFF")
            },
            FLAG: str(int(enabled)),
        }
    )
    queue = ObservedQueue(root / "queue")
    cache = PlanAdviceCache(root / "answers", llmopt_vnext=config.llmopt_vnext)
    specs = FileAdviceJobSpecStore(root / "specs")

    def capture_for_key(key):
        spec = specs.get(key)
        return spec.context.capture_snapshot_id if spec else None

    runs = FileRunStore(root / "runs", capture_for_key=capture_for_key)
    names = frozenset(context.inputs.players.team_id)
    roster = frozenset(context.inputs.players.player_id)
    reader = AdviceReadStore(
        FrozenDirectory(inputs, entry),
        cache,
        contexts,
        {"saf-puan": False},
        capabilities=menu_capabilities(),
        transfer_packages=config.enabled_packages,
        three_week_paths=config.enabled_three_week_paths,
        preference_bundles=True,
        verified_repairs=config.llmopt_vnext,
        llmopt_vnext=config.llmopt_vnext,
        preference_players=lambda *_: PreferencePlayers(frozenset(block["held"]), roster, names),
        chip_availability=lambda *_: {entry: ()},
    )
    submit = AdviceSubmitService(
        reader,
        queue,
        specs=specs,
        runs=runs,
        rate_limiter=FixedWindowRateLimiter(config.rate_limit, config.rate_window_seconds),
        max_open_jobs_per_client=config.max_open_jobs_per_client,
    )
    app = create_app(
        advice_store=reader,
        advice_submit=submit,
        llmopt_vnext=config.llmopt_vnext,
        utc_now=lambda: datetime.fromisoformat(stamp),
    )
    compute = build_advice_compute(
        contexts, specs, cache=cache, runs=runs, llmopt_vnext=config.llmopt_vnext
    )
    case = f"gw{inputs.gameweek}-{entry}"
    identifier = hashlib.sha256(f"{case}:{window}:{enabled}".encode()).hexdigest()[:32]
    published = publication(frozen["source_commit"], "device-plan")
    squad = publication(frozen["source_commit"], f"entries/{entry}")
    if squad["device_plan"] != block or squad["source_snapshot_id"] != table["source_snapshot_id"]:
        raise ValueError("Published member differs from the frozen capture.")
    if not all(
        all(p.get(key) == value for key, value in frozen_player.items())
        for p, frozen_player in zip(published["players"], table["players"], strict=True)
    ) or any(published[key] != value for key, value in table.items() if key != "players"):
        raise ValueError("Published table differs from the frozen solver inputs.")
    initial = {
        "document": published,
        "squad": squad,
        "block": block,
        "entryId": entry,
        "window": window,
        "enabled": enabled,
        "runId": identifier,
        "setupOnly": setup_only,
    }
    passes = {}
    current = None
    with (
        TestClient(app) as client,
        subprocess.Popen(
            ["node", ".codex-tmp/phase8-workload.mjs"],
            cwd=ROOT,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
            encoding="utf-8",
        ) as process,
    ):
        try:

            def send(data):
                process.stdin.write(json.dumps(data, allow_nan=False) + "\n")
                process.stdin.flush()

            send(initial)
            for line in process.stdout:
                event = json.loads(line)
                if event["op"] == "begin":
                    current = passes[event["cache"]] = {"http": [], "jobs": []}
                    opened_before = set(queue.enqueued)
                    send({})
                elif event["op"] == "http":
                    response = client.request(
                        event["method"],
                        event["path"],
                        content=event.get("body"),
                        headers=event.get("headers"),
                    )
                    result = response.json()
                    current["http"].append(
                        {
                            "method": event["method"],
                            "path": event["path"].partition("?")[0],
                            "status": response.status_code,
                            **({"job_id": result["job_id"]} if "job_id" in result else {}),
                            **({"error": result["error"].get("code")} if "error" in result else {}),
                        }
                    )
                    send({"status": response.status_code, "body": result})
                elif event["op"] == "drain":
                    # A repeated run can point to its earlier terminal failure.
                    # Only new queue publications are charged to this cache pass.
                    queued = set()
                    for identifier in event["jobs"]:
                        job = queue.load(identifier)
                        if job is None:
                            raise ValueError(f"API returned a missing job: {identifier}")
                        if not job.is_terminal:
                            queued.add(identifier)
                    completed = [
                        complete(queue, cache, compute, runs, stamp, event["label"]) for _ in queued
                    ]
                    if {job["job_id"] for job in completed} != queued:
                        raise ValueError("Worker drained a different job than the submitted stage.")
                    current["jobs"].extend(completed)
                    send([j["job_id"] for j in completed])
                elif event["op"] == "done":
                    for measured in event["passes"]:
                        passes[measured["cache"]].update(measured)
                    break
                else:
                    raise ValueError(f"Unknown local workload operation: {event['op']}")
            if process.wait(timeout=30) != 0 or set(passes) != (
                {"cold"} if setup_only else {"cold", "warm"}
            ):
                raise RuntimeError(f"Local workload failed for {case}/{window}/{enabled}.")
        finally:
            if process.poll() is None:
                process.kill()
    if setup_only:
        if not passes["cold"].get("setup") or queue.enqueued:
            raise ValueError("A configuration check must stop before submitting work.")
        return
    if set(queue.enqueued) - opened_before != {j["job_id"] for j in passes["warm"]["jobs"]}:
        raise ValueError("Warm queue publications disagree with the transport.")
    for result in passes.values():
        if "answers" not in result:
            raise RuntimeError(f"Missing pass for {case}/{window}/{enabled}.")
        if any(value["status"] in ("failed", "idle") for value in result["answers"].values()):
            result["incomplete"] = True
        if len(result["jobs"]) != sum(len(s["job_ids"]) for s in result["stages"]):
            raise ValueError("Queue and transport disagree on opened jobs.")
    if set(queue.enqueued) != {
        job["job_id"] for result in passes.values() for job in result["jobs"]
    }:
        raise ValueError("Published queue records disagree with the per-pass job counts.")
    return {
        "case": case,
        "window": window,
        "release": "on" if enabled else "off",
        "run_id": initial["runId"] if enabled else None,
        **passes,
    }


def provenance(*, require_clean=True):
    names = [
        HERE / "measure.py",
        HERE / "report.py",
        *HERE.glob("*.ts"),
        *HERE.glob("*.mjs"),
        RESEARCH / "llmopt_phase1/inputs.json",
        RESEARCH / "llmopt_phase1_baseline.json",
        RESEARCH / "llmopt_phase2/measure_named_chip.py",
        RESEARCH / "llmopt_phase2/frozen_capture.py",
        RESEARCH / "llmopt_phase1/benchmark.py",
        ROOT / "web/package-lock.json",
        ROOT / "web/src/features/league/llmopt/releaseRun.ts",
        ROOT / "web/src/features/league/llmopt/planRun.ts",
        ROOT / "web/src/features/league/llmopt/preferenceExecution.ts",
        ROOT / "web/src/features/league/device/adviceClient.ts",
        ROOT / "web/src/features/league/device/requests.ts",
        ROOT / "src/squadopt/platform/advice_plan_cache.py",
        ROOT / "src/squadopt/platform/advice_read.py",
        ROOT / "src/squadopt/platform/advice_worker.py",
        ROOT / "src/squadopt/platform/backend_runtime.py",
        ROOT / "src/squadopt/platform/advice_submit.py",
        ROOT / "src/squadopt/planning/optimizer.py",
    ]
    if require_clean:
        subprocess.run(
            [
                "git",
                "diff",
                "--quiet",
                "HEAD",
                "--",
                "src",
                "web/src",
                "web/package-lock.json",
                "docs/research/llmopt_phase1",
                "docs/research/llmopt_phase1_baseline.json",
                "docs/research/llmopt_phase2",
                "docs/research/llmopt_phase8",
            ],
            cwd=ROOT,
            check=True,
        )
    return {
        "commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "source_sha256": {p.relative_to(ROOT).as_posix(): sha(p) for p in sorted(names)},
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument(
        "--check-setup",
        action="store_true",
        help="Check all inputs and routes without submitting any work.",
    )
    parser.add_argument("--checkpoint", type=Path, default=CHECKPOINT)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    producer = provenance(require_clean=not args.check_setup)
    rows = []
    if not args.check_setup and args.resume and args.checkpoint.exists():
        prior = json.loads(args.checkpoint.read_bytes())
        if prior["provenance"] != producer:
            raise ValueError("The checkpoint was produced by different code or inputs.")
        rows = prior["rows"]
    done = {(r["case"], r["window"], r["release"]) for r in rows}
    record = {
        "contract_version": "llmopt_phase8_workload_v1",
        "producer_repository_commit": producer["commit"],
        "provenance": producer,
        "rows": rows,
    }
    subprocess.run(["node", str(HERE / "bundle.mjs")], cwd=ROOT, check=True)
    cases = set()
    with TemporaryDirectory(prefix="llmopt-measure-") as tmp:
        for frozen, inputs in snapshots():
            for index, entry in enumerate(sorted(inputs.members)):
                case = f"gw{inputs.gameweek}-{entry}"
                for window in (1, 3):
                    # Alternate first arm by member and capture to distribute setup/order effects.
                    for enabled in (
                        (True, False) if (index + inputs.gameweek) % 2 else (False, True)
                    ):
                        release = "on" if enabled else "off"
                        cases.add((case, window, release))
                        if (case, window, release) in done:
                            continue
                        if not args.check_setup:
                            print(f"Starting {case}/{window}/{release}", flush=True)
                        row = replay(
                            Path(tmp) / f"{case}-{window}-{release}",
                            frozen,
                            inputs,
                            entry,
                            window,
                            enabled,
                            producer["commit"],
                            setup_only=args.check_setup,
                        )
                        if args.check_setup:
                            continue
                        rows.append(row)
                        write(args.checkpoint, record)
                        print(
                            f"Finished {case}/{window}/{release}: "
                            f"{len(row['cold']['jobs'])} cold jobs, "
                            f"{row['cold']['seconds']:.2f} s, {len(row['warm']['jobs'])} warm jobs",
                            flush=True,
                        )
    if len(cases) != 80:
        raise ValueError("The frozen workload must have eighty distinct configurations.")
    if args.check_setup:
        print("Verified 80 configurations on 20 member-weeks. No work submitted.")
        return
    if len(rows) != 80 or {(r["case"], r["window"], r["release"]) for r in rows} != cases:
        raise ValueError("The record must have two arms at two windows on all twenty members.")
    if provenance() != producer:
        raise ValueError("The producer changed during the measurement.")
    write(args.output, record, compact=True)


if __name__ == "__main__":
    main()
