"""Synthetic acceptance tests for deterministic multi-gameweek transfer planning."""

from collections import Counter
from dataclasses import replace

import pandas as pd
import pytest
from ortools.sat.python import cp_model
from pandas.testing import assert_frame_equal

import squadopt.planning.optimizer as planning_optimizer
from squadopt.optimization import OptimizationConfig, SolverStatus
from squadopt.planning import (
    InitialSquadState,
    PlanningHorizon,
    TransferPlanningConfig,
    TransferPlanningConfigurationError,
    TransferPlanningValidationError,
    optimize_transfer_plan,
)


def _horizon_table(
    players: pd.DataFrame,
    gameweeks: tuple[int, ...] = (1, 2),
) -> pd.DataFrame:
    records: list[dict[str, object]] = []
    for gameweek in gameweeks:
        for row in players.to_dict("records"):
            records.append(
                {
                    "gameweek": gameweek,
                    "player_id": row["player_id"],
                    "name": row["name"],
                    "team_id": row["team_id"],
                    "position": row["position"],
                    "buy_price_tenths": row["price_tenths"],
                    "sell_price_tenths": row["price_tenths"],
                    "expected_points": row["expected_points"],
                }
            )
    return pd.DataFrame.from_records(records)


def _initial(*player_ids: str, bank_tenths: int = 0, free_transfers: int = 1) -> InitialSquadState:
    return InitialSquadState(
        squad_player_ids=player_ids,
        bank_tenths=bank_tenths,
        free_transfers=free_transfers,
    )


