"""Tests for the declared season-age weighting of the Phase C component estimators.

What is pinned is the weighting contract, not a number: the rule halves per season of
age, the weights are normalized to a mean of one inside each fitted subset, they reach
the scaler and the estimator alike, the equal-weight control is untouched, a row from
after the prediction season is a refusal, and a weighted fit says what it is.
"""

import numpy as np
import pandas as pd
import pytest
from pandas.testing import assert_frame_equal
from sklearn.linear_model import LogisticRegression, Ridge  # type: ignore[import-untyped]
from sklearn.pipeline import make_pipeline  # type: ignore[import-untyped]
from sklearn.preprocessing import StandardScaler  # type: ignore[import-untyped]

from squadopt.features.component_targets import build_component_targets
from squadopt.prediction.component_dataset import (
    build_component_frame,
    component_feature_columns,
    rows_at,
    rows_strictly_before,
)
from squadopt.prediction.component_models import (
    COMPONENT_MODEL_VERSION,
    EQUAL_WEIGHTING,
    SEASON_HALF_LIFE_WEIGHTING,
    SEASON_WEIGHT_BASE,
    SEASON_WEIGHTED_MODEL_VERSION,
    ComponentModelConfig,
    SeasonAgeWeighting,
    fit_component_models,
    normalize_weights,
    predict_components,
    season_age_weights,
    season_start_year,
)
from squadopt.prediction.config import PredictionConfigurationError

FEATURES = component_feature_columns()
SMALL = ComponentModelConfig(minimum_training_rows=10)
OLD = "2023-24"
NEW = "2024-25"
LATER = "2025-26"
FORM_FEATURE = "points_last_3"


def _panel(
    season: str, gameweeks: int, players: int, *, intercept: int, slope: int
) -> pd.DataFrame:
    """A canonical panel whose points follow ``intercept + slope * form`` when appearing."""

    rows = []
    for gameweek in range(1, gameweeks + 1):
        for player in range(1, players + 1):
            plays = (player + gameweek) % 5 != 0
            form = player % 7
            rows.append(
                (
                    season,
                    gameweek,
                    player,
                    90 if plays else 0,
                    intercept + slope * form if plays else 0,
                )
            )
    raw = pd.DataFrame(rows, columns=["season", "gameweek", "player_id", "minutes", "total_points"])
    return pd.DataFrame(
        {
            "season": raw["season"].astype("string"),
            "gameweek": raw["gameweek"].astype("int64"),
            "player_id": raw["player_id"].astype("int64"),
            "name": ("P" + raw["player_id"].astype(str)).astype("string"),
            "team_id": pd.Series(1, index=raw.index, dtype="int64"),
            "position": pd.Series("MID", index=raw.index, dtype="string"),
            "price_tenths": (40 + raw["player_id"] % 5).astype("int64"),
            "minutes": raw["minutes"].astype("int64"),
            "total_points": raw["total_points"].astype("int64"),
        }
    )


def _frame(*panels: pd.DataFrame) -> pd.DataFrame:
    """A joined modelling frame whose ``points_last_3`` feature is each player's form."""

    panel = pd.concat(panels, ignore_index=True)
    features = panel.loc[:, ["season", "gameweek", "player_id", "price_tenths"]].copy(deep=True)
    for column in FEATURES:
        if column == "price_tenths":
            continue
        if column == "fixture_count":
            features[column] = (1 + (panel["player_id"] % 4 == 0)).astype("int64")
        elif column == "home_fixture_count":
            features[column] = (panel["player_id"] % 2).astype("int64")
        elif column == FORM_FEATURE:
            features[column] = (panel["player_id"] % 7).astype("float64")
        else:
            features[column] = (panel["player_id"] % 3 + panel["gameweek"]).astype("float64")
    return build_component_frame(features, build_component_targets(panel))


def _two_seasons() -> pd.DataFrame:
    return _frame(
        _panel(OLD, 8, 20, intercept=1, slope=1),
        _panel(NEW, 8, 20, intercept=9, slope=-1),
    )


@pytest.mark.parametrize(
    ("season", "year"), [("2025-26", 2025), ("2021-22", 2021), ("1999-00", 1999)]
)
def test_season_start_year_parses_canonical_labels(season: str, year: int) -> None:
    assert season_start_year(season) == year


@pytest.mark.parametrize("season", ["2025-27", "25-26", "2025/26", "2025-26 ", None, 2025])
def test_season_start_year_refuses_anything_but_a_canonical_label(season: object) -> None:
    with pytest.raises(PredictionConfigurationError):
        season_start_year(season)


