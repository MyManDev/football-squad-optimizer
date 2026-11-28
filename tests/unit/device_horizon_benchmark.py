"""Opt-in local measurement controller; never writes a capture or published table.

The temporary anonymous Windows CPU job contains only this controller's freshly
spawned Node launcher and inherited Chromium children. No global CPU/service/browser
setting changes. A rate is selected by data-free calibration before any solve.
"""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
import statistics
import struct
import subprocess
from ctypes import wintypes
from pathlib import Path
from typing import Any

import psutil  # type: ignore[import-untyped]
from tests.unit.device_horizon_replay import benchmark_problem

from squadopt.data.snapshots import CapturedSnapshot, SnapshotMetadata
from squadopt.live.rules import read_season_rules

ROOT = Path(__file__).resolve().parents[2]
CONTROLLER = ROOT / "web/src/features/league/device/benchmark/controller.mjs"
TABLE = ROOT / "web/public/data/device/fpl-live-20261127T103417Z-2907c387f11f/device-plan.json"
CALENDAR = ROOT / "web/public/data/fixtures.json"


def normalized_mask(value: int | list[int] | None) -> list[int] | None:
    return [value] if isinstance(value, int) else sorted(value) if value is not None else None


def cpu_topology() -> list[dict[str, int]]:
    """Read the official variable-sized CPU-set records without changing CPU settings."""
    api = ctypes.WinDLL("kernel32", use_last_error=True).GetSystemCpuSetInformation
    api.argtypes = [
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
        wintypes.HANDLE,
        wintypes.DWORD,
    ]
    api.restype = wintypes.BOOL
    needed = wintypes.DWORD()
    api(None, 0, ctypes.byref(needed), None, 0)
    if needed.value == 0:
        raise ctypes.WinError(ctypes.get_last_error())
    buffer = ctypes.create_string_buffer(needed.value)
    if not api(buffer, needed, ctypes.byref(needed), None, 0):
        raise ctypes.WinError(ctypes.get_last_error())
    offset = 0
    rows = []
    while offset < needed.value:
        size, kind = struct.unpack_from("<II", buffer.raw, offset)
        if size < 32:
            raise ValueError("Unknown CPU-set topology record")
        if kind == 0:
            group = struct.unpack_from("<H", buffer.raw, offset + 12)[0]
            logical, core, _, _, efficiency, _ = struct.unpack_from("<6B", buffer.raw, offset + 14)
            rows.append(
                {"group": group, "logical": logical, "core": core, "efficiency_class": efficiency}
            )
        offset += size
    return rows


def wasm_contract() -> dict[str, Any]:
    """Inspect the loaded package's actual compiled memory declaration, not a CDP label."""
    package = ROOT / "web/node_modules/highs"
    raw = (package / "build/highs.wasm").read_bytes()
    if raw[:8] != b"\0asm\x01\0\0\0":
        raise ValueError("Unknown solver binary")

    def integer(offset: int) -> tuple[int, int]:
        value = shift = 0
        while True:
            byte = raw[offset]
            offset += 1
            value |= (byte & 127) << shift
            if byte < 128:
                return value, offset
            shift += 7

    offset = 8
    memories = []
    while offset < len(raw):
        section = raw[offset]
        size, start = integer(offset + 1)
        if section == 5:
            count, cursor = integer(start)
            for _ in range(count):
                flags, cursor = integer(cursor)
                minimum, cursor = integer(cursor)
                maximum = None
                if flags & 1:
                    maximum, cursor = integer(cursor)
                memories.append(
                    {"shared": bool(flags & 2), "minimum_pages": minimum, "maximum_pages": maximum}
                )
        offset = start + size
    if len(memories) != 1 or memories[0]["shared"]:
        raise ValueError("The solver memory is not the verified single-threaded build")
    readme = (package / "README.md").read_text(encoding="utf-8")
    glue = (package / "build/highs.mjs").read_text(encoding="utf-8")
    if "This WebAssembly build is single-threaded." not in readme or any(
        marker in glue for marker in ("SharedArrayBuffer", "PThread", "pthread_create")
    ):
        raise ValueError("Solver threading source contract changed")
    return {
        "package_version": json.loads((package / "package.json").read_bytes())["version"],
        "wasm_sha256": hashlib.sha256(raw).hexdigest(),
        "memories": memories,
        "native_worker_threads": False,
        "thread_option_override": None,
        "exact_options_source_sha256": hashlib.sha256(
            (ROOT / "web/src/features/league/device/lp/problem.ts").read_bytes()
        ).hexdigest(),
    }


