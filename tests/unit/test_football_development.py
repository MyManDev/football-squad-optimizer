"""Causal football candidate, shared match events, and observed recourse regressions."""

import json
from dataclasses import replace

import numpy as np
import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

from squadopt.application.football_candidate import preview_football_candidate
from squadopt.data.sources.fpl_live import live_event_outcomes
from squadopt.evaluation.models import FrozenSquadDecision
from squadopt.evaluation.scoring import score_frozen_squad_decision
from squadopt.live.football_horizon import build_football_horizon
from squadopt.optimization import InvalidConfigurationError, OptimizationConfig, optimize_squad
from squadopt.planning import InitialSquadState, PlanningHorizon
from squadopt.planning.models import TransferPlanningConfig
from squadopt.planning.recourse import ObservationNode, optimize_observed_recourse
from squadopt.prediction.football import FixtureFootballModel
from squadopt.prediction.football_features import football_features
from squadopt.scenarios.football import (
    FootballDraws,
    sample_football_events,
    score_football_candidates,
)


def frozen():
    positions = ["GK"] * 2 + ["DEF"] * 5 + ["MID"] * 5 + ["FWD"] * 3
    return FrozenSquadDecision(
        pd.DataFrame({"player_id": range(1, 16), "position": positions}),
        (1, 3, 4, 5, 8, 9, 10, 11, 13, 14, 15),
        (2, 12, 6, 7),
        13,
        8,
    )


def test_lp2_preserves_known_squad_objective_and_proves_both_stages(
    known_optimum_players, small_config
):
    control = optimize_squad(known_optimum_players, small_config)
    paired = optimize_squad(known_optimum_players, small_config, linearization_level=2)
    assert paired.objective_value == control.objective_value
    assert set(paired.selected_squad.player_id) == set(control.selected_squad.player_id)
    assert paired.captain.player_id == control.captain.player_id
    assert paired.diagnostics["tiebreak_completed"]
    assert paired.diagnostics["linearization_level"] == 2
    assert "linearization_level" not in control.diagnostics
    for invalid in (True, -1, 3, 1.1):
        with pytest.raises(InvalidConfigurationError, match="linearization_level"):
            optimize_squad(known_optimum_players, small_config, linearization_level=invalid)


@pytest.mark.parametrize("player", [1, 3, 13])
def test_carded_nonplaying_starter_is_not_autosubbed(player):
    outcome = pd.DataFrame(
        {"player_id": range(1, 16), "minutes": 90, "total_points": 2, "card_participation": False}
    )
    outcome.loc[outcome.player_id.eq(player), ["minutes", "total_points", "card_participation"]] = [
        0,
        -1,
        True,
    ]
    score = score_frozen_squad_decision(frozen(), outcome)
    assert score.total_points == 21
    assert player in score.final_xi
    assert not score.autosubs
    if player == 13:
        assert score.captain_bonus_player_id == 8


def test_carded_bench_player_enters_with_negative_points():
    outcome = pd.DataFrame(
        {"player_id": range(1, 16), "minutes": 90, "total_points": 2, "card_participation": False}
    )
    outcome.loc[outcome.player_id.eq(9), ["minutes", "total_points"]] = [0, 0]
    outcome.loc[outcome.player_id.eq(12), ["minutes", "total_points", "card_participation"]] = [
        0,
        -1,
        True,
    ]
    score = score_frozen_squad_decision(frozen(), outcome)
    assert score.total_points == 21 and score.autosubs == ((9, 12),)


def test_partial_scenario_and_duplicate_fixture_are_not_silently_zero_filled():
    first = pd.DataFrame(
        {
            "scenario_id": 0,
            "fixture": 1,
            "player_id": range(1, 16),
            "minutes": 90,
            "total_points": 2,
        }
    )
    complete = pd.concat([first, first.assign(scenario_id=1)], ignore_index=True)
    draws = FootballDraws(complete, pd.DataFrame(), 0)
    assert score_football_candidates(draws, {"control": frozen()}).net_points.eq(24).all()
    for broken in (complete.iloc[1:], pd.concat([complete, complete.iloc[:1]])):
        with pytest.raises(ValueError, match="coverage"):
            score_football_candidates(replace(draws, outcomes=broken), {"control": frozen()})


