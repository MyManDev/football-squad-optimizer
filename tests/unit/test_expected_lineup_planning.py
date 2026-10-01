"""Expected lineup selection preserves certified paths and pre-information roles."""

from dataclasses import fields, replace

import pandas as pd
import pytest

from squadopt.contracts.preferences import DecisionPreferences
from squadopt.optimization import OptimizationConfig, SolverStatus
from squadopt.planning import (
    ChipAvailability,
    ChipUseWindow,
    FirstWeekExclusion,
    InitialSquadState,
    PlanningHorizon,
    TransferPlanningConfig,
    TransferPlanResult,
    optimize_transfer_plan,
)
from squadopt.planning.expected_window import optimize_expected_window
from squadopt.planning.lineup_utility import (
    expected_week_utility,
    improve_plan_lineups,
    rescore_expected_week,
)
from squadopt.planning.observed import optimize_observed_window
from squadopt.planning.policy_seed import forecast_policy_seed
from squadopt.planning.recourse import ObservationNode
from squadopt.scenarios.expected_lineup import expected_lineup_score


def full_problem(window, *, strings=False):
    """Sixteen available players, with one forward outside a legal initial fifteen."""
    positions = ["GK"] * 2 + ["DEF"] * 5 + ["MID"] * 5 + ["FWD"] * 4
    parts = []
    for week in range(1, window + 1):
        points = [4, 2, 8, 7, 6, 0.4, 0.2, 10, 8, 7, 6, 0.3, 20, 5, 4, 1]
        if week % 2 == 0:
            points[2], points[5] = 0.1, 14
            points[12], points[15] = 7, 12
        parts.append(
            pd.DataFrame(
                {
                    "gameweek": week,
                    "player_id": list(range(1, 17)),
                    "name": [f"Player {p}" for p in range(1, 17)],
                    "team_id": list(range(1, 17)),
                    "position": positions,
                    "buy_price_tenths": 50,
                    "sell_price_tenths": 50,
                    "expected_points": points,
                    "appearance_probability": [0.5 if p == 13 else 1.0 for p in range(1, 17)],
                }
            )
        )
    table = pd.concat(parts, ignore_index=True)
    initial_ids = (*range(1, 13), 14, 15, 16)
    if strings:
        table["player_id"] = table.player_id.map(lambda p: f"p{p:02d}")
        initial_ids = tuple(f"p{p:02d}" for p in initial_ids)
    return (
        PlanningHorizon(table),
        InitialSquadState(initial_ids, bank_tenths=0, free_transfers=1),
        OptimizationConfig(
            budget_tenths=1000,
            bench_weight=0.1,
            solver_deterministic_time_limit=5 if window == 3 else 10,
            solver_time_limit_seconds=180,
        ),
    )


def roles(week):
    return (
        tuple(week.starting_xi.player_id),
        tuple(week.bench.player_id),
        week.captain.player_id,
        week.vice_captain_id,
    )


def assert_fresh_score(week):
    score = expected_lineup_score(
        week.selected_squad,
        *roles(week),
        chip=week.chip,
        hit_points=week.transfer_hit_points,
    )
    assert week.lineup_expectation is not None
    assert week.lineup_expectation["expected_net_points"] == pytest.approx(
        score.expected_net_points
    )
    assert week.lineup_expectation["fingerprint"] == score.fingerprint
    assert week.lineup_expectation["scoring_multipliers"] == dict(score.scoring_multipliers)
    return score


def assert_same_resources(before, after, *, refreshed=False):
    varying = {
        "starting_xi",
        "bench",
        "captain",
        "vice_captain_id",
        "lineup_expectation",
        "projected_score",
        "projected_bench_points",
        "discounted_objective_contribution",
    }
    for field in fields(before):
        if field.name in varying:
            continue
        old, new = getattr(before, field.name), getattr(after, field.name)
        if isinstance(old, pd.DataFrame):
            if refreshed:
                old = old.drop(columns=["expected_points", "appearance_probability"])
                new = new.drop(columns=["expected_points", "appearance_probability"])
            pd.testing.assert_frame_equal(old, new)
        else:
            assert old == new, field.name


