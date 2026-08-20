"""The clean-sheet re-measurement: the table baseline, the fills, and the gate frame.

Synthetic leagues reusing the team-rating test generator's idea — the point is the
walk-forward legality of the baseline and the promoted fill, not the football.
"""

import math

import numpy as np
import pandas as pd
import pytest

from squadopt.experiments.config import ExperimentConfigurationError, ExperimentExecutionError
from squadopt.experiments.team_rating_cs import (
    CsRemeasureConfig,
    fit_table_baseline,
    previous_season_points,
    promoted_points_fill,
)

STRENGTHS = {1: 0.6, 2: 0.3, 3: 0.0, 4: -0.3, 5: -0.6, 6: -0.9}


def _league(season: str, clubs: tuple[int, ...], *, start: str, seed: int, rounds: int = 4):
    generator = np.random.default_rng(seed)
    rows = []
    day = pd.Timestamp(start, tz="UTC")
    game = 0
    for _ in range(rounds):
        for home in clubs:
            for away in clubs:
                if home == away:
                    continue
                game += 1
                home_rate = math.exp(0.25 + STRENGTHS[home] - STRENGTHS[away])
                away_rate = math.exp(STRENGTHS[away] - STRENGTHS[home])
                rows.append(
                    {
                        "season": season,
                        "gameweek": 1 + (game // len(clubs)),
                        "kickoff": day + pd.Timedelta(days=game),
                        "home_club": home,
                        "away_club": away,
                        "home_goals": int(generator.poisson(home_rate)),
                        "away_goals": int(generator.poisson(away_rate)),
                        "home_difficulty": 3.0,
                        "away_difficulty": 3.0,
                    }
                )
    return pd.DataFrame(rows)


def _matches() -> pd.DataFrame:
    return pd.concat(
        [
            _league("2021-22", (1, 2, 3, 4, 5), start="2021-08-01", seed=1),
            _league("2022-23", (1, 2, 3, 4, 6), start="2022-08-01", seed=2),
            _league("2023-24", (1, 2, 3, 4, 6), start="2023-08-01", seed=3),
        ],
        ignore_index=True,
    )


def test_the_locked_holdout_is_refused_by_configuration() -> None:
    with pytest.raises(ExperimentConfigurationError, match="locked holdout"):
        CsRemeasureConfig(seasons=("2024-25", "2025-26"), evaluated_seasons=("2024-25",))


def test_previous_season_points_pair_a_season_with_the_table_before_it() -> None:
    matches = _matches()
    points = previous_season_points(matches, "2022-23", promoted_fill=7.5)
    # Club 6 is new in 2022-23: it has no 2021-22 table row and carries the fill.
    assert points[6] == 7.5
    # Club 1 is the strongest and must out-point club 4 in the previous table.
    assert points[1] > points[4]
    # Club 5 left the league; the mapping covers the *current* season's clubs only.
    assert 5 not in points


def test_the_first_season_has_no_previous_table() -> None:
    with pytest.raises(ExperimentExecutionError, match="no previous season"):
        previous_season_points(_matches(), "2021-22", promoted_fill=0.0)


def test_the_promoted_fill_is_measured_from_what_promoted_clubs_earned() -> None:
    matches = _matches()
    fill = promoted_points_fill(matches, ("2021-22", "2022-23"))
    # Club 6 (the only promotion) is the weakest side; its earned points sit well below
    # the strongest club's, and the fill is exactly its 2022-23 total.
    from squadopt.experiments.team_rating_cs import _league_points

    table = _league_points(matches.loc[matches["season"] == "2022-23"])
    assert fill == pytest.approx(float(table.get(6, 0.0)))
    assert promoted_points_fill(matches, ("2021-22",)) == 0.0


def test_the_table_baseline_learns_that_strong_opponents_mean_fewer_clean_sheets() -> None:
    matches = _matches()
    intercept, slope, venue = fit_table_baseline(
        matches, ("2021-22", "2022-23"), promoted_fill=10.0
    )
    # More opponent points -> harder to keep them out -> the slope must be negative.
    assert slope < 0.0
    assert math.isfinite(intercept) and math.isfinite(venue)


def test_the_baseline_refuses_a_frame_with_no_usable_training_season() -> None:
    matches = _matches().loc[lambda f: f["season"] == "2021-22"]
    with pytest.raises(ExperimentExecutionError, match="previous-season table"):
        fit_table_baseline(matches, ("2021-22",), promoted_fill=0.0)


def test_the_study_runs_and_applies_the_declared_gate_frame() -> None:
    matches = _matches()  # noqa: F841 - documents what the archive stand-in would hold
    config = CsRemeasureConfig(
        seasons=("2021-22", "2022-23", "2023-24"),
        evaluated_seasons=("2023-24",),
        first_evaluated_gameweek=3,
    )
    # The study reads the archive layout; wire the synthetic frame through a stub root.
    import squadopt.experiments.team_rating_cs as module

    original = module.load_match_results
    try:
        module.load_match_results = lambda root, seasons: _matches()  # type: ignore[assignment]
        study = module.run_cs_remeasure("unused", config)
    finally:
        module.load_match_results = original  # type: ignore[assignment]
    assert study.seasons[0].season == "2023-24"
    assert study.seasons[0].fixture_sides > 0
    assert set(study.verdict) >= {"pooled_improvement", "seasons_better", "passes", "note"}
    assert "does not reopen" in str(study.verdict["note"])
