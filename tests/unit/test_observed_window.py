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
    horizon, initial, config = problem(known_optimum_players, small_config, window)
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

    horizon, initial, config = problem(known_optimum_players, small_config)
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

    horizon, initial, config = problem(known_optimum_players, small_config)
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
    horizon, initial, config = problem(known_optimum_players, small_config)
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
