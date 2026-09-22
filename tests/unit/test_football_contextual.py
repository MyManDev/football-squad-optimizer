"""Contextual candidate invariants; synthetic evidence is not a performance backtest."""

import numpy as np
import pandas as pd
import pytest
from pandas.testing import assert_frame_equal
from tests.unit.test_football_development import football_fixture  # noqa: F401

from squadopt.application.football_candidate import preview_football_candidate
from squadopt.live.football_horizon import build_football_horizon
from squadopt.optimization import OptimizationConfig
from squadopt.planning import InitialSquadState
from squadopt.planning.horizon import to_planning_horizon
from squadopt.planning.models import TransferPlanningValidationError
from squadopt.prediction.football_contextual import (
    CONTEXTUAL_MODEL_VERSION,
    ContextualFootballModel,
)
from squadopt.prediction.football_strength import DynamicTeamStrength
from squadopt.scenarios.football import sample_football_events
from squadopt.scenarios.football_lineups import sample_intervals


@pytest.fixture(scope="module")
def contextual(football_fixture):  # noqa: F811
    baseline, history, roster, fixtures, training = football_fixture
    return (
        ContextualFootballModel(training, history, cutoff=baseline.cutoff),
        history,
        roster,
        fixtures,
    )


def build(contextual, roster=None):
    model, history, original, fixtures = contextual
    return build_football_horizon(
        model,
        history,
        original if roster is None else roster,
        fixtures,
        gameweeks=(16, 17, 18),
        season="2025-26",
        source_snapshot_id="synthetic",
        captured_at=model.cutoff,
    )


def test_dynamic_strength_counts_matches_once_and_ignores_row_order(contextual):
    model, history, _, fixtures = contextual
    repeated = pd.concat([history, history.sample(frac=1, random_state=2)], ignore_index=True)
    other = DynamicTeamStrength(repeated, cutoff=model.cutoff)
    assert_frame_equal(model.strength.predict(fixtures), other.predict(fixtures))
    forecast = model.strength.predict(fixtures)
    assert (forecast > 0).all().all()
    with pytest.raises(ValueError, match="unavailable"):
        DynamicTeamStrength(history.assign(kickoff=model.cutoff), cutoff=model.cutoff)
    broken = history.copy()
    broken.loc[0, "team_goals"] = 99
    with pytest.raises(ValueError, match="Inconsistent"):
        DynamicTeamStrength(broken, cutoff=model.cutoff)


def test_availability_precedes_share_allocation_and_is_applied_once(contextual):
    _, _, roster, _ = contextual
    _, reference = build(contextual)
    adjusted_roster = roster.assign(availability_probability=1.0)
    player = int(roster.loc[roster.position.eq("FWD"), "player_id"].iloc[0])
    adjusted_roster.loc[adjusted_roster.player_id.eq(player), "availability_probability"] = 0
    _, adjusted = build(contextual, adjusted_roster)
    assert adjusted.loc[adjusted.player_code.eq(player), "expected_points"].eq(0).all()
    assert adjusted.loc[adjusted.player_code.eq(player), "goals_share"].eq(0).all()
    assert np.allclose(adjusted.groupby(["fixture", "club"]).goals_share.sum(), 1)
    assert np.allclose(
        reference.groupby(["fixture", "club"]).goals.sum(),
        adjusted.groupby(["fixture", "club"]).goals.sum(),
    )
    adjusted_roster.loc[adjusted_roster.player_id.eq(player), "availability_probability"] = 0.5
    _, half = build(contextual, adjusted_roster)
    assert np.allclose(
        half.loc[half.player_code.eq(player), "appearance_probability"],
        reference.loc[reference.player_code.eq(player), "appearance_probability"] / 2,
    )


