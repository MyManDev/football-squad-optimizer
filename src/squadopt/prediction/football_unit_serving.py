"""Pure compact v4 inference, distinct from the full training-receipt result.

The expected digest checks parameter bytes. The producer-supplied original fit
digest is provenance only; this loader does not authenticate training sources.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import asdict, dataclass, fields
from datetime import datetime
from typing import Any, Final

import numpy as np
from scipy.sparse import vstack

from squadopt.features.football_unit_inputs import (
    NumericAttributeSpec,
    UnitProjection,
    scope,
    utc_time,
)
from squadopt.prediction.football_unit_strength import (
    UNIT_ALL_UNOBSERVED_SEMANTICS,
    UNIT_PHYSICAL_EXPOSURE_POLICY,
    UNIT_PHYSICAL_FIT_VERSION,
    UNIT_PHYSICAL_PROJECTION,
    UNIT_POOLED_FEATURE_VERSION,
    UNIT_POOLED_IDENTITY_POLICY,
    UNIT_POOLED_MODEL_VERSION,
    UNIT_POOLED_OBJECTIVE,
    UNIT_POOLED_PRIOR,
    UNIT_POOLED_SCALING,
    UNIT_RESIDUAL_MISSINGNESS_SEMANTICS,
    UNIT_SOURCE_MISSINGNESS_POLICY,
    FootballUnitStrengthModel,
    UnitStateRate,
    _attribute_contract,
    _fingerprint,
    _projection_fingerprint,
    pooled_feature_columns,
    pooled_identity_columns,
    pooled_relative_features,
)

UNIT_SERVING_VERSION: Final = "football_unit_pooled_serving_v1"
UNIT_SERVING_RECEIPT_VERSION: Final = "football_unit_pooled_serving_result_v1"
MAX_ARTIFACT_BYTES: Final = 4 * 1024 * 1024
MAX_VOCABULARY: Final = 10_000
MAX_ATTRIBUTES: Final = 512
PROVENANCE_SCOPE: Final = "original fit digest supplied by producer; training sources not reaudited"
OUTPUT_SCOPE: Final = "paired whole-fixture means; independent of native focal minute law"


@dataclass(frozen=True)
class UnitServingAttribute:
    source_id: str
    name: str
    minimum: float
    maximum: float
    unit: str
    definition: str
    provider: str
    kind: str

    def spec(self) -> NumericAttributeSpec:
        return NumericAttributeSpec(
            self.name, self.source_id, self.minimum, self.maximum, self.unit, self.definition
        )


@dataclass(frozen=True)
class UnitServingMetadata:
    contract_version: str
    model_version: str
    feature_version: str
    fit_contract_version: str
    original_fit_sha256: str
    cutoff: str
    training_scopes: tuple[tuple[str, int], ...]
    allow_released_2025_26: bool
    attributes: tuple[UnitServingAttribute, ...]
    player_vocabulary: tuple[int, ...]
    feature_columns: tuple[str, ...]
    coefficients: tuple[float, ...]
    applied_scales: tuple[float, ...]
    training_scaler_scales: tuple[float, ...]
    alpha: float
    training_offset_sum: float
    raw_identity_count_prior_precision: float
    identity_policy: str
    missingness_policy: str
    exposure_policy: str
    scaling: str
    objective: str
    identity_prior: str
    all_unobserved_semantics: str
    residual_missingness_semantics: str
    projection_extrapolation: str
    output_scope: str
    provenance_scope: str
    fm_game_vintage: str


@dataclass(frozen=True)
class UnitServingReceipt:
    contract_version: str
    artifact_sha256: str
    original_fit_sha256: str
    model_version: str
    feature_version: str
    fit_cutoff: str
    projection_sha256: str
    catalog_sha256: str
    attribute_contract_sha256: str
    provenance_scope: str


@dataclass(frozen=True)
class UnitServingResult:
    fixture_id: int
    season: str
    gameweek: int
    decision_cutoff: datetime
    kickoff: datetime
    home: bool
    club: int
    opponent: int
    causal_baseline_own_goal_rate: float
    causal_baseline_opponent_goal_rate: float
    own_goal_rate: float
    opponent_goal_rate: float
    state_rates: tuple[UnitStateRate, ...]
    serving_receipt: UnitServingReceipt


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _sha(value: object) -> str:
    if type(value) is not str or re.fullmatch(r"[a-f0-9]{64}", value) is None:
        raise ValueError("Unit serving requires an explicit lowercase SHA256.")
    return value


def _finite(value: object, *, positive: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("Unit serving numbers must be numeric, not boolean.")
    try:
        number = float(value)
    except OverflowError as error:
        raise ValueError("Unit serving number exceeds finite support.") from error
    if not math.isfinite(number) or (positive and number <= 0):
        raise ValueError("Unit serving requires finite supported numbers and positive scales.")
    return number


def _timestamp(value: object) -> datetime:
    if type(value) is not str:
        raise ValueError("Unit serving cutoff must be an explicit ISO timestamp.")
    result = datetime.fromisoformat(value)
    utc_time(result, "unit serving cutoff")
    if result.isoformat() != value:
        raise ValueError("Unit serving cutoff must use canonical ISO format.")
    return result


def _validate(metadata: UnitServingMetadata) -> None:
    if type(metadata) is not UnitServingMetadata:
        raise ValueError("Unit serving requires its typed immutable metadata.")
    expected = {
        "contract_version": UNIT_SERVING_VERSION,
        "model_version": UNIT_POOLED_MODEL_VERSION,
        "feature_version": UNIT_POOLED_FEATURE_VERSION,
        "fit_contract_version": UNIT_PHYSICAL_FIT_VERSION,
        "identity_policy": UNIT_POOLED_IDENTITY_POLICY,
        "missingness_policy": UNIT_SOURCE_MISSINGNESS_POLICY,
        "exposure_policy": UNIT_PHYSICAL_EXPOSURE_POLICY,
        "scaling": UNIT_POOLED_SCALING,
        "objective": UNIT_POOLED_OBJECTIVE,
        "identity_prior": UNIT_POOLED_PRIOR,
        "all_unobserved_semantics": UNIT_ALL_UNOBSERVED_SEMANTICS,
        "residual_missingness_semantics": UNIT_RESIDUAL_MISSINGNESS_SEMANTICS,
        "projection_extrapolation": UNIT_PHYSICAL_PROJECTION,
        "output_scope": OUTPUT_SCOPE,
        "provenance_scope": PROVENANCE_SCOPE,
        "fm_game_vintage": "unknown",
    }
    if any(
        type(getattr(metadata, key)) is not str or getattr(metadata, key) != value
        for key, value in expected.items()
    ):
        raise ValueError("Unsupported unit serving version or semantics.")
    _sha(metadata.original_fit_sha256)
    _timestamp(metadata.cutoff)
    if type(metadata.allow_released_2025_26) is not bool:
        raise ValueError("Unit serving release declaration must be an explicit boolean.")
    if (
        type(metadata.training_scopes) is not tuple
        or not 1 <= len(metadata.training_scopes) <= 3800
    ):
        raise ValueError("Unit serving requires a bounded immutable training scope.")
    for item in metadata.training_scopes:
        if type(item) is not tuple or len(item) != 2:
            raise ValueError("Unit serving scopes require immutable season and gameweek pairs.")
        scope(*item, fixture_id=1)
        if item[0] == "2025-26" and not metadata.allow_released_2025_26:
            raise ValueError("Released training scope needs its explicit opt-in.")
    if metadata.training_scopes != tuple(sorted(set(metadata.training_scopes))):
        raise ValueError("Unit serving scopes must be sorted and unique.")
    vocabulary = metadata.player_vocabulary
    if type(vocabulary) is not tuple or not 1 <= len(vocabulary) <= MAX_VOCABULARY:
        raise ValueError("Unit serving requires a bounded immutable player vocabulary.")
    if any(type(value) is not int or not 0 < value <= 2**53 for value in vocabulary):
        raise ValueError("Unit serving player IDs must be positive exact integers.")
    if vocabulary != tuple(sorted(set(vocabulary))):
        raise ValueError("Unit serving player vocabulary must be sorted and unique.")
    if type(metadata.attributes) is not tuple or len(metadata.attributes) > MAX_ATTRIBUTES:
        raise ValueError("Unit serving requires bounded immutable attribute definitions.")
    keys = []
    families: dict[str, tuple[str, str]] = {}
    for record in metadata.attributes:
        if type(record) is not UnitServingAttribute:
            raise ValueError("Unit serving requires typed attribute source definitions.")
        record.spec()
        if (
            not isinstance(record.provider, str)
            or not record.provider.strip()
            or record.kind not in ("fm", "provider", "synthetic")
        ):
            raise ValueError("Unit serving attributes require source provider and kind.")
        key = (record.source_id, record.name)
        keys.append(key)
        family = record.provider, record.kind
        if families.setdefault(record.source_id, family) != family:
            raise ValueError(
                "One logical attribute source cannot have multiple provider identities."
            )
    if keys != sorted(set(keys)):
        raise ValueError("Unit serving attributes must be sorted and unique.")
    expected_columns = pooled_feature_columns(
        vocabulary, tuple(x.spec() for x in metadata.attributes)
    )
    if (
        type(metadata.feature_columns) is not tuple
        or metadata.feature_columns != expected_columns
        or len(set(expected_columns)) != len(expected_columns)
    ):
        raise ValueError("Unit serving feature identity differs from its exact encoder.")
    for vector in (metadata.coefficients, metadata.applied_scales, metadata.training_scaler_scales):
        if type(vector) is not tuple or len(vector) != len(expected_columns):
            raise ValueError("Unit serving parameter vectors must match the encoder width.")
    for value in metadata.coefficients:
        _finite(value)
    identities = set(pooled_identity_columns(vocabulary))
    for name, applied, observed in zip(
        expected_columns, metadata.applied_scales, metadata.training_scaler_scales, strict=True
    ):
        _finite(applied, positive=True)
        _finite(observed, positive=True)
        if applied != (1.0 if name in identities else observed):
            raise ValueError("Unit serving scales disagree with the fixed raw identity policy.")
    if _finite(metadata.alpha) != 0.1:
        raise ValueError("Unit serving preserves the fitted fixed alpha 0.1 policy.")
    total = _finite(metadata.training_offset_sum, positive=True)
    if (
        _finite(metadata.raw_identity_count_prior_precision, positive=True)
        != metadata.alpha * total
    ):
        raise ValueError("Unit serving prior precision disagrees with the normalized objective.")


@dataclass(frozen=True)
class UnitServingModel:
    metadata: UnitServingMetadata
    artifact_sha256: str

    def __post_init__(self) -> None:
        _validate(self.metadata)
        payload = _canonical(asdict(self.metadata))
        if len(payload) > MAX_ARTIFACT_BYTES or hashlib.sha256(payload).hexdigest() != _sha(
            self.artifact_sha256
        ):
            raise ValueError("Unit serving metadata differs from its bounded artifact bytes.")

    def predict(self, projection: UnitProjection) -> UnitServingResult:
        if type(projection) is not UnitProjection or projection.catalog.replay is not None:
            raise ValueError("Unit serving requires a current typed projection without replay.")
        metadata = self.metadata
        if _timestamp(metadata.cutoff) > projection.decision_cutoff:
            raise ValueError("Fitted unit model was unavailable at the projection cutoff.")
        if any(
            season > projection.season
            or (season == projection.season and week >= projection.gameweek)
            for season, week in metadata.training_scopes
        ):
            raise ValueError("Unit serving cannot train on the same or a future gameweek.")
        attributes = tuple(x.spec() for x in metadata.attributes)
        contract = tuple(
            (x.source_id, x.name, x.minimum, x.maximum, x.unit, x.definition, x.provider, x.kind)
            for x in metadata.attributes
        )
        if _attribute_contract(projection.catalog) != contract:
            raise ValueError("Current attribute definitions and source families differ from fit.")
        coefficients = np.asarray(metadata.coefficients, dtype=float)
        scales = np.asarray(metadata.applied_scales, dtype=float)
        states = sorted(
            projection.states,
            key=lambda x: (
                tuple((p.player_id, p.position) for p in x.own.players),
                tuple((p.player_id, p.position) for p in x.opponent.players),
            ),
        )
        rates = []
        for state in states:
            rows = tuple(
                pooled_relative_features(
                    projection.catalog,
                    own,
                    opponent,
                    reference_own,
                    reference_opponent,
                    home,
                    vocabulary=metadata.player_vocabulary,
                    attributes=attributes,
                )
                for own, opponent, reference_own, reference_opponent, home in (
                    (
                        state.own,
                        state.opponent,
                        projection.reference_own,
                        projection.reference_opponent,
                        projection.home,
                    ),
                    (
                        state.opponent,
                        state.own,
                        projection.reference_opponent,
                        projection.reference_own,
                        not projection.home,
                    ),
                )
            )
            standardized = vstack(rows, format="csr").multiply(1 / scales).tocsr()
            with np.errstate(over="ignore", under="ignore", invalid="ignore"):
                values = np.exp(standardized @ coefficients) * np.asarray(
                    [
                        projection.causal_baseline_own_goal_rate,
                        projection.causal_baseline_opponent_goal_rate,
                    ]
                )
            if not np.isfinite(values).all() or np.any(values <= 0):
                raise ValueError("Unit serving produced unsupported nonfinite or zero rates.")
            rates.append(
                UnitStateRate(
                    state.probability, float(values[0]), float(values[1]), state.own, state.opponent
                )
            )
        own_rate = math.fsum(x.probability * x.own_goal_rate for x in rates)
        other_rate = math.fsum(x.probability * x.opponent_goal_rate for x in rates)
        return UnitServingResult(
            projection.fixture_id,
            projection.season,
            projection.gameweek,
            projection.decision_cutoff,
            projection.kickoff,
            projection.home,
            projection.reference_own.club,
            projection.reference_opponent.club,
            projection.causal_baseline_own_goal_rate,
            projection.causal_baseline_opponent_goal_rate,
            own_rate,
            other_rate,
            tuple(rates),
            UnitServingReceipt(
                UNIT_SERVING_RECEIPT_VERSION,
                self.artifact_sha256,
                metadata.original_fit_sha256,
                metadata.model_version,
                metadata.feature_version,
                metadata.cutoff,
                _projection_fingerprint(projection),
                _fingerprint(projection.catalog),
                hashlib.sha256(_canonical(contract)).hexdigest(),
                PROVENANCE_SCOPE,
            ),
        )


def export_unit_serving_model(
    model: FootballUnitStrengthModel, *, original_fit_sha256: str
) -> bytes:
    """Export actual v4 parameters; the caller verifies original fit provenance."""
    if not isinstance(model, FootballUnitStrengthModel) or (
        model.model_version != UNIT_POOLED_MODEL_VERSION
        or model.feature_version != UNIT_POOLED_FEATURE_VERSION
        or getattr(model, "identity_policy", None) != UNIT_POOLED_IDENTITY_POLICY
        or getattr(model, "missingness_policy", None) != UNIT_SOURCE_MISSINGNESS_POLICY
        or getattr(model, "exposure_policy", None) != UNIT_PHYSICAL_EXPOSURE_POLICY
        or model._replay_metadata.get("fit_contract") != UNIT_PHYSICAL_FIT_VERSION
        or model.regularization != 0.1
        or model._head.alpha != 0.1
        or model._head.fit_intercept is not False
        or model._head.intercept_ != 0
    ):
        raise ValueError("Unit serving exports only the actual fitted v4 physical policy.")
    attributes = tuple(UnitServingAttribute(*item) for item in model._attribute_contract)
    if tuple(record.spec() for record in attributes) != model.attributes:
        raise ValueError("Fitted unit attribute definitions disagree with their source contract.")
    released = model._replay_metadata.get("allow_released_2025_26", False)
    if type(released) is not bool:
        raise ValueError("Fitted unit release declaration must be an explicit boolean.")
    metadata = UnitServingMetadata(
        UNIT_SERVING_VERSION,
        model.model_version,
        model.feature_version,
        UNIT_PHYSICAL_FIT_VERSION,
        _sha(original_fit_sha256),
        model.cutoff.isoformat(),
        tuple(sorted({(row.season, row.gameweek) for row in model._observations})),
        released,
        attributes,
        model.player_vocabulary,
        model.feature_contract,
        tuple(float(x) for x in model._head.coef_),
        tuple(float(x) for x in model._feature_scales),
        tuple(float(x) for x in model._scaler.scale_),
        model.regularization,
        model._training_offset_sum,
        model.regularization * model._training_offset_sum,
        UNIT_POOLED_IDENTITY_POLICY,
        UNIT_SOURCE_MISSINGNESS_POLICY,
        UNIT_PHYSICAL_EXPOSURE_POLICY,
        UNIT_POOLED_SCALING,
        UNIT_POOLED_OBJECTIVE,
        UNIT_POOLED_PRIOR,
        UNIT_ALL_UNOBSERVED_SEMANTICS,
        UNIT_RESIDUAL_MISSINGNESS_SEMANTICS,
        UNIT_PHYSICAL_PROJECTION,
        OUTPUT_SCOPE,
        PROVENANCE_SCOPE,
        "unknown",
    )
    _validate(metadata)
    payload = _canonical(asdict(metadata))
    if len(payload) > MAX_ARTIFACT_BYTES:
        raise ValueError("Unit serving artifact exceeds its transport bound.")
    return payload


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate unit serving JSON keys are forbidden.")
        result[key] = value
    return result


def _record(value: object, kind: type[Any]) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {x.name for x in fields(kind)}:
        raise ValueError("Unit serving JSON fields must match the exact contract.")
    return value


def read_unit_serving_model(payload: bytes, *, expected_sha256: str) -> UnitServingModel:
    """Read bounded canonical parameters without source IO or a training model."""
    if type(payload) is not bytes or not 0 < len(payload) <= MAX_ARTIFACT_BYTES:
        raise ValueError("Unit serving payload must be bounded nonempty bytes.")
    if hashlib.sha256(payload).hexdigest() != _sha(expected_sha256):
        raise ValueError("Unit serving bytes differ from the expected SHA256.")
    try:
        values = _record(json.loads(payload, object_pairs_hook=_object), UnitServingMetadata)
        for name in (
            "attributes",
            "training_scopes",
            "player_vocabulary",
            "feature_columns",
            "coefficients",
            "applied_scales",
            "training_scaler_scales",
        ):
            if type(values[name]) is not list:
                raise ValueError("Unit serving vector fields require JSON arrays.")
            values[name] = tuple(values[name])
        values["attributes"] = tuple(
            UnitServingAttribute(**_record(item, UnitServingAttribute))
            for item in values["attributes"]
        )
        if any(type(item) is not list for item in values["training_scopes"]):
            raise ValueError("Unit serving scopes require JSON array pairs.")
        values["training_scopes"] = tuple(tuple(item) for item in values["training_scopes"])
        metadata = UnitServingMetadata(**values)
        _validate(metadata)
        if _canonical(asdict(metadata)) != payload:
            raise ValueError("Unit serving JSON must use canonical serialization.")
        return UnitServingModel(metadata, expected_sha256)
    except (TypeError, KeyError, OverflowError, RecursionError, UnicodeError) as error:
        raise ValueError("Malformed unit serving artifact.") from error
