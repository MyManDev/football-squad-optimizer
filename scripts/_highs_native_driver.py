"""The native HiGHS side of the window solver measurement, in a process without OR-Tools.

``scripts/measure_window_solver_highs.py`` runs CP-SAT in its own process and native HiGHS in
a child, and this module is that child. It imports ``highspy`` and the standard library only:
OR-Tools ships a ``libhighs.so.1`` of its own and ``highspy`` ships another with the same
SONAME, so on Linux one process cannot load both, in either order. The runner imports the
functions below (the tests exercise them in-process with a stand-in ``highspy``) and runs
this file as ``python -m scripts._highs_native_driver`` for every native solve and for the
version guard. The functions are the #1083 runner's, unchanged; only their home moved.

    python -m scripts._highs_native_driver --version
    python -m scripts._highs_native_driver --job <job.json> --out <result.json>
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import math
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from time import perf_counter
from typing import Any, Final

from scripts._provenance import write_json

#: The native build is set to this many threads. The wasm build is single-threaded and
#: refuses a thread option, so its job leaves it out.
HIGHS_THREADS: Final = 1
MIP_REL_GAP: Final = 0.0
MIP_ABS_GAP: Final = 0.5
HIGHS_PRIMAL_FEASIBLE: Final = 2
#: (month, day) in UTC on which no solve runs.
BLOCKED_DAYS: Final = ((10, 9), (10, 10))

#: The runner file beside this one, with LF line ends so the digest is the committed file's
#: on every checkout; the child reports it so the runner can tell the file changed on disk.
RUNNER_SHA256: Final = hashlib.sha256(
    Path(__file__).with_name("measure_window_solver_highs.py").read_bytes().replace(b"\r\n", b"\n")
).hexdigest()
#: This file's own digest, reported and checked the same way.
DRIVER_SHA256: Final = hashlib.sha256(
    Path(__file__).read_bytes().replace(b"\r\n", b"\n")
).hexdigest()


class ProtocolRefusal(RuntimeError):
    """An input, a guard or a check is not what the protocol declares; nothing goes on."""


def refuse_blocked_date(now: datetime, seconds: float = 0.0) -> None:
    """No solve runs on 9 or 10 October (UTC): none starts on either day, and none starts
    whose ``seconds`` of wall stops could carry it into either."""

    start = now.astimezone(UTC)
    end = start + timedelta(seconds=max(float(seconds), 0.0))
    day = start.date()
    while day <= end.date():
        if (day.month, day.day) in BLOCKED_DAYS:
            if day == start.date():
                raise ProtocolRefusal(
                    f"It is {day.isoformat()} UTC; the protocol runs no solve on 9 or 10 October."
                )
            raise ProtocolRefusal(
                f"A solve started at {start.isoformat(timespec='seconds')} may run until "
                f"{end.isoformat(timespec='seconds')}, into {day.isoformat()} UTC; the "
                "protocol runs no solve on 9 or 10 October."
            )
        day += timedelta(days=1)


def _native_version(highspy: Any) -> str:
    highs = highspy.Highs()
    try:
        return str(highs.version())
    except AttributeError:
        return f"{highs.versionMajor()}.{highs.versionMinor()}.{highs.versionPatch()}"


def highs_options(time_limit: float) -> dict[str, float | bool | int]:
    return {
        "output_flag": False,
        "threads": HIGHS_THREADS,
        "mip_rel_gap": MIP_REL_GAP,
        "mip_abs_gap": MIP_ABS_GAP,
        "time_limit": max(float(time_limit), 0.0),
    }


def _option_value(highs: Any, name: str) -> Any:
    """An option as the native build reports it (older bindings return a status first)."""

    value = highs.getOptionValue(name)
    return value[-1] if isinstance(value, tuple) else value


def _finite(value: float) -> float | None:
    """A bound HiGHS has not computed is infinite; the record holds None, as the wasm
    build's JSON does."""

    return value if math.isfinite(value) else None