def test_context_components_are_finite_and_probabilities_reach_planning(contextual):
    model, _, _, _ = contextual
    horizon, components = build(contextual)
    assert horizon.model_version == CONTEXTUAL_MODEL_VERSION
    assert model.dispersion_calibration_rows > 0
    assert np.allclose(components[[f"minute_probability_{b}" for b in range(4)]].sum(axis=1), 1)
    assert (components.clean_sheet_probability <= components.p60 + 1e-12).all()
    assert (components.defcon_probability <= components.appearance_probability + 1e-12).all()
    assert components.loc[components.position.eq("GK"), "defcon_probability"].eq(0).all()
    planning = to_planning_horizon(horizon)
    assert np.allclose(planning.table.appearance_probability, horizon.table.appearance_probability)
    assert horizon.table.loc[horizon.table.gameweek.eq(16), "appearance_probability"].eq(0).all()
    planning.table.loc[0, "appearance_probability"] = 0.5
    with pytest.raises(TransferPlanningValidationError, match="fingerprint"):
        planning.validated_copy()
    horizon.table.loc[0, "appearance_probability"] = 0.5
    with pytest.raises(TransferPlanningValidationError, match="changed"):
        horizon.assert_fingerprint()


def test_double_week_keeps_one_shared_health_state(contextual):
    model, history, roster, fixtures = contextual
    original = fixtures.loc[fixtures.GW.eq(17)]
    doubled = pd.concat(
        [
            original,
            original.assign(
                fixture=original.fixture + 10000, kickoff=original.kickoff + pd.Timedelta(days=1)
            ),
        ]
    )
    uncertain = roster.assign(availability_probability=0.5)
    horizon, parts = build_football_horizon(
        model,
        history,
        uncertain,
        doubled,
        gameweeks=(17,),
        season="2025-26",
        source_snapshot_id="synthetic-double",
        captured_at=model.cutoff,
    )
    expected = parts.groupby("player_code").appearance_probability.agg(
        lambda p: 0.5 * (1 - float((1 - p.to_numpy(float) / 0.5).prod()))
    )
    actual = horizon.table.set_index("player_id").appearance_probability
    assert np.allclose(actual, expected.reindex(actual.index))
    assert actual.le(0.5).all()
    assert horizon.table.fixture_count.eq(2).all()


def full_match_components():
    frames = []
    positions = ["GK"] * 2 + ["DEF"] * 7 + ["MID"] * 7 + ["FWD"] * 4
    for club in (1, 2):
        frame = pd.DataFrame({"player_code": np.arange(20) + club * 100, "position": positions})
        frame = frame.assign(
            season="2026-27",
            GW=5,
            fixture=1,
            club=club,
            opponent=3 - club,
            home=int(club == 1),
            team_goal_rate=2.0,
            opponent_goal_rate=2.0,
            team_goal_variance=0.5,
            opponent_goal_variance=0.5,
            start_probability=0.55,
            appearance_probability=0.8,
            expected_minutes=60.0,
            goals=0.1,
            assists=0.075,
            goals_share=0.05,
            assists_share=0.05,
            defcon_rate90=9.0,
            defcon_dispersion=10.0,
            residual_if_appearance=0.0,
        )
        for b, (p, minutes) in enumerate(zip((0.2, 0.25, 0.25, 0.3), (0, 30, 75, 90), strict=True)):
            frame[f"minute_probability_{b}"] = p
            frame[f"minute_value_{b}"] = minutes
        frames.append(frame)
    return pd.concat(frames, ignore_index=True)


def test_conditional_lineups_have_legal_occupancy_and_paired_substitutions():
    team = full_match_components().query("club == 1").copy()
    team.loc[team.player_code.eq(119), ["start_probability", "appearance_probability"]] = 0
    rng = np.random.default_rng(61)
    for _ in range(50):
        start, end = sample_intervals(team, rng)
        assert (end - start).sum() == 990
        assert ((start == 0) & (end > 0)).sum() == 11
        assert (start > 0).sum() <= 5
        assert end[-1] == 0
        for time in (0, 29.5, 60, 75.5, 89.9):
            active = (start <= time) & (time < end)
            assert active.sum() == 11
            assert team.loc[active, "position"].eq("GK").sum() == 1
    with pytest.raises(ValueError, match="complete eligible"):
        sample_intervals(team.iloc[:5], rng)


