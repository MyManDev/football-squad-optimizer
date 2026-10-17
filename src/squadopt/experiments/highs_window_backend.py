"""A HiGHS backend for the member window model's MPS export: the switch's draft (#1090).

The #1090 record (``docs/research/window_solver_highs_current.md``) found that native HiGHS
proves every GW7 member window CP-SAT proves, and every five-week window CP-SAT leaves
FEASIBLE, never below CP-SAT's value: "a switch is supported". This module is the solver
side of that switch, drafted in the laboratory and wired to nothing: no planner, use case or
publication imports it, and every default of the window path stays as it is. The design note
``docs/research/highs_window_switch_design.md`` says what would have to change for it to serve.

It does what the measurement's native child does (``scripts/_highs_native_driver.py``), on
the two MPS files the measurement's exporter writes for one instance:

1. solve the hold model (the window with no transfer) to its optimum;
2. floor the primary at the primary objective of the rounded hold solution, recomputed
   exactly from the objective's coefficients, and start the primary from that solution;
3. solve the primary within what the budget left, and return the rounded column values.

Mapping a solution back onto the CP-SAT model is the exporter's second check, which fixes
every CP-SAT variable at the rounded value and asks CP-SAT to confirm feasibility and the
objective; the tests run that path on a synthetic model. ``highspy`` is imported when a
solve is asked for, never at import time, because the project does not depend on it: the
measurement installed ``highspy==1.15.1`` in its own environment, and OR-Tools and
``highspy`` each ship a ``libhighs.so.1``, so on Linux one process cannot hold both. A
process that solves with this module must not have loaded OR-Tools, which is the first
thing the design note has to settle.
"""

from __future__ import annotations

import importlib
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Any, Final

#: The settings the #994 protocol measured: one thread, a proof on the integer objective.
HIGHS_THREADS: Final = 1
MIP_REL_GAP: Final = 0.0
MIP_ABS_GAP: Final = 0.5
#: HiGHS model status codes this module reads (``HighsModelStatus``).
HIGHS_OPTIMAL: Final = 7
HIGHS_TIME_LIMIT: Final = 13
#: ``HighsSolutionStatus``: a primal solution is present and feasible.
HIGHS_PRIMAL_FEASIBLE: Final = 2


class HighsUnavailable(RuntimeError):
    """``highspy`` could not be imported in this process."""


@dataclass(frozen=True)
class HighsSolve:
    """One HiGHS solve of one MPS file."""

    model_status: int
    seconds: float
    read_seconds: float
    bound: float | None
    objective: float | None
    solution: tuple[float, ...] | None
    threads: int

    @property
    def proved(self) -> bool:
        return self.model_status == HIGHS_OPTIMAL and self.solution is not None

    @property
    def rounded(self) -> tuple[int, ...] | None:
        return None if self.solution is None else tuple(round(v) for v in self.solution)


@dataclass(frozen=True)
class HighsWindowResult:
    """The hold solve, the floored primary and what the window's answer is."""

    core_version: str
    hold: HighsSolve
    floor: int | None
    primary: HighsSolve | None

    @property
    def status(self) -> str:
        """``proved_optimal``, ``feasible`` or ``no_solution``, read as the protocol reads a run:
        a primary without a solution keeps the hold plan and is not proved."""

        if self.primary is not None and self.primary.solution is not None:
            return "proved_optimal" if self.primary.proved else "feasible"
        return "feasible" if self.hold.solution is not None else "no_solution"

    @property
    def solution(self) -> tuple[int, ...] | None:
        """The rounded column values of the answer: the primary's, else the hold's."""

        if self.primary is not None and self.primary.rounded is not None:
            return self.primary.rounded
        return self.hold.rounded

    @property
    def seconds(self) -> float:
        return self.hold.seconds + (0.0 if self.primary is None else self.primary.seconds)


def import_highspy() -> Any:
    """``highspy``, imported now; a missing or unloadable build is named, not guessed at."""

    try:
        return importlib.import_module("highspy")
    except ImportError as error:
        raise HighsUnavailable(
            "highspy could not be imported. It is not a project dependency; the measurement "
            "installed highspy==1.15.1 in its own environment, and a process that has loaded "
            f"OR-Tools cannot load it on Linux (one libhighs.so.1 per process): {error}"
        ) from error


