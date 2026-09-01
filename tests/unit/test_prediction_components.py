"""Behavioural tests for the Phase C component-prediction boundary."""

from collections.abc import Callable

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

from squadopt.prediction import (
    ComponentPredictionSnapshot,
    PredictionConfigurationError,
    PredictionProvenance,
    prepare_component_prediction,
    prepare_optimizer_projection,
)

DECISION_TIMESTAMP = "2026-09-01T12:00:00Z"


def _provenance() -> PredictionProvenance:
    return PredictionProvenance(
        model_name="phase-c-synthetic",
        model_version="1.0.0",
        feature_contract_version="phase-c-features-v1",
        training_cutoff="2024-25:GW38",
        training_data_fingerprint="a" * 64,
    )


def _components() -> pd.DataFrame:
    """One reduced-form component row and one direct-control fallback row."""

    return pd.DataFrame(
        {
            "player_id": [2, 1],
            "fixture_count": [1, 1],
            "appearance_probability": [float("nan"), 0.75],
            "expected_minutes_if_appearance": [float("nan"), 80.0],
            "expected_points_if_appearance": [float("nan"), 8.0],
            "fallback_expected_points": [3.25, float("nan")],
            "composition_route": ["direct_control", "component_model"],
            "evidence_status": ["not_requested", "not_requested"],
        }
    )


def _prepare(frame: pd.DataFrame | None = None) -> ComponentPredictionSnapshot:
    return prepare_component_prediction(
        _components() if frame is None else frame,
        _provenance(),
        decision_timestamp_utc=DECISION_TIMESTAMP,
    )


def test_mixed_component_and_fallback_rows_compose_their_exact_means() -> None:
    snapshot = _prepare()

    assert isinstance(snapshot, ComponentPredictionSnapshot)
    assert snapshot.table["player_id"].tolist() == [1, 2]
    assert pd.isna(snapshot.table["start_probability"].iloc[0])
    assert snapshot.table["expected_minutes"].tolist()[0] == pytest.approx(60.0)
    assert pd.isna(snapshot.table["expected_minutes"].iloc[1])
    assert snapshot.table["expected_points"].tolist() == pytest.approx([6.0, 3.25])

    assert snapshot.start_component_status == "unavailable"
    assert snapshot.diagnostics["start_component_status"] == "unavailable"


@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("appearance_probability", -0.01),
        ("appearance_probability", 1.01),
        ("appearance_probability", float("nan")),
        ("appearance_probability", float("inf")),
    ],
)
def test_component_probabilities_must_be_finite_and_bounded(column: str, value: float) -> None:
    frame = _components()
    component = frame["composition_route"].eq("component_model")
    frame.loc[component, column] = value

    with pytest.raises(PredictionConfigurationError):
        _prepare(frame)


@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("expected_minutes_if_appearance", -1.0),
        ("expected_minutes_if_appearance", float("nan")),
        ("expected_minutes_if_appearance", float("inf")),
        ("expected_points_if_appearance", float("nan")),
        ("expected_points_if_appearance", float("inf")),
    ],
)
def test_component_conditional_means_must_be_finite_and_non_negative(
    column: str,
    value: float,
) -> None:
    frame = _components()
    component = frame["composition_route"].eq("component_model")
    frame.loc[component, column] = value

    with pytest.raises(PredictionConfigurationError):
        _prepare(frame)


def test_only_the_composed_point_mean_must_be_non_negative() -> None:
    frame = _components()
    component = frame["composition_route"].eq("component_model")
    frame.loc[component, "appearance_probability"] = 0.0
    frame.loc[component, "expected_points_if_appearance"] = -1.0

    assert _prepare(frame).table.loc[0, "expected_points"] == 0.0

    frame.loc[component, "appearance_probability"] = 0.5
    with pytest.raises(PredictionConfigurationError, match="optimizer boundary"):
        _prepare(frame)


def test_conditional_minutes_cannot_exceed_the_fixture_support() -> None:
    frame = _components()
    component = frame["composition_route"].eq("component_model")
    frame.loc[component, "expected_minutes_if_appearance"] = 91.0

    with pytest.raises(PredictionConfigurationError, match=r"90 \* fixture_count"):
        _prepare(frame)


def test_missing_required_component_column_is_reported() -> None:
    with pytest.raises(PredictionConfigurationError, match="fixture_count"):
        _prepare(_components().drop(columns=["fixture_count"]))


@pytest.mark.parametrize(
    "mutation",
    [
        lambda frame: pd.concat([frame, frame.iloc[[0]]], ignore_index=True),
        lambda frame: frame.assign(player_id=[1, "2"]),
    ],
)
def test_player_ids_must_be_unique_and_use_one_representation(
    mutation: Callable[[pd.DataFrame], pd.DataFrame],
) -> None:
    with pytest.raises(PredictionConfigurationError, match="player_id"):
        _prepare(mutation(_components()))


@pytest.mark.parametrize("value", [-1, 1.5, float("nan"), True])
def test_fixture_count_must_be_a_non_negative_integer(value: object) -> None:
    frame = _components()
    frame["fixture_count"] = frame["fixture_count"].astype("object")
    frame.loc[frame.index[0], "fixture_count"] = value

    with pytest.raises(PredictionConfigurationError, match="fixture_count"):
        _prepare(frame)


