"""Information branches preserve expectation, resources and the shared solve budget."""

from dataclasses import replace

import pandas as pd
import pytest
from tests.unit.test_planner_incumbent import problem

from squadopt.live.football_observations import availability_observations
from squadopt.optimization import SolverExecutionError, SolverStatus
from squadopt.planning import ChipAvailability, PlanningHorizon, TransferPlanningConfig
from squadopt.planning.observed import optimize_observed_window, validate_observations
from squadopt.planning.recourse import ObservationNode
from squadopt.prediction.football import FOOTBALL_MODEL_VERSION


def comparison_problem(players, config, window=3):
    """Two legal first actions: improve the initially weaker forward or retain him."""
    horizon, initial, optimization = problem(players, config, window)
    initial = replace(initial, squad_player_ids=("GK_A", "DEF_A", "MID_A", "FWD_B"))
    return horizon, initial, optimization


def nodes_for(horizon):
    future = horizon.table.loc[horizon.table.gameweek.ne(horizon.gameweeks[0])].copy()
    yes, no = future.copy(), future.copy()
    selected = future.gameweek.eq(horizon.gameweeks[1]) & future.player_id.eq("FWD_B")
    yes.loc[selected, "expected_points"] *= 2
    no.loc[selected, "expected_points"] = 0
    return (
        ObservationNode("good", 0.5, PlanningHorizon(yes)),
        ObservationNode("bad", 0.5, PlanningHorizon(no)),
    )


@pytest.mark.parametrize("window", [3, 5])
@pytest.mark.parametrize("freehit", [False, True])
def test_complete_budgeted_branches_retain_resources(
    known_optimum_players, small_config, window, freehit
):
    horizon, initial, config = comparison_problem(known_optimum_players, small_config, window)
    rights = ChipAvailability({"freehit": frozenset({1})}, {1: "freehit"}) if freehit else None
    result = optimize_observed_window(
        horizon,
        initial,
        nodes_for(horizon),
        replace(config, bench_weight=0.1, solver_time_limit_seconds=120),
        TransferPlanningConfig(transfer_hit_cost_points=8, acquisition_sell_on_fee=0.5),
        chips=rights,
    )
    assert result.has_solution and len(result.weeks) == window
    review = result.diagnostics["observed_window"]
    assert review["status"] == "compared"
    assert result.diagnostics["selection_status"] == "FEASIBLE_RESTRICTED_MENU"
    assert result.diagnostics["absolute_optimality_gap"] is None
    assert review["allocated_total"] <= 5.000001
    assert review["actual_total"] <= 5.01
    assert review["utility_gain_vs_baseline"] >= 0
    for candidate in review["candidates"]:
        assert len(candidate["branches"]) == 2
        for branch in candidate["branches"]:
            assert len(branch["weeks"]) == window - 1
            assert all(w["bank"] >= 0 and w["ft"] >= 0 for w in branch["weeks"])
    if freehit:
        assert result.weeks[0].chip == "freehit"
        assert result.weeks[1].bank_before_tenths == initial.bank_tenths


@pytest.mark.parametrize("corruption", ["price", "mean", "probability"])
def test_bad_information_rejected_before_solve(known_optimum_players, small_config, corruption):
    horizon, _, _ = problem(known_optimum_players, small_config)
    nodes = list(nodes_for(horizon))
    table = nodes[0].horizon.table.copy()
    if corruption == "price":
        table["buy_price_tenths"] += 1
    elif corruption == "mean":
        table["expected_points"] += 1
    nodes[0] = replace(
        nodes[0],
        horizon=PlanningHorizon(table),
        probability=0.6 if corruption == "probability" else 0.5,
    )
    with pytest.raises(ValueError):
        validate_observations(horizon, tuple(nodes))


def test_partial_comparison_keeps_complete_baseline(
    known_optimum_players, small_config, monkeypatch
):
    import squadopt.planning.observed as module

    horizon, initial, config = comparison_problem(known_optimum_players, small_config)
    original = module.optimize_transfer_plan
    calls = 0

    def fail_continuation(*args, **kwargs):
        nonlocal calls
        calls += 1
        result = original(*args, **kwargs)
        if calls == 3:
            return replace(
                result,
                solver_status=SolverStatus.UNKNOWN,
                weeks=(),
                total_projected_score=None,
                total_projected_bench_points=None,
                total_transfer_hit_points=None,
                objective_value=None,
                diagnostics={**result.diagnostics, "deterministic_time_budget_exhausted": True},
            )
        return result

    monkeypatch.setattr(module, "optimize_transfer_plan", fail_continuation)
    result = module.optimize_observed_window(
        horizon,
        initial,
        nodes_for(horizon),
        replace(config, solver_time_limit_seconds=120),
        TransferPlanningConfig(),
    )
    assert len(result.weeks) == 3 and result.has_solution
    assert result.diagnostics["observed_window"]["status"] == "incomplete_continuation"


