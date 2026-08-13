"""Tests for the model-neutral prediction-to-optimization hand-off."""

from dataclasses import replace

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal
from tests.fixtures.synthetic_gameweeks import SEASON, make_canonical_gameweeks

from squadopt.backtest import DecisionPoint, baseline_projection_builder, build_walk_forward_fold
from squadopt.prediction import (
    PREDICTION_TO_OPTIMIZATION_CONTRACT_VERSION,
    PredictionConfigurationError,
    PredictionProvenance,
    PredictionSnapshot,
    prepare_optimizer_projection,
)


def _provenance() -> PredictionProvenance:
    return PredictionProvenance(
        model_name="synthetic-regressor",
        model_version="1.0.0",
        feature_contract_version="synthetic-features-v1",
        training_cutoff="2024-25:GW38",
        training_data_fingerprint="a" * 64,
    )


def _inputs() -> tuple[pd.DataFrame, pd.DataFrame]:
    players = pd.DataFrame(
        {
            "player_id": [2, 1],
            "name": ["Two", "One"],
            "team_id": [20, 10],
            "position": ["MID", "GK"],
            "price_tenths": pd.Series([75, 45], dtype="int64"),
        }
    )
    predictions = pd.DataFrame(
        {
            "player_id": [1, 2],
            "expected_points": [3.125, 6.75],
            "model_debug": ["ignored", "ignored"],
        }
    )
    return players, predictions


def test_external_predictions_are_exact_aligned_and_fingerprinted() -> None:
    players, predictions = _inputs()

    result = prepare_optimizer_projection(players, predictions, _provenance())

    assert result.table["player_id"].tolist() == [1, 2]
    assert result.table["expected_points"].tolist() == [3.125, 6.75]
    assert "model_debug" not in result.table
    assert len(result.prediction_fingerprint) == 64
    assert len(result.provenance.provenance_fingerprint) == 64
    assert result.provenance.contract_version == PREDICTION_TO_OPTIMIZATION_CONTRACT_VERSION


def test_prediction_inputs_are_not_mutated() -> None:
    players, predictions = _inputs()
    players_before = players.copy(deep=True)
    predictions_before = predictions.copy(deep=True)

    result = prepare_optimizer_projection(players, predictions, _provenance())
    result.table.loc[0, "name"] = "changed"

    assert_frame_equal(players, players_before)
    assert_frame_equal(predictions, predictions_before)


def test_prediction_snapshot_is_order_deterministic() -> None:
    players, predictions = _inputs()

    first = prepare_optimizer_projection(players, predictions, _provenance())
    second = prepare_optimizer_projection(
        players.iloc[::-1].reset_index(drop=True),
        predictions.iloc[::-1].reset_index(drop=True),
        _provenance(),
    )

    assert_frame_equal(first.table, second.table)
    assert first.prediction_fingerprint == second.prediction_fingerprint


def test_numerically_equal_signed_zero_has_one_prediction_fingerprint() -> None:
    players, predictions = _inputs()
    positive = predictions.assign(expected_points=[0.0, 0.0])
    negative = predictions.assign(expected_points=[-0.0, -0.0])

    first = prepare_optimizer_projection(players, positive, _provenance())
    second = prepare_optimizer_projection(players, negative, _provenance())

    assert first.prediction_fingerprint == second.prediction_fingerprint


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda frame: frame.iloc[:-1].copy(), "align exactly"),
        (
            lambda frame: pd.concat(
                [frame, pd.DataFrame({"player_id": [3], "expected_points": [1.0]})],
                ignore_index=True,
            ),
            "align exactly",
        ),
        (lambda frame: frame.assign(expected_points=float("nan")), "missing values"),
        (lambda frame: frame.assign(expected_points=-1.0), "non-negative"),
        (lambda frame: frame.assign(player_id=frame["player_id"].astype(str)), "same player_id"),
    ],
)
def test_invalid_prediction_contract_is_rejected(mutation: object, message: str) -> None:
    players, predictions = _inputs()
    transform = mutation
    assert callable(transform)

    with pytest.raises(PredictionConfigurationError, match=message):
        prepare_optimizer_projection(players, transform(predictions), _provenance())


def test_tampered_snapshot_fingerprint_is_rejected() -> None:
    players, predictions = _inputs()
    result = prepare_optimizer_projection(players, predictions, _provenance())

    with pytest.raises(PredictionConfigurationError, match="does not match"):
        replace(result, prediction_fingerprint="b" * 64)


def test_walk_forward_fold_preserves_prediction_provenance() -> None:
    panel = make_canonical_gameweeks()
    decision = DecisionPoint(season=SEASON, gameweek=6)

    def builder(visible: pd.DataFrame, target: DecisionPoint) -> PredictionSnapshot:
        baseline = baseline_projection_builder(visible, target)
        return prepare_optimizer_projection(
            baseline.drop(columns=["expected_points"]),
            baseline.loc[:, ["player_id", "expected_points"]],
            _provenance(),
        )

    fold = build_walk_forward_fold(panel, decision, projection_builder=builder)

    assert fold.metadata["prediction_contract_version"] == (
        PREDICTION_TO_OPTIMIZATION_CONTRACT_VERSION
    )
    assert fold.metadata["prediction_model_name"] == "synthetic-regressor"
    assert fold.metadata["prediction_training_cutoff"] == "2024-25:GW38"
    assert fold.metadata["prediction_training_data_fingerprint"] == "a" * 64
    assert len(str(fold.metadata["prediction_fingerprint"])) == 64


def test_walk_forward_fold_revalidates_a_mutated_snapshot() -> None:
    panel = make_canonical_gameweeks()
    decision = DecisionPoint(season=SEASON, gameweek=6)
    baseline = baseline_projection_builder(panel, decision)
    snapshot = prepare_optimizer_projection(
        baseline.drop(columns=["expected_points"]),
        baseline.loc[:, ["player_id", "expected_points"]],
        _provenance(),
    )
    snapshot.table.loc[snapshot.table.index[0], "expected_points"] = 999.0

    with pytest.raises(PredictionConfigurationError, match="does not match"):
        build_walk_forward_fold(
            panel,
            decision,
            projection_builder=lambda _visible, _target: snapshot,
        )
