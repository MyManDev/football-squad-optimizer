"""The experimental member route keeps resources and scores its complete decision."""

import json
from dataclasses import fields, replace

import pandas as pd
import pytest
from tests.unit.test_advice_chips import _every_chip_open
from tests.unit.test_advice_worker import ENTRY_ID, _deployment
from tests.unit.test_expected_lineup_planning import assert_same_resources
from tests.unit.test_live_football_model import _forecast

from squadopt.application.advice import (
    AdviseEntryRequest,
    net_expected_points,
    solve_member_control,
)
from squadopt.application.advice_chips import advise_with_chip
from squadopt.application.entries import held_squad_from_picks
from squadopt.application.top100_weight import base_net, base_points, decision_changed, rebased_week
from squadopt.data.errors import DataSourceError
from squadopt.live.football_artifact import football_artifact_path, read_football_forecast
from squadopt.live.transfers import plan_transfers, plan_transfers_with_exclusion
from squadopt.optimization import SolverStatus
from squadopt.planning import FirstWeekExclusion
from squadopt.scenarios.expected_lineup import expected_lineup_score


@pytest.fixture
def football_world(tmp_path, monkeypatch):
    world = _deployment(tmp_path, monkeypatch)
    identity = world["backend"].contexts.identity()
    capture = world["backend"].contexts.capture(identity.context)
    path = football_artifact_path(tmp_path / "artifacts", world["snapshot_id"])
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(_forecast(identity.inputs)), encoding="utf-8")
    football = read_football_forecast(path, identity.inputs)
    picks = capture.provider.picks(ENTRY_ID, identity.inputs.season, 1)
    prices = dict(
        zip(capture.inputs.players.player_id, capture.inputs.players.price_tenths, strict=True)
    )
    held = held_squad_from_picks(picks, current_prices=prices)
    return capture, football, picks, held


def exact_score(week):
    return expected_lineup_score(
        week.selected_squad,
        tuple(week.starting_xi.player_id),
        tuple(week.bench.player_id),
        week.captain.player_id,
        week.vice_captain_id,
        chip=week.chip,
        hit_points=week.transfer_hit_points,
    )


def test_one_week_football_control_keeps_native_resources_and_effective_appearance(football_world):
    capture, football, picks, held = football_world
    original, _, _ = plan_transfers(capture.inputs, football.projection, held, capture.rules)
    selected = solve_member_control(picks, capture.inputs, football.projection, capture.rules)
    week = selected.plan.weeks[0]
    normalized = replace(
        week,
        **{
            field.name: getattr(week, field.name).drop(
                columns="appearance_probability", errors="ignore"
            )
            for field in fields(week)
            if isinstance(getattr(week, field.name), pd.DataFrame)
        },
    )
    assert_same_resources(original.weeks[0], normalized)
    assert selected.plan.solver_status is SolverStatus.FEASIBLE
    assert selected.decision.planner_solver_status == "FEASIBLE"
    assert selected.plan.diagnostics["best_objective_bound"] is None
    assert selected.plan.diagnostics["relative_optimality_gap"] is None
    assert selected.plan.diagnostics["lineup_search"]["evaluations"] <= 128
    source = football.projection.table.set_index("player_id")
    for row in week.selected_squad.itertuples():
        assert row.appearance_probability == source.loc[row.player_id, "appearance_probability"]
        assert row.expected_points == source.loc[row.player_id, "expected_points"]
    assert net_expected_points(selected.plan) == pytest.approx(
        exact_score(week).expected_net_points
    )


def test_current_control_keeps_legacy_roles_even_with_an_unused_appearance_column(football_world):
    capture, _, picks, held = football_world
    table = capture.projection.table.assign(appearance_probability=0.01)
    projection = replace(capture.projection, table=table)
    original, _, _ = plan_transfers(capture.inputs, projection, held, capture.rules)
    selected = solve_member_control(picks, capture.inputs, projection, capture.rules)
    assert selected.plan.weeks[0].lineup_expectation is None
    assert "appearance_probability" not in selected.plan.weeks[0].selected_squad
    assert_same_resources(original.weeks[0], selected.plan.weeks[0])
    assert tuple(original.weeks[0].bench.player_id) == tuple(selected.plan.weeks[0].bench.player_id)
    assert tuple(original.weeks[0].starting_xi.player_id) == tuple(
        selected.plan.weeks[0].starting_xi.player_id
    )
    assert net_expected_points(selected.plan) == net_expected_points(original)


