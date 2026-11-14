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
        None,
        "",
        [],
        {"keep_players": [True]},
        {"avoid_players": [0]},
        {"keep_players": [1, 1]},
        {"include_players": [False]},
        {"include_players": [1, 1]},
        {"no_hits": 1},
        {"hold_transfers": 1},
        {"keep_players": [1], "avoid_players": [1]},
        {"include_players": [1], "avoid_players": [1]},
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


def test_new_preferences_keep_legacy_canonical_identity_when_off():
    legacy = DecisionPreferences(no_hits=True)
    assert (
        DecisionPreferences.parse(
            {"no_hits": True, "hold_transfers": False, "include_players": []}
        ).canonical()
        == '{"avoid_players":[],"keep_players":[],"no_hits":true,"save_chips":false}'
    )
    assert DecisionPreferences.parse(
        {"include_players": [4, 2], "hold_transfers": True}
    ).payload() == {
        **DecisionPreferences().payload(),
        "include_players": [2, 4],
        "hold_transfers": True,
    }
    assert not DecisionPreferences.parse({"hold_transfers": False, "include_players": []}).active
    assert legacy == DecisionPreferences.parse(legacy.payload())


@pytest.mark.parametrize("chip", ["wildcard", "freehit", "auto"])
def test_holding_transfers_conflicts_with_rebuilding_chip_requests(chip):
    with pytest.raises(ValueError, match="Holding transfers conflicts"):
        DecisionPreferences(hold_transfers=True).validate_selection("saf-puan", False, chip)
    DecisionPreferences(hold_transfers=True).validate_selection("saf-puan", False, "3xc")


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


@pytest.mark.parametrize("length", [1, 3, 5])
def test_holding_transfers_retains_squad_and_rolls_the_free_transfer(
    known_optimum_players, small_config, length
):
    horizon, initial, _ = _case(known_optimum_players, length)
    result = optimizer.optimize_transfer_plan(
        horizon, initial, small_config, preferences=DecisionPreferences(hold_transfers=True)
    )
    assert result.solver_status is SolverStatus.OPTIMAL
    assert result.weeks[0].free_transfers_for_next_gameweek == initial.free_transfers + 1
    for week in result.weeks:
        assert week.transfer_count == 0
        assert set(week.selected_squad.player_id) == set(initial.squad_player_ids)


@pytest.mark.parametrize("length", [1, 3, 5])
def test_including_an_unowned_player_requires_membership_in_every_week(
    known_optimum_players, small_config, length
):
    horizon, initial, ids = _case(known_optimum_players, length)
    player = ids["MID_B"]
    result = optimizer.optimize_transfer_plan(
        horizon,
        initial,
        small_config,
        preferences=DecisionPreferences(include_players=(player,), no_hits=True),
    )
    assert result.solver_status is SolverStatus.OPTIMAL
    assert tuple(result.weeks[0].transfers_in.player_id) == (player,)
    for week in result.weeks:
        assert player in set(week.selected_squad.player_id)
        assert week.transfer_hit_points == 0


def test_holding_transfers_with_an_unowned_target_has_no_plan(known_optimum_players, small_config):
    horizon, initial, ids = _case(known_optimum_players, 1)
    result = optimizer.optimize_transfer_plan(
        horizon,
        initial,
        small_config,
        preferences=DecisionPreferences(include_players=(ids["MID_B"],), hold_transfers=True),
        protect_hold=True,
    )
    assert result.solver_status is SolverStatus.INFEASIBLE
    assert not result.weeks


@pytest.mark.parametrize("chip", ["wildcard", "freehit"])
def test_holding_transfers_disallows_forced_rebuild_in_solver(
    known_optimum_players, small_config, chip
):
    horizon, initial, _ = _case(known_optimum_players, 1)
    result = optimizer.optimize_transfer_plan(
        horizon,
        initial,
        small_config,
        chips=ChipAvailability(available={chip: frozenset({1})}, forced={1: chip}),
        preferences=DecisionPreferences(hold_transfers=True),
    )
    assert result.solver_status is SolverStatus.INFEASIBLE


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
