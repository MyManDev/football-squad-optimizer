"""Tests for canonical player validation."""

import math

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

from squadopt import (
    InsufficientPlayerPoolError,
    InvalidPlayerDataError,
    OptimizationConfig,
)
from squadopt.optimization.validation import validate_players


def test_validation_returns_an_independent_copy(baseline_players: pd.DataFrame) -> None:
    original = baseline_players.copy(deep=True)

    validated = validate_players(baseline_players, OptimizationConfig())
    validated.loc[0, "name"] = "Changed"

    assert_frame_equal(baseline_players, original)
    assert baseline_players.loc[0, "name"] != "Changed"


def test_rejects_duplicate_player_id(baseline_players: pd.DataFrame) -> None:
    baseline_players.loc[1, "player_id"] = baseline_players.loc[0, "player_id"]

    with pytest.raises(InvalidPlayerDataError, match="Duplicate player_id"):
        validate_players(baseline_players, OptimizationConfig())


def test_rejects_missing_required_columns(baseline_players: pd.DataFrame) -> None:
    players = baseline_players.drop(columns=["price_tenths", "expected_points"])

    with pytest.raises(InvalidPlayerDataError) as error:
        validate_players(players, OptimizationConfig())

    assert "price_tenths" in str(error.value)
    assert "expected_points" in str(error.value)


def test_rejects_invalid_position(baseline_players: pd.DataFrame) -> None:
    baseline_players.loc[0, "position"] = "WING"

    with pytest.raises(InvalidPlayerDataError, match="Invalid positions"):
        validate_players(baseline_players, OptimizationConfig())


@pytest.mark.parametrize("column", ["player_id", "name", "team_id"])
def test_rejects_missing_identity_values(
    baseline_players: pd.DataFrame,
    column: str,
) -> None:
    baseline_players.loc[0, column] = None

    with pytest.raises(InvalidPlayerDataError, match="missing values"):
        validate_players(baseline_players, OptimizationConfig())


def test_rejects_mixed_identifier_types(baseline_players: pd.DataFrame) -> None:
    baseline_players["player_id"] = baseline_players["player_id"].astype(object)
    baseline_players.loc[0, "player_id"] = "1"

    with pytest.raises(InvalidPlayerDataError, match="consistent ID type"):
        validate_players(baseline_players, OptimizationConfig())


@pytest.mark.parametrize("invalid_price", [55.0, -1, True])
def test_rejects_noncanonical_prices(
    baseline_players: pd.DataFrame,
    invalid_price: object,
) -> None:
    baseline_players["price_tenths"] = baseline_players["price_tenths"].astype(object)
    baseline_players.loc[0, "price_tenths"] = invalid_price

    with pytest.raises(InvalidPlayerDataError, match="non-negative integers"):
        validate_players(baseline_players, OptimizationConfig())


@pytest.mark.parametrize("invalid_points", [-0.1, math.nan, math.inf, True])
def test_rejects_invalid_expected_points(
    baseline_players: pd.DataFrame,
    invalid_points: object,
) -> None:
    baseline_players["expected_points"] = baseline_players["expected_points"].astype(object)
    baseline_players.loc[0, "expected_points"] = invalid_points

    with pytest.raises(InvalidPlayerDataError):
        validate_players(baseline_players, OptimizationConfig())


def test_rejects_insufficient_total_pool(baseline_players: pd.DataFrame) -> None:
    with pytest.raises(InsufficientPlayerPoolError, match="Insufficient total players"):
        validate_players(baseline_players.head(14), OptimizationConfig())


def test_rejects_insufficient_position_pool(baseline_players: pd.DataFrame) -> None:
    players = baseline_players.loc[baseline_players["position"] != "GK"].copy()
    players = pd.concat(
        [players, players.head(2).assign(player_id=[1001, 1002])], ignore_index=True
    )

    with pytest.raises(InsufficientPlayerPoolError, match="Insufficient GK players"):
        validate_players(players, OptimizationConfig())
