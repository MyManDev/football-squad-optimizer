"""Replay both cold API/worker paths for every frozen Wildcard and Free Hit control."""

import argparse
import hashlib
import json
import subprocess
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import ortools
from docs.research.llmopt_phase1 import benchmark
from docs.research.llmopt_phase2.frozen_capture import (
    FrozenContexts,
    FrozenDirectory,
    make_capture,
)
from docs.research.llmopt_phase2.named_chip_readout import write_readout
from fastapi.testclient import TestClient

from squadopt.api.app import create_app
from squadopt.application.advice_capabilities import menu_capabilities
from squadopt.live import transfers
from squadopt.optimization.work_budget import current_work_budget
from squadopt.platform import advice_worker
from squadopt.platform.advice_cache import FileAdviceCache
from squadopt.platform.advice_job_spec import FileAdviceJobSpecStore
from squadopt.platform.advice_queue import FileJobQueue, run_advice_worker_once
from squadopt.platform.advice_read import AdviceReadStore, PreferencePlayers
from squadopt.platform.advice_runs import FileRunStore
from squadopt.platform.advice_submit import AdviceSubmitService

ROOT = Path(__file__).resolve().parents[3]
RESEARCH = ROOT / "docs/research"
BASELINE = RESEARCH / "llmopt_phase1_baseline.json"
OUTPUT = RESEARCH / "llmopt_phase2_named_chip.json"
SOURCES = (
    Path(__file__),
    Path(__file__).with_name("frozen_capture.py"),
    ROOT / "docs/research/llmopt_phase1/benchmark.py",
    ROOT / "scripts/measure_window_solver_highs.py",
    *(
        ROOT / f"src/squadopt/{name}.py"
        for name in (
            "application/advice_chip_strategy",
            "live/transfers",
            "optimization/cpsat",
            "optimization/work_budget",
            "planning/optimizer",
            "platform/advice_read",
            "platform/advice_submit",
            "platform/advice_worker",
            "platform/advice_runs",
        )
    ),
)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def json_digest(value):
    return digest(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    )


def published_week(week):
    lineup = week["lineup"]
    return dict(
        gameweek=week["gameweek"],
        expected_points=week["expected_points"],
        transfer_hit_points=week["transfer_hit_points"],
        bank_after_tenths=week["bank_after_tenths"],
        free_transfers_after=week["free_transfers_after"],
        starting_xi=sorted(p["player_id"] for p in lineup["starting_xi"]),
        bench=[p["player_id"] for p in lineup["bench"]],
        captain=lineup["captain"]["player_id"],
        vice_captain=lineup["vice_captain"]["player_id"],
    )


@contextmanager
def observe_worker():
    """Delegate each call to its production implementation with arguments untouched."""
    named = []
    plan_named = transfers._plan_named_chip_window
    native = advice_worker.execute_native_window

    def observed_named(*args, **kwargs):
        call = {"run_allocation_active": current_work_budget() is not None}
        named.append(call)
        result = plan_named(*args, **kwargs)
        call.update(
            solver_status=result.solver_status.name,
            objective=result.objective_value,
            seed=result.diagnostics.get("named_chip_seed"),
        )
        return result

    # The real worker installs its own native executor inside the benchmark
    # observer. Watch its underlying child invocation so its reservation still runs.
    with benchmark.capture_solves() as solves:

        def observed_native(packet, seconds):
            call = {"backend": "highs-native", "wall_cap_seconds": seconds}
            solves.append(call)
            try:
                result = native(packet, seconds)
            except (OSError, RuntimeError, ValueError) as error:
                call.update(status="ERROR", error=type(error).__name__)
                raise
            call.update(status=result["status"], objective_raw=result["objective"])
            return result

        with (
            patch.object(transfers, "_plan_named_chip_window", observed_named),
            patch.object(advice_worker, "execute_native_window", observed_native),
        ):
            yield named, solves


