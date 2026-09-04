"""Tests for the expected-minutes stage.

Feature values are supplied directly rather than built from a panel, so each rung of
the precedence ladder can be exercised in isolation.
"""

import numpy as np
import pandas as pd
import pytest

from squadopt.features import MINUTES_PER_FULL_MATCH, PRIOR_MINUTES_COLUMN
from squadopt.prediction.config import PredictionConfigurationError
from squadopt.prediction.minutes import (
    FIXTURE_COUNT_COLUMN,
    MINUTES_BLANK_GAMEWEEK,
    MINUTES_FROM_CARRY_OVER,
    MINUTES_FROM_HISTORY,
    MINUTES_FROM_NO_APPEARANCE,
    MINUTES_UNKNOWN,
    ExpectedMinutesConfig,
    appearance_probability,
    expected_minutes,
)

CONFIG = ExpectedMinutesConfig(window=6, carry_over_weight=0.75)


def _features(rows: list[dict[str, object]]) -> pd.DataFrame:
    frame = pd.DataFrame(rows)
    for column in (
        CONFIG.appearance_rate_column,
        CONFIG.minutes_per_appearance_column,
        PRIOR_MINUTES_COLUMN,
    ):
        if column not in frame.columns:
            frame[column] = pd.NA
    return frame


def _row(
    rate: object = pd.NA,
    per_appearance: object = pd.NA,
    prior: object = pd.NA,
) -> dict[str, object]:
    return {
        CONFIG.appearance_rate_column: rate,
        CONFIG.minutes_per_appearance_column: per_appearance,
        PRIOR_MINUTES_COLUMN: prior,
    }


# --- appearance probability -------------------------------------------------


def test_appearance_probability_preserves_history_zero_and_missing() -> None:
    frame = _features([_row(0.75), _row(0.0), _row()])
    before = frame.copy(deep=True)

    probability = appearance_probability(frame, config=CONFIG)

    assert probability.iloc[:2].tolist() == [0.75, 0.0]
    assert pd.isna(probability.iloc[2])
    assert probability.index.equals(frame.index)
    assert frame.equals(before)


def test_appearance_probability_uses_the_calendar_only_as_a_blank_override() -> None:
    probability = appearance_probability(
        _with_fixtures([_row(0.75), _row(0.75)], [0, 2]),
        config=CONFIG,
    )

    assert probability.tolist() == [0.0, 0.75]


@pytest.mark.parametrize("value", [-0.01, 1.01, float("inf"), "unknown", True])
def test_appearance_probability_rejects_values_outside_its_contract(value: object) -> None:
    with pytest.raises(PredictionConfigurationError, match=r"probabilities in \[0, 1\]"):
        appearance_probability(_features([_row(value)]), config=CONFIG)


def test_appearance_probability_rejects_duplicate_source_columns() -> None:
    frame = _features([_row(0.75)])
    duplicated = pd.concat([frame, frame[[CONFIG.appearance_rate_column]]], axis="columns")

    with pytest.raises(PredictionConfigurationError, match="duplicate"):
        appearance_probability(duplicated, config=CONFIG)


# --- the measured rung ------------------------------------------------------


def test_history_multiplies_how_often_by_how_long() -> None:
    projection = expected_minutes(_features([_row(0.5, 80.0)]), config=CONFIG)

    assert projection.expected_minutes.tolist() == [40.0]
    assert projection.source.tolist() == [MINUTES_FROM_HISTORY]


def test_two_players_with_equal_minutes_averages_can_differ() -> None:
    """Rotation risk and early substitution are different, and this separates them."""

    projection = expected_minutes(_features([_row(2 / 3, 90.0), _row(1.0, 60.0)]), config=CONFIG)

    assert projection.expected_minutes.tolist() == [pytest.approx(60.0), pytest.approx(60.0)]
    # Same estimate here by construction, but from different observed behaviour.
    assert projection.source.tolist() == [MINUTES_FROM_HISTORY, MINUTES_FROM_HISTORY]


def test_the_estimate_never_exceeds_one_match() -> None:
    """The product of two estimates can, and a player cannot."""

    projection = expected_minutes(_features([_row(1.0, 120.0)]), config=CONFIG)

    assert projection.expected_minutes.tolist() == [float(MINUTES_PER_FULL_MATCH)]


def test_history_wins_over_carry_over() -> None:
    projection = expected_minutes(_features([_row(0.5, 80.0, prior=90.0)]), config=CONFIG)

    assert projection.expected_minutes.tolist() == [40.0]
    assert projection.source.tolist() == [MINUTES_FROM_HISTORY]