def test_contextual_worlds_conserve_goals_and_credit_cs_after_exit():
    components = full_match_components()
    draws = sample_football_events(components, samples=160, seed=32, coherent_lineups=True)
    repeated = sample_football_events(components, samples=160, seed=32, coherent_lineups=True)
    assert_frame_equal(draws.outcomes, repeated.outcomes)
    table = draws.outcomes.merge(
        components[["player_code", "club"]], left_on="player_id", right_on="player_code"
    )
    assert table.groupby(["scenario_id", "club"]).minutes.sum().eq(990).all()
    assert table.loc[table.minutes.eq(0), ["goals", "assists", "total_points"]].eq(0).all().all()
    assert table.loc[table.clean_sheet, "minutes"].ge(60).all()
    for row in draws.match_scores.itertuples():
        game = table.loc[table.scenario_id.eq(row.scenario_id)]
        assert game.loc[game.club.eq(1), "goals"].sum() == row.home_goals
        assert game.loc[game.club.eq(2), "goals"].sum() == row.away_goals
    conceded = draws.match_scores.set_index("scenario_id")
    opposition_goals = [
        conceded.loc[r.scenario_id, "away_goals" if r.club == 1 else "home_goals"]
        for r in table.itertuples()
    ]
    assert (table.clean_sheet & table.left_at.lt(90) & (np.array(opposition_goals) > 0)).any()


def test_joint_worlds_respect_certain_starts_and_source_minute_limits():
    team = full_match_components().query("club == 1").copy()
    team["minutes_limited"] = False
    team.loc[
        team.player_code.eq(102), ["start_probability", "appearance_probability", "minutes_limited"]
    ] = [1.0, 1.0, True]
    rng = np.random.default_rng(3)
    for _ in range(30):
        start, end = sample_intervals(team, rng)
        assert start[2] == 0 and 0 < end[2] < 90
        assert (end - start).sum() == 990
        assert (start > 0).sum() <= 5
    team["minutes_limited"] = True
    with pytest.raises(ValueError, match="minute limits"):
        sample_intervals(team, rng)


def test_contextual_model_to_legal_plan_and_shared_scenarios(contextual):
    model, history, original, fixtures = contextual
    positions = ["GK"] * 2 + ["DEF"] * 7 + ["MID"] * 7 + ["FWD"] * 4
    frames = []
    for club in sorted(original.club.unique()):
        frames.append(
            pd.DataFrame(
                {
                    "player_id": np.arange(20) + 1000 + int(club) * 20,
                    "position": positions,
                    "club": club,
                    "team_id": str(club),
                    "price_tenths": 50,
                }
            )
        )
    roster = pd.concat(frames, ignore_index=True)
    roster["name"] = roster.player_id.astype(str)
    # Official 2/5/5/3 composition, at most three players per club.
    selected = [
        1000,
        1020,
        1002,
        1022,
        1042,
        1062,
        1082,
        1049,
        1069,
        1089,
        1109,
        1129,
        1116,
        1136,
        1156,
    ]
    initial = InitialSquadState(tuple(selected), 250, 1)
    result = preview_football_candidate(
        model,
        history,
        roster,
        fixtures,
        initial,
        {p: 50 for p in selected},
        gameweeks=(17,),
        season="2025-26",
        source_snapshot_id="synthetic-complete-roster",
        captured_at=model.cutoff,
        optimization=OptimizationConfig(bench_weight=0, solver_time_limit_seconds=30),
        samples=4,
        seed=11,
        candidate_count=1,
        scenario_selection=True,
    )
    assert result.control.has_solution
    assert result.draws.contract_version == "shared_football_intervals_v2"
    assert len(result.decisions[result.recommendation].squad) == 15
    assert result.scenario_selection_evaluation["draws"] == 2
    assert result.scenario_mean_diagnostics["player_fixtures"] == 160
    clubs = result.draws.outcomes.merge(roster[["player_id", "club"]], on="player_id")
    assert clubs.groupby(["scenario_id", "club"]).minutes.sum().eq(990).all()