@pytest.mark.parametrize("chance", [25, 50, 75])
def test_health_information_preserves_mean_and_minutes(known_optimum_players, small_config, chance):
    horizon, initial, _ = problem(known_optimum_players, small_config)
    ids = {p: i + 1 for i, p in enumerate(horizon.table.player_id.unique())}
    table = horizon.table.copy()
    table["player_id"] = table.player_id.map(ids)
    table["appearance_probability"] = 0.8
    player = ids["FWD_A"]
    mask = table.player_id.eq(player)
    table.loc[mask, "expected_points"] *= chance / 100
    table.loc[mask, "appearance_probability"] *= chance / 100
    horizon = PlanningHorizon(table)
    initial = replace(initial, squad_player_ids=tuple(ids[p] for p in initial.squad_player_ids))
    observations = availability_observations(
        horizon,
        initial,
        pd.DataFrame({"player_id": [player], "chance_of_playing": [chance]}),
        model_version=FOOTBALL_MODEL_VERSION,
        source_snapshot_id="test-capture",
        captured_at_utc="2026-09-01T00:00:00Z",
        deadline_utc="2026-09-02T00:00:00Z",
    )
    assert len(observations.nodes) == 2
    validate_observations(horizon, observations.nodes)
    yes, no = observations.nodes
    assert yes.horizon.table.loc[
        lambda x: x.player_id.eq(player) & x.gameweek.eq(2), "appearance_probability"
    ].iloc[0] == pytest.approx(0.8)
    assert (
        no.horizon.table.loc[
            lambda x: x.player_id.eq(player) & x.gameweek.eq(2), "expected_points"
        ].iloc[0]
        == 0
    )
    assert yes.horizon.table.loc[lambda x: x.gameweek.eq(3), "expected_points"].tolist() == (
        horizon.table.loc[lambda x: x.gameweek.eq(3), "expected_points"].tolist()
    )


def test_clock_truncation_is_not_silently_replaced(
    known_optimum_players, small_config, monkeypatch
):
    import squadopt.planning.observed as module

    horizon, initial, config = problem(known_optimum_players, small_config)
    original = module.optimize_transfer_plan

    def stopped(*args, **kwargs):
        plan = original(*args, **kwargs)
        return replace(
            plan,
            solver_status=SolverStatus.FEASIBLE,
            diagnostics={**plan.diagnostics, "deterministic_time_budget_exhausted": False},
        )

    monkeypatch.setattr(module, "optimize_transfer_plan", stopped)
    with pytest.raises(SolverExecutionError, match="wall-clock"):
        module.optimize_observed_window(
            horizon,
            initial,
            nodes_for(horizon),
            replace(config, solver_time_limit_seconds=120),
            TransferPlanningConfig(),
        )


def test_public_comparison_rescores_top100_on_base_points(known_optimum_players, small_config):
    from squadopt.application.football_information import information_review_payload
    from squadopt.live.recommendation import Projection
    from squadopt.planning import ProjectionHorizon

    horizon, initial, config = comparison_problem(known_optimum_players, small_config)
    ids = {p: i + 1 for i, p in enumerate(horizon.table.player_id.unique())}
    table = horizon.table.copy()
    table["player_id"] = table.player_id.map(ids)
    baseline = PlanningHorizon(table)
    initial = replace(initial, squad_player_ids=tuple(ids[p] for p in initial.squad_player_ids))
    nodes = tuple(
        replace(
            n,
            horizon=PlanningHorizon(
                n.horizon.table.assign(player_id=lambda d: d.player_id.map(ids))
            ),
        )
        for n in nodes_for(horizon)
    )
    result = optimize_observed_window(
        baseline,
        initial,
        nodes,
        replace(config, solver_time_limit_seconds=120),
        TransferPlanningConfig(),
    )
    result = replace(
        result,
        diagnostics={
            **result.diagnostics,
            "availability_information": {
                "reason": "test",
                "source_snapshot_id": "synthetic",
                "captured_at_utc": "2026-09-01T00:00:00Z",
                "player_id": ids["FWD_A"],
                "probability": 0.5,
                "gameweek": 2,
            },
        },
    )
    projection = Projection(table.loc[table.gameweek.eq(1)], (), {})
    base = ProjectionHorizon(
        table.assign(
            price_tenths=50,
            fixture_count=1,
            home_fixture_count=1,
            expected_points=lambda d: d.expected_points / 1.2,
        ),
        "2026-27",
        "synthetic",
        "test",
        "v1",
        "test",
        "test",
    )
    plain = information_review_payload(result, projection)
    weighted = information_review_payload(result, projection, base_horizon=base, weighted=True)
    hidden = information_review_payload(result, projection, weighted=True)
    assert plain["status"] == weighted["status"] == "compared"
    for a, b, c in zip(
        plain["candidates"], weighted["candidates"], hidden["candidates"], strict=True
    ):
        assert c["expected_net_points"] is None
        for raw, shown in zip(a["branches"], b["branches"], strict=True):
            assert shown["hit_points"] == raw["hit_points"]
            assert shown["expected_net_points"] == pytest.approx(
                (raw["expected_net_points"] + raw["hit_points"]) / 1.2 - raw["hit_points"]
            )


