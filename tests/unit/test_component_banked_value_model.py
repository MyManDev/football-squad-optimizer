"""The Bellman model of a carried free transfer's value.

What must hold: an opportunity is the marginal value of each free transfer, never negative;
the value function is zero after the last decision and adds nothing past the cap; the
marginal values fall with each transfer carried when opportunities shrink; a decision picks
the highest objective plus carried value and ties to fewer moves; and the readings follow the
protocol.
"""

import pytest

from squadopt.evaluation.promotion import ExperimentConfigurationError
from squadopt.experiments.component_banked_value_model import (
    MODEL_LABEL,
    OWNER_LABEL,
    POLICY_LABEL,
    bellman_values,
    best_choice,
    marginal_values,
    model_reading,
    opportunity,
)

SEASONS = ("2021-22", "2022-23", "2023-24", "2024-25")


def _comparison(baseline: str, mean: float, low: float, high: float) -> dict[str, object]:
    return {
        "variant": MODEL_LABEL,
        "baseline": baseline,
        "mean_weekly_advantage_points": mean,
        "weekly_advantage_block_bootstrap_interval": [low, high],
        "season_net_advantage_points": dict.fromkeys(SEASONS, mean),
    }


def test_an_opportunity_is_each_free_transfers_marginal_value():
    assert opportunity([10.0, 12.0, 12.5, 12.4]) == (2.0, 0.5, 0.0)
    with pytest.raises(ExperimentConfigurationError):
        opportunity([10.0])


def test_the_last_decision_carries_nothing_and_the_cap_adds_nothing():
    values = bellman_values([1, 2, 3], [(2.0, 1.0, 0.5)], cap=3)
    assert values[3] == (0.0, 0.0, 0.0, 0.0)
    # One week left: V(b) is the best use of b free transfers that week.
    assert values[2] == pytest.approx((0.0, 2.0, 3.0, 3.5))
    assert marginal_values(values[2]) == pytest.approx((1.0, 0.5))


def test_values_fall_with_each_transfer_carried_and_towards_the_seasons_end():
    samples = [(3.0, 1.0, 0.2), (0.0, 0.0, 0.0), (1.0, 0.5, 0.0)]
    values = bellman_values(list(range(1, 11)), samples, cap=3)
    for gameweek in range(1, 10):
        first, second = marginal_values(values[gameweek])
        assert first >= second >= 0.0
    assert marginal_values(values[1])[0] >= marginal_values(values[9])[0]


def test_a_decision_takes_the_best_total_and_ties_to_fewer_moves():
    row = (0.0, 0.0, 1.0, 1.5)
    # Hold carries 2 (worth 1.0); one move gains 0.8 and carries 1.
    assert best_choice([(None, 50.0, 2), (1, 50.8, 1)], row) == 0
    # A move worth 1.2 beats carrying.
    assert best_choice([(None, 50.0, 2), (1, 51.2, 1)], row) == 1
    # A tie goes to the hold.
    assert best_choice([(None, 50.0, 2), (1, 51.0, 1)], row) == 0


def test_the_readings_follow_the_protocol():
    better = model_reading(
        _comparison(OWNER_LABEL, 0.6, 0.1, 1.1),
        _comparison(POLICY_LABEL, 2.0, 0.5, 3.5),
        _comparison(OWNER_LABEL, 0.0, -1.0, 1.0),
    )
    assert better["primary_against_1.12"] == "better"
    assert better["against_0_gate_passed"] is True
    assert better["proposal"] == "replace_the_constant_with_the_model"
    unclear = model_reading(
        _comparison(OWNER_LABEL, 0.1, -1.0, 1.2),
        _comparison(POLICY_LABEL, 0.3, -1.0, 1.6),
        _comparison(OWNER_LABEL, -2.0, -3.0, -0.5),
    )
    assert unclear["primary_against_1.12"] == "not_separable"
    assert unclear["against_0.5"] == "worse"
    assert unclear["proposal"] == "owner_chooses"