def core_version(highspy: Any) -> str:
    highs = highspy.Highs()
    try:
        return str(highs.version())
    except AttributeError:
        return f"{highs.versionMajor()}.{highs.versionMinor()}.{highs.versionPatch()}"


def objective_at(solution: Sequence[float], costs: Mapping[int, int | float]) -> int:
    """The objective at the rounded ``solution``, exactly, from the MPS objective's columns."""

    return int(sum(cost * round(solution[j]) for j, cost in costs.items()))


def _option(highs: Any, name: str) -> Any:
    value = highs.getOptionValue(name)
    return value[-1] if isinstance(value, tuple) else value


def _finite(value: float) -> float | None:
    return value if math.isfinite(value) else None


def solve_mps(
    highspy: Any,
    path: Path,
    budget_seconds: float,
    *,
    floor: tuple[int, Mapping[int, int | float]] | None = None,
    start: Sequence[int] | None = None,
    threads: int = HIGHS_THREADS,
) -> HighsSolve:
    """Solve one MPS file, with an optional floor row on the objective and an optional start.

    The floor is ``(value, costs)``: the row ``sum(costs[j] * x_j) >= value``. The clock runs
    around ``run`` only; the read, the floor row and the start are set before it starts.
    """

    numpy = importlib.import_module("numpy")
    highs = highspy.Highs()
    highs.setOptionValue("threads", int(threads))
    started = perf_counter()
    if int(highs.readModel(str(path))) < 0:
        raise RuntimeError(f"HiGHS could not read {path}.")
    read_seconds = perf_counter() - started
    highs.setOptionValue("output_flag", False)
    highs.setOptionValue("mip_rel_gap", MIP_REL_GAP)
    highs.setOptionValue("mip_abs_gap", MIP_ABS_GAP)
    highs.setOptionValue("time_limit", max(float(budget_seconds), 0.0))
    if floor is not None:
        value, costs = floor
        indices = numpy.array(sorted(costs), dtype=numpy.int32)
        values = numpy.array([float(costs[j]) for j in sorted(costs)], dtype=numpy.float64)
        if int(highs.addRow(float(value), highspy.kHighsInf, len(indices), indices, values)) < 0:
            raise RuntimeError("HiGHS refused the hold floor row.")
    if start is not None:
        columns = numpy.arange(len(start), dtype=numpy.int32)
        values = numpy.array([float(v) for v in start], dtype=numpy.float64)
        if int(highs.setSolution(len(start), columns, values)) < 0:
            raise RuntimeError("HiGHS refused the hold solution as a start.")
    started = perf_counter()
    highs.run()
    seconds = perf_counter() - started
    info = highs.getInfo()
    found = int(info.primal_solution_status) == HIGHS_PRIMAL_FEASIBLE
    return HighsSolve(
        model_status=int(highs.getModelStatus()),
        seconds=seconds,
        read_seconds=read_seconds,
        bound=_finite(float(info.mip_dual_bound)),
        objective=float(info.objective_function_value) if found else None,
        solution=tuple(float(v) for v in highs.getSolution().col_value) if found else None,
        threads=int(_option(highs, "threads")),
    )


def solve_window(
    hold_mps: Path,
    primary_mps: Path,
    objective: Mapping[int, int | float],
    budget_seconds: float,
    *,
    threads: int = HIGHS_THREADS,
    highspy: Any | None = None,
) -> HighsWindowResult:
    """Solve one window as the measurement did: the hold model, then the floored primary.

    ``objective`` maps MPS column indices to the primary objective's coefficients, the
    exporter's order; the hold and primary MPS share their columns. The primary gets what the
    hold solve left of ``budget_seconds``; when nothing is left it is not run.
    """

    highspy = import_highspy() if highspy is None else highspy
    costs = {int(j): cost for j, cost in objective.items()}
    hold = solve_mps(highspy, hold_mps, budget_seconds, threads=threads)
    floor: int | None = None
    start: tuple[int, ...] | None = None
    if hold.solution is not None:
        floor = objective_at(hold.solution, costs)
        start = hold.rounded
    remaining = float(budget_seconds) - hold.seconds
    primary: HighsSolve | None = None
    if remaining > 0:
        primary = solve_mps(
            highspy,
            primary_mps,
            remaining,
            floor=None if floor is None else (floor, costs),
            start=start,
            threads=threads,
        )
    return HighsWindowResult(core_version(highspy), hold, floor, primary)
