"""Human constraints and a legal fallback must survive the whole planning window."""

from dataclasses import replace

import pytest
from ortools.sat.python import cp_model
from tests.unit.test_transfer_planning import _horizon_table

import squadopt.planning.optimizer as optimizer
from squadopt.contracts.preferences import DecisionPreferences
from squadopt.optimization import SolverStatus
from squadopt.planning import ChipAvailability, InitialSquadState, PlanningHorizon


@pytest.mark.parametrize(
    "value",
    [
        {"keep_players": [True]},
        {"avoid_players": [0]},
        {"keep_players": [1, 1]},
        {"no_hits": 1},
        {"keep_players": [1], "avoid_players": [1]},
        {"unknown": True},
    ],
)
def test_invalid_preferences_are_refused(value):
    with pytest.raises(ValueError):
        DecisionPreferences.parse(value)


def test_preferences_are_canonical_and_conflicts_are_not_silently_dropped():
    assert DecisionPreferences.parse({"keep_players": [4, 2]}).canonical() == (
        DecisionPreferences(keep_players=(2, 4)).canonical()
    )
    p = DecisionPreferences(no_hits=True, save_chips=True)
    for strategy, news, chip in [
        ("riskli", False, None),
        ("saf-puan", True, None),
        ("saf-puan", False, "auto"),
    ]:
        with pytest.raises(ValueError):
            p.validate_selection(strategy, news, chip)


def _case(players, length=3):
    mapping = {player: n for n, player in enumerate(players.player_id, 1)}
    players = players.copy()
    players.player_id = players.player_id.map(mapping)
    return (
        PlanningHorizon(_horizon_table(players, tuple(range(1, length + 1)))),
        InitialSquadState(
            tuple(mapping[p] for p in ("GK_A", "DEF_B", "MID_A", "FWD_A")),
            bank_tenths=100,
            free_transfers=1,
        ),
        mapping,
    )


@pytest.mark.parametrize("length", [1, 3, 5])
def test_every_week_honours_preferences(known_optimum_players, small_config, length):
    horizon, initial, ids = _case(known_optimum_players, length)
    p = DecisionPreferences(
        keep_players=(ids["DEF_B"],), avoid_players=(ids["MID_B"],), no_hits=True, save_chips=True
    )
    result = optimizer.optimize_transfer_plan(
        horizon,
        initial,
        small_config,
        preferences=p,
        chips=ChipAvailability(available={"3xc": frozenset(range(1, length + 1))}),
        protect_hold=True,
    )
    assert result.solver_status is SolverStatus.OPTIMAL
    for week in result.weeks:
        assert ids["DEF_B"] in set(week.selected_squad.player_id)
        assert ids["MID_B"] not in set(week.selected_squad.player_id)
        assert week.transfer_hit_points == 0
        assert week.chip is None
    assert result.diagnostics["decision_preferences"] == p.payload()


def test_unknown_search_uses_verified_hold_without_claiming_optimality(
    known_optimum_players,
    small_config,
    monkeypatch,
):
    horizon, initial, _ = _case(known_optimum_players)
    solve = optimizer._solve
    calls = 0

    def interrupted(model, solver):
        nonlocal calls
        calls += 1
        return solve(model, solver) if calls == 1 else cp_model.UNKNOWN

    monkeypatch.setattr(optimizer, "_solve", interrupted)
    result = optimizer.optimize_transfer_plan(horizon, initial, small_config, protect_hold=True)
    assert result.solver_status is SolverStatus.FEASIBLE
    assert all(
        set(w.selected_squad.player_id) == set(initial.squad_player_ids) for w in result.weeks
    )
    assert result.diagnostics["hold_protection"]["selected"] is True
    assert result.diagnostics["absolute_optimality_gap"] is None
    assert result.diagnostics["primary_search_status"] == "UNKNOWN"


def test_forbidden_hold_is_never_a_fallback(known_optimum_players, small_config, monkeypatch):
    horizon, initial, ids = _case(known_optimum_players)
    solve = optimizer._solve
    calls = 0

    def interrupted(model, solver):
        nonlocal calls
        calls += 1
        return solve(model, solver) if calls == 1 else cp_model.UNKNOWN

    monkeypatch.setattr(optimizer, "_solve", interrupted)
    result = optimizer.optimize_transfer_plan(
        horizon,
        initial,
        small_config,
        protect_hold=True,
        preferences=DecisionPreferences(avoid_players=(ids["DEF_B"],)),
    )
    assert result.solver_status is SolverStatus.UNKNOWN
    assert not result.weeks
    assert result.diagnostics["hold_protection"]["status"] == "INFEASIBLE"


def test_restricted_chips_and_no_hits_can_be_infeasible(known_optimum_players, small_config):
    horizon, initial, _ = _case(known_optimum_players, 1)
    result = optimizer.optimize_transfer_plan(
        horizon,
        initial,
        replace(small_config),
        chips=ChipAvailability(available={"3xc": frozenset({1})}, forced={1: "3xc"}),
        preferences=DecisionPreferences(save_chips=True),
        protect_hold=True,
    )
    assert result.solver_status is SolverStatus.INFEASIBLE
