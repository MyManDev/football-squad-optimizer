"""Experimental football requests spend one budget at the member's chosen setting."""

import json
import math
from dataclasses import replace
from types import SimpleNamespace

import pytest
from tests.unit.test_advice_menu import _collaborators, _request
from tests.unit.test_advice_variants import RIVAL, _world
from tests.unit.test_member_windows import _window_world

import squadopt.application.advice_chip_strategy as chip_module
import squadopt.application.advice_menu as menu
from squadopt.application.advice import TOP100_LIMIT
from squadopt.application.advice_variants import TOP100_WINDOW_LIMIT
from squadopt.platform.advice_documents import validate_advice_document

window_world = _window_world
world = _world


@pytest.mark.parametrize("window,weight", [(3, 20), (5, 50)])
def test_weighted_football_request_solves_only_its_selected_horizon(
    world, monkeypatch, window, weight
):
    projection = replace(
        world["projection"],
        diagnostics={
            **world["projection"].diagnostics,
            "model_name": "fixture_football_candidate",
        },
    )
    built = []
    solved = []
    original_plan = chip_module.plan_transfer_horizon

    def builder(dates):
        horizon = replace(world["builder"](dates), model_name="fixture_football_candidate")
        built.append(horizon)
        return horizon

    def solve(inputs, horizon, held, rules, **kwargs):
        plan, config = original_plan(inputs, horizon, held, rules, **kwargs)
        solved.append((horizon, plan, kwargs))
        return plan, config

    def unexpected(*args, **kwargs):
        pytest.fail("The chosen football setting must not solve or retrieve a setting-0 plan.")

    monkeypatch.setattr(chip_module, "plan_transfer_horizon", solve)
    monkeypatch.setattr(menu, "advise_entry", unexpected)
    monkeypatch.setattr(menu, "advise_window_with_top100", unexpected)
    payload = menu.advise_menu_entry(
        _request(window=window, top100_weight=weight),
        **{**_collaborators(world), "projection": projection, "horizon_builder": builder},
        top100_counts=world["counts"],
        prerequisite=unexpected,
    )

    assert len(built) == len(solved) == 1
    base = built[0]
    chosen, plan, options = solved[0]
    gameweeks = tuple(sorted(base.table.gameweek.unique()))
    assert gameweeks == tuple(range(2, 2 + window))
    assert tuple(week.gameweek for week in plan.weeks) == gameweeks
    assert options["optimization"].solver_deterministic_time_limit == 20 * window
    assert options["chip_strategy"] is False
    assert all(week.chip is None for week in plan.weeks)
    before = base.table.set_index(["gameweek", "player_id"])
    after = chosen.table.set_index(["gameweek", "player_id"])
    assert chosen.source_snapshot_id == base.source_snapshot_id
    for (gameweek, player), row in before.iterrows():
        factor = 1 + weight / 100 * world["counts"].counts.get(player, 0) / 100
        assert after.loc[(gameweek, player), "expected_points"] == pytest.approx(
            row["expected_points"] * factor
        )
    # Selection uses the weighted horizon; every displayed week's score uses the
    # unweighted forecasts of the actual selected eleven and captain.
    for shown, week in zip(payload["plan_weeks"], plan.weeks, strict=True):
        points = before.loc[week.gameweek, "expected_points"]
        total = math.fsum(float(points.loc[player]) for player in week.starting_xi.player_id)
        total += float(points.loc[int(week.captain["player_id"])])
        assert shown["expected_points"] == pytest.approx(total)
        assert shown["transfer_hit_points"] == pytest.approx(week.transfer_hit_points)
    assert payload["expected_own_points"] == pytest.approx(
        payload["plan_weeks"][0]["expected_points"]
    )
    assert payload["selection_top100_weight"] == weight
    assert payload["selection_top100_source"] == world["counts"].source_record()
    assert payload["stated_limits"].count(TOP100_LIMIT.format(weight=weight)) == 1
    assert payload["stated_limits"].count(TOP100_WINDOW_LIMIT) == 1
    assert payload["source_snapshot_id"] == world["inputs"].snapshot_id
    assert payload["window"] == window
    assert "top100" not in payload
    assert "expected_points_cost" not in payload
    assert "expected_points_cost_ceiling" not in payload
    assert "control_solver_status" not in payload
    assert "chip_strategy" not in payload
    validate_advice_document(
        json.dumps(
            {
                "contract_version": "provisional_league_ui_v1",
                "generated_at_utc": "2026-08-27T09:00:00Z",
                "source_kind": "example",
                "payload": payload,
            }
        ).encode()
    )


@pytest.mark.parametrize("window", [3, 5])
def test_current_model_keeps_its_paired_zero_setting_comparison(world, monkeypatch, window):
    control = {"control": "already computed"}
    expected = {"legacy": "paired window"}
    calls = []
    lookups = []

    def paired(request, **kwargs):
        calls.append((request, kwargs))
        return SimpleNamespace(payload=expected)

    def prerequisite(request):
        lookups.append(request)
        return control

    def unexpected(*args, **kwargs):
        pytest.fail("The current model keeps its paired comparison route.")

    monkeypatch.setattr(menu, "advise_window_with_top100", paired)
    monkeypatch.setattr(menu, "advise_chip_strategy", unexpected)
    payload = menu.advise_menu_entry(
        _request(window=window, top100_weight=20),
        **_collaborators(world),
        top100_counts=world["counts"],
        prerequisite=prerequisite,
    )
    assert payload is expected
    assert len(calls) == len(lookups) == 1
    assert calls[0][1]["control_payload"] == control
    assert calls[0][1]["weight"] == 20
    assert lookups[0].top100_weight == 0
    assert lookups[0].window == window


def test_football_rival_keeps_both_existing_comparison_lookups(world, monkeypatch):
    projection = replace(
        world["projection"],
        diagnostics={
            **world["projection"].diagnostics,
            "model_name": "fixture_football_candidate",
        },
    )
    control = {"control": "already computed"}
    reference = {"rival": "already computed"}
    expected = {"legacy": "paired rival"}
    lookups = []
    calls = []

    def prerequisite(request):
        lookups.append(request)
        return control if request.strategy == "saf-puan" else reference

    def rival(request, **kwargs):
        calls.append((request, kwargs))
        return SimpleNamespace(payload=expected)

    def unexpected(*args, **kwargs):
        pytest.fail("The rival strategy keeps its existing comparison route.")

    monkeypatch.setattr(menu, "advise_chip_strategy", unexpected)
    monkeypatch.setattr(menu, "advise_rival_window", rival)
    payload = menu.advise_menu_entry(
        _request(strategy="ortak-koru", window=3, rival_entry_id=RIVAL, top100_weight=20),
        **{**_collaborators(world), "projection": projection},
        top100_counts=world["counts"],
        prerequisite=prerequisite,
    )
    assert payload is expected
    assert len(calls) == 1
    assert [(r.strategy, r.top100_weight) for r in lookups] == [
        ("saf-puan", 0),
        ("ortak-koru", 0),
    ]
    assert calls[0][1]["control_payload"] == control
    assert calls[0][1]["reference_payload"] == reference
