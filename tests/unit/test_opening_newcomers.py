"""The opening newcomer study: fitting, walking forward, and the gate that judges it.

Synthetic seasons only — the archive is not available everywhere the tests run, and the
point of these tests is the machinery, not the football.
"""

import numpy as np
import pandas as pd
import pytest

from squadopt.experiments.config import ExperimentConfigurationError
from squadopt.experiments.opening_newcomers import (
    CANDIDATES,
    CandidateResult,
    CandidateSeasonResult,
    DecisionComparison,
    OpeningStudyConfig,
    control_prediction,
    evaluate_candidate,
    evaluate_movers,
    fit_candidate,
    gate_verdict,
    predict_candidate,
)
from squadopt.prediction.config import FITTED_OPENING_PRICE_COEFFICIENT


def _rows(season: str, *, slope: float, count: int = 40, seed: int = 0) -> pd.DataFrame:
    """A season whose newcomers score ``slope`` points per million, plus a mover block."""

    generator = np.random.default_rng(seed)
    prices = np.linspace(4.0, 12.0, count)
    ownership = np.linspace(0.0, 1.0, count)
    frame = pd.DataFrame(
        {
            "season": season,
            "player_id": [int(f"{hash((season, index)) % 100000}") for index in range(count)],
            "name": [f"Player {index}" for index in range(count)],
            "team_id": ["Club A" if index % 2 else "Club B" for index in range(count)],
            "position": [["GK", "DEF", "MID", "FWD"][index % 4] for index in range(count)],
            "price_tenths": (prices * 10).astype(int),
            "price_m": prices,
            "ownership_share": ownership,
            "source_expected_points": prices * 0.2,
            "published_ease": 0.5,
            "carried_ease": 0.5,
            "minutes": 90,
            "total_points": prices * slope + generator.normal(0.0, 0.01, count),
            "has_prior_record": False,
            "is_mover": False,
            "carried_projection": float("nan"),
        }
    )
    return frame


def test_the_locked_holdout_is_refused_by_configuration() -> None:
    with pytest.raises(ExperimentConfigurationError, match="locked holdout"):
        OpeningStudyConfig(seasons=("2024-25", "2025-26"), evaluated_seasons=("2024-25",))
    with pytest.raises(ExperimentConfigurationError, match="locked holdout"):
        OpeningStudyConfig(evaluated_seasons=("2025-26",))
    with pytest.raises(ExperimentConfigurationError, match="part of the study"):
        OpeningStudyConfig(seasons=("2023-24", "2024-25"), evaluated_seasons=("2021-22",))
    with pytest.raises(ExperimentConfigurationError, match="nothing before it"):
        OpeningStudyConfig(seasons=("2023-24", "2024-25"), evaluated_seasons=("2023-24",))


def test_the_control_is_the_prior_that_ships() -> None:
    rows = _rows("2023-24", slope=1.0)
    predicted = control_prediction(rows)
    assert predicted == pytest.approx(rows["price_m"] * FITTED_OPENING_PRICE_COEFFICIENT)
    assert float(predicted.min()) >= 0.0


def test_a_fit_recovers_a_linear_relation_and_predictions_never_go_negative() -> None:
    rows = _rows("2023-24", slope=0.5)
    coefficients = fit_candidate(rows, ("price_m",), None)
    for position in ("GK", "DEF", "MID", "FWD"):
        assert coefficients[position]["price_m"] == pytest.approx(0.5, abs=0.02)
    predicted = predict_candidate(rows, coefficients, ("price_m",), None)
    assert predicted == pytest.approx(rows["total_points"].to_numpy(), abs=0.05)

    negative = rows.copy()
    negative["total_points"] = -5.0
    downward = fit_candidate(negative, ("price_m",), None)
    assert predict_candidate(negative, downward, ("price_m",), None).min() >= 0.0


def test_the_walk_forward_fit_never_sees_the_season_it_judges() -> None:
    # Training seasons say one point per million; the judged season says four. A fit that
    # peeked would predict the judged season almost exactly.
    rows = pd.concat(
        [
            _rows("2021-22", slope=1.0, seed=1),
            _rows("2022-23", slope=1.0, seed=2),
            _rows("2023-24", slope=4.0, seed=3),
        ],
        ignore_index=True,
    )
    config = OpeningStudyConfig(
        seasons=("2021-22", "2022-23", "2023-24"),
        evaluated_seasons=("2023-24",),
        bootstrap_resamples=100,
        minimum_training_rows=10,
    )
    result = evaluate_candidate(rows, "M1_price_by_position", config)
    assert [season.season for season in result.seasons] == ["2023-24"]
    judged = result.seasons[0]
    # Predicting a four-point slope with a one-point fit leaves a large, negative bias.
    assert judged.bias < -5.0
    assert judged.rows == 40


