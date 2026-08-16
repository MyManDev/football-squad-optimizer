"""Tests for the selection-optimism profile."""

import pytest
from tests.fixtures.synthetic_gameweeks import SEASON, make_canonical_gameweeks

from squadopt.experiments import (
    ExperimentExecutionError,
    PolicyObjectiveConfig,
    measure_selection_optimism,
)

CONFIG = PolicyObjectiveConfig(development_seasons=(SEASON,))


def test_the_profile_measures_selected_versus_roster_residuals() -> None:
    result = measure_selection_optimism(make_canonical_gameweeks(), CONFIG, form_window=5)

    assert result.fold_count == 7
    assert result.selection_gap_per_starter == pytest.approx(
        result.starter_mean_residual - result.roster_mean_residual
    )
    assert result.diagnostics["starter_observations"] == 7 * 11
    assert set(result.position_starter_mean_residuals) <= {"GK", "DEF", "MID", "FWD"}
    assert set(result.rank_bucket_mean_residuals) == {"top_05", "rank_06_15", "rank_16_plus"}


def test_the_profile_is_deterministic() -> None:
    first = measure_selection_optimism(make_canonical_gameweeks(), CONFIG, form_window=5)
    second = measure_selection_optimism(make_canonical_gameweeks(), CONFIG, form_window=5)

    assert first.selection_gap_per_starter == second.selection_gap_per_starter
    assert first.mean_realized_xi_score == second.mean_realized_xi_score


def test_an_unknown_season_is_refused() -> None:
    with pytest.raises(ExperimentExecutionError, match="absent from the panel"):
        measure_selection_optimism(
            make_canonical_gameweeks(),
            PolicyObjectiveConfig(development_seasons=("1999-00",)),
        )