# --- the observed-absence rung ----------------------------------------------


def test_a_player_who_featured_in_none_of_the_window_projects_to_zero() -> None:
    """A measurement, not a gap: collapsing it into the fallback would discard it."""

    projection = expected_minutes(_features([_row(0.0, pd.NA)]), config=CONFIG)

    assert projection.expected_minutes.tolist() == [0.0]
    assert projection.source.tolist() == [MINUTES_FROM_NO_APPEARANCE]


def test_an_observed_absence_wins_over_carry_over() -> None:
    projection = expected_minutes(_features([_row(0.0, pd.NA, prior=90.0)]), config=CONFIG)

    assert projection.expected_minutes.tolist() == [0.0]
    assert projection.source.tolist() == [MINUTES_FROM_NO_APPEARANCE]


# --- the carry-over rung ----------------------------------------------------


def test_carry_over_is_shrunk_rather_than_projected_forward_unchanged() -> None:
    """He has not been picked this season, and last season may no longer describe him."""

    projection = expected_minutes(_features([_row(prior=80.0)]), config=CONFIG)

    assert projection.expected_minutes.tolist() == [pytest.approx(60.0)]
    assert projection.source.tolist() == [MINUTES_FROM_CARRY_OVER]


def test_carry_over_is_also_clipped_to_one_match() -> None:
    projection = expected_minutes(
        _features([_row(prior=200.0)]),
        config=ExpectedMinutesConfig(window=6, carry_over_weight=1.0),
    )

    assert projection.expected_minutes.tolist() == [float(MINUTES_PER_FULL_MATCH)]


def test_a_missing_carry_over_column_is_tolerated() -> None:
    """A caller working within one season never attaches it."""

    frame = pd.DataFrame(
        [
            {
                CONFIG.appearance_rate_column: 0.5,
                CONFIG.minutes_per_appearance_column: 80.0,
            }
        ]
    )

    projection = expected_minutes(frame, config=CONFIG)

    assert projection.expected_minutes.tolist() == [40.0]


# --- the empty rung ---------------------------------------------------------


def test_a_player_with_no_record_is_left_missing_for_the_points_stage() -> None:
    """A price prior estimates points directly; there is no per-90 to multiply."""

    projection = expected_minutes(_features([_row()]), config=CONFIG)

    assert projection.expected_minutes.isna().all()
    assert projection.source.tolist() == [MINUTES_UNKNOWN]


def test_a_rate_without_a_duration_falls_through_to_the_lower_rung() -> None:
    """An appearance rate above zero with no duration cannot form a product."""

    projection = expected_minutes(_features([_row(0.5, pd.NA, prior=40.0)]), config=CONFIG)

    assert projection.expected_minutes.tolist() == [pytest.approx(30.0)]
    assert projection.source.tolist() == [MINUTES_FROM_CARRY_OVER]


# --- precedence across a mixed roster ---------------------------------------


def test_every_rung_can_fire_within_one_roster() -> None:
    projection = expected_minutes(
        _features(
            [
                _row(0.5, 80.0),
                _row(0.0, pd.NA),
                _row(prior=40.0),
                _row(),
            ]
        ),
        config=CONFIG,
    )

    assert projection.source.tolist() == [
        MINUTES_FROM_HISTORY,
        MINUTES_FROM_NO_APPEARANCE,
        MINUTES_FROM_CARRY_OVER,
        MINUTES_UNKNOWN,
    ]
    assert projection.expected_minutes.tolist()[:3] == [40.0, 0.0, pytest.approx(30.0)]
    assert pd.isna(projection.expected_minutes.iloc[3])


def test_the_input_frame_is_not_modified() -> None:
    frame = _features([_row(0.5, 80.0)])
    before = frame.copy(deep=True)

    expected_minutes(frame, config=CONFIG)

    assert frame.equals(before)


def test_the_result_is_never_negative() -> None:
    projection = expected_minutes(_features([_row(prior=-10.0)]), config=CONFIG)

    assert projection.expected_minutes.tolist() == [0.0]


# --- configuration ----------------------------------------------------------


def test_the_config_names_the_columns_it_reads() -> None:
    config = ExpectedMinutesConfig(window=4)

    assert config.required_columns == (
        "appearance_rate_last_4",
        "minutes_per_appearance_last_4",
    )


def test_a_missing_feature_column_names_itself() -> None:
    frame = pd.DataFrame([{CONFIG.appearance_rate_column: 0.5}])

    with pytest.raises(PredictionConfigurationError, match="minutes_per_appearance_last_6"):
        expected_minutes(frame, config=CONFIG)