def run_arm(root, capture, stamp, inputs, entry, request, *, bound):
    cache = FileAdviceCache(root / "answers")
    queue = FileJobQueue(root / "queue")
    specs = FileAdviceJobSpecStore(root / "specs")
    runs = FileRunStore(root / "runs")
    contexts = FrozenContexts(capture)
    held = frozenset(map(int, inputs.members[entry]["held"]))
    players = capture.inputs.players
    reader = AdviceReadStore(
        FrozenDirectory(inputs, entry),
        cache,
        contexts,
        {"saf-puan": False},
        capabilities=menu_capabilities(),
        preference_players=lambda *_: PreferencePlayers(
            held, frozenset(players.player_id), frozenset(players.team_id)
        ),
        chip_availability=lambda *_: {entry: ("wildcard", "freehit", "3xc", "bboost")},
    )
    service = AdviceSubmitService(reader, queue, specs=specs, runs=runs)
    app = create_app(
        advice_store=reader, advice_submit=service, utc_now=lambda: datetime.fromisoformat(stamp)
    )
    body = dict(request)
    if bound:
        body["run"] = {
            "contract_version": "llmopt_run_v1",
            "run_id": json_digest([inputs.capture, entry, request])[:32],
            "stage": "base",
        }
    league = inputs.table["league_id"]
    route = f"/api/v1/leagues/{league}/entries/{entry}/advice"
    with TestClient(app) as client:
        response = client.post(route, json=body)
    if response.status_code != 202:
        raise ValueError(
            f"Cold submission at {route} returned {response.status_code}: {response.text}"
        )
    job_id = response.json()["job_id"]
    fields = {}
    compute = advice_worker.build_advice_compute(
        contexts, specs, cache=cache, runs=runs, job_log_fields=fields
    )
    with observe_worker() as (named, solves):
        if not run_advice_worker_once(
            queue, cache, compute, at_utc=stamp, terminal_at_utc=lambda: stamp
        ):
            raise ValueError(f"No queued job for {job_id}.")
    job = queue.load(job_id)
    spec = specs.get(job.cache_key)
    if spec is None or len(queue.jobs()) != 1:
        raise ValueError(f"The isolated queue must have one job and one immutable spec: {job_id}.")
    allocation = {}
    if runs.path.exists():
        allocation = json.loads(runs.path.read_bytes())["jobs"].get(job_id, {})
    data = cache.get(job.cache_key)
    payload = None if data is None else json.loads(data)["payload"]
    weeks = [] if payload is None else payload["plan_weeks"]
    log = dict(
        contract_version=job.contract_version,
        api_status=response.status_code,
        job_status=job.status,
        job_error=None if job.error is None else job.error.code,
        cache_key=job.cache_key,
        spec_sha256=json_digest(spec.as_payload()),
        payload_sha256=None if data is None else digest(data),
        solver_status=None if payload is None else payload["solver_status"],
        objective=named[-1].get("objective") if named else None,
        published_net_points=None
        if payload is None
        else sum(week["expected_points"] - week["transfer_hit_points"] for week in weeks),
        published_weeks=[published_week(week) for week in weeks],
        transfers=[
            {
                "gameweek": week["gameweek"],
                "chip": week["chip"],
                "transfers_in": sorted(p["player_id"] for p in week["transfers_in"]),
                "transfers_out": sorted(p["player_id"] for p in week["transfers_out"]),
            }
            for week in weeks
        ],
        allocation=allocation.get("limit"),
        receipt=allocation.get("receipt"),
        named_chip_calls=named,
        solver_calls=[
            {key: value for key, value in call.items() if key != "seconds"} for call in solves
        ],
        native_outcomes=fields.get("window_solvers", []),
    )
    return log, payload


