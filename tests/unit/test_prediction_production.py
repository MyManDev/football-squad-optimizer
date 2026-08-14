"""Tests for the production projection and its precedence ladder."""

import pandas as pd
import pytest

from squadopt.features import PRIOR_MINUTES_COLUMN, PRIOR_RATE_COLUMN
from squadopt.prediction.config import (
    FITTED_OPENING_PRICE_COEFFICIENT,
    PredictionConfigurationError,
)
from squadopt.prediction.minutes import (
    FIXTURE_COUNT_COLUMN,
    ExpectedMinutesConfig,
)
from squadopt.prediction.production import (
    POINTS_FROM_BLANK_GAMEWEEK,
    POINTS_FROM_PRICE_PRIOR,
    POINTS_FROM_TWO_STAGE,
    RATE_FROM_CARRY_OVER,
    RATE_FROM_HISTORY,
    RATE_UNKNOWN,
    ProductionProjectionConfig,
    expected_points_per_90,
    production_projection,
)

CONFIG = ProductionProjectionConfig(
    rate_window=6,
    carry_over_rate_weight=0.75,
    minutes=ExpectedMinutesConfig(window=6, carry_over_weight=0.75),
)


def _row(
    *,
    rate: object = pd.NA,
    appearance_rate: object = pd.NA,
    minutes_per_appearance: object = pd.NA,
    prior_rate: object = pd.NA,
    prior_minutes: object = pd.NA,
    price_tenths: int = 100,
    fixtures: object = 1,
) -> dict[str, object]:
    return {
        CONFIG.rate_column: rate,
        CONFIG.minutes.appearance_rate_column: appearance_rate,
        CONFIG.minutes.minutes_per_appearance_column: minutes_per_appearance,
        PRIOR_RATE_COLUMN: prior_rate,
        PRIOR_MINUTES_COLUMN: prior_minutes,
        "price_tenths": price_tenths,
        FIXTURE_COUNT_COLUMN: fixtures,
    }


def _frame(rows: list[dict[str, object]]) -> pd.DataFrame:
    return pd.DataFrame(rows)


# --- the product ------------------------------------------------------------


def test_a_full_match_at_a_known_rate_projects_that_rate() -> None:
    projection = production_projection(
        _frame([_row(rate=4.0, appearance_rate=1.0, minutes_per_appearance=90.0)]), config=CONFIG
    )

    assert projection.expected_points.tolist() == [pytest.approx(4.0)]
    assert projection.points_source.tolist() == [POINTS_FROM_TWO_STAGE]


def test_a_double_gameweek_doubles_the_projection() -> None:
    """The calendar is the whole reason the fixture table exists."""

    projection = production_projection(
        _frame(
            [
                _row(rate=4.0, appearance_rate=1.0, minutes_per_appearance=90.0, fixtures=1),
                _row(rate=4.0, appearance_rate=1.0, minutes_per_appearance=90.0, fixtures=2),
            ]
        ),
        config=CONFIG,
    )

    assert projection.expected_points.tolist() == [pytest.approx(4.0), pytest.approx(8.0)]


def test_half_the_minutes_halves_the_projection() -> None:
    projection = production_projection(
        _frame([_row(rate=4.0, appearance_rate=0.5, minutes_per_appearance=90.0)]), config=CONFIG
    )

    assert projection.expected_points.tolist() == [pytest.approx(2.0)]


# --- a projected absence ----------------------------------------------------


def test_an_expected_absence_projects_nothing_without_needing_a_rate() -> None:
    """Requiring a rate here would price a player we expect not to play as if he will."""

    projection = production_projection(
        _frame([_row(appearance_rate=0.0, price_tenths=100)]), config=CONFIG
    )

    assert projection.expected_points.tolist() == [0.0]
    assert projection.points_source.tolist() == [POINTS_FROM_TWO_STAGE]


def test_an_expected_absence_is_not_routed_to_the_price_prior() -> None:
    """The regression this guards: 'we expect nothing' is not 'we know nothing'."""

    projection = production_projection(
        _frame([_row(appearance_rate=0.0, price_tenths=130)]), config=CONFIG
    )

    assert projection.points_source.tolist() != [POINTS_FROM_PRICE_PRIOR]
    assert projection.expected_points.tolist() == [0.0]


def test_a_blank_gameweek_projects_nothing_and_says_so_separately() -> None:
    projection = production_projection(
        _frame([_row(rate=6.0, appearance_rate=1.0, minutes_per_appearance=90.0, fixtures=0)]),
        config=CONFIG,
    )

    assert projection.expected_points.tolist() == [0.0]
    assert projection.points_source.tolist() == [POINTS_FROM_BLANK_GAMEWEEK]


# --- the price prior --------------------------------------------------------


def test_a_player_with_no_record_is_priced_from_price_alone() -> None:
    projection = production_projection(_frame([_row(price_tenths=55)]), config=CONFIG)

    assert projection.expected_points.tolist() == [
        pytest.approx(5.5 * FITTED_OPENING_PRICE_COEFFICIENT)
    ]
    assert projection.points_source.tolist() == [POINTS_FROM_PRICE_PRIOR]


def test_the_prior_is_not_multiplied_by_expected_minutes() -> None:
    """It already accounts for playing time; scaling it again would count it twice."""

    projection = production_projection(_frame([_row(price_tenths=100)]), config=CONFIG)

    assert projection.expected_points.tolist() == [
        pytest.approx(10.0 * FITTED_OPENING_PRICE_COEFFICIENT)
    ]


def test_neither_half_is_invented_for_a_priced_player() -> None:
    projection = production_projection(_frame([_row(price_tenths=55)]), config=CONFIG)

    assert projection.expected_minutes.isna().all()
    assert projection.expected_points_per_90.isna().all()