def _native_solve(
    highspy: Any,
    path: str,
    budget: float,
    floor: tuple[int, Mapping[int, int | float]] | None,
    start: Sequence[int] | None = None,
) -> dict[str, Any]:
    numpy = importlib.import_module("numpy")
    highs = highspy.Highs()
    # Set before anything runs: the native build starts its scheduler on the first run.
    highs.setOptionValue("threads", HIGHS_THREADS)
    started = perf_counter()
    read_status = int(highs.readModel(path))
    read_seconds = perf_counter() - started
    if read_status < 0:
        raise RuntimeError(f"HiGHS could not read {path}.")
    for name, value in highs_options(budget).items():
        highs.setOptionValue(name, value)
    floor_seconds = 0.0
    if floor is not None:
        value, costs = floor
        started = perf_counter()
        indices = numpy.array(sorted(costs), dtype=numpy.int32)
        values = numpy.array([float(costs[j]) for j in sorted(costs)], dtype=numpy.float64)
        added = int(highs.addRow(float(value), highspy.kHighsInf, len(indices), indices, values))
        floor_seconds = perf_counter() - started
        if added < 0:
            raise RuntimeError("HiGHS refused the hold floor row.")
    start_seconds = 0.0
    start_status: int | None = None
    if start is not None:
        started = perf_counter()
        columns = numpy.arange(len(start), dtype=numpy.int32)
        values = numpy.array([float(value) for value in start], dtype=numpy.float64)
        start_status = int(highs.setSolution(len(start), columns, values))
        start_seconds = perf_counter() - started
        if start_status < 0:
            raise RuntimeError("HiGHS refused the hold solution as a start.")
    started = perf_counter()
    highs.run()
    seconds = perf_counter() - started
    status = int(highs.getModelStatus())
    info = highs.getInfo()
    primal = int(info.primal_solution_status)
    result: dict[str, Any] = {
        "model_status": status,
        "read_seconds": read_seconds,
        "floor_seconds": floor_seconds,
        "start_seconds": start_seconds,
        "start_status": start_status,
        "seconds": seconds,
        "primal_solution_status": primal,
        "bound": _finite(float(info.mip_dual_bound)),
        "threads": int(_option_value(highs, "threads")),
    }
    if primal == HIGHS_PRIMAL_FEASIBLE:
        result["objective"] = float(info.objective_function_value)
        result["solution"] = [float(value) for value in highs.getSolution().col_value]
    return result


def floor_value(solution: Sequence[float], costs: Mapping[int, int | float]) -> int:
    """The primary objective at a rounded hold solution: the floor a HiGHS primary gets."""

    return int(sum(cost * round(solution[j]) for j, cost in costs.items()))


def native_run(job: Mapping[str, Any]) -> dict[str, Any]:
    """One native HiGHS run of one instance: the hold model, then the floored primary."""

    budget = float(job["budget_seconds"])
    refuse_blocked_date(datetime.now(UTC), budget)
    started = perf_counter()
    highspy = importlib.import_module("highspy")
    load_seconds = perf_counter() - started
    costs = {int(j): cost for j, cost in job["objective"].items()}
    hold = _native_solve(highspy, str(job["hold_mps"]), budget, None)
    result: dict[str, Any] = {
        "build": "native",
        "nonce": job.get("nonce"),
        "runner_sha256": RUNNER_SHA256,
        "driver_sha256": DRIVER_SHA256,
        "core_version": _native_version(highspy),
        "load_seconds": load_seconds,
        "hold": {key: value for key, value in hold.items() if key != "solution"},
        "hold_solution": hold.get("solution"),
        "floor": None,
        "primary": None,
        "primary_solution": None,
    }
    start: list[int] | None = None
    if hold.get("solution") is not None:
        result["floor"] = floor_value(hold["solution"], costs)
        start = [round(value) for value in hold["solution"]]
    remaining = budget - float(hold["seconds"])
    if remaining <= 0:
        return result
    floor = None if result["floor"] is None else (int(result["floor"]), costs)
    primary = _native_solve(highspy, str(job["primary_mps"]), remaining, floor, start)
    result["primary"] = {key: value for key, value in primary.items() if key != "solution"}
    result["primary_solution"] = primary.get("solution")
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--version", action="store_true", help="print the HiGHS core version")
    parser.add_argument("--job", type=Path, default=None)
    parser.add_argument("--out", type=Path, default=None)
    arguments = parser.parse_args(argv)
    if arguments.version:
        print(_native_version(importlib.import_module("highspy")))
        return 0
    if arguments.job is None or arguments.out is None:
        parser.error("--job and --out are required for a solve")
    job = json.loads(arguments.job.read_text(encoding="utf-8"))
    write_json(arguments.out, native_run(job))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
