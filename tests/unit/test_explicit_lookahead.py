"""The explicit lookahead runner's arithmetic, gates and reading rule, on synthetic frames.

Nothing here solves a real capture. It pins what the runner declares before a result: the
case set, equal budgets, the self-parity gate, the availability flag, the handoff, and the
rule that reads a pair without turning an unproved shortfall into a loss.
"""

from dataclasses import replace

import pandas as pd
import pytest
from scripts.measure_explicit_lookahead import (
    AVAILABILITY_LABEL,
    UNITS_PER_WEEK,
    WALL_CEILING_SECONDS,
    Case,
    budget_arithmetic,
    cases,
    compact,
    first_action,
    flagged_players,
    handoff,
    label_pair,
    path_summary,
    render_markdown,
    self_parity,
    solve_record,
    solver_config,
    summarize,
)
from tests.unit.test_shortlist_matrix import CONFIG, world

from squadopt.optimization import SolverStatus
from squadopt.planning import optimize_transfer_plan, to_planning_horizon
from squadopt.planning.recourse_chips import net_week_points


def test_the_declared_cases_are_the_served_tail_for_three_weeks_and_expiry_for_both():
    declared = cases(6, 19, [1000, 900])
    assert declared == [
        Case(1000, 3, "served", 10),
        Case(1000, 3, "expiry", 19),
        Case(1000, 5, "expiry", 19),
        Case(900, 3, "served", 10),
        Case(900, 3, "expiry", 19),
        Case(900, 5, "expiry", 19),
    ]


def test_control_and_lookahead_budgets_are_equal_by_construction():
    for case, units in zip(cases(6, 19, [1000]), (100.0, 280.0, 280.0), strict=True):
        arithmetic = budget_arithmetic(case, 6)
        assert arithmetic["control_units"] == arithmetic["lookahead_units"] == units
        assert arithmetic["forecast_weeks"] * UNITS_PER_WEEK == units
    config = solver_config(14)
    assert config.solver_deterministic_time_limit == 280.0
    assert config.solver_time_limit_seconds == WALL_CEILING_SECONDS
    assert config.bench_weight == 0


def _frame(weeks, points=None):
    rows = []
    for week in weeks:
        for player in (1, 2):
            rows.append(
                dict(
                    gameweek=week,
                    player_id=player,
                    expected_points=(points or {}).get((week, player), 3.0 + player),
                    appearance_probability=0.9,
                    fixture_count=1,
                    price_tenths=50,
                )
            )
    return pd.DataFrame(rows)


def test_self_parity_holds_equal_served_weeks_and_refuses_a_moved_number_or_a_lost_row():
    served = _frame((6, 7))
    self_parity(served, _frame((6, 7, 8)))
    with pytest.raises(ValueError, match="Self-parity failed on expected_points"):
        self_parity(served, _frame((6, 7, 8), {(7, 2): 5.0 + 1e-8}))
    with pytest.raises(ValueError, match="served rows"):
        self_parity(served, _frame((6, 8)))
    # The reader narrows its horizon to the base columns; the gate compares what both carry.
    self_parity(served.drop(columns="appearance_probability"), _frame((6, 7, 8)))
    with pytest.raises(ValueError, match="expected_points"):
        self_parity(
            served.drop(columns="appearance_probability"),
            _frame((6, 7, 8), {(6, 1): 4.0 + 1e-8}),
        )
    with pytest.raises(ValueError, match="no expected points"):
        self_parity(served.drop(columns="expected_points"), _frame((6, 7, 8)))


def test_flagged_players_are_those_the_capture_prices_below_one():
    availability = pd.DataFrame(
        {
            "player_id": [1, 2, 3, 4, 5, 6],
            "status": ["a", "a", "d", "i", "u", "a"],
            "chance_of_playing": [pd.NA, 75, pd.NA, 0, pd.NA, 100],
        }
    )
    assert flagged_players(availability) == frozenset({2, 3, 4, 5})


def test_path_summary_reports_transfers_paid_transfers_and_reversals_apart():
    weeks = [
        {"in": [10], "out": [1], "hit_points": 0.0, "net_points": 50.0},
        {"in": [1, 11], "out": [10, 2], "hit_points": 4.0, "net_points": 48.0},
        {"in": [], "out": [], "hit_points": 0.0, "net_points": 49.0},
    ]
    summary = path_summary(weeks)
    assert summary == {
        "transfer_count": 3,
        "paid_transfer_count": 1,
        "reversals": 2,
        "hit_points": 4.0,
        "net_points": 147.0,
    }


def _arm(status, net, squad, incoming=(5,), free_next=1, hits=0.0, bound=None):
    return {
        "valid": True,
        "status": status,
        "net_points": net,
        "hit_points": hits,
        "best_objective_bound": bound,
        "first_action": {
            "squad": sorted(squad),
            "in": list(incoming),
            "out": [],
            "hit_points": hits,
        },
        "weeks": [{"free_next": free_next}, {"free_next": free_next}],
    }