# --- the rate ladder --------------------------------------------------------


def test_the_current_season_rate_wins() -> None:
    rate, source = expected_points_per_90(_frame([_row(rate=5.0, prior_rate=1.0)]), config=CONFIG)

    assert rate.tolist() == [pytest.approx(5.0)]
    assert source.tolist() == [RATE_FROM_HISTORY]


def test_a_carry_over_rate_is_shrunk() -> None:
    rate, source = expected_points_per_90(_frame([_row(prior_rate=4.0)]), config=CONFIG)

    assert rate.tolist() == [pytest.approx(3.0)]
    assert source.tolist() == [RATE_FROM_CARRY_OVER]


def test_a_player_with_no_rate_anywhere_is_left_missing() -> None:
    rate, source = expected_points_per_90(_frame([_row()]), config=CONFIG)

    assert rate.isna().all()
    assert source.tolist() == [RATE_UNKNOWN]


def test_a_negative_rate_is_clamped() -> None:
    """Realized points can be negative; a projected rate may not be."""

    rate, _ = expected_points_per_90(_frame([_row(rate=-2.0)]), config=CONFIG)

    assert rate.tolist() == [0.0]


def test_a_carry_over_rate_can_carry_a_returning_player() -> None:
    projection = production_projection(
        _frame([_row(prior_rate=4.0, prior_minutes=60.0)]), config=CONFIG
    )

    # minutes 60 * 0.75 = 45, rate 4.0 * 0.75 = 3.0, so 45/90 * 3.0.
    assert projection.expected_points.tolist() == [pytest.approx(1.5)]
    assert projection.points_source.tolist() == [POINTS_FROM_TWO_STAGE]


# --- guarantees -------------------------------------------------------------


def test_expected_points_is_never_missing() -> None:
    projection = production_projection(
        _frame(
            [
                _row(rate=4.0, appearance_rate=1.0, minutes_per_appearance=90.0),
                _row(appearance_rate=0.0),
                _row(prior_rate=3.0, prior_minutes=30.0),
                _row(),
                _row(fixtures=0),
            ]
        ),
        config=CONFIG,
    )

    assert projection.expected_points.notna().all()


def test_expected_points_is_never_negative() -> None:
    projection = production_projection(
        _frame([_row(rate=-5.0, appearance_rate=1.0, minutes_per_appearance=90.0)]), config=CONFIG
    )

    assert (projection.expected_points >= 0.0).all()


def test_every_route_is_reported() -> None:
    projection = production_projection(
        _frame(
            [
                _row(rate=4.0, appearance_rate=1.0, minutes_per_appearance=90.0),
                _row(),
                _row(fixtures=0),
            ]
        ),
        config=CONFIG,
    )

    assert projection.points_source.tolist() == [
        POINTS_FROM_TWO_STAGE,
        POINTS_FROM_PRICE_PRIOR,
        POINTS_FROM_BLANK_GAMEWEEK,
    ]


def test_the_input_frame_is_not_modified() -> None:
    frame = _frame([_row(rate=4.0, appearance_rate=1.0, minutes_per_appearance=90.0)])
    before = frame.copy(deep=True)

    production_projection(frame, config=CONFIG)

    assert frame.equals(before)


def test_the_same_input_projects_identically_twice() -> None:
    frame = _frame([_row(rate=4.0, appearance_rate=0.5, minutes_per_appearance=80.0)])

    first = production_projection(frame, config=CONFIG)
    second = production_projection(frame, config=CONFIG)

    assert first.expected_points.equals(second.expected_points)


# --- input validation -------------------------------------------------------


def test_a_missing_price_is_rejected() -> None:
    """The prior is the only estimate a player with no record has."""

    frame = _frame([_row()])
    frame["price_tenths"] = pd.NA

    with pytest.raises(PredictionConfigurationError, match="price_tenths must be present"):
        production_projection(frame, config=CONFIG)


def test_a_negative_price_is_rejected() -> None:
    with pytest.raises(PredictionConfigurationError, match="non-negative"):
        production_projection(_frame([_row(price_tenths=-10)]), config=CONFIG)


def test_a_missing_rate_column_names_itself() -> None:
    frame = _frame([_row()]).drop(columns=[CONFIG.rate_column])

    with pytest.raises(PredictionConfigurationError, match=CONFIG.rate_column):
        production_projection(frame, config=CONFIG)


def test_an_empty_frame_is_rejected() -> None:
    with pytest.raises(PredictionConfigurationError, match="no rows"):
        production_projection(pd.DataFrame(columns=[CONFIG.rate_column]), config=CONFIG)


def test_the_config_lists_every_column_it_reads() -> None:
    assert CONFIG.required_columns == (
        "points_per_90_last_6",
        "appearance_rate_last_6",
        "minutes_per_appearance_last_6",
        "price_tenths",
    )


@pytest.mark.parametrize("weight", [-0.1, 1.1, float("nan"), True])
def test_an_invalid_carry_over_rate_weight_is_rejected(weight: object) -> None:
    with pytest.raises(PredictionConfigurationError, match="carry_over_rate_weight"):
        ProductionProjectionConfig(carry_over_rate_weight=weight)  # type: ignore[arg-type]


@pytest.mark.parametrize("coefficient", [-0.5, float("inf"), True, "0.3"])
def test_an_invalid_price_coefficient_is_rejected(coefficient: object) -> None:
    with pytest.raises(PredictionConfigurationError, match="opening_price_coefficient"):
        ProductionProjectionConfig(opening_price_coefficient=coefficient)  # type: ignore[arg-type]


def test_the_config_is_immutable() -> None:
    with pytest.raises(AttributeError):
        CONFIG.rate_window = 3  # type: ignore[misc]
