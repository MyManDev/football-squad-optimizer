"""Tests for the deterministic control component models.

These estimators are a reference, so what is pinned is not their accuracy but their
contract: which rows they refuse to be fitted on, which bounds their output respects, where
a missing component stays missing, and that the same input twice gives the same numbers.
"""

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

from squadopt.features.component_targets import build_component_targets
from squadopt.prediction.component_dataset import (
    build_component_frame,
    component_feature_columns,
    rows_at,
    rows_strictly_before,
)
from squadopt.prediction.component_models import (
    COMPONENT_MODEL_VERSION,
    COMPONENT_PREDICTION_COLUMNS,
    MINUTES_PER_FIXTURE,
    ComponentModelConfig,
    complete_feature_rows,
    fit_component_models,
    predict_components,
)
from squadopt.prediction.components import COMPONENT_MODEL_ROUTE, DIRECT_CONTROL_ROUTE
from squadopt.prediction.config import PredictionConfigurationError

FEATURES = component_feature_columns()
SEASON = "2024-25"
SEASON_ORDER = (SEASON,)
# Small enough to keep the synthetic frames readable, and the default is asserted
# separately by its own test.
SMALL = ComponentModelConfig(minimum_training_rows=10)


def _frame(gameweeks: int, players: int, *, fixture_count: int = 1) -> pd.DataFrame:
    """A joined modelling frame with a real, simple signal.

    A player's index drives both his form and his outcomes, so the estimators have
    something to fit rather than noise. Every feature is present, so every row is a
    ``component_model`` row unless a test removes one.
    """

    rows = []
    for gameweek in range(1, gameweeks + 1):
        for player in range(1, players + 1):
            plays = (player + gameweek) % 5 != 0
            rows.append(
                {
                    "season": SEASON,
                    "gameweek": gameweek,
                    "player_id": player,
                    "minutes": 90 * fixture_count if plays else 0,
                    "total_points": (2 + player % 4) * fixture_count if plays else 0,
                    "form": float(player % 7),
                }
            )
    raw = pd.DataFrame(rows)
    panel = pd.DataFrame(
        {
            "season": raw["season"].astype("string"),
            "gameweek": raw["gameweek"].astype("int64"),
            "player_id": raw["player_id"].astype("int64"),
            "name": ("P" + raw["player_id"].astype(str)).astype("string"),
            "team_id": pd.Series(1, index=raw.index, dtype="int64"),
            "position": pd.Series("MID", index=raw.index, dtype="string"),
            "price_tenths": (40 + raw["player_id"]).astype("int64"),
            "minutes": raw["minutes"].astype("int64"),
            "total_points": raw["total_points"].astype("int64"),
        }
    )
    features = panel.loc[:, ["season", "gameweek", "player_id", "price_tenths"]].copy(deep=True)
    for offset, column in enumerate(FEATURES, start=1):
        if column == "price_tenths":
            continue
        if column in ("fixture_count", "home_fixture_count"):
            features[column] = pd.Series(fixture_count, index=raw.index, dtype="int64")
        else:
            features[column] = (raw["form"] * offset + raw["gameweek"]).astype("float64")
    return build_component_frame(features, build_component_targets(panel))


def _fitted(frame: pd.DataFrame) -> object:
    return fit_component_models(frame, feature_columns=FEATURES, config=SMALL)


# --- refusals ---------------------------------------------------------------


def test_too_little_history_is_a_refusal_not_a_guess() -> None:
    """`None` is the refusal the caller records; a ridge on a handful of rows is worse."""

    assert fit_component_models(_frame(2, 3), feature_columns=FEATURES, config=SMALL) is None


def test_the_default_row_minimum_guards_a_realistic_frame() -> None:
    """The default is asserted so a change to it cannot pass unnoticed."""

    assert ComponentModelConfig().minimum_training_rows == 200
    assert fit_component_models(_frame(4, 10), feature_columns=FEATURES) is None