def test_blank_gameweek_requires_an_explicit_zero_component_contribution() -> None:
    frame = _components()
    component = frame["composition_route"].eq("component_model")
    frame.loc[component, "fixture_count"] = 0

    with pytest.raises(PredictionConfigurationError):
        _prepare(frame)

    frame.loc[component, "appearance_probability"] = 0.0
    frame.loc[component, "expected_minutes_if_appearance"] = 0.0
    frame.loc[component, "expected_points_if_appearance"] = 0.0

    snapshot = _prepare(frame)

    assert snapshot.table.loc[0, "expected_minutes"] == 0.0
    assert snapshot.table.loc[0, "expected_points"] == 0.0
    assert snapshot.table.loc[0, "start_probability"] == 0.0


def test_blank_direct_control_normalizes_calendar_outputs_to_zero() -> None:
    frame = _components()
    direct = frame["composition_route"].eq("direct_control")
    frame.loc[direct, "fixture_count"] = 0
    frame.loc[direct, "fallback_expected_points"] = 0.0

    row = _prepare(frame).table.loc[1]

    assert row["appearance_probability"] == 0.0
    assert row["expected_minutes_if_appearance"] == 0.0
    assert row["expected_points_if_appearance"] == 0.0
    assert row["start_probability"] == 0.0
    assert row["expected_minutes"] == 0.0
    assert row["expected_points"] == 0.0


@pytest.mark.parametrize("fallback", [float("nan"), -1.0, float("inf")])
def test_direct_control_requires_a_finite_non_negative_fallback(fallback: float) -> None:
    frame = _components()
    direct = frame["composition_route"].eq("direct_control")
    frame.loc[direct, "fallback_expected_points"] = fallback

    with pytest.raises(PredictionConfigurationError, match="fallback_expected_points"):
        _prepare(frame)


def test_direct_control_rejects_component_values() -> None:
    frame = _components()
    direct = frame["composition_route"].eq("direct_control")
    frame.loc[direct, "appearance_probability"] = 0.5

    with pytest.raises(PredictionConfigurationError, match=r"direct_control|component"):
        _prepare(frame)


def test_component_route_rejects_a_fallback_value() -> None:
    frame = _components()
    component = frame["composition_route"].eq("component_model")
    frame.loc[component, "fallback_expected_points"] = 5.0

    with pytest.raises(PredictionConfigurationError, match="fallback_expected_points"):
        _prepare(frame)


@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("composition_route", "hybrid"),
        ("evidence_status", "imputed_zero"),
        ("evidence_status", "available"),
        ("evidence_status", "missing"),
        ("composition_route", pd.NA),
        ("evidence_status", pd.NA),
    ],
)
def test_route_and_evidence_status_use_the_frozen_vocabularies(column: str, value: object) -> None:
    frame = _components()
    frame.loc[frame.index[0], column] = value

    with pytest.raises(PredictionConfigurationError, match=column):
        _prepare(frame)


@pytest.mark.parametrize(
    "timestamp",
    [
        "2026-09-01T12:00:00",
        "2026-09-01T15:00:00+03:00",
        "not-a-timestamp",
    ],
)
def test_decision_timestamp_must_be_an_explicit_utc_instant(timestamp: str) -> None:
    with pytest.raises(PredictionConfigurationError, match="decision_timestamp_utc"):
        prepare_component_prediction(
            _components(),
            _provenance(),
            decision_timestamp_utc=timestamp,
        )


def test_input_is_not_mutated_and_row_order_does_not_change_the_fingerprint() -> None:
    frame = _components()
    before = frame.copy(deep=True)

    first = _prepare(frame)
    second = _prepare(frame.iloc[::-1].reset_index(drop=True))

    assert_frame_equal(frame, before)
    assert_frame_equal(first.table, second.table)
    assert first.component_fingerprint == second.component_fingerprint
    assert len(first.component_fingerprint) == 64


def test_validated_copy_detects_mutable_result_corruption() -> None:
    snapshot = _prepare()
    snapshot.table.loc[0, "expected_points"] = 999.0

    with pytest.raises(PredictionConfigurationError):
        snapshot.validated_copy()


def test_optimizer_handoff_receives_only_player_id_and_expected_points() -> None:
    snapshot = _prepare()
    players = pd.DataFrame(
        {
            "player_id": [2, 1],
            "name": ["Two", "One"],
            "team_id": [20, 10],
            "position": ["MID", "GK"],
            "price_tenths": pd.Series([75, 45], dtype="int64"),
        }
    )

    optimizer_snapshot = prepare_optimizer_projection(
        players,
        snapshot.table.loc[:, ["player_id", "expected_points"]],
        snapshot.provenance,
    )

    assert optimizer_snapshot.table.columns.tolist() == [
        "player_id",
        "name",
        "team_id",
        "position",
        "price_tenths",
        "expected_points",
    ]
    assert "appearance_probability" not in optimizer_snapshot.table
    assert "start_probability" not in optimizer_snapshot.table
