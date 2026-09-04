"""Tests for the shared integer-coefficient experiment contract."""

from dataclasses import replace

import pandas as pd
from pandas.testing import assert_frame_equal

from squadopt import OptimizationConfig
from squadopt.optimization import objective_coefficient_fingerprint
from squadopt.optimization.coefficients import (
    objective_coefficients,
    scale_bench_coefficient,
    scale_expected_points,
)


def test_shared_scaling_uses_decimal_round_half_up() -> None:
    assert scale_expected_points("1.2345", 1000) == 1235
    assert scale_expected_points("1.2344", 1000) == 1234
    assert scale_bench_coefficient(5, 0.1) == 1
    assert scale_bench_coefficient(4, 0.1) == 0


def test_objective_coefficients_match_the_model_algebra() -> None:
    config = OptimizationConfig(bench_weight=0.1, expected_points_scale=10)

    assert objective_coefficients([1.0, 0.5], config) == (
        (1, 9, 10),
        (1, 4, 5),
    )


def test_fingerprint_is_order_independent_and_does_not_mutate_input(
    baseline_players: pd.DataFrame,
) -> None:
    original = baseline_players.copy(deep=True)
    shuffled = baseline_players.sample(frac=1.0, random_state=7).reset_index(drop=True)
    config = OptimizationConfig()

    first = objective_coefficient_fingerprint(baseline_players, config)
    second = objective_coefficient_fingerprint(shuffled, config)

    assert first == second
    assert len(first) == 64
    assert_frame_equal(baseline_players, original)


def test_fingerprint_changes_when_effective_model_input_changes(
    baseline_players: pd.DataFrame,
) -> None:
    config = OptimizationConfig()
    changed = baseline_players.copy(deep=True)
    changed.loc[0, "price_tenths"] += 1

    assert objective_coefficient_fingerprint(
        baseline_players, config
    ) != objective_coefficient_fingerprint(changed, config)
    assert objective_coefficient_fingerprint(
        baseline_players, config
    ) != objective_coefficient_fingerprint(
        baseline_players,
        replace(config, bench_weight=0.25),
    )
