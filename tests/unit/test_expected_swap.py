"""Fixed synthetic swap neighborhood and work-accounting regressions; no data inputs."""

from dataclasses import replace

import pandas as pd
import pytest

from squadopt.contracts.preferences import DecisionPreferences
from squadopt.optimization import OptimizationConfig, SolverStatus
from squadopt.planning.expected_swap import propose_expected_swap
from squadopt.planning.expected_window import optimize_expected_window
from squadopt.planning.lineup_utility import expected_week_utility, rescore_expected_week
from squadopt.planning.models import (
    ChipAvailability,
    ChipUseWindow,
    InitialSquadState,
    PlanningHorizon,
    PlanningWeekResult,
    TransferPlanningConfig,
    TransferPlanResult,
)
from squadopt.scenarios.expected_lineup import expected_lineup_score


def world(window=3, *, string_ids=False):
    positions = ["GK"] * 2 + ["DEF"] * 5 + ["MID"] * 5 + ["FWD"] * 5
    points = [4, 2, 5, 5, 5, 1, 1, 7, 7, 7, 7, 1, 4, 1, 1, 12, 12]
    identity = (lambda p: f"p{p:02d}") if string_ids else (lambda p: p)
    rows = [
        {
            "gameweek": week,
            "player_id": identity(p),
            "name": f"Player {p}",
            "team_id": p,
            "position": positions[p - 1],
            "buy_price_tenths": 50,
            "sell_price_tenths": 50,
            "expected_points": float(points[p - 1]),
            "appearance_probability": 1.0,
        }
        for week in range(1, window + 1)
        for p in range(1, 18)
    ]
    horizon = PlanningHorizon(pd.DataFrame(rows))
    initial = InitialSquadState(tuple(identity(p) for p in range(1, 16)), 5, 1)
    config = OptimizationConfig(solver_deterministic_time_limit=5, solver_time_limit_seconds=120)
    transfer = TransferPlanningConfig(horizon_discount_factor=0.9, banked_transfer_value_points=1.5)
    weeks = []
    for week in horizon.gameweeks:
        table = horizon.table.loc[horizon.table.gameweek.eq(week)].set_index(
            "player_id", drop=False
        )
        squad = table.loc[list(initial.squad_player_ids)]
        xi = squad.loc[[identity(p) for p in (1, 3, 4, 5, 8, 9, 10, 11, 13, 14, 15)]]
        bench = squad.loc[[identity(p) for p in (2, 6, 7, 12)]]
        score = float(xi.expected_points.sum()) + 7
        weeks.append(
            rescore_expected_week(
                PlanningWeekResult(
                    gameweek=week,
                    selected_squad=squad,
                    starting_xi=xi,
                    bench=bench,
                    captain=table.loc[identity(8)],
                    transfers_in=table.iloc[:0],
                    transfers_out=table.iloc[:0],
                    bank_before_tenths=5,
                    bank_after_tenths=5,
                    free_transfers_before=min(week, 5),
                    free_transfers_unused=min(week, 5),
                    free_transfers_for_next_gameweek=min(week + 1, 5),
                    transfer_count=0,
                    paid_transfer_count=0,
                    transfer_hit_points=0,
                    projected_score=score,
                    projected_bench_points=float(bench.expected_points.sum()),
                    discounted_objective_contribution=0.9 ** (week - 1) * score,
                    vice_captain_id=identity(9),
                )
            )
        )
    plan = TransferPlanResult(
        solver_status=SolverStatus.OPTIMAL,
        weeks=tuple(weeks),
        horizon_fingerprint=horizon.horizon_fingerprint,
        total_projected_score=sum(w.projected_score for w in weeks),
        total_projected_bench_points=sum(w.projected_bench_points for w in weeks),
        total_transfer_hit_points=0,
        objective_value=sum(w.discounted_objective_contribution for w in weeks),
        diagnostics={
            "sequential_incumbent": {"actual_total": 0.5, "seed_completed": True},
            "deterministic_time_used": 0.5,
            "terminal_banked_transfer_value": 0,
        },
    )
    return horizon, initial, config, transfer, plan


