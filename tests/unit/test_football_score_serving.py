"""Strict parameter transport and exact full/compact score process parity."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import FrozenInstanceError, asdict, replace
from typing import Any

import pytest
from tests.unit.test_football_score_replay import fit as replay_fit
from tests.unit.test_football_score_replay import replay
from tests.unit.test_football_score_state import fit, fixture

from squadopt.prediction.football_score_serving import (
    MAX_ARTIFACT_BYTES,
    ScoreServingModel,
    export_score_serving_model,
    read_score_serving_model,
)
from squadopt.prediction.football_score_state import ScoreStateModel


def load(payload: bytes) -> ScoreServingModel:
    return read_score_serving_model(payload, expected_sha256=hashlib.sha256(payload).hexdigest())


@pytest.fixture(scope="module")
def fitted() -> ScoreStateModel:
    return fit()


@pytest.mark.parametrize("zero", [False, True])
def test_identical_process_outputs_have_distinct_correct_parameter_receipt(
    fitted: ScoreStateModel, zero: bool
) -> None:
    original = fitted.metadata_json
    payload = export_score_serving_model(fitted)
    compact = load(payload)
    source = fixture(target=True)
    full = fitted.predict(source, zero_coefficients=zero)
    result = compact.predict(source, zero_coefficients=zero)
    assert replace(result.prediction, model_sha256=full.model_sha256) == full
    assert result.prediction.model_sha256 == hashlib.sha256(payload).hexdigest()
    assert result.serving_receipt.artifact_sha256 == result.prediction.model_sha256
    assert result.serving_receipt.original_metadata_sha256 == fitted.model_sha256
    assert result.serving_receipt.input_sha256 == full.input_sha256
    assert result.serving_receipt.zero_coefficients is zero
    assert fitted.metadata_json == original
    assert "training_receipts" not in json.loads(payload)
    assert "solver_receipt" not in json.loads(payload)
    assert len(payload) < 2048


def test_released_replay_fit_exports_actual_contract_and_original_digest() -> None:
    model = replay_fit(
        (replay(released=True),), allowed_seasons=("2025-26",), allow_released_2025_26=True
    )
    compact = load(export_score_serving_model(model))
    assert compact.metadata.allow_released_2025_26
    assert compact.metadata.fit_contract == "football_score_public_replay_fit_v1"
    assert compact.metadata.original_metadata_sha256 == model.model_sha256
    result = compact.predict(fixture(target=True))
    assert replace(result.prediction, model_sha256=model.model_sha256) == model.predict(
        fixture(target=True)
    )


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("contract_version", "unknown"),
        ("model_version", "unknown"),
        ("feature_version", "unknown"),
        ("feature_names", ["wrong"] * 6),
        ("coefficients", [True] * 6),
        ("coefficients", ["1"] * 6),
        ("coefficients", [6.000001] * 6),
        ("coefficients", [0] * 5),
        ("coefficients", "000000"),
        ("cutoff", "2026-10-09"),
        ("cutoff", None),
        ("target_season", "2026-28"),
        ("target_gameweeks", [6, 6]),
        ("target_gameweeks", [True]),
        ("target_gameweeks", []),
        ("numerical_tolerance", True),
        ("numerical_tolerance", 1e-13),
        ("numerical_tolerance", 1e-5),
        ("max_difference", 513),
        ("max_difference", 2.0),
        ("max_difference", True),
        ("original_metadata_sha256", "A" * 64),
        ("fit_contract", "unknown"),
        ("allow_released_2025_26", 1),
        ("allow_released_2025_26", True),
        ("native_offset", "changed"),
        ("playing_interval_policy", "changed"),
        ("numerical_method", "changed"),
    ],
)
def test_semantic_tampering_refuses_even_with_a_matching_outer_digest(
    fitted: ScoreStateModel, name: str, value: Any
) -> None:
    body = json.loads(export_score_serving_model(fitted))
    body[name] = value
    with pytest.raises(ValueError):
        load(json.dumps(body, sort_keys=True, separators=(",", ":")).encode())


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf"), 10**500])
def test_nonfinite_and_overflow_coefficients_refuse(fitted: ScoreStateModel, value: Any) -> None:
    body = json.loads(export_score_serving_model(fitted))
    body["coefficients"][0] = value
    with pytest.raises(ValueError):
        load(json.dumps(body, sort_keys=True, separators=(",", ":")).encode())


def test_duplicate_unknown_missing_and_noncanonical_json_refuse(fitted: ScoreStateModel) -> None:
    payload = export_score_serving_model(fitted)
    body = json.loads(payload)
    invalid = [
        b'{"cutoff":"2026-10-09T00:00:00Z",' + payload[1:],
        json.dumps(body, indent=2).encode(),
        payload + b"\n",
        b"[]",
        b"\xff",
        b"{" * 2000,
        b" " * (MAX_ARTIFACT_BYTES + 1),
        json.dumps(dict(body, training_receipts=[])).encode(),
    ]
    del body["feature_names"]
    invalid.append(json.dumps(body).encode())
    for raw in invalid:
        with pytest.raises(ValueError):
            load(raw)
    with pytest.raises(ValueError, match="digest"):
        read_score_serving_model(payload, expected_sha256="a" * 64)
    with pytest.raises(ValueError, match="SHA256"):
        read_score_serving_model(payload, expected_sha256="x")
    with pytest.raises(ValueError, match="bytes"):
        read_score_serving_model(bytearray(payload), expected_sha256="a" * 64)  # type: ignore[arg-type]


def test_recursive_immutability_and_direct_construction_hash_guard(fitted: ScoreStateModel) -> None:
    compact = load(export_score_serving_model(fitted))
    with pytest.raises(FrozenInstanceError):
        compact.metadata = compact.metadata  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        compact.metadata.cutoff = "2026-01-01T00:00:00Z"  # type: ignore[misc]
    with pytest.raises(TypeError):
        compact.metadata.coefficients[0] = 0.0  # type: ignore[index]
    with pytest.raises(ValueError, match="digest"):
        ScoreServingModel(
            replace(compact.metadata, coefficients=(0.0,) * 6), compact.artifact_sha256
        )
    # Even deliberate frozen-dataclass bypass cannot silently change inference.
    object.__setattr__(compact, "metadata", replace(compact.metadata, coefficients=(0.0,) * 6))
    with pytest.raises(ValueError, match="digest"):
        compact.predict(fixture(target=True))


def test_temporal_target_and_nonboolean_controls_refuse(fitted: ScoreStateModel) -> None:
    compact = load(export_score_serving_model(fitted))
    target = fixture(target=True)
    for source in (
        fixture(),
        replace(target, gameweek=5),
        replace(target, decision_at="2026-10-08T00:00:00Z"),
    ):
        with pytest.raises(ValueError):
            compact.predict(source)
    with pytest.raises(ValueError, match="Boolean"):
        compact.predict(target, zero_coefficients=1)  # type: ignore[arg-type]


def test_zero_chain_matches_independent_interval_survival(fitted: ScoreStateModel) -> None:
    compact = load(export_score_serving_model(fitted))
    target = fixture(target=True)
    result = compact.predict(target, zero_coefficients=True).prediction
    for source, actual in zip(target.players, result.player_survival, strict=True):
        opponent = (
            target.native_away_goals
            if source.club_code == target.home_club_code
            else target.native_home_goals
        )
        expected = tuple(
            0.0
            if policy == "not_playing"
            else math.exp(-opponent * (end - start) / target.forecast_duration)
            for start, end, policy in zip(
                source.physical_on, source.physical_off, source.exit_policies, strict=True
            )
        )
        assert actual.survival == pytest.approx(expected, abs=2e-15)
    assert asdict(result)["home_physical_goals"] == pytest.approx(
        target.native_home_goals, abs=1e-14
    )
