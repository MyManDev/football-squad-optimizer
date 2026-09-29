"""State continuity and honest incumbent/proof handling in temporal repair."""

from dataclasses import replace

import pandas as pd
import pytest

import squadopt.planning.refinement as module
from squadopt.contracts.preferences import DecisionPreferences
from squadopt.optimization import SolverStatus
from squadopt.planning import ChipAvailability, InitialSquadState, PlanningHorizon
from squadopt.planning.models import TransferPlanningValidationError
from squadopt.planning.optimizer import optimize_transfer_plan


def problem(players, config, window):
    parts = []
    for week in range(1, window + 1):
        frame = players.assign(gameweek=week, buy_price_tenths=50, sell_price_tenths=50)
        frame.loc[frame.player_id.eq("FWD_B"), "expected_points"] = 20 if week == 2 else 0
        parts.append(frame)
    return (
        PlanningHorizon(pd.concat(parts, ignore_index=True)),
        InitialSquadState(("GK_A", "DEF_A", "MID_A", "FWD_A"), 0, 1),
        replace(
            config, bench_weight=0, solver_time_limit_seconds=30, solver_deterministic_time_limit=5
        ),
    )


@pytest.mark.parametrize("window", [3, 5])
@pytest.mark.parametrize("chip", [None, "freehit", "wildcard", "3xc", "bboost"])
def test_fixed_outer_squads_retain_full_state_constraints(
    known_optimum_players, small_config, window, chip
):
    horizon, state, config = problem(known_optimum_players, small_config, window)
    chips = (
        ChipAvailability()
        if chip is None
        else ChipAvailability(available={chip: frozenset({2})}, forced={2: chip})
    )
    fixed = {1: state.squad_player_ids, window: state.squad_player_ids}
    result = optimize_transfer_plan(horizon, state, config, chips=chips, fixed_week_squads=fixed)
    assert result.has_solution
    assert result.diagnostics["fixed_week_squads"] == fixed
    assert all(
        set(w.selected_squad.player_id) == set(fixed[w.gameweek])
        for w in result.weeks
        if w.gameweek in fixed
    )
    before, bank, ft = set(state.squad_player_ids), state.bank_tenths, state.free_transfers
    for week in result.weeks:
        squad = set(week.selected_squad.player_id)
        assert set(week.transfers_in.player_id) == squad - before
        assert set(week.transfers_out.player_id) == before - squad
        assert week.bank_before_tenths == bank
        assert week.free_transfers_before == ft
        assert week.bank_after_tenths == bank  # Equal prices and squad cardinality.
        if week.chip != "freehit":
            before, bank = squad, week.bank_after_tenths
        ft = week.free_transfers_for_next_gameweek
    if chip:
        assert result.weeks[1].chip == chip
    if chip == "freehit":
        assert result.weeks[2].transfer_count == 0


@pytest.mark.parametrize(
    "bad",
    [
        {99: ("GK_A",)},
        {True: ("GK_A",)},
        {1: ()},
        {1: ("GK_A", "GK_A", "MID_A", "FWD_A")},
        {1: ("missing", "DEF_A", "MID_A", "FWD_A")},
    ],
)
def test_rejects_invalid_fixed_squads(known_optimum_players, small_config, bad):
    args = problem(known_optimum_players, small_config, 3)
    with pytest.raises(TransferPlanningValidationError, match="Fixed"):
        optimize_transfer_plan(*args, fixed_week_squads=bad)


@pytest.mark.parametrize("window", [3, 5])
@pytest.mark.parametrize("width", [2, 3])
def test_refinement_keeps_preferences_and_does_not_upgrade_restricted_proofs(
    known_optimum_players, small_config, monkeypatch, window, width
):
    args = problem(known_optimum_players, small_config, window)
    ids = {p: i + 1 for i, p in enumerate(known_optimum_players.player_id)}
    args = (
        PlanningHorizon(args[0].table.assign(player_id=lambda t: t.player_id.map(ids))),
        InitialSquadState(tuple(ids[p] for p in args[1].squad_player_ids), 0, 1),
        args[2],
    )
    solve = module.optimize_transfer_plan
    calls = []

    def bounded(*a, **kw):
        result = solve(*a, **kw)
        calls.append(kw)
        return replace(result, solver_status=SolverStatus.FEASIBLE) if len(calls) == 1 else result

    monkeypatch.setattr(module, "optimize_transfer_plan", bounded)
    preferences = DecisionPreferences(
        keep_players=(7,), avoid_players=(6,), no_hits=True, save_chips=True
    )
    chips = ChipAvailability(available={c: frozenset(args[0].gameweeks) for c in ("3xc", "bboost")})
    result = module.optimize_refined_plan(
        *args, neighborhood_width=width, preferences=preferences, chips=chips
    )
    assert result.proof_status == "FEASIBLE_REFINED_HORIZON"
    assert len(result.steps) == window - width + 1
    assert all(c["preferences"] == preferences for c in calls)
    assert all(s.objective_after >= s.objective_before for s in result.steps)
    for week in result.chosen.weeks:
        assert 7 in set(week.selected_squad.player_id)
        assert 6 not in set(week.selected_squad.player_id)
        assert week.transfer_hit_points == 0 and week.chip is None