def call(problem, *, template=None, retained=None, **kwargs):
    horizon, initial, config, transfer, plan = problem
    return propose_expected_swap(
        horizon,
        initial,
        config,
        transfer,
        template or plan.weeks[0],
        (frozenset(initial.squad_player_ids),) if retained is None else retained,
        deterministic_slack=kwargs.pop("deterministic_slack", 3.0),
        wall_slack=kwargs.pop("wall_slack", 60.0),
        **kwargs,
    )


def no_solve(*args, **kwargs):
    pytest.fail("A documented no-op must not start another CP solve.")


@pytest.mark.parametrize("window", [3, 5])
def test_one_real_cold_full_horizon_candidate_keeps_initial_purchase_state(window):
    horizon, initial, config, transfer, plan = world(window)
    table = horizon.table.copy()
    table.loc[table.player_id.eq(14), ["buy_price_tenths", "sell_price_tenths"]] = [60, 45]
    horizon = PlanningHorizon(table)
    transfer = replace(transfer, acquisition_sell_on_fee=0.5, transfer_hit_cost_points=8)
    if window == 5:
        initial = replace(initial, free_transfers=0)
    # The cheap ranking sees the same fixed first-week points. The real CP model
    # receives the revised, captured transaction basis and original bank/FT.
    result, record = call((horizon, initial, config, transfer, plan))
    assert result is not None and tuple(w.gameweek for w in result.weeks) == horizon.gameweeks
    assert record["solver_calls"] == 1 and record["outgoing"] == 14 and record["incoming"] == 16
    first = result.weeks[0]
    assert set(first.selected_squad.player_id) == set(initial.squad_player_ids) - {14} | {16}
    assert set(first.transfers_out.player_id) == {14} and set(first.transfers_in.player_id) == {16}
    assert first.bank_before_tenths == 5 and first.bank_after_tenths == 0
    assert first.free_transfers_before == initial.free_transfers
    assert first.paid_transfer_count == (1 if window == 5 else 0)
    assert first.transfer_hit_points == (4 if window == 5 else 0)
    assert record["actual"] <= record["cap"] + 0.01
    assert record["hold_score_calls"] == 0 and record["cheap_pair_checks"] == 30
    assert record["cheap_pair_cap"] == 30 and record["proxy_is_exact_gain"] is False
    assert record["lineup_search"]["evaluations"] <= 128 * window
    for week in result.weeks:
        assert (
            len(week.selected_squad) == 15 and len(week.starting_xi) == 11 and len(week.bench) == 4
        )
        assert set(week.starting_xi.player_id).isdisjoint(week.bench.player_id)
        assert (
            week.bank_after_tenths >= 0 and week.transfer_hit_points == 4 * week.paid_transfer_count
        )
        assert week.lineup_expectation is not None
    pd.testing.assert_frame_equal(horizon.table, table)


def test_duplicate_first_action_and_keep_or_club_filters_do_not_add_a_retry(monkeypatch):
    problem = list(world())
    table = problem[0].table.copy()
    # Only outgoing 14 / incoming 16 has a positive template proxy.
    table.loc[table.player_id.isin((13, 15)), "expected_points"] = 100
    table.loc[table.player_id.eq(17), "expected_points"] = 0
    problem[0] = PlanningHorizon(table)
    duplicate = frozenset(set(problem[1].squad_player_ids) - {14} | {16})
    monkeypatch.setattr("squadopt.planning.expected_swap.optimize_transfer_plan", no_solve)
    result, record = call(tuple(problem), retained=(duplicate,))
    assert result is None and record["reason"] == "no_distinct_legal_positive_pair"
    result, record = call(tuple(problem), preferences=DecisionPreferences(keep_players=(14,)))
    assert result is None and record["solver_calls"] == 0
    table.loc[table.player_id.isin((1, 3, 4, 16)), "team_id"] = 1
    problem[0] = PlanningHorizon(table)
    result, record = call(tuple(problem))
    assert result is None and record["solver_calls"] == 0


