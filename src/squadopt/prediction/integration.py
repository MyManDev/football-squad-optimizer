"""Model-neutral hand-off from predicted points to the optimizer contract."""

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from numbers import Integral, Real
from types import MappingProxyType
from typing import Final

import pandas as pd

from squadopt.data.schema import POSITIONS, PROJECTION_REQUIRED_COLUMNS
from squadopt.optimization.coefficients import sort_players_by_id
from squadopt.prediction.config import PredictionConfigurationError

PREDICTION_TO_OPTIMIZATION_CONTRACT_VERSION: Final = "prediction_to_optimization_v1"
PREDICTION_VALUE_COLUMNS: Final = ("player_id", "expected_points")
_PLAYER_SNAPSHOT_COLUMNS: Final = (
    "player_id",
    "name",
    "team_id",
    "position",
    "price_tenths",
)


def _text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PredictionConfigurationError(f"{name} must be a non-empty string.")
    return value.strip()


def _digest(value: object, name: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise PredictionConfigurationError(
            f"{name} must be a lowercase 64-character SHA-256 digest."
        )
    return value


def _identifier_kind(value: object) -> str | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, Integral):
        return "integer"
    if isinstance(value, str) and value.strip():
        return "string"
    return None


def _validate_identifiers(frame: pd.DataFrame, column: str, label: str) -> str:
    kinds: set[str] = set()
    invalid: list[object] = []
    for value in frame[column].tolist():
        kind = _identifier_kind(value)
        if kind is None:
            invalid.append(value)
        else:
            kinds.add(kind)
    if invalid:
        raise PredictionConfigurationError(
            f"{label} {column} values must be non-empty strings or integers; "
            f"invalid examples: {invalid[:10]!r}."
        )
    if len(kinds) != 1:
        raise PredictionConfigurationError(
            f"{label} {column} must use one consistent ID type; found {sorted(kinds)!r}."
        )
    return next(iter(kinds))


def _frame(
    value: object,
    *,
    label: str,
    required_columns: tuple[str, ...],
) -> pd.DataFrame:
    if not isinstance(value, pd.DataFrame):
        raise PredictionConfigurationError(f"{label} must be a pandas DataFrame.")
    duplicates = value.columns[value.columns.duplicated()].tolist()
    if duplicates:
        raise PredictionConfigurationError(
            f"{label} contains duplicate columns: {duplicates[:10]!r}."
        )
    missing = [column for column in required_columns if column not in value.columns]
    if missing:
        raise PredictionConfigurationError(f"{label} is missing columns: {missing!r}.")
    selected = value.loc[:, list(required_columns)].copy(deep=True)
    if selected.empty:
        raise PredictionConfigurationError(f"{label} must contain at least one player row.")
    missing_values = [column for column in required_columns if bool(selected[column].isna().any())]
    if missing_values:
        raise PredictionConfigurationError(
            f"{label} contains missing values in columns: {missing_values!r}."
        )
    duplicate_ids = selected.loc[selected["player_id"].duplicated(), "player_id"].tolist()
    if duplicate_ids:
        raise PredictionConfigurationError(
            f"{label} contains duplicate player_id values: {duplicate_ids[:10]!r}."
        )
    return selected


def _expected_points(values: list[object], label: str) -> list[Decimal]:
    converted: list[Decimal] = []
    invalid: list[object] = []
    for value in values:
        if isinstance(value, bool) or not isinstance(value, (Real, Decimal)):
            invalid.append(value)
            continue
        try:
            number = Decimal(str(value))
        except (InvalidOperation, OverflowError, ValueError):
            invalid.append(value)
            continue
        if not number.is_finite() or number < 0:
            invalid.append(value)
            continue
        converted.append(number)
    if invalid:
        raise PredictionConfigurationError(
            f"{label} expected_points must be finite, numeric, and non-negative; "
            f"invalid examples: {invalid[:10]!r}."
        )
    return converted


def _validate_projection_table(table: object) -> pd.DataFrame:
    validated = _frame(
        table,
        label="Optimizer projection",
        required_columns=tuple(PROJECTION_REQUIRED_COLUMNS),
    )
    _validate_identifiers(validated, "player_id", "Optimizer projection")
    _validate_identifiers(validated, "team_id", "Optimizer projection")
    invalid_names = [
        value
        for value in validated["name"].tolist()
        if not isinstance(value, str) or not value.strip()
    ]
    if invalid_names:
        raise PredictionConfigurationError(
            "Optimizer projection name values must be non-empty strings; "
            f"invalid examples: {invalid_names[:10]!r}."
        )
    invalid_positions = [
        value for value in validated["position"].tolist() if value not in POSITIONS
    ]
    if invalid_positions:
        raise PredictionConfigurationError(
            f"Optimizer projection positions must be in {list(POSITIONS)!r}; "
            f"invalid examples: {invalid_positions[:10]!r}."
        )
    invalid_prices = [
        value
        for value in validated["price_tenths"].tolist()
        if isinstance(value, bool) or not isinstance(value, Integral) or int(value) < 0
    ]
    if invalid_prices:
        raise PredictionConfigurationError(
            "Optimizer projection price_tenths must contain non-negative integers; "
            f"invalid examples: {invalid_prices[:10]!r}."
        )
    _expected_points(validated["expected_points"].tolist(), "Optimizer projection")
    return sort_players_by_id(validated)


def _typed_identifier(value: object) -> dict[str, object]:
    if isinstance(value, Integral) and not isinstance(value, bool):
        return {"kind": "integer", "value": int(value)}
    return {"kind": "string", "value": str(value)}