@pytest.mark.parametrize("status", [SolverStatus.UNKNOWN, SolverStatus.INFEASIBLE])
@pytest.mark.parametrize("width", [2, 3])
def test_unknown_retains_incumbent_but_contradiction_is_an_error(
    known_optimum_players, small_config, monkeypatch, status, width
):
    args = problem(known_optimum_players, small_config, 3)
    baseline = replace(optimize_transfer_plan(*args), solver_status=SolverStatus.FEASIBLE)
    empty = replace(
        baseline,
        solver_status=status,
        weeks=(),
        objective_value=None,
        total_projected_score=None,
        total_projected_bench_points=None,
        total_transfer_hit_points=None,
    )
    monkeypatch.setattr(
        module,
        "optimize_transfer_plan",
        lambda *a, **kw: empty if "fixed_week_squads" in kw else baseline,
    )
    if status is SolverStatus.INFEASIBLE:
        with pytest.raises(TransferPlanningValidationError, match="contradicts"):
            module.optimize_refined_plan(*args, neighborhood_width=width)
    else:
        result = module.optimize_refined_plan(*args, neighborhood_width=width)
        assert result.chosen is baseline
        assert all(not s.accepted for s in result.steps)


def test_a_proved_baseline_needs_no_restricted_search(known_optimum_players, small_config):
    result = module.optimize_refined_plan(*problem(known_optimum_players, small_config, 3))
    assert result.baseline.solver_status is SolverStatus.OPTIMAL
    assert result.steps == () and result.chosen is result.baseline
    assert result.proof_status == "OPTIMAL_FULL_HORIZON_SCALED_OBJECTIVE"


@pytest.mark.parametrize("window", [3, 5])
@pytest.mark.parametrize("width", [2, 3])
def test_repair_improves_a_legal_hold_incumbent_without_resetting_resources(
    known_optimum_players, small_config, monkeypatch, window, width
):
    args = problem(known_optimum_players, small_config, window)
    solve = module.optimize_transfer_plan
    hold = solve(*args, fixed_week_squads={w: args[1].squad_player_ids for w in args[0].gameweeks})
    hold = replace(hold, solver_status=SolverStatus.FEASIBLE)
    calls = 0

    def seeded(*a, **kw):
        nonlocal calls
        calls += 1
        return hold if calls == 1 else solve(*a, **kw)

    monkeypatch.setattr(module, "optimize_transfer_plan", seeded)
    result = module.optimize_refined_plan(*args, neighborhood_width=width)
    assert result.chosen.objective_value > hold.objective_value
    assert result.chosen.solver_status is SolverStatus.FEASIBLE
    assert result.chosen.diagnostics["best_objective_bound"] is None
    assert any(s.accepted for s in result.steps)
    assert all(s.objective_after >= s.objective_before for s in result.steps)
    assert result.chosen.weeks[0].free_transfers_before == 1
    assert all(
        result.chosen.weeks[i].free_transfers_before
        == result.chosen.weeks[i - 1].free_transfers_for_next_gameweek
        for i in range(1, window)
    )
    assert result.chosen.total_transfer_hit_points == 0


@pytest.mark.parametrize("bad", [True, 1, 4, 2.5])
def test_neighborhood_width_is_bounded(known_optimum_players, small_config, bad):
    with pytest.raises(ValueError, match="width"):
        module.optimize_refined_plan(
            *problem(known_optimum_players, small_config, 3), neighborhood_width=bad
        )


def test_triple_escapes_pair_trap_from_an_early_affordable_purchase(
    known_optimum_players, small_config, monkeypatch
):
    ids = ("GK_A", "DEF_A", "MID_A", "FWD_A")
    players = known_optimum_players.loc[known_optimum_players.player_id.isin((*ids, "FWD_B"))]
    parts = []
    for week in (1, 2, 3):
        frame = players.assign(
            gameweek=week, buy_price_tenths=50, sell_price_tenths=50, expected_points=0.0
        )
        frame.loc[frame.player_id.eq("FWD_A"), "expected_points"] = 10.0
        frame.loc[frame.player_id.eq("FWD_B"), "expected_points"] = 30.0 if week == 3 else 5.0
        frame.loc[frame.player_id.eq("FWD_B"), "buy_price_tenths"] = 50 if week == 1 else 60
        # The held early purchase realizes only half of the subsequent rise.
        frame.loc[frame.player_id.eq("FWD_B"), "sell_price_tenths"] = 50 if week == 1 else 55
        parts.append(frame)
    args = (
        PlanningHorizon(pd.concat(parts, ignore_index=True)),
        InitialSquadState(ids, 0, 1),
        replace(small_config, bench_weight=0),
    )
    solve = module.optimize_transfer_plan
    hold = replace(
        solve(*args, fixed_week_squads={w: ids for w in (1, 2, 3)}),
        solver_status=SolverStatus.FEASIBLE,
    )
    monkeypatch.setattr(
        module,
        "optimize_transfer_plan",
        lambda *a, **kw: solve(*a, **kw) if "fixed_week_squads" in kw else hold,
    )
    pair = module.optimize_refined_plan(*args)
    triple = module.optimize_refined_plan(*args, neighborhood_width=3)
    assert pair.chosen.objective_value == pytest.approx(60.0)
    assert triple.chosen.objective_value == pytest.approx(80.0)
    assert all("FWD_B" in set(w.selected_squad.player_id) for w in triple.chosen.weeks)
    assert triple.chosen.total_transfer_hit_points == 0
    assert triple.steps[0].free_gameweeks == (1, 2, 3)
    assert triple.proof_status == "FEASIBLE_REFINED_HORIZON"
