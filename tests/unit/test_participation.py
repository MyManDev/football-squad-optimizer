"""The conditional start estimator, and the three states it composes into.

Every test is offline and synthetic. What is asserted is not that the model is accurate --
that is the calibration record's job, on the declared population -- but that it refuses when
it should, that it never manufactures a probability for a row it cannot score, and that the
state algebra the standing contract fixes holds without a repair step.
"""

import numpy as np
import pandas as pd
import pytest

from squadopt.prediction.config import PredictionConfigurationError
from squadopt.prediction.participation import (
    TEAM_STRENGTH_COLUMN,
    ParticipationModelConfig,
    attach_team_strength,
    fit_start_model,
    participation_states,
    predict_start_given_appearance,
    start_feature_columns,
)

FEATURES = ("minutes_last_3", "appearance_rate_last_3")


def _training(rows: int, *, labelled: bool = True, single_class: bool = False) -> pd.DataFrame:
    """Appeared rows with a separable signal, so a fit is possible when it is allowed."""

    generator = np.random.default_rng(11)
    minutes = generator.uniform(0.0, 90.0, size=rows)
    rate = generator.uniform(0.0, 1.0, size=rows)
    started = np.where(single_class, 1, (minutes > 45.0).astype("int64"))
    return pd.DataFrame(
        {
            "season": pd.Series(["2023-24"] * rows, dtype="string"),
            "gameweek": pd.Series(np.arange(rows) % 38 + 1, dtype="int64"),
            "player_id": pd.Series(np.arange(rows), dtype="int64"),
            "minutes_last_3": minutes,
            "appearance_rate_last_3": rate,
            "appearance_target": pd.Series([1] * rows, dtype="Int64"),
            "start_target": pd.Series(started if labelled else [pd.NA] * rows, dtype="Int64"),
        }
    )


# --- what the fit refuses ---------------------------------------------------


def test_a_population_below_the_declared_floor_is_refused() -> None:
    """A probability fitted on a handful of rows is worse than an honest absence."""

    assert fit_start_model(_training(50), feature_columns=FEATURES) is None


def test_a_single_class_population_is_refused_rather_than_made_constant() -> None:
    """Everyone starting cannot produce a probability, and a constant would look like one."""

    training = _training(600, single_class=True)

    assert fit_start_model(training, feature_columns=FEATURES) is None


def test_unlabelled_rows_are_not_trained_on() -> None:
    """The declared population is what may be fitted; an appeared row outside it is not."""

    assert fit_start_model(_training(600, labelled=False), feature_columns=FEATURES) is None


def test_rows_that_did_not_appear_are_not_trained_on() -> None:
    """`q` is conditional on appearing, so a non-appearance row answers another question."""

    training = _training(600)
    training.loc[training.index[:400], "appearance_target"] = 1
    training.loc[training.index[400:], "appearance_target"] = 0

    model = fit_start_model(training, feature_columns=FEATURES)

    assert model is not None
    assert model.training_rows == 400


def test_a_bad_configuration_is_refused_before_anything_is_fitted() -> None:
    with pytest.raises(PredictionConfigurationError):
        ParticipationModelConfig(regularization=0.0)
    with pytest.raises(PredictionConfigurationError):
        ParticipationModelConfig(minimum_training_rows=0)


# --- what the fit produces --------------------------------------------------


def test_a_fitted_model_scores_within_the_unit_interval() -> None:
    """`q` is a probability; the composition below relies on it staying one."""

    model = fit_start_model(_training(600), feature_columns=FEATURES)
    assert model is not None

    conditional = predict_start_given_appearance(model, _training(120), feature_columns=FEATURES)

    assert bool(conditional.notna().all())
    assert float(conditional.min()) >= 0.0
    assert float(conditional.max()) <= 1.0


