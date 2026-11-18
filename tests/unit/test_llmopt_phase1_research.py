"""Research accounting, frozen population and full-resource package validation."""

from dataclasses import replace
from itertools import combinations

import pytest
from docs.research.llmopt_phase1 import benchmark, pairs
from docs.research.llmopt_phase1.freeze import digest
from docs.research.llmopt_phase1.neighborhood import candidate_ids
from scripts.measure_window_solver_highs import window_call
from tests.unit.test_expected_swap import world

from squadopt.contracts.preferences import DecisionPreferences
from squadopt.optimization import SolverStatus


def test_inputs_have_twenty_distinct_member_weeks_on_matching_captures():
    population = set()
    for frozen, inputs in benchmark.snapshots():
        assert inputs.capture == frozen["projection"]["source_snapshot_id"]
        for entry in inputs.members:
            population.add((inputs.gameweek, entry))
    assert len(population) == 20
    assert digest({8: "week"}) == digest({"8": "week"})


def test_rescored_expected_utility_never_inherits_the_surrogate_proof():
    *_, plan = world()
    plan = replace(
        plan,
        diagnostics={
            "expected_lineup_window": {
                "chosen": "legacy_proposal",
                "candidates": [{"proposal": "legacy_proposal", "utility": 100}],
            },
            "best_objective_bound": 100,
            "absolute_optimality_gap": 0,
        },
    )
    result = benchmark.summary(plan, 1.0, [])
    assert result["solver_status"] == "OPTIMAL"
    assert result["proof"] == "not_proven"
    assert result["best_bound"] is None
    assert result["absolute_gap_points"] is None


def test_nonoptimal_incumbent_keeps_its_gap_without_becoming_a_proof():
    *_, plan = world()
    plan = replace(
        plan,
        solver_status=SolverStatus.FEASIBLE,
        diagnostics={
            "best_objective_bound": 110,
            "absolute_optimality_gap": 10,
        },
    )
    result = benchmark.summary(plan, 1.0, [])
    assert result["proof"] == "not_proven"
    assert result["best_bound"] == 110
    assert result["absolute_gap_points"] == 10


def test_two_moves_are_validated_together_with_the_original_bank_and_free_transfers():
    horizon, initial, settings, policy, plan = world()
    initial = replace(initial, free_transfers=2)
    policy = replace(policy, max_transfers_per_gameweek=1, allow_two_free_transfers=True)
    candidate, record = pairs.propose_pairs(
        horizon,
        initial,
        settings,
        policy,
        plan.weeks[0],
        (frozenset(initial.squad_player_ids),),
        deterministic_slack=3,
        wall_slack=60,
    )
    assert candidate.has_solution
    assert set(candidate.weeks[0].transfers_in.player_id) == {16, 17}
    assert candidate.weeks[0].bank_after_tenths == initial.bank_tenths
    assert candidate.weeks[0].transfer_hit_points == 0
    assert record["solver_calls"] == 1
    assert record["actual"] <= record["cap"] == 3
    assert record["cheap_pair_checks"] <= record["cheap_pair_cap"]


def test_funding_pair_checks_the_package_not_each_individual_purchase():
    horizon, initial, settings, policy, _ = world()
    first = horizon.table.loc[horizon.table.gameweek.eq(1)].set_index("player_id")
    # Selling 14 funds buying 16; selling 15 finances the expensive 17 in the package.
    first.loc[16, "buy_price_tenths"] = 60
    first.loc[17, "buy_price_tenths"] = 40
    initial = replace(initial, bank_tenths=0, free_transfers=2)
    policy = replace(policy, max_transfers_per_gameweek=1, allow_two_free_transfers=True)
    pref = DecisionPreferences()
    assert not pairs.legal_package(first, initial, settings, policy, pref, (14,), (16,))
    assert pairs.legal_package(first, initial, settings, policy, pref, (14, 15), (16, 17))
    assert not pairs.legal_package(
        first, replace(initial, free_transfers=1), settings, policy, pref, (14, 15), (16, 17)
    )


def test_hold_does_not_open_an_optional_solver_call(monkeypatch):
    horizon, initial, settings, policy, plan = world()
    monkeypatch.setattr(pairs, "optimize_transfer_plan", lambda *a, **kw: pytest.fail("solve"))
    candidate, record = pairs.propose_pairs(
        horizon,
        initial,
        settings,
        policy,
        plan.weeks[0],
        (),
        deterministic_slack=3,
        wall_slack=60,
        preferences=DecisionPreferences(hold_transfers=True),
    )
    assert candidate is None
    assert record["solver_calls"] == 0


def test_native_failure_still_counts_as_a_solver_attempt(monkeypatch):
    def fail(*args):
        raise RuntimeError("isolated child failed")

    monkeypatch.setattr(benchmark, "execute_native_window", fail)
    with (
        benchmark.capture_solves() as calls,
        pytest.raises(RuntimeError, match="isolated child failed"),
    ):
        from squadopt.planning.native_highs import _EXECUTOR

        _EXECUTOR.get()({}, 1)
    assert len(calls) == 1
    assert calls[0]["backend"] == "highs-native"
    assert calls[0]["status"] == "ERROR"


