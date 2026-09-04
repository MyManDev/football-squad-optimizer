"""The opponent-aware projection study: fitting, applying, the hindsight check, the gate.

Synthetic folds only — the archive is not available everywhere the tests run, and the point
of these tests is the machinery, not the football.
"""

import numpy as np
import pandas as pd
import pytest

from squadopt.experiments.config import ExperimentConfigurationError
from squadopt.experiments.opponent_projection import (
    CANDIDATES,
    CandidateOutcome,
    FoldOutcome,
    OpponentProjectionConfig,
    apply_adjustment,
    fit_adjustment,
    gate_verdict,
    hindsight_flagged,
    published_rating_hindsight,
)

POSITIONS = ("GK", "DEF", "MID", "FWD")


def _folds(season: str, *, slope: float, count: int = 200, seed: int = 0) -> pd.DataFrame:
    """A season whose residuals move with the fixture signal by ``slope``."""

    generator = np.random.default_rng(seed)
    predicted = generator.uniform(0.5, 8.0, count)
    attacking_signal = generator.uniform(0.8, 2.2, count)
    defensive_signal = generator.uniform(0.1, 0.45, count)
    published = generator.uniform(-5.0, -1.0, count)
    positions = np.array([POSITIONS[index % 4] for index in range(count)])
    is_attacking = np.isin(positions, ("MID", "FWD"))
    signal = np.where(is_attacking, attacking_signal, defensive_signal)
    # Centred per position, because that is what the fit does: the two signals live on
    # different scales and a pooled centre would bias the slope the test is checking.
    centre = np.zeros(count, dtype="float64")
    for position in POSITIONS:
        mask = positions == position
        centre[mask] = float(np.mean(signal[mask]))
    residual = slope * predicted * (signal - centre) + generator.normal(0.0, 0.05, count)
    return pd.DataFrame(
        {
            "fold_id": [f"{season}-gw{2 + index % 5:02d}" for index in range(count)],
            "season": season,
            "gameweek": [2 + index % 5 for index in range(count)],
            "player_id": [index + 1 for index in range(count)],
            "name": [f"Player {index}" for index in range(count)],
            "team_id": [f"Club {index % 5}" for index in range(count)],
            "position": positions,
            "price_tenths": np.linspace(40, 130, count).astype(int),
            "predicted_points": predicted,
            "realized_points": predicted + residual,
            "residual": residual,
            "rating_attacking_signal": attacking_signal,
            "rating_defensive_signal": defensive_signal,
            "published_signal": published,
            "fixture_count": 1.0,
        }
    )


def test_the_locked_holdout_is_refused_by_configuration() -> None:
    with pytest.raises(ExperimentConfigurationError, match="locked holdout"):
        OpponentProjectionConfig(
            seasons=("2024-25", "2025-26"),
            development_seasons=("2024-25",),
            evaluated_seasons=("2024-25",),
        )
    with pytest.raises(ExperimentConfigurationError, match="locked holdout"):
        OpponentProjectionConfig(evaluated_seasons=("2025-26",))


def test_the_earliest_development_season_cannot_be_judged() -> None:
    with pytest.raises(ExperimentConfigurationError, match="no residuals before it"):
        OpponentProjectionConfig(evaluated_seasons=("2021-22",))


def test_the_fit_recovers_the_slope_that_generated_the_residuals() -> None:
    rows = _folds("2022-23", slope=0.4, count=800)
    coefficients = fit_adjustment(rows, "R_team_rating")
    for position in POSITIONS:
        slope, _ = coefficients[position]
        assert slope == pytest.approx(0.4, abs=0.05)


def test_an_inert_signal_fits_a_slope_of_about_zero() -> None:
    rows = _folds("2022-23", slope=0.0, count=800)
    coefficients = fit_adjustment(rows, "R_team_rating")
    for position in POSITIONS:
        slope, _ = coefficients[position]
        assert abs(slope) < 0.05


