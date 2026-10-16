"""Compact phase inference bytes and receipts, with no file or source access.

An externally supplied SHA256 checks retained bytes, not their authenticity.
The original full training metadata digest is provenance, not a source audit.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field, fields
from types import MappingProxyType
from typing import Any, Final

import numpy as np

from squadopt.data.errors import DataError
from squadopt.data.timestamps import normalize_utc_timestamp
from squadopt.features.football_phase_inputs import (
    PHASE_DEFINITION_VERSION,
    PHASES,
    PhaseProjection,
    validate_phase_season,
)
from squadopt.prediction.football_phase_duties import (
    FEATURE_VERSION,
    MODEL_VERSION,
    PENALTY_MISS_POLICY,
    POSITION_FEATURES,
    RANK_FEATURES,
    Array,
    PhaseAllocatedPlayer,
    PhaseDutyModel,
    PhaseHeadMetadata,
    PhaseStateAllocation,
    _immutable_array,
    _phase_moments,
    _rank_field,
)

SERVING_CONTRACT: Final = "football_phase_serving_v1"
SERVING_RECEIPT: Final = "football_phase_serving_allocation_v1"
MAX_ARTIFACT_BYTES: Final = 65_536
_HEADS = ("goals", "assists")


@dataclass(frozen=True)
class PhaseServingMetadata:
    contract_version: str
    model_version: str
    feature_version: str
    fit_contract_version: str
    original_metadata_sha256: str
    observation_count: int
    cutoff: str
    target_season: str
    target_gameweek: int
    allowed_seasons: tuple[str, ...]
    phase_definition_version: str
    goal_events: int
    assist_events: int
    goal_status: str
    assist_status: str
    alpha: float
    max_iter: int
    recipient_heads: tuple[PhaseHeadMetadata, ...]
    released_2025_26: bool
    penalty_miss_treatment: str
    output_scope: str
    physical_check: str


@dataclass(frozen=True)
class PhaseServingReceipt:
    contract_version: str
    artifact_sha256: str
    original_metadata_sha256: str
    fit_contract_version: str
    cutoff: str
    target_season: str
    target_gameweek: int


@dataclass(frozen=True)
class PhaseServingAllocation:
    players: tuple[PhaseAllocatedPlayer, ...]
    states: tuple[PhaseStateAllocation, ...]
    goal_phase_shares: tuple[float, ...]
    assist_phase_shares: tuple[float, ...]
    total_goals: float
    total_assists: float
    physical_goal_mass: float
    projection_sha256: str
    model_version: str
    feature_version: str
    serving_receipt: PhaseServingReceipt


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _sha(value: object) -> str:
    if type(value) is not str or re.fullmatch(r"[a-f0-9]{64}", value) is None:
        raise ValueError("Phase serving requires an explicit lowercase SHA256.")
    return value


def _count(value: object, *, minimum: int = 0) -> int:
    if type(value) is not int or not minimum <= value <= 2**53:
        raise ValueError("Phase serving counts must be exact supported integers.")
    return value


def _finite(value: object) -> float:
    try:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("Phase serving numbers must be numeric, not boolean.")
        if not math.isfinite(float(value)):
            raise ValueError("Phase serving coefficients and hyperparameters must be finite.")
        return float(value)
    except OverflowError as error:
        raise ValueError("Phase serving number exceeds finite support.") from error


def _validate(metadata: PhaseServingMetadata) -> None:
    if type(metadata) is not PhaseServingMetadata:
        raise ValueError("Phase serving requires typed compact metadata.")
    if (
        metadata.contract_version != SERVING_CONTRACT
        or metadata.model_version != MODEL_VERSION
        or metadata.feature_version != FEATURE_VERSION
        or metadata.phase_definition_version != PHASE_DEFINITION_VERSION
        or metadata.fit_contract_version
        not in (
            "football_phase_duty_fit_v1",
            "football_phase_duty_replay_fit_v1",
            "football_phase_duty_fit_v2",
            "football_phase_duty_replay_fit_v2",
        )
        or metadata.penalty_miss_treatment != PENALTY_MISS_POLICY
        or metadata.output_scope != "separate_expected_scoring_marginals"
        or metadata.physical_check != "per_state_player_goals_plus_assists_not_above_physical_goals"
    ):
        raise ValueError("Unsupported phase serving version or scoring policy.")
    _sha(metadata.original_metadata_sha256)
    _count(metadata.observation_count, minimum=1)
    _count(metadata.max_iter, minimum=1)
    if _finite(metadata.alpha) < 0:
        raise ValueError("Phase serving alpha must be nonnegative.")
    if type(metadata.cutoff) is not str:
        raise ValueError("Phase serving cutoff must be an explicit timestamp.")
    try:
        normalize_utc_timestamp(metadata.cutoff, label="phase serving cutoff")
    except DataError as error:
        raise ValueError(
            "Phase serving cutoff must state an ISO timestamp and timezone."
        ) from error
    validate_phase_season(metadata.target_season)
    if metadata.target_season == "2025-26" or not 1 <= _count(metadata.target_gameweek) <= 38:
        raise ValueError("Phase serving requires an admitted target season and gameweek.")
    if type(metadata.released_2025_26) is not bool:
        raise ValueError("Phase serving release declaration must be an explicit boolean.")
    if (
        type(metadata.allowed_seasons) is not tuple
        or not metadata.allowed_seasons
        or any(type(season) is not str for season in metadata.allowed_seasons)
        or len(set(metadata.allowed_seasons)) != len(metadata.allowed_seasons)
    ):
        raise ValueError("Phase serving requires unique immutable allowed seasons.")
    legacy_fit = metadata.fit_contract_version.endswith("_v1")
    if (
        not legacy_fit
        and not metadata.released_2025_26
        and metadata.allowed_seasons == ("2025-26",)
    ):
        raise ValueError("Phase serving needs an observed season within its declared allowlist.")
    for season in metadata.allowed_seasons:
        validate_phase_season(season)
        if season > metadata.target_season or (
            legacy_fit and season == "2025-26" and not metadata.released_2025_26
        ):
            raise ValueError("Phase serving season release/window declarations disagree.")
    if metadata.released_2025_26 and (
        metadata.fit_contract_version
        != (
            "football_phase_duty_replay_fit_v1"
            if legacy_fit
            else "football_phase_duty_replay_fit_v2"
        )
        or (not legacy_fit and "2025-26" not in metadata.allowed_seasons)
    ):
        raise ValueError("Released phase fitting requires its explicit fit contract.")
    if type(metadata.recipient_heads) is not tuple or len(metadata.recipient_heads) > 10:
        raise ValueError("Phase serving requires immutable recipient heads.")
    keys = []
    counts = {head: 0 for head in _HEADS}
    for record in metadata.recipient_heads:
        if (
            type(record) is not PhaseHeadMetadata
            or record.head not in _HEADS
            or record.phase not in PHASES
        ):
            raise ValueError("Unknown phase serving recipient head.")
        keys.append((_HEADS.index(record.head), PHASES.index(record.phase)))
        expected = POSITION_FEATURES + (
            RANK_FEATURES if _rank_field(record.head, record.phase) else ()
        )
        if type(record.features) is not tuple or record.features != expected:
            raise ValueError("Phase serving recipient feature identity differs.")
        if type(record.coefficients) is not tuple or len(record.coefficients) != len(expected):
            raise ValueError("Phase serving recipient coefficient width differs.")
        for coefficient in record.coefficients:
            _finite(coefficient)
        events = _count(record.credited_events, minimum=1)
        groups = _count(record.fitting_groups, minimum=1)
        if groups > min(events, metadata.observation_count):
            raise ValueError("Phase serving fitting-group counts exceed their population.")
        counts[record.head] += events
    if keys != sorted(set(keys)):
        raise ValueError("Phase serving heads must be unique and in fitted order.")
    for head, total, status in (
        ("goals", metadata.goal_events, metadata.goal_status),
        ("assists", metadata.assist_events, metadata.assist_status),
    ):
        if _count(total) != counts[head] or status != (
            "fitted" if total else "unavailable_no_credited_events"
        ):
            raise ValueError("Phase serving head totals or availability status disagree.")


def _parameters(
    metadata: PhaseServingMetadata,
) -> tuple[Mapping[str, Array], Mapping[tuple[str, str], Array]]:
    counts = {head: np.zeros(len(PHASES), dtype=float) for head in _HEADS}
    coefficients = {}
    for record in metadata.recipient_heads:
        counts[record.head][PHASES.index(record.phase)] = record.credited_events
        coefficients[record.head, record.phase] = _immutable_array(
            np.asarray(record.coefficients, dtype=float)
        )
    shares = {
        head: _immutable_array(values / total if total else values)
        for head, values, total in (
            ("goals", counts["goals"], metadata.goal_events),
            ("assists", counts["assists"], metadata.assist_events),
        )
    }
    return MappingProxyType(shares), MappingProxyType(coefficients)


@dataclass(frozen=True)
class PhaseServingModel:
    metadata: PhaseServingMetadata
    artifact_sha256: str
    _phase_shares: Mapping[str, Array] = field(init=False, repr=False, compare=False)
    _coefficients: Mapping[tuple[str, str], Array] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        _validate(self.metadata)
        if hashlib.sha256(_canonical(asdict(self.metadata))).hexdigest() != _sha(
            self.artifact_sha256
        ):
            raise ValueError("Phase serving metadata differs from its retained artifact hash.")
        shares, coefficients = _parameters(self.metadata)
        object.__setattr__(self, "_phase_shares", shares)
        object.__setattr__(self, "_coefficients", coefficients)

    def predict(self, projection: PhaseProjection) -> PhaseServingAllocation:
        moments = _phase_moments(
            projection,
            cutoff=self.metadata.cutoff,
            target_season=self.metadata.target_season,
            target_gameweek=self.metadata.target_gameweek,
            phase_shares=self._phase_shares,
            coefficients=self._coefficients,
        )
        return PhaseServingAllocation(
            players=moments.players,
            states=moments.states,
            goal_phase_shares=moments.goal_phase_shares,
            assist_phase_shares=moments.assist_phase_shares,
            total_goals=moments.total_goals,
            total_assists=moments.total_assists,
            physical_goal_mass=moments.physical_goal_mass,
            projection_sha256=moments.projection_sha256,
            model_version=MODEL_VERSION,
            feature_version=FEATURE_VERSION,
            serving_receipt=PhaseServingReceipt(
                SERVING_RECEIPT,
                self.artifact_sha256,
                self.metadata.original_metadata_sha256,
                self.metadata.fit_contract_version,
                self.metadata.cutoff,
                self.metadata.target_season,
                self.metadata.target_gameweek,
            ),
        )


def export_phase_serving_model(model: PhaseDutyModel) -> bytes:
    """Export exact fitted parameters; the full metadata digest records provenance."""
    if not isinstance(model, PhaseDutyModel) or model._fitted is None:
        raise ValueError("Phase serving export requires an actual fitted phase model.")
    full = model.metadata
    if (
        len(full.training_receipts) != len(full.observation_sha256)
        or tuple(receipt.observation_sha256 for receipt in full.training_receipts)
        != full.observation_sha256
    ):
        raise ValueError("Phase fitting metadata lacks its original observation receipt binding.")
    values = asdict(full)
    original_sha = hashlib.sha256(_canonical(values)).hexdigest()
    del values["training_receipts"], values["observation_sha256"]
    values["fit_contract_version"] = values.pop("contract_version")
    values.update(
        contract_version=SERVING_CONTRACT,
        model_version=MODEL_VERSION,
        feature_version=FEATURE_VERSION,
        original_metadata_sha256=original_sha,
        observation_count=len(full.observation_sha256),
        recipient_heads=full.recipient_heads,
    )
    metadata = PhaseServingMetadata(**values)
    _validate(metadata)
    shares, coefficients = _parameters(metadata)
    if (
        shares.keys() != model._fitted.phase_shares.keys()
        or coefficients.keys() != model._fitted.coefficients.keys()
    ):
        raise ValueError("Phase fitted parameter keys differ from their metadata.")
    if any(
        not np.array_equal(value, model._fitted.phase_shares[key]) for key, value in shares.items()
    ) or any(
        not np.array_equal(value, model._fitted.coefficients[key])
        for key, value in coefficients.items()
    ):
        raise ValueError("Phase fitted parameters differ from their metadata.")
    return _canonical(asdict(metadata))


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Phase serving JSON repeats a field.")
        result[key] = value
    return result


def read_phase_serving_model(payload: bytes, *, expected_sha256: str) -> PhaseServingModel:
    """Restore canonical retained bytes; expected SHA integrity is not authenticity."""
    expected = _sha(expected_sha256)
    if type(payload) is not bytes or not 0 < len(payload) <= MAX_ARTIFACT_BYTES:
        raise ValueError("Phase serving requires bounded retained JSON bytes.")
    if hashlib.sha256(payload).hexdigest() != expected:
        raise ValueError("Phase serving artifact differs from the expected SHA256.")
    try:
        document = json.loads(payload, object_pairs_hook=_object)
        if type(document) is not dict or set(document) != {
            item.name for item in fields(PhaseServingMetadata)
        }:
            raise ValueError("Phase serving artifact fields differ from its contract.")
        if _canonical(document) != payload:
            raise ValueError("Phase serving artifact must use canonical JSON bytes.")
        if (
            type(document["allowed_seasons"]) is not list
            or type(document["recipient_heads"]) is not list
        ):
            raise ValueError("Phase serving seasons and recipient heads must be arrays.")
        heads = []
        for value in document["recipient_heads"]:
            if type(value) is not dict or set(value) != {
                item.name for item in fields(PhaseHeadMetadata)
            }:
                raise ValueError("Phase serving head fields differ from their contract.")
            if type(value["features"]) is not list or type(value["coefficients"]) is not list:
                raise ValueError("Phase serving features and coefficients must be arrays.")
            heads.append(
                PhaseHeadMetadata(
                    **{
                        **value,
                        "features": tuple(value["features"]),
                        "coefficients": tuple(value["coefficients"]),
                    }
                )
            )
        metadata = PhaseServingMetadata(
            **{
                **document,
                "allowed_seasons": tuple(document["allowed_seasons"]),
                "recipient_heads": tuple(heads),
            }
        )
        return PhaseServingModel(metadata, expected)
    except (TypeError, UnicodeError, OverflowError, RecursionError) as error:
        raise ValueError("Malformed phase serving artifact.") from error