@pytest.mark.parametrize(
    "reason,version,chance",
    [
        ("conditional_team_components_unavailable", "football_contextual_v3", 50),
        ("no_usable_held_uncertainty", FOOTBALL_MODEL_VERSION, None),
        ("no_usable_held_uncertainty", FOOTBALL_MODEL_VERSION, 0),
        ("no_usable_held_uncertainty", FOOTBALL_MODEL_VERSION, 100),
    ],
)
def test_no_invented_health_states(known_optimum_players, small_config, reason, version, chance):
    horizon, initial, _ = problem(known_optimum_players, small_config)
    horizon = PlanningHorizon(horizon.table.assign(appearance_probability=0.4))
    info = availability_observations(
        horizon,
        initial,
        pd.DataFrame({"player_id": ["FWD_A"], "chance_of_playing": [chance]}),
        model_version=version,
        source_snapshot_id="synthetic",
        captured_at_utc="2026-09-01T00:00:00Z",
        deadline_utc="2026-09-02T00:00:00Z",
    )
    assert not info.nodes and info.reason == reason


def test_information_cannot_silently_change_appearance_mean(known_optimum_players, small_config):
    horizon, _, _ = problem(known_optimum_players, small_config)
    horizon = PlanningHorizon(horizon.table.assign(appearance_probability=0.8))
    nodes = list(nodes_for(horizon))
    nodes[0] = replace(
        nodes[0], horizon=PlanningHorizon(nodes[0].horizon.table.assign(appearance_probability=0.9))
    )
    with pytest.raises(ValueError, match="appearance expectation"):
        validate_observations(horizon, tuple(nodes))


@pytest.mark.parametrize("chip", ["freehit", "wildcard", "bboost", "3xc"])
def test_dated_chip_is_retained_in_every_continuation(known_optimum_players, small_config, chip):
    horizon, initial, config = comparison_problem(known_optimum_players, small_config)
    rights = ChipAvailability({chip: frozenset({2})}, {2: chip})
    result = optimize_observed_window(
        horizon,
        initial,
        nodes_for(horizon),
        replace(config, solver_time_limit_seconds=120),
        TransferPlanningConfig(),
        chips=rights,
    )
    assert result.diagnostics["observed_window"]["status"] == "compared"
    for candidate in result.diagnostics["observed_window"]["candidates"]:
        assert candidate["first_chip"] is None
        for branch in candidate["branches"]:
            assert branch["weeks"][0]["gameweek"] == 2
            assert branch["weeks"][0]["chip"] == chip
            assert branch["weeks"][1]["chip"] is None


def test_waiting_preserves_an_unaffordable_repurchase_option(known_optimum_players, small_config):
    # A constructed counterexample: selling the held player loses the right to retain
    # him cheaply if good news arrives. This is a correctness test, not measured uplift.
    horizon, initial, config = problem(known_optimum_players, small_config)
    table = horizon.table.copy()
    table["expected_points"] = table.player_id.map(
        {
            "GK_A": 50.0,
            "GK_B": 0.0,
            "DEF_A": 1.0,
            "DEF_B": 0.0,
            "MID_A": 20.0,
            "MID_B": 0.0,
            "FWD_A": 2.0,
            "FWD_B": 3.0,
        }
    )
    table.loc[table.player_id.eq("FWD_A"), "buy_price_tenths"] = 60
    table.loc[table.player_id.eq("FWD_B") & table.gameweek.eq(1), "expected_points"] = 2.1
    table.loc[table.player_id.eq("FWD_A") & table.gameweek.eq(3), "expected_points"] = 3.0
    horizon = PlanningHorizon(table)
    future = table.loc[table.gameweek.gt(1)].copy()
    yes, no = future.copy(), future.copy()
    target = future.player_id.eq("FWD_A") & future.gameweek.eq(2)
    yes.loc[target, "expected_points"] = 4.0
    no.loc[target, "expected_points"] = 0.0
    nodes = (
        ObservationNode("eligible", 0.5, PlanningHorizon(yes)),
        ObservationNode("unavailable", 0.5, PlanningHorizon(no)),
    )
    result = optimize_observed_window(
        horizon,
        initial,
        nodes,
        replace(config, solver_time_limit_seconds=120),
        TransferPlanningConfig(acquisition_sell_on_fee=0.5),
    )
    review = result.diagnostics["observed_window"]
    assert review["status"] == "compared"
    assert review["candidates"][0]["first_in"] == ["FWD_B"]
    assert review["chosen_index"] != 0
    assert result.weeks[0].transfers_in.empty
    assert review["utility_gain_vs_baseline"] == pytest.approx(0.4)
    selected = review["candidates"][review["chosen_index"]]
    eligible, unavailable = selected["branches"]
    assert eligible["weeks"][0]["in"] == []
    assert unavailable["weeks"][0]["in"] == ["FWD_B"]


def _unknown_result(plan):
    return replace(
        plan,
        solver_status=SolverStatus.UNKNOWN,
        weeks=(),
        total_projected_score=None,
        total_projected_bench_points=None,
        total_transfer_hit_points=None,
        objective_value=None,
        chips_played={},
        diagnostics={**plan.diagnostics, "deterministic_time_budget_exhausted": True},
    )