def test_a_pair_is_read_by_the_declared_rule():
    control = _arm("OPTIMAL", 100.0, range(1, 16))
    continuation = _arm("OPTIMAL", 200.0, range(1, 16))
    ahead = _arm("OPTIMAL", 301.5, range(2, 17), bound=305.0)
    pair = label_pair(control, continuation, ahead, frozenset())
    assert pair["delta"] == pytest.approx(1.5)
    assert pair["gain_upper_bound"] == pytest.approx(5.0)
    assert pair["labels"] == ["first_week_changed", "gain_defined"]
    flagged = label_pair(control, continuation, ahead, frozenset({16}))
    assert flagged["labels"] == ["first_week_changed", AVAILABILITY_LABEL, "gain_defined"]
    held = label_pair(
        control, continuation, _arm("OPTIMAL", 300.0, range(1, 16), incoming=()), frozenset()
    )
    assert held["labels"] == ["hold_equal", "gain_defined"]
    assert held["delta"] == pytest.approx(0.0)


def test_an_unproved_shortfall_is_not_a_loss_and_a_proved_one_is_a_defect():
    control = _arm("OPTIMAL", 100.0, range(1, 16))
    unproved = _arm("FEASIBLE", 200.0, range(1, 16))
    behind = _arm("FEASIBLE", 297.0, range(1, 16), incoming=())
    pair = label_pair(control, unproved, behind, frozenset())
    assert pair["delta"] is None
    assert pair["delta_unread"] == pytest.approx(-3.0)
    assert pair["labels"] == ["unproved_shortfall", "hold_equal"]
    with pytest.raises(ValueError, match="code defect"):
        label_pair(
            control,
            _arm("OPTIMAL", 200.0, range(1, 16)),
            _arm("OPTIMAL", 297.0, range(1, 16)),
            frozenset(),
        )
    failed = label_pair(control, {"valid": False, "status": "FAILED"}, behind, frozenset())
    assert failed == {"valid": False, "labels": ["failed"]}


def test_a_real_two_week_solve_is_recorded_and_handed_on_with_its_end_state():
    projection, state = world()
    horizon = to_planning_horizon(projection)
    plan = optimize_transfer_plan(horizon, state, CONFIG, protect_hold=True, linearization_level=2)
    record = solve_record(plan, horizon, 1.0)
    assert record["valid"] and record["status"] == "OPTIMAL"
    assert record["net_points"] == pytest.approx(sum(net_week_points(w) for w in plan.weeks))
    assert record["first_action"] == first_action(plan.weeks[0])
    assert len(record["first_action"]["squad"]) == 15
    assert [w["net_points"] for w in record["weeks"]] == pytest.approx(
        [net_week_points(w) for w in plan.weeks]
    )
    assert record["transfer_count"] == sum(w.transfer_count for w in plan.weeks)
    handed = handoff(plan.weeks[-1])
    assert set(handed.squad_player_ids) == set(plan.weeks[-1].selected_squad.player_id)
    assert handed.bank_tenths == plan.weeks[-1].bank_after_tenths
    assert handed.free_transfers == plan.weeks[-1].free_transfers_for_next_gameweek


def test_a_solve_the_clock_stopped_is_failed_and_never_read():
    projection, state = world()
    horizon = to_planning_horizon(projection)
    plan = optimize_transfer_plan(horizon, state, CONFIG, protect_hold=True, linearization_level=2)
    cut = replace(
        plan,
        solver_status=SolverStatus.FEASIBLE,
        diagnostics={**plan.diagnostics, "deterministic_time_budget_exhausted": False},
    )
    record = solve_record(cut, horizon, 1.0)
    assert record == {"valid": False, "status": "FAILED", "error": "wall clock stopped the search"}
    exhausted = replace(
        cut, diagnostics={**cut.diagnostics, "deterministic_time_budget_exhausted": True}
    )
    assert solve_record(exhausted, horizon, 1.0)["status"] == "FEASIBLE"


def _records():
    control = _arm("OPTIMAL", 100.0, range(1, 16))
    return [
        {
            "profile": 1000,
            "window": 3,
            "tail": "served",
            "last_week": 10,
            "budget": {},
            "arms": {
                "window": control,
                "continuation": control,
                "lookahead": _arm("OPTIMAL", 201.0, range(2, 17)),
            },
            "pair": label_pair(control, control, _arm("OPTIMAL", 201.0, range(2, 17)), frozenset()),
        },
        {
            "profile": 1000,
            "window": 5,
            "tail": "expiry",
            "last_week": 19,
            "budget": {},
            "arms": {
                "window": control,
                "continuation": control,
                "lookahead": {"valid": False, "status": "FAILED"},
            },
            "pair": {"valid": False, "labels": ["failed"]},
        },
    ]


def test_summary_and_compact_record_keep_labels_and_drop_week_tables():
    rolling = {"1000": {"valid": True, "net_points": 290.0, "weeks": [{"in": []}]}}
    summary = summarize(_records(), rolling)
    assert summary["cases"] == 2 and summary["valid_pairs"] == 1 and summary["failed_pairs"] == 1
    assert summary["first_week_changed"] == 1 and summary["gains_over_0_1"] == 1
    assert summary["rolling_one_week"] == {"1000": {"net_points": 290.0, "valid": True}}
    assert summary["promotion"] is False and summary["realized_returns"] is False
    compacted = compact(_records(), rolling)
    assert all("weeks" not in arm for case in compacted["cases"] for arm in case["arms"].values())
    assert "weeks" not in compacted["rolling_one_week"]["1000"]
    table = render_markdown(compacted)
    assert table.splitlines()[0].startswith("| Profile | Window | Tail |")
    assert "| 1000 | 3 | served to GW10 |" in table and "+1.000000" in table
    assert "not read" in table