@pytest.fixture(scope="module")
def resource_plan():
    horizon, initial, config = full_problem(5)
    table = horizon.table.copy()
    for player, prices in {13: [50, 55, 60, 62, 64], 16: [50, 52, 54, 56, 58]}.items():
        table.loc[table.player_id.eq(player), "buy_price_tenths"] = prices
    table["sell_price_tenths"] = table.buy_price_tenths
    horizon = PlanningHorizon(table)
    initial = replace(initial, bank_tenths=40, free_transfers=0)
    transfer = TransferPlanningConfig(
        acquisition_sell_on_fee=0.5,
        transfer_hit_cost_points=8,
        horizon_discount_factor=0.9,
        banked_transfer_value_points=1.5,
    )
    rights = ChipAvailability(
        {"freehit": frozenset({2}), "bboost": frozenset({3}), "3xc": frozenset({5})},
        {2: "freehit", 3: "bboost", 5: "3xc"},
    )
    squads = {
        week: (*range(1, 13), 14, 15, forward)
        for week, forward in enumerate((13, 16, 13, 16, 13), 1)
    }
    plan = optimize_transfer_plan(
        horizon,
        initial,
        config,
        transfer,
        chips=rights,
        fixed_week_squads=squads,
    )
    assert plan.has_solution and len(plan.weeks) == 5
    return horizon, initial, config, transfer, rights, plan


def test_lineup_improvement_retains_complete_transfer_and_chip_state(resource_plan):
    _, _, config, transfer, _, plan = resource_plan
    result = improve_plan_lineups(plan, config, transfer, max_evaluations=16)
    assert result.solver_status is SolverStatus.FEASIBLE
    assert result.horizon_fingerprint == plan.horizon_fingerprint
    assert result.chips_played == plan.chips_played
    assert result.total_transfer_hit_points == plan.total_transfer_hit_points
    assert result.weeks[0].paid_transfer_count == 1
    assert result.weeks[2].bank_before_tenths == result.weeks[0].bank_after_tenths
    assert result.diagnostics["best_objective_bound"] is None
    assert result.diagnostics["scaled_model_objective_value"] is None
    assert result.diagnostics["primary_search_status"] == plan.diagnostics.get(
        "primary_search_status",
        plan.solver_status.name,
    )
    for before, after in zip(plan.weeks, result.weeks, strict=True):
        assert_same_resources(before, after)
        assert_fresh_score(after)
        assert expected_week_utility(after, transfer) == pytest.approx(
            after.lineup_expectation["expected_net_points"]
            + after.transfer_hit_points
            - after.paid_transfer_count * transfer.transfer_hit_cost_points,
        )
        assert after.transfer_hit_points == 4 * after.paid_transfer_count
        assert after.lineup_expectation["expected_net_points"] - expected_week_utility(
            after, transfer
        ) == pytest.approx(4 * after.paid_transfer_count)
    # Nominal raw arithmetic still has an explicit proposal objective of its own.
    terminal = result.diagnostics["terminal_banked_transfer_value"]
    assert result.objective_value == pytest.approx(
        sum(w.discounted_objective_contribution for w in result.weeks) + terminal,
    )
    assert result.diagnostics["lineup_search"]["evaluations"] <= 5 * 16
    assert all(w.lineup_expectation is None for w in plan.weeks)


