"""Tests for Sprint 4 risk objective and screening configuration."""

import dataclasses

import pytest

from squadopt.risk import (
    RISK_OPTIMIZATION_CONTRACT_VERSION,
    RISK_SCREENING_CONTRACT_VERSION,
    RiskConfigurationError,
    RiskOptimizationConfig,
    RiskScreeningConfig,
)


def test_risk_objective_defaults_to_the_risk_neutral_control() -> None:
    config = RiskOptimizationConfig()

    assert config.risk_aversion == 0.0
    assert config.candidate_id == "risk-0"
    assert config.contract_version == RISK_OPTIMIZATION_CONTRACT_VERSION
    assert len(config.configuration_fingerprint) == 64


@pytest.mark.parametrize("value", [-0.1, 1.1, float("nan"), float("inf"), True, "0.5"])
def test_invalid_risk_aversion_is_rejected(value: object) -> None:
    with pytest.raises(RiskConfigurationError, match="risk_aversion"):
        RiskOptimizationConfig(risk_aversion=value)  # type: ignore[arg-type]


def test_screening_defaults_are_pre_registered_and_development_only() -> None:
    config = RiskScreeningConfig()

    assert config.season_order == ("2021-22", "2022-23", "2023-24", "2024-25")
    assert config.risk_aversion_levels == (0.0, 0.25, 0.5, 1.0)
    assert tuple(candidate.candidate_id for candidate in config.candidates) == (
        "risk-0",
        "risk-0p25",
        "risk-0p5",
        "risk-1",
    )
    assert config.contract_version == RISK_SCREENING_CONTRACT_VERSION
    assert len(config.configuration_fingerprint) == 64


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"season_order": ("s1",)}, "at least two"),
        ({"season_order": ("s1", "s1")}, "unique"),
        ({"risk_aversion_levels": (0.25, 0.5)}, "0.0 control"),
        ({"risk_aversion_levels": (0.0, 0.5, 0.5)}, "unique"),
        ({"downside_quantile": 0.0}, "downside_quantile"),
        ({"uncertainty_confidence_level": 0.0}, "uncertainty_confidence_level"),
        ({"uncertainty_confidence_level": 1.0}, "strictly between"),
        ({"min_pooled_observations": 1}, "at least 2"),
        ({"min_group_observations": 1}, "at least 2"),
        ({"min_prior_gameweeks_in_season": 0}, "at least 1"),
    ],
)
def test_invalid_screening_configuration_is_rejected(
    changes: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(RiskConfigurationError, match=message):
        RiskScreeningConfig(**changes)  # type: ignore[arg-type]


def test_configs_are_frozen_and_fingerprints_cover_controls() -> None:
    first = RiskScreeningConfig(risk_aversion_levels=(0.0, 0.5))
    second = RiskScreeningConfig(risk_aversion_levels=(0.0, 1.0))

    assert first.configuration_fingerprint != second.configuration_fingerprint
    with pytest.raises(dataclasses.FrozenInstanceError):
        first.downside_quantile = 0.2  # type: ignore[misc]