@pytest.mark.parametrize("window", [0, -1, 1.5, True, "6"])
def test_an_invalid_window_is_rejected(window: object) -> None:
    with pytest.raises(PredictionConfigurationError, match="window must"):
        ExpectedMinutesConfig(window=window)  # type: ignore[arg-type]


@pytest.mark.parametrize("weight", [-0.1, 1.1, float("nan"), True, "0.5"])
def test_an_invalid_carry_over_weight_is_rejected(weight: object) -> None:
    with pytest.raises(PredictionConfigurationError, match="carry_over_weight must"):
        ExpectedMinutesConfig(carry_over_weight=weight)  # type: ignore[arg-type]


def test_the_config_is_immutable() -> None:
    config = ExpectedMinutesConfig()

    with pytest.raises(AttributeError):
        config.window = 3  # type: ignore[misc]


# --- the calendar -----------------------------------------------------------


def _with_fixtures(rows: list[dict[str, object]], counts: list[object]) -> pd.DataFrame:
    frame = _features(rows)
    frame[FIXTURE_COUNT_COLUMN] = counts
    return frame


def test_a_double_gameweek_offers_twice_the_minutes() -> None:
    """The panel sums minutes across a gameweek's fixtures, so the cap doubles too."""

    projection = expected_minutes(
        _with_fixtures([_row(1.0, 90.0), _row(1.0, 90.0)], [1, 2]), config=CONFIG
    )

    assert projection.expected_minutes.tolist() == [90.0, 180.0]


def test_the_cap_scales_with_the_fixture_count() -> None:
    projection = expected_minutes(
        _with_fixtures([_row(1.0, 200.0), _row(1.0, 200.0)], [1, 2]), config=CONFIG
    )

    assert projection.expected_minutes.tolist() == [
        float(MINUTES_PER_FULL_MATCH),
        2 * float(MINUTES_PER_FULL_MATCH),
    ]


def test_a_blank_gameweek_projects_to_zero_whatever_the_history_says() -> None:
    """History cannot override an empty calendar."""

    projection = expected_minutes(_with_fixtures([_row(1.0, 90.0)], [0]), config=CONFIG)

    assert projection.expected_minutes.tolist() == [0.0]
    assert projection.source.tolist() == [MINUTES_BLANK_GAMEWEEK]


def test_a_missing_fixture_count_uses_the_documented_single_fixture_default() -> None:
    probability = appearance_probability(
        _with_fixtures([_row(0.75)], [pd.NA]),
        config=CONFIG,
    )

    assert probability.tolist() == [0.75]


@pytest.mark.parametrize("count", ["unknown", True, np.bool_(False), 1.5, float("inf")])
def test_an_invalid_fixture_count_is_rejected(count: object) -> None:
    with pytest.raises(PredictionConfigurationError, match="integer fixture counts"):
        appearance_probability(
            _with_fixtures([_row(0.75)], [count]),
            config=CONFIG,
        )


def test_a_blank_gameweek_overrides_even_a_missing_record() -> None:
    projection = expected_minutes(_with_fixtures([_row()], [0]), config=CONFIG)

    assert projection.expected_minutes.tolist() == [0.0]
    assert projection.source.tolist() == [MINUTES_BLANK_GAMEWEEK]


def test_carry_over_is_scaled_by_the_calendar_too() -> None:
    projection = expected_minutes(_with_fixtures([_row(prior=40.0)], [2]), config=CONFIG)

    assert projection.expected_minutes.tolist() == [pytest.approx(60.0)]


def test_a_missing_calendar_assumes_one_fixture() -> None:
    """Absence of a calendar is not evidence of an empty one."""

    without = expected_minutes(_features([_row(1.0, 90.0)]), config=CONFIG)
    single = expected_minutes(_with_fixtures([_row(1.0, 90.0)], [1]), config=CONFIG)

    assert without.expected_minutes.tolist() == single.expected_minutes.tolist()


def test_a_missing_fixture_count_value_assumes_one_fixture() -> None:
    projection = expected_minutes(_with_fixtures([_row(1.0, 90.0)], [pd.NA]), config=CONFIG)

    assert projection.expected_minutes.tolist() == [90.0]
    assert projection.source.tolist() == [MINUTES_FROM_HISTORY]


def test_a_negative_fixture_count_is_rejected() -> None:
    with pytest.raises(PredictionConfigurationError, match="may not be negative"):
        expected_minutes(_with_fixtures([_row(1.0, 90.0)], [-1]), config=CONFIG)