def test_explicit_expected_lineup_refuses_missing_appearance(football_world):
    capture, football, _, held = football_world
    projection = replace(
        football.projection,
        table=football.projection.table.drop(columns="appearance_probability"),
    )
    with pytest.raises(DataSourceError, match="published appearance"):
        plan_transfers(capture.inputs, projection, held, capture.rules, expected_lineups=True)


def test_experimental_role_search_obeys_starter_and_both_captain_exclusions(football_world):
    capture, football, picks, held = football_world
    control = solve_member_control(picks, capture.inputs, football.projection, capture.rules)
    first = control.plan.weeks[0]
    barred_start = next(p for p in first.starting_xi.player_id if p != first.captain.player_id)
    barred_captain = first.captain.player_id
    exclusion = FirstWeekExclusion(
        not_starting=frozenset({barred_start}), not_captain=frozenset({barred_captain})
    )
    plan, decision, _ = plan_transfers_with_exclusion(
        capture.inputs,
        football.projection,
        held,
        capture.rules,
        exclusion,
        expected_lineups=True,
    )
    week = plan.weeks[0]
    assert barred_start not in week.starting_xi.player_id.tolist()
    assert barred_captain not in {week.captain.player_id, week.vice_captain_id}
    assert week.lineup_expectation is not None
    assert decision.planner_solver_status == "FEASIBLE"
    assert net_expected_points(plan) == pytest.approx(exact_score(week).expected_net_points)


def test_weighted_comparison_rescores_complete_roles_on_raw_points(football_world):
    capture, football, picks, _ = football_world
    control = solve_member_control(picks, capture.inputs, football.projection, capture.rules)
    week = control.plan.weeks[0]
    raw = {
        p: value * (0.5 if p % 2 else 1.5) for p, value in base_points(football.projection).items()
    }
    rebased = rebased_week(week, raw)
    assert tuple(rebased.bench.player_id) == tuple(week.bench.player_id)
    assert rebased.vice_captain_id == week.vice_captain_id
    assert base_net(week, raw) == pytest.approx(exact_score(rebased).expected_net_points)


@pytest.mark.parametrize("changed_role", ["bench", "vice"])
def test_bench_or_vice_alone_counts_as_changed_experimental_decision(football_world, changed_role):
    capture, football, picks, _ = football_world
    control = solve_member_control(picks, capture.inputs, football.projection, capture.rules)
    week = control.plan.weeks[0]
    if changed_role == "bench":
        changed = replace(week, bench=week.bench.iloc[[0, 3, 2, 1]].reset_index(drop=True))
    else:
        vice = next(
            p
            for p in week.starting_xi.player_id
            if p not in {week.captain.player_id, week.vice_captain_id}
        )
        changed = replace(week, vice_captain_id=vice)
    assert decision_changed(week, control.decision, changed, control.decision)


@pytest.mark.parametrize("chip", ["wildcard", "freehit", "3xc", "bboost"])
def test_named_football_chip_and_control_use_same_complete_score(football_world, chip):
    capture, football, picks, _ = football_world
    rules = _every_chip_open(capture.rules)
    control = solve_member_control(picks, capture.inputs, football.projection, rules)
    request = AdviseEntryRequest(
        season=capture.inputs.season, gameweek=2, league_id=1, entry_id=ENTRY_ID
    )
    advice = advise_with_chip(
        request,
        chip=chip,
        provider=capture.provider,
        inputs=capture.inputs,
        projection=football.projection,
        rules=rules,
        control=control,
    )
    payload = advice.payload
    table = football.projection.table.set_index("player_id", drop=False)
    xi = tuple(p["player_id"] for p in payload["starting_xi"])
    bench = tuple(p["player_id"] for p in payload["bench"])
    score = expected_lineup_score(
        table.loc[list((*xi, *bench))],
        xi,
        bench,
        payload["captain"]["player_id"],
        payload["vice_captain"]["player_id"],
        chip=chip,
        hit_points=payload["transfer_hit_points"],
    )
    assert payload["expected_own_points"] == pytest.approx(
        score.expected_net_points + payload["transfer_hit_points"]
    )
    assert payload["chip_choice"]["gain_vs_no_chip"] == pytest.approx(
        score.expected_net_points - net_expected_points(control.plan)
    )
    assert payload["solver_status"] == "FEASIBLE"
    assert payload["expected_gain_vs_hold"] is None
    assert all(move["expected_points_delta"] is None for move in payload["moves"])
