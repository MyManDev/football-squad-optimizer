"""Offline application review preserves human choice, provenance and raw point units."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from tests.unit.test_planner_decision_quality import problem

from squadopt.application.planner_review import ObservationContext, review_observed_plans
from squadopt.application.top100_weight import Top100Counts
from squadopt.planning import PlanningHorizon
from squadopt.planning.recourse import (
    ObservationNode,
    _continuation_horizon,
    optimize_observed_recourse,
)


@pytest.mark.parametrize("window", [3, 5])
def test_review_preserves_selected_weight_and_reports_raw_branch_points(
    known_optimum_players, small_config, window
):
    args = problem(known_optimum_players, small_config, window)
    cutoff = datetime(2026, 9, 29, tzinfo=UTC)
    context = ObservationContext("synthetic-predecision", cutoff, cutoff, "authored sensitivity")
    counts = Top100Counts({7: 100, 8: 25}, "fixture", "fixture", "fixture", 0)
    report = review_observed_plans(
        *args,
        context=context,
        decision_cutoff=cutoff,
        selected_weight=20,
        alternatives=(0, 50),
        counts=counts,
    )
    assert report.selected_weight == 20
    assert [option.top100_weight for option in report.options] == [20, 0, 50]
    assert not report.calibration_verified
    pure = next(o for o in report.options if o.top100_weight == 0)
    assert pure.base_expected_net == pytest.approx(
        pure.rollout.candidates[pure.rollout.chosen_index].expected_net_points
    )
    weighted = report.options[0]
    assert (
        weighted.base_expected_net
        < weighted.rollout.candidates[weighted.rollout.chosen_index].expected_net_points
    )
    assert all(o.minimum_node_base_net <= o.base_expected_net for o in report.options)
    with pytest.raises(ValueError, match="previous gameweek"):
        review_observed_plans(
            *args, context=context, decision_cutoff=cutoff, counts=replace(counts, picks_gameweek=1)
        )
    with pytest.raises(ValueError, match="evidence"):
        review_observed_plans(*args, context=context, decision_cutoff=cutoff)


@pytest.mark.parametrize("kind", ["late_issue", "late_evidence", "naive", "no_source"])
def test_future_or_unattributed_information_is_rejected_before_search(kind):
    cutoff = datetime(2026, 9, 29, tzinfo=UTC)
    context = ObservationContext("snapshot", cutoff, cutoff, "stress, not calibrated")
    if kind == "late_issue":
        context = replace(context, issued_at=cutoff + timedelta(seconds=1))
    elif kind == "late_evidence":
        context = replace(context, evidence_cutoff=cutoff + timedelta(seconds=1))
    elif kind == "naive":
        context = replace(context, issued_at=cutoff.replace(tzinfo=None))
    else:
        context = replace(context, source_id=" ")
    with pytest.raises(ValueError):
        context.validate(cutoff)


@pytest.mark.parametrize("chip", [None, "freehit"])
@pytest.mark.parametrize("market,expected", [(43, 43), (53, 51), (54, 52)])
def test_first_purchase_book_rebases_gain_loss_but_freehit_restores_original_book(
    known_optimum_players, small_config, chip, market, expected
):
    baseline, initial, nodes, config = problem(known_optimum_players, small_config, 3)
    result = optimize_observed_recourse(
        baseline, initial, nodes, config, candidate_count=1, value_extra_free_transfer=False
    )
    week = result.candidates[0].first_week
    bought = baseline.table.loc[
        baseline.table.gameweek.eq(1) & baseline.table.player_id.eq(8)
    ].copy()
    week = replace(week, chip=chip, transfers_in=bought)
    future = nodes[0].horizon.table.copy()
    future.loc[future.player_id.eq(8), "buy_price_tenths"] = market
    future.loc[future.player_id.eq(8), "sell_price_tenths"] = 40
    node = ObservationNode("price-evidence", 1, PlanningHorizon(future))
    rebased = _continuation_horizon(node, week)
    assert (
        rebased.table.loc[rebased.table.player_id.eq(8), "sell_price_tenths"]
        .eq(40 if chip else expected)
        .all()
    )
    assert (
        node.horizon.table.loc[node.horizon.table.player_id.eq(8), "sell_price_tenths"].eq(40).all()
    )