def test_live_adapter_retains_card_participation_without_changing_appearance():
    bootstrap = json.dumps({"elements": [{"id": 1, "code": 101}]}).encode()
    live = json.dumps(
        {
            "elements": [
                {
                    "id": 1,
                    "stats": {
                        "minutes": 0,
                        "starts": 0,
                        "total_points": -1,
                        "yellow_cards": 1,
                        "red_cards": 0,
                    },
                }
            ]
        }
    ).encode()
    outcome = live_event_outcomes(live, bootstrap, gameweek=2)
    assert outcome.iloc[0].card_participation
    assert not outcome.iloc[0].appearance
    assert outcome.iloc[0].total_points == -1 and outcome.iloc[0].minutes == 0


@pytest.fixture(scope="module")
def football_fixture():
    rng = np.random.default_rng(12)
    rows = []
    for week in range(1, 17):
        for club in range(8):
            for offset, position in enumerate(("GK", "DEF", "MID", "FWD")):
                minutes = int(rng.choice([0, 30, 75, 90], p=[0.2, 0.1, 0.2, 0.5]))
                goals = int(rng.poisson(minutes / 90 * 0.15))
                assists = int(rng.poisson(minutes / 90 * 0.12))
                dc = int(rng.poisson(minutes / 90 * 9))
                clean = int(minutes >= 60 and week % 3 == 0)
                points = float(
                    (minutes > 0) + (minutes >= 60) + goals * 5 + 3 * assists + clean * 2
                )
                rows.append(
                    dict(
                        season="2025-26",
                        GW=week,
                        rank=week,
                        fixture=week * 10 + club // 2,
                        player_code=club * 4 + offset + 1,
                        club=club,
                        opponent=club ^ 1,
                        home=float(club % 2 == 0),
                        position=position,
                        kickoff=pd.Timestamp("2025-08-01", tz="UTC") + pd.Timedelta(days=week * 7),
                        minutes=minutes,
                        appeared=float(minutes > 0),
                        long=float(minutes >= 60),
                        m_bin=0
                        if minutes == 0
                        else 1
                        if minutes < 60
                        else 2
                        if minutes < 90
                        else 3,
                        starts=float(minutes >= 60),
                        goals_scored=goals,
                        assists=assists,
                        expected_goals=minutes / 90 * 0.2,
                        expected_assists=minutes / 90 * 0.15,
                        clean_sheets=clean,
                        defensive_contribution=dc,
                        dc_event=float(dc >= (10 if position == "DEF" else 12)),
                        total_points=points,
                        team_goals=week % 3,
                        team_conceded=week % 3,
                    )
                )
    history = pd.DataFrame(rows)
    parts = []
    for week in range(3, 17):
        target = history.loc[history.GW.eq(week)]
        features = football_features(history.loc[history.GW.lt(week)], target, target.kickoff.min())
        train = pd.concat([target.drop(columns="home"), features], axis=1).assign(
            feature_cutoff=target.kickoff.min()
        )
        gc = train.position.map({"GK": 10, "DEF": 6, "MID": 5, "FWD": 4})
        cc = train.position.map({"GK": 4, "DEF": 4, "MID": 1, "FWD": 0})
        train["residual_target"] = train.total_points - (
            train.appeared
            + train.long
            + gc * train.goals_scored
            + 3 * train.assists
            + cc * train.clean_sheets
            + 2 * train.dc_event
        )
        parts.append(train)
    cutoff = history.kickoff.max() + pd.Timedelta(days=1)
    model = FixtureFootballModel(pd.concat(parts, ignore_index=True), history, cutoff=cutoff)
    roster = history.loc[history.GW.eq(16), ["player_code", "position", "club"]].rename(
        columns={"player_code": "player_id"}
    )
    roster = roster.assign(
        name=lambda d: d.player_id.astype(str),
        team_id=lambda d: d.club.astype(str),
        price_tenths=50,
    )
    fixtures = []
    for week in (17, 18):
        for club in range(8):
            fixtures.append(
                dict(
                    fixture=week * 10 + club // 2,
                    club=club,
                    opponent=club ^ 1,
                    home=float(club % 2 == 0),
                    GW=week,
                    kickoff=cutoff + pd.Timedelta(days=week - 15),
                )
            )
    return model, history, roster, pd.DataFrame(fixtures), pd.concat(parts, ignore_index=True)


