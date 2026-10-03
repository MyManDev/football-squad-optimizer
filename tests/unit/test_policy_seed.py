"""Forecast reuse preserves a complete policy and requires current-model certification."""

from dataclasses import replace

import pandas as pd
import pytest
from tests.unit.test_planner_incumbent import problem

from squadopt.optimization import SolverStatus
from squadopt.planning import (
    ChipAvailability,
    PlanningHorizon,
    TransferPlanningConfig,
    TransferPlanningValidationError,
    optimize_transfer_plan,
)
from squadopt.planning.policy_seed import forecast_policy_seed
from squadopt.planning.recourse_chips import restrict_first_chip


@pytest.fixture
def seed_problem(known_optimum_players, small_config):
    horizon, initial, config = problem(known_optimum_players, small_config)
    settings = TransferPlanningConfig(acquisition_sell_on_fee=0.5)
    plan = optimize_transfer_plan(horizon, initial, config, settings)
    target = PlanningHorizon(
        horizon.table.assign(expected_points=horizon.table.expected_points + 7)
    )
    return horizon, initial, config, settings, plan, target


def test_only_forecasts_and_fresh_arithmetic_change(seed_problem):
    source, _, config, settings, plan, target = seed_problem
    source_table = source.table.copy(deep=True)
    original_squad = plan.weeks[0].selected_squad.copy(deep=True)
    forged = replace(
        plan,
        objective_value=1e12,
        total_projected_score=1e12,
        diagnostics={**plan.diagnostics, "best_objective_bound": 1e15, "old_proof": True},
        weeks=tuple(
            replace(w, projected_score=1e12, discounted_objective_contribution=1e12)
            for w in plan.weeks
        ),
    )
    result = forecast_policy_seed(forged, source, target, config, settings)
    assert result.solver_status is SolverStatus.FEASIBLE
    assert result.horizon_fingerprint == target.horizon_fingerprint
    assert result.diagnostics["best_objective_bound"] is None
    assert "old_proof" not in result.diagnostics
    assert result.diagnostics["source_objective_used"] is False
    assert result.total_projected_score == pytest.approx(plan.total_projected_score + 7 * 4 * 3)
    assert result.objective_value == pytest.approx(
        sum(w.discounted_objective_contribution for w in result.weeks)
    )
    for old, new in zip(plan.weeks, result.weeks, strict=True):
        for name in ("selected_squad", "starting_xi", "bench", "transfers_in", "transfers_out"):
            pd.testing.assert_frame_equal(
                getattr(old, name).drop(columns="expected_points"),
                getattr(new, name).drop(columns="expected_points"),
            )
        assert old.captain.player_id == new.captain.player_id
        for name in (
            "bank_before_tenths",
            "bank_after_tenths",
            "free_transfers_before",
            "free_transfers_unused",
            "free_transfers_for_next_gameweek",
            "transfer_count",
            "paid_transfer_count",
            "chip",
        ):
            assert getattr(old, name) == getattr(new, name)
    pd.testing.assert_frame_equal(source.table, source_table)
    pd.testing.assert_frame_equal(plan.weeks[0].selected_squad, original_squad)


@pytest.mark.parametrize(
    "changed", ["weeks", "player_id", "name", "team_id", "position", "buy", "sell", "extra"]
)
def test_changed_assets_or_horizon_are_not_relabelled(seed_problem, changed):
    source, _, config, settings, plan, target = seed_problem
    table = target.table.copy()
    if changed == "weeks":
        table = table.loc[table.gameweek.ne(1)]
    elif changed == "player_id":
        table.player_id = table.player_id.replace({"FWD_A": "renamed"})
    elif changed in {"name", "team_id", "position"}:
        table.loc[0, changed] = {"name": "New name", "team_id": "other", "position": "DEF"}[changed]
    elif changed == "buy":
        table.loc[0, "buy_price_tenths"] += 1
    elif changed == "sell":
        table.loc[0, "sell_price_tenths"] -= 1
    else:
        table["new_metadata"] = "different"
    with pytest.raises(TransferPlanningValidationError, match="forecast changes only"):
        forecast_policy_seed(plan, source, PlanningHorizon(table), config, settings)


@pytest.mark.parametrize("changed", ["fingerprint", "partial", "rules", "chips"])
def test_source_provenance_must_match(seed_problem, changed):
    source, _, config, settings, plan, target = seed_problem
    if changed == "fingerprint":
        plan = replace(plan, horizon_fingerprint="0" * 64)
    elif changed == "partial":
        plan = replace(plan, weeks=plan.weeks[:-1])
    else:
        key = "configuration_fingerprint" if changed == "rules" else "chip_availability_fingerprint"
        plan = replace(plan, diagnostics={**plan.diagnostics, key: "0" * 64})
    with pytest.raises(TransferPlanningValidationError, match="complete source horizon and rules"):
        forecast_policy_seed(plan, source, target, config, settings)


