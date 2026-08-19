"""Tests for mapping experiment factors into prediction-pipeline controls."""

import pytest

from squadopt.features import FeatureConfigurationError
from squadopt.prediction import (
    BASELINE_FORM_WINDOW,
    FEATURE_GENERATION_CONTRACT_VERSION,
    FormWindowMapping,
)


def test_form_window_controls_every_baseline_form_lookback() -> None:
    mapping = FormWindowMapping(form_window=7)

    assert mapping.feature_config.minutes_windows == (7,)
    assert mapping.feature_config.points_windows == (7,)
    assert mapping.feature_config.per_90_window == 7
    assert mapping.projection_config.minutes_window == 7
    assert mapping.projection_config.per_90_window == 7


def test_minimum_history_policy_is_a_fixed_control() -> None:
    assert FormWindowMapping(form_window=3).feature_config.min_periods == 1


def test_the_declared_baseline_is_five_completed_matches() -> None:
    assert BASELINE_FORM_WINDOW == 5
    assert FormWindowMapping().form_window == 5


def test_the_mapping_has_a_stable_contract_version() -> None:
    assert FEATURE_GENERATION_CONTRACT_VERSION == "form_window_v1"


@pytest.mark.parametrize("value", [True, 0, -1, 3.5, "5"])
def test_invalid_form_windows_are_rejected(value: object) -> None:
    with pytest.raises(FeatureConfigurationError, match="form_window"):
        FormWindowMapping(form_window=value)  # type: ignore[arg-type]
