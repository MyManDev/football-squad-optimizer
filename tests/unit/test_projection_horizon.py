"""Contract tests for the multi-gameweek projection handoff.

The prediction-side builder does not exist yet; these tests pin down what the planner
will accept. Blank and double gameweeks are the point: a handoff that cannot represent
them explicitly would silently plan transfers around fixtures that do not exist.
"""

import pandas as pd
import pytest

from squadopt.optimization import OptimizationConfig, SolverStatus
from squadopt.planning import (
    InitialSquadState,
    ProjectionHorizon,
    TransferPlanningValidationError,
    optimize_transfer_plan,
    to_planning_horizon,
)

GAMEWEEKS = (1, 2)


def _projection_table(
    players: pd.DataFrame,
    gameweeks: tuple[int, ...] = GAMEWEEKS,
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
                    "price_tenths": row["price_tenths"],
                    "expected_points": row["expected_points"],
                    "fixture_count": 1,
                    "home_fixture_count": gameweek % 2,
                }
            )
    return pd.DataFrame.from_records(records)


def _horizon(table: pd.DataFrame) -> ProjectionHorizon:
    return ProjectionHorizon(
        table,
        season="2026-27",
        source_snapshot_id="fpl-live@rehearsal",
        model_name="control-model",
        model_version="1.0.0",
        feature_contract_version="form_window_v1",
        post_processing_contract_version="captured_availability_rule_v1",
    )


# --- accepting a valid handoff ----------------------------------------------


def test_a_conforming_horizon_is_accepted_with_a_stable_fingerprint(
    known_optimum_players: pd.DataFrame,
) -> None:
    table = _projection_table(known_optimum_players)

    first = _horizon(table)
    shuffled = _horizon(table.sample(frac=1.0, random_state=7).reset_index(drop=True))

    assert first.target_gameweeks == GAMEWEEKS
    assert len(first.horizon_fingerprint) == 64
    assert first.horizon_fingerprint == shuffled.horizon_fingerprint


def test_the_fingerprint_binds_provenance_not_only_rows(
    known_optimum_players: pd.DataFrame,
) -> None:
    """Two identical tables from different models are different evidence."""

    table = _projection_table(known_optimum_players)
    first = _horizon(table)
    other = ProjectionHorizon(
        table,
        season="2026-27",
        source_snapshot_id="fpl-live@rehearsal",
        model_name="candidate-model",
        model_version="1.0.0",
        feature_contract_version="form_window_v1",
        post_processing_contract_version="captured_availability_rule_v1",
    )

    assert first.horizon_fingerprint != other.horizon_fingerprint


def test_a_double_gameweek_is_representable(known_optimum_players: pd.DataFrame) -> None:
    table = _projection_table(known_optimum_players)
    doubled = table["gameweek"] == 2
    table.loc[doubled, "fixture_count"] = 2
    table.loc[doubled, "home_fixture_count"] = 1

    horizon = _horizon(table)

    week = horizon.table.loc[horizon.table["gameweek"] == 2]
    assert (week["fixture_count"] == 2).all()


def test_a_blank_gameweek_row_with_zero_points_is_representable(
    known_optimum_players: pd.DataFrame,
) -> None:
    table = _projection_table(known_optimum_players)
    blanked = (table["gameweek"] == 2) & (table["player_id"] == "GK_A")
    table.loc[blanked, ["fixture_count", "home_fixture_count"]] = 0
    table.loc[blanked, "expected_points"] = 0.0

    horizon = _horizon(table)

    assert (horizon.table.loc[blanked, "expected_points"] == 0.0).all()


# --- refusing a malformed handoff -------------------------------------------


def test_a_blank_row_projecting_points_is_refused(
    known_optimum_players: pd.DataFrame,
) -> None:
    """A player cannot score in a gameweek with no fixture."""

    table = _projection_table(known_optimum_players)
    blanked = (table["gameweek"] == 2) & (table["player_id"] == "GK_A")
    table.loc[blanked, ["fixture_count", "home_fixture_count"]] = 0

    with pytest.raises(TransferPlanningValidationError, match="exactly zero points"):
        _horizon(table)


def test_a_missing_gameweek_is_not_a_blank(known_optimum_players: pd.DataFrame) -> None:
    with pytest.raises(TransferPlanningValidationError, match="consecutive"):
        _horizon(_projection_table(known_optimum_players, (1, 3)))


def test_more_home_fixtures_than_fixtures_is_refused(
    known_optimum_players: pd.DataFrame,
) -> None:
    table = _projection_table(known_optimum_players)
    table.loc[table.index[:1], "home_fixture_count"] = 5

    with pytest.raises(TransferPlanningValidationError, match="may not exceed"):
        _horizon(table)


def test_a_changing_player_universe_is_refused(
    known_optimum_players: pd.DataFrame,
) -> None:
    table = _projection_table(known_optimum_players)
    table = table.loc[~((table["gameweek"] == 2) & (table["player_id"] == "MID_B"))]

    with pytest.raises(TransferPlanningValidationError, match="same player universe"):
        _horizon(table)


def test_duplicate_gameweek_player_rows_are_refused(
    known_optimum_players: pd.DataFrame,
) -> None:
    table = _projection_table(known_optimum_players)

    with pytest.raises(TransferPlanningValidationError, match=r"\(gameweek, player_id\)"):
        _horizon(pd.concat([table, table.iloc[[0]]], ignore_index=True))


def test_negative_expected_points_are_refused(
    known_optimum_players: pd.DataFrame,
) -> None:
    table = _projection_table(known_optimum_players)
    table.loc[table.index[:1], "expected_points"] = -1.0

    with pytest.raises(TransferPlanningValidationError, match="non-negative"):
        _horizon(table)


def test_missing_provenance_is_refused(known_optimum_players: pd.DataFrame) -> None:
    table = _projection_table(known_optimum_players)

    with pytest.raises(TransferPlanningValidationError, match="model_name"):
        ProjectionHorizon(
            table,
            season="2026-27",
            source_snapshot_id="fpl-live@rehearsal",
            model_name="  ",
            model_version="1.0.0",
            feature_contract_version="form_window_v1",
            post_processing_contract_version="captured_availability_rule_v1",
        )


def test_missing_columns_are_refused(known_optimum_players: pd.DataFrame) -> None:
    table = _projection_table(known_optimum_players).drop(columns="fixture_count")

    with pytest.raises(TransferPlanningValidationError, match="missing required columns"):
        _horizon(table)


# --- feeding the planner -----------------------------------------------------


def test_the_conversion_feeds_the_transfer_planner_end_to_end(
    known_optimum_players: pd.DataFrame,
    small_config: OptimizationConfig,
) -> None:
    horizon = _horizon(_projection_table(known_optimum_players))

    planning_horizon = to_planning_horizon(horizon)
    result = optimize_transfer_plan(
        planning_horizon,
        InitialSquadState(("GK_A", "DEF_A", "MID_A", "FWD_A")),
        small_config,
    )

    assert result.solver_status is SolverStatus.OPTIMAL
    assert len(result.weeks) == len(GAMEWEEKS)
    buy = planning_horizon.table["buy_price_tenths"]
    sell = planning_horizon.table["sell_price_tenths"]
    assert buy.equals(sell)


def test_the_conversion_refuses_an_unvalidated_table(
    known_optimum_players: pd.DataFrame,
) -> None:
    with pytest.raises(TransferPlanningValidationError, match="ProjectionHorizon"):
        to_planning_horizon(_projection_table(known_optimum_players))  # type: ignore[arg-type]
