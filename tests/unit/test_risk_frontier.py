"""Tests for the mean-versus-downside risk frontier measurement.

The synthetic world is the same one the scenario objective is tested on, so every
frontier point comes from real scenario-aware CP-SAT decisions; only the panel is
small. The frontier's job is bookkeeping honesty: identical folds per level, the
risk-neutral baseline always present, and downside metrics derived from the recorded
per-fold scores rather than re-computed elsewhere.
"""

import pandas as pd
import pytest
from tests.fixtures.synthetic_gameweeks import SEASON, make_canonical_gameweeks

from squadopt.experiments import (
    ExperimentExecutionError,
    RiskFrontierResult,
    ScenarioPolicyObjective,
    ScenarioPolicyObjectiveConfig,
    measure_risk_frontier,
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
def frontier() -> RiskFrontierResult:
    return measure_risk_frontier(
        _objective(),
        form_window=5,
        bench_weight=0.1,
        risk_aversion_levels=(0.0, 0.5, 1.0),
        points_threshold=30.0,
    )


def test_the_frontier_orders_levels_and_keeps_the_neutral_baseline(
    frontier: RiskFrontierResult,
) -> None:
    assert [point.risk_aversion for point in frontier.points] == [0.0, 0.5, 1.0]
    assert frontier.risk_neutral.risk_aversion == 0.0
    assert all(point.scored_folds == 4 for point in frontier.points)


def test_downside_metrics_come_from_the_recorded_fold_scores(
    frontier: RiskFrontierResult,
) -> None:
    for point in frontier.points:
        assert point.worst_tail_mean_score <= point.mean_realized_squad_points
        assert point.lower_quantile_score <= point.mean_realized_squad_points
        assert 0.0 <= point.probability_below_threshold <= 1.0


def test_the_frontier_is_deterministic() -> None:
    first = measure_risk_frontier(
        _objective(),
        form_window=5,
        bench_weight=0.1,
        risk_aversion_levels=(0.0, 1.0),
    )
    second = measure_risk_frontier(
        _objective(),
        form_window=5,
        bench_weight=0.1,
        risk_aversion_levels=(0.0, 1.0),
    )

    assert [
        (point.risk_aversion, point.mean_realized_squad_points, point.lower_quantile_score)
        for point in first.points
    ] == [
        (point.risk_aversion, point.mean_realized_squad_points, point.lower_quantile_score)
        for point in second.points
    ]


def test_a_ladder_without_the_neutral_baseline_is_refused() -> None:
    with pytest.raises(ExperimentExecutionError, match=r"risk-neutral 0\.0"):
        measure_risk_frontier(
            _objective(),
            form_window=5,
            bench_weight=0.1,
            risk_aversion_levels=(0.2, 0.5),
        )


def test_a_single_level_is_not_a_frontier() -> None:
    with pytest.raises(ExperimentExecutionError, match="at least two"):
        measure_risk_frontier(
            _objective(),
            form_window=5,
            bench_weight=0.1,
            risk_aversion_levels=(0.0,),
        )


def test_an_out_of_range_quantile_is_refused() -> None:
    with pytest.raises(ExperimentExecutionError, match="lower_quantile"):
        measure_risk_frontier(
            _objective(),
            form_window=5,
            bench_weight=0.1,
            risk_aversion_levels=(0.0, 0.5),
            lower_quantile=1.5,
        )
