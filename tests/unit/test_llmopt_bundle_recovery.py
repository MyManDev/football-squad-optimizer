"""A failed or recovered preference job can use only its original unspent work."""

import json
from datetime import UTC, datetime

import pytest
from ortools.sat.python import cp_model
from tests.unit import test_advice_worker as world
from tests.unit.test_llmopt_preference_bundle import _started

from squadopt.contracts.preference_bundle import BUNDLE_VERSION
from squadopt.optimization.cpsat import solve
from squadopt.optimization.models import SolverExecutionError
from squadopt.optimization.work_budget import (
    WorkBudget,
    WorkBudgetExhausted,
    current_work_budget,
    work_budget,
)
from squadopt.platform import advice_worker
from squadopt.platform.advice_queue import run_advice_worker_once
from squadopt.platform.advice_runs import FileRunStore, RunAdmissionError
from squadopt.platform.jobs_contract import JobError


def program_request(body, run, player):
    return {
        **body,
        "run": run,
        "preference_bundle": {
            "contract_version": BUNDLE_VERSION,
            "slots": [],
            "prices": [],
            "choices": [],
            "program": {
                "preferences": [{"rules": {"keep_players": [player]}}],
                "max_total_cost_tenths": 30,
            },
        },
    }


def attempt(backend):
    compute = advice_worker.build_advice_compute(
        backend.contexts, backend.job_specs, runs=backend.runs, cache=backend.cache
    )

    def clock():
        return datetime.now(UTC).isoformat()

    return run_advice_worker_once(
        backend.queue, backend.cache, compute, claim_at_utc=clock, terminal_at_utc=clock
    )


def test_transient_bundle_failure_retries_same_request_and_job_without_double_charge(
    tmp_path, monkeypatch
):
    backend, client, route, body, run, held = _started(tmp_path, monkeypatch)
    request = program_request(body, run, held[0])
    identifier = client.post(route, json=request).json()["job_id"]
    compute = advice_worker.compute_preference_bundle
    balances = []

    def interrupted(*args):
        budget = current_work_budget()
        balances.append(budget.remaining)
        if len(balances) == 1:
            assert budget.cp_limit(21) == 21
            budget.record_cp(1.5)
            raise OSError("Transient worker read failure")
        return compute(*args)

    monkeypatch.setattr(advice_worker, "compute_preference_bundle", interrupted)
    retry = attempt(backend)
    assert (retry.job_id, retry.status, retry.attempt) == (identifier, "queued", 2)
    assert client.post(route, json=request).json()["job_id"] == identifier
    done = attempt(backend)
    assert (done.job_id, done.status, done.attempt) == (identifier, "completed", 2)
    assert balances == [63, 61.5]
    assert client.post(route, json=request).status_code == 200
    with backend.runs.transaction() as tx:
        receipt = tx.state["jobs"][identifier]["receipt"]
        assert receipt["cp_used"] >= 1.5
        assert receipt["unconfirmed"] == 0
        assert tx.state["runs"][run["run_id"]]["reserved"] == 84
    assert len(backend.queue.jobs()) == 2


