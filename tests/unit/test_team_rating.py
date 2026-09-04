"""The Dixon-Coles team rating: fitting, timing, the promoted prior, and the gate.

Synthetic leagues only — the archive is not available everywhere the tests run, and the
point of these tests is the machinery, not the football.
"""

import math

import numpy as np
import pandas as pd
import pytest

from squadopt.experiments.config import ExperimentConfigurationError, ExperimentExecutionError
from squadopt.experiments.team_rating import (
    MAXIMUM_GOALS,
    DixonColesConfig,
    SeasonScorecard,
    TeamRating,
    TeamRatingStudyConfig,
    fit_clean_sheet_calibration,
    fit_dixon_coles,
    measure_promoted_prior,
    promoted_clubs,
    rating_gate_verdict,
    walk_forward_log_likelihood,
)

STRENGTHS = {1: 0.6, 2: 0.3, 3: 0.0, 4: -0.3, 5: -0.6, 6: -0.9}


def _league(
    season: str, clubs: tuple[int, ...], *, start: str, seed: int, rounds: int = 6
) -> pd.DataFrame:
    """A season where a club's attack and defence both follow its strength."""

    generator = np.random.default_rng(seed)
    rows: list[dict[str, object]] = []
    day = pd.Timestamp(start, tz="UTC")
    gameweek = 0
    for _ in range(rounds):
        for home in clubs:
            for away in clubs:
                if home == away:
                    continue
                gameweek += 1
                # The generating model is the one being fitted: a club's strength is both
                # its attack and its defence, so a strong opponent suppresses goals.
                home_rate = math.exp(0.25 + STRENGTHS[home] - STRENGTHS[away])
                away_rate = math.exp(STRENGTHS[away] - STRENGTHS[home])
                rows.append(
                    {
                        "season": season,
                        "gameweek": 1 + (gameweek // len(clubs)),
                        "kickoff": day + pd.Timedelta(days=gameweek),
                        "home_club": home,
                        "away_club": away,
                        "home_goals": int(generator.poisson(home_rate)),
                        "away_goals": int(generator.poisson(away_rate)),
                        # A published rating that is honest about who is strong.
                        "home_difficulty": 3.0 - STRENGTHS[away] * 2.0,
                        "away_difficulty": 3.0 - STRENGTHS[home] * 2.0,
                    }
                )
    return pd.DataFrame(rows)


def _matches() -> pd.DataFrame:
    first = _league("2021-22", (1, 2, 3, 4, 5), start="2021-08-01", seed=1)
    second = _league("2022-23", (1, 2, 3, 4, 6), start="2022-08-01", seed=2)
    third = _league("2023-24", (1, 2, 3, 4, 6), start="2023-08-01", seed=3)
    return pd.concat([first, second, third], ignore_index=True)


def test_the_locked_holdout_is_refused_by_configuration() -> None:
    with pytest.raises(ExperimentConfigurationError, match="locked holdout"):
        TeamRatingStudyConfig(seasons=("2024-25", "2025-26"), evaluated_seasons=("2024-25",))
    with pytest.raises(ExperimentConfigurationError, match="locked holdout"):
        TeamRatingStudyConfig(evaluated_seasons=("2025-26",))


def test_a_nonsense_decay_or_ridge_is_refused() -> None:
    with pytest.raises(ExperimentConfigurationError, match="half_life_days"):
        DixonColesConfig(half_life_days=0.0)
    with pytest.raises(ExperimentConfigurationError, match="ridge"):
        DixonColesConfig(ridge=-1.0)
    with pytest.raises(ExperimentConfigurationError, match="rho_grid"):
        DixonColesConfig(rho_grid=())


def test_the_fit_recovers_the_ordering_that_generated_the_goals() -> None:
    matches = _matches()
    as_of = pd.Timestamp(matches["kickoff"].max()) + pd.Timedelta(days=1)
    rating = fit_dixon_coles(matches, as_of=as_of, config=DixonColesConfig(ridge=0.2))
    assert rating.attack[1] > rating.attack[3] > rating.attack[4]
    assert rating.defence[1] > rating.defence[4]
    assert rating.home_advantage > 0.0
    assert rating.matches_used == len(matches)


def test_the_fit_reads_nothing_after_its_as_of() -> None:
    """Poisoning the future cannot move a rating fitted on the past."""

    matches = _matches()
    cut = pd.Timestamp(matches.loc[matches["season"] == "2023-24", "kickoff"].min())
    poisoned = matches.copy()
    later = poisoned["kickoff"] >= cut
    poisoned.loc[later, "home_goals"] = 9
    poisoned.loc[later, "away_goals"] = 0
    clean = fit_dixon_coles(matches, as_of=cut)
    dirty = fit_dixon_coles(poisoned, as_of=cut)
    assert clean.attack == dirty.attack
    assert clean.defence == dirty.defence
    assert clean.home_advantage == pytest.approx(dirty.home_advantage)


def test_a_fit_with_no_history_is_refused() -> None:
    matches = _matches()
    with pytest.raises(ExperimentExecutionError, match="kicked off before"):
        fit_dixon_coles(matches, as_of=pd.Timestamp("2000-01-01", tz="UTC"))


def test_promoted_clubs_are_the_ones_absent_from_the_season_before() -> None:
    promoted = promoted_clubs(_matches())
    assert promoted["2022-23"] == (6,)
    assert promoted["2023-24"] == ()
    assert "2021-22" not in promoted


def test_the_promoted_prior_is_measured_from_seasons_already_played() -> None:
    matches = _matches()
    attack, defence = measure_promoted_prior(matches, ("2021-22", "2022-23"))
    # Club 6 is the weakest club in the league and the only promoted one.
    assert attack < 0.0
    assert defence < 0.0
    assert measure_promoted_prior(matches, ("2021-22",)) == (0.0, 0.0)


def test_an_unseen_club_falls_back_to_the_promoted_prior() -> None:
    rating = TeamRating(
        as_of=pd.Timestamp("2023-01-01", tz="UTC"),
        attack={1: 0.5},
        defence={1: 0.4},
        home_advantage=0.2,
        rho=0.0,
        matches_used=10,
        promoted_attack_prior=-0.3,
        promoted_defence_prior=-0.4,
    )
    assert rating.attack_of(99) == pytest.approx(-0.3)
    assert rating.defence_of(99) == pytest.approx(-0.4)
    home, away = rating.expected_goals(1, 99)
    assert home > away


def test_the_promoted_prior_moves_a_club_with_no_matches() -> None:
    matches = _matches()
    as_of = pd.Timestamp(matches["kickoff"].max()) + pd.Timedelta(days=1)
    rating = fit_dixon_coles(matches, as_of=as_of, promoted_prior=(-0.4, -0.5), newly_promoted=(7,))
    # Club 7 never played, so it is not in the fit and reads the prior instead.
    assert 7 not in rating.attack
    assert rating.attack_of(7) == pytest.approx(-0.4)


def test_the_score_matrix_is_a_distribution_and_respects_the_correction() -> None:
    matches = _matches()
    as_of = pd.Timestamp(matches["kickoff"].max()) + pd.Timedelta(days=1)
    rating = fit_dixon_coles(matches, as_of=as_of)
    matrix = rating.score_matrix(1, 4)
    assert matrix.shape == (MAXIMUM_GOALS + 1, MAXIMUM_GOALS + 1)
    assert float(matrix.sum()) == pytest.approx(1.0)
    assert (matrix >= 0.0).all()


def test_a_clean_sheet_probability_is_larger_against_a_weaker_attack() -> None:
    matches = _matches()
    as_of = pd.Timestamp(matches["kickoff"].max()) + pd.Timedelta(days=1)
    rating = fit_dixon_coles(matches, as_of=as_of, config=DixonColesConfig(ridge=0.2))
    strong_opponent = rating.clean_sheet_probability(3, 1, is_home=True)
    weak_opponent = rating.clean_sheet_probability(3, 6, is_home=True)
    assert weak_opponent > strong_opponent
    assert 0.0 < strong_opponent < 1.0


def test_home_and_away_clean_sheets_differ_for_the_same_pair() -> None:
    matches = _matches()
    as_of = pd.Timestamp(matches["kickoff"].max()) + pd.Timedelta(days=1)
    rating = fit_dixon_coles(matches, as_of=as_of)
    at_home = rating.clean_sheet_probability(3, 4, is_home=True)
    away = rating.clean_sheet_probability(3, 4, is_home=False)
    assert at_home != pytest.approx(away)


def test_a_shorter_half_life_forgets_faster() -> None:
    matches = _matches()
    as_of = pd.Timestamp(matches["kickoff"].max()) + pd.Timedelta(days=1)
    long_memory = fit_dixon_coles(
        matches, as_of=as_of, config=DixonColesConfig(half_life_days=900.0)
    )
    short_memory = fit_dixon_coles(
        matches, as_of=as_of, config=DixonColesConfig(half_life_days=30.0)
    )
    assert long_memory.matches_used == short_memory.matches_used
    assert long_memory.attack != short_memory.attack


def test_walk_forward_likelihood_is_finite_and_negative() -> None:
    matches = _matches()
    value = walk_forward_log_likelihood(
        matches, ("2022-23", "2023-24"), DixonColesConfig(), first_gameweek=3
    )
    assert math.isfinite(value)
    assert value < 0.0


def test_the_clean_sheet_calibration_returns_a_usable_pair() -> None:
    matches = _matches()
    intercept, slope = fit_clean_sheet_calibration(
        matches, ("2022-23", "2023-24"), DixonColesConfig(), first_gameweek=3
    )
    assert math.isfinite(intercept)
    assert math.isfinite(slope)
    assert fit_clean_sheet_calibration(matches, (), DixonColesConfig(), first_gameweek=3) == (
        0.0,
        1.0,
    )


def _card(**overrides: object) -> SeasonScorecard:
    settings: dict[str, object] = {
        "season": "2022-23",
        "fixtures": 300,
        "rating_log_likelihood": -3.0,
        "baseline_log_likelihood": -3.1,
        "rating_clean_sheet_brier": 0.17,
        "uncalibrated_clean_sheet_brier": 0.18,
        "published_clean_sheet_brier": 0.19,
        "rating_attacking_correlation": 0.06,
        "published_attacking_correlation": 0.02,
        "rating_defensive_correlation": 0.07,
        "published_defensive_correlation": 0.05,
        "mean_clean_sheet_probability": 0.25,
        "realized_clean_sheet_rate": 0.24,
        "refits": 33,
    }
    settings.update(overrides)
    return SeasonScorecard(**settings)  # type: ignore[arg-type]


def _pooled(**overrides: float) -> dict[str, float]:
    values = {
        "log_likelihood_improvement": 0.1,
        "brier_improvement": 0.01,
        "rating_attacking_correlation": 0.06,
        "published_attacking_correlation": 0.02,
        "rating_defensive_correlation": 0.07,
        "published_defensive_correlation": 0.05,
    }
    values.update(overrides)
    return values


_INTERVALS = {
    "log_likelihood_improvement": (0.05, 0.15),
    "brier_improvement": (0.002, 0.02),
}


def test_the_gate_passes_when_all_three_conditions_hold() -> None:
    verdict = rating_gate_verdict([_card(), _card(season="2023-24")], _pooled(), _INTERVALS)
    assert verdict["passes"] is True
    assert verdict["goals_passes"] is True
    assert verdict["clean_sheets_passes"] is True
    assert verdict["players_passes"] is True


def test_one_season_worse_at_goals_fails_the_gate() -> None:
    cards = [_card(), _card(season="2023-24", rating_log_likelihood=-3.2)]
    verdict = rating_gate_verdict(cards, _pooled(), _INTERVALS)
    assert verdict["goals_sign_consistent"] is False
    assert verdict["passes"] is False


def test_a_goal_interval_touching_zero_fails_the_gate() -> None:
    intervals = {**_INTERVALS, "log_likelihood_improvement": (-0.01, 0.2)}
    verdict = rating_gate_verdict([_card(), _card(season="2023-24")], _pooled(), intervals)
    assert verdict["goals_interval_excludes_zero"] is False
    assert verdict["passes"] is False


def test_clean_sheets_need_more_than_a_pooled_win() -> None:
    """Three seasons, one better and two worse: pooled positive is not enough."""

    cards = [
        _card(season="2022-23", rating_clean_sheet_brier=0.20),
        _card(season="2023-24", rating_clean_sheet_brier=0.10),
        _card(season="2024-25", rating_clean_sheet_brier=0.20),
    ]
    verdict = rating_gate_verdict(cards, _pooled(brier_improvement=0.005), _INTERVALS)
    assert verdict["clean_sheet_seasons_better"] == 1
    assert verdict["clean_sheets_passes"] is False
    assert verdict["passes"] is False


def test_a_worse_ordering_on_either_side_fails_the_gate() -> None:
    cards = [_card(), _card(season="2023-24")]
    attacking = rating_gate_verdict(cards, _pooled(rating_attacking_correlation=0.01), _INTERVALS)
    assert attacking["players_passes"] is False
    defensive = rating_gate_verdict(cards, _pooled(rating_defensive_correlation=0.01), _INTERVALS)
    assert defensive["players_passes"] is False


def test_the_gate_needs_at_least_one_season() -> None:
    verdict = rating_gate_verdict([], _pooled(), _INTERVALS)
    assert verdict["passes"] is False
