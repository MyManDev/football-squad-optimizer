"""Tests for the learned scoring rate, the one component Issue #43 changes.

The declaration's whole value is that exactly one thing moved. So the tests here spend
most of their effort on what must *not* have moved: the cold-start ladder's shape, the
set of rows each rung covers, and the declared input list. A candidate that quietly
scores rows the old stage left missing is a different candidate, however good its
numbers look.
"""

import numpy as np
import pandas as pd
import pytest

from squadopt.features.config import (
    minutes_per_appearance_feature_name,
    per_90_feature_name,
    rolling_feature_name,
)
from squadopt.prediction.config import PredictionConfigurationError
from squadopt.prediction.learned_rate import (
    CALENDAR_INPUT_COLUMNS,
    RATE_FROM_LEARNED_MODEL,
    LearnedRateConfig,
    LearnedRateModel,
    fit_learned_rate,
    learned_points_per_90,
    rate_input_columns,
    realized_points_per_90,
)

WINDOW = 6
PRIOR_RATE_COLUMN = "prior_seasons_points_per_90"
CARRY_WEIGHT = 0.75


def _training(rows: int = 800, *, seed: int = 0) -> pd.DataFrame:
    """Deterministic training rows with a genuine signal in the declared inputs."""

    generator = np.random.default_rng(seed)
    per_90 = generator.uniform(0.0, 8.0, rows)
    appearance = generator.uniform(0.0, 1.0, rows)
    minutes_per_appearance = generator.uniform(10.0, 90.0, rows)
    fixtures = generator.integers(1, 3, rows).astype("float64")
    home = np.minimum(fixtures, generator.integers(0, 2, rows).astype("float64"))
    minutes = np.clip(appearance * minutes_per_appearance * fixtures, 1.0, 190.0)
    # A rate that genuinely depends on the declared inputs, so a fitted model has
    # something to find and a broken fit shows up as a bad prediction.
    rate = 0.6 * per_90 + 1.4 * appearance + 0.2 * fixtures
    points = rate * minutes / 90.0
    return pd.DataFrame(
        {
            per_90_feature_name(WINDOW): per_90,
            rolling_feature_name("appeared", WINDOW): appearance,
            minutes_per_appearance_feature_name(WINDOW): minutes_per_appearance,
            "fixture_count": fixtures,
            "home_fixture_count": home,
            "minutes": minutes,
            "total_points": points,
        }
    )


def _model(**kwargs: object) -> LearnedRateModel:
    return fit_learned_rate(_training(**kwargs), config=LearnedRateConfig(window=WINDOW))


# --- the declared input list ------------------------------------------------


def test_the_inputs_are_exactly_the_declared_list() -> None:
    """A silently widened input list is a different candidate than the one declared."""

    assert rate_input_columns(WINDOW) == (
        "points_per_90_last_6",
        "appearance_rate_last_6",
        "minutes_per_appearance_last_6",
        "fixture_count",
        "home_fixture_count",
    )


def test_the_calendar_inputs_are_named_rather_than_derived() -> None:
    assert CALENDAR_INPUT_COLUMNS == ("fixture_count", "home_fixture_count")


def test_the_window_selects_the_same_frozen_features_the_old_stage_read() -> None:
    assert rate_input_columns(10)[0] == per_90_feature_name(10)


def test_a_feature_dataset_missing_a_declared_input_is_refused() -> None:
    training = _training().drop(columns=["fixture_count"])

    with pytest.raises(PredictionConfigurationError, match="fixture_count"):
        fit_learned_rate(training, config=LearnedRateConfig(window=WINDOW))


# --- the training target ----------------------------------------------------


def test_the_target_is_missing_where_nobody_played() -> None:
    """Filling a benched row with zero would teach selection, not scoring."""

    frame = pd.DataFrame({"minutes": [90.0, 0.0, 45.0], "total_points": [6.0, 0.0, 2.0]})

    rate = realized_points_per_90(frame)

    assert rate.isna().tolist() == [False, True, False]


def test_the_target_is_points_scaled_to_ninety_minutes() -> None:
    frame = pd.DataFrame({"minutes": [45.0], "total_points": [3.0]})

    assert realized_points_per_90(frame).iloc[0] == pytest.approx(6.0)


def test_a_negative_outcome_survives_into_the_target() -> None:
    """Red cards and own goals are real; clipping the target would hide them."""

    frame = pd.DataFrame({"minutes": [90.0], "total_points": [-2.0]})

    assert realized_points_per_90(frame).iloc[0] == pytest.approx(-2.0)


def test_training_rows_without_minutes_are_refused() -> None:
    with pytest.raises(PredictionConfigurationError, match="minutes"):
        realized_points_per_90(pd.DataFrame({"total_points": [1.0]}))


# --- the fit ----------------------------------------------------------------


def test_the_fit_is_deterministic() -> None:
    """No seed, no iteration count, no solver choice to drift between environments."""

    first, second = _model(), _model()

    assert first.coefficients == second.coefficients
    assert first.intercept == second.intercept
    assert first.model_fingerprint == second.model_fingerprint