@pytest.mark.parametrize(("window", "single"), [(1, 21), (3, 122)])
def test_recovered_bundle_fences_stale_worker_and_retains_a_real_retry(
    tmp_path, monkeypatch, window, single
):
    backend, client, route, body, run, held = _started(tmp_path, monkeypatch, window)
    request = program_request(body, run, held[0])
    identifier = client.post(route, json=request).json()["job_id"]
    job = backend.queue.claim(at_utc=backend.queue.load(identifier).updated_at_utc)
    old = backend.runs.allocation(identifier, attempt=job.attempt)
    assert old.cp_limit(single) == single
    old.record_cp(1)
    # A hard crash with one outstanding grant leaves real work for the same job.
    grant = old.cp_limit(3 * single)
    assert grant == 3 * single - 1 - single / 4 and grant > single
    backend.queue.recover(at_utc=job.updated_at_utc, lease_seconds=0)
    assert client.post(route, json=request).json()["job_id"] == identifier
    assert world._work(backend) == 1
    assert client.post(route, json=request).status_code == 200
    restarted = FileRunStore(backend.runs.root)
    with restarted.transaction() as tx:
        receipt = tx.state["jobs"][identifier]["receipt"]
        assert receipt["attempt"] == 2 and receipt["finished"]
        assert receipt["unconfirmed"] == grant
        assert receipt["cp_used"] >= 1
        assert tx.state["runs"][run["run_id"]]["reserved"] == 4 * single
        assert len(backend.queue.jobs()) == 2
    before = restarted.path.read_bytes()
    with pytest.raises(WorkBudgetExhausted):
        old.record_cp(1)
    with pytest.raises(WorkBudgetExhausted):
        old.cp_limit(1)
    backend.runs.finish(identifier, old)
    with pytest.raises(RunAdmissionError):
        restarted.allocation(identifier, attempt=2)
    assert restarted.path.read_bytes() == before


def test_repeated_failure_releases_unused_budget_but_keeps_all_job_slots_counted(
    tmp_path, monkeypatch
):
    backend, client, route, body, run, held = _started(tmp_path, monkeypatch)
    request = program_request(body, run, held[0])
    identifier = client.post(route, json=request).json()["job_id"]

    def broken(*args):
        budget = current_work_budget()
        assert budget.cp_limit(1) == 1
        budget.record_cp(0.001)
        raise OSError("Repeated worker read failure")

    monkeypatch.setattr(advice_worker, "compute_preference_bundle", broken)
    assert [attempt(backend).status for _ in range(3)] == ["queued", "queued", "failed"]
    assert client.post(route, json=request).json()["job_id"] == identifier
    with backend.runs.transaction() as tx:
        assert tx.state["jobs"][identifier]["receipt"]["charged"] == 0.003
        assert tx.state["runs"][run["run_id"]]["reserved"] == 21.003
    for player in held[:2]:
        followup = {**body, "run": run, "preferences": {"keep_players": [player]}}
        assert client.post(route, json=followup).status_code == 202
    blocked = client.post(
        route, json={**body, "run": run, "preferences": {"keep_players": [held[2]]}}
    )
    assert blocked.json()["error"]["code"] == "RUN_BUDGET_EXHAUSTED"
    assert len(backend.queue.jobs()) == 4
    with FileRunStore(backend.runs.root).transaction() as tx:
        assert tx.state["runs"][run["run_id"]]["reserved"] == 63.003


@pytest.mark.parametrize(
    "failure", [OSError("Settlement failed"), WorkBudgetExhausted("Stale attempt")]
)
def test_solver_propagates_ledger_settlement_failure_without_reclassifying_it(monkeypatch, failure):
    def settle(*args):
        raise failure

    monkeypatch.setattr(WorkBudget, "record_cp", settle)
    with work_budget(WorkBudget(1)), pytest.raises(type(failure)) as caught:
        solve(cp_model.CpModel(), cp_model.CpSolver())
    assert caught.value is failure