def test_forecast_seed_refreshes_scores_and_preserves_full_frozen_action(resource_plan):
    horizon, _, config, transfer, rights, plan = resource_plan
    original = improve_plan_lineups(plan, config, transfer, max_evaluations=16)
    first = original.weeks[0]
    # Preserve a deliberately non-default bench order and vice, not just the XI/captain.
    vice = next(
        p for p in reversed(first.starting_xi.player_id.tolist()) if p != first.captain.player_id
    )
    first = replace(first, bench=first.bench.iloc[::-1], vice_captain_id=vice)
    original = replace(original, weeks=(first, *original.weeks[1:]))
    table = horizon.table.copy()
    table["appearance_probability"] = 0.75
    table["expected_points"] = table.expected_points * 0.2 + 0.3
    table.loc[table.player_id.eq(int(first.bench.iloc[0].player_id)), "expected_points"] = 80
    target = PlanningHorizon(table)
    seed = forecast_policy_seed(
        original,
        horizon,
        target,
        config,
        transfer,
        source_chips=rights,
    )
    assert seed.horizon_fingerprint == target.horizon_fingerprint
    for before, after in zip(original.weeks, seed.weeks, strict=True):
        assert roles(after) == roles(before)
        assert_same_resources(before, after, refreshed=True)
        assert_fresh_score(after)
        assert after.lineup_expectation["fingerprint"] != before.lineup_expectation["fingerprint"]
        raw = after.starting_xi.expected_points.sum() + after.captain.expected_points * (
            2 if after.chip == "3xc" else 1
        )
        assert after.projected_score == pytest.approx(raw)
        assert after.projected_score != before.projected_score
    improved = improve_plan_lineups(seed, config, transfer, fixed_first=first, max_evaluations=16)
    assert roles(improved.weeks[0]) == roles(first)
    assert_fresh_score(improved.weeks[0])
    locked = improved.diagnostics["lineup_search"]["weeks"][0]
    assert locked["first_action_locked"] is True and locked["evaluations"] == 1
    assert all(
        not w["first_action_locked"] for w in improved.diagnostics["lineup_search"]["weeks"][1:]
    )


@pytest.mark.parametrize("strings", [False, True])
def test_fixed_squad_rotates_weekly_and_retains_explicit_first_role_restrictions(strings):
    horizon, initial, config = full_problem(3, strings=strings)
    identity = (lambda p: f"p{p:02d}") if strings else (lambda p: p)
    squad = (*[identity(p) for p in range(1, 16)],)
    exclusion = FirstWeekExclusion(
        not_starting=frozenset({identity(3)}),
        not_captain=frozenset({identity(13)}),
    )
    plan = optimize_transfer_plan(
        horizon,
        initial,
        config,
        TransferPlanningConfig(),
        fixed_week_squads={week: squad for week in horizon.gameweeks},
        first_week_exclusion=exclusion,
    )
    result = improve_plan_lineups(
        plan,
        config,
        TransferPlanningConfig(),
        max_evaluations=16,
        not_starting=exclusion.not_starting,
        not_captain=exclusion.not_captain,
    )
    assert result.has_solution
    first, second, third = result.weeks
    assert identity(3) not in set(first.starting_xi.player_id)
    assert first.captain.player_id not in exclusion.not_captain
    assert first.vice_captain_id not in exclusion.not_captain
    assert identity(6) in set(second.starting_xi.player_id)
    assert identity(3) in set(third.starting_xi.player_id)
    assert identity(6) not in set(third.starting_xi.player_id)
    for before, after in zip(plan.weeks, result.weeks, strict=True):
        assert set(after.selected_squad.player_id) == set(squad)
        assert_same_resources(before, after)
        assert_fresh_score(after)