OPTIMAL_INITIAL = _initial("GK_A", "DEF_A", "MID_A", "FWD_A")


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"max_free_transfers": 0}, "at least 1"),
        ({"free_transfer_accrual": -1}, "at least 0"),
        (
            {"max_free_transfers": 2, "free_transfer_accrual": 3},
            "may not exceed",
        ),
        ({"transfer_hit_cost_points": -1.0}, "at least 0"),
        ({"horizon_discount_factor": 0.0}, "strictly positive"),
        ({"horizon_discount_factor": 1.1}, "at most 1"),
        ({"objective_weight_scale": 0}, "at least 1"),
        ({"contract_version": "future"}, "contract_version"),
    ],
)
def test_invalid_transfer_config_is_rejected(
    change: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(TransferPlanningConfigurationError, match=message):
        TransferPlanningConfig(**change)  # type: ignore[arg-type]


def test_transfer_config_fingerprint_is_stable_and_complete() -> None:
    baseline = TransferPlanningConfig()

    assert baseline.configuration_fingerprint == TransferPlanningConfig().configuration_fingerprint
    assert (
        baseline.configuration_fingerprint
        != replace(
            baseline,
            horizon_discount_factor=0.99,
        ).configuration_fingerprint
    )


def test_invalid_initial_state_is_rejected() -> None:
    with pytest.raises(TransferPlanningValidationError, match="duplicates"):
        InitialSquadState(("A", "A"))
    with pytest.raises(TransferPlanningValidationError, match="bank_tenths"):
        InitialSquadState(("A",), bank_tenths=-1)


def test_horizon_requires_complete_consecutive_unique_rows(
    known_optimum_players: pd.DataFrame,
) -> None:
    table = _horizon_table(known_optimum_players)

    with pytest.raises(TransferPlanningValidationError, match="missing required columns"):
        PlanningHorizon(table.drop(columns="sell_price_tenths"))
    with pytest.raises(TransferPlanningValidationError, match="must be consecutive"):
        PlanningHorizon(_horizon_table(known_optimum_players, (1, 3)))
    with pytest.raises(TransferPlanningValidationError, match=r"\(gameweek, player_id\)"):
        PlanningHorizon(pd.concat([table, table.iloc[[0]]], ignore_index=True))


def test_horizon_requires_the_same_player_universe_each_week(
    known_optimum_players: pd.DataFrame,
) -> None:
    table = _horizon_table(known_optimum_players)
    table = table.loc[~((table["gameweek"] == 2) & (table["player_id"] == "MID_B"))]

    with pytest.raises(TransferPlanningValidationError, match="same player universe"):
        PlanningHorizon(table)


def test_horizon_copies_input_and_detects_later_internal_mutation(
    known_optimum_players: pd.DataFrame,
) -> None:
    table = _horizon_table(known_optimum_players)
    before = table.copy(deep=True)
    horizon = PlanningHorizon(table)

    table.loc[:, "expected_points"] = 999.0
    assert_frame_equal(horizon.table, before)
    horizon.table.loc[horizon.table.index[0], "expected_points"] = 999.0

    with pytest.raises(TransferPlanningValidationError, match="horizon_fingerprint"):
        horizon.validated_copy()


def test_optimal_initial_squad_requires_no_transfer(
    known_optimum_players: pd.DataFrame,
    small_config: OptimizationConfig,
) -> None:
    result = optimize_transfer_plan(
        PlanningHorizon(_horizon_table(known_optimum_players)),
        OPTIMAL_INITIAL,
        small_config,
    )

    assert result.solver_status is SolverStatus.OPTIMAL
    assert len(result.weeks) == 2
    assert [week.transfer_count for week in result.weeks] == [0, 0]
    assert [week.paid_transfer_count for week in result.weeks] == [0, 0]
    assert [week.bank_after_tenths for week in result.weeks] == [0, 0]
    assert all(len(week.selected_squad) == small_config.squad_size for week in result.weeks)
    assert all(len(week.starting_xi) == small_config.starting_size for week in result.weeks)
    assert all(week.captain["player_id"] == "MID_A" for week in result.weeks)


def test_one_free_transfer_replaces_a_known_weak_player(
    known_optimum_players: pd.DataFrame,
    small_config: OptimizationConfig,
) -> None:
    result = optimize_transfer_plan(
        PlanningHorizon(_horizon_table(known_optimum_players, (1,))),
        _initial("GK_A", "DEF_B", "MID_A", "FWD_A"),
        small_config,
    )

    week = result.weeks[0]
    assert week.transfers_in["player_id"].tolist() == ["DEF_A"]
    assert week.transfers_out["player_id"].tolist() == ["DEF_B"]
    assert week.transfer_count == 1
    assert week.paid_transfer_count == 0
    assert week.transfer_hit_points == 0.0
    assert week.bank_after_tenths == 0


def test_every_week_satisfies_squad_lineup_and_state_invariants(
    known_optimum_players: pd.DataFrame,
    small_config: OptimizationConfig,
) -> None:
    horizon = PlanningHorizon(_horizon_table(known_optimum_players))
    initial = _initial("GK_A", "DEF_B", "MID_A", "FWD_A")

    result = optimize_transfer_plan(horizon, initial, small_config)

    previous_squad = set(initial.squad_player_ids)
    for week in result.weeks:
        squad_ids = set(week.selected_squad["player_id"])
        starter_ids = set(week.starting_xi["player_id"])
        bench_ids = set(week.bench["player_id"])
        incoming_ids = set(week.transfers_in["player_id"])
        outgoing_ids = set(week.transfers_out["player_id"])

        assert len(squad_ids) == small_config.squad_size
        assert Counter(week.selected_squad["position"]) == dict(
            small_config.squad_position_limits
        )
        assert week.selected_squad["buy_price_tenths"].sum() <= small_config.budget_tenths
        assert week.selected_squad.groupby("team_id").size().max() <= (
            small_config.max_players_per_team
        )
        assert len(starter_ids) == small_config.starting_size
        assert starter_ids <= squad_ids
        assert bench_ids == squad_ids - starter_ids
        assert len(week.starting_xi.loc[week.starting_xi["position"] == "GK"]) == 1
        starter_positions = Counter(week.starting_xi["position"])
        for position in small_config.starting_position_min:
            assert small_config.starting_position_min[position] <= starter_positions[position]
            assert starter_positions[position] <= small_config.starting_position_max[position]
        assert week.captain["player_id"] in starter_ids

        assert incoming_ids.isdisjoint(outgoing_ids)
        assert squad_ids == (previous_squad - outgoing_ids) | incoming_ids
        assert len(incoming_ids) == len(outgoing_ids) == week.transfer_count
        assert week.bank_after_tenths == (
            week.bank_before_tenths
            + int(week.transfers_out["sell_price_tenths"].sum())
            - int(week.transfers_in["buy_price_tenths"].sum())
        )
        previous_squad = squad_ids


def test_bank_accounting_blocks_an_unaffordable_transfer(
    known_optimum_players: pd.DataFrame,
    small_config: OptimizationConfig,
) -> None:
    table = _horizon_table(known_optimum_players, (1,))
    table.loc[table["player_id"] == "DEF_A", ["buy_price_tenths", "sell_price_tenths"]] = 60
    horizon = PlanningHorizon(table)
    state = _initial("GK_A", "DEF_B", "MID_A", "FWD_A")

    blocked = optimize_transfer_plan(horizon, state, small_config)
    affordable = optimize_transfer_plan(horizon, replace(state, bank_tenths=10), small_config)

    assert blocked.weeks[0].transfer_count == 0
    assert affordable.weeks[0].transfers_in["player_id"].tolist() == ["DEF_A"]
    assert affordable.weeks[0].bank_after_tenths == 0


def test_a_second_same_week_transfer_pays_the_declared_hit(
    known_optimum_players: pd.DataFrame,
    small_config: OptimizationConfig,
) -> None:
    table = _horizon_table(known_optimum_players, (1,))
    table.loc[table["player_id"].isin(["GK_A", "MID_A"]), "expected_points"] = 10.0
    table.loc[table["player_id"].isin(["GK_B", "MID_B"]), "expected_points"] = 1.0

    result = optimize_transfer_plan(
        PlanningHorizon(table),
        _initial("GK_B", "DEF_A", "MID_B", "FWD_A"),
        small_config,
    )

    week = result.weeks[0]
    assert set(week.transfers_in["player_id"]) == {"GK_A", "MID_A"}
    assert set(week.transfers_out["player_id"]) == {"GK_B", "MID_B"}
    assert week.transfer_count == 2
    assert week.paid_transfer_count == 1
    assert week.transfer_hit_points == 4.0
    assert result.total_transfer_hit_points == 4.0


def test_unused_free_transfers_carry_to_the_configured_cap(
    known_optimum_players: pd.DataFrame,
    small_config: OptimizationConfig,
) -> None:
    result = optimize_transfer_plan(
        PlanningHorizon(_horizon_table(known_optimum_players, (1, 2, 3, 4, 5, 6))),
        OPTIMAL_INITIAL,
        small_config,
        TransferPlanningConfig(max_free_transfers=3),
    )

    assert [week.free_transfers_before for week in result.weeks] == [1, 2, 3, 3, 3, 3]
    assert [week.free_transfers_for_next_gameweek for week in result.weeks] == [2, 3, 3, 3, 3, 3]


def test_horizon_can_buy_early_before_a_future_price_becomes_unaffordable(
    known_optimum_players: pd.DataFrame,
    small_config: OptimizationConfig,
) -> None:
    table = _horizon_table(known_optimum_players)
    mid_a = table["player_id"] == "MID_A"
    mid_b = table["player_id"] == "MID_B"
    table.loc[mid_a & (table["gameweek"] == 1), "expected_points"] = 0.0
    table.loc[mid_a & (table["gameweek"] == 2), "expected_points"] = 20.0
    table.loc[mid_b, "expected_points"] = 5.0
    table.loc[mid_a & (table["gameweek"] == 1), ["buy_price_tenths", "sell_price_tenths"]] = 60
    table.loc[mid_a & (table["gameweek"] == 2), ["buy_price_tenths", "sell_price_tenths"]] = 100

    result = optimize_transfer_plan(
        PlanningHorizon(table),
        _initial("GK_A", "DEF_A", "MID_B", "FWD_A", bank_tenths=10),
        small_config,
    )

    assert result.weeks[0].transfers_in["player_id"].tolist() == ["MID_A"]
    assert result.weeks[0].bank_after_tenths == 0
    assert result.weeks[1].transfer_count == 0


def test_valid_but_unfundable_horizon_is_structured_infeasible(
    known_optimum_players: pd.DataFrame,
    small_config: OptimizationConfig,
) -> None:
    table = _horizon_table(known_optimum_players)
    table.loc[:, ["buy_price_tenths", "sell_price_tenths"]] = 0
    second_week = table["gameweek"] == 2
    table.loc[second_week & (table["player_id"] == "GK_A"), "position"] = "DEF"
    table.loc[
        table["player_id"] == "GK_B",
        ["buy_price_tenths", "sell_price_tenths"],
    ] = [1_000, 0]

    result = optimize_transfer_plan(
        PlanningHorizon(table),
        OPTIMAL_INITIAL,
        small_config,
    )

    assert result.solver_status is SolverStatus.INFEASIBLE
    assert result.weeks == ()
    assert result.objective_value is None


def test_result_is_deterministic_and_inputs_are_not_mutated(
    known_optimum_players: pd.DataFrame,
    small_config: OptimizationConfig,
) -> None:
    horizon = PlanningHorizon(_horizon_table(known_optimum_players))
    before = horizon.table.copy(deep=True)

    first = optimize_transfer_plan(horizon, OPTIMAL_INITIAL, small_config)
    second = optimize_transfer_plan(horizon, OPTIMAL_INITIAL, small_config)

    assert_frame_equal(horizon.table, before)
    assert [week.selected_squad["player_id"].tolist() for week in first.weeks] == [
        week.selected_squad["player_id"].tolist() for week in second.weeks
    ]
    assert first.objective_value == second.objective_value


def test_unknown_solver_status_is_structured(
    known_optimum_players: pd.DataFrame,
    small_config: OptimizationConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    horizon = PlanningHorizon(_horizon_table(known_optimum_players, (1,)))
    monkeypatch.setattr(planning_optimizer, "_solve", lambda model, solver: cp_model.UNKNOWN)

    result = optimize_transfer_plan(horizon, OPTIMAL_INITIAL, small_config)

    assert result.solver_status is SolverStatus.UNKNOWN
    assert result.weeks == ()
    assert result.objective_value is None