def test_overshot_price_preserves_fractional_remaining_work_for_selected_combo(
    tmp_path, monkeypatch
):
    backend, client, route, body, run, held = _started(tmp_path, monkeypatch, window=3)

    def rule(player):
        return {"preferences": {"keep_players": [player]}, "chip": None}

    bundle = {
        "contract_version": BUNDLE_VERSION,
        "program": None,
        "slots": [rule(held[0]), rule(held[1])],
        "prices": [{"outcome": i, "ceiling": None} for i in range(2)],
        "choices": [
            {
                "accepted": mask,
                "applied": [i for i in range(2) if mask & (1 << i)],
                "selection": rule(held[2]),
            }
            for mask in range(4)
        ],
    }
    request = {**body, "run": run, "preference_bundle": bundle}
    queued = client.post(route, json=request)
    assert queued.status_code == 202, queued.text
    normal = advice_worker.compute_preference_bundle
    caps = []
    keys = []

    def simulate_stops(job, spec, menu, capture, cache, specs, compute):
        baseline = cache.get(spec.switch("llmopt_preference_bundle")["base_key"])

        def component(child, *args):
            budget = current_work_budget()
            cap = budget.cp_limit(122)
            caps.append(cap)
            keys.append(child.cache_key)
            budget.record_cp(cap + (0.000085 if len(caps) == 1 else 0))
            return baseline

        return normal(job, spec, menu, capture, cache, specs, component)

    monkeypatch.setattr(advice_worker, "compute_preference_bundle", simulate_stops)
    assert world._work(backend) == 1
    answer = client.post(route, json=request)
    result = answer.json()["payload"]["preference_bundle_result"]
    assert result["selected"]["status"] == "done"
    assert caps == pytest.approx([122, 122, 121.999915])
    assert backend.cache.get(keys[-1]) is None
    state = json.loads(backend.runs.path.read_bytes())
    assert state["jobs"][queued.json()["job_id"]]["receipt"]["cp_used"] == pytest.approx(366)


@pytest.mark.parametrize("shared", [False, True])
def test_retry_requires_an_active_consumer_before_running_new_solver_work(
    tmp_path, monkeypatch, shared
):
    backend, client, route, body, run, held = _started(tmp_path, monkeypatch)
    request = program_request(body, run, held[0])
    identifier = client.post(route, json=request).json()["job_id"]
    if shared:
        other = {**run, "run_id": "b" * 32}
        assert (
            client.post(route, json={**body, "run": {**other, "stage": "base"}}).status_code == 200
        )
        assert client.post(route, json={**request, "run": other}).json()["job_id"] == identifier
    compute = advice_worker.compute_preference_bundle
    calls = []

    def cancel_during_first_attempt(job, *args):
        calls.append(job.attempt)
        if job.attempt == 1:
            assert (
                client.post(f"/api/v1/llmopt/runs/{run['run_id']}/cancel", json={}).status_code
                == 200
            )
            raise OSError("Worker interrupted after cancellation")
        return compute(job, *args)

    monkeypatch.setattr(advice_worker, "compute_preference_bundle", cancel_during_first_attempt)
    assert attempt(backend).status == "queued"
    assert attempt(backend).status == ("completed" if shared else "cancelled")
    assert calls == ([1, 2] if shared else [1])
    assert len(backend.queue.jobs()) == 2


def test_closed_recovery_finishes_a_previously_published_answer_without_computing(
    tmp_path, monkeypatch
):
    backend, client, route, body, run, held = _started(tmp_path, monkeypatch)
    request = program_request(body, run, held[0])
    identifier = client.post(route, json=request).json()["job_id"]
    job = backend.queue.claim(at_utc=backend.queue.load(identifier).updated_at_utc)
    compute = advice_worker.build_advice_compute(
        backend.contexts, backend.job_specs, runs=backend.runs, cache=backend.cache
    )
    payload = compute(job)
    backend.cache.put(job.cache_key, payload)
    assert client.post(f"/api/v1/llmopt/runs/{run['run_id']}/cancel", json={}).status_code == 200
    backend.queue.recover(at_utc=job.updated_at_utc, lease_seconds=0)
    monkeypatch.setattr(
        backend.runs,
        "allocation",
        lambda *a, **kw: pytest.fail("Cached completion requested solver work"),
    )
    assert attempt(backend).status == "completed"
    assert backend.cache.get(job.cache_key) == payload