def test_optional_proposal_failure_keeps_complete_action_comparison(
    known_optimum_players, small_config, monkeypatch
):
    import squadopt.planning.observed as module

    horizon, initial, config = comparison_problem(known_optimum_players, small_config)
    original = module.optimize_transfer_plan
    failed = []

    def lose_optional_proposal(*args, **kwargs):
        plan = original(*args, **kwargs)
        if kwargs.get("incumbent_plan") is not None and kwargs.get("first_week_exclusion") is None:
            failed.append(plan)
            return _unknown_result(plan)
        return plan

    monkeypatch.setattr(module, "optimize_transfer_plan", lose_optional_proposal)
    result = module.optimize_observed_window(
        horizon,
        initial,
        nodes_for(horizon),
        replace(config, solver_time_limit_seconds=120),
        TransferPlanningConfig(),
    )
    review = result.diagnostics["observed_window"]
    assert len(failed) == 1
    assert review["status"] == "compared"
    assert review["candidate_count"] == 2
    assert review["proposal_completed"] is False
    assert review["hold_feasible"] is True
    assert all(len(c["branches"]) == 2 for c in review["candidates"])
    assert review["allocated_total"] <= 5.000001


def test_one_distinct_action_does_not_claim_a_comparison(known_optimum_players, small_config):
    horizon, initial, config = problem(known_optimum_players, small_config)
    result = optimize_observed_window(
        horizon,
        initial,
        nodes_for(horizon),
        replace(config, solver_time_limit_seconds=120),
        TransferPlanningConfig(),
    )
    review = result.diagnostics["observed_window"]
    assert result.has_solution and len(result.weeks) == len(horizon.gameweeks)
    assert review["status"] == "no_distinct_alternative"
    assert review["candidate_count"] == 1
    assert "candidates" not in review
    assert not any(row["phase"].startswith("candidate_") for row in review["ledger"])


@pytest.mark.parametrize("fee", [None, 0.5])
def test_full_branches_preserve_first_action_and_recompute_utility(
    known_optimum_players, small_config, monkeypatch, fee
):
    import squadopt.planning.observed as module

    horizon, initial, config = comparison_problem(known_optimum_players, small_config)
    table = horizon.table.copy()
    table.loc[table.player_id.eq("FWD_A"), "buy_price_tenths"] = [50, 55, 60]
    table.loc[table.player_id.eq("FWD_B"), "buy_price_tenths"] = [50, 52, 54]
    table["sell_price_tenths"] = table.buy_price_tenths
    horizon = PlanningHorizon(table)
    initial = replace(initial, bank_tenths=40)
    config = replace(config, bench_weight=0.25, solver_time_limit_seconds=120)
    settings = TransferPlanningConfig(transfer_hit_cost_points=8, acquisition_sell_on_fee=fee)
    original = module.optimize_transfer_plan
    recorded = []

    def capture(*args, **kwargs):
        plan = original(*args, **kwargs)
        if kwargs.get("first_week_exclusion") is not None:
            seed = kwargs["incumbent_plan"]
            assert kwargs["protect_incumbent"] is True
            assert args[0].gameweeks == horizon.gameweeks
            assert args[1] == initial
            before, after = seed.weeks[0], plan.weeks[0]
            for name in ("selected_squad", "starting_xi", "bench", "transfers_in", "transfers_out"):
                assert set(getattr(before, name).player_id) == set(getattr(after, name).player_id)
            assert before.captain.player_id == after.captain.player_id
            for name in (
                "chip",
                "bank_before_tenths",
                "bank_after_tenths",
                "free_transfers_before",
                "free_transfers_unused",
                "free_transfers_for_next_gameweek",
            ):
                assert getattr(before, name) == getattr(after, name)
            recorded.append((args[0], plan))
        return plan

    monkeypatch.setattr(module, "optimize_transfer_plan", capture)
    result = module.optimize_observed_window(
        horizon,
        initial,
        nodes_for(horizon),
        config,
        settings,
    )
    review = result.diagnostics["observed_window"]
    assert review["status"] == "compared"
    assert len(recorded) >= review["candidate_count"] * 2

    def independent_utility(forecast, plan):
        points = forecast.table.set_index(["gameweek", "player_id"]).expected_points
        utility = 0.0
        for week in plan.weeks:
            selected = set(week.selected_squad.player_id)
            starting = set(week.starting_xi.player_id)
            utility += sum(float(points.loc[(week.gameweek, p)]) for p in starting)
            utility += float(points.loc[(week.gameweek, week.captain.player_id)]) * (
                2 if week.chip == "3xc" else 1
            )
            utility += (1 if week.chip == "bboost" else config.bench_weight) * sum(
                float(points.loc[(week.gameweek, p)]) for p in selected - starting
            )
            utility -= week.paid_transfer_count * settings.transfer_hit_cost_points
        return utility

    for index, candidate in enumerate(review["candidates"]):
        first, second = candidate["branches"]
        assert first["first_action"] == second["first_action"]
        assert first["first_action"]["in"] == candidate["first_in"]
        assert first["first_action"]["out"] == candidate["first_out"]
        assert first["first_action"]["chip"] == candidate["first_chip"]
        expected = sum(
            branch["probability"] * independent_utility(*recorded[index * 2 + offset])
            for offset, branch in enumerate(candidate["branches"])
        )
        assert candidate["selection_utility"] == pytest.approx(expected)
    published = result.weeks[0]
    selected = review["candidates"][review["chosen_index"]]["branches"][0]["first_action"]
    assert set(published.selected_squad.player_id) == set(selected["squad"])
    assert set(published.starting_xi.player_id) == set(selected["starters"])
    assert published.captain.player_id == selected["captain"]
    assert published.chip == selected["chip"]