@pytest.mark.parametrize("window", [3, 5])
def test_expected_window_selects_on_common_lineup_utility(window):
    horizon, initial, config = full_problem(window)
    transfer = TransferPlanningConfig()
    result = optimize_expected_window(horizon, initial, config, transfer)
    assert result.has_solution and len(result.weeks) == window
    review = result.diagnostics["expected_lineup_window"]
    assert review["status"] == "compared"
    assert review["selection_basis"] == "expected_lineup_selection_utility"
    assert review["selection_policy"]["hit_points_charged"] == 4
    assert review["selection_policy"]["transfer_hit_cost_points"] == 4
    assert review["baseline_completed"]
    assert len(review["candidates"]) == 2
    assert review["actual_total"] <= config.solver_deterministic_time_limit + 0.01
    assert sum(entry["cap"] for entry in review["ledger"]) == config.solver_deterministic_time_limit
    utility = sum(assert_fresh_score(w).expected_net_points for w in result.weeks)
    assert utility == pytest.approx(max(p["utility"] for p in review["candidates"]))
    assert review["gain_vs_retained_baseline"] >= -1e-9
    assert result.diagnostics["best_objective_bound"] is None
    for entry in review["ledger"]:
        assert entry["lineup_search"]["evaluations"] <= 128 * window
        for work in entry["lineup_search"]["weeks"]:
            assert work["states_evaluated"] <= 640 * work["evaluations"]


@pytest.mark.parametrize("failed_proposal", ["legacy_proposal", "zero_bonus_proposal"])
def test_expected_window_reports_single_completed_proposal(
    monkeypatch, resource_plan, failed_proposal
):
    horizon, initial, config, transfer, rights, complete = resource_plan
    labels = ("legacy_proposal", "zero_bonus_proposal")
    attempts = []

    def one_failure(_horizon, _initial, settings, _transfer, **kwargs):
        index = len(attempts)
        label = labels[index]
        attempts.append(settings.solver_deterministic_time_limit)
        diagnostics = {"sequential_incumbent": {"actual_total": (0.7, 1.1)[index]}}
        if label == failed_proposal:
            return TransferPlanResult(
                solver_status=SolverStatus.INFEASIBLE,
                weeks=(),
                horizon_fingerprint=horizon.horizon_fingerprint,
                total_projected_score=None,
                total_projected_bench_points=None,
                total_transfer_hit_points=None,
                objective_value=None,
                diagnostics=diagnostics,
            )
        return replace(complete, diagnostics={**complete.diagnostics, **diagnostics})

    monkeypatch.setattr("squadopt.planning.expected_window.optimize_guarded_window", one_failure)
    result = optimize_expected_window(horizon, initial, config, transfer, chips=rights)
    chosen = next(label for label in labels if label != failed_proposal)
    review = result.diagnostics["expected_lineup_window"]
    assert result.has_solution and len(result.weeks) == len(complete.weeks)
    assert attempts == [
        0.4 * config.solver_deterministic_time_limit,
        0.6 * config.solver_deterministic_time_limit,
    ]
    assert review["status"] == "single_proposal"
    assert review["chosen"] == chosen
    assert review["baseline_completed"] is (chosen == "legacy_proposal")
    assert review["gain_vs_retained_baseline"] == (0.0 if chosen == "legacy_proposal" else None)
    assert len(review["candidates"]) == 1
    assert review["candidates"][0]["proposal"] == chosen
    assert [entry["phase"] for entry in review["ledger"]] == list(labels)
    assert review["actual_total"] == pytest.approx(1.8)
    for before, after in zip(complete.weeks, result.weeks, strict=True):
        assert_same_resources(before, after)
        assert_fresh_score(after)