def test_a_single_class_fold_cannot_produce_a_probability() -> None:
    """Every player appeared, so there is no non-appearance to estimate against."""

    frame = _frame(6, 10)
    always = frame.assign(
        appearance_target=pd.Series(1, index=frame.index, dtype="Int64"),
    )

    assert fit_component_models(always, feature_columns=FEATURES, config=SMALL) is None


def test_predicting_with_columns_the_models_were_not_fitted_on_is_refused() -> None:
    frame = _frame(8, 20)
    models = _fitted(frame)
    assert models is not None

    with pytest.raises(PredictionConfigurationError, match="another model"):
        predict_components(models, frame, feature_columns=tuple(reversed(FEATURES)))


def test_a_scoring_frame_without_a_fixture_count_is_refused() -> None:
    """The minutes bound is taken against the calendar, so it cannot be assumed."""

    frame = _frame(8, 20)
    models = _fitted(frame)

    with pytest.raises(PredictionConfigurationError, match="fixture_count"):
        predict_components(models, frame.drop(columns=["fixture_count"]), feature_columns=FEATURES)


# --- bounds -----------------------------------------------------------------


def test_probabilities_lie_in_the_unit_interval() -> None:
    frame = _frame(8, 20)
    models = _fitted(frame)

    predicted = predict_components(models, frame, feature_columns=FEATURES)

    probability = predicted["appearance_probability"].dropna()
    assert bool(probability.between(0.0, 1.0).all())


def test_conditional_minutes_respect_the_calendar_ceiling() -> None:
    """A double gameweek raises the ceiling to 180; a single one holds it at 90."""

    for fixtures in (1, 2):
        frame = _frame(8, 20, fixture_count=fixtures)
        models = _fitted(frame)

        predicted = predict_components(models, frame, feature_columns=FEATURES)

        minutes = predicted["expected_minutes_if_appearance"].dropna()
        assert bool(minutes.between(0.0, MINUTES_PER_FIXTURE * fixtures).all())


def test_the_public_expected_points_is_non_negative_and_the_raw_value_is_kept() -> None:
    """`prediction.components` refuses a negative composition, so the clip happens here.

    The unclipped conditional value survives beside it, because a negative ridge estimate
    is a diagnostic about the model and deleting it would hide the one place the clip did
    any work.
    """

    frame = _frame(8, 20)
    models = _fitted(frame)

    predicted = predict_components(models, frame, feature_columns=FEATURES)

    assert bool((predicted["expected_points_if_appearance"].dropna() >= 0.0).all())
    assert bool((predicted["control_expected_points"].dropna() >= 0.0).all())
    assert "raw_expected_points_if_appearance" in predicted.columns


def test_a_blank_gameweek_overrides_history_with_zero() -> None:
    """Historical form cannot override a known empty calendar."""

    frame = _frame(8, 20)
    models = _fitted(frame)
    blank = frame.assign(fixture_count=pd.Series(0, index=frame.index, dtype="int64"))

    predicted = predict_components(models, blank, feature_columns=FEATURES)

    assert predicted["appearance_probability"].tolist() == [0.0] * len(blank)
    assert predicted["expected_minutes_if_appearance"].tolist() == [0.0] * len(blank)
    assert predicted["control_expected_points"].tolist() == [0.0] * len(blank)


# --- missingness and routes -------------------------------------------------


def test_both_halves_of_the_start_component_are_missing_rather_than_zero() -> None:
    """The label does not exist and the admissible model is conditional, so neither exists.

    Both are named rather than absent, so a consumer meets an explicit missing value
    instead of a missing column -- the evaluation side asked for exactly that.
    """

    frame = _frame(8, 20)
    models = _fitted(frame)

    predicted = predict_components(models, frame, feature_columns=FEATURES)

    assert bool(predicted["q_start_given_appearance"].isna().all())
    assert bool(predicted["start_probability"].isna().all())


