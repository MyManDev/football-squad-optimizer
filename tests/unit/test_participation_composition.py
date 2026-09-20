"""The composition's arithmetic, its refusal, and the empty-label trap it was built around."""

import pandas as pd
import pytest

from squadopt.evaluation.participation_composition import (
    compose_arms,
    fit_state_points,
    points_reading,
    realized_state,
    state_points,
)
from squadopt.prediction.component_models import ComponentModelConfig


def _training(rows: int = 600) -> pd.DataFrame:
    """A frame with both states present, scoring differently, and one unlabelled appearance."""

    index = range(rows)
    started = [index % 3 != 0 for index in index]
    return pd.DataFrame(
        {
            "form": [float(value % 7) for value in index],
            "minutes_mean": [float(value % 90) for value in index],
            "appearance_target": [1] * rows,
            "start_target": [1 if value else 0 for value in started],
            # Starters score around six, substitutes around one.
            "points_target": [6.0 if value else 1.0 for value in started],
        }
    )


COLUMNS = ("form", "minutes_mean")


def test_an_appearance_without_a_start_label_is_missing_and_not_a_substitute() -> None:
    """The trap the frozen out-of-fold table sets: its `start_target` is empty on every row.

    Reading both labels off that frame would call every appearance a substitute, which is a
    measured claim about rotation made out of an absent column.
    """

    appearance = pd.Series([0, 1, 1, 1])
    start = pd.Series([pd.NA, 1, 0, pd.NA], dtype="Int64")
    state = realized_state(appearance, start)
    assert list(state[:3]) == ["absent", "start", "substitute"]
    assert state[3] is pd.NA
    # A row that did not appear is `absent` whatever the start column says.
    assert realized_state(pd.Series([0]), pd.Series([1]))[0] == "absent"


def test_a_state_with_too_few_training_rows_is_refused_rather_than_fitted() -> None:
    """A ridge over a handful of rows returns a number nothing downstream can tell apart."""

    frame = _training()
    config = ComponentModelConfig(minimum_training_rows=200)
    assert fit_state_points(frame, feature_columns=COLUMNS, config=config) is not None

    # Two substitute rows in six hundred: the pooled fit is comfortable and the split is not.
    thin = frame.assign(start_target=[0 if value < 2 else 1 for value in range(len(frame))])
    assert fit_state_points(thin, feature_columns=COLUMNS, config=config) is None


def test_the_two_state_models_are_fitted_on_disjoint_halves_of_the_pooled_one() -> None:
    models = fit_state_points(_training(), feature_columns=COLUMNS)
    assert models is not None
    assert models.started_rows + models.substitute_rows == models.pooled_rows
    assert models.training_start_rate == pytest.approx(models.started_rows / models.pooled_rows)

    predicted = state_points(models, _training().head(5))
    # Starters score six and substitutes one in this frame, and the fits separate them.
    assert predicted["points_if_start"].mean() > predicted["points_if_substitute"].mean()
    # The pooled fit sits between the two, which is the whole reason a split can move a price.
    assert (
        predicted["points_if_substitute"].mean()
        < predicted["points_if_appearance"].mean()
        < predicted["points_if_start"].mean()
    )
    assert predicted.min().min() >= 0.0


def _points(start: float, substitute: float, pooled: float, rows: int = 3) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "points_if_appearance": [pooled] * rows,
            "points_if_start": [start] * rows,
            "points_if_substitute": [substitute] * rows,
        }
    )


def test_a_row_without_q_keeps_the_uncomposed_value_in_every_arm() -> None:
    """The arms must differ only where the composition had something to say.

    A row that fell back in one arm and not another would let a decision difference come from
    which rows were priced rather than from how they were priced.
    """

    appearance = pd.Series([0.5, 0.5, 0.5], dtype="Float64")
    conditional = pd.Series([1.0, 0.0, pd.NA], dtype="Float64")
    arms = compose_arms(appearance, conditional, _points(8.0, 2.0, 5.0), training_start_rate=0.75)
    assert list(arms["uncomposed"]) == [2.5, 2.5, 2.5]
    # q = 1 prices the row as a certain starter; q = 0 as a certain substitute.
    assert arms["composed"][0] == pytest.approx(4.0)
    assert arms["composed"][1] == pytest.approx(1.0)
    # No q, so the arm is the uncomposed value exactly rather than a guess at one.
    assert arms["composed"][2] == pytest.approx(2.5)
    # The middle arm weighs the same two numbers by the training season's scalar everywhere.
    assert list(arms["state_split"]) == [pytest.approx(0.5 * 6.5)] * 3

    # A missing appearance probability leaves every arm missing: half a composition is not a
    # price, and a zero there would say the player is certain to score nothing.
    missing = compose_arms(
        pd.Series([pd.NA], dtype="Float64"),
        pd.Series([1.0], dtype="Float64"),
        _points(8.0, 2.0, 5.0, rows=1),
        training_start_rate=0.75,
    )
    assert missing.isna().all().all()


def test_the_error_is_forecast_minus_realized_and_skips_rows_without_both() -> None:
    forecast = pd.Series([3.0, 1.0, 5.0, pd.NA], dtype="Float64")
    realized = pd.Series([1.0, 2.0, pd.NA, 4.0], dtype="Float64")
    reading = points_reading(forecast, realized)
    assert reading["rows"] == 2
    # Over-forecasting is positive: +2 and -1 average to +0.5, and the absolute error to 1.5.
    assert reading["mean_error"] == pytest.approx(0.5)
    assert reading["mean_absolute_error"] == pytest.approx(1.5)
    assert points_reading(pd.Series([], dtype="Float64"), pd.Series([], dtype="Float64")) == {
        "rows": 0
    }