def test_a_row_the_design_cannot_score_is_absent_rather_than_zero() -> None:
    """A zero would say he is certain not to start, which nothing measured."""

    model = fit_start_model(_training(600), feature_columns=FEATURES)
    assert model is not None
    scoring = _training(10)
    scoring.loc[scoring.index[0], "minutes_last_3"] = np.nan

    conditional = predict_start_given_appearance(model, scoring, feature_columns=FEATURES)

    assert conditional.iloc[0] is pd.NA
    assert bool(conditional.iloc[1:].notna().all())


def test_no_model_means_no_probability_at_all() -> None:
    """The refusal survives to the caller as absence, not as a default."""

    conditional = predict_start_given_appearance(None, _training(5), feature_columns=FEATURES)

    assert bool(conditional.isna().all())


# --- the three states -------------------------------------------------------


def test_the_states_sum_to_one_and_start_never_exceeds_appearance() -> None:
    """The structural requirement, met by algebra rather than by clipping."""

    appearance = pd.Series([0.0, 0.25, 0.9, 1.0], dtype="Float64")
    conditional = pd.Series([0.5, 0.0, 0.75, 1.0], dtype="Float64")

    states = participation_states(appearance, conditional)

    assert float((states.sum(axis=1, skipna=False) - 1.0).abs().max()) == pytest.approx(0.0)
    assert bool((states["p_start"].to_numpy() <= appearance.to_numpy()).all())
    assert float(states.to_numpy(dtype="float64").min()) >= 0.0


def test_a_missing_half_makes_all_three_missing() -> None:
    """Filling one from the other would state a split nobody estimated."""

    states = participation_states(
        pd.Series([0.8, pd.NA], dtype="Float64"), pd.Series([pd.NA, 0.4], dtype="Float64")
    )

    assert bool(states.isna().all(axis=None))


# --- the team-strength control ----------------------------------------------


def test_team_strength_is_one_number_per_club_and_gameweek() -> None:
    """A club's form is a property of the club, not of each of its players."""

    frame = pd.DataFrame(
        {
            "season": pd.Series(["2023-24"] * 6, dtype="string"),
            "team_id": pd.Series(["A", "A", "B", "A", "A", "B"], dtype="string"),
            "gameweek": pd.Series([1, 1, 1, 2, 2, 2], dtype="int64"),
            "total_points": pd.Series([2.0, 6.0, 5.0, 1.0, 3.0, 9.0], dtype="float64"),
        }
    )

    attached = attach_team_strength(frame, window=3)
    second = attached.loc[attached["gameweek"] == 2]

    club_a = second.loc[second["team_id"] == "A", TEAM_STRENGTH_COLUMN]
    assert club_a.nunique() == 1
    # Club A scored 8 in gameweek one, and gameweek two sees only what preceded it.
    assert float(club_a.iloc[0]) == pytest.approx(8.0)


def test_the_first_gameweek_has_no_earlier_form_to_average() -> None:
    """Shifted by construction, so a gameweek can never enter its own feature."""

    frame = pd.DataFrame(
        {
            "season": pd.Series(["2023-24", "2023-24"], dtype="string"),
            "team_id": pd.Series(["A", "A"], dtype="string"),
            "gameweek": pd.Series([1, 2], dtype="int64"),
            "total_points": pd.Series([4.0, 7.0], dtype="float64"),
        }
    )

    attached = attach_team_strength(frame, window=3)

    assert bool(pd.isna(attached.loc[attached["gameweek"] == 1, TEAM_STRENGTH_COLUMN].iloc[0]))


def test_a_frame_without_the_team_columns_is_refused() -> None:
    """Named columns, named refusal: the control is not silently skipped."""

    with pytest.raises(PredictionConfigurationError, match="Team strength needs"):
        attach_team_strength(pd.DataFrame({"season": pd.Series([], dtype="string")}))


def test_the_control_joins_the_design_once() -> None:
    """Calling twice must not produce two copies of one control."""

    assert start_feature_columns(FEATURES)[-1] == TEAM_STRENGTH_COLUMN
    assert start_feature_columns(start_feature_columns(FEATURES)) == start_feature_columns(FEATURES)
