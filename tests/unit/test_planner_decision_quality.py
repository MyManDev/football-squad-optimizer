"""Small exact decision problems test causality, feasible search and human constraints."""

from dataclasses import replace

import pandas as pd
import pytest

import squadopt.planning.recourse as module
from squadopt.contracts.preferences import DecisionPreferences
from squadopt.optimization import SolverStatus
from squadopt.planning import InitialSquadState, PlanningHorizon
from squadopt.planning.models import ChipAvailability, TransferPlanningValidationError
from squadopt.planning.recourse import ObservationNode, optimize_observed_recourse
from squadopt.planning.recourse_chips import net_week_points


def problem(players, config, window):
    players = players.copy()
    players["player_id"] = range(1, len(players) + 1)
    baseline = PlanningHorizon(
        pd.concat(
            [
                players.assign(gameweek=w, buy_price_tenths=50, sell_price_tenths=50)
                for w in range(1, window + 1)
            ],
            ignore_index=True,
        )
    )
    nodes = []
    for striker in (7, 8):
        future = baseline.table.loc[baseline.table.gameweek.gt(1)].copy()
        future.loc[future.position.eq("FWD"), "expected_points"] = 0.0
        future.loc[future.player_id.eq(striker), "expected_points"] = 25.0
        nodes.append(ObservationNode(str(striker), 0.5, PlanningHorizon(future)))
    return (
        baseline,
        InitialSquadState((1, 3, 5, 7), 0, 1),
        nodes,
        replace(config, bench_weight=0, solver_time_limit_seconds=30),
    )


@pytest.mark.parametrize("window", [3, 5])
def test_expanded_menu_is_one_common_action_scored_in_every_node(
    known_optimum_players, small_config, window
):
    args = problem(known_optimum_players, small_config, window)
    control = optimize_observed_recourse(*args, candidate_count=1)
    result = optimize_observed_recourse(*args, candidate_count=1, observation_proposals=True)

    def keys(result):
        return {
            (frozenset(c.first_week.selected_squad.player_id), c.first_week.chip)
            for c in result.candidates
        }

    assert keys(control) <= keys(result)
    assert result.selection_status == "OPTIMAL_RESTRICTED_MENU"
    assert result.candidates[result.chosen_index].expected_net_points >= (
        control.candidates[control.chosen_index].expected_net_points - 1e-6
    )
    for c in result.candidates:
        assert {b.observation_id for b in c.continuations} == {"7", "8"}
        assert c.expected_net_points == pytest.approx(
            net_week_points(c.first_week)
            + sum(
                b.probability * sum(net_week_points(w) for w in b.plan.weeks)
                for b in c.continuations
            )
        )
        for b in c.continuations:
            assert (
                b.plan.weeks[0].free_transfers_before
                == c.first_week.free_transfers_for_next_gameweek
            )
    reversed_result = optimize_observed_recourse(
        args[0],
        args[1],
        list(reversed(args[2])),
        args[3],
        candidate_count=1,
        observation_proposals=True,
    )
    assert reversed_result.candidates[
        reversed_result.chosen_index
    ].expected_net_points == pytest.approx(
        result.candidates[result.chosen_index].expected_net_points
    )


def test_bounded_search_keeps_feasible_status_and_does_not_invent_ft_value(
    known_optimum_players, small_config, monkeypatch
):
    args = problem(known_optimum_players, small_config, 5)
    solve = module.optimize_transfer_plan

    def feasible(*a, **kw):
        result = solve(*a, **kw)
        return replace(result, solver_status=SolverStatus.FEASIBLE) if result.weeks else result

    monkeypatch.setattr(module, "optimize_transfer_plan", feasible)
    with pytest.raises(TransferPlanningValidationError, match="proved"):
        optimize_observed_recourse(*args, candidate_count=1)
    result = optimize_observed_recourse(*args, candidate_count=1, require_optimal=False)
    assert result.selection_status == "FEASIBLE_RESTRICTED_MENU"
    assert result.contract_version == "observed_rollout_v3"
    assert "FEASIBLE" in result.proposal_statuses
    assert all(
        b.extra_free_transfer_value is None for c in result.candidates for b in c.continuations
    )


def test_incomplete_positive_probability_branch_is_never_silently_dropped(
    known_optimum_players, small_config, monkeypatch
):
    args = problem(known_optimum_players, small_config, 3)
    solve = module.optimize_transfer_plan

    def missing(horizon, *a, **kw):
        result = solve(horizon, *a, **kw)
        return (
            replace(
                result,
                solver_status=SolverStatus.UNKNOWN,
                weeks=(),
                total_projected_score=None,
                objective_value=None,
                total_projected_bench_points=None,
                total_transfer_hit_points=None,
            )
            if horizon.gameweeks[0] == 2
            else result
        )

    monkeypatch.setattr(module, "optimize_transfer_plan", missing)
    with pytest.raises(TransferPlanningValidationError, match="every node"):
        optimize_observed_recourse(*args, candidate_count=1, require_optimal=False)


@pytest.mark.parametrize("window", [3, 5])
def test_human_constraints_reach_proposals_hold_and_every_continuation(
    known_optimum_players, small_config, window
):
    args = problem(known_optimum_players, small_config, window)
    preferences = DecisionPreferences(
        keep_players=(1,), avoid_players=(8,), no_hits=True, save_chips=True
    )
    result = optimize_observed_recourse(
        *args,
        candidate_count=1,
        observation_proposals=True,
        require_optimal=False,
        preferences=preferences,
        chips=ChipAvailability({"3xc": frozenset(range(1, window + 1))}),
    )
    for candidate in result.candidates:
        for week in [
            candidate.first_week,
            *(w for b in candidate.continuations for w in b.plan.weeks),
        ]:
            assert 1 in set(week.selected_squad.player_id)
            assert 8 not in set(week.selected_squad.player_id)
            assert week.transfer_hit_points == 0
            assert week.chip is None


@pytest.mark.parametrize("switch", ["require_optimal", "observation_proposals"])
def test_search_switches_reject_truthy_strings(known_optimum_players, small_config, switch):
    with pytest.raises(ValueError, match="booleans"):
        optimize_observed_recourse(
            *problem(known_optimum_players, small_config, 3), **{switch: "false"}
        )
