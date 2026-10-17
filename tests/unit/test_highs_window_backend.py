"""The HiGHS window backend draft solves the exporter's MPS and maps back through check 2.

The synthetic model is the measurement runner's toy model: a CP-SAT model with a maximum, an
element and an enforced constraint, exported as MPS by the runner's exporter. A stand-in
``highspy`` records the calls the backend makes (the hold model, the floor row at the hold
value, the start, the primary) and gives back known solutions, so these tests run where
``highspy`` is not installed. The one test on the real build skips in a process that has
loaded OR-Tools, which on Linux is every pytest process here, and says so.
"""

from __future__ import annotations

import math
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from ortools.sat.python import cp_model
from scripts import measure_window_solver_highs as runner

from squadopt.experiments import highs_window_backend as backend


def _export(tmp_path: Path) -> tuple[dict[str, runner.Milp], dict[str, Path]]:
    milps: dict[str, runner.Milp] = {}
    paths: dict[str, Path] = {}
    for part, hold in (("hold", True), ("primary", False)):
        milps[part] = runner.export_milp(runner._toy_model(hold).proto, f"toy-{part}")
        paths[part] = tmp_path / f"toy-{part}.mps"
        paths[part].write_bytes(runner.write_mps(milps[part]).encode("utf-8"))
    return milps, paths


def _cp_sat_optimum(hold: bool) -> tuple[int, list[int]]:
    model = runner._toy_model(hold)
    solver = cp_model.CpSolver()
    solver.parameters.num_search_workers = 1
    assert solver.solve(model) == cp_model.OPTIMAL
    return round(solver.objective_value), [int(v) for v in solver.response_proto.solution]


def _column_values(milp: runner.Milp, proto: Any, cp_values: list[int]) -> list[float]:
    assignment = runner.cp_sat_assignment(milp, proto, cp_values)
    assert assignment is not None
    return [float(v) for v in assignment]


class _FakeHighs:
    """The calls a solve makes, in order, with a hold or primary answer to give."""

    log: list[tuple[Any, ...]]
    answers: list[list[float] | None]

    def __init__(self) -> None:
        self.options: dict[str, Any] = {}
        self.answer: list[float] | None = None

    def setOptionValue(self, name: str, value: Any) -> None:
        self.options[name] = value

    def getOptionValue(self, name: str) -> Any:
        return self.options[name]

    def readModel(self, path: str) -> int:
        self.log.append(("read", Path(path).name))
        self.answer = self.answers.pop(0)
        return 0

    def addRow(self, lower: float, upper: float, count: int, indices: Any, values: Any) -> int:
        self.log.append(("floor", lower, [int(i) for i in indices], [float(v) for v in values]))
        return 0

    def setSolution(self, count: int, indices: Any, values: Any) -> int:
        self.log.append(("start", [float(v) for v in values]))
        return 0

    def run(self) -> None:
        self.log.append(("run", dict(self.options)))

    def getModelStatus(self) -> int:
        return backend.HIGHS_OPTIMAL if self.answer is not None else backend.HIGHS_TIME_LIMIT

    def getInfo(self) -> Any:
        found = self.answer is not None
        return SimpleNamespace(
            primal_solution_status=backend.HIGHS_PRIMAL_FEASIBLE if found else 0,
            mip_dual_bound=0.0 if found else math.inf,
            objective_function_value=0.0,
        )

    def getSolution(self) -> Any:
        return SimpleNamespace(col_value=self.answer)

    def version(self) -> str:
        return "1.15.1"


def _fake(answers: list[list[float] | None]) -> tuple[Any, list[tuple[Any, ...]]]:
    log: list[tuple[Any, ...]] = []
    highs = type("Highs", (_FakeHighs,), {"log": log, "answers": answers})
    return SimpleNamespace(Highs=highs, kHighsInf=math.inf), log


