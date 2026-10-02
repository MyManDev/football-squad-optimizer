"""Scenario comparison reports solved values without invented information timing."""

import pytest

from squadopt.planning.policy_comparison import PolicyComparisonInput, compare_completed_policies


def policy(values, *, moves=0, bank=15, ft=2, chip=None):
    return PolicyComparisonInput(
        dict(zip(("available", "unavailable"), values, strict=True)), moves, chip, bank, ft
    )


def test_crossing_scenarios_are_not_called_dominant_or_guaranteed_gains():
    result = compare_completed_policies(
        [policy((100, 80)), policy((110, 70), moves=1, bank=0, ft=1)], basis="expected_own_points"
    )
    hold, move = result["candidates"]
    assert result["news_arrival_probability"] is None
    assert result["terminal_resource_value_added"] is False
    assert hold["action_kind"] == "hold"
    assert move["action_kind"] == "move"
    assert hold["first_state"] == {"bank_tenths": 15, "free_transfers": 2}
    assert move["scenario_min"] == 70 and move["scenario_max"] == 110
    assert move["branch_gaps_vs_baseline"] == {"available": 10, "unavailable": -10}
    assert move["minimum_gap_vs_baseline"] == -10
    assert not move["dominates_baseline"] and not hold["dominated_by"]


def test_weak_componentwise_improvement_with_one_strict_gain_dominates():
    result = compare_completed_policies(
        [policy((100, 80)), policy((100, 81), chip="3xc"), policy((100, 80))],
        basis="selection_utility",
    )
    baseline, improved, tied = result["candidates"]
    assert improved["action_kind"] == "chip" and improved["dominates_baseline"]
    assert baseline["dominated_by"] == tied["dominated_by"] == [1]
    assert not tied["dominates_baseline"]


def test_incomplete_scenario_menu_is_refused():
    with pytest.raises(ValueError, match="same finite"):
        compare_completed_policies(
            [policy((10, 20)), PolicyComparisonInput({"available": 11}, 0, None, 0, 0)],
            basis="own_points",
        )