def test_certified_branches_survive_unknown_primary_search(
    known_optimum_players, small_config, monkeypatch
):
    from ortools.sat.python import cp_model

    import squadopt.planning.observed as observed
    import squadopt.planning.optimizer as optimizer

    horizon, initial, config = comparison_problem(known_optimum_players, small_config)
    original_plan = observed.optimize_transfer_plan
    original_solve = optimizer._solve
    original_work = optimizer._deterministic_time_used
    active = False
    retained = []

    def exhaust_primary(model, solver):
        if active and model.has_objective():
            return cp_model.UNKNOWN
        return original_solve(model, solver)

    def simulated_work(solver, status):
        if active and status == cp_model.UNKNOWN:
            return float(solver.parameters.max_deterministic_time)
        return original_work(solver, status)

    def only_branch_search_stops(*args, **kwargs):
        nonlocal active
        active = kwargs.get("first_week_exclusion") is not None
        try:
            result = original_plan(*args, **kwargs)
            if active:
                assert result.has_solution
                assert result.solver_status is SolverStatus.FEASIBLE
                assert result.diagnostics["primary_search_status"] == "UNKNOWN"
                assert result.diagnostics["incumbent_protection"]["selected"] is True
                assert result.diagnostics["deterministic_time_budget_exhausted"] is True
                assert result.objective_value == pytest.approx(
                    kwargs["incumbent_plan"].objective_value
                )
                retained.append(result)
            return result
        finally:
            active = False

    monkeypatch.setattr(optimizer, "_solve", exhaust_primary)
    monkeypatch.setattr(optimizer, "_deterministic_time_used", simulated_work)
    monkeypatch.setattr(observed, "optimize_transfer_plan", only_branch_search_stops)
    result = observed.optimize_observed_window(
        horizon,
        initial,
        nodes_for(horizon),
        replace(config, solver_time_limit_seconds=120),
        TransferPlanningConfig(),
    )
    review = result.diagnostics["observed_window"]
    assert review["status"] == "compared"
    assert len(retained) >= review["candidate_count"] * 2
    assert review["actual_total"] <= 5.000001
    assert review["allocated_total"] <= 5.000001


def test_sub_rounding_utility_loss_retains_seed_without_borrowed_optimality(
    known_optimum_players, small_config, monkeypatch
):
    import squadopt.planning.observed as module

    horizon, initial, config = comparison_problem(known_optimum_players, small_config)
    table = horizon.table.copy()
    last_mid = table.gameweek.eq(3) & table.player_id.eq("MID_A")
    table.loc[last_mid, "expected_points"] = 10.0006
    table.loc[table.gameweek.eq(3) & table.player_id.eq("FWD_A"), "expected_points"] = 10.0
    horizon = PlanningHorizon(table)
    future = table.loc[table.gameweek.gt(1)].copy()
    lower, higher = future.copy(), future.copy()
    future_mid = future.gameweek.eq(3) & future.player_id.eq("MID_A")
    lower.loc[future_mid, "expected_points"] = 10.0004
    higher.loc[future_mid, "expected_points"] = 10.0008
    nodes = (
        ObservationNode("lower", 0.5, PlanningHorizon(lower)),
        ObservationNode("higher", 0.5, PlanningHorizon(higher)),
    )
    original_plan = module.optimize_transfer_plan
    original_clock_check = module.wall_clock_stopped_the_search
    rounded_losses, retained_diagnostics = [], []

    def capture_rounded_search(*args, **kwargs):
        result = original_plan(*args, **kwargs)
        if kwargs.get("first_week_exclusion") is not None:
            seed = kwargs["incumbent_plan"]
            if result.objective_value + 1e-9 < seed.objective_value:
                assert result.solver_status is SolverStatus.OPTIMAL
                assert result.weeks[-1].captain.player_id == "FWD_A"
                assert seed.weeks[-1].captain.player_id == "MID_A"
                assert seed.objective_value - result.objective_value == pytest.approx(0.0004)
                assert (
                    result.diagnostics["scaled_model_objective_value"]
                    == (result.diagnostics["incumbent_protection"]["scaled_objective_value"])
                )
                rounded_losses.append((seed, result))
        return result

    def capture_retention_status(status, diagnostics):
        stopped = original_clock_check(status, diagnostics)
        if diagnostics.get("unrounded_incumbent_retained"):
            assert status is SolverStatus.FEASIBLE
            assert diagnostics["solver_status_name"] == "FEASIBLE"
            assert diagnostics["primary_search_status"] == "OPTIMAL"
            assert diagnostics["scaled_model_objective_value"] is None
            assert diagnostics["best_objective_bound"] is None
            assert diagnostics["absolute_optimality_gap"] is None
            assert diagnostics["relative_optimality_gap"] is None
            assert stopped is False
            retained_diagnostics.append(diagnostics)
        return stopped

    monkeypatch.setattr(module, "optimize_transfer_plan", capture_rounded_search)
    monkeypatch.setattr(module, "wall_clock_stopped_the_search", capture_retention_status)
    result = module.optimize_observed_window(
        horizon,
        initial,
        nodes,
        replace(config, solver_time_limit_seconds=120),
        TransferPlanningConfig(),
    )
    review = result.diagnostics["observed_window"]
    assert review["status"] == "compared"
    assert rounded_losses and len(retained_diagnostics) == len(rounded_losses)
    assert result.solver_status is SolverStatus.FEASIBLE
    assert result.diagnostics["best_objective_bound"] is None
    for candidate in review["candidates"]:
        lower_branch = next(branch for branch in candidate["branches"] if branch["id"] == "lower")
        captains = [
            term["player_id"]
            for term in lower_branch["point_terms"]
            if term["gameweek"] == 3 and term["multiplier"] == 2
        ]
        assert captains == ["MID_A"]


