"""An incumbent is a certified starting suggestion, never a new constraint or score."""

from dataclasses import replace

import pandas as pd
import pytest

import squadopt.planning.optimizer as module
from squadopt.optimization import SolverStatus
from squadopt.planning import (
    ChipAvailability,
    InitialSquadState,
    PlanningHorizon,
    TransferPlanningConfig,
    TransferPlanningValidationError,
    optimize_transfer_plan,
)


def problem(players, config, window=3):
    parts = []
    for week in range(1, window + 1):
        frame = players.assign(gameweek=week, buy_price_tenths=50, sell_price_tenths=50)
        frame.loc[frame.player_id.eq("FWD_B"), "expected_points"] = 30 if week == 2 else 0
        parts.append(frame)
    return (
        PlanningHorizon(pd.concat(parts, ignore_index=True)),
        InitialSquadState(("GK_A", "DEF_A", "MID_A", "FWD_A"), 0, 1),
        replace(config, bench_weight=0, solver_deterministic_time_limit=5),
    )


@pytest.mark.parametrize("window", [3, 5])
@pytest.mark.parametrize("chip", [None, "freehit", "wildcard", "3xc", "bboost"])
def test_valid_hint_preserves_optimum_and_budget(
    known_optimum_players, small_config, window, chip, monkeypatch
):
    args = problem(known_optimum_players, small_config, window)
    chips = (
        ChipAvailability()
        if chip is None
        else ChipAvailability(available={chip: frozenset({2})}, forced={2: chip})
    )
    settings = TransferPlanningConfig(acquisition_sell_on_fee=0.5)
    baseline = optimize_transfer_plan(*args, settings, chips=chips)
    budgets = []
    configure = module.configure_solver

    def recorded(solver, config, wall, deterministic):
        budgets.append(deterministic)
        return configure(solver, config, wall, deterministic)

    monkeypatch.setattr(module, "configure_solver", recorded)
    hinted = optimize_transfer_plan(*args, settings, chips=chips, incumbent_plan=baseline)
    assert hinted.solver_status is SolverStatus.OPTIMAL
    assert hinted.objective_value == baseline.objective_value
    assert hinted.chips_played == baseline.chips_played
    d = hinted.diagnostics
    probe = (
        d["deterministic_time_used"]
        - d["primary_deterministic_time"]
        - (d["tiebreak_deterministic_time"] or 0)
    )
    assert budgets[0] == 0.5
    assert probe + budgets[1] == pytest.approx(5)
    assert d["deterministic_time_used"] == pytest.approx(
        probe + d["primary_deterministic_time"] + (d["tiebreak_deterministic_time"] or 0)
    )
    assert d["deterministic_time_used"] <= 5.001
    assert "incumbent_hint" not in baseline.diagnostics


def test_hint_can_be_improved_and_claimed_score_is_not_a_bound(known_optimum_players, small_config):
    args = problem(known_optimum_players, small_config)
    hold = optimize_transfer_plan(
        *args, fixed_week_squads={w: args[1].squad_player_ids for w in args[0].gameweeks}
    )
    forged_score = replace(hold, objective_value=1e9, total_projected_score=1e9)
    improved = optimize_transfer_plan(*args, incumbent_plan=forged_score)
    assert improved.objective_value > hold.objective_value
    assert improved.objective_value < 1e9
    assert improved.diagnostics["incumbent_hint"]["claimed_objective_used"] is False


@pytest.mark.parametrize(
    "kind",
    [
        "horizon",
        "incomplete",
        "duplicate",
        "unknown",
        "roles",
        "bank",
        "free_transfers",
        "first_bank",
        "restrictions",
        "rules",
        "hold",
    ],
)
def test_incompatible_or_corrupt_incumbent_is_rejected(known_optimum_players, small_config, kind):
    args = problem(known_optimum_players, small_config)
    plan = optimize_transfer_plan(*args)
    first = plan.weeks[0]
    kw = {}
    if kind == "horizon":
        plan = replace(plan, horizon_fingerprint="0" * 64)
    elif kind == "incomplete":
        plan = replace(plan, weeks=plan.weeks[:-1])
    elif kind in ("duplicate", "unknown"):
        frame = first.selected_squad.copy()
        frame.loc[0, "player_id"] = frame.iloc[1].player_id if kind == "duplicate" else "missing"
        first = replace(first, selected_squad=frame)
    elif kind == "roles":
        first = replace(first, bench=first.starting_xi)
    elif kind == "bank":
        first = replace(first, bank_after_tenths=999)
    elif kind == "free_transfers":
        first = replace(first, free_transfers_before=5)
    elif kind == "first_bank":
        args = (args[0], replace(args[1], bank_tenths=1), args[2])
    elif kind == "restrictions":
        kw["excluded_squads"] = (frozenset(first.selected_squad.player_id),)
    elif kind == "rules":
        kw["transfer_config"] = TransferPlanningConfig(acquisition_sell_on_fee=0.5)
    else:
        kw["protect_hold"] = True
    if kind in ("duplicate", "unknown", "roles", "bank", "free_transfers"):
        plan = replace(plan, weeks=(first, *plan.weeks[1:]))
    with pytest.raises(TransferPlanningValidationError, match="Incumbent"):
        optimize_transfer_plan(*args, incumbent_plan=plan, **kw)
