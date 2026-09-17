"""A Brier with something to beat: the declared reference and the skill it produces.

A proper score alone can neither support nor refuse a claim. 0.0365 is a good Brier for a
coin and a terrible one for an event that happens 98.6 per cent of the time, and the
difference only becomes visible once the score is read against a reference forecast. These
pin the reference this repository declares -- a constant at the scored rows' own event rate --
and the arithmetic that turns it into a skill score.
"""

import pandas as pd
from scripts.measure_participation_calibration import (
    REFERENCE_FORECAST,
    _binary_metrics,
    _headline,
)


def _metrics(probabilities: list[float], outcomes: list[float]) -> dict[str, object]:
    return _binary_metrics(pd.Series(probabilities, dtype="float64"), pd.Series(outcomes))


def test_the_reference_is_the_scored_rows_own_rate_and_scores_zero() -> None:
    """Knowing only how often the thing happens is the floor, and the floor is zero."""

    metrics = _metrics([0.25] * 4, [1.0, 0.0, 0.0, 0.0])

    assert metrics["reference_forecast"] == REFERENCE_FORECAST
    assert metrics["reference_brier_score"] == 0.25 * 0.75
    assert metrics["brier_skill_score"] == 0.0


def test_a_forecast_worse_than_the_base_rate_reads_negative() -> None:
    """The goalkeeper slice in miniature: confident, calibrated badly, and worse than nothing.

    Predicting 0.89 for an event that happens 49 times in 50 gives a Brier of 0.0277, which
    looks respectable until it is read against the reference's 0.0196. The skill is what says
    so on the record's own face rather than waiting for a reader to divide.
    """

    outcomes = [1.0] * 49 + [0.0]
    metrics = _metrics([0.89] * 50, outcomes)

    assert round(float(metrics["brier_score"]), 4) == 0.0277
    assert round(float(metrics["brier_skill_score"]), 4) == -0.4133
    assert "skill -" in _headline(metrics)


def test_a_perfect_forecast_reads_one() -> None:
    metrics = _metrics([1.0, 0.0, 1.0, 0.0], [1.0, 0.0, 1.0, 0.0])

    assert metrics["brier_skill_score"] == 1.0


def test_a_slice_whose_outcome_never_varies_has_no_skill_to_measure() -> None:
    """Absent rather than infinite: the reference is exactly right, so there is nothing to beat."""

    metrics = _metrics([0.8, 0.9, 0.95], [1.0, 1.0, 1.0])

    assert metrics["reference_brier_score"] == 0.0
    assert metrics["brier_skill_score"] is None
    assert "no skill" in _headline(metrics)
