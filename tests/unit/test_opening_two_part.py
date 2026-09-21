"""The two-part opening projection's arithmetic, and the sign its ordering clause turns on."""

import numpy as np
import pandas as pd
import pytest

from squadopt.experiments.config import ExperimentExecutionError
from squadopt.experiments.opening_two_part import (
    ORDERING_TOLERANCE,
    PART_ONE_DESIGN,
    SeasonReading,
    TwoPartCoefficients,
    calibration_by_decile,
    fit_two_part,
    part_one_design,
    play_probability,
    played,
    predict_two_part,
    two_part_gate,
)


def _rows(**overrides: object) -> pd.DataFrame:
    frame = pd.DataFrame(
        {
            "position": ["GK", "DEF", "MID", "FWD"],
            "ownership_share": [0.1, 0.5, 0.9, 0.2],
            "price_m": [4.5, 5.0, 7.0, 6.0],
            "minutes": [0, 90, 90, 0],
            "total_points": [0.0, 6.0, 8.0, 0.0],
        }
    )
    for name, value in overrides.items():
        frame[name] = value
    return frame


def _reading(season: str, *, control_rank: float, candidate_rank: float) -> SeasonReading:
    return SeasonReading(
        season=season,
        rows=10,
        training_rows=100,
        rows_without_published_ownership=0,
        control_mae=1.0,
        candidate_mae=0.5,
        control_rank=control_rank,
        candidate_rank=candidate_rank,
        played_rows=5,
        candidate_bias_on_played=0.0,
        candidate_mae_on_played=0.0,
        control_bias_on_played=0.0,
        control_mae_on_played=0.0,
        candidate_rank_on_played=0.0,
        control_rank_on_played=0.0,
        calibration=(),
        coefficients={},
    )


def test_the_design_is_the_protocols_with_gk_as_the_reference_level() -> None:
    design = part_one_design(_rows())
    assert design.shape == (4, len(PART_ONE_DESIGN))
    # Intercept, ownership, price, then DEF, MID, FWD as indicators.
    assert list(design[0]) == [1.0, 0.1, 4.5, 0.0, 0.0, 0.0]
    assert list(design[1]) == [1.0, 0.5, 5.0, 1.0, 0.0, 0.0]
    assert list(design[3]) == [1.0, 0.2, 6.0, 0.0, 0.0, 1.0]
    # The target is a play label: he took the field.
    assert list(played(_rows())) == [0.0, 1.0, 1.0, 0.0]


def test_a_position_with_no_played_training_row_is_refused_rather_than_priced_at_zero() -> None:
    """Pricing an unfitted position at zero would publish a number nobody measured."""

    coefficients = TwoPartCoefficients(
        part_one=(0.0, 0.0, 0.0, 0.0, 0.0, 0.0), part_two=(("GK", 0.5),)
    )
    with pytest.raises(ExperimentExecutionError, match="no scoring rate"):
        predict_two_part(_rows(), coefficients)
    # With every position fitted it predicts, and the product is clipped at zero.
    whole = TwoPartCoefficients(
        part_one=(0.0, 0.0, 0.0, 0.0, 0.0, 0.0),
        part_two=(("GK", 0.5), ("DEF", 0.4), ("MID", 0.3), ("FWD", -1.0)),
    )
    prediction = predict_two_part(_rows(), whole)
    assert prediction.min() >= 0.0
    # A zero coefficient vector is a probability of one half everywhere.
    assert prediction[0] == pytest.approx(0.5 * 4.5 * 0.5)


def test_part_two_is_fitted_on_played_rows_only() -> None:
    """The whole structural difference from the candidate that failed."""

    training = pd.DataFrame(
        {
            "position": ["MID"] * 4,
            "ownership_share": [0.1, 0.2, 0.3, 0.4],
            "price_m": [5.0, 5.0, 5.0, 5.0],
            # Two played and scored 10; two never appeared and scored nothing.
            "minutes": [90, 90, 0, 0],
            "total_points": [10.0, 10.0, 0.0, 0.0],
        }
    )
    coefficients = fit_two_part(training)
    # Through the origin on price over the played rows only: 10 / 5 = 2.0. Including the
    # absent rows would halve it, which is exactly what flattened the predecessor's slope.
    assert coefficients.slope("MID") == pytest.approx(2.0)
    assert coefficients.slope("GK") is None


