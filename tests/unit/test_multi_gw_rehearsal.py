"""Synthetic tests for the multi-gameweek planning rehearsal.

The rehearsal must compare the planner and the myopic baseline under one fairness
frame: same decision-time candidate pool, same starting squad, same realized scoring.
Blank and double gameweeks flow in through known fixture counts, which is exactly
where a multi-week plan can differ from a week-at-a-time one.
"""

import pandas as pd
import pytest
from tests.fixtures.synthetic_gameweeks import SEASON, TEAM_COUNT, make_canonical_gameweeks

from squadopt.experiments import (
    ExperimentExecutionError,
    MultiGwRehearsal,
    MultiGwRehearsalConfig,
    RehearsalWindowResult,
)
from squadopt.optimization import optimize_squad
from squadopt.planning import InitialSquadState

CONFIG = MultiGwRehearsalConfig(
    season=SEASON,
    horizon_length=3,
    candidate_pool_per_position=10,
    cheap_pool_per_position=2,
)


def _fixture_counts() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for gameweek in range(1, 9):
        for team_id in range(1, TEAM_COUNT + 1):
            count = 1
            if gameweek == 4 and team_id == 1:
                count = 2
            if gameweek == 4 and team_id == 6:
                count = 0
            rows.append({"gameweek": gameweek, "team_id": team_id, "fixture_count": count})
    return pd.DataFrame(rows)


def _rehearsal() -> MultiGwRehearsal:
    return MultiGwRehearsal(make_canonical_gameweeks(), _fixture_counts(), CONFIG)


@pytest.fixture(scope="module")
def window() -> RehearsalWindowResult:
    return _rehearsal().rehearse_window(3)


def test_the_window_scores_both_strategies_on_identical_terms(
    window: RehearsalWindowResult,
) -> None:
    assert window.gameweeks == (3, 4, 5)
    assert window.candidate_pool_size <= 36
    assert window.planned_net_points == (
        window.planned_realized_points - window.planned_transfer_hit_points
    )
    assert window.planning_advantage_points == (
        window.planned_net_points - window.myopic_net_points
    )
    assert len(window.horizon_fingerprint) == 64


def test_the_rehearsal_is_deterministic(window: RehearsalWindowResult) -> None:
    repeat = _rehearsal().rehearse_window(3)

    assert repeat.planned_realized_points == window.planned_realized_points
    assert repeat.myopic_realized_points == window.myopic_realized_points
    assert repeat.horizon_fingerprint == window.horizon_fingerprint


def test_blank_and_double_gameweeks_shape_the_horizon() -> None:
    rehearsal = _rehearsal()
    pool = rehearsal._candidate_pool(rehearsal._projection_at(3))
    horizon = rehearsal._naive_horizon(pool, (3, 4))

    week_four = horizon.table.loc[horizon.table["gameweek"] == 4]
    blank_rows = week_four.loc[week_four["team_id"] == 6]
    double_rows = week_four.loc[week_four["team_id"] == 1]
    single_rows = horizon.table.loc[
        (horizon.table["gameweek"] == 3) & (horizon.table["team_id"] == 1)
    ]
    assert not blank_rows.empty and (blank_rows["expected_points"] == 0.0).all()
    assert not double_rows.empty and (double_rows["fixture_count"] == 2).all()
    merged = double_rows.merge(single_rows, on="player_id", suffixes=("_dgw", "_sgw"))
    assert (merged["expected_points_dgw"] == 2.0 * merged["expected_points_sgw"]).all()


def test_a_window_leaving_the_season_is_refused() -> None:
    with pytest.raises(ExperimentExecutionError, match="leaves the season"):
        _rehearsal().rehearse_window(7)


def test_missing_fixture_columns_are_refused() -> None:
    with pytest.raises(ExperimentExecutionError, match="missing required columns"):
        MultiGwRehearsal(
            make_canonical_gameweeks(),
            _fixture_counts().drop(columns="fixture_count"),
            CONFIG,
        )


def test_an_unknown_season_is_refused() -> None:
    with pytest.raises(ExperimentExecutionError, match="absent from the panel"):
        MultiGwRehearsal(
            make_canonical_gameweeks(),
            _fixture_counts(),
            MultiGwRehearsalConfig(season="1999-00"),
        )


def test_a_blank_gameweek_absent_from_the_panel_still_scores_both_strategies() -> None:
    """The archive records appearances, not absences: a blank team has no rows.

    The planner carries the pool through the window, but the myopic baseline
    re-projects each week from the panel, so a blank team's players vanish from its
    table while the squad still holds them. The rehearsal must carry those rows at a
    zero projection and score a blank starter as zero rather than fail the window.
    """

    panel = make_canonical_gameweeks()
    absent = panel.loc[~((panel["gameweek"] == 4) & (panel["team_id"] == 6))]
    assert len(absent) < len(panel)

    window = MultiGwRehearsal(absent, _fixture_counts(), CONFIG).rehearse_window(3)

    assert window.gameweeks == (3, 4, 5)
    assert window.myopic_realized_points >= 0.0
    assert window.planned_realized_points >= 0.0


