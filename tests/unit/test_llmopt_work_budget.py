"""A run allocation bounds nested solves without changing unbound callers."""

import json
from pathlib import Path

import pytest
from ortools.sat.python import cp_model

from squadopt.contracts.llmopt_run import RunReference, run_reference_schema
from squadopt.optimization.cpsat import solve
from squadopt.optimization.work_budget import WorkBudget, WorkBudgetExhausted, work_budget
from squadopt.platform.jobs_contract import backend_jobs_schema


def test_every_nested_call_is_clamped_and_exhaustion_starts_no_solve(monkeypatch):
    model = cp_model.CpModel()
    value = model.new_int_var(0, 9, "value")
    model.maximize(value)
    seen = []
    original = cp_model.CpSolver.solve

    def recorded(solver, problem):
        seen.append(solver.parameters.max_deterministic_time)
        return original(solver, problem)

    monkeypatch.setattr(cp_model.CpSolver, "solve", recorded)
    budget = WorkBudget(2.0, cp_used=1.5)
    with work_budget(budget):
        assert solve(model, cp_model.CpSolver()) == cp_model.OPTIMAL
        assert seen == [0.5]
        budget.cp_used = 2.00001  # Engine stop granularity remains visible, never clamped.
        with pytest.raises(WorkBudgetExhausted):
            solve(model, cp_model.CpSolver())
    assert seen == [0.5]
    assert solve(model, cp_model.CpSolver()) == cp_model.OPTIMAL
    assert len(seen) == 2


def test_native_capacity_is_reserved_before_execution_and_never_refunded():
    budget = WorkBudget(122)
    budget.reserve_native(1800)
    assert budget.native_reserved == 60
    assert budget.remaining == 62
    budget.cp_used = 61.5
    with pytest.raises(WorkBudgetExhausted):
        budget.reserve_native(30)
    assert budget.native_reserved == 60


@pytest.mark.parametrize("field", ["api_key", "unknown", "preferences"])
def test_run_reference_rejects_extra_fields(field):
    with pytest.raises(ValueError):
        RunReference.parse(
            {"contract_version": "llmopt_run_v1", "run_id": "a" * 32, "stage": "base", field: "x"}
        )


def test_new_schemas_match_their_producers_and_v1_is_unchanged():
    root = Path("docs/contracts")
    assert json.loads((root / "llmopt_run_v1.schema.json").read_text()) == run_reference_schema()
    assert json.loads((root / "backend_jobs_v2.schema.json").read_text()) == backend_jobs_schema(
        "backend_jobs_v2"
    )
    assert json.loads((root / "backend_jobs_v1.schema.json").read_text()) == backend_jobs_schema()