def test_expected_window_keeps_both_failed_proposals_and_their_selection_policy(monkeypatch):
    horizon, initial, config = full_problem(3)
    transfer = TransferPlanningConfig(
        transfer_hit_cost_points=8,
        horizon_discount_factor=0.9,
        banked_transfer_value_points=1.5,
        chip_holding_value_points={"3xc": 2, "bboost": 3},
    )
    rights = ChipAvailability(
        available={"3xc": frozenset({1, 2, 3, 4}), "bboost": frozenset({2, 3})},
        use_windows={
            "3xc": (
                ChipUseWindow(frozenset({1, 2})),
                ChipUseWindow(frozenset({3, 4}), holding_value_points=5),
            )
        },
    )
    attempts = []

    def infeasible(_horizon, _initial, settings, _transfer, **kwargs):
        attempts.append(settings.solver_deterministic_time_limit)
        return TransferPlanResult(
            solver_status=SolverStatus.INFEASIBLE,
            weeks=(),
            horizon_fingerprint=horizon.horizon_fingerprint,
            total_projected_score=None,
            total_projected_bench_points=None,
            total_transfer_hit_points=None,
            objective_value=None,
            diagnostics={"sequential_incumbent": {"actual_total": (0.7, 1.1)[len(attempts) - 1]}},
        )

    monkeypatch.setattr("squadopt.planning.expected_window.optimize_guarded_window", infeasible)
    result = optimize_expected_window(horizon, initial, config, transfer, chips=rights)
    assert attempts == [2, 3]
    assert not result.has_solution and result.weeks == ()
    assert result.objective_value is None
    review = result.diagnostics["expected_lineup_window"]
    assert review["status"] == "no_solution"
    assert review["configured_total"] == 5
    assert review["actual_total"] == pytest.approx(1.8)
    assert review["ledger"] == [
        {"phase": "legacy_proposal", "cap": 2, "actual": 0.7, "status": "INFEASIBLE"},
        {"phase": "zero_bonus_proposal", "cap": 3, "actual": 1.1, "status": "INFEASIBLE"},
    ]
    assert review["chosen"] is None
    assert review["gain_vs_retained_baseline"] is None
    assert review["baseline_completed"] is False
    assert review["candidates"] == []
    assert review["selection_basis"] == "expected_lineup_selection_utility"
    assert review["selection_policy"] == {
        "hit_points_charged": 4,
        "transfer_hit_cost_points": 8,
        "horizon_discount_factor": 0.9,
        "banked_transfer_value_points": 1.5,
        "chip_holding_value_points": {"3xc": 2, "bboost": 3},
        "chip_holding_value_overrides": {"3xc": [{"gameweeks": [3, 4], "holding_value_points": 5}]},
    }


def observations(horizon):
    future = horizon.table.loc[horizon.table.gameweek.ne(horizon.gameweeks[0])]
    nodes = []
    for label, factor in (("appears", 2), ("absent", 0)):
        table = future.copy()
        mask = table.gameweek.eq(2) & table.player_id.eq(13)
        table.loc[mask, "expected_points"] *= factor
        table.loc[mask, "appearance_probability"] *= factor
        nodes.append(ObservationNode(label, 0.5, PlanningHorizon(table)))
    return tuple(nodes)