def test_permuted_rows_and_new_appearance_forecasts_are_supported(seed_problem):
    source, _, config, settings, plan, target = seed_problem
    target = PlanningHorizon(target.table.iloc[::-1].assign(appearance_probability=0.75))
    result = forecast_policy_seed(plan, source, target, config, settings)
    assert all(w.selected_squad.appearance_probability.eq(0.75).all() for w in result.weeks)
    assert tuple(w.gameweek for w in result.weeks) == source.gameweeks


def test_expanded_chip_rights_and_terminal_values_are_recomputed(
    known_optimum_players, small_config
):
    source, initial, config = problem(known_optimum_players, small_config)
    rights = ChipAvailability({"3xc": frozenset({1, 2, 3})})
    restricted = restrict_first_chip(rights, 1, None)
    settings = TransferPlanningConfig(
        banked_transfer_value_points=1.5,
        chip_holding_value_points={"3xc": 100},
        horizon_discount_factor=0.9,
    )
    plan = optimize_transfer_plan(source, initial, config, settings, chips=restricted)
    result = forecast_policy_seed(
        plan, source, source, config, settings, source_chips=restricted, target_chips=rights
    )
    assert result.diagnostics["chip_availability_fingerprint"] == rights.availability_fingerprint
    assert result.objective_value == pytest.approx(plan.objective_value)
    assert result.diagnostics["terminal_chip_holding_value"] == pytest.approx(81)
    # Relaxing proposal rights yields only a seed; the current full model must
    # independently certify its complete decisions under the expanded rights.
    checked = optimize_transfer_plan(
        source,
        initial,
        config,
        settings,
        chips=rights,
        incumbent_plan=result,
        protect_incumbent=True,
    )
    assert checked.has_solution
    assert checked.diagnostics["chip_availability_fingerprint"] == rights.availability_fingerprint
    assert checked.diagnostics["incumbent_hint"]["version"] == "certified_decisions_v1"
    assert checked.diagnostics["incumbent_hint"]["claimed_objective_used"] is False
    forbidden = ChipAvailability({"3xc": frozenset({1, 2, 3})}, {1: "3xc"})
    with pytest.raises(TransferPlanningValidationError, match="chip schedule"):
        forecast_policy_seed(
            plan, source, source, config, settings, source_chips=restricted, target_chips=forbidden
        )


def test_complete_acquisition_path_and_freehit_are_certified(known_optimum_players, small_config):
    source, initial, config = problem(known_optimum_players, small_config, 5)
    table = source.table.copy()
    for player, prices in {"FWD_A": [50, 55, 60, 62, 64], "FWD_B": [50, 52, 54, 56, 58]}.items():
        table.loc[table.player_id.eq(player), "buy_price_tenths"] = prices
    table["sell_price_tenths"] = table.buy_price_tenths
    source = PlanningHorizon(table)
    initial = replace(initial, bank_tenths=40)
    settings = TransferPlanningConfig(acquisition_sell_on_fee=0.5)
    rights = ChipAvailability({"freehit": frozenset({2})}, {2: "freehit"})
    forwards = ("FWD_B", "FWD_A", "FWD_A", "FWD_B", "FWD_A")
    squads = {week: ("GK_A", "DEF_A", "MID_A", forward) for week, forward in enumerate(forwards, 1)}
    plan = optimize_transfer_plan(
        source, initial, config, settings, chips=rights, fixed_week_squads=squads
    )
    target = PlanningHorizon(table.assign(expected_points=table.expected_points + 1))
    seed = forecast_policy_seed(plan, source, target, config, settings, source_chips=rights)
    assert seed.weeks[1].transfers_out.iloc[0].sell_price_tenths == 51
    assert seed.weeks[2].transfers_out.iloc[0].sell_price_tenths == 52
    assert seed.weeks[2].bank_before_tenths == seed.weeks[0].bank_after_tenths
    assert seed.weeks[3].transfers_out.iloc[0].sell_price_tenths == 61
    assert seed.weeks[4].transfers_out.iloc[0].sell_price_tenths == 57
    checked = optimize_transfer_plan(
        target, initial, config, settings, chips=rights, incumbent_plan=seed, protect_incumbent=True
    )
    assert checked.has_solution
    assert checked.diagnostics["incumbent_hint"]["claimed_objective_used"] is False


def test_resource_corruption_is_still_rejected_by_current_model(seed_problem):
    source, initial, config, settings, plan, target = seed_problem
    first = replace(plan.weeks[0], bank_after_tenths=1000)
    bad = replace(plan, weeks=(first, *plan.weeks[1:]))
    seed = forecast_policy_seed(bad, source, target, config, settings)
    with pytest.raises(TransferPlanningValidationError, match="Incumbent"):
        optimize_transfer_plan(
            target, initial, config, settings, incumbent_plan=seed, protect_incumbent=True
        )