@pytest.mark.parametrize("strings", [False, True])
def test_tied_cheap_pairs_use_stable_ids_and_one_original_config_solve(monkeypatch, strings):
    problem = world(string_ids=strings)
    horizon, initial, config, transfer, _plan = problem
    captured = []
    rights = ChipAvailability(
        available={"3xc": frozenset({2, 3})},
        use_windows={"3xc": (ChipUseWindow(frozenset({2, 3}), holding_value_points=2),)},
    )
    preferences = None if strings else DecisionPreferences(keep_players=(13,), no_hits=True)

    def refused(h, state, settings, policy, **kwargs):
        captured.append((h, state, settings, policy, kwargs))
        return TransferPlanResult(
            SolverStatus.INFEASIBLE,
            (),
            h.horizon_fingerprint,
            None,
            None,
            None,
            None,
            {"deterministic_time_used": 0.125},
        )

    monkeypatch.setattr("squadopt.planning.expected_swap.optimize_transfer_plan", refused)
    result, record = call(problem, chips=rights, preferences=preferences)
    identity = (lambda p: f"p{p:02d}") if strings else (lambda p: p)
    assert result is None and record["reason"] == "optional_no_solution"
    assert (record["outgoing"], record["incoming"]) == (identity(14), identity(16))
    assert len(captured) == 1
    h, state, settings, policy, kwargs = captured[0]
    assert h is horizon and state is initial and policy is transfer
    assert (
        settings.bench_weight == config.bench_weight
        and settings.solver_deterministic_time_limit == 3
    )
    assert kwargs["chips"] is rights
    if preferences is not None:
        assert kwargs["preferences"] is preferences
    assert kwargs["protect_hold"] is False and kwargs["incumbent_plan"] is None
    assert kwargs["protect_incumbent"] is False and kwargs["linearization_level"] == 2
    assert set(kwargs["fixed_week_squads"]) == {1}
    assert record["actual"] == 0.125
    assert record["solver_phase_wall_cap_seconds"] * 2 == record["solver_wall_cap_seconds"]


@pytest.mark.parametrize(
    "case,reason",
    [
        ("cp", "no_remaining_budget"),
        ("wall", "no_remaining_budget"),
        ("horizon", "unsupported_horizon"),
        ("nohits", "no_free_transfer_and_no_hits"),
        ("wc", "first_week_rebuild"),
        ("fh", "first_week_rebuild"),
        ("not_starting", "first_week_role_exclusions_not_supported"),
        ("not_captain", "first_week_role_exclusions_not_supported"),
        ("bench_exclusion", "first_week_role_exclusions_not_supported"),
        ("noncaptain_exclusion", "first_week_role_exclusions_not_supported"),
        ("avoid", "no_distinct_legal_positive_pair"),
        ("price", "no_distinct_legal_positive_pair"),
        ("nonpositive", "no_distinct_legal_positive_pair"),
    ],
)
def test_explicit_noops_have_no_solver_calls(monkeypatch, case, reason):
    problem = list(world(2 if case == "horizon" else 3))
    horizon, initial, _config, _transfer, _plan = problem
    kwargs = {}
    if case == "cp":
        kwargs["deterministic_slack"] = 0.0
    if case == "wall":
        kwargs["wall_slack"] = 0.0
    if case == "nohits":
        problem[1] = replace(initial, free_transfers=0)
        kwargs["preferences"] = DecisionPreferences(no_hits=True)
    if case in {"wc", "fh"}:
        chip = "wildcard" if case == "wc" else "freehit"
        kwargs["chips"] = ChipAvailability({chip: frozenset({1})}, {1: chip})
    if case == "not_starting":
        kwargs["not_starting"] = (14,)
    if case == "not_captain":
        kwargs["not_captain"] = (8,)
    if case == "bench_exclusion":
        kwargs["not_starting"] = (6,)
    if case == "noncaptain_exclusion":
        kwargs["not_captain"] = (13,)
    if case == "avoid":
        kwargs["preferences"] = DecisionPreferences(avoid_players=(16, 17))
    if case in {"price", "nonpositive"}:
        table = horizon.table.copy()
        column, value = ("buy_price_tenths", 100) if case == "price" else ("expected_points", 0)
        table.loc[table.player_id.isin((16, 17)), column] = value
        problem[0] = PlanningHorizon(table)
    monkeypatch.setattr("squadopt.planning.expected_swap.optimize_transfer_plan", no_solve)
    result, record = call(tuple(problem), **kwargs)
    assert result is None and record["solver_calls"] == 0 and record["reason"] == reason