def test_failed_initial_allocation_charges_zero_and_allows_another_complete_bundle(
    tmp_path, monkeypatch
):
    backend, client, route, body, run, held = _started(tmp_path, monkeypatch)
    request = program_request(body, run, held[0])
    identifier = client.post(route, json=request).json()["job_id"]
    with monkeypatch.context() as stopped:

        def unavailable(*args, **kwargs):
            raise OSError("Initial ledger write could not complete")

        stopped.setattr(backend.runs, "_save", unavailable)
        assert attempt(backend).status == "failed"
    with backend.runs.transaction() as tx:
        assert tx.state["jobs"][identifier]["receipt"] is None
    alternate = program_request(body, run, held[1])
    assert client.post(route, json=alternate).status_code == 202
    assert world._work(backend) == 1
    assert client.post(route, json=alternate).status_code == 200
    with backend.runs.transaction() as tx:
        receipt = tx.state["jobs"][identifier]["receipt"]
        assert receipt["charged"] == receipt["calls"] == 0
        assert tx.state["runs"][run["run_id"]]["reserved"] == 84
    assert len(backend.queue.jobs()) == 3


@pytest.mark.parametrize("cancel", [False, True])
def test_stale_solver_cannot_spend_after_terminal_release_or_cancelled_recovery(
    tmp_path, monkeypatch, cancel
):
    backend, client, route, body, run, held = _started(tmp_path, monkeypatch)
    request = program_request(body, run, held[0])
    identifier = client.post(route, json=request).json()["job_id"]
    stamp = backend.queue.load(identifier).updated_at_utc
    original = backend.queue.claim(at_utc=stamp)
    grant = backend.runs.allocation(identifier, attempt=original.attempt)
    assert grant.cp_limit(2) == 2
    if cancel:
        assert (
            client.post(f"/api/v1/llmopt/runs/{run['run_id']}/cancel", json={}).status_code == 200
        )
    backend.queue.recover(at_utc=stamp, lease_seconds=0)
    if cancel:
        assert attempt(backend).status == "cancelled"
    else:
        recovered = backend.queue.claim(at_utc=stamp)
        # The new worker failed before calling allocation (for example, reading cache).
        backend.queue.store(
            recovered.transition(
                "failed", at_utc=stamp, error=JobError("ADVICE_FAILED", "Read failed.")
            )
        )
        assert client.post(route, json=request).json()["job_id"] == identifier
    with backend.runs.transaction() as tx:
        receipt = tx.state["jobs"][identifier]["receipt"]
        assert receipt["finished"] and receipt["unconfirmed"] == 2 and receipt["pending"] == 0
        if not cancel:
            assert receipt["charged"] == 2
    before = backend.runs.path.read_bytes()
    with pytest.raises(WorkBudgetExhausted):
        grant.record_cp(1)
    with pytest.raises(WorkBudgetExhausted):
        grant.cp_limit(1)
    backend.runs.finish(identifier, grant)
    assert backend.runs.path.read_bytes() == before


def test_failed_cp_call_charges_unknown_work_and_leaves_remaining_components_usable(
    tmp_path, monkeypatch
):
    backend, client, route, body, run, held = _started(tmp_path, monkeypatch)
    job_id = client.post(route, json=program_request(body, run, held[0])).json()["job_id"]
    job = backend.queue.claim(at_utc=backend.queue.load(job_id).updated_at_utc)
    budget = backend.runs.allocation(job_id, attempt=job.attempt)
    solver = cp_model.CpSolver()
    solver.parameters.max_deterministic_time = 7
    with work_budget(budget):
        with monkeypatch.context() as stopped:

            def fail(*args):
                raise RuntimeError("No engine diagnostics returned")

            stopped.setattr(cp_model.CpSolver, "solve", fail)
            with pytest.raises(SolverExecutionError):
                solve(cp_model.CpModel(), solver)
        assert budget.unconfirmed == 7
        assert budget.cp_used == 0 and budget.remaining == 56
        assert solve(cp_model.CpModel(), solver) == cp_model.OPTIMAL
    with backend.runs.transaction() as tx:
        receipt = tx.state["jobs"][job_id]["receipt"]
        assert receipt["unconfirmed"] == 7 and receipt["pending"] == 0
        assert receipt["calls"] == 2
