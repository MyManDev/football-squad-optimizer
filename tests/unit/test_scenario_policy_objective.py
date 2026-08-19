"""Synthetic tests for the scenario-based three-factor policy objective.

The panel and residual history are small and synthetic, but every evaluation runs the
real chain: scenario generation from strictly-prior residuals, scenario-aware CP-SAT
optimization under the candidate's risk aversion, and realized scoring of the frozen
decision. The leakage rule - only earlier folds feed a fold's scenarios - is the
point of most tests here.
"""

import pandas as pd
import pytest
from tests.fixtures.synthetic_gameweeks import SEASON, make_canonical_gameweeks

from squadopt.bayesopt import (
    BayesianCandidate,
    BayesianFactor,
    BayesianOptimizationConfig,
    FactorKind,
    run_bayesian_optimization,
)
from squadopt.experiments import (
    ExperimentExecutionError,
    ScenarioPolicyObjective,
    ScenarioPolicyObjectiveConfig,
)

CONFIG = ScenarioPolicyObjectiveConfig(
    development_seasons=(SEASON,),
    scenario_count=32,
    min_history_folds=3,
    min_player_observations=2,
)

HISTORY_GAMEWEEKS = (2, 3, 4, 5, 6)


def _history() -> pd.DataFrame:
    panel = make_canonical_gameweeks()
    rows: list[dict[str, object]] = []
    for gameweek in HISTORY_GAMEWEEKS:
        week = panel.loc[panel["gameweek"] == gameweek]
        for row in week.itertuples(index=False):
            predicted = 2.5 + (int(row.player_id) % 4) * 0.5
            rows.append(
                {
                    "fold_id": f"{SEASON}-gw{gameweek:02d}",
                    "season": SEASON,
                    "gameweek": gameweek,
                    "player_id": int(row.player_id),
                    "team_id": int(row.team_id),
                    "position": str(row.position),
                    "predicted_points": predicted,
                    "realized_points": float(row.total_points),
                    "residual": float(row.total_points) - predicted,
                }
            )
    return pd.DataFrame(rows)


def _objective() -> ScenarioPolicyObjective:
    return ScenarioPolicyObjective(make_canonical_gameweeks(), _history(), CONFIG)


def _candidate(
    form_window: int = 5,
    bench_weight: float = 0.1,
    risk_aversion: float = 0.2,
) -> BayesianCandidate:
    return BayesianCandidate(
        {
            "form_window": form_window,
            "bench_weight": bench_weight,
            "risk_aversion": risk_aversion,
        }
    )


# --- eligibility and leakage -------------------------------------------------


def test_only_folds_with_enough_prior_history_are_eligible() -> None:
    """gw2..gw4 have fewer than three earlier history folds and must be excluded."""

    objective = _objective()

    assert objective.development_fold_ids == tuple(
        f"{SEASON}-gw{gameweek:02d}" for gameweek in (5, 6, 7, 8)
    )


def test_history_naming_unknown_folds_is_refused() -> None:
    history = _history()
    history.loc[history.index[:1], "fold_id"] = "2030-31-gw02"

    with pytest.raises(ExperimentExecutionError, match="one fold policy"):
        ScenarioPolicyObjective(make_canonical_gameweeks(), history, CONFIG)


def test_no_eligible_fold_is_an_error_not_an_empty_run() -> None:
    config = ScenarioPolicyObjectiveConfig(
        development_seasons=(SEASON,),
        scenario_count=32,
        min_history_folds=10,
        min_player_observations=2,
    )

    with pytest.raises(ExperimentExecutionError, match="enough prior residual history"):
        ScenarioPolicyObjective(make_canonical_gameweeks(), _history(), config)


# --- the three-factor contract -----------------------------------------------


def test_risk_aversion_is_a_required_live_factor() -> None:
    objective = _objective()
    candidate = BayesianCandidate({"form_window": 5, "bench_weight": 0.1})

    with pytest.raises(ExperimentExecutionError, match="missing"):
        objective(candidate, objective.development_fold_ids)


def test_an_out_of_domain_risk_aversion_is_refused() -> None:
    objective = _objective()

    with pytest.raises(ExperimentExecutionError, match="risk_aversion"):
        objective(_candidate(risk_aversion=1.5), objective.development_fold_ids)


def test_foreign_fold_ids_are_refused() -> None:
    objective = _objective()

    with pytest.raises(ExperimentExecutionError, match="same inputs"):
        objective(_candidate(), (f"{SEASON}-gw02",))


# --- evaluation behavior -----------------------------------------------------


def test_one_evaluation_is_deterministic_across_instances() -> None:
    first = _objective()
    second = _objective()
    candidate = _candidate()

    first_value = first(candidate, first.development_fold_ids)
    second_value = second(candidate, second.development_fold_ids)

    assert first_value == second_value
    record = first.records[candidate.candidate_id]
    assert record["risk_aversion"] == 0.2
    assert record["scored_folds"] == 4
    assert record["mean_realized_squad_points"] == first_value


def test_risk_neutral_and_risk_averse_candidates_are_evaluated_separately() -> None:
    objective = _objective()

    neutral = objective(_candidate(risk_aversion=0.0), objective.development_fold_ids)
    averse = objective(_candidate(risk_aversion=1.0), objective.development_fold_ids)

    assert len(objective.records) == 2
    assert all(isinstance(value, float) for value in (neutral, averse))


# --- the objective under the real search loop --------------------------------


@pytest.mark.slow
def test_the_three_factor_search_runs_deterministically() -> None:
    search_config = BayesianOptimizationConfig(
        factors=(
            BayesianFactor("form_window", 3, 4, 1, FactorKind.INTEGER),
            BayesianFactor("bench_weight", 0.0, 0.05, 0.05),
            BayesianFactor("risk_aversion", 0.0, 1.0, 0.5),
        ),
        evaluation_budget=4,
        initial_design_size=2,
    )

    first = run_bayesian_optimization(
        _objective(), _objective().development_fold_ids, search_config
    )
    second = run_bayesian_optimization(
        _objective(), _objective().development_fold_ids, search_config
    )

    assert first.run_fingerprint == second.run_fingerprint
    assert {"form_window", "bench_weight", "risk_aversion"} == set(
        first.recommended_candidate.values
    )
