"""Paired-study arithmetic and real planner constraint preservation."""

from dataclasses import replace

import pandas as pd
import pytest
from scripts.measure_shortlist_matrix import (
    Case,
    audit_plan,
    cases,
    restrictions,
    score_plan,
    summarize,
)

from squadopt.application.advice_variants import weighted_horizon
from squadopt.contracts.preferences import DecisionPreferences
from squadopt.experiments.planning_shortlist import shortlist_horizon
from squadopt.optimization import OptimizationConfig
from squadopt.planning import (
    ChipAvailability,
    InitialSquadState,
    optimize_transfer_plan,
    to_planning_horizon,
)
from squadopt.planning.horizon import ProjectionHorizon


def world():
    rows, held = [], []
    identifier = 0
    for position, count, own in (("GK", 16, 2), ("DEF", 18, 5), ("MID", 18, 5), ("FWD", 16, 3)):
        for offset in range(count):
            identifier += 1
            if offset >= count - own:
                held.append(identifier)
            for week in (6, 7):
                rows.append(
                    dict(
                        gameweek=week,
                        player_id=identifier,
                        name=str(identifier),
                        team_id=identifier,
                        position=position,
                        price_tenths=45,
                        expected_points=float(count - offset),
                        fixture_count=1,
                        home_fixture_count=0,
                    )
                )
    projection = ProjectionHorizon(
        pd.DataFrame(rows), "2026-27", "synthetic", "test", "test", "test", "test"
    )
    return projection, InitialSquadState(tuple(held), 325, 1)


CONFIG = OptimizationConfig(
    bench_weight=0, solver_time_limit_seconds=20, solver_deterministic_time_limit=5
)


def test_top100_selection_preserves_named_avoids_outside_ordinary_shortlist():
    projection, initial = world()
    base = to_planning_horizon(projection)
    preferences, _ = restrictions(Case(1000, 2, 20, "constraints"), base, initial)
    ordinary = shortlist_horizon(base, initial)
    assert set(preferences.avoid_players) - set(ordinary.table.player_id)
    selected = shortlist_horizon(
        base, initial, required_players=(*preferences.keep_players, *preferences.avoid_players)
    )
    assert set(preferences.avoid_players) <= set(selected.table.player_id)
    plan = optimize_transfer_plan(
        selected, initial, CONFIG, preferences=preferences, linearization_level=2, protect_hold=True
    )
    assert audit_plan(plan, base, base, preferences, ChipAvailability())["valid"]
    assert plan.total_transfer_hit_points == 0


@pytest.mark.parametrize("chip", ["3xc", "bboost", "wildcard", "freehit"])
def test_chips_rescore_on_base_and_weighted_full_tables(chip):
    projection, initial = world()
    base = to_planning_horizon(projection)
    counts = {int(p): 100 for p in projection.table.player_id.unique()}
    weighted = to_planning_horizon(weighted_horizon(projection, counts, 50))
    preferences, chips = restrictions(Case(1000, 2, 50, chip), weighted, initial)
    selected = shortlist_horizon(weighted, initial)
    plan = optimize_transfer_plan(
        selected, initial, CONFIG, chips=chips, linearization_level=2, protect_hold=True
    )
    audited = audit_plan(plan, base, weighted, preferences, chips)
    hits = plan.total_transfer_hit_points
    assert audited["weighted_net_points"] + hits == pytest.approx(
        1.5 * (audited["base_net_points"] + hits)
    )
    assert plan.weeks[0].chip == chip
    if chip == "freehit":
        assert set(plan.weeks[1].transfers_out.player_id) <= set(initial.squad_player_ids)
    broken = replace(plan, objective_value=plan.objective_value + 1)
    with pytest.raises(ValueError, match="objective"):
        audit_plan(broken, base, weighted, preferences, chips)


def test_save_preference_disables_available_chips_in_both_arms():
    projection, initial = world()
    base = to_planning_horizon(projection)
    preferences, chips = restrictions(Case(1000, 2, 20, "save"), base, initial)
    for horizon in (base, shortlist_horizon(base, initial)):
        plan = optimize_transfer_plan(
            horizon,
            initial,
            CONFIG,
            chips=chips,
            preferences=preferences,
            linearization_level=2,
            protect_hold=True,
        )
        assert audit_plan(plan, base, base, preferences, chips)["valid"]
        assert all(w.chip is None for w in plan.weeks)
        with pytest.raises(ValueError, match="preference"):
            audit_plan(
                plan,
                base,
                base,
                DecisionPreferences(avoid_players=(int(plan.weeks[0].captain.player_id),)),
                chips,
            )


def test_chips_add_exactly_the_captain_or_bench_to_independent_score():
    projection, initial = world()
    base = to_planning_horizon(projection)
    plan = optimize_transfer_plan(base, initial, CONFIG, linearization_level=2, protect_hold=True)
    week = plan.weeks[0]
    for chip, extra in (
        ("3xc", week.captain.expected_points),
        ("bboost", week.bench.expected_points.sum()),
    ):
        changed = replace(plan, weeks=(replace(week, chip=chip), *plan.weeks[1:]))
        assert score_plan(changed, base) - score_plan(plan, base) == pytest.approx(extra)


def test_failed_missing_and_regressing_pairs_cannot_pass_the_screen():
    def arm(points, seconds):
        return dict(
            valid=True,
            weighted_net_points=points,
            base_net_points=points,
            wall_seconds=seconds,
            status="OPTIMAL",
        )

    row = dict(case={}, arms={"full": arm(10, 2), "shortlist": arm(10, 1)})
    assert summarize([row], 1)["screen_passed"]
    assert not summarize([row], 2)["screen_passed"]
    row["arms"]["shortlist"] = arm(9.8, 1)
    assert summarize([row], 1)["weighted_regressions_over_0_1"] == 1
    assert not summarize([row], 1)["screen_passed"]
    row["arms"]["shortlist"] = {"valid": False, "status": "FAILED"}
    result = summarize([row], 1)
    assert not result["screen_passed"] and result["failed_pairs"] == 1
    assert result["median_wall_ratio"] is None


def test_declared_case_matrix_covers_all_weights_chips_and_profiles_without_duplicates():
    matrix = cases()
    assert len(matrix) == len(set(matrix)) == 40
    assert {c.weight for c in matrix} == {0, 5, 10, 20, 30, 40, 50}
    assert {c.profile for c in matrix} == {900, 950, 1000}
    assert {c.mode for c in matrix} == {
        "plain",
        "constraints",
        "save",
        "3xc",
        "bboost",
        "wildcard",
        "freehit",
    }