def test_future_label_mutation_cannot_change_football_features(football_fixture):
    model, history, roster, fixtures, _ = football_fixture
    target = (
        roster.rename(columns={"player_id": "player_code"})
        .merge(fixtures, on="club")
        .assign(season="2025-26")
    )
    before = football_features(history, target, model.cutoff)
    after = football_features(
        history, target.assign(minutes=99, assists=99, total_points=-100), model.cutoff
    )
    assert_frame_equal(before, after)
    with pytest.raises(ValueError, match="unavailable"):
        football_features(history.assign(kickoff=model.cutoff), target, model.cutoff)


def test_blank_origin_does_not_zero_future_and_role_paths_are_versioned(football_fixture):
    model, history, roster, fixtures, _ = football_fixture
    kwargs = dict(
        gameweeks=(16, 17, 18),
        season="2025-26",
        source_snapshot_id="synthetic",
        captured_at=model.cutoff - pd.Timedelta(hours=1),
    )
    horizon, components = build_football_horizon(model, history, roster, fixtures, **kwargs)
    role, role_components = build_football_horizon(
        model, history, roster, fixtures, role_transitions=True, **kwargs
    )
    assert horizon.table.loc[horizon.table.gameweek.eq(16), "expected_points"].eq(0).all()
    assert horizon.table.loc[horizon.table.gameweek.eq(17), "expected_points"].sum() > 0
    assert horizon.model_version != role.model_version
    assert np.allclose(
        components.loc[components.GW.eq(17), "expected_points"],
        role_components.loc[role_components.GW.eq(17), "expected_points"],
    )
    assert not np.allclose(
        components.loc[components.GW.eq(18), "expected_minutes"],
        role_components.loc[role_components.GW.eq(18), "expected_minutes"],
    )
    for _, group in components.groupby(["fixture", "club"]):
        assert np.isclose(group.goals.sum(), group.team_goal_rate.iloc[0] * model.scored_fraction)


def test_joint_worlds_conserve_goals_and_keep_cs_opponent_consistent(football_fixture):
    model, history, roster, fixtures, _ = football_fixture
    _, components = build_football_horizon(
        model,
        history,
        roster,
        fixtures,
        gameweeks=(17,),
        season="2025-26",
        source_snapshot_id="synthetic",
        captured_at=model.cutoff,
    )
    draws = sample_football_events(components, samples=32, seed=3)
    repeated = sample_football_events(components, samples=32, seed=3)
    assert_frame_equal(draws.outcomes, repeated.outcomes)
    joined = draws.outcomes.merge(
        components[["fixture", "player_code", "club"]],
        left_on=["fixture", "player_id"],
        right_on=["fixture", "player_code"],
    )
    assert joined.loc[joined.minutes.eq(0), ["goals", "assists", "total_points"]].eq(0).all().all()
    for row in draws.match_scores.itertuples():
        for club, goals, conceded in [
            (row.home_club, row.home_goals, row.away_goals),
            (row.away_club, row.away_goals, row.home_goals),
        ]:
            g = joined.loc[
                joined.fixture.eq(row.fixture)
                & joined.scenario_id.eq(row.scenario_id)
                & joined.club.eq(club)
            ]
            assert g.goals.sum() <= goals and g.assists.sum() <= g.goals.sum()
            if conceded:
                assert not g.clean_sheet.any()
    with pytest.raises(ValueError, match="coverage"):
        score_football_candidates(
            draws,
            {
                "missing": replace(
                    frozen(), squad=frozen().squad.assign(player_id=lambda d: d.player_id + 100)
                )
            },
        )


def test_recourse_rejects_duplicate_information_and_obeys_resource_state(
    known_optimum_players, small_config
):
    players = known_optimum_players
    parts = []
    for week in (1, 2):
        parts.append(
            players.assign(
                gameweek=week,
                buy_price_tenths=players.price_tenths,
                sell_price_tenths=players.price_tenths,
            )
        )
    baseline = PlanningHorizon(pd.concat(parts, ignore_index=True))
    future = PlanningHorizon(baseline.table.loc[baseline.table.gameweek.eq(2)])
    state = InitialSquadState(("GK_A", "DEF_A", "MID_A", "FWD_A"), 0, 1)
    nodes = [ObservationNode("observed", 1.0, future)]
    result = optimize_observed_recourse(
        baseline,
        state,
        nodes,
        replace(small_config, bench_weight=0, solver_time_limit_seconds=30),
        candidate_count=1,
    )
    assert len(result.candidates) >= 1
    for candidate in result.candidates:
        continuation = candidate.continuations[0]
        assert (
            continuation.plan.weeks[0].bank_before_tenths == candidate.first_week.bank_after_tenths
        )
        assert (
            continuation.plan.weeks[0].free_transfers_before
            == candidate.first_week.free_transfers_for_next_gameweek
        )
        assert continuation.extra_free_transfer_value >= -1e-6
    with pytest.raises(ValueError, match="unique observation"):
        optimize_observed_recourse(
            baseline, state, [nodes[0], nodes[0]], replace(small_config, bench_weight=0)
        )