def test_the_rule_halves_per_season_of_age() -> None:
    rule = SeasonAgeWeighting(target_season=LATER)
    seasons = pd.Series([LATER, NEW, OLD, NEW], index=[10, 20, 30, 40], dtype="string")

    weights = season_age_weights(seasons, weighting=rule)

    assert SEASON_WEIGHT_BASE == 0.5
    assert weights.tolist() == [1.0, 0.5, 0.25, 0.5]
    assert weights.index.tolist() == [10, 20, 30, 40]
    assert rule.label == SEASON_HALF_LIFE_WEIGHTING
    assert rule.model_version == SEASON_WEIGHTED_MODEL_VERSION


def test_a_row_from_after_the_prediction_season_is_a_leak_not_a_weight() -> None:
    rule = SeasonAgeWeighting(target_season=NEW)

    with pytest.raises(PredictionConfigurationError, match="leak"):
        season_age_weights(pd.Series([NEW, LATER], dtype="string"), weighting=rule)


def test_a_missing_season_label_cannot_be_weighted() -> None:
    rule = SeasonAgeWeighting(target_season=NEW)

    with pytest.raises(PredictionConfigurationError, match="season label"):
        season_age_weights(pd.Series([NEW, pd.NA], dtype="string"), weighting=rule)


def test_normalized_weights_have_mean_one_over_exactly_the_rows_given() -> None:
    normalized = normalize_weights(pd.Series([1.0, 0.5, 0.25, 0.25]))

    assert normalized.mean() == pytest.approx(1.0)
    assert normalized.tolist() == pytest.approx([2.0, 1.0, 0.5, 0.5])


@pytest.mark.parametrize("weights", [[1.0, 0.0], [1.0, -1.0], [1.0, float("nan")], []])
def test_non_positive_or_missing_weights_are_refused(weights: list[float]) -> None:
    with pytest.raises(PredictionConfigurationError):
        normalize_weights(pd.Series(weights, dtype="float64"))


def test_the_equal_weight_control_is_unchanged_and_names_itself() -> None:
    frame = _frame(_panel(NEW, 8, 20, intercept=9, slope=-1))
    training = rows_strictly_before(frame, season_order=(NEW,), season=NEW, gameweek=6)
    scoring = rows_at(frame, season=NEW, gameweek=6)

    control = fit_component_models(training, feature_columns=FEATURES, config=SMALL)
    assert control is not None
    assert control.model_version == COMPONENT_MODEL_VERSION
    assert control.weighting == EQUAL_WEIGHTING
    assert control.season_weights == ((NEW, 1.0),)

    # One season means every row weighs 1 under the rule, so the weighted arm reduces to
    # the control up to floating-point summation order.
    weighted = fit_component_models(
        training,
        feature_columns=FEATURES,
        config=SMALL,
        weighting=SeasonAgeWeighting(target_season=NEW),
    )
    assert weighted is not None
    assert weighted.season_weights == ((NEW, 1.0),)
    assert_frame_equal(
        predict_components(control, scoring, feature_columns=FEATURES),
        predict_components(weighted, scoring, feature_columns=FEATURES),
        check_exact=False,
        rtol=1e-9,
        atol=1e-9,
    )