def test_the_adjustment_moves_the_projection_in_the_right_direction() -> None:
    rows = _folds("2022-23", slope=0.4, count=800)
    coefficients = fit_adjustment(rows, "R_team_rating")
    adjusted, multiplier = apply_adjustment(rows, "R_team_rating", coefficients)
    signal = np.where(
        rows["position"].isin(("MID", "FWD")),
        rows["rating_attacking_signal"],
        rows["rating_defensive_signal"],
    )
    positions = rows["position"].to_numpy()
    # Compared within position: the two signals live on different scales, so a pooled
    # threshold would only separate attackers from defenders.
    for position in POSITIONS:
        mask = positions == position
        _, centre = coefficients[position]
        kind = mask & (signal > centre)
        harsh = mask & (signal < centre)
        assert float(multiplier[kind].mean()) > 1.0 > float(multiplier[harsh].mean())
    assert (adjusted >= 0.0).all()


def test_a_player_projected_at_zero_is_not_lifted_by_a_kind_fixture() -> None:
    rows = _folds("2022-23", slope=0.4, count=80)
    rows.loc[:, "predicted_points"] = 0.0
    coefficients = fit_adjustment(_folds("2021-22", slope=0.4, count=800), "R_team_rating")
    adjusted, _ = apply_adjustment(rows, "R_team_rating", coefficients)
    assert float(np.abs(adjusted).max()) == 0.0


def test_a_missing_signal_leaves_the_projection_alone() -> None:
    rows = _folds("2022-23", slope=0.4, count=80)
    rows.loc[:, "rating_attacking_signal"] = float("nan")
    rows.loc[:, "rating_defensive_signal"] = float("nan")
    coefficients = fit_adjustment(_folds("2021-22", slope=0.4, count=800), "R_team_rating")
    adjusted, multiplier = apply_adjustment(rows, "R_team_rating", coefficients)
    assert np.allclose(multiplier, 1.0)
    assert np.allclose(adjusted, rows["predicted_points"].to_numpy())


def test_every_candidate_names_two_signal_columns_that_exist() -> None:
    rows = _folds("2022-23", slope=0.2, count=40)
    for attacking, defensive in CANDIDATES.values():
        assert attacking in rows.columns
        assert defensive in rows.columns


def _matches(seasons: tuple[str, ...], *, hindsight: bool) -> pd.DataFrame:
    """Two seasons where club strength reverses, so the two hypotheses separate cleanly."""

    rows: list[dict[str, object]] = []
    for index, season in enumerate(seasons):
        # Strength order reverses each season, so a pre-season rating and a hindsight
        # rating disagree by construction.
        order = list(range(1, 7)) if index % 2 == 0 else list(reversed(range(1, 7)))
        rank = {club: position for position, club in enumerate(order)}
        for home in range(1, 7):
            for away in range(1, 7):
                if home == away:
                    continue
                difficulty = 1.0 + rank[away] * (1.0 if hindsight or index == 0 else -1.0)
                rows.append(
                    {
                        "season": season,
                        "gameweek": 1,
                        "kickoff": pd.Timestamp("2020-08-01", tz="UTC"),
                        "home_club": home,
                        "away_club": away,
                        "home_goals": 3 - rank[home] // 2,
                        "away_goals": 3 - rank[away] // 2,
                        "home_difficulty": difficulty,
                        "away_difficulty": 1.0 + rank[home] * 1.0,
                    }
                )
    return pd.DataFrame(rows)


def test_the_hindsight_check_reports_both_correlations() -> None:
    matches = _matches(("2021-22", "2022-23"), hindsight=True)
    report = published_rating_hindsight(matches, ("2022-23",))
    assert set(report) == {"2022-23"}
    values = report["2022-23"]
    assert "against_this_season" in values
    assert "against_previous_season" in values
    assert values["clubs_shared_with_previous"] == 6.0


def test_the_first_season_cannot_be_checked_for_hindsight() -> None:
    matches = _matches(("2021-22", "2022-23"), hindsight=True)
    assert published_rating_hindsight(matches, ("2021-22",)) == {}


