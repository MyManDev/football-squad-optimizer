"""Human constraints and a legal fallback must survive the whole planning window."""

from dataclasses import replace

import pytest
from ortools.sat.python import cp_model
from tests.unit.test_transfer_planning import _horizon_table

import squadopt.planning.optimizer as optimizer
from squadopt.contracts.preferences import DecisionPreferences
from squadopt.optimization import SolverStatus
from squadopt.planning import (
    ChipAvailability,
    ChipUseWindow,
    InitialSquadState,
    PlanningHorizon,
    TransferPlanningConfig,
)
from squadopt.planning.guarded import optimize_guarded_window


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
        {"club_counts": [{"club": "Brighton", "count": 4}]},
        {"club_counts": [{"club": "Brighton", "count": True}]},
        {"club_counts": [{"club": "Brighton", "count": 2, "scope": "other"}]},
        {"club_counts": [{"club": "Brighton", "count": 1}] * 2},
        {
            "club_counts": [
                {"club": "Brighton", "count": 1},
                {"club": "Brighton", "count": 2, "scope": "transfers_in"},
            ]
        },
        {
            "hold_transfers": True,
            "club_counts": [{"club": "Brighton", "count": 1, "scope": "transfers_in"}],
        },
        {"club_counts": [{"club": f"Club {index}", "count": 3} for index in range(6)]},
        {"week_rules": [{"week": True, "rules": {"hold_transfers": True}}]},
        {"week_rules": [{"week": 4, "rules": {"hold_transfers": True}}]},
        {"week_rules": [{"week": 1, "rules": {"hold_transfers": False}}]},
        {"week_rules": [{"week": 1, "rules": {"hold_transfers": True}}] * 2},
        {"week_rules": [{"week": 1, "rules": {"max_hit_points": 0}}]},
        {"week_rules": [{"week": 1, "rules": {"buy_players": [4], "hold_transfers": True}}]},
        {"buy_players": [1]},
        {"avoid_players": [1], "week_rules": [{"week": 2, "rules": {"buy_players": [1]}}]},
        {"max_hit_points": True},
        {"max_hit_points": -1},
        {"max_hit_points": None},
        {"wildcard_week": 1},
        {"wildcard_week": 2, "week_rules": [{"week": 2, "rules": {"save_chips": True}}]},
        {"hold_opening_transfers": 1},
        {"min_opening_bank_tenths": 0},
        {"min_opening_bank_tenths": 10001},
        {"min_opening_bank_tenths": True},
        {"min_opening_bank_tenths": None},
        {"net_points_priority": 1},
        {"week_rules": [{"week": 1, "rules": {"net_points_priority": True}}]},
        {"week_rules": [{"week": 1, "rules": {"hold_opening_transfers": True}}]},
        {"week_rules": [{"week": 1, "rules": {"min_opening_bank_tenths": 1}}]},
        {
            "hold_opening_transfers": True,
            "week_rules": [{"week": 1, "rules": {"buy_players": [1]}}],
        },
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
    assert DecisionPreferences.parse({"no_hits": True, "club_counts": []}).canonical() == (
        legacy.canonical()
    )
    assert legacy == DecisionPreferences.parse(legacy.payload())
    assert DecisionPreferences.parse({"no_hits": True, "hold_opening_transfers": False}) == legacy
    assert DecisionPreferences.parse({"no_hits": True, "net_points_priority": False}) == legacy


def test_club_counts_canonicalize_scope_and_preserve_distinct_requests():
    squad = {"club": "Brighton", "count": 3}
    incoming = {"club": "Brighton", "count": 2, "scope": "transfers_in"}
    preferences = DecisionPreferences.parse(
        {"club_counts": [incoming, {**squad, "scope": "squad"}]}
    )
    assert preferences.active
    assert preferences.payload()["club_counts"] == [squad, incoming]
    assert (
        preferences.canonical() != DecisionPreferences.parse({"club_counts": [squad]}).canonical()
    )


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