def test_a_pool_player_missing_without_a_blank_is_refused() -> None:
    """A row missing while the team plays is a data hole, not a blank, and says so."""

    panel = make_canonical_gameweeks()
    rehearsal = MultiGwRehearsal(panel, _fixture_counts(), CONFIG)
    pool = rehearsal._candidate_pool(rehearsal._projection_at(3))
    victim = int(pool["player_id"].iloc[0])
    holed = panel.loc[~((panel["gameweek"] == 4) & (panel["player_id"] == victim))]

    with pytest.raises(
        ExperimentExecutionError,
        match=r"do not cover selected players|although their teams have fixtures",
    ):
        MultiGwRehearsal(holed, _fixture_counts(), CONFIG).rehearse_window(3)


def test_rolling_replan_is_off_by_default_and_reports_solver_statuses(
    window: RehearsalWindowResult,
) -> None:
    assert window.rolling_realized_points is None
    assert window.rolling_advantage_points is None
    assert window.diagnostics["planner_solver_status"] in {"OPTIMAL", "FEASIBLE"}
    assert len(list(window.diagnostics["myopic_solver_statuses"])) == len(window.gameweeks)


def test_a_rolling_horizon_of_one_week_is_the_myopic_baseline() -> None:
    """The identity that anchors the rolling planner: lookahead one re-derives myopic."""

    rehearsal = _rehearsal()
    pool = rehearsal._candidate_pool(rehearsal._projection_at(3))
    window = rehearsal.rehearse_window(3)

    opening = optimize_squad(pool, CONFIG.frozen_optimization_config)
    assert opening.total_cost_tenths is not None
    state = InitialSquadState(
        tuple(opening.selected_squad["player_id"].tolist()),
        bank_tenths=CONFIG.frozen_optimization_config.budget_tenths
        - int(opening.total_cost_tenths),
        free_transfers=1,
    )
    outcome = rehearsal._score_rolling(pool, state, window.gameweeks, lookahead=1)

    assert outcome.realized_points == window.myopic_realized_points
    assert outcome.hit_points == window.myopic_transfer_hit_points
    assert outcome.lookahead_lengths == (1, 1, 1)


def test_rolling_replan_scores_the_window_and_records_its_lookahead() -> None:
    config = MultiGwRehearsalConfig(
        season=SEASON,
        horizon_length=3,
        candidate_pool_per_position=10,
        cheap_pool_per_position=2,
        rolling_replan=True,
    )
    window = MultiGwRehearsal(
        make_canonical_gameweeks(), _fixture_counts(), config
    ).rehearse_window(3)

    assert window.rolling_realized_points is not None
    assert window.rolling_transfer_hit_points is not None
    assert window.rolling_advantage_points == (
        window.rolling_realized_points
        - window.rolling_transfer_hit_points
        - window.myopic_net_points
    )
    assert list(window.diagnostics["rolling_lookahead_gameweeks"]) == [3, 3, 3]
    assert len(list(window.diagnostics["rolling_solver_statuses"])) == 3


def test_a_rolling_lookahead_is_truncated_at_the_last_decision_gameweek() -> None:
    config = MultiGwRehearsalConfig(
        season=SEASON,
        horizon_length=3,
        candidate_pool_per_position=10,
        cheap_pool_per_position=2,
        rolling_replan=True,
    )
    rehearsal = MultiGwRehearsal(make_canonical_gameweeks(), _fixture_counts(), config)
    last = max(rehearsal.available_gameweeks)

    window = rehearsal.rehearse_window(last - 2)

    assert list(window.diagnostics["rolling_lookahead_gameweeks"]) == [3, 2, 1]


def test_a_rolling_lookahead_stops_at_a_gameweek_the_season_never_played() -> None:
    """A postponed round is not a blank: the lookahead ends there instead of skipping it."""

    panel = make_canonical_gameweeks()
    without_gw6 = panel.loc[panel["gameweek"] != 6]
    config = MultiGwRehearsalConfig(
        season=SEASON,
        horizon_length=3,
        candidate_pool_per_position=10,
        cheap_pool_per_position=2,
        rolling_replan=True,
    )
    rehearsal = MultiGwRehearsal(without_gw6, _fixture_counts(), config)

    window = rehearsal.rehearse_window(3)

    # Weeks 3, 4, 5: lookaheads 3-5, 4-5 (6 is missing), 5 alone.
    assert list(window.diagnostics["rolling_lookahead_gameweeks"]) == [3, 2, 1]
