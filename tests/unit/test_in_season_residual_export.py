"""Tests for the in-season blend's residual export.

The export exists so a live spread can be calibrated on the model that is deciding rather
than on a different one. Two things would defeat that quietly and both are checked here: the
manifest claiming the wrong identity or regime, and opening-gameweek rows reaching a history
that cannot describe them.

The contract checks are exercised against hand-built tables. Building the real one reads the
whole archive, which belongs in the script rather than in a unit suite.
"""

import pandas as pd
import pytest
from scripts import export_in_season_residuals as export

from squadopt.backtest.splits import BacktestConfigurationError
from squadopt.prediction.in_season import (
    IN_SEASON_FEATURE_CONTRACT_VERSION,
    IN_SEASON_MODEL_VERSION,
)


def _table(
    *,
    gameweeks: tuple[int, ...] = (2, 3),
    players: tuple[int, ...] = (1001, 1002),
    predicted: float = 3.0,
    realized: float = 4.0,
) -> pd.DataFrame:
    rows = [
        {
            "fold_id": f"2021-22-gw{gameweek:02d}",
            "season": "2021-22",
            "gameweek": gameweek,
            "player_id": player,
            "team_id": "Club 1",
            "position": "MID",
            "predicted_points": predicted,
            "realized_points": realized,
            "residual": realized - predicted,
        }
        for gameweek in gameweeks
        for player in players
    ]
    return pd.DataFrame(rows, columns=list(export.RESIDUAL_COLUMNS))


# --- the identity is the deciding model's, not a neighbouring one -------------


def test_the_manifest_claims_the_model_that_will_decide() -> None:
    """Calibrating on another model's residuals is the mistake #45 exists to prevent."""

    record = export.manifest(
        _table(),
        table_sha256="abc",
        created_at_utc="2026-08-22T17:00:00+00:00",
        repository_commit="deadbeef",
    )

    assert record["model_version"] == IN_SEASON_MODEL_VERSION
    assert record["feature_contract_version"] == IN_SEASON_FEATURE_CONTRACT_VERSION
    assert record["model_name"] == export.CONTROL_MODEL_NAME


def test_the_regime_label_differs_from_the_controls() -> None:
    """The pairing rule refuses two exports claiming the same regime, and these are two."""

    assert export.IN_SEASON_CANDIDATE_LABEL != "control"
    assert "in_season" in export.IN_SEASON_CANDIDATE_LABEL


def test_the_manifest_carries_the_contract_and_the_holdout_claim() -> None:
    record = export.manifest(
        _table(),
        table_sha256="abc",
        created_at_utc="2026-08-22T17:00:00+00:00",
        repository_commit="deadbeef",
    )

    assert record["contract_version"] == export.RESIDUAL_EXPORT_CONTRACT_VERSION
    assert record["locked_holdout_accessed"] is False
    assert record["opening_gameweeks_included"] is False
    assert record["fold_count"] == 2
    assert record["row_count"] == 4


# --- opening gameweeks must not reach a history that cannot describe them -----


def test_an_opening_gameweek_row_stops_the_export() -> None:
    """Mid-season residuals do not describe a carry-over-and-price-prior projection.

    Letting one through would produce a confident-looking opening-gameweek interval with
    nothing behind it, which is the failure the issue names explicitly.
    """

    with pytest.raises(BacktestConfigurationError, match="Opening gameweeks are present"):
        export._check(_table(gameweeks=(1, 2)))


def test_a_table_of_later_gameweeks_passes() -> None:
    export._check(_table(gameweeks=(2, 38)))


# --- the contract's arithmetic ------------------------------------------------


def test_a_residual_that_is_not_realized_minus_predicted_is_refused() -> None:
    table = _table()
    table.loc[0, "residual"] = 99.0

    with pytest.raises(BacktestConfigurationError, match="realized minus predicted"):
        export._check(table)


def test_a_repeated_fold_and_player_pair_is_refused() -> None:
    """One row each is the contract; two would double a player's weight in the history."""

    table = pd.concat([_table(gameweeks=(2,)), _table(gameweeks=(2,))], ignore_index=True)

    with pytest.raises(BacktestConfigurationError, match="repeat a "):
        export._check(table)


def test_a_negative_prediction_is_refused() -> None:
    table = _table(predicted=-1.0)

    with pytest.raises(BacktestConfigurationError, match="non-negative"):
        export._check(table)


def test_a_missing_prediction_is_refused() -> None:
    table = _table()
    table.loc[0, "predicted_points"] = None

    with pytest.raises(BacktestConfigurationError, match="predicted point is missing"):
        export._check(table)


def test_an_empty_table_is_refused() -> None:
    with pytest.raises(BacktestConfigurationError, match="empty"):
        export._check(_table(gameweeks=(), players=()))


def test_a_negative_realized_score_is_allowed() -> None:
    """Players do lose points, so the contract permits it where it forbids a negative
    prediction."""

    export._check(_table(predicted=1.0, realized=-2.0))


# --- the column order is the contract's --------------------------------------


def test_the_column_order_matches_the_contract() -> None:
    assert export.RESIDUAL_COLUMNS == (
        "fold_id",
        "season",
        "gameweek",
        "player_id",
        "team_id",
        "position",
        "predicted_points",
        "realized_points",
        "residual",
    )
