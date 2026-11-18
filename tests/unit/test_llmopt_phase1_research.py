"""Research accounting, frozen population and full-resource package validation."""

from dataclasses import replace

import pytest
from docs.research.llmopt_phase1 import benchmark, pairs
from docs.research.llmopt_phase1.freeze import digest
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
            "expected_lineup_window": {"chosen": "legacy_proposal"},
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