def test_recourse_waits_for_information_before_selecting_future_striker(
    known_optimum_players, small_config
):
    players = known_optimum_players.copy()
    baseline = PlanningHorizon(
        pd.concat(
            [
                players.assign(gameweek=week, buy_price_tenths=50, sell_price_tenths=50)
                for week in (1, 2)
            ],
            ignore_index=True,
        )
    )
    nodes = []
    for striker in ("FWD_A", "FWD_B"):
        future = baseline.table.loc[baseline.table.gameweek.eq(2)].copy()
        future.loc[future.position.eq("FWD"), "expected_points"] = 0.0
        future.loc[future.player_id.eq(striker), "expected_points"] = 100.0
        nodes.append(ObservationNode(striker, 0.5, PlanningHorizon(future)))
    state = InitialSquadState(("GK_A", "DEF_A", "MID_A", "FWD_A"), 0, 1)
    config = replace(small_config, bench_weight=0, solver_time_limit_seconds=30)
    result = optimize_observed_recourse(baseline, state, nodes, config, candidate_count=1)
    chosen = result.candidates[result.chosen_index]
    assert chosen.first_week.transfer_count == 0
    assert chosen.first_week.free_transfers_for_next_gameweek == 2
    assert len(chosen.continuations) == 2
    for continuation in chosen.continuations:
        future = continuation.plan.weeks[0]
        assert continuation.observation_id in set(future.starting_xi.player_id)
        assert future.transfer_hit_points == 0
    assert chosen.expected_net_points == pytest.approx(
        chosen.first_week.projected_score
        + sum(0.5 * c.plan.total_projected_score for c in chosen.continuations)
    )
    with pytest.raises(ValueError, match="integer"):
        optimize_observed_recourse(baseline, state, nodes, config, candidate_count=1.5)
    with pytest.raises(ValueError, match="net-points"):
        optimize_observed_recourse(baseline, state, nodes, small_config)


def test_football_candidate_application_e2e_from_fitted_history_to_official_scores(
    football_fixture,
):
    model, history, roster, fixtures, _ = football_fixture
    selected = pd.concat(
        [
            (
                roster.loc[roster.position.eq(pos)].tail(n)
                if pos in ("GK", "MID")
                else roster.loc[roster.position.eq(pos)].head(n)
            )
            for pos, n in {"GK": 2, "DEF": 5, "MID": 5, "FWD": 3}.items()
        ]
    )
    state = InitialSquadState(tuple(selected.player_id), 250, 1)
    config = OptimizationConfig(bench_weight=0, solver_time_limit_seconds=30)
    future_table = roster.assign(
        gameweek=18, buy_price_tenths=50, sell_price_tenths=50, expected_points=2.0
    )
    future = PlanningHorizon(future_table)
    preview = preview_football_candidate(
        model,
        history,
        roster,
        fixtures,
        state,
        {p: 45 for p in state.squad_player_ids},
        gameweeks=(17, 18),
        season="2025-26",
        source_snapshot_id="synthetic-e2e",
        captured_at=model.cutoff,
        optimization=config,
        observations=[ObservationNode("future-update", 1.0, future)],
        candidate_count=1,
        samples=8,
        seed=5,
        scenario_selection=True,
    )
    assert preview.control.has_solution and preview.recourse is not None
    assert preview.scenario_mean_diagnostics["draws"] == 8
    assert preview.scenario_selection_evaluation["draws"] == 4
    assert preview.recommendation.startswith("recourse_")
    selected = preview.recourse.candidates[int(preview.recommendation.split("_")[1])]
    evaluation_scores = preview.scenario_scores.loc[
        preview.scenario_scores.candidate.eq(preview.recommendation)
        & preview.scenario_scores.scenario_partition.eq("evaluation")
    ]
    assert preview.scenario_selection_evaluation["first_week_mean_net_points"] == pytest.approx(
        evaluation_scores.net_points.mean()
    )
    assert preview.scenario_selection_evaluation[
        "analytic_continuation_net_points"
    ] == pytest.approx(
        selected.expected_net_points
        - selected.first_week.projected_score
        + selected.first_week.transfer_hit_points
    )
    assert preview.recommendation in preview.decisions
    assert preview.scenario_scores.net_points.notna().all()
    assert preview.scenario_scores.groupby("candidate").size().eq(8).all()
    assert preview.control.weeks[0].transfers_out.sell_price_tenths.eq(47).all()
    rival = preview.decisions[preview.recommendation]
    paired = preview_football_candidate(
        model,
        history,
        roster,
        fixtures,
        state,
        {p: 45 for p in state.squad_player_ids},
        gameweeks=(17,),
        season="2025-26",
        source_snapshot_id="synthetic-e2e",
        captured_at=model.cutoff,
        optimization=config,
        samples=8,
        seed=5,
        rival=rival,
        rival_hit_points=4,
    )
    assert paired.one_week_rival_recommendation == "control"
    assert paired.rival_simulation_evaluation["draws"] == 4
    assert paired.scenario_scores.groupby("scenario_partition").scenario_id.nunique().to_dict() == {
        "evaluation": 4,
        "selection": 4,
    }
    assert paired.scenario_scores.groupby("scenario_id").size().eq(2).all()


