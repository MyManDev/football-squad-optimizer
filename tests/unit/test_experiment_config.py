"""Tests for the immutable Sprint 2 screening design contract."""

import pytest

from squadopt.experiments import (
    ExperimentCandidate,
    ExperimentConfigurationError,
    PromotionPolicy,
    ScreeningExperimentConfig,
)


def test_default_design_is_the_agreed_four_by_three_factorial() -> None:
    config = ScreeningExperimentConfig()

    assert config.form_windows == (3, 5, 7, 10)
    assert config.bench_weights == (0.0, 0.1, 0.25)
    assert len(config.candidates) == 12
    assert len({candidate.candidate_id for candidate in config.candidates}) == 12
    assert config.control == ExperimentCandidate(5, 0.1)
    assert config.development_seasons == ("2021-22", "2022-23", "2023-24", "2024-25")
    assert config.holdout_seasons == ("2025-26",)


def test_candidate_ids_do_not_expose_binary_float_formatting() -> None:
    assert ExperimentCandidate(3, 0.0).candidate_id == "fw03-bw0"
    assert ExperimentCandidate(10, 0.25).candidate_id == "fw10-bw0p25"


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"development_seasons": ("2025-26",)}, "disjoint"),
        ({"min_prior_gameweeks_in_season": 0}, "excludes opening gameweeks"),
        ({"parallel_candidate_jobs": 0}, "parallel_candidate_jobs"),
        ({"form_windows": (3, 3)}, "unique"),
        ({"bench_weights": (0.1, 0.10)}, "unique"),
        ({"control": ExperimentCandidate(4, 0.1)}, "design cells"),
    ],
)
def test_invalid_designs_are_rejected(changes: dict[str, object], message: str) -> None:
    with pytest.raises(ExperimentConfigurationError, match=message):
        ScreeningExperimentConfig(**changes)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "changes",
    [
        {"min_mean_improvement": -0.1},
        {"confidence_level": 1.0},
        {"bootstrap_resamples": 0},
        {"moving_block_length": 0},
        {"deterministic_seed": -1},
    ],
)
def test_invalid_promotion_policies_are_rejected(changes: dict[str, object]) -> None:
    with pytest.raises(ExperimentConfigurationError):
        PromotionPolicy(**changes)  # type: ignore[arg-type]


def test_configuration_fingerprint_covers_promotion_controls() -> None:
    first = ScreeningExperimentConfig(
        promotion_policy=PromotionPolicy(bootstrap_resamples=100),
    )
    second = ScreeningExperimentConfig(
        promotion_policy=PromotionPolicy(bootstrap_resamples=101),
    )

    assert first.configuration_fingerprint != second.configuration_fingerprint