def test_a_season_is_flagged_only_when_it_tracks_its_own_table_better() -> None:
    assert hindsight_flagged(
        {"2022-23": {"against_this_season": 0.9, "against_previous_season": 0.4}}
    ) == ("2022-23",)
    assert (
        hindsight_flagged({"2022-23": {"against_this_season": 0.4, "against_previous_season": 0.9}})
        == ()
    )
    assert (
        hindsight_flagged(
            {"2022-23": {"against_this_season": float("nan"), "against_previous_season": 0.9}}
        )
        == ()
    )


def _fold(**overrides: object) -> FoldOutcome:
    settings: dict[str, object] = {
        "fold_id": "2022-23-gw02",
        "season": "2022-23",
        "gameweek": 2,
        "rows": 500,
        "control_absolute_error": 1.5,
        "candidate_absolute_error": 1.4,
        "control_rank_correlation": 0.30,
        "candidate_rank_correlation": 0.31,
        "control_realized_points": 50.0,
        "candidate_realized_points": 53.0,
        "changed_starters": 2,
        "mean_multiplier": 1.0,
        "minimum_multiplier": 0.8,
        "maximum_multiplier": 1.2,
    }
    settings.update(overrides)
    return FoldOutcome(**settings)  # type: ignore[arg-type]


def _outcome(**overrides: object) -> CandidateOutcome:
    settings: dict[str, object] = {
        "candidate": "R_team_rating",
        "folds": (_fold(),),
        "coefficients": {"GK": {"slope": 0.1, "centre": 0.3}},
        "error_improvement": 0.1,
        "error_interval": (0.05, 0.15),
        "per_season_error_improvement": {"2022-23": 0.1, "2023-24": 0.1},
        "rank_improvement": 0.01,
        "per_season_rank_improvement": {"2022-23": 0.01, "2023-24": 0.01},
        "decision_difference": 3.0,
        "decision_interval": (1.0, 5.0),
        "per_season_decision_difference": {"2022-23": 3.0, "2023-24": 3.0},
    }
    settings.update(overrides)
    return CandidateOutcome(**settings)  # type: ignore[arg-type]


def test_the_gate_passes_only_when_all_three_clauses_hold() -> None:
    verdict = gate_verdict(_outcome())
    assert verdict["passes"] is True
    assert verdict["accuracy_passes"] is True
    assert verdict["ordering_passes"] is True
    assert verdict["decision_passes"] is True


def test_an_accuracy_win_with_a_losing_decision_fails_the_gate() -> None:
    """The standing lesson from the schedule signal study, encoded as a test."""

    verdict = gate_verdict(_outcome(decision_difference=-1.0, decision_interval=(-3.0, 1.0)))
    assert verdict["accuracy_passes"] is True
    assert verdict["decision_passes"] is False
    assert verdict["passes"] is False


def test_a_decision_interval_touching_zero_fails_the_gate() -> None:
    verdict = gate_verdict(_outcome(decision_interval=(-0.2, 6.0)))
    assert verdict["decision_passes"] is False
    assert verdict["passes"] is False


def test_one_season_of_the_wrong_error_sign_fails_the_gate() -> None:
    verdict = gate_verdict(
        _outcome(per_season_error_improvement={"2022-23": -0.02, "2023-24": 0.2})
    )
    assert verdict["accuracy_passes"] is False
    assert verdict["passes"] is False


def test_a_worse_ordering_in_every_season_fails_the_gate() -> None:
    verdict = gate_verdict(
        _outcome(
            rank_improvement=-0.01,
            per_season_rank_improvement={"2022-23": -0.01, "2023-24": -0.01},
        )
    )
    assert verdict["ordering_passes"] is False
    assert verdict["passes"] is False


def test_fold_arithmetic_is_the_candidate_minus_the_control() -> None:
    fold = _fold()
    assert fold.error_improvement == pytest.approx(0.1)
    assert fold.rank_improvement == pytest.approx(0.01)
    assert fold.decision_difference == pytest.approx(3.0)