def live_problem(bootstrap_path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    """Use an explicitly named live bootstrap only for verified rule metadata."""
    raw = bootstrap_path.read_bytes()
    meta = json.loads((bootstrap_path.parent.parent / "metadata.json").read_bytes())
    checksum = hashlib.sha256(raw).hexdigest()
    if meta["checksums"]["bootstrap-static.json"] != checksum:
        raise ValueError("Rule bootstrap does not match its recorded checksum")
    bootstrap = json.loads(raw)
    if not bootstrap["events"][0]["deadline_time"].startswith("2026-"):
        raise ValueError("Only explicitly named 2026-27 live rule metadata is allowed")
    metadata = SnapshotMetadata(**meta)
    snapshot = CapturedSnapshot(metadata, {"bootstrap-static.json": raw})
    rules = read_season_rules(snapshot, season="2026-27")
    table, calendar = json.loads(TABLE.read_bytes()), json.loads(CALENDAR.read_bytes())
    problem = benchmark_problem(table, calendar, rules)
    document = problem["document"]
    provenance = {
        "season": "2026-27",
        "source_snapshot_id": document["source_snapshot_id"],
        "source_table_sha256": hashlib.sha256(TABLE.read_bytes()).hexdigest(),
        "source_calendar_sha256": hashlib.sha256(CALENDAR.read_bytes()).hexdigest(),
        "numeric_rule": "first_week_control_relative_fixture_scaling_v3",
        "original_projection_handoff_available": False,
        "original_projection_horizon_fingerprint": None,
        "original_rules_fingerprint": None,
        "rule_metadata_source_snapshot_id": metadata.snapshot_id,
        "rule_bootstrap_sha256": checksum,
        "rule_metadata_is_original_capture": metadata.snapshot_id == document["source_snapshot_id"],
        "in_memory_problem_sha256": hashlib.sha256(
            json.dumps(problem, sort_keys=True).encode()
        ).hexdigest(),
        "players": len(document["players"]),
        "clubs": len({p["team"] for p in document["players"]}),
        "members": [
            {
                "member": m["member"],
                "free_transfers": m["entry"]["free_transfers"],
                "bank_tenths": m["entry"]["bank_tenths"],
                "held_count": len(m["entry"]["held"]),
                "roster_sha256": hashlib.sha256(
                    json.dumps(m["entry"], sort_keys=True).encode()
                ).hexdigest(),
            }
            for m in problem["members"]
        ],
    }
    return problem, provenance


class CpuRate(ctypes.Structure):
    _fields_ = [("ControlFlags", wintypes.DWORD), ("CpuRate", wintypes.DWORD)]


class OwnedCpuJob:
    """Only receives a process created by this Python parent before Chrome is spawned."""

    def __init__(self, proc: subprocess.Popen[str]) -> None:
        self.node = psutil.Process(proc.pid)
        if self.node.ppid() != os.getpid():
            raise RuntimeError("Refusing a launcher outside this controller")
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        signatures = {
            "CreateJobObjectW": ([ctypes.c_void_p, wintypes.LPCWSTR], wintypes.HANDLE),
            "OpenProcess": ([wintypes.DWORD, wintypes.BOOL, wintypes.DWORD], wintypes.HANDLE),
            "AssignProcessToJobObject": ([wintypes.HANDLE, wintypes.HANDLE], wintypes.BOOL),
            "SetInformationJobObject": (
                [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD],
                wintypes.BOOL,
            ),
            "QueryInformationJobObject": (
                [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p],
                wintypes.BOOL,
            ),
            "IsProcessInJob": (
                [wintypes.HANDLE, wintypes.HANDLE, ctypes.POINTER(wintypes.BOOL)],
                wintypes.BOOL,
            ),
            "CloseHandle": ([wintypes.HANDLE], wintypes.BOOL),
        }
        for name, (arguments, result) in signatures.items():
            getattr(self.kernel, name).argtypes = arguments
            getattr(self.kernel, name).restype = result
        self.handle = self.kernel.CreateJobObjectW(None, None)
        self.checked(self.handle)
        process = self.kernel.OpenProcess(0x0101, False, proc.pid)
        self.checked(process)
        try:
            self.checked(self.kernel.AssignProcessToJobObject(self.handle, process))
        finally:
            self.kernel.CloseHandle(process)

    @staticmethod
    def checked(ok: Any) -> None:
        if not ok:
            raise ctypes.WinError(ctypes.get_last_error())

    def configure(self, rate: int) -> dict[str, int]:
        value = CpuRate(5, rate)  # ENABLE | HARD_CAP, system-wide CPU share in 1/100 percent.
        self.checked(
            self.kernel.SetInformationJobObject(
                self.handle, 15, ctypes.byref(value), ctypes.sizeof(value)
            )
        )
        result = CpuRate()
        self.checked(
            self.kernel.QueryInformationJobObject(
                self.handle, 15, ctypes.byref(result), ctypes.sizeof(result), None
            )
        )
        if result.ControlFlags != 5 or result.CpuRate != rate:
            raise RuntimeError("CPU rate readback differs from the requested own-job limit")
        return {"flags": result.ControlFlags, "rate": result.CpuRate}

    def verify(self, cpu: list[int] | None = None) -> dict[str, Any]:
        count = 0
        console_hosts = []
        compute_affinity = []
        for child in [self.node, *self.node.children(recursive=True)]:
            process = self.kernel.OpenProcess(0x1000, False, child.pid)
            self.checked(process)
            try:
                member = wintypes.BOOL()
                self.checked(self.kernel.IsProcessInJob(process, self.handle, ctypes.byref(member)))
                if not member.value:
                    # Windows creates a console host outside the inherited CPU job.
                    # It never runs JS/WASM. Do not assign or limit that OS host.
                    executable = Path(child.exe()).resolve()
                    system_root = Path(os.environ["SYSTEMROOT"])
                    expected_hosts = {
                        str(system_root / directory / "conhost.exe").casefold()
                        for directory in ("System32", "SysWOW64")
                    }
                    if (
                        child.name() == "conhost.exe"
                        and str(executable).casefold() in expected_hosts
                        and child.ppid() == self.node.pid
                        and child.create_time() >= self.node.create_time()
                    ):
                        console_hosts.append(
                            {
                                "pid": child.pid,
                                "executable": str(executable),
                                "parent_pid": child.ppid(),
                                "created": child.create_time(),
                            }
                        )
                        continue
                    raise RuntimeError(
                        f"Own child escaped the quota job: {child.pid} {child.name()}"
                    )
                count += 1
                affinity = child.cpu_affinity()
                if cpu is not None and affinity != cpu:
                    raise RuntimeError("Own compute process changed the frozen CPU affinity")
                compute_affinity.append({"pid": child.pid, "affinity": affinity})
            finally:
                self.kernel.CloseHandle(process)
        return {
            "compute_processes_verified": count,
            "compute_affinity": compute_affinity,
            "unthrottled_console_hosts": console_hosts,
        }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--runtime", choices=["calibration", "node", "desktop", "throttled"], required=True
    )
    parser.add_argument("--rule-bootstrap", type=Path)
    parser.add_argument("--rate", type=int)
    parser.add_argument("--initial-rate", type=int)
    parser.add_argument("--calibration-log", type=Path)
    parser.add_argument("--prior-calibration-log", type=Path)
    parser.add_argument("--cpu", type=int)
    parser.add_argument(
        "--cpus", help="Comma-separated logical CPUs from four homogeneous physical cores"
    )
    parser.add_argument("--nominal-cdp", action="store_true")
    parser.add_argument("--execution-context", choices=["worker", "main"], default="worker")
    parser.add_argument("--cpu-throttling", choices=["job", "cdp"], default="job")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--audit-only", action="store_true")
    parser.add_argument("--watchdog-smoke", action="store_true")
    parser.add_argument("--references", type=Path, help="Numeric server reference JSONL to compare")
    args = parser.parse_args()
    if args.cpu is not None and args.cpus is not None:
        raise ValueError("Choose either a single CPU or a homogeneous CPU mask")
    cpu_mask = (
        sorted({int(value) for value in args.cpus.split(",")})
        if args.cpus
        else normalized_mask(args.cpu)
    )
    selected_topology = []
    if args.cpus:
        assert cpu_mask is not None
        topology = cpu_topology()
        selected_topology = [
            row for row in topology if row["group"] == 0 and row["logical"] in cpu_mask
        ]
        if (
            len(cpu_mask) != 4
            or len({row["core"] for row in selected_topology}) != 4
            or {row["efficiency_class"] for row in selected_topology}
            != {max(row["efficiency_class"] for row in topology)}
        ):
            raise ValueError("The mask must cover four distinct highest-efficiency-class cores")
    if args.nominal_cdp and (args.cpu_throttling != "cdp" or args.execution_context != "main"):
        raise ValueError("Nominal CDP measurements require the explicit main-thread context")
    if args.audit_only and (args.runtime != "desktop" or args.execution_context != "worker"):
        raise ValueError("The compatibility audit uses only the unthrottled Dedicated Worker")
    prior_count = 0
    prior_manifest = None
    if args.prior_calibration_log:
        prior_bytes = args.prior_calibration_log.read_bytes()
        prior_rows = [json.loads(line) for line in prior_bytes.splitlines()]
        prior_protocol = next(row for row in prior_rows if row["event"] == "protocol")
        if (
            normalized_mask(prior_protocol["logical_cpu_affinity"]) != cpu_mask
            or prior_protocol["calibration_iterations"] != 1_200_000_000
            or prior_protocol["calibration_repeats"] != 5
        ):
            raise ValueError("The prior calibration used another pinned protocol")
        prior_count = prior_protocol.get("prior_candidate_count", 0) + sum(
            row["event"] == "cpu_rate" for row in prior_rows
        )
        prior_manifest = {
            "sha256": hashlib.sha256(prior_bytes).hexdigest(),
            "source_head": prior_protocol["head"],
            "earlier_manifest": prior_protocol.get("prior_calibration"),
            "candidates": [
                row
                for row in prior_rows
                if row["event"] in ("calibration_result", "calibration_confirmation")
            ],
            "candidate_count": prior_count,
        }
    problem, provenance = (
        ({}, {})
        if args.runtime == "calibration" or args.smoke
        else live_problem(args.rule_bootstrap)
    )
    if args.smoke:
        problem = json.loads((ROOT / "web/src/fixtures/device-plan/horizons.json").read_bytes())
        problem["members"] = [
            {**member, "member": f"synthetic-ft{member['entry']['free_transfers']}"}
            for member in problem["members"]
        ]
        provenance = {"pool": "parity-24", "diagnostic_smoke_only": True}
    references = {}
    reference_manifest = None
    if args.references:
        from tests.unit.device_horizon_reference import compare_reference

        raw_references = args.references.read_bytes()
        reference_rows = [json.loads(line) for line in raw_references.splitlines()]
        reference_provenance = next(row for row in reference_rows if row["event"] == "metadata")
        if reference_provenance["provenance"]["in_memory_problem_sha256"] != provenance.get(
            "in_memory_problem_sha256"
        ):
            raise ValueError("The numeric reference belongs to a different problem")
        references = {
            (row["member"], row["window"]): row
            for row in reference_rows
            if row["event"] == "reference"
        }
        if len(references) != 6 or any(
            row["status"] != "OPTIMAL" or row["diagnostics"]["relative_optimality_gap"] != 0
            for row in references.values()
        ):
            raise ValueError("Six proved primary references with zero gap are required")
        reference_manifest = {"sha256": hashlib.sha256(raw_references).hexdigest()}
    if args.calibration_log:
        raw_calibration = args.calibration_log.read_bytes()
        records = [json.loads(line) for line in raw_calibration.splitlines()]
        protocol = next(row for row in records if row["event"] == "protocol")
        confirmation = next(row for row in records if row["event"] == "calibration_confirmation")
        cleanup = records[-1]
        if (
            any(row["event"] == "run_failed" for row in records)
            or (
                not args.nominal_cdp
                and not 3.90
                <= confirmation["main_ratio" if args.cpu_throttling == "cdp" else "worker_ratio"]
                <= 4.10
            )
            or cleanup
            != {"event": "cleanup", "owned_processes_remaining": 0, "node_exit": 0, "errors": []}
            or normalized_mask(protocol["logical_cpu_affinity"]) != cpu_mask
            or protocol.get("cpu_throttling", "job") != args.cpu_throttling
            or protocol.get("execution_context", "worker") != args.execution_context
            or (args.runtime == "throttled" and args.rate != confirmation["rate"])
        ):
            raise ValueError("The fixed rate/affinity has no successful 4x calibration evidence")
        provenance["calibration_evidence"] = {
            "sha256": hashlib.sha256(raw_calibration).hexdigest(),
            "source_head": protocol["head"],
            "rate": confirmation["rate"],
            "worker_confirmation_ratio": confirmation["worker_ratio"],
            "main_confirmation_ratio": confirmation.get("main_ratio"),
            "calibrated_context": protocol.get("execution_context", "worker"),
        }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as log:

        def emit(value: Any) -> None:
            row = json.dumps(value, allow_nan=False)
            log.write(row + "\n")
            log.flush()
            print(row, flush=True)

        emit(
            {
                "event": "protocol",
                "runtime": args.runtime,
                "head": subprocess.check_output(
                    ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
                ).strip(),
                "diagnostic_seconds": 300,
                "production_ceiling_seconds": 60,
                "repeats": 1 if args.smoke or args.audit_only else 3,
                "purpose": "parity-smoke"
                if args.smoke
                else "execution-context-audit"
                if args.audit_only
                else "timing",
                "numeric_server_references": reference_manifest,
                "calibration_iterations": 1_200_000_000,
                "calibration_repeats": 5,
                "calibration_target_ratio": [3.90, 4.10],
                "selected_rate": args.rate,
                "initial_calibration_rate": args.initial_rate,
                "calibration_candidate_limit": 1 if args.cpu_throttling == "cdp" else 6,
                "fixed_cdp_candidate_count": 1 if args.cpu_throttling == "cdp" else 0,
                "prior_candidate_count": prior_count,
                "prior_calibration": prior_manifest,
                "logical_cpu_affinity": cpu_mask,
                "selected_cpu_topology": selected_topology,
                "nominal_cdp_protocol": args.nominal_cdp,
                "execution_context": "node" if args.runtime == "node" else args.execution_context,
                "cpu_throttling": args.cpu_throttling,
                "logical_cpus": psutil.cpu_count(),
                "physical_cpus": psutil.cpu_count(logical=False),
                "solver_threading": wasm_contract(),
                **provenance,
            }
        )
        if args.prepare_only:
            return
        if args.runtime == "throttled" and (args.rate is None or not 1 <= args.rate <= 10000):
            raise ValueError("A frozen calibrated CPU rate is required before solving")
        if args.cpu_throttling == "cdp" and args.execution_context != "main":
            raise ValueError("CDP CPU throttling is supported only in the explicit main context")
        runtime = (
            "node"
            if args.runtime == "node"
            else "main"
            if args.execution_context == "main"
            else "browser"
        )
        proc = subprocess.Popen(
            ["node", str(CONTROLLER), runtime],
            cwd=ROOT / "web",
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        job = None
        owned: list[psutil.Process] = []
        original_affinity = []
        errors = []

        def send(value: Any) -> None:
            assert proc.stdin is not None
            proc.stdin.write(json.dumps(value) + "\n")
            proc.stdin.flush()

        def receive() -> dict[str, Any]:
            assert proc.stdout is not None
            line = proc.stdout.readline()
            if not line:
                assert proc.stderr is not None
                raise RuntimeError("Own launcher exited: " + proc.stderr.read()[-3000:])
            result: dict[str, Any] = json.loads(line)
            return result

        def probe() -> dict[str, Any]:
            assert job is not None
            membership_before = job.verify(cpu_mask)
            send({"command": "probe", "count": 1_200_000_000, "repeats": 5})
            result = receive()
            if result["event"] != "probe":
                raise RuntimeError("Wrong calibration response")
            emit(
                {
                    **result,
                    "membership_before": membership_before,
                    "membership_after": job.verify(cpu_mask),
                }
            )
            return result

        def cdp_rate(rate: int) -> None:
            send({"command": "cdp-rate", "rate": rate})
            result = receive()
            if result != {"event": "cdp_rate", "rate": rate, "execution_context": "chromium-main"}:
                raise RuntimeError("Wrong main-thread CDP rate response")
            emit(result)

        def adopt_children() -> None:
            nonlocal owned
            assert job is not None
            identities = {(child.pid, child.create_time()): child for child in owned}
            for child in [job.node, *job.node.children(recursive=True)]:
                identities.setdefault((child.pid, child.create_time()), child)
            owned = list(identities.values())

        def accept_restart(result: dict[str, Any]) -> bool:
            if result["event"] != "runtime_restarted":
                return False
            assert job is not None
            adopt_children()
            job.verify()
            if cpu_mask is not None:
                for child in job.node.children(recursive=True):
                    if child.name() != "conhost.exe":
                        child.cpu_affinity(cpu_mask)
            emit({**result, "owned_membership": job.verify(cpu_mask)})
            send({"command": "resume"})
            return True

        try:
            boot = receive()
            if boot != {"event": "boot", "pid": proc.pid}:
                raise RuntimeError("Wrong own launcher PID")
            job = OwnedCpuJob(proc)
            emit({"event": "cpu_full_rate", **job.configure(10000)})
            owned = [job.node]
            original_affinity = job.node.cpu_affinity()
            if cpu_mask is not None:
                if not set(cpu_mask).issubset(original_affinity):
                    raise ValueError("Requested CPU is outside this own process's allowed affinity")
                job.node.cpu_affinity(cpu_mask)
            send({"command": "go"})
            ready = receive()
            if ready.get("event") != "ready":
                raise RuntimeError("Own runtime did not load")
            owned += job.node.children(recursive=True)
            emit({**ready, "owned_processes_verified": job.verify()})
            compute = [child for child in owned if child.name() != "conhost.exe"]
            if cpu_mask is not None:
                # Chromium's GPU child can restore a wide mask at startup. All these
                # identities are already verified descendants in this own CPU job.
                for child in compute:
                    child.cpu_affinity(cpu_mask)
            emit(
                {
                    "event": "owned_identities",
                    "processes": [
                        {
                            "pid": child.pid,
                            "parent_pid": child.ppid(),
                            "created": child.create_time(),
                            "executable": child.exe(),
                            "affinity": child.cpu_affinity(),
                        }
                        for child in owned
                    ],
                }
            )
            if cpu_mask is not None and any(child.cpu_affinity() != cpu_mask for child in compute):
                raise RuntimeError("Own compute child did not inherit the frozen CPU affinity")
            if args.watchdog_smoke:
                send({"command": "watchdog-smoke"})
                result = receive()
                while accept_restart(result):
                    result = receive()
                emit(result)
                if result["event"] != "watchdog_smoke" or result["reply"]["kind"] != "timeout":
                    raise RuntimeError(
                        "The external watchdog did not close its blocked own context"
                    )
            elif args.runtime == "calibration" and args.cpu_throttling == "cdp":
                baseline = probe()
                cdp_rate(4)
                limited = probe()
                confirmation = probe()
                ratios = {
                    kind: statistics.median(r["milliseconds"] for r in limited[kind])
                    / statistics.median(r["milliseconds"] for r in baseline[kind])
                    for kind in ("main", "dedicatedWorker")
                }
                confirmed = {
                    kind: statistics.median(r["milliseconds"] for r in confirmation[kind])
                    / statistics.median(r["milliseconds"] for r in baseline[kind])
                    for kind in ("main", "dedicatedWorker")
                }
                checksums = {
                    r["checksum"]
                    for rows in (baseline, limited, confirmation)
                    for kind in ratios
                    for r in rows[kind]
                }
                accepted = len(checksums) == 1 and all(
                    3.90 <= values["main"] <= 4.10 for values in (ratios, confirmed)
                )
                emit(
                    {
                        "event": "calibration_result",
                        "rate": 4,
                        "mechanism": "cdp-main",
                        "ratios": ratios,
                        "checksum_stable": len(checksums) == 1,
                        "accepted": accepted,
                        "nominal_protocol_accepted": args.nominal_cdp or accepted,
                    }
                )
                emit(
                    {
                        "event": "calibration_confirmation",
                        "rate": 4,
                        "main_ratio": confirmed["main"],
                        "worker_ratio": confirmed["dedicatedWorker"],
                        "owned_membership": job.verify(cpu_mask),
                    }
                )
                cdp_rate(1)
                if len(checksums) != 1 or (not accepted and not args.nominal_cdp):
                    raise RuntimeError("The fixed CDP4 main-thread protocol failed calibration")
            elif args.runtime == "calibration":
                baseline = probe()
                rate = args.initial_rate or round(10000 / (4 * psutil.cpu_count()) * 1.2)
                if not 1 <= rate <= 10000:
                    raise ValueError("Initial own-job calibration CPU rate is invalid")
                for attempt in range(prior_count, 6):
                    emit({"event": "cpu_rate", "attempt": attempt, **job.configure(rate)})
                    limited = probe()
                    ratios = {
                        kind: statistics.median(r["milliseconds"] for r in limited[kind])
                        / statistics.median(r["milliseconds"] for r in baseline[kind])
                        for kind in ("main", "dedicatedWorker")
                    }
                    stable = (
                        len(
                            {
                                r["checksum"]
                                for rows in (baseline, limited)
                                for kind in ratios
                                for r in rows[kind]
                            }
                        )
                        == 1
                    )
                    accepted = stable and 3.90 <= ratios["dedicatedWorker"] <= 4.10
                    emit(
                        {
                            "event": "calibration_result",
                            "attempt": attempt,
                            "rate": rate,
                            "ratios": ratios,
                            "checksum_stable": stable,
                            "accepted": accepted,
                        }
                    )
                    if accepted:
                        confirmation = probe()
                        confirmed = statistics.median(
                            r["milliseconds"] for r in confirmation["dedicatedWorker"]
                        ) / statistics.median(
                            r["milliseconds"] for r in baseline["dedicatedWorker"]
                        )
                        emit(
                            {
                                "event": "calibration_confirmation",
                                "rate": rate,
                                "worker_ratio": confirmed,
                                "owned_membership": job.verify(cpu_mask),
                            }
                        )
                        confirmed_checksums = {
                            r["checksum"]
                            for rows in (baseline, confirmation)
                            for kind in ("main", "dedicatedWorker")
                            for r in rows[kind]
                        }
                        if not 3.90 <= confirmed <= 4.10 or len(confirmed_checksums) != 1:
                            raise RuntimeError("The fixed 4x rate did not survive confirmation")
                        break
                    job.configure(10000)
                    rate = max(1, round(rate * ratios["dedicatedWorker"] / 4))
                else:
                    raise RuntimeError("Cannot establish the predeclared 4x worker calibration")
            else:
                if args.runtime == "throttled":
                    if args.cpu_throttling == "cdp":
                        if args.rate != 4:
                            raise ValueError("The predeclared CDP rate is exactly four")
                        cdp_rate(4)
                    else:
                        emit({"event": "cpu_rate", **job.configure(args.rate)})
                send(
                    {
                        "command": "measure",
                        "problem": problem,
                        "repeats": 1 if args.smoke or args.audit_only else 3,
                        "pool": "parity-24" if args.smoke else "published-674",
                        "audit": args.audit_only,
                        "purpose": "parity-smoke"
                        if args.smoke
                        else "execution-context-audit"
                        if args.audit_only
                        else "timing",
                    }
                )
                reference_failures = []
                while True:
                    result = receive()
                    if accept_restart(result):
                        continue
                    if result["event"] == "sample":
                        result["runtime"] = args.runtime
                    emit(result)
                    if references and result["event"] == "sample" and result["completed"]:
                        comparison = compare_reference(
                            result["reply"]["answer"],
                            references[result["member"], result["window"]],
                        )
                        emit(
                            {
                                "event": "reference_check",
                                "member": result["member"],
                                "window": result["window"],
                                "repetition": result["repetition"],
                                **comparison,
                            }
                        )
                        if not comparison["passed"]:
                            reference_failures.append(
                                (result["member"], result["window"], result["repetition"])
                            )
                    if (
                        args.audit_only
                        and result["event"] == "sample"
                        and result["completed"]
                        and result.get("model_sha256") != result["expected_model_sha256"]
                    ):
                        raise RuntimeError(
                            "Worker primary LP differs from the canonical Node builder"
                        )
                    if args.smoke and result["event"] == "sample":
                        member = next(
                            member
                            for member in problem["members"]
                            if member["member"] == result["member"]
                        )
                        reference = member["reference"][str(result["window"])]
                        answer = result["reply"]["answer"]
                        assert abs(answer["objective"] - reference["objective"]) <= 1e-6
                        assert answer["objective_scaled"] == reference["objective_scaled"]
                        if reference["unique_moves"]:
                            for week, expected in zip(
                                answer["plan_weeks"], reference["weeks"], strict=True
                            ):
                                assert week["transfers_in"] == expected["transfers_in"]
                                assert week["transfers_out"] == expected["transfers_out"]
                    if result["event"] == "measured":
                        break
                if reference_failures:
                    raise RuntimeError(f"Numeric reference parity failed: {reference_failures}")
                if args.cpu_throttling == "cdp" and args.runtime == "throttled":
                    cdp_rate(1)
        except Exception as error:
            emit({"event": "run_failed", "error": type(error).__name__, "message": str(error)})
            raise
        finally:
            if job:
                if job.node.is_running():
                    adopt_children()
                try:
                    emit({"event": "cpu_restored", **job.configure(10000)})
                except OSError as error:
                    errors.append(f"restore:{error.winerror}")
                if cpu_mask is not None:
                    for child in owned:
                        try:
                            if child.is_running() and child.name() != "conhost.exe":
                                child.cpu_affinity(original_affinity)
                        except psutil.NoSuchProcess:
                            pass
            if proc.poll() is None:
                try:
                    send({"command": "finish"})
                    proc.wait(timeout=15)
                except (OSError, subprocess.TimeoutExpired):
                    for child in reversed(owned):
                        try:
                            if child.is_running():
                                child.terminate()
                        except psutil.NoSuchProcess:
                            pass
                    proc.wait(timeout=5)
            if job:
                job.kernel.CloseHandle(job.handle)
            # Console and browser children can exit just after the launcher. Await their
            # recorded process identities, never a name-wide process selection.
            _, still_alive = psutil.wait_procs(owned, timeout=5)
            for child in still_alive:
                if child.is_running():
                    child.terminate()
            if still_alive:
                psutil.wait_procs(still_alive, timeout=5)
            remaining = sum(child.is_running() for child in owned)
            emit(
                {
                    "event": "cleanup",
                    "owned_processes_remaining": remaining,
                    "node_exit": proc.returncode,
                    "errors": errors,
                }
            )
            if remaining or errors or proc.returncode:
                raise RuntimeError("Own measurement runtime did not close cleanly")


if __name__ == "__main__":
    main()