def test_restricted_diagnostic_keeps_all_held_players_and_is_order_independent():
    frozen, inputs = next(benchmark.snapshots())
    call = window_call(inputs, min(inputs.members), 3)
    ids = candidate_ids(call, frozen)
    assert set(call.state.squad_player_ids) <= set(ids)
    assert len(ids) <= 39
    from squadopt.planning import PlanningHorizon

    reversed_call = replace(call, horizon=PlanningHorizon(call.horizon.table.iloc[::-1]))
    assert ids == candidate_ids(reversed_call, frozen)


def test_existing_accounting_refusal_is_recorded_without_fabricating_a_gain():
    def refusal():
        raise ValueError("Invalid deterministic-work accounting for expected windows.")

    result = benchmark.timed(refusal, capture_expected_failure=True)
    assert result["solver_status"] == "ERROR"
    assert result["raw_xi_net_points"] is None
    assert result["expected_lineup_net_points"] is None
    assert result["absolute_gap_points"] is None
    assert result["expected_window"]["candidates"] == []
    with pytest.raises(ValueError):
        benchmark.timed(
            lambda: (_ for _ in ()).throw(ValueError("unexpected input")),
            capture_expected_failure=True,
        )


def test_capped_pair_prefix_starts_with_the_highest_disjoint_proxy():
    # The old ascending combination order put the strongest pair beyond the cap.
    moves = [(float(i), 0, i, i + 100) for i in range(1, 33)]
    menu = pairs.package_menu(moves)
    assert menu[: len(moves)] == [(move,) for move in moves]
    brute_best = max(sum(m[0] for m in p) for p in combinations(moves, 2))
    assert sum(m[0] for m in menu[len(moves)]) == brute_best
    assert menu == pairs.package_menu(moves.copy())


def test_summary_keeps_raw_points_scored_net_and_selection_utility_distinct():
    *_, plan = world()
    weeks = tuple(replace(w, lineup_expectation={"expected_net_points": 3.5}) for w in plan.weeks)
    plan = replace(plan, weeks=weeks)
    result = benchmark.summary(plan, 1, [])
    assert result["expected_lineup_net_points"] == 10.5
    assert result["raw_xi_net_points"] == sum(w.projected_score for w in weeks)
    assert result["selection_utility"] is None


@pytest.mark.parametrize("module", [benchmark.expected_window, benchmark.expected_swap, pairs])
def test_accounting_refusal_records_every_imported_alias(module):
    with benchmark.accounting_checks() as checks, pytest.raises(ValueError):
        module.checked_work(3, 1)
    assert checks == [{"actual": 3, "cap": 1}]


def test_pricing_join_reuses_the_completed_result_without_another_solve(monkeypatch, tmp_path):
    from types import SimpleNamespace

    horizon, state, settings, policy, plan = world()
    # A clean CI checkout has no bundled probe or scratch directory. Keep this
    # queue stub isolated from both the checkout and a concurrent measurement.
    monkeypatch.setattr(benchmark, "ROOT", tmp_path)
    (tmp_path / ".codex-tmp").mkdir()
    call = SimpleNamespace(horizon=horizon, state=state, settings=settings, policy=policy)
    request = {"preferences": {}}
    run = {"base": request, "slots": [{"request": request}], "combined": None, "prices": []}
    monkeypatch.setattr(benchmark, "schedule", lambda payload: run)
    executions = []

    def execute(*args, **kwargs):
        executions.append(True)
        return benchmark.summary(plan, 1, [])

    monkeypatch.setattr(benchmark, "timed", execute)

    class Queue:
        def __init__(self, path):
            self.seen = set()

        def submit_unique(self, job):
            identity = job.request_fingerprint
            created = identity not in self.seen
            self.seen.add(identity)
            return job, created

    monkeypatch.setattr(benchmark, "FileJobQueue", Queue)
    result = benchmark.pricing(call, SimpleNamespace(gameweek=1), 1)
    assert len(executions) == result["backend_jobs"] == 1
    assert result["job_requests"] == 2
    assert result["deduplicated_requests"] == 1


def test_missing_appearance_data_cannot_silently_remove_a_held_player():
    frozen, inputs = next(benchmark.snapshots())
    call = window_call(inputs, min(inputs.members), 3)
    projection = dict(frozen["projection"])
    probabilities = dict(projection["appearance_probability"])
    probabilities.pop(str(call.state.squad_player_ids[0]))
    projection["appearance_probability"] = probabilities
    with pytest.raises(ValueError, match="retain every held player"):
        benchmark.expected_comparison(call, {**frozen, "projection": projection})


def test_compact_evidence_keeps_budget_and_thread_disclosures():
    *_, plan = world()
    plan = replace(
        plan,
        diagnostics={
            "solver_deterministic_time_limit": 20,
            "wall_time_limit_seconds": 300,
            "deterministic_time_budget_exhausted": True,
        },
    )
    calls = [{"backend": "cp-sat", "threads": 1}, {"backend": "highs-native", "threads": None}]
    compact = benchmark.compact_plan(benchmark.summary(plan, 1, calls))
    assert compact["solver_limits"]["wall_time_limit_seconds"] == 300
    assert compact["solver_limits"]["deterministic_time_budget_exhausted"] is True
    assert compact["reported_thread_counts"] == [1]
    assert compact["unknown_thread_calls"] == 1
    assert len(compact["decision_sha256"]) == 64