def test_the_fit_recovers_a_signal_present_in_the_declared_inputs() -> None:
    model = _model()
    training = _training()

    predicted = model.predict(training)
    actual = realized_points_per_90(training)

    assert float(np.corrcoef(predicted, actual)[0, 1]) > 0.9


def test_too_little_history_is_refused_rather_than_fitted() -> None:
    """A model fitted on forty rows would be reported as confidently as one on a season."""

    with pytest.raises(PredictionConfigurationError, match="at least"):
        fit_learned_rate(
            _training(rows=40), config=LearnedRateConfig(window=WINDOW, min_training_rows=500)
        )


def test_rows_with_an_incomplete_input_do_not_enter_the_fit() -> None:
    training = _training()
    training.loc[training.index[:100], "fixture_count"] = float("nan")

    model = fit_learned_rate(training, config=LearnedRateConfig(window=WINDOW))

    assert model.training_rows == len(training) - 100
    assert model.diagnostics["training_rows_offered"] == len(training)


def test_a_constant_input_does_not_divide_by_zero() -> None:
    training = _training().assign(home_fixture_count=1.0)

    model = fit_learned_rate(training, config=LearnedRateConfig(window=WINDOW))

    assert all(np.isfinite(model.coefficients))
    assert len(model.input_columns) == len(rate_input_columns(WINDOW))


def test_two_different_fits_have_different_fingerprints() -> None:
    assert _model(seed=0).model_fingerprint != _model(seed=1).model_fingerprint


# --- the ladder, which must not move ----------------------------------------


def _features(**overrides: object) -> pd.DataFrame:
    columns = rate_input_columns(WINDOW)
    base = {column: [1.0, 1.0, 1.0] for column in columns}
    base[PRIOR_RATE_COLUMN] = [float("nan"), 4.0, 4.0]
    frame = pd.DataFrame(base)
    for name, value in overrides.items():
        frame[name] = value
    return frame


def _rate(features: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    return learned_points_per_90(
        features,
        _model(),
        config=LearnedRateConfig(window=WINDOW),
        carry_over_rate_weight=CARRY_WEIGHT,
        prior_rate_column=PRIOR_RATE_COLUMN,
    )


def test_a_row_with_in_season_history_is_scored_by_the_model() -> None:
    _, source = _rate(_features())

    assert source.iloc[0] == RATE_FROM_LEARNED_MODEL


def test_a_row_without_in_season_history_falls_to_the_shrunk_carry_over() -> None:
    """The rung below the model is untouched, shrinkage weight included."""

    features = _features()
    features.loc[1, per_90_feature_name(WINDOW)] = float("nan")

    values, source = _rate(features)

    assert source.iloc[1] == "carry_over"
    assert values.iloc[1] == pytest.approx(4.0 * CARRY_WEIGHT)


def test_a_row_with_neither_history_nor_carry_over_stays_missing() -> None:
    """A price prior estimates points, not a rate; inventing one fabricates a factor."""

    features = _features()
    features.loc[0, per_90_feature_name(WINDOW)] = float("nan")

    values, source = _rate(features)

    assert bool(pd.isna(values.iloc[0]))
    assert source.iloc[0] == "unknown"


def test_a_row_missing_a_calendar_input_is_not_scored_by_the_model() -> None:
    """Imputing would answer confidently from a value nobody measured."""

    features = _features()
    features.loc[1, "fixture_count"] = float("nan")

    values, source = _rate(features)

    assert source.iloc[1] == "carry_over"
    assert values.iloc[1] == pytest.approx(4.0 * CARRY_WEIGHT)


def test_the_modelled_rate_is_never_negative() -> None:
    features = _features()
    features[per_90_feature_name(WINDOW)] = -50.0

    values, _ = _rate(features)

    assert float(values.min()) >= 0.0


def test_a_model_reading_other_inputs_than_the_config_is_refused() -> None:
    features = _features()

    with pytest.raises(PredictionConfigurationError, match="different inputs"):
        learned_points_per_90(
            features,
            _model(),
            config=LearnedRateConfig(window=WINDOW + 1),
            carry_over_rate_weight=CARRY_WEIGHT,
            prior_rate_column=PRIOR_RATE_COLUMN,
        )


# --- configuration ----------------------------------------------------------


@pytest.mark.parametrize("window", [0, -1, True])
def test_an_invalid_window_is_refused(window: object) -> None:
    with pytest.raises(PredictionConfigurationError, match="window"):
        LearnedRateConfig(window=window)  # type: ignore[arg-type]


@pytest.mark.parametrize("alpha", [0.0, -1.0, float("inf")])
def test_an_invalid_ridge_alpha_is_refused(alpha: float) -> None:
    with pytest.raises(PredictionConfigurationError, match="ridge_alpha"):
        LearnedRateConfig(ridge_alpha=alpha)


def test_a_model_with_mismatched_widths_is_refused() -> None:
    with pytest.raises(PredictionConfigurationError, match="one value per input column"):
        LearnedRateModel(
            input_columns=("a", "b"),
            means=(0.0,),
            scales=(1.0, 1.0),
            coefficients=(1.0, 1.0),
            intercept=0.0,
            training_rows=10,
            ridge_alpha=1.0,
        )