def compare(case, inputs, entry, window, control, arms):
    bound, bound_payload = arms["run_bound"]
    legacy, legacy_payload = arms["legacy"]
    both_completed = all(arm["job_status"] == "completed" for arm in (bound, legacy))
    scored = all(arm["objective"] is not None for arm in (bound, legacy))
    displayed = all(arm["published_net_points"] is not None for arm in (bound, legacy))
    different_fields = sorted(
        key
        for key in set(bound_payload or {}) | set(legacy_payload or {})
        if (bound_payload or {}).get(key) != (legacy_payload or {}).get(key)
        or (key in (bound_payload or {})) != (key in (legacy_payload or {}))
    )
    return dict(
        case=case,
        capture=inputs.capture,
        entry_id=entry,
        scenario=control["scenario"],
        window=window,
        frozen_control={
            key: control["windows"][str(window)]["control"][key]
            for key in ("solver_status", "objective", "decision_sha256")
        },
        run_bound=bound,
        legacy=legacy,
        same_key=bound["cache_key"] == legacy["cache_key"],
        same_spec=bound["spec_sha256"] == legacy["spec_sha256"],
        same_status=both_completed and bound["solver_status"] == legacy["solver_status"],
        same_objective=scored and bound["objective"] == legacy["objective"],
        objective_delta=None if not scored else bound["objective"] - legacy["objective"],
        same_published_net_points=displayed
        and bound["published_net_points"] == legacy["published_net_points"],
        published_net_points_delta=(
            bound["published_net_points"] - legacy["published_net_points"] if displayed else None
        ),
        same_transfers=both_completed and bound["transfers"] == legacy["transfers"],
        same_payload=both_completed and bound["payload_sha256"] == legacy["payload_sha256"],
        differing_payload_fields=different_fields,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    producer = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    controls = {
        row["case"]: row
        for row in json.loads(BASELINE.read_bytes())["rows"]
        if row["scenario"] in ("wildcard", "freehit")
    }
    rows = []
    with TemporaryDirectory(prefix="llmopt-named-chip-") as folder:
        for frozen, inputs in benchmark.snapshots():
            for entry in sorted(inputs.members):
                case = f"gw{inputs.gameweek}-{entry}"
                if case not in controls:
                    continue
                control = controls[case]
                chip = control["scenario"]
                capture, stamp = make_capture(frozen, inputs, entry, chip, producer)
                for window in (1, 3):
                    request = dict(
                        strategy="saf-puan",
                        window=window,
                        chip=chip,
                        preferences=dict(net_points_priority=True, save_chips=False),
                    )
                    arms = {}
                    for mode in ("run_bound", "legacy"):
                        root = Path(folder) / f"{case}-{window}" / mode
                        arms[mode] = run_arm(
                            root, capture, stamp, inputs, entry, request, bound=mode == "run_bound"
                        )
                    row = compare(case, inputs, entry, window, control, arms)
                    row["request"] = request
                    rows.append(row)
                    print(
                        f"{case} {chip} {window}w same payload={row['same_payload']} "
                        f"objective delta={row['objective_delta']}",
                        flush=True,
                    )
    if len(controls) != 8 or len(rows) != 16:
        raise ValueError(
            "The frozen controls must contain eight named-chip member-weeks and sixteen pairs."
        )
    report = dict(
        contract_version="llmopt_phase2_named_chip_parity_v1",
        producer_repository_commit=producer,
        source_sha256={
            p.relative_to(ROOT).as_posix(): digest(p.read_bytes().replace(b"\r\n", b"\n"))
            for p in SOURCES
        },
        frozen_manifest_sha256=digest(
            (RESEARCH / "llmopt_phase1/inputs.json").read_bytes().replace(b"\r\n", b"\n")
        ),
        baseline_record_sha256=digest(BASELINE.read_bytes().replace(b"\r\n", b"\n")),
        solver_version=ortools.__version__,
        rows=rows,
    )
    args.output.write_text(
        json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8", newline="\n"
    )
    write_readout(report, args.output.with_suffix(".md"))


if __name__ == "__main__":
    main()
