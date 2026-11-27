"""The protocol side of the held free transfer's value on the component forecast.

What must hold: every arm is the member planning policy with the banked transfer value as
the one control that varies; the 2026-27 rule caps the bank at 5 in every season and the
season rule at each season's own cap; the component cells decide on a supplied forecast and
the control cell on the naive rule; the three readings follow the protocol's order; and a
chain's free-transfer use counts used, paid and lost transfers the way the protocol states.
"""

import pytest

from squadopt.experiments import (
    NAIVE_PROJECTION_RULE,
    SUPPLIED_DECISION_WEEK_PROJECTION_RULE,
    ExperimentConfigurationError,
)
from squadopt.experiments.component_banked_transfer_value import (
    BANKED_VALUE_LEVELS,
    CELLS,
    POLICY_BANKED_VALUE,
    PRIMARY_CELL,
    READING_DIRECTION,
    READING_MOVE,
    READING_UNSUPPORTED,
    RULES_2026_27,
    SEASON_RULES,
    arm_label,
    build_arms,
    comparison_pairs,
    free_transfer_cap,
    free_transfer_use,
    level_tag,
    reading,
)
from squadopt.experiments.component_hit_margin import (
    COMPONENT,
    CONTROL,
    GAME_HIT_CHARGE,
    POLICY_HIT_COST,
)
from squadopt.optimization import OptimizationConfig

SEASONS = ("2021-22", "2022-23", "2023-24", "2024-25")


def _comparison(
    variant: str,
    baseline: str,
    mean: float,
    low: float,
    season_gains: tuple[float, ...] = (10.0, 10.0, 10.0, 10.0),
) -> dict[str, object]:
    return {
        "variant": variant,
        "baseline": baseline,
        "mean_weekly_advantage_points": mean,
        "weekly_advantage_block_bootstrap_interval": [low, mean + (mean - low)],
        "season_net_advantage_points": dict(zip(SEASONS, season_gains, strict=True)),
    }


def _flat(overrides: dict[float, tuple[float, float, tuple[float, ...]]]) -> list[dict]:
    """Every pair at no difference, except primary-cell levels named in ``overrides``."""

    rows = []
    primary = arm_label(*PRIMARY_CELL, POLICY_BANKED_VALUE)
    for variant, baseline in comparison_pairs():
        level = float(variant.rsplit("bank", 1)[1].replace("p", "."))
        if baseline == primary and level in overrides:
            mean, low, seasons = overrides[level]
            rows.append(_comparison(variant, baseline, mean, low, seasons))
        else:
            rows.append(_comparison(variant, baseline, 0.0, -1.0))
    return rows


def test_level_tags_and_labels_are_stable():
    assert [level_tag(v) for v in (0.0, 0.5, 1.2, 6.0)] == ["0", "0p5", "1p2", "6"]
    assert arm_label(COMPONENT, RULES_2026_27, 1.5) == "component_rules_2026_27_bank1p5"
    with pytest.raises(ExperimentConfigurationError):
        level_tag(0.25)
    with pytest.raises(ExperimentConfigurationError):
        arm_label(CONTROL, RULES_2026_27, 1.0)


def test_the_two_rules_cap_the_bank_as_the_protocol_says():
    assert [free_transfer_cap(s, RULES_2026_27) for s in SEASONS] == [5, 5, 5, 5]
    assert [free_transfer_cap(s, SEASON_RULES) for s in SEASONS] == [2, 2, 2, 5]


@pytest.mark.parametrize(("forecast", "rules"), CELLS)
def test_arms_move_only_the_banked_value(forecast, rules):
    arms = build_arms("2022-23", forecast, rules, OptimizationConfig())
    assert [arm.banked_value for arm in arms] == list(BANKED_VALUE_LEVELS)
    expected_rule = (
        SUPPLIED_DECISION_WEEK_PROJECTION_RULE if forecast == COMPONENT else NAIVE_PROJECTION_RULE
    )
    for arm in arms:
        config = arm.config
        transfer = config.transfer_config
        assert config.lookahead == 1
        assert config.chip_windows == ()
        assert config.projection_rule == expected_rule
        assert transfer.banked_transfer_value_points == arm.banked_value
        assert transfer.transfer_hit_cost_points == POLICY_HIT_COST
        assert transfer.hit_points_charged == GAME_HIT_CHARGE
        assert transfer.horizon_discount_factor == 1.0
        assert transfer.max_transfers_per_gameweek is None
        assert transfer.max_free_transfers == free_transfer_cap("2022-23", rules)


def test_every_level_is_compared_with_zero_in_every_cell():
    pairs = comparison_pairs()
    assert len(pairs) == len(CELLS) * (len(BANKED_VALUE_LEVELS) - 1)
    assert all(baseline.endswith("_bank0") for _, baseline in pairs)


def test_no_level_moving_reads_unsupported():
    verdict = reading(_flat({}))
    assert verdict["reading"] == READING_UNSUPPORTED
    assert verdict["named_level"] is None
    assert verdict["changes_a_default"] is False
    assert verdict["intervals_corrected_for_multiplicity"] is False


def test_a_passing_level_reads_move_and_the_best_passing_level_is_named():
    verdict = reading(
        _flat(
            {
                1.0: (1.6, 0.2, (5.0, 5.0, 5.0, -1.0)),
                2.0: (2.1, 0.4, (5.0, 5.0, 5.0, 5.0)),
                6.0: (2.5, -0.1, (5.0, 5.0, 5.0, 5.0)),
            }
        )
    )
    assert verdict["reading"] == READING_MOVE
    assert verdict["named_level"] == 2.0
    assert verdict["primary"]["levels_passing"] == [1.0, 2.0]
    assert verdict["primary"]["highest_pooled_mean_level"] == 6.0
    assert verdict["primary"]["highest_pooled_mean_on_grid_edge"] is True


def test_two_losing_seasons_keep_a_level_from_passing():
    verdict = reading(_flat({1.0: (2.0, 0.5, (5.0, 5.0, -1.0, -1.0))}))
    assert verdict["reading"] == READING_UNSUPPORTED


def test_an_interval_above_zero_under_the_floor_reads_direction():
    verdict = reading(_flat({0.5: (0.9, 0.1, (5.0, 5.0, 5.0, 5.0))}))
    assert verdict["reading"] == READING_DIRECTION
    assert verdict["named_level"] == 0.5


def test_levels_below_zero_are_named_without_deciding():
    verdict = reading(_flat({4.0: (-2.0, -3.0, (-5.0, -5.0, -5.0, -5.0))}))
    assert verdict["reading"] == READING_UNSUPPORTED
    assert verdict["primary"]["levels_with_interval_below_zero"] == [4.0]


def test_free_transfer_use_counts_used_paid_lost_and_held():
    weeks = [
        {"free_transfers_before": 1, "transfer_count": 1, "paid_transfer_count": 0},
        {"free_transfers_before": 1, "transfer_count": 0, "paid_transfer_count": 0},
        {"free_transfers_before": 2, "transfer_count": 0, "paid_transfer_count": 0},
        {"free_transfers_before": 2, "transfer_count": 3, "paid_transfer_count": 1},
    ]
    use = free_transfer_use({"weeks": weeks}, cap=2)
    assert use == {
        "decisions": 4,
        "free_transfers_used": 3,
        "paid_transfers": 1,
        "free_transfers_lost_at_cap": 1,
        "mean_free_transfers_held": 1.5,
        "cap": 2,
    }
    with pytest.raises(ExperimentConfigurationError):
        free_transfer_use({"weeks": []}, cap=5)
