"""The protocol side of the held free transfer's value computed each week.

What must hold: next week's forecast is this week's per fixture times next week's fixtures;
the computed value is the gain from one more free transfer and never below zero; the arm is the
primary cell's policy arm; and the reading follows the protocol's order.
"""

from squadopt.experiments.component_banked_transfer_value import (
    POLICY_BANKED_VALUE,
    PRIMARY_CELL,
    member_transfer_config,
)
from squadopt.experiments.component_computed_banked_value import (
    COMPUTED_LABEL,
    POLICY_LABEL,
    READING_DIRECTION,
    READING_MOVE,
    READING_UNSUPPORTED,
    SECONDARY_LABELS,
    build_computed_arm,
    computed_reading,
    computed_value,
    next_week_points,
)
from squadopt.optimization import OptimizationConfig

SEASONS = ("2021-22", "2022-23", "2023-24", "2024-25")


def _comparison(mean: float, low: float, high: float, seasons=(5.0, 5.0, 5.0, 5.0)) -> dict:
    return {
        "variant": COMPUTED_LABEL,
        "baseline": POLICY_LABEL,
        "mean_weekly_advantage_points": mean,
        "weekly_advantage_block_bootstrap_interval": [low, high],
        "season_net_advantage_points": dict(zip(SEASONS, seasons, strict=True)),
    }


def _flat() -> dict[str, dict]:
    return {label: _comparison(0.0, -1.0, 1.0) for label in SECONDARY_LABELS}


def test_next_week_points_move_per_fixture():
    moved = next_week_points([4.0, 6.0, 0.2, 5.0], [1, 2, 0, 1], [2, 1, 1, 0])
    assert moved == [8.0, 3.0, 0.2, 0.0]


def test_computed_value_is_the_gain_and_never_negative():
    assert computed_value(61.5, 60.0) == 1.5
    assert computed_value(60.0, 60.5) == 0.0
    assert computed_value(None, 60.0) == 0.0


def test_the_arm_is_the_primary_cells_policy_arm():
    arm = build_computed_arm("2022-23", OptimizationConfig())
    assert arm.label == COMPUTED_LABEL == f"{PRIMARY_CELL[0]}_{PRIMARY_CELL[1]}_bankcomputed"
    assert arm.config.lookahead == 1
    assert arm.config.transfer_config == member_transfer_config(
        "2022-23", PRIMARY_CELL[1], POLICY_BANKED_VALUE
    )


def test_a_passing_primary_reads_move_and_proposes_unless_worse_than_half_a_point():
    verdict = computed_reading(_comparison(2.0, 0.5, 3.5), _flat())
    assert verdict["reading"] == READING_MOVE
    assert verdict["proposes_computed_value"] is True
    worse = _flat()
    worse[SECONDARY_LABELS[0]] = _comparison(-1.0, -2.0, -0.1)
    verdict = computed_reading(_comparison(2.0, 0.5, 3.5), worse)
    assert verdict["secondary"][SECONDARY_LABELS[0]] == "worse"
    assert verdict["proposes_computed_value"] is False


def test_an_interval_above_zero_under_the_floor_reads_direction():
    verdict = computed_reading(_comparison(0.9, 0.1, 1.7), _flat())
    assert verdict["reading"] == READING_DIRECTION
    assert verdict["proposes_computed_value"] is False


def test_nothing_moving_reads_unsupported():
    verdict = computed_reading(_comparison(0.3, -1.0, 1.6, (5.0, -5.0, -5.0, 5.0)), _flat())
    assert verdict["reading"] == READING_UNSUPPORTED