@pytest.fixture
def captured_observed_branches(monkeypatch):
    import squadopt.planning.observed as module

    original = module.optimize_transfer_plan
    captured = []

    def capture(*args, **kwargs):
        result = original(*args, **kwargs)
        if kwargs.get("first_week_exclusion") is not None:
            captured.append((args[0], args[1], result))
        return result

    monkeypatch.setattr(module, "optimize_transfer_plan", capture)
    return captured


def _assert_complete_resource_path(plan, dates, initial, settings):
    assert plan.has_solution
    assert tuple(week.gameweek for week in plan.weeks) == dates
    held = set(initial.squad_player_ids)
    bank, free = initial.bank_tenths, initial.free_transfers
    for week in plan.weeks:
        squad = set(week.selected_squad.player_id)
        starting, bench = set(week.starting_xi.player_id), set(week.bench.player_id)
        assert starting.isdisjoint(bench) and starting | bench == squad
        assert week.captain.player_id in starting
        assert week.selected_squad.groupby("position").size().to_dict() == {
            "GK": 1,
            "DEF": 1,
            "MID": 1,
            "FWD": 1,
        }
        assert set(week.transfers_in.player_id) == squad - held
        assert set(week.transfers_out.player_id) == held - squad
        assert week.transfer_count == len(squad - held) == len(held - squad)
        assert week.bank_before_tenths == bank
        assert week.bank_after_tenths == bank + (
            int(week.transfers_out.sell_price_tenths.sum())
            - int(week.transfers_in.buy_price_tenths.sum())
        )
        assert week.bank_after_tenths >= 0
        assert week.free_transfers_before == free
        rebuild = week.chip in {"wildcard", "freehit"}
        preserved = rebuild and settings.wildcard_preserves_free_transfers
        consumed = 0 if preserved else week.transfer_count
        paid = 0 if rebuild else max(0, week.transfer_count - free)
        assert week.paid_transfer_count == paid
        assert week.transfer_hit_points == pytest.approx(paid * settings.hit_points_charged)
        assert week.free_transfers_unused == max(0, free - consumed)
        free = min(
            settings.max_free_transfers,
            max(0, free - consumed) + (0 if preserved else settings.free_transfer_accrual),
        )
        assert week.free_transfers_for_next_gameweek == free
        assert 0 <= free <= settings.max_free_transfers
        if week.chip != "freehit":
            held, bank = squad, week.bank_after_tenths


def _assert_observed_coverage(result, captured, horizon, initial, settings):
    _assert_complete_resource_path(result, horizon.gameweeks, initial, settings)
    review = result.diagnostics["observed_window"]
    assert review["status"] in {"compared", "no_distinct_alternative"}
    if review["status"] == "compared":
        assert review["candidate_count"] >= 2
        assert len(captured) >= review["candidate_count"] * 2
        for candidate in review["candidates"]:
            assert len(candidate["branches"]) == 2
            assert {branch["id"] for branch in candidate["branches"]} == {"good", "bad"}
            assert (
                candidate["branches"][0]["first_action"] == candidate["branches"][1]["first_action"]
            )
            assert all(
                len(branch["weeks"]) == len(horizon.gameweeks) - 1
                for branch in candidate["branches"]
            )
    else:
        assert review["candidate_count"] == 1
        assert not captured
    for branch_horizon, branch_initial, plan in captured:
        assert branch_horizon.gameweeks == horizon.gameweeks
        assert branch_initial == initial
        _assert_complete_resource_path(plan, horizon.gameweeks, initial, settings)


