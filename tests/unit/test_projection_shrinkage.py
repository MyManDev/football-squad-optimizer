"""Tests for decision-side projection shrinkage."""

import pandas as pd
import pytest
from tests.fixtures.synthetic_gameweeks import SEASON, make_canonical_gameweeks

from squadopt.bayesopt import BayesianCandidate
from squadopt.experiments import (
    BaselinePolicyObjective,
    ExperimentConfigurationError,
    PolicyObjectiveConfig,
    shrink_projections,
)


def _table() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "player_id": [1, 2, 3, 4],
            "name": ["A", "B", "C", "D"],
            "team_id": [1, 1, 2, 2],
            "position": ["MID", "MID", "FWD", "FWD"],
            "price_tenths": [50, 60, 70, 80],
            "expected_points": [2.0, 6.0, 3.0, 5.0],
        }
    )


def test_zero_strength_is_the_identity() -> None:
    table = _table()

    assert shrink_projections(table, 0.0) is table


def test_full_strength_collapses_to_position_means() -> None:
    shrunk = shrink_projections(_table(), 1.0)

    assert shrunk["expected_points"].tolist() == [4.0, 4.0, 4.0, 4.0]


def test_partial_strength_moves_extremes_toward_the_position_mean() -> None:
    shrunk = shrink_projections(_table(), 0.5)

    assert shrunk["expected_points"].tolist() == [3.0, 5.0, 3.5, 4.5]
    assert _table()["expected_points"].tolist() == [2.0, 6.0, 3.0, 5.0]


def test_an_out_of_range_strength_is_refused() -> None:
    with pytest.raises(ExperimentConfigurationError, match=r"\[0, 1\]"):
        shrink_projections(_table(), 1.5)
    with pytest.raises(ExperimentConfigurationError, match=r"\[0, 1\]"):
        PolicyObjectiveConfig(projection_shrinkage=-0.1)


def test_shrinkage_changes_the_fingerprint_and_the_evaluation_runs() -> None:
    plain = PolicyObjectiveConfig(development_seasons=(SEASON,))
    shrunk = PolicyObjectiveConfig(development_seasons=(SEASON,), projection_shrinkage=0.3)

    assert plain.configuration_fingerprint != shrunk.configuration_fingerprint

    objective = BaselinePolicyObjective(make_canonical_gameweeks(), shrunk)
    candidate = BayesianCandidate({"form_window": 5, "bench_weight": 0.1})
    value = objective(candidate, objective.development_fold_ids)

    assert isinstance(value, float)
    assert objective.records[candidate.candidate_id]["scored_folds"] == 7