def test_week_rules_can_roll_then_force_an_incoming_transfer_after_the_deadline(
    known_optimum_players, small_config
):
    horizon, initial, ids = _case(known_optimum_players)
    targeted = ids["MID_B"]
    preferences = DecisionPreferences.parse(
        {
            "max_hit_points": 4,
            "week_rules": [
                {"week": 3, "rules": {"avoid_players": [targeted]}},
                {"week": 1, "rules": {"hold_transfers": True}},
                {"week": 2, "rules": {"buy_players": [targeted]}},
            ],
        }
    )
    assert DecisionPreferences.parse(preferences.payload()) == preferences
    assert [row.week for row in preferences.week_rules] == [1, 2, 3]
    with pytest.raises(ValueError, match="outside the selected window"):
        preferences.validate_window(1)
    result = optimize_guarded_window(
        horizon,
        initial,
        replace(small_config, solver_deterministic_time_limit=5.0),
        TransferPlanningConfig(),
        preferences=preferences,
    )
    assert result.has_solution
    assert result.weeks[0].transfer_count == 0
    assert result.weeks[0].free_transfers_for_next_gameweek == initial.free_transfers + 1
    assert targeted in set(result.weeks[1].transfers_in.player_id)
    assert targeted not in set(result.weeks[2].selected_squad.player_id)
    assert result.diagnostics["sequential_incumbent"]["seed_cap"] == 0


@pytest.mark.parametrize(
    ("ceiling", "status"), [(4, SolverStatus.INFEASIBLE), (8, SolverStatus.OPTIMAL)]
)
def test_hit_limit_caps_the_actual_total_across_weeks(
    known_optimum_players, small_config, ceiling, status
):
    horizon, initial, ids = _case(known_optimum_players)
    preferences = DecisionPreferences.parse(
        {
            "max_hit_points": ceiling,
            "week_rules": [
                {"week": 1, "rules": {"buy_players": [ids["DEF_A"]]}},
                {"week": 2, "rules": {"buy_players": [ids["MID_B"]]}},
            ],
        }
    )
    result = optimizer.optimize_transfer_plan(
        horizon,
        replace(initial, free_transfers=0),
        small_config,
        TransferPlanningConfig(free_transfer_accrual=0, transfer_hit_cost_points=9),
        preferences=preferences,
        protect_hold=True,
    )
    assert result.solver_status is status
    if result.has_solution:
        assert result.total_transfer_hit_points == 8
        assert [week.transfer_hit_points for week in result.weeks] == [4, 4, 0]


def test_resource_variants_change_the_opening_action_under_the_same_hard_rules(
    known_optimum_players, small_config
):
    players = known_optimum_players.copy()
    players.loc[players.player_id.eq("DEF_A"), ["price_tenths", "expected_points"]] = [70, 20]
    players.loc[players.player_id.eq("GK_B"), "price_tenths"] = 30
    horizon, initial, ids = _case(players)
    base = DecisionPreferences(keep_players=(ids["FWD_A"],), no_hits=True)
    hold = replace(base, hold_opening_transfers=True)
    keep_cash = replace(base, min_opening_bank_tenths=initial.bank_tenths + 1)
    assert len({p.canonical() for p in (base, hold, keep_cash)}) == 3
    assert all(DecisionPreferences.parse(p.payload()) == p for p in (hold, keep_cash))
    assert all(p.scoped and not p.uses_game_transfer_limits for p in (hold, keep_cash))
    policy = TransferPlanningConfig(max_transfers_per_gameweek=1)
    highest, held, richer = (
        optimizer.optimize_transfer_plan(horizon, initial, small_config, policy, preferences=p)
        for p in (base, hold, keep_cash)
    )
    assert all(p.solver_status is SolverStatus.OPTIMAL for p in (highest, held, richer))
    assert tuple(highest.weeks[0].transfers_in.player_id) == (ids["DEF_A"],)
    assert held.weeks[0].transfer_count == 0
    assert held.weeks[0].free_transfers_for_next_gameweek == 2
    assert tuple(held.weeks[1].transfers_in.player_id) == (ids["DEF_A"],)
    assert tuple(richer.weeks[0].transfers_in.player_id) == (ids["GK_B"],)
    assert richer.weeks[0].bank_after_tenths >= keep_cash.min_opening_bank_tenths
    assert (
        max(held.total_projected_score, richer.total_projected_score)
        < highest.total_projected_score
    )
    for plan in (highest, held, richer):
        assert all(week.transfer_count <= 1 for week in plan.weeks)
        assert all(ids["FWD_A"] in set(week.selected_squad.player_id) for week in plan.weeks)
        assert plan.total_transfer_hit_points == 0


