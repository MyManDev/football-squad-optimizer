"""Tests for the scenario calibration audit.

The audit's job is honest bookkeeping: the frozen decision must never depend on the
scenarios it is measured against, PIT and coverage must come from the recorded
distributions, and the fold population must be exactly the objective's own.
"""

import pandas as pd
import pytest
from tests.fixtures.synthetic_gameweeks import SEASON, make_canonical_gameweeks

from squadopt.experiments import (
    ExperimentExecutionError,
    ScenarioAuditResult,
    ScenarioPolicyObjective,
    ScenarioPolicyObjectiveConfig,
    audit_scenario_calibration,
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


@pytest.fixture(scope="module")
def audit() -> ScenarioAuditResult:
    return audit_scenario_calibration(
        _objective(),
        _history(),
        form_window=5,
        bench_weight=0.1,
        points_threshold=30.0,
    )


def test_the_audit_covers_exactly_the_objectives_folds(audit: ScenarioAuditResult) -> None:
    objective = _objective()

    assert tuple(row.fold_id for row in audit.rows) == objective.development_fold_ids
    assert audit.diagnostics["fold_count"] == 4


def test_pit_and_rates_are_probabilities(audit: ScenarioAuditResult) -> None:
    for row in audit.rows:
        assert 0.0 <= row.probability_integral_transform <= 1.0
    assert 0.0 <= audit.mean_pit <= 1.0
    assert 0.0 <= audit.realized_below_scenario_quantile_rate <= 1.0
    assert 0.0 <= audit.predicted_bad_week_probability <= 1.0
    assert 0.0 <= audit.realized_bad_week_frequency <= 1.0


def test_player_coverage_is_reported_per_position(audit: ScenarioAuditResult) -> None:
    assert set(audit.player_interval_coverage) <= {"GK", "DEF", "MID", "FWD"}
    assert audit.player_interval_coverage
    for coverage in audit.player_interval_coverage.values():
        assert 0.0 <= coverage <= 1.0


def test_the_audit_is_deterministic(audit: ScenarioAuditResult) -> None:
    repeat = audit_scenario_calibration(
        _objective(),
        _history(),
        form_window=5,
        bench_weight=0.1,
        points_threshold=30.0,
    )

    assert [
        (row.fold_id, row.realized_score, row.probability_integral_transform) for row in repeat.rows
    ] == [
        (row.fold_id, row.realized_score, row.probability_integral_transform) for row in audit.rows
    ]
    assert repeat.mean_pit == audit.mean_pit


def test_an_out_of_range_quantile_is_refused() -> None:
    with pytest.raises(ExperimentExecutionError, match="lower_quantile"):
        audit_scenario_calibration(
            _objective(),
            _history(),
            form_window=5,
            bench_weight=0.1,
            lower_quantile=1.5,
        )


def test_a_non_objective_input_is_refused() -> None:
    with pytest.raises(ExperimentExecutionError, match="ScenarioPolicyObjective"):
        audit_scenario_calibration(
            "not an objective",  # type: ignore[arg-type]
            _history(),
            form_window=5,
            bench_weight=0.1,
        )