def test_a_better_candidate_shows_up_as_a_positive_interval() -> None:
    # Points are ownership-driven, so the price-only control is beaten by the ownership
    # candidate in every season.
    frames = []
    for index, season in enumerate(("2021-22", "2022-23", "2023-24")):
        block = _rows(season, slope=0.0, seed=index)
        block["total_points"] = block["ownership_share"] * 6.0
        frames.append(block)
    rows = pd.concat(frames, ignore_index=True)
    config = OpeningStudyConfig(
        seasons=("2021-22", "2022-23", "2023-24"),
        evaluated_seasons=("2022-23", "2023-24"),
        bootstrap_resamples=200,
        minimum_training_rows=10,
    )
    ownership = evaluate_candidate(rows, "M2_ownership", config)
    assert ownership.improves_every_season
    assert ownership.interval_excludes_zero
    assert ownership.pooled_error_improvement > 0.0
    assert set(CANDIDATES) >= {"M1_price_by_position", "M2_ownership"}


def test_the_gate_is_computed_from_the_numbers() -> None:
    def _season(name: str, gain: float, rank_gain: float) -> CandidateSeasonResult:
        return CandidateSeasonResult(
            candidate="candidate",
            season=name,
            rows=10,
            mean_absolute_error=1.0 - gain,
            bias=0.0,
            rank_correlation=0.5 + rank_gain,
            control_mean_absolute_error=1.0,
            control_bias=0.0,
            control_rank_correlation=0.5,
            rank_correlation_players_only=0.2,
            control_rank_correlation_players_only=0.2,
        )

    def _candidate(gain: float, rank_gain: float, interval: tuple[float, float]) -> CandidateResult:
        return CandidateResult(
            candidate="candidate",
            features=("price_m",),
            multiplier=None,
            seasons=(_season("a", gain, rank_gain), _season("b", gain, rank_gain)),
            pooled_rows=20,
            pooled_error_improvement=gain,
            pooled_error_interval=interval,
            coefficients={},
        )

    wins = (
        DecisionComparison("a", 50.0, 56.0, 0, 2, 3),
        DecisionComparison("b", 50.0, 49.0, 0, 1, 2),
    )
    passing = gate_verdict(_candidate(0.3, 0.05, (0.1, 0.5)), wins)
    assert passing == {
        "candidate": "candidate",
        "accuracy_passes": True,
        "ordering_passes": True,
        "decision_passes": True,
        "mean_decision_difference": pytest.approx(2.5),
        "decision_losses": 1,
        "passes": True,
    }
    # An interval that touches zero is not evidence.
    assert gate_verdict(_candidate(0.3, 0.05, (-0.01, 0.5)), wins)["passes"] is False
    # Ordering that merely stays level does not count as an improvement.
    assert gate_verdict(_candidate(0.3, 0.0, (0.1, 0.5)), wins)["ordering_passes"] is False
    # Losing in two of two seasons fails whatever the mean says.
    losses = (
        DecisionComparison("a", 50.0, 49.0, 0, 1, 1),
        DecisionComparison("b", 50.0, 49.0, 0, 1, 1),
    )
    assert gate_verdict(_candidate(0.3, 0.05, (0.1, 0.5)), losses)["decision_passes"] is False


def test_movers_are_measured_against_the_players_who_stayed() -> None:
    frames = []
    for index, season in enumerate(("2021-22", "2022-23", "2023-24")):
        block = _rows(season, slope=0.5, seed=index)
        block["has_prior_record"] = True
        block["carried_projection"] = block["total_points"] + 1.0  # carried too high
        block["is_mover"] = [item % 4 == 0 for item in range(len(block))]
        frames.append(block)
    rows = pd.concat(frames, ignore_index=True)
    config = OpeningStudyConfig(
        seasons=("2021-22", "2022-23", "2023-24"),
        evaluated_seasons=("2022-23", "2023-24"),
        bootstrap_resamples=100,
        minimum_training_rows=10,
    )
    movers = evaluate_movers(rows, config)
    assert movers.rows == 30
    assert movers.mover_bias == pytest.approx(-1.0, abs=0.05)
    assert movers.stayer_bias == pytest.approx(-1.0, abs=0.05)
    assert set(movers.per_season_bias) == {"2021-22", "2022-23", "2023-24"}
    assert movers.best_shrink in OpeningStudyConfig().mover_shrink_grid