def test_opening_hold_keeps_a_future_wildcard_available(known_optimum_players, small_config):
    horizon, initial, _ = _case(known_optimum_players)
    hold = DecisionPreferences(hold_opening_transfers=True, wildcard_week=2)
    plan = optimizer.optimize_transfer_plan(
        horizon,
        initial,
        small_config,
        chips=ChipAvailability(available={"wildcard": frozenset({2})}),
        preferences=hold,
        protect_hold=True,
    )
    assert plan.solver_status is SolverStatus.OPTIMAL
    assert plan.weeks[0].transfer_count == 0
    assert [week.chip for week in plan.weeks] == [None, "wildcard", None]


def test_temporary_free_hit_savings_cannot_fund_an_opening_bank_floor(
    known_optimum_players, small_config
):
    players = known_optimum_players.copy()
    players.loc[players.player_id.eq("GK_B"), "price_tenths"] = 30
    horizon, initial, ids = _case(players)
    chips = ChipAvailability(available={"freehit": frozenset({1})}, forced={1: "freehit"})
    floor = initial.bank_tenths + 1
    hard = DecisionPreferences.parse(
        {"week_rules": [{"week": 1, "rules": {"buy_players": [ids["GK_B"]]}}]}
    )
    unconstrained = optimizer.optimize_transfer_plan(
        horizon, initial, small_config, chips=chips, preferences=hard
    )
    assert unconstrained.solver_status is SolverStatus.OPTIMAL
    assert unconstrained.weeks[0].bank_after_tenths >= floor
    refused = optimizer.optimize_transfer_plan(
        horizon,
        initial,
        small_config,
        chips=chips,
        preferences=replace(hard, min_opening_bank_tenths=floor),
        protect_hold=True,
    )
    assert refused.solver_status is SolverStatus.INFEASIBLE
    assert not refused.weeks


def test_net_points_priority_compares_the_exact_cost_of_keeping_a_player(
    known_optimum_players, small_config
):
    players = known_optimum_players.copy()
    players.loc[players.player_id.eq("DEF_A"), "expected_points"] = 13.12349
    horizon, initial, ids = _case(players, 1)
    initial = replace(initial, free_transfers=0)
    config = replace(small_config, bench_weight=0.75)
    policy = TransferPlanningConfig(transfer_hit_cost_points=9, hit_points_charged=4.125)
    base = DecisionPreferences(net_points_priority=True)
    preferred = replace(base, keep_players=(ids["DEF_B"],))
    best, keep = (
        optimizer.optimize_transfer_plan(horizon, initial, config, policy, preferences=preference)
        for preference in (base, preferred)
    )
    assert base.canonical() != DecisionPreferences().canonical()
    assert best.solver_status is keep.solver_status is SolverStatus.OPTIMAL
    assert tuple(best.weeks[0].transfers_in.player_id) == (ids["DEF_A"],)
    assert best.weeks[0].transfer_hit_points == 4.125
    assert best.weeks[0].captain.expected_points == 13.123
    assert keep.weeks[0].transfer_count == 0
    assert best.objective_value == pytest.approx(33.121)
    assert keep.objective_value == pytest.approx(31.0)
    assert best.objective_value - keep.objective_value == pytest.approx(2.121)


def test_net_points_priority_counts_named_chips_and_equal_weeks_with_no_terminal_utility(
    known_optimum_players, small_config
):
    horizon, initial, _ = _case(known_optimum_players)
    config = replace(small_config, bench_weight=0.75)
    policy = TransferPlanningConfig(
        horizon_discount_factor=0.4,
        banked_transfer_value_points=11,
        chip_holding_value_points={"freehit": 8},
    )
    chips = ChipAvailability(
        available={"bboost": frozenset({1}), "3xc": frozenset({2}), "freehit": frozenset({3})},
        forced={1: "bboost", 2: "3xc"},
        use_windows={"freehit": (ChipUseWindow(frozenset({3}), holding_value_points=15),)},
    )
    result = optimizer.optimize_transfer_plan(
        horizon,
        initial,
        config,
        policy,
        chips=chips,
        preferences=DecisionPreferences(net_points_priority=True, hold_transfers=True),
    )
    assert result.solver_status is SolverStatus.OPTIMAL
    assert [week.chip for week in result.weeks] == ["bboost", "3xc", None]
    expected = sum(week.projected_score - week.transfer_hit_points for week in result.weeks)
    expected += result.weeks[0].projected_bench_points
    assert result.objective_value == pytest.approx(expected)
    assert result.diagnostics["terminal_banked_transfer_value"] == 0
    assert result.diagnostics["terminal_chip_holding_value"] == 0


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