def test_a_blank_gameweek_leaves_the_start_component_missing_not_zero() -> None:
    """The calendar override zeroes what exists; it cannot zero what is unavailable.

    A conditional start probability given no appearance is undefined rather than zero, and
    writing 0.0 here would make the column mean "evaluated to zero" on blank rows and
    "unavailable" everywhere else -- one column, two meanings, told apart only by
    fixture_count.
    """

    frame = _frame(8, 20)
    models = _fitted(frame)
    blank = frame.assign(fixture_count=pd.Series(0, index=frame.index, dtype="int64"))

    predicted = predict_components(models, blank, feature_columns=FEATURES)

    assert predicted["appearance_probability"].tolist() == [0.0] * len(blank)
    assert bool(predicted["q_start_given_appearance"].isna().all())
    assert bool(predicted["start_probability"].isna().all())


def test_a_row_missing_a_feature_gets_no_component_prediction_and_says_so() -> None:
    """Half a composition is not a prediction, and a zero-filled feature is not a feature."""

    frame = _frame(8, 20)
    models = _fitted(frame)
    holed = frame.copy(deep=True)
    holed.loc[holed.index[0], "points_last_5"] = pd.NA

    predicted = predict_components(models, holed, feature_columns=FEATURES)

    first = predicted.iloc[0]
    assert first["composition_route"] == DIRECT_CONTROL_ROUTE
    assert pd.isna(first["appearance_probability"])
    assert pd.isna(first["control_expected_points"])
    assert predicted["composition_route"].iloc[1] == COMPONENT_MODEL_ROUTE


def test_without_models_every_row_takes_the_fallback_route() -> None:
    frame = _frame(8, 20)

    predicted = predict_components(None, frame, feature_columns=FEATURES)

    assert predicted["composition_route"].unique().tolist() == [DIRECT_CONTROL_ROUTE]
    assert bool(predicted["control_expected_points"].isna().all())


def test_complete_feature_rows_reports_which_rows_are_modellable() -> None:
    frame = _frame(4, 5)
    holed = frame.copy(deep=True)
    holed.loc[holed.index[2], "minutes_last_3"] = pd.NA

    complete = complete_feature_rows(holed, FEATURES)

    assert not bool(complete.iloc[2])
    assert int(complete.sum()) == len(holed) - 1


# --- determinism and the out-of-fold boundary -------------------------------


def test_the_same_input_twice_gives_the_same_predictions() -> None:
    frame = _frame(8, 20)

    first = predict_components(_fitted(frame), frame, feature_columns=FEATURES)
    second = predict_components(_fitted(frame), frame, feature_columns=FEATURES)

    assert_frame_equal(first, second)
    assert COMPONENT_MODEL_VERSION == "phase_c_control_components_v1"


def test_an_out_of_fold_row_is_never_in_its_own_training_slice() -> None:
    """The property the whole out-of-fold table rests on, asserted on keys rather than
    inferred from a metric."""

    frame = _frame(10, 20)
    training = rows_strictly_before(frame, season_order=SEASON_ORDER, season=SEASON, gameweek=6)
    scoring = rows_at(frame, season=SEASON, gameweek=6)

    keys = ["season", "gameweek", "player_id"]
    overlap = training.merge(scoring.loc[:, keys], on=keys, how="inner")

    assert overlap.empty
    assert training["gameweek"].max() == 5


def test_predicting_does_not_modify_the_scoring_frame() -> None:
    frame = _frame(8, 20)
    models = _fitted(frame)
    before = frame.copy(deep=True)

    predict_components(models, frame, feature_columns=FEATURES)

    assert_frame_equal(frame, before)


def test_the_prediction_columns_are_the_declared_ones() -> None:
    frame = _frame(8, 20)

    predicted = predict_components(_fitted(frame), frame, feature_columns=FEATURES)

    assert tuple(predicted.columns) == COMPONENT_PREDICTION_COLUMNS
