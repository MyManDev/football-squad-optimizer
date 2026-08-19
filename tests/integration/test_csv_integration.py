"""Integration tests for canonical prediction CSV input."""

from pathlib import Path

import pandas as pd
import pytest
from pandas.api.types import is_integer_dtype

from squadopt import (
    InvalidPlayerDataError,
    OptimizationConfig,
    SolverStatus,
    optimize_squad_from_csv,
)


def _write_predictions(path: Path, players: pd.DataFrame) -> None:
    players.to_csv(path, index=False, encoding="utf-8")


def test_optimizes_canonical_predictions_csv(
    tmp_path: Path,
    known_optimum_players: pd.DataFrame,
    small_config: OptimizationConfig,
) -> None:
    predictions_path = tmp_path / "predictions.csv"
    players = known_optimum_players.assign(source_note="synthetic-csv")
    _write_predictions(predictions_path, players)

    result = optimize_squad_from_csv(predictions_path, small_config)

    assert result.solver_status is SolverStatus.OPTIMAL
    assert set(result.selected_squad["player_id"]) == {
        "GK_A",
        "DEF_A",
        "MID_A",
        "FWD_A",
    }
    assert set(result.starting_xi["player_id"]) == {"GK_A", "MID_A", "FWD_A"}
    assert len(result.bench) == 1
    assert result.captain is not None
    assert result.captain["player_id"] == "MID_A"
    assert result.total_cost_tenths == 200
    assert is_integer_dtype(result.selected_squad["price_tenths"].dtype)
    assert set(result.selected_squad["source_note"]) == {"synthetic-csv"}


def test_csv_input_uses_existing_schema_validation(
    tmp_path: Path,
    known_optimum_players: pd.DataFrame,
    small_config: OptimizationConfig,
) -> None:
    predictions_path = tmp_path / "predictions.csv"
    invalid_players = known_optimum_players.drop(columns="expected_points")
    _write_predictions(predictions_path, invalid_players)

    with pytest.raises(InvalidPlayerDataError, match="expected_points"):
        optimize_squad_from_csv(predictions_path, small_config)


def test_csv_does_not_convert_decimal_prices_to_tenths(
    tmp_path: Path,
    known_optimum_players: pd.DataFrame,
    small_config: OptimizationConfig,
) -> None:
    predictions_path = tmp_path / "predictions.csv"
    invalid_players = known_optimum_players.copy(deep=True)
    invalid_players["price_tenths"] = invalid_players["price_tenths"].astype(float)
    invalid_players.loc[0, "price_tenths"] = 5.5
    _write_predictions(predictions_path, invalid_players)

    with pytest.raises(InvalidPlayerDataError, match="price_tenths"):
        optimize_squad_from_csv(predictions_path, small_config)


def test_csv_preserves_lexical_identifiers(
    tmp_path: Path,
    known_optimum_players: pd.DataFrame,
    small_config: OptimizationConfig,
) -> None:
    predictions_path = tmp_path / "predictions.csv"
    players = known_optimum_players.copy(deep=True)
    players["player_id"] = [f"{value:03d}" for value in range(7, 15)]
    players["team_id"] = [f"{value:02d}" for value in range(1, 9)]
    _write_predictions(predictions_path, players)

    result = optimize_squad_from_csv(predictions_path, small_config)

    assert result.has_solution
    assert set(result.selected_squad["player_id"]) == {"007", "009", "011", "013"}
    assert set(result.selected_squad["team_id"]) == {"01", "03", "05", "07"}


def test_csv_missing_price_has_actionable_domain_error(
    tmp_path: Path,
    known_optimum_players: pd.DataFrame,
    small_config: OptimizationConfig,
) -> None:
    predictions_path = tmp_path / "predictions.csv"
    invalid_players = known_optimum_players.copy(deep=True)
    invalid_players["price_tenths"] = invalid_players["price_tenths"].astype(object)
    invalid_players.loc[0, "price_tenths"] = None
    _write_predictions(predictions_path, invalid_players)

    with pytest.raises(InvalidPlayerDataError, match=r"missing values.*price_tenths"):
        optimize_squad_from_csv(predictions_path, small_config)


def test_csv_malformed_price_has_actionable_domain_error(
    tmp_path: Path,
    known_optimum_players: pd.DataFrame,
    small_config: OptimizationConfig,
) -> None:
    predictions_path = tmp_path / "predictions.csv"
    invalid_players = known_optimum_players.copy(deep=True)
    invalid_players["price_tenths"] = invalid_players["price_tenths"].astype(object)
    invalid_players.loc[0, "price_tenths"] = "not-a-price"
    _write_predictions(predictions_path, invalid_players)

    with pytest.raises(InvalidPlayerDataError, match="price_tenths CSV values must be numeric"):
        optimize_squad_from_csv(predictions_path, small_config)