def test_extra_ft_is_paired_resource_value_not_a_terminal_constant(
    known_optimum_players, small_config
):
    baseline = PlanningHorizon(
        pd.concat(
            [
                known_optimum_players.assign(gameweek=w, buy_price_tenths=50, sell_price_tenths=50)
                for w in (1, 2)
            ],
            ignore_index=True,
        )
    )
    future = baseline.table.loc[baseline.table.gameweek.eq(2)].copy()
    future.loc[future.player_id.eq("FWD_B"), "expected_points"] = 100.0
    state = InitialSquadState(("GK_A", "DEF_A", "MID_A", "FWD_A"), 0, 0)
    result = optimize_observed_recourse(
        baseline,
        state,
        [ObservationNode("striker-update", 1.0, PlanningHorizon(future))],
        replace(small_config, bench_weight=0),
        TransferPlanningConfig(free_transfer_accrual=0),
        candidate_count=1,
    )
    held = next(c for c in result.candidates if c.first_week.transfer_count == 0)
    continuation = held.continuations[0]
    assert continuation.plan.total_transfer_hit_points == 4
    assert continuation.extra_free_transfer_value == pytest.approx(4.0)


def test_cli_bundle_to_hashed_artifacts_and_no_overwrite(football_fixture, tmp_path):
    from scripts.preview_football_candidate import run

    model, history, roster, fixtures, training = football_fixture
    for name, table in (
        ("training", training),
        ("history", history),
        ("roster", roster),
        ("calendar", fixtures),
    ):
        table.to_csv(tmp_path / (name + ".csv"), index=False)
    selected = pd.concat(
        [
            (
                roster.loc[roster.position.eq(pos)].tail(n)
                if pos in ("GK", "MID")
                else roster.loc[roster.position.eq(pos)].head(n)
            )
            for pos, n in {"GK": 2, "DEF": 5, "MID": 5, "FWD": 3}.items()
        ]
    )
    bundle = dict(
        contract_version="football_candidate_bundle_v1",
        training="training.csv",
        history="history.csv",
        roster="roster.csv",
        calendar="calendar.csv",
        decision_cutoff=model.cutoff.isoformat(),
        captured_at=model.cutoff.isoformat(),
        source_snapshot_id="synthetic-cli",
        season="2025-26",
        gameweeks=[17],
        bank_tenths=250,
        free_transfers=1,
        holdings=[dict(player_id=int(p), purchase_price_tenths=50) for p in selected.player_id],
    )
    path = tmp_path / "bundle.json"
    path.write_text(json.dumps(bundle), encoding="utf-8")
    report = run(path, tmp_path / "result", samples=4, seed=2)
    assert report["production_promotion"] is False
    assert report["independent_evidence_verified"] is False
    assert len(report["input_sha256"]) == 5
    assert len(report["squad"]) == 15
    assert (tmp_path / "result" / "projections.csv").is_file()
    assert (tmp_path / "result" / "scenario_scores.csv").is_file()
    with pytest.raises(FileExistsError):
        run(path, tmp_path / "result", samples=4, seed=2)
