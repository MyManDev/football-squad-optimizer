"""The protocol side of the hit margin measurement on the component forecast.

What must hold: the arms are the member planning policy with the planning hit cost as the
one thing that varies; the component arm decides on a supplied forecast and the control arm
on the naive rule; the gate needs the noise floor, an interval above zero and at most one
losing season; and the three readings follow the protocol's order, name a candidate only
under ``move``, and say when the best level sits on the edge of the grid.
"""

import pytest

from squadopt.experiments import (
    NAIVE_PROJECTION_RULE,
    SUPPLIED_DECISION_WEEK_PROJECTION_RULE,
    ExperimentConfigurationError,
)
from squadopt.experiments.component_chain import load_component_chain_inputs
from squadopt.experiments.component_hit_margin import (
    COMPONENT,
    CONTROL,
    GAME_HIT_CHARGE,
    HIT_COST_LEVELS,
    POLICY_HIT_COST,
    READING_CONFIRMED,
    READING_MOVE,
    READING_UNSUPPORTED,
    arm_label,
    build_arms,
    comparison_pairs,
    forecast_gap,
    gate,
    reading,
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


def _flat(overrides: dict[tuple[int, int], tuple[float, float]]) -> list[dict[str, object]]:
    """Every component pair at no difference, except the (level, baseline) overrides."""

    rows = []
    for variant, baseline in comparison_pairs():
        if not variant.startswith(COMPONENT):
            continue
        level = int(variant.rsplit("hit", 1)[1])
        base = int(baseline.rsplit("hit", 1)[1])
        mean, low = overrides.get((level, base), (0.0, -1.0))
        rows.append(_comparison(variant, baseline, mean, low))
    return rows


def test_the_grid_brackets_the_policy_and_starts_at_the_game_s_charge() -> None:
    assert HIT_COST_LEVELS == (4, 5, 6, 7, 8, 9, 10, 11, 12)
    assert POLICY_HIT_COST == 8 and GAME_HIT_CHARGE == 4
    assert min(HIT_COST_LEVELS) < POLICY_HIT_COST < max(HIT_COST_LEVELS)


def test_the_arms_are_the_member_policy_with_only_the_planning_cost_varied() -> None:
    arms = build_arms("2023-24", COMPONENT, OptimizationConfig())
    assert [arm.label for arm in arms] == [f"component_hit{c}" for c in HIT_COST_LEVELS]
    for arm in arms:
        config = arm.config
        transfers = config.frozen_transfer_config
        assert config.projection_rule == SUPPLIED_DECISION_WEEK_PROJECTION_RULE
        assert config.lookahead == 1 and not config.chips_enabled
        assert config.hit_points_charged == 4.0 and config.sell_on_fee_halved
        assert transfers.transfer_hit_cost_points == float(arm.hit_cost)
        assert transfers.hit_points_charged == 4.0
        assert transfers.max_transfers_per_gameweek is None
        assert transfers.banked_transfer_value_points == 0.0
        assert transfers.horizon_discount_factor == 1.0
        assert transfers.max_free_transfers == 2
    control = build_arms("2024-25", CONTROL, OptimizationConfig(), hit_costs=(4, 8))
    assert [arm.label for arm in control] == ["control_hit4", "control_hit8"]
    assert all(arm.config.projection_rule == NAIVE_PROJECTION_RULE for arm in control)
    assert control[0].config.frozen_transfer_config.max_free_transfers == 5


def test_a_pilot_stops_the_walk_early_and_an_unknown_forecast_is_refused() -> None:
    arms = build_arms("2024-25", COMPONENT, OptimizationConfig(), end_gameweek=6)
    assert all(arm.config.end_gameweek == 6 for arm in arms)
    with pytest.raises(ExperimentConfigurationError, match="forecast"):
        build_arms("2024-25", "ridge", OptimizationConfig())
    with pytest.raises(ExperimentConfigurationError, match="forecast"):
        arm_label("ridge", 8)
    with pytest.raises(ExperimentConfigurationError, match="hit_costs"):
        build_arms("2024-25", COMPONENT, OptimizationConfig(), hit_costs=(8, 8))


def test_the_pairs_are_every_level_against_the_policy_and_against_the_charge() -> None:
    pairs = comparison_pairs()
    component = [pair for pair in pairs if pair[0].startswith(COMPONENT)]
    against_policy = [v for v, b in component if b == "component_hit8"]
    against_charge = [v for v, b in component if b == "component_hit4"]
    assert against_policy == [f"component_hit{c}" for c in (5, 6, 7, 9, 10, 11, 12)]
    assert against_charge == [f"component_hit{c}" for c in (5, 6, 7, 8, 9, 10, 11, 12)]
    assert len(pairs) == 2 * len(component) and len(set(pairs)) == len(pairs)
    assert all(variant.split("_")[0] == baseline.split("_")[0] for variant, baseline in pairs)


def test_the_gate_needs_the_floor_the_interval_and_the_seasons() -> None:
    passing = gate(_comparison("component_hit10", "component_hit8", 1.8, 0.3, (9, 9, -2, 9)))
    assert passing["passed"] and passing["losing_seasons"] == ["2023-24"]
    under_floor = gate(_comparison("component_hit10", "component_hit8", 1.4, 0.3))
    assert not under_floor["passed"] and not under_floor["clears_noise_floor"]
    touching_zero = gate(_comparison("component_hit10", "component_hit8", 2.0, 0.0))
    assert not touching_zero["passed"] and not touching_zero["interval_excludes_zero"]
    two_losing = gate(_comparison("component_hit10", "component_hit8", 2.0, 0.5, (9, -1, -2, 9)))
    assert not two_losing["passed"] and not two_losing["at_most_one_losing_season"]
    assert gate(None) == {"available": False, "passed": False}


def test_move_names_the_passing_level_with_the_highest_mean() -> None:
    result = reading(_flat({(6, 8): (1.6, 0.2), (5, 8): (2.1, 0.4), (8, 4): (3.0, 1.0)}))
    assert result["reading"] == READING_MOVE
    assert result["candidate_hit_cost"] == 5
    assert result["levels_passing_against_policy"] == [5, 6]
    assert result["highest_pooled_mean_level"] == 5
    assert result["highest_pooled_mean_on_grid_edge"] is False
    assert result["changes_a_default"] is False


def test_a_tie_between_passing_levels_goes_to_the_one_nearer_the_policy() -> None:
    result = reading(_flat({(5, 8): (2.0, 0.4), (10, 8): (2.0, 0.4)}))
    assert result["reading"] == READING_MOVE and result["candidate_hit_cost"] == 10


def test_confirmed_needs_no_level_past_the_policy_and_the_policy_past_the_charge() -> None:
    result = reading(_flat({(8, 4): (2.2, 0.6), (9, 8): (0.4, -0.5)}))
    assert result["reading"] == READING_CONFIRMED
    assert result["candidate_hit_cost"] is None
    assert result["levels_passing_against_policy"] == []
    assert result["highest_pooled_mean_level"] == 9


def test_unsupported_when_neither_holds_and_an_edge_optimum_is_said() -> None:
    result = reading(_flat({(12, 8): (1.2, -0.1), (8, 4): (0.9, -0.4)}))
    assert result["reading"] == READING_UNSUPPORTED
    assert result["candidate_hit_cost"] is None
    assert result["highest_pooled_mean_level"] == 12
    assert result["highest_pooled_mean_on_grid_edge"] is True


def test_the_policy_itself_is_the_best_level_when_nothing_beats_it() -> None:
    result = reading(_flat({(8, 4): (2.2, 0.6), (9, 8): (-0.4, -1.5), (7, 8): (-0.2, -1.0)}))
    assert result["highest_pooled_mean_level"] == POLICY_HIT_COST
    assert result["highest_pooled_mean_on_grid_edge"] is False


def test_the_forecast_gap_is_projected_minus_realized_per_decision() -> None:
    record = {
        "weeks": [
            {"projected_points": 60.0, "realized_points": 50.0},
            {"projected_points": 58.0, "realized_points": 62.0},
        ]
    }
    gap = forecast_gap(record)
    assert gap["decisions"] == 2
    assert gap["mean_projected_points"] == 59.0 and gap["mean_realized_points"] == 56.0
    assert gap["mean_projected_minus_realized"] == 3.0
    with pytest.raises(ExperimentConfigurationError, match="weeks"):
        forecast_gap({"weeks": []})


def test_the_composer_refuses_the_locked_season_before_it_opens_a_file(tmp_path: object) -> None:
    with pytest.raises(ExperimentConfigurationError, match="locked holdout"):
        load_component_chain_inputs(
            tmp_path,  # type: ignore[arg-type]
            None,  # type: ignore[arg-type]
            seasons=("2024-25", "2025-26"),
        )
    with pytest.raises(ExperimentConfigurationError, match="once"):
        load_component_chain_inputs(
            tmp_path,  # type: ignore[arg-type]
            None,  # type: ignore[arg-type]
            seasons=("2024-25", "2024-25"),
        )
