"""The compounding question, and the honesty the answer needs while the record is thin.

What these hold: the recency count reads the weeks the record actually holds rather than the
window it would like; a bucket too thin to characterise is named, counted and **not**
characterised; the population is the players the capture priced below full and nobody else;
and the sentence about what the record supports is generated from the record.
"""

import pandas as pd
import pytest
from scripts.measure_double_reduction import (
    MINIMUM_BUCKET_ROWS,
    RECENCY_WINDOW,
    WeekInputs,
    measure_double_reduction,
    recent_absences,
)

SEASON = "2026-27"


def _week(gameweek: int, rows: list[dict[str, object]]) -> pd.DataFrame:
    frame = pd.DataFrame(rows)
    frame["season"] = SEASON
    frame["gameweek"] = gameweek
    return frame


def _player(
    player_id: int,
    *,
    appearance: bool,
    multiplier: float | None = 0.5,
) -> dict[str, object]:
    return {
        "player_id": player_id,
        "appearance": appearance,
        "pre_deadline_availability_multiplier": multiplier,
    }


def _inputs(gameweek: int, frame: pd.DataFrame, fitted: dict[int, float]) -> WeekInputs:
    return WeekInputs(
        season=SEASON,
        gameweek=gameweek,
        outcomes=frame,
        fitted=pd.Series(fitted, dtype="float64"),
        fitted_source="fitted.csv",
    )


# --- the recency count ------------------------------------------------------


def test_recency_counts_absences_over_the_weeks_the_record_holds() -> None:
    weeks = [
        _week(4, [_player(1, appearance=False), _player(2, appearance=True)]),
        _week(5, [_player(1, appearance=False), _player(2, appearance=True)]),
    ]

    counts = recent_absences(weeks)

    assert counts.to_dict() == {1: 2, 2: 0}


def test_recency_looks_back_no_further_than_its_declared_window() -> None:
    weeks = [_week(week, [_player(1, appearance=False)]) for week in range(1, RECENCY_WINDOW + 3)]

    assert int(recent_absences(weeks)[1]) == RECENCY_WINDOW


def test_the_first_week_has_no_prior_weeks_and_says_so() -> None:
    assert recent_absences([]).empty


# --- what the reading refuses to say ----------------------------------------


def test_a_bucket_too_thin_to_characterise_is_counted_and_not_characterised() -> None:
    """A mean appearance rate over four players is a number with no reading."""

    first = _week(4, [_player(index, appearance=index % 2 == 0) for index in range(1, 5)])
    second = _week(5, [_player(index, appearance=False) for index in range(1, 5)])
    fitted = dict.fromkeys(range(1, 5), 0.6)

    record = measure_double_reduction([_inputs(4, first, fitted), _inputs(5, second, fitted)])

    buckets = record["by_recent_weeks_missed"]
    assert all(not value["read"] for value in buckets.values())
    assert all("rows" in value for value in buckets.values())
    assert "no bucket reaches" in str(record["supports"])


def test_a_thick_bucket_is_read_and_carries_the_gap_the_question_asks_for() -> None:
    """Fitted against realised, with the multiplier beside it: the compounding, measured."""

    absent = [_player(index, appearance=False) for index in range(1, 41)]
    present = [_player(index, appearance=True) for index in range(1, 41)]
    fitted = dict.fromkeys(range(1, 41), 0.30)

    record = measure_double_reduction(
        [
            _inputs(4, _week(4, absent), fitted),
            _inputs(5, _week(5, present), fitted),
        ]
    )

    read = record["by_recent_weeks_missed"]["1"]
    assert read["read"] and read["rows"] == 40
    assert read["fitted_appearance_probability"] == pytest.approx(0.30)
    assert read["realised_appearance_rate"] == pytest.approx(1.0)
    # The fitted probability was far below what happened, so the multiplier is a correction
    # rather than a second cut -- and the sign of the gap is what says which.
    assert read["calibration_gap"] == pytest.approx(-0.70)
    assert read["further_reduction"] == pytest.approx(0.15)


def test_the_population_is_the_players_the_capture_priced_below_full() -> None:
    """A fully available player is not in the question, and an unlisted one is not either."""

    rows = [
        _player(1, appearance=True, multiplier=0.5),
        _player(2, appearance=True, multiplier=1.0),
        _player(3, appearance=True, multiplier=None),
    ]
    record = measure_double_reduction([_inputs(4, _week(4, rows), {1: 0.4, 2: 0.9, 3: 0.9})])

    assert record["population_rows"] == 1


def test_a_player_with_no_fitted_probability_is_not_counted_as_zero() -> None:
    rows = [_player(1, appearance=True), _player(2, appearance=True)]

    record = measure_double_reduction([_inputs(4, _week(4, rows), {1: 0.4})])

    assert record["population_rows"] == 1


# --- the sentence -----------------------------------------------------------


def test_nothing_settled_says_nothing_is_measured() -> None:
    record = measure_double_reduction([])

    assert record["population_rows"] == 0
    assert "nothing is measured yet" in str(record["supports"])


def test_one_readable_bucket_is_a_level_and_not_a_contrast() -> None:
    """The question is whether the gap differs by recency, and one bucket cannot say."""

    rows = [_player(index, appearance=True) for index in range(1, MINIMUM_BUCKET_ROWS + 10)]
    fitted = dict.fromkeys(range(1, MINIMUM_BUCKET_ROWS + 10), 0.5)

    record = measure_double_reduction(
        [
            _inputs(4, _week(4, rows), fitted),
            _inputs(5, _week(5, rows), fitted),
        ]
    )

    assert "a level and not a contrast" in str(record["supports"])