@dataclass(frozen=True, slots=True)
class PredictionProvenance:
    """Versioned identity of the model and training state that produced predictions."""

    model_name: str
    model_version: str
    feature_contract_version: str
    training_cutoff: str
    training_data_fingerprint: str
    contract_version: str = PREDICTION_TO_OPTIMIZATION_CONTRACT_VERSION

    def __post_init__(self) -> None:
        if self.contract_version != PREDICTION_TO_OPTIMIZATION_CONTRACT_VERSION:
            raise PredictionConfigurationError(
                "contract_version must match the implemented prediction integration contract."
            )
        object.__setattr__(self, "model_name", _text(self.model_name, "model_name"))
        object.__setattr__(self, "model_version", _text(self.model_version, "model_version"))
        object.__setattr__(
            self,
            "feature_contract_version",
            _text(self.feature_contract_version, "feature_contract_version"),
        )
        object.__setattr__(
            self,
            "training_cutoff",
            _text(self.training_cutoff, "training_cutoff"),
        )
        object.__setattr__(
            self,
            "training_data_fingerprint",
            _digest(self.training_data_fingerprint, "training_data_fingerprint"),
        )

    @property
    def provenance_fingerprint(self) -> str:
        """Return a stable digest of the model and training provenance."""

        payload = {
            "contract_version": self.contract_version,
            "feature_contract_version": self.feature_contract_version,
            "model_name": self.model_name,
            "model_version": self.model_version,
            "training_cutoff": self.training_cutoff,
            "training_data_fingerprint": self.training_data_fingerprint,
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


def _prediction_fingerprint(table: pd.DataFrame, provenance: PredictionProvenance) -> str:
    rows: list[dict[str, object]] = []
    for row in sort_players_by_id(table).to_dict("records"):
        points = Decimal(str(row["expected_points"]))
        canonical_points = "0" if points == 0 else format(points.normalize(), "f")
        rows.append(
            {
                "player_id": _typed_identifier(row["player_id"]),
                "name": str(row["name"]),
                "team_id": _typed_identifier(row["team_id"]),
                "position": str(row["position"]),
                "price_tenths": int(row["price_tenths"]),
                "expected_points": canonical_points,
            }
        )
    payload = {
        "contract_version": provenance.contract_version,
        "provenance_fingerprint": provenance.provenance_fingerprint,
        "players": rows,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class PredictionSnapshot:
    """Independent optimizer-ready table with complete prediction provenance."""

    table: pd.DataFrame
    provenance: PredictionProvenance
    prediction_fingerprint: str
    diagnostics: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.provenance, PredictionProvenance):
            raise PredictionConfigurationError(
                "provenance must be a PredictionProvenance instance."
            )
        table = _validate_projection_table(self.table)
        fingerprint = _digest(self.prediction_fingerprint, "prediction_fingerprint")
        if fingerprint != _prediction_fingerprint(table, self.provenance):
            raise PredictionConfigurationError(
                "prediction_fingerprint does not match the table and provenance."
            )
        if not isinstance(self.diagnostics, Mapping):
            raise PredictionConfigurationError("diagnostics must be a mapping.")
        object.__setattr__(self, "table", table)
        object.__setattr__(self, "prediction_fingerprint", fingerprint)
        object.__setattr__(self, "diagnostics", MappingProxyType(dict(self.diagnostics)))

    def validated_copy(self) -> "PredictionSnapshot":
        """Revalidate mutable table state and return an independent snapshot copy."""

        return PredictionSnapshot(
            table=self.table,
            provenance=self.provenance,
            prediction_fingerprint=self.prediction_fingerprint,
            diagnostics=self.diagnostics,
        )


def prepare_optimizer_projection(
    player_snapshot: pd.DataFrame,
    predictions: pd.DataFrame,
    provenance: PredictionProvenance,
) -> PredictionSnapshot:
    """Exact-align external model predictions with deadline-known player fields."""

    if not isinstance(provenance, PredictionProvenance):
        raise PredictionConfigurationError("provenance must be a PredictionProvenance instance.")
    players = _frame(
        player_snapshot,
        label="Player snapshot",
        required_columns=_PLAYER_SNAPSHOT_COLUMNS,
    )
    predicted = _frame(
        predictions,
        label="Predictions",
        required_columns=PREDICTION_VALUE_COLUMNS,
    )
    player_kind = _validate_identifiers(players, "player_id", "Player snapshot")
    prediction_kind = _validate_identifiers(predicted, "player_id", "Predictions")
    if player_kind != prediction_kind:
        raise PredictionConfigurationError(
            "Player snapshot and predictions must use the same player_id type."
        )
    expected_ids = set(players["player_id"].tolist())
    observed_ids = set(predicted["player_id"].tolist())
    if expected_ids != observed_ids:
        missing = sorted(expected_ids - observed_ids, key=str)
        extra = sorted(observed_ids - expected_ids, key=str)
        raise PredictionConfigurationError(
            "Predictions must align exactly with the player snapshot; "
            f"missing={missing[:10]!r}, extra={extra[:10]!r}."
        )
    _expected_points(predicted["expected_points"].tolist(), "Predictions")

    table = players.merge(predicted, on="player_id", how="inner", validate="one_to_one")
    table = _validate_projection_table(table)
    fingerprint = _prediction_fingerprint(table, provenance)
    return PredictionSnapshot(
        table=table,
        provenance=provenance,
        prediction_fingerprint=fingerprint,
        diagnostics={
            "contract_version": provenance.contract_version,
            "provenance_fingerprint": provenance.provenance_fingerprint,
            "prediction_fingerprint": fingerprint,
            "player_count": len(table),
            "point_projection_changed": False,
        },
    )
