"""Synthetic physical clocks exercise source and offset contracts without data reads."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import timedelta
from types import MappingProxyType

import numpy as np
import pytest
from tests.unit.test_football_unit_replay import (
    ACQUIRED,
    FIT,
    GENERATED,
    D,
    current_projection,
    replay_observation,
)

from squadopt.experiments.football_unit_experiment import _result_receipt
from squadopt.features.football_unit_inputs import (
    ProjectedUnitState,
    UnitPhysicalExposureClock,
)
from squadopt.prediction.football_unit_strength import (
    UNIT_PHYSICAL_EXPOSURE_POLICY,
    UNIT_PHYSICAL_FIT_VERSION,
    UNIT_PHYSICAL_MODEL_VERSION,
    UNIT_SOURCE_MISSINGNESS_POLICY,
    FootballUnitStrengthModel,
)


def physical_rows():
    original = replay_observation()
    replay = replace(
        original.catalog.replay,
        source_hashes=(
            *original.catalog.replay.source_hashes,
            ("duration_forecast.json", "8" * 64),
            ("duration_history.json", "9" * 64),
            ("duration_clock_source.json", "b" * 64),
        ),
    )
    catalog = replace(original.catalog, replay=replay)
    clock = UnitPhysicalExposureClock(
        source_sha256=original.outcome_source.sha256,
        interval_id="fixture1:0:3001",
        selection_reference="test-only-whole-match-selection",
        start_seconds=0,
        end_seconds=3001,
        actual_duration_seconds=6001,
        forecast_duration_minutes=100.0,
        duration_forecast_sha256="8" * 64,
        duration_history_sha256="9" * 64,
        duration_source_sha256="b" * 64,
        feature_cutoff=replay.feature_cutoff,
        latest_history_settlement_bound=D - timedelta(days=2),
        duration_source_captured_at=ACQUIRED,
        generated_at=GENERATED,
        history_fixtures=(("2024-25", 38, 999),),
    )
    first = replace(original, catalog=catalog, minutes=3001 / 60, exposure_clock=clock)
    second = replace(
        first,
        start_minute=3001 / 60,
        minutes=3000 / 60,
        own_goals=0,
        opponent_goals=0,
        exposure_clock=replace(
            clock, start_seconds=3001, end_seconds=6001, interval_id="fixture1:3001:6001"
        ),
    )
    return first, second


def fit(rows=None, **options):
    return FootballUnitStrengthModel(
        physical_rows() if rows is None else rows,
        cutoff=FIT,
        **{
            "allow_released_2025_26": True,
            "missingness_policy": UNIT_SOURCE_MISSINGNESS_POLICY,
            "exposure_policy": UNIT_PHYSICAL_EXPOSURE_POLICY,
            **options,
        },
    )


@pytest.fixture(scope="module")
def model():
    return fit()


@pytest.mark.parametrize(
    "changes",
    [
        {"version": "reported-clock"},
        {"duration_policy": "actual_target_duration"},
        {"start_seconds": True},
        {"start_seconds": 0.0},
        {"end_seconds": 3001.0},
        {"actual_duration_seconds": 6001.0},
        {"start_seconds": -1},
        {"end_seconds": 0},
        {"actual_duration_seconds": 3000},
        {"actual_duration_seconds": 7201},
        {"forecast_duration_minutes": True},
        {"forecast_duration_minutes": float("nan")},
        {"forecast_duration_minutes": float("inf")},
        {"forecast_duration_minutes": 0},
        {"forecast_duration_minutes": 121},
        {"source_sha256": "x" * 64},
        {"duration_forecast_sha256": "8" * 63},
        {"duration_history_sha256": ""},
        {"duration_source_sha256": "B" * 64},
        {"interval_id": " "},
        {"selection_reference": ""},
        {"duration_source_captured_at": D - timedelta(hours=1)},
        {"generated_at": ACQUIRED - timedelta(seconds=1)},
        {"generated_at": GENERATED.replace(tzinfo=None)},
        {"latest_history_settlement_bound": D},
        {"history_fixtures": ()},
        {"history_fixtures": [["2024-25", 38, 999]]},
        {"history_fixtures": (("2024-25", 38, True),)},
        {"history_fixtures": (("2024-25", 38, 999), ("2024-25", 37, 999))},
    ],
)
def test_physical_clock_requires_exact_source_clock_and_population(changes):
    with pytest.raises(ValueError):
        replace(physical_rows()[0].exposure_clock, **changes)


@pytest.mark.parametrize(
    "changes",
    [
        {"source_sha256": "a" * 64},
        {"duration_forecast_sha256": "a" * 64},
        {"duration_history_sha256": "a" * 64},
        {"duration_source_sha256": "a" * 64},
        {"feature_cutoff": D - timedelta(hours=2)},
        {"latest_history_settlement_bound": D - timedelta(days=2) + timedelta(seconds=1)},
        {"generated_at": GENERATED + timedelta(seconds=1)},
        {"history_fixtures": (("2025-26", 1, 999),)},
        {"history_fixtures": (("2025-26", 2, 999),)},
        {"history_fixtures": (("2026-27", 1, 999),)},
    ],
)
def test_physical_observation_binds_original_replay_and_duration_sources(changes):
    row = physical_rows()[0]
    with pytest.raises(ValueError):
        replace(row, exposure_clock=replace(row.exposure_clock, **changes))


def test_same_season_duration_history_excludes_target_fixture_under_an_earlier_week():
    row = physical_rows()[0]
    with pytest.raises(ValueError, match="target whole gameweek"):
        row.exposure_clock.validate_replay(
            row.catalog.replay, season="2024-25", gameweek=39, fixture_id=999
        )


def test_observed_finished_bound_may_equal_original_revision_record():
    row = physical_rows()[0]
    assert row.exposure_clock.latest_history_settlement_bound == row.catalog.replay.recorded_at
    row.exposure_clock.validate_replay(
        row.catalog.replay, season=row.season, gameweek=row.gameweek, fixture_id=row.fixture_id
    )


@pytest.mark.parametrize("changes", [{"minutes": 50}, {"start_minute": 0.01}])
def test_float_minutes_must_match_exact_seconds(changes):
    with pytest.raises(ValueError, match="exact source second bounds"):
        replace(physical_rows()[0], **changes)


@pytest.mark.parametrize("case", ["gap", "overlap", "partial", "duration", "forecast"])
def test_physical_fit_requires_one_complete_consistent_observed_partition(case):
    first, second = physical_rows()
    if case == "partial":
        rows = (first,)
    elif case in ("duration", "forecast"):
        key = "actual_duration_seconds" if case == "duration" else "forecast_duration_minutes"
        second = replace(
            second,
            exposure_clock=replace(
                second.exposure_clock, **{key: 6100 if case == "duration" else 99}
            ),
        )
        rows = (first, second)
    else:
        start = 3002 if case == "gap" else 3000
        second = replace(
            second,
            start_minute=start / 60,
            minutes=(6001 - start) / 60,
            exposure_clock=replace(second.exposure_clock, start_seconds=start),
        )
        rows = (first, second)
    with pytest.raises(ValueError):
        fit(rows)


@pytest.mark.parametrize("policy", [None, True, 1, "unknown", ""])
def test_exposure_policy_requires_exact_explicit_choice(policy):
    with pytest.raises(ValueError, match="policy"):
        fit(exposure_policy=policy)


def test_physical_policy_rejects_legacy_features_and_mixed_clock_populations():
    with pytest.raises(ValueError, match="source missingness"):
        fit(missingness_policy="per_attribute_v1")
    with pytest.raises(ValueError, match="separate explicit fits"):
        fit((physical_rows()[0], replay_observation()))
    with pytest.raises(ValueError, match="separate explicit fits"):
        fit(exposure_policy="reported_minutes_over_90_v1")
    with pytest.raises(ValueError, match="Locked 2025-26"):
        fit(allow_released_2025_26=False)


def test_offset_uses_predecision_duration_and_whole_fixture_mean(monkeypatch):
    from sklearn.linear_model import PoissonRegressor

    original = PoissonRegressor.fit
    captured = []

    def recording_fit(self, x, y, sample_weight=None):
        captured.append((y.copy(), sample_weight.copy()))
        return original(self, x, y, sample_weight=sample_weight)

    monkeypatch.setattr(PoissonRegressor, "fit", recording_fit)
    fit()
    targets, weights = captured[0]
    expected = np.array([3001 / 6000 * 1.4, 3001 / 6000 * 0.8, 0.7, 0.4])
    np.testing.assert_array_equal(weights, expected)
    np.testing.assert_array_equal(targets * weights, [2, 1, 0, 0])
    # 6001 observed seconds define the partition, never the 6000-second forecast offset.
    assert weights.sum() == pytest.approx(6001 / 6000 * 2.2)


def test_physical_result_is_versioned_and_neutral_reference_retains_native_mean(model):
    projection = current_projection()
    result = model.predict(projection)
    assert result.model_version == UNIT_PHYSICAL_MODEL_VERSION
    assert result.metadata["fit_contract"] == UNIT_PHYSICAL_FIT_VERSION
    assert result.metadata["exposure_policy"] == UNIT_PHYSICAL_EXPOSURE_POLICY
    assert result.metadata["training_rows"] == 4
    assert _result_receipt(result)
    neutral = model.predict(
        replace(
            projection,
            states=(
                ProjectedUnitState(1, projection.reference_own, projection.reference_opponent),
            ),
        )
    )
    assert neutral.own_goal_rate == projection.causal_baseline_own_goal_rate
    assert neutral.opponent_goal_rate == projection.causal_baseline_opponent_goal_rate


@pytest.mark.parametrize(
    "mutation",
    [
        "strip_contract",
        "model_version",
        "offset",
        "policy",
        "selection",
        "clock",
        "missing_clock_version",
        "duration_hash",
        "forecast_hash",
        "capture",
        "history_target",
        "history_future",
        "minute_rounding",
        "partial_partition",
        "overlap",
        "duration_disagreement",
    ],
)
def test_result_reader_refuses_tampered_physical_contract_and_population(model, mutation):
    result = model.predict(current_projection())
    metadata = dict(result.metadata)
    exposures = [json.loads(value) for value in metadata["training_exposure_receipts"]]
    if mutation == "strip_contract":
        metadata.pop("fit_contract")
    elif mutation == "model_version":
        result = replace(result, model_version="football_projected_unit_source_missingness_v2")
    elif mutation in ("offset", "selection", "policy"):
        key = {"offset": "offset", "selection": "training_selection", "policy": "exposure_policy"}
        metadata[key[mutation]] = "other"
    elif mutation == "partial_partition":
        for key in (
            "training_exposure_receipts",
            "training_replay_receipts",
            "training_source_receipts",
            "training_catalog_receipts",
            "training_observation_receipts",
        ):
            if key in metadata:
                metadata[key] = metadata[key][:1]
        exposures = exposures[:1]
        metadata["training_rows"] = 2
    elif mutation == "minute_rounding":
        exposures[0]["minutes"] = 50
    elif mutation == "overlap":
        exposures[1]["clock"]["start_seconds"] = 3000
        exposures[1]["start_minute"] = 50
        exposures[1]["minutes"] = 3001 / 60
    elif mutation == "duration_disagreement":
        exposures[1]["clock"]["actual_duration_seconds"] = 6100
    elif mutation == "missing_clock_version":
        exposures[0]["clock"].pop("version")
    else:
        key, value = {
            "clock": ("version", "reported_first_half_minute_bins_0_to_40_v1"),
            "duration_hash": ("duration_source_sha256", "c" * 64),
            "forecast_hash": ("duration_forecast_sha256", "c" * 64),
            "capture": ("duration_source_captured_at", D.isoformat()),
            "history_target": ("history_fixtures", [["2025-26", 1, 1]]),
            "history_future": ("history_fixtures", [["2026-27", 1, 999]]),
        }[mutation]
        exposures[0]["clock"][key] = value
    metadata["training_exposure_receipts"] = tuple(json.dumps(value) for value in exposures)
    with pytest.raises(ValueError):
        _result_receipt(replace(result, metadata=MappingProxyType(metadata)))