def test_reconstructed_initial_roster_needs_one_score_and_remapped_roles_are_checked(monkeypatch):
    problem = world()
    horizon, _, _, _, plan = problem
    table = horizon.table.loc[horizon.table.gameweek.eq(1)].set_index("player_id", drop=False)
    first = plan.weeks[0]

    def ids(frame):
        return [16 if p == 14 else p for p in frame.player_id]

    template = replace(
        first,
        selected_squad=table.loc[ids(first.selected_squad)],
        starting_xi=table.loc[ids(first.starting_xi)],
        captain=table.loc[16],
        vice_captain_id=8,
        lineup_expectation=None,
    )
    calls = []

    def score(*args, **kwargs):
        calls.append((args, kwargs))
        return expected_lineup_score(*args, **kwargs)

    monkeypatch.setattr("squadopt.planning.expected_swap.expected_lineup_score", score)
    monkeypatch.setattr("squadopt.planning.expected_swap.optimize_transfer_plan", no_solve)
    result, record = call(problem, template=template, not_captain=(14,))
    assert (
        result is None
        and record["reason"] == "first_week_role_exclusions_not_supported"
        and not calls
    )
    result, record = call(
        problem, template=template, preferences=DecisionPreferences(avoid_players=(16, 17))
    )
    assert result is None and record["hold_score_calls"] == 1 and len(calls) == 1
    args, _ = calls[0]
    assert args[3] == 14 and args[4] == 8
    assert set(args[0].player_id) == set(range(1, 16))


@pytest.mark.parametrize("actual", [float("nan"), -1.0, 4.0, True])
def test_bad_optional_accounting_is_not_hidden_as_a_fallback(monkeypatch, actual):
    problem = world()

    def malformed(h, *args, **kwargs):
        return TransferPlanResult(
            SolverStatus.INFEASIBLE,
            (),
            h.horizon_fingerprint,
            None,
            None,
            None,
            None,
            {"deterministic_time_used": actual},
        )

    monkeypatch.setattr("squadopt.planning.expected_swap.optimize_transfer_plan", malformed)
    with pytest.raises(ValueError, match="accounting"):
        call(problem)


@pytest.mark.parametrize(
    "status,clock", [(SolverStatus.UNKNOWN, False), (SolverStatus.FEASIBLE, True)]
)
def test_failed_optional_solve_is_not_retried(monkeypatch, status, clock):
    problem = world()
    calls = []

    def failed(h, *args, **kwargs):
        calls.append(kwargs)
        if status is SolverStatus.UNKNOWN:
            return TransferPlanResult(
                status,
                (),
                h.horizon_fingerprint,
                None,
                None,
                None,
                None,
                {"deterministic_time_used": 3.0, "deterministic_time_budget_exhausted": True},
            )
        return replace(
            problem[-1],
            solver_status=status,
            diagnostics={
                "deterministic_time_used": 0.1,
                "deterministic_time_budget_exhausted": not clock,
            },
        )

    monkeypatch.setattr("squadopt.planning.expected_swap.optimize_transfer_plan", failed)
    result, record = call(problem)
    assert result is None and len(calls) == 1
    assert record["reason"] == (
        "optional_wall_clock_truncation" if clock else "optional_no_solution"
    )


@pytest.mark.parametrize("chip", ["wildcard", "freehit"])
def test_a_rebuild_chosen_by_the_optional_solve_is_discarded_without_rescore(monkeypatch, chip):
    problem = world()
    calls = []

    def rebuilding(h, initial, settings, transfer, **kwargs):
        calls.append(kwargs)
        ids = kwargs["fixed_week_squads"][1]
        table = h.table.loc[h.table.gameweek.eq(1)].set_index("player_id", drop=False)
        first = replace(problem[-1].weeks[0], selected_squad=table.loc[list(ids)], chip=chip)
        return replace(
            problem[-1],
            weeks=(first, *problem[-1].weeks[1:]),
            diagnostics={"deterministic_time_used": 0.125},
        )

    monkeypatch.setattr("squadopt.planning.expected_swap.optimize_transfer_plan", rebuilding)
    monkeypatch.setattr("squadopt.planning.expected_swap.improve_plan_lineups", no_solve)
    result, record = call(problem, chips=ChipAvailability({chip: frozenset({1, 2, 3})}))
    assert result is None and len(calls) == 1
    assert record["reason"] == "optional_first_week_rebuild" and record["actual"] == 0.125


