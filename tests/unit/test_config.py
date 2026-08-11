"""Tests for OptimizationConfig."""

from dataclasses import FrozenInstanceError

import pytest

from squadopt import InvalidConfigurationError, OptimizationConfig


def test_default_configuration_matches_sprint_zero_rules() -> None:
    config = OptimizationConfig()

    assert config.budget_tenths == 1000
    assert config.squad_size == 15
    assert dict(config.squad_position_limits) == {"GK": 2, "DEF": 5, "MID": 5, "FWD": 3}
    assert config.starting_size == 11
    assert config.starting_position_min["GK"] == 1
    assert config.starting_position_max["GK"] == 1
    assert config.bench_weight == 0.1
    assert config.expected_points_scale == 1000


def test_configuration_is_frozen_and_copies_mapping_inputs() -> None:
    limits = {"GK": 2, "DEF": 5, "MID": 5, "FWD": 3}
    config = OptimizationConfig(squad_position_limits=limits)
    limits["GK"] = 99

    assert config.squad_position_limits["GK"] == 2
    with pytest.raises(TypeError):
        config.squad_position_limits["GK"] = 3  # type: ignore[index]
    with pytest.raises(FrozenInstanceError):
        config.budget_tenths = 900  # type: ignore[misc]


@pytest.mark.parametrize(
    "kwargs",
    [
        {"squad_size": 14},
        {"budget_tenths": -1},
        {"bench_weight": 1.1},
        {"expected_points_scale": 0},
        {"solver_time_limit_seconds": 0.0},
        {"deterministic_seed": -1},
    ],
)
def test_rejects_invalid_scalar_configuration(kwargs: dict[str, object]) -> None:
    with pytest.raises(InvalidConfigurationError):
        OptimizationConfig(**kwargs)  # type: ignore[arg-type]


def test_rejects_non_exact_starting_goalkeeper_rule() -> None:
    with pytest.raises(InvalidConfigurationError, match="exactly one starting goalkeeper"):
        OptimizationConfig(starting_position_min={"GK": 0, "DEF": 3, "MID": 2, "FWD": 1})
