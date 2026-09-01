"""Parity tests for the empirical appearance control adapter."""

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

from squadopt.features import PRIOR_MINUTES_COLUMN, PRIOR_RATE_COLUMN
from squadopt.prediction import (
    COMPONENT_MODEL_ROUTE,
    DIRECT_CONTROL_ROUTE,
    ComponentPredictionSnapshot,
    PredictionConfigurationError,
    PredictionProvenance,
    ProductionProjectionConfig,
    production_component_prediction,
    production_projection,
)

TIMESTAMP = "2026-09-01T12:00:00Z"
CONFIG = ProductionProjectionConfig()


def _provenance() -> PredictionProvenance:
    return PredictionProvenance(
        model_name="squadopt-two-stage-control",
        model_version="control-v1",
        feature_contract_version="two-stage-appearance-calendar-v1",
        training_cutoff="2024-25:GW38",
        training_data_fingerprint="a" * 64,
    )


def _features() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "player_id": [1, 2, 3, 4, 5, 6, 7, 8],
            CONFIG.minutes.appearance_rate_column: [
                0.5,
                0.0,
                pd.NA,
                pd.NA,
                0.8,
                0.5,
                0.5,
                0.5,
            ],
            CONFIG.minutes.minutes_per_appearance_column: [
                80.0,
                pd.NA,
                pd.NA,
                pd.NA,
                80.0,
                200.0,
                80.0,
                80.0,
            ],
            CONFIG.rate_column: [9.0, pd.NA, pd.NA, pd.NA, 6.0, 6.0, 6.0, pd.NA],
            PRIOR_MINUTES_COLUMN: [
                pd.NA,
                pd.NA,
                80.0,
                pd.NA,
                pd.NA,
                pd.NA,
                pd.NA,
                pd.NA,
            ],
            PRIOR_RATE_COLUMN: [pd.NA, pd.NA, 6.0, pd.NA, pd.NA, pd.NA, pd.NA, pd.NA],
            "fixture_count": [1, 1, 1, 1, 0, 1, 2, 1],
            "price_tenths": [80, 70, 60, 100, 90, 80, 80, 90],
        }
    )


def _snapshot(frame: pd.DataFrame | None = None) -> ComponentPredictionSnapshot:
    return production_component_prediction(
        _features() if frame is None else frame,
        _provenance(),
        decision_timestamp_utc=TIMESTAMP,
        config=CONFIG,
    )


def test_component_control_preserves_every_operational_expected_point() -> None:
    features = _features()
    operational = production_projection(features, config=CONFIG)
    snapshot = _snapshot(features)

    assert snapshot.table["expected_points"].tolist() == pytest.approx(
        operational.expected_points.tolist(), abs=1e-12
    )


def test_only_algebraically_supported_rows_use_the_component_route() -> None:
    table = _snapshot().table.set_index("player_id")

    assert table.loc[[1, 2, 7], "composition_route"].tolist() == [
        COMPONENT_MODEL_ROUTE,
        COMPONENT_MODEL_ROUTE,
        COMPONENT_MODEL_ROUTE,
    ]
    assert table.loc[[3, 4, 5, 6, 8], "composition_route"].tolist() == [
        DIRECT_CONTROL_ROUTE,
        DIRECT_CONTROL_ROUTE,
        DIRECT_CONTROL_ROUTE,
        DIRECT_CONTROL_ROUTE,
        DIRECT_CONTROL_ROUTE,
    ]
    assert table.loc[1, "expected_minutes_if_appearance"] == 80.0
    assert table.loc[1, "expected_points_if_appearance"] == 8.0
    assert table.loc[7, "expected_minutes_if_appearance"] == 160.0
    assert table.loc[7, "appearance_probability"] == 0.5
    assert pd.isna(table.loc[8, "appearance_probability"])


def test_missing_history_is_not_relabelled_as_zero_probability() -> None:
    table = _snapshot().table.set_index("player_id")

    assert pd.isna(table.loc[3, "appearance_probability"])
    assert pd.isna(table.loc[4, "appearance_probability"])
    assert table.loc[2, "appearance_probability"] == 0.0


def test_adapter_is_deterministic_and_does_not_mutate_inputs() -> None:
    frame = _features()
    before = frame.copy(deep=True)

    first = _snapshot(frame)
    second = _snapshot(frame.iloc[::-1].reset_index(drop=True))

    assert_frame_equal(frame, before)
    assert_frame_equal(first.table, second.table)
    assert first.component_fingerprint == second.component_fingerprint


def test_adapter_rejects_a_non_dataframe_at_the_public_boundary() -> None:
    with pytest.raises(PredictionConfigurationError, match="pandas DataFrame"):
        production_component_prediction(
            [],  # type: ignore[arg-type]
            _provenance(),
            decision_timestamp_utc=TIMESTAMP,
            config=CONFIG,
        )