def test_the_ordering_clause_rejects_a_candidate_that_falls_behind() -> None:
    """The sign of `rank_shortfall` is what the clause turns on, so it is pinned here.

    `rank_shortfall` is control minus candidate: positive means the candidate orders worse.
    A tidy-up that flipped it would turn a clause that rejects into one that accepts anything.
    """

    better = _reading("2022-23", control_rank=0.50, candidate_rank=0.56)
    assert better.rank_shortfall == pytest.approx(-0.06)
    worse = _reading("2023-24", control_rank=0.50, candidate_rank=0.40)
    assert worse.rank_shortfall == pytest.approx(0.10)

    summary = {"improves_every_season": True, "interval_excludes_zero": True}
    passing = two_part_gate((better,), summary, -0.02, (1.0, 0.0))
    assert passing["ordering_passes"] is True and passing["passes"] is True

    # One season falling behind by more than the tolerance fails the clause.
    failing = two_part_gate((better, worse), summary, -0.02, (1.0, 0.0))
    assert failing["ordering_passes"] is False and failing["passes"] is False
    # And so does a pooled shortfall beyond it, even when every season is inside.
    pooled = two_part_gate((better,), summary, ORDERING_TOLERANCE + 0.001, (1.0, 0.0))
    assert pooled["ordering_passes"] is False
    # Exactly at the tolerance is inside it.
    edge = two_part_gate((better,), summary, ORDERING_TOLERANCE, (1.0, 0.0))
    assert edge["ordering_passes"] is True


def test_the_other_two_clauses_are_the_protocols() -> None:
    reading = _reading("2022-23", control_rank=0.5, candidate_rank=0.5)
    passing = {"improves_every_season": True, "interval_excludes_zero": True}
    assert two_part_gate((reading,), passing, 0.0, (0.0, 0.0))["accuracy_passes"] is True
    for summary in (
        {"improves_every_season": False, "interval_excludes_zero": True},
        {"improves_every_season": True, "interval_excludes_zero": False},
    ):
        assert two_part_gate((reading,), summary, 0.0, (0.0,))["accuracy_passes"] is False

    # Decisions: mean at least zero and at most one losing season.
    assert two_part_gate((reading,), passing, 0.0, (5.0, -1.0))["decision_passes"] is True
    assert two_part_gate((reading,), passing, 0.0, (-1.0, -1.0))["decision_passes"] is False
    assert two_part_gate((reading,), passing, 0.0, ())["decision_passes"] is False


def test_the_calibration_reading_is_by_decile_of_the_predicted_probability() -> None:
    probability = np.linspace(0.05, 0.95, 20)
    outcome = (probability > 0.5).astype("float64")
    cells = calibration_by_decile(probability, outcome)
    assert [cell["decile"] for cell in cells] == list(range(1, 11))
    assert sum(int(cell["rows"]) for cell in cells) == 20
    assert cells[0]["mean_predicted"] < cells[-1]["mean_predicted"]
    assert cells[0]["realized_play_rate"] == 0.0 and cells[-1]["realized_play_rate"] == 1.0
    assert calibration_by_decile(np.array([]), np.array([])) == ()


def test_the_probability_is_a_logistic_of_the_design() -> None:
    coefficients = TwoPartCoefficients(
        part_one=(0.0, 1.0, 0.0, 0.0, 0.0, 0.0), part_two=(("GK", 1.0),)
    )
    probability = play_probability(_rows(), coefficients)
    assert probability[0] == pytest.approx(1.0 / (1.0 + np.exp(-0.1)))
    assert probability.min() > 0.0 and probability.max() < 1.0
