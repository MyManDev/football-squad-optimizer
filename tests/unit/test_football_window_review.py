"""Common football worlds aggregate doubles/blanks without perfect-information choices."""

from dataclasses import replace

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal
from tests.unit.test_football_development import (
    football_fixture as synthetic_football,  # noqa: F401
)

from squadopt.application.football_window_review import review_football_window
from squadopt.live.football_horizon import build_football_horizon
from squadopt.optimization import OptimizationConfig
from squadopt.planning import InitialSquadState, optimize_transfer_plan
from squadopt.planning.horizon import to_planning_horizon


@pytest.mark.parametrize("window", [3, 5])
# ruff: noqa: F811
def test_common_worlds_full_window_blanks_doubles_and_missing_components(
    synthetic_football, window
):
    model, history, roster, fixtures, _ = synthetic_football
    extra = fixtures.loc[fixtures.GW.eq(17)].assign(fixture=lambda d: d.fixture + 1000)
    frames = [fixtures, extra]
    for week in range(19, 16 + window):
        frames.append(
            fixtures.loc[fixtures.GW.eq(18)].assign(
                GW=week, fixture=lambda d, week=week: d.fixture + week * 100
            )
        )
    horizon, components = build_football_horizon(
        model,
        history,
        roster,
        pd.concat(frames, ignore_index=True),
        gameweeks=tuple(range(16, 16 + window)),
        season="2025-26",
        source_snapshot_id="synthetic-only-no-archive",
        captured_at=model.cutoff,
    )
    selected = pd.concat(
        [
            roster.loc[roster.position.eq(pos)].head(n)
            for pos, n in {"GK": 2, "DEF": 5, "MID": 5, "FWD": 3}.items()
        ]
    )
    plan = optimize_transfer_plan(
        to_planning_horizon(horizon),
        InitialSquadState(tuple(selected.player_id), 250, 1),
        OptimizationConfig(solver_time_limit_seconds=60, solver_deterministic_time_limit=3),
        linearization_level=2,
    )
    assert plan.has_solution
    review = review_football_window(
        components, horizon, {"a": plan, "same": plan}, samples=8, seed=31
    )
    again = review_football_window(
        components, horizon, {"a": plan, "same": plan}, samples=8, seed=31
    )
    assert_frame_equal(review.window_scores, again.window_scores)
    totals = review.window_scores.pivot(
        index="scenario_id", columns="candidate", values="net_points"
    )
    assert totals.a.equals(totals.same)
    assert len(review.weekly_scores) == window * 8 * 2
    assert (
        review.weekly_scores.loc[review.weekly_scores.gameweek.eq(16), "net_points"]
        .eq(-plan.weeks[0].transfer_hit_points)
        .all()
    )
    assert review.component_diagnostics[17]["player_fixtures"] == len(roster) * 2
    assert "total_points_mean_gap" in review.component_diagnostics[17]
    with pytest.raises(ValueError, match="every scheduled"):
        review_football_window(components.iloc[1:], horizon, {"a": plan}, samples=8)
    with pytest.raises(ValueError, match="same window"):
        review_football_window(
            components, horizon, {"a": replace(plan, weeks=plan.weeks[:-1])}, samples=8
        )
