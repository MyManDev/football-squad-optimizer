"""Tests for the versioned Sprint 3 uncertainty configuration."""

import dataclasses

import pytest

from squadopt.uncertainty import (
    PROJECTION_UNCERTAINTY_CONTRACT_VERSION,
    UncertaintyConfig,
    UncertaintyConfigurationError,
)


def test_defaults_define_the_locked_sprint3_split() -> None:
    config = UncertaintyConfig()

    assert config.confidence_level == 0.9
    assert config.development_seasons == (
        "2021-22",
        "2022-23",
        "2023-24",
        "2024-25",
    )
    assert config.holdout_season == "2025-26"
    assert config.contract_version == PROJECTION_UNCERTAINTY_CONTRACT_VERSION


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"confidence_level": 0.0}, "strictly between"),
        ({"confidence_level": 1.0}, "strictly between"),
        ({"confidence_level": float("nan")}, "strictly between"),
        ({"confidence_level": 10**1000}, "finite number"),
        ({"confidence_level": True}, "finite number"),
        ({"development_seasons": ()}, "non-empty tuple"),
        ({"development_seasons": ("d1", "d1")}, "unique"),
        ({"development_seasons": ("h1",), "holdout_season": "h1"}, "disjoint"),
        ({"min_pooled_observations": 1}, "at least 2"),
        ({"min_group_observations": 1}, "at least 2"),
        ({"contract_version": "future"}, "implemented"),
    ],
)
def test_invalid_configuration_is_rejected(changes: dict[str, object], message: str) -> None:
    with pytest.raises(UncertaintyConfigurationError, match=message):
        UncertaintyConfig(**changes)  # type: ignore[arg-type]


def test_configuration_fingerprint_covers_calibration_controls() -> None:
    first = UncertaintyConfig(confidence_level=0.8)
    second = UncertaintyConfig(confidence_level=0.9)

    assert first.configuration_fingerprint != second.configuration_fingerprint
    assert len(first.configuration_fingerprint) == 64


def test_configuration_is_immutable() -> None:
    config = UncertaintyConfig()

    with pytest.raises(dataclasses.FrozenInstanceError):
        config.confidence_level = 0.8  # type: ignore[misc]