@pytest.mark.parametrize("window", [3, 5])
def test_observed_expected_branches_freeze_today_and_recompute_every_legal_week(window):
    horizon, initial, config = full_problem(window)
    nodes = observations(horizon)
    result = optimize_observed_window(
        horizon,
        initial,
        nodes,
        config,
        TransferPlanningConfig(),
        expected_lineups=True,
    )
    assert result.has_solution and len(result.weeks) == window
    review = result.diagnostics["observed_window"]
    assert review["status"] == "compared"
    assert review["selection_basis"] == "expected_lineup_selection_utility"
    assert review["selection_policy"]["hit_points_charged"] == 4
    assert review["selection_policy"]["transfer_hit_cost_points"] == 4
    assert review["selection_policy"]["horizon_discount_factor"] == 1
    assert review["selection_policy"]["banked_transfer_value_points"] == 0
    assert review["actual_total"] <= config.solver_deterministic_time_limit + 0.01
    assert review["allocated_total"] <= config.solver_deterministic_time_limit + 1e-9
    assert review["utility_gain_vs_baseline"] >= -1e-9
    assert review["lineup_evaluations"] == sum(
        entry["evaluations"] for entry in review["lineup_evaluator_ledger"]
    )
    for candidate in review["candidates"]:
        assert len(candidate["branches"]) == 2
        assert candidate["branches"][0]["first_action"] == candidate["branches"][1]["first_action"]
        candidate_utility = 0.0
        for branch, node in zip(candidate["branches"], nodes, strict=True):
            assert branch["id"] == node.observation_id
            assert len(branch["weeks"]) == window - 1
            target = pd.concat(
                [
                    horizon.table.loc[horizon.table.gameweek.eq(1)],
                    node.horizon.table,
                ]
            ).set_index(["gameweek", "player_id"])
            owned, free_transfers, bank = (
                set(initial.squad_player_ids),
                initial.free_transfers,
                initial.bank_tenths,
            )
            expected, total_hits = 0.0, 0.0
            decisions = ({**branch["first_action"], "gameweek": 1}, *branch["weeks"])
            for decision in decisions:
                incoming, outgoing = set(decision["in"]), set(decision["out"])
                assert outgoing <= owned and not incoming & owned
                assert len(incoming) == len(outgoing)
                paid = max(0, len(incoming) - free_transfers)
                total_hits += 4 * paid
                free_transfers = min(5, max(0, free_transfers - len(incoming)) + 1)
                owned = owned - outgoing | incoming
                assert owned == set(decision["starters"]) | set(decision["bench"])
                assert decision["bank"] == bank and decision["ft"] == free_transfers
                squad = target.loc[decision["gameweek"]].loc[sorted(owned)].reset_index()
                score = expected_lineup_score(
                    squad,
                    decision["starters"],
                    decision["bench"],
                    decision["captain"],
                    decision["vice_captain"],
                    chip=decision["chip"],
                    hit_points=4 * paid,
                )
                expected += score.expected_net_points
                terms = [t for t in branch["point_terms"] if t["gameweek"] == decision["gameweek"]]
                assert len(terms) == 15
                assert {t["player_id"]: t["multiplier"] for t in terms} == dict(
                    score.scoring_multipliers
                )
                assert sum(
                    t["multiplier"] * t["forecast"] for t in terms
                ) - 4 * paid == pytest.approx(score.expected_net_points)
            assert branch["hit_points"] == total_hits
            assert branch["net_points_on_selection_scale"] == pytest.approx(expected)
            candidate_utility += node.probability * expected
        assert candidate["selection_utility"] == pytest.approx(candidate_utility)
    assert all(assert_fresh_score(w) for w in result.weeks)


def test_binding_ownership_hit_and_chip_preferences_retain_a_complete_plan():
    horizon, initial, config = full_problem(3)
    rights = ChipAvailability({"3xc": frozenset({1, 2, 3}), "bboost": frozenset({1, 2, 3})})
    preferences = DecisionPreferences(
        keep_players=(16,), avoid_players=(13,), no_hits=True, save_chips=True
    )
    result = optimize_expected_window(
        horizon,
        replace(initial, free_transfers=0),
        config,
        TransferPlanningConfig(),
        chips=rights,
        preferences=preferences,
    )
    assert result.has_solution and len(result.weeks) == 3
    for week in result.weeks:
        assert set(week.selected_squad.player_id) == set(initial.squad_player_ids)
        assert week.chip is None and week.paid_transfer_count == 0
        assert_fresh_score(week)


def test_rescoring_legacy_week_persists_its_scored_bench_order(resource_plan):
    *_, plan = resource_plan
    legacy = replace(
        plan.weeks[0],
        bench=plan.weeks[0].bench.sort_values("expected_points", ascending=True),
    )
    assert legacy.lineup_expectation is None and legacy.vice_captain_id is None
    once = rescore_expected_week(legacy)
    assert tuple(once.bench.player_id) != tuple(legacy.bench.player_id)
    score = assert_fresh_score(once)
    assert score.autosub_points > 0
    twice = rescore_expected_week(once)
    assert roles(twice) == roles(once)
    assert dict(twice.lineup_expectation) == dict(once.lineup_expectation)
    pd.testing.assert_frame_equal(twice.bench, once.bench)
    assert legacy.lineup_expectation is None