def test_the_backend_solves_hold_then_the_floored_primary_from_the_hold_start(
    tmp_path: Path,
) -> None:
    milps, paths = _export(tmp_path)
    hold_value, hold_cp = _cp_sat_optimum(True)
    _, primary_cp = _cp_sat_optimum(False)
    hold_columns = _column_values(milps["hold"], runner._toy_model(True).proto, hold_cp)
    primary_columns = _column_values(milps["primary"], runner._toy_model(False).proto, primary_cp)
    # The stand-in returns the hold optimum nudged off the integers, then the primary optimum.
    nudged = [v + (0.3 if i == 0 else -0.2) for i, v in enumerate(hold_columns)]
    highspy, log = _fake([nudged, primary_columns])
    result = backend.solve_window(
        paths["hold"], paths["primary"], milps["primary"].objective, 60.0, highspy=highspy
    )
    assert [entry[0] for entry in log] == ["read", "run", "read", "floor", "start", "run"]
    assert log[0][1] == "toy-hold.mps" and log[2][1] == "toy-primary.mps"
    floor = log[3]
    assert floor[1] == float(result.floor)
    assert result.floor == backend.objective_at(nudged, milps["primary"].objective)
    assert result.floor == hold_value - milps["primary"].objective_offset
    assert floor[2] == sorted(milps["primary"].objective)
    assert log[4][1] == [float(round(v)) for v in nudged]
    assert log[1][1]["threads"] == 1 and log[1][1]["mip_abs_gap"] == 0.5
    assert log[5][1]["time_limit"] <= 60.0
    assert result.status == "proved_optimal"
    assert result.solution == tuple(round(v) for v in primary_columns)
    assert result.core_version == "1.15.1"
    assert result.primary is not None and result.primary.threads == 1
    assert result.seconds >= 0.0


def test_the_answer_maps_back_through_check_two_at_cp_sat_s_optimum(tmp_path: Path) -> None:
    milps, paths = _export(tmp_path)
    primary_value, primary_cp = _cp_sat_optimum(False)
    _, hold_cp = _cp_sat_optimum(True)
    hold_columns = _column_values(milps["hold"], runner._toy_model(True).proto, hold_cp)
    primary_columns = _column_values(milps["primary"], runner._toy_model(False).proto, primary_cp)
    highspy, _ = _fake([hold_columns, [v + 0.1 for v in primary_columns]])
    result = backend.solve_window(
        paths["hold"], paths["primary"], milps["primary"].objective, 60.0, highspy=highspy
    )
    assert result.solution is not None
    parsed = runner.read_mps(paths["primary"].read_text(encoding="utf-8"))
    check = runner.check_two(
        milps["primary"], parsed, runner._toy_model(False).proto, list(result.solution)
    )
    assert check["passed"] is True
    assert round(check["value"]) == primary_value


def test_a_primary_without_a_solution_keeps_the_hold_plan_and_is_not_proved(
    tmp_path: Path,
) -> None:
    milps, paths = _export(tmp_path)
    _, hold_cp = _cp_sat_optimum(True)
    hold_columns = _column_values(milps["hold"], runner._toy_model(True).proto, hold_cp)
    highspy, _ = _fake([hold_columns, None])
    result = backend.solve_window(
        paths["hold"], paths["primary"], milps["primary"].objective, 60.0, highspy=highspy
    )
    assert result.status == "feasible"
    assert result.solution == tuple(round(v) for v in hold_columns)
    assert result.primary is not None and result.primary.solution is None


def test_a_hold_without_a_solution_runs_the_primary_with_no_floor_and_no_start(
    tmp_path: Path,
) -> None:
    milps, paths = _export(tmp_path)
    highspy, log = _fake([None, None])
    result = backend.solve_window(
        paths["hold"], paths["primary"], milps["primary"].objective, 60.0, highspy=highspy
    )
    assert [entry[0] for entry in log] == ["read", "run", "read", "run"]
    assert result.floor is None and result.status == "no_solution" and result.solution is None


def test_a_missing_highspy_is_named_not_guessed_at(monkeypatch: pytest.MonkeyPatch) -> None:
    import sys

    monkeypatch.setitem(sys.modules, "highspy", None)
    with pytest.raises(backend.HighsUnavailable, match=r"one libhighs\.so\.1 per process"):
        backend.import_highspy()


def test_the_real_build_proves_the_toy_model_where_it_can_load(tmp_path: Path) -> None:
    """On Linux this skips in any process that holds OR-Tools, which pytest does here."""

    try:
        highspy = backend.import_highspy()
    except backend.HighsUnavailable as error:
        pytest.skip(str(error)[:160])
    milps, paths = _export(tmp_path)
    primary_value, _ = _cp_sat_optimum(False)
    result = backend.solve_window(paths["hold"], paths["primary"], milps["primary"].objective, 60.0)
    assert result.status == "proved_optimal" and result.solution is not None
    parsed = runner.read_mps(paths["primary"].read_text(encoding="utf-8"))
    check = runner.check_two(
        milps["primary"], parsed, runner._toy_model(False).proto, list(result.solution)
    )
    assert check["passed"] is True and round(check["value"]) == primary_value
    assert highspy is not None