@pytest.mark.parametrize("free_transfers", [0, 5])
def test_zero_bank_ft_edges_survive_complete_policies(
    known_optimum_players, small_config, captured_observed_branches, free_transfers
):
    horizon, initial, config = comparison_problem(known_optimum_players, small_config)
    initial = replace(initial, bank_tenths=0, free_transfers=free_transfers)
    settings = TransferPlanningConfig(acquisition_sell_on_fee=0.5)
    result = optimize_observed_window(
        horizon,
        initial,
        nodes_for(horizon),
        replace(config, solver_time_limit_seconds=120),
        settings,
    )
    _assert_observed_coverage(result, captured_observed_branches, horizon, initial, settings)
    for plan in [result, *(record[2] for record in captured_observed_branches)]:
        assert all(week.bank_before_tenths == week.bank_after_tenths == 0 for week in plan.weeks)
        assert plan.weeks[0].free_transfers_before == free_transfers


def test_renewed_free_hit_rights_preserve_full_branch_state(
    known_optimum_players, small_config, captured_observed_branches
):
    from squadopt.planning import ChipUseWindow

    horizon, initial, config = comparison_problem(known_optimum_players, small_config, 5)
    initial = replace(initial, bank_tenths=0, free_transfers=1)
    settings = TransferPlanningConfig(acquisition_sell_on_fee=0.5)
    rights = ChipAvailability(
        {"freehit": frozenset(range(1, 6))},
        {2: "freehit", 4: "freehit"},
        {"freehit": (ChipUseWindow(frozenset({1, 2})), ChipUseWindow(frozenset({3, 4, 5})))},
    )
    result = optimize_observed_window(
        horizon,
        initial,
        nodes_for(horizon),
        replace(config, solver_time_limit_seconds=120),
        settings,
        chips=rights,
    )
    _assert_observed_coverage(result, captured_observed_branches, horizon, initial, settings)
    assert result.diagnostics["observed_window"]["status"] == "compared"
    for plan in [result, *(record[2] for record in captured_observed_branches)]:
        assert dict(plan.chips_played) == {2: "freehit", 4: "freehit"}
        for chip_index in (1, 3):
            chip_week, following = plan.weeks[chip_index : chip_index + 2]
            assert following.bank_before_tenths == chip_week.bank_before_tenths
            assert chip_week.free_transfers_for_next_gameweek == chip_week.free_transfers_before
            assert following.free_transfers_before == chip_week.free_transfers_before
        assert all(week.bank_after_tenths == 0 for week in plan.weeks)


@pytest.mark.parametrize("free_transfers", [0, 5])
def test_binding_preferences_preserve_every_complete_policy(
    known_optimum_players, small_config, captured_observed_branches, free_transfers
):
    from squadopt.contracts.preferences import DecisionPreferences

    horizon, initial, config = comparison_problem(known_optimum_players, small_config)
    ids = {player: index + 1 for index, player in enumerate(horizon.table.player_id.unique())}
    nodes = tuple(
        replace(
            node,
            horizon=PlanningHorizon(
                node.horizon.table.assign(player_id=lambda table: table.player_id.map(ids))
            ),
        )
        for node in nodes_for(horizon)
    )
    horizon = PlanningHorizon(
        horizon.table.assign(player_id=lambda table: table.player_id.map(ids))
    )
    initial = replace(
        initial,
        bank_tenths=0,
        free_transfers=free_transfers,
        squad_player_ids=tuple(ids[p] for p in ("GK_A", "DEF_B", "MID_B", "FWD_B")),
    )
    preferences = DecisionPreferences(
        keep_players=(ids["DEF_B"],),
        avoid_players=(ids["MID_A"],),
        no_hits=True,
        save_chips=True,
    )
    # These valuable optional chips are available; saving them is an active restriction.
    rights = ChipAvailability({chip: frozenset(horizon.gameweeks) for chip in ("3xc", "bboost")})
    settings = TransferPlanningConfig(acquisition_sell_on_fee=0.5)
    result = optimize_observed_window(
        horizon,
        initial,
        nodes,
        replace(config, solver_time_limit_seconds=120),
        settings,
        chips=rights,
        preferences=preferences,
    )
    _assert_observed_coverage(result, captured_observed_branches, horizon, initial, settings)
    if free_transfers == 0:
        assert result.diagnostics["observed_window"]["status"] == "no_distinct_alternative"
        assert result.weeks[0].transfers_in.empty
    for plan in [result, *(record[2] for record in captured_observed_branches)]:
        assert not plan.chips_played
        for week in plan.weeks:
            assert ids["DEF_B"] in set(week.selected_squad.player_id)
            assert ids["MID_A"] not in set(week.selected_squad.player_id)
            assert week.paid_transfer_count == 0 and week.transfer_hit_points == 0
            assert week.chip is None