def test_the_weights_reach_the_scaler_and_every_estimator_on_the_right_rows() -> None:
    """The fit must equal a by-hand weighted fit: normalized per subset, scaler included."""

    frame = _two_seasons()
    training = rows_strictly_before(frame, season_order=(OLD, NEW), season=NEW, gameweek=6).copy(
        deep=True
    )
    # One appeared row loses its points target: it stays in the appearance subset and
    # leaves the conditional one, and the conditional normalization must follow it out.
    first_appeared = training.index[training["appearance_target"].eq(1)][0]
    training.loc[first_appeared, "points_target"] = pd.NA
    rule = SeasonAgeWeighting(target_season=NEW)

    fitted = fit_component_models(training, feature_columns=FEATURES, config=SMALL, weighting=rule)
    assert fitted is not None

    raw = training["season"].astype("string").map({OLD: 0.5, NEW: 1.0}).astype("float64")
    design = training.loc[:, list(FEATURES)].astype("float64")
    appearance_target = training["appearance_target"].astype("int64")
    usable_weights = (raw / raw.mean()).to_numpy()
    reference_appearance = make_pipeline(
        StandardScaler(),
        LogisticRegression(C=1.0, max_iter=1000, solver="lbfgs", random_state=0),
    ).fit(
        design,
        appearance_target,
        standardscaler__sample_weight=usable_weights,
        logisticregression__sample_weight=usable_weights,
    )
    appeared = (
        appearance_target.eq(1)
        & training["minutes_target"].notna()
        & training["points_target"].notna()
    )
    assert fitted.appearance_rows == len(training)
    assert fitted.conditional_rows == int(appeared.sum()) == int(appearance_target.sum()) - 1
    conditional_raw = raw.loc[appeared]
    conditional_weights = (conditional_raw / conditional_raw.mean()).to_numpy()
    reference_points = make_pipeline(StandardScaler(), Ridge(alpha=1.0, solver="cholesky")).fit(
        design.loc[appeared],
        training.loc[appeared, "points_target"].astype("float64"),
        standardscaler__sample_weight=conditional_weights,
        ridge__sample_weight=conditional_weights,
    )

    np.testing.assert_allclose(fitted.appearance[-1].coef_, reference_appearance[-1].coef_)
    np.testing.assert_allclose(fitted.appearance[0].mean_, reference_appearance[0].mean_)
    np.testing.assert_allclose(fitted.points[-1].coef_, reference_points[-1].coef_)
    np.testing.assert_allclose(fitted.points[-1].intercept_, reference_points[-1].intercept_)
    np.testing.assert_allclose(fitted.points[0].scale_, reference_points[0].scale_)
    np.testing.assert_allclose(fitted.minutes[0].mean_, reference_points[0].mean_)

    # The check has teeth only if the control fit is a different model.
    control = fit_component_models(training, feature_columns=FEATURES, config=SMALL)
    assert control is not None
    assert not np.allclose(control.points[-1].coef_, fitted.points[-1].coef_)
    assert not np.allclose(control.points[0].mean_, fitted.points[0].mean_)


def test_the_weighted_fit_follows_the_recent_season_more_closely() -> None:
    frame = _two_seasons()
    training = rows_strictly_before(frame, season_order=(OLD, NEW), season=NEW, gameweek=6)
    scoring = rows_at(frame, season=NEW, gameweek=6)
    appeared = scoring["appearance_target"].eq(1)

    control = fit_component_models(training, feature_columns=FEATURES, config=SMALL)
    weighted = fit_component_models(
        training,
        feature_columns=FEATURES,
        config=SMALL,
        weighting=SeasonAgeWeighting(target_season=NEW),
    )
    assert control is not None and weighted is not None

    def mae(models: object) -> float:
        predicted = predict_components(models, scoring, feature_columns=FEATURES)  # type: ignore[arg-type]
        error = predicted["expected_points_if_appearance"].astype("float64") - scoring[
            "points_target"
        ].astype("float64")
        return float(error.loc[appeared].abs().mean())

    assert mae(weighted) < mae(control)


def test_a_weighted_fit_carries_its_own_identity_and_the_declared_weights() -> None:
    frame = _two_seasons()
    training = rows_strictly_before(frame, season_order=(OLD, NEW), season=NEW, gameweek=6)

    fitted = fit_component_models(
        training,
        feature_columns=FEATURES,
        config=SMALL,
        weighting=SeasonAgeWeighting(target_season=NEW),
    )

    assert fitted is not None
    assert fitted.model_version == SEASON_WEIGHTED_MODEL_VERSION
    assert fitted.model_version != COMPONENT_MODEL_VERSION
    assert fitted.weighting == SEASON_HALF_LIFE_WEIGHTING
    assert fitted.season_weights == ((OLD, 0.5), (NEW, 1.0))


def test_training_rows_after_the_prediction_season_are_refused_by_the_fit() -> None:
    frame = _frame(
        _panel(NEW, 8, 20, intercept=9, slope=-1),
        _panel(LATER, 8, 20, intercept=9, slope=-1),
    )

    with pytest.raises(PredictionConfigurationError, match="leak"):
        fit_component_models(
            frame,
            feature_columns=FEATURES,
            config=SMALL,
            weighting=SeasonAgeWeighting(target_season=NEW),
        )


def test_a_thin_history_is_refused_under_weighting_too() -> None:
    frame = _two_seasons()
    training = rows_strictly_before(frame, season_order=(OLD, NEW), season=NEW, gameweek=6)

    assert (
        fit_component_models(
            training,
            feature_columns=FEATURES,
            config=ComponentModelConfig(minimum_training_rows=10_000),
            weighting=SeasonAgeWeighting(target_season=NEW),
        )
        is None
    )


def test_weighting_must_be_the_declared_rule() -> None:
    frame = _two_seasons()

    with pytest.raises(PredictionConfigurationError, match="SeasonAgeWeighting"):
        fit_component_models(
            frame,
            feature_columns=FEATURES,
            config=SMALL,
            weighting={"target_season": NEW},  # type: ignore[arg-type]
        )
