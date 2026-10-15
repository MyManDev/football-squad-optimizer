"""Compact score-process parameters with a distinct serving receipt and no IO.

The caller authenticates original training sources. A supplied digest binds
these canonical parameter bytes; the original metadata digest is provenance.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import asdict, dataclass, fields
from typing import Any

import numpy as np

from squadopt.features.football_score_replay import REPLAY_FIT_VERSION
from squadopt.features.football_score_state_inputs import ScoreFixture, validate_score_fixture
from squadopt.prediction.football_score_state import (
    COEFFICIENT_BOUND,
    FEATURE_NAMES,
    FEATURE_VERSION,
    MODEL_VERSION,
    ScoreReplayMetadata,
    ScoreStateModel,
    ScoreStatePrediction,
    _predict_score_process,
    _targets,
    _utc,
)

SERVING_VERSION = "football_score_serving_v1"
RECEIPT_VERSION = "football_score_serving_prediction_v1"
MAX_ARTIFACT_BYTES = 65_536


@dataclass(frozen=True)
class ScoreServingMetadata:
    contract_version: str
    model_version: str
    feature_version: str
    feature_names: tuple[str, ...]
    coefficients: tuple[float, ...]
    cutoff: str
    target_season: str
    target_gameweeks: tuple[int, ...]
    numerical_tolerance: float
    max_difference: int
    original_metadata_sha256: str
    fit_contract: str
    allow_released_2025_26: bool
    native_offset: str
    playing_interval_policy: str
    numerical_method: str


@dataclass(frozen=True)
class ScoreServingReceipt:
    contract_version: str
    artifact_sha256: str
    original_metadata_sha256: str
    fit_cutoff: str
    fit_contract: str
    input_sha256: str
    zero_coefficients: bool


@dataclass(frozen=True)
class ScoreServingPrediction:
    prediction: ScoreStatePrediction
    serving_receipt: ScoreServingReceipt


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _sha(value: object) -> str:
    if type(value) is not str or re.fullmatch(r"[a-f0-9]{64}", value) is None:
        raise ValueError("Score serving requires an explicit lowercase SHA256.")
    return value


def _finite(value: object) -> float:
    if type(value) not in (int, float):
        raise ValueError("Score serving numbers must be real numeric values, not Boolean.")
    try:
        result = float(value)  # type: ignore[arg-type]
    except (ValueError, OverflowError) as error:
        raise ValueError("Score serving numbers must be finite.") from error
    if not math.isfinite(result):
        raise ValueError("Score serving numbers must be finite.")
    return result


def _validate(metadata: ScoreServingMetadata) -> None:
    if type(metadata) is not ScoreServingMetadata:
        raise ValueError("Score serving requires typed compact metadata.")
    if (
        metadata.contract_version != SERVING_VERSION
        or metadata.model_version != MODEL_VERSION
        or metadata.feature_version != FEATURE_VERSION
        or type(metadata.feature_names) is not tuple
        or metadata.feature_names != FEATURE_NAMES
        or metadata.fit_contract not in ("football_score_state_fit_v1", REPLAY_FIT_VERSION)
        or metadata.native_offset
        != "original_whole_fixture_goals_divided_by_forecast_physical_duration"
        or metadata.playing_interval_policy
        != "frozen_predecision_normal_exit_no_learned_substitution"
        or metadata.numerical_method
        != "sparse_piecewise_uniformization_exact_difference_poisson_tail_bound"
    ):
        raise ValueError("Unsupported score serving version or numerical policy.")
    if type(metadata.allow_released_2025_26) is not bool or (
        metadata.allow_released_2025_26 and metadata.fit_contract != REPLAY_FIT_VERSION
    ):
        raise ValueError("Score serving released-season declaration disagrees with fit contract.")
    _sha(metadata.original_metadata_sha256)
    _targets(metadata.target_season, metadata.target_gameweeks)
    _utc(metadata.cutoff)
    if (
        type(metadata.coefficients) is not tuple
        or len(metadata.coefficients) != 6
        or any(abs(_finite(value)) > COEFFICIENT_BOUND for value in metadata.coefficients)
    ):
        raise ValueError("Score serving requires six finite bounded coefficients.")
    if not 1e-12 <= _finite(metadata.numerical_tolerance) <= 1e-6:
        raise ValueError("Score serving numerical tolerance is outside its supported range.")
    if type(metadata.max_difference) is not int or not 1 <= metadata.max_difference <= 512:
        raise ValueError("Score serving difference bound must be an integer in 1..512.")


@dataclass(frozen=True)
class ScoreServingModel:
    metadata: ScoreServingMetadata
    artifact_sha256: str

    def __post_init__(self) -> None:
        _validate(self.metadata)
        if hashlib.sha256(_canonical(asdict(self.metadata))).hexdigest() != _sha(
            self.artifact_sha256
        ):
            raise ValueError("Score serving metadata does not match its artifact digest.")

    def predict(
        self, fixture: ScoreFixture, *, zero_coefficients: bool = False
    ) -> ScoreServingPrediction:
        self.__post_init__()
        if type(zero_coefficients) is not bool:
            raise ValueError("Score serving zero-coefficient option must be Boolean.")
        validate_score_fixture(fixture)
        if (
            fixture.season != self.metadata.target_season
            or fixture.gameweek < min(self.metadata.target_gameweeks)
            or _utc(fixture.decision_at) < _utc(self.metadata.cutoff)
        ):
            raise ValueError("Score serving prediction precedes its fit contract.")
        result = _predict_score_process(
            fixture,
            np.zeros(6)
            if zero_coefficients
            else np.asarray(self.metadata.coefficients, dtype=float),
            numerical_tolerance=self.metadata.numerical_tolerance,
            max_difference=self.metadata.max_difference,
            model_sha256=self.artifact_sha256,
            zero_coefficients=zero_coefficients,
        )
        return ScoreServingPrediction(
            result,
            ScoreServingReceipt(
                RECEIPT_VERSION,
                self.artifact_sha256,
                self.metadata.original_metadata_sha256,
                self.metadata.cutoff,
                self.metadata.fit_contract,
                result.input_sha256,
                zero_coefficients,
            ),
        )


def export_score_serving_model(model: ScoreStateModel) -> bytes:
    """Export already fitted parameters; no training provenance is reconstructed."""
    original = model.metadata
    metadata = ScoreServingMetadata(
        SERVING_VERSION,
        original.model_version,
        original.feature_version,
        original.feature_names,
        original.coefficients,
        original.cutoff,
        original.target_season,
        original.target_gameweeks,
        original.numerical_tolerance,
        original.max_difference,
        model.model_sha256,
        original.fit_contract
        if isinstance(original, ScoreReplayMetadata)
        else "football_score_state_fit_v1",
        original.allow_released_2025_26 if isinstance(original, ScoreReplayMetadata) else False,
        original.native_offset,
        original.playing_interval_policy,
        original.numerical_method,
    )
    _validate(metadata)
    payload = _canonical(asdict(metadata))
    if len(payload) > MAX_ARTIFACT_BYTES:
        raise ValueError("Score serving parameter artifact exceeds its transport bound.")
    return payload


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Score serving JSON contains a duplicate key.")
        result[key] = value
    return result


def read_score_serving_model(payload: bytes, *, expected_sha256: str) -> ScoreServingModel:
    """Read a strict canonical artifact whose expected hash the caller supplies."""
    _sha(expected_sha256)
    if type(payload) is not bytes or not 1 <= len(payload) <= MAX_ARTIFACT_BYTES:
        raise ValueError("Score serving requires bounded parameter bytes.")
    if hashlib.sha256(payload).hexdigest() != expected_sha256:
        raise ValueError("Score serving artifact digest differs from expected bytes.")
    try:
        body = json.loads(payload, object_pairs_hook=_object)
        if type(body) is not dict or set(body) != {
            item.name for item in fields(ScoreServingMetadata)
        }:
            raise ValueError("Score serving JSON fields differ from its exact contract.")
        if _canonical(body) != payload:
            raise ValueError("Score serving JSON must use canonical serialization.")
        for name in ("coefficients", "feature_names", "target_gameweeks"):
            if type(body[name]) is not list:
                raise ValueError("Score serving vectors must be JSON arrays.")
            body[name] = tuple(body[name])
        metadata = ScoreServingMetadata(**body)
        return ScoreServingModel(metadata, expected_sha256)
    except (TypeError, UnicodeError, OverflowError, RecursionError) as error:
        raise ValueError("Malformed score serving parameter artifact.") from error