def test_hold_proposal_reserves_probe_budget_and_retains_certified_hold(
    known_optimum_players, small_config, monkeypatch
):
    from ortools.sat.python import cp_model

    import squadopt.planning.observed as observed
    import squadopt.planning.optimizer as optimizer

    horizon, initial, config = comparison_problem(known_optimum_players, small_config)
    config = replace(config, solver_deterministic_time_limit=20, solver_time_limit_seconds=120)
    original_plan = observed.optimize_transfer_plan
    original_solve = optimizer._solve
    original_work = optimizer._deterministic_time_used
    active = False
    held_calls, hold_solver_limits = [], []

    def stop_hold_primary(model, solver):
        if active:
            hold_solver_limits.append(
                (
                    float(solver.parameters.max_deterministic_time),
                    float(solver.parameters.max_time_in_seconds),
                )
            )
            if len(hold_solver_limits) == 2:
                return cp_model.UNKNOWN
        return original_solve(model, solver)

    def simulated_primary_work(solver, status):
        if active and status == cp_model.UNKNOWN:
            return float(solver.parameters.max_deterministic_time)
        return original_work(solver, status)

    def capture_held_proposal(*args, **kwargs):
        nonlocal active
        active = (
            kwargs.get("fixed_week_squads") is not None
            and kwargs.get("first_week_exclusion") is None
            and kwargs.get("incumbent_plan") is None
        )
        try:
            if active:
                assert kwargs["protect_hold"] is True
                assert args[2].solver_deterministic_time_limit == pytest.approx(1.0)
                assert args[2].solver_time_limit_seconds < config.solver_time_limit_seconds * 0.1
            result = original_plan(*args, **kwargs)
            if active:
                assert result.has_solution and result.solver_status is SolverStatus.FEASIBLE
                assert result.diagnostics["primary_search_status"] == "UNKNOWN"
                assert result.diagnostics["hold_protection"]["status"] == "OPTIMAL"
                assert result.diagnostics["hold_protection"]["selected"] is True
                assert len(result.weeks) == len(horizon.gameweeks)
                assert all(
                    week.transfers_in.empty and week.transfers_out.empty for week in result.weeks
                )
                assert all(
                    set(week.selected_squad.player_id) == set(initial.squad_player_ids)
                    for week in result.weeks
                )
                held_calls.append(result)
            return result
        finally:
            active = False

    monkeypatch.setattr(optimizer, "_solve", stop_hold_primary)
    monkeypatch.setattr(optimizer, "_deterministic_time_used", simulated_primary_work)
    monkeypatch.setattr(observed, "optimize_transfer_plan", capture_held_proposal)
    result = observed.optimize_observed_window(
        horizon,
        initial,
        nodes_for(horizon),
        config,
        TransferPlanningConfig(),
    )
    review = result.diagnostics["observed_window"]
    assert review["status"] == "compared" and review["candidate_count"] >= 2
    assert review["hold_feasible"] is True
    assert len(held_calls) == 1 and len(hold_solver_limits) == 2
    assert hold_solver_limits[0][0] == 1.0
    assert sum(limit for limit, _ in hold_solver_limits) <= 2.0
    assert sum(wall for _, wall in hold_solver_limits) <= config.solver_time_limit_seconds * 0.1
    held = held_calls[0]
    probe_work = held.diagnostics["hold_protection"]["deterministic_time"]
    assert probe_work > 0
    row = next(row for row in review["ledger"] if row["phase"] == "hold_proposal")
    assert row["cap"] == pytest.approx(2.0)
    assert row["actual"] == pytest.approx(held.diagnostics["deterministic_time_used"] + probe_work)
    assert row["actual"] <= row["cap"]
    assert review["actual_total"] == pytest.approx(sum(row["actual"] for row in review["ledger"]))
    assert review["allocated_total"] <= 20.000001
    assert any(
        candidate["first_in"] == candidate["first_out"] == [] for candidate in review["candidates"]
    )


@pytest.mark.parametrize("probe_status", ["FEASIBLE", "UNKNOWN"])
def test_clock_truncated_hold_probe_is_rejected(
    known_optimum_players, small_config, monkeypatch, probe_status
):
    import squadopt.planning.observed as module

    horizon, initial, config = comparison_problem(known_optimum_players, small_config)
    config = replace(config, solver_deterministic_time_limit=20, solver_time_limit_seconds=120)
    original = module.optimize_transfer_plan
    injected = []

    def clock_truncated_probe(*args, **kwargs):
        result = original(*args, **kwargs)
        if kwargs.get("protect_hold"):
            assert result.has_solution
            assert result.diagnostics["hold_protection"]["status"] == "OPTIMAL"
            injected.append(result)
            return replace(
                result,
                diagnostics={
                    **result.diagnostics,
                    "hold_protection": {
                        **result.diagnostics["hold_protection"],
                        "status": probe_status,
                        "deterministic_time": 0.0,
                    },
                },
            )
        return result

    monkeypatch.setattr(module, "optimize_transfer_plan", clock_truncated_probe)
    with pytest.raises(SolverExecutionError, match=r"hold probe.*wall-clock"):
        module.optimize_observed_window(
            horizon,
            initial,
            nodes_for(horizon),
            config,
            TransferPlanningConfig(),
        )
    assert len(injected) == 1