def original_routes(monkeypatch, problem, *, status=SolverStatus.OPTIMAL, seed=True, actual=0.5):
    plan = problem[-1]
    calls = []

    def route(h, state, config, transfer, **kwargs):
        calls.append(config)
        return replace(
            plan,
            solver_status=status,
            diagnostics={
                **plan.diagnostics,
                "sequential_incumbent": {"actual_total": actual, "seed_completed": seed},
                "deterministic_time_budget_exhausted": True,
            },
        )

    monkeypatch.setattr("squadopt.planning.expected_window.optimize_guarded_window", route)
    return calls


@pytest.mark.parametrize(
    "status,seed", [(SolverStatus.FEASIBLE, True), (SolverStatus.OPTIMAL, False)]
)
def test_incomplete_original_proof_or_seed_never_spends_optional_work(monkeypatch, status, seed):
    problem = world()
    original_routes(monkeypatch, problem, status=status, seed=seed)
    monkeypatch.setattr("squadopt.planning.expected_window.propose_expected_swap", no_solve)
    result = optimize_expected_window(*problem[:4])
    review = result.diagnostics["expected_lineup_window"]
    assert (
        len(review["candidates"]) == 2
        and review["optional_swap"]["reason"] == "original_routes_incomplete"
    )


def test_original_proposals_ties_and_gross_recycled_caps_remain_honest(monkeypatch):
    problem = world()
    routes = original_routes(monkeypatch, problem)

    def unchanged_roles(plan, *args, **kwargs):
        work = {
            "evaluations": len(plan.weeks),
            "weeks": [{"states_evaluated": 1, "evaluations": 1, "cap": 128} for _ in plan.weeks],
        }
        return replace(plan, diagnostics={**plan.diagnostics, "lineup_search": work})

    monkeypatch.setattr("squadopt.planning.expected_window.improve_plan_lineups", unchanged_roles)
    # Use the first original scored plan as an equal-utility optional response;
    # this isolates stable final menu selection from candidate construction.
    captured = []

    def optional(h, initial, config, transfer, template, retained, **kwargs):
        captured.append(kwargs)
        plan = replace(problem[-1], weeks=(template, *problem[-1].weeks[1:]))
        return plan, {
            "phase": "initial_single_swap",
            "status": "OPTIMAL",
            "reason": "retained",
            "cap": kwargs["deterministic_slack"],
            "actual": 0.25,
            "solver_calls": 1,
            "hold_score_calls": 1,
            "hold_score_states": 8,
            "lineup_search": None,
        }

    monkeypatch.setattr("squadopt.planning.expected_window.propose_expected_swap", optional)
    result = optimize_expected_window(*problem[:4])
    review = result.diagnostics["expected_lineup_window"]
    assert [r.solver_deterministic_time_limit for r in routes] == [2, 3]
    assert [r.bench_weight for r in routes] == [0.1, 0.0]
    assert captured[0]["deterministic_slack"] == 4
    assert [r["proposal"] for r in review["candidates"]][:2] == [
        "legacy_proposal",
        "zero_bonus_proposal",
    ]
    assert review["actual_total"] == 1.25 and review["gross_sequential_issued_cap"] == 9
    assert review["released_after_original_phases"] == review["reused_cap"] == 4
    assert review["configured_total"] == 5
    assert (
        review["lineup_evaluation_cap"] == 1153 and review["previous_lineup_evaluation_cap"] == 768
    )
    assert review["equal_total_lineup_work_claim"] is False
    assert len({r["utility"] for r in review["candidates"]}) == 1
    assert review["chosen"] == "legacy_proposal"
    assert (
        sum(expected_week_utility(w, problem[3]) * 0.9**i for i, w in enumerate(result.weeks)) >= 0
    )
