"""Typed component predictions before the optimizer point-estimate hand-off."""

import hashlib
import json
import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from numbers import Integral, Real
from types import MappingProxyType
from typing import Final

import pandas as pd

from squadopt.data.errors import DataSourceError
from squadopt.data.timestamps import normalize_utc_timestamp
from squadopt.prediction.config import PredictionConfigurationError
from squadopt.prediction.integration import PredictionProvenance

COMPONENT_PREDICTION_CONTRACT_VERSION: Final = "component_prediction_v1"
COMPONENT_PREDICTION_INPUT_COLUMNS: Final = (
    "player_id",
    "fixture_count",
    "appearance_probability",
    "expected_minutes_if_appearance",
    "expected_points_if_appearance",
    "fallback_expected_points",
    "composition_route",
    "evidence_status",
)
COMPONENT_PREDICTION_OUTPUT_COLUMNS: Final = (
    *COMPONENT_PREDICTION_INPUT_COLUMNS,
    "start_probability",
    "expected_minutes",
    "expected_points",
)
COMPONENT_MODEL_ROUTE: Final = "component_model"
DIRECT_CONTROL_ROUTE: Final = "direct_control"
COMPONENT_PREDICTION_ROUTES: Final = (COMPONENT_MODEL_ROUTE, DIRECT_CONTROL_ROUTE)
EVIDENCE_NOT_REQUESTED: Final = "not_requested"
COMPONENT_EVIDENCE_STATUSES: Final = (EVIDENCE_NOT_REQUESTED,)
START_COMPONENT_UNAVAILABLE: Final = "unavailable"
_COMPONENT_VALUES: Final = (
    "appearance_probability",
    "expected_minutes_if_appearance",
    "expected_points_if_appearance",
)
_DERIVED_VALUES: Final = ("start_probability", "expected_minutes", "expected_points")


def _missing(value: object) -> bool:
    if value is None or value is pd.NA or value is pd.NaT:
        return True
    if isinstance(value, Decimal):
        return value.is_nan()
    return isinstance(value, Real) and not isinstance(value, bool) and math.isnan(float(value))


def _number(value: object, name: str, *, allow_negative: bool = False) -> float | None:
    if _missing(value):
        return None
    if isinstance(value, bool) or not isinstance(value, (Real, Decimal)):
        raise PredictionConfigurationError(f"{name} must be numeric or missing.")
    number = float(value)
    if not math.isfinite(number) or (number < 0.0 and not allow_negative):
        requirement = "finite" if allow_negative else "finite and non-negative"
        raise PredictionConfigurationError(f"{name} must be {requirement}.")
    return number


def _id_key(value: object) -> tuple[int, int | str]:
    if isinstance(value, Integral) and not isinstance(value, bool):
        return (0, int(value))
    return (1, str(value))


def _validate_ids(frame: pd.DataFrame) -> None:
    kinds: set[str] = set()
    for value in frame["player_id"].tolist():
        if isinstance(value, Integral) and not isinstance(value, bool):
            kinds.add("integer")
        elif isinstance(value, str) and value.strip():
            kinds.add("string")
        else:
            raise PredictionConfigurationError(
                "player_id values must be non-empty strings or integers."
            )
    if len(kinds) != 1:
        raise PredictionConfigurationError("player_id must use one consistent ID type.")
    repeated = frame.loc[frame["player_id"].duplicated(), "player_id"].tolist()
    if repeated:
        raise PredictionConfigurationError(f"Repeated player_id values: {repeated[:10]!r}.")


def _same_number(actual: object, expected: object) -> bool:
    if _missing(actual) or _missing(expected):
        return _missing(actual) and _missing(expected)
    return (
        not isinstance(actual, bool)
        and not isinstance(expected, bool)
        and isinstance(actual, (Real, Decimal))
        and isinstance(expected, (Real, Decimal))
        and math.isclose(float(actual), float(expected), rel_tol=0.0, abs_tol=1e-12)
    )


def _derived_values_match(value: pd.DataFrame, composed: pd.DataFrame) -> bool:
    if any(column not in value for column in _DERIVED_VALUES):
        return False
    actual = value.set_index("player_id")
    return all(
        _same_number(actual.at[row.player_id, column], getattr(row, column))
        for row in composed.itertuples(index=False)
        for column in _DERIVED_VALUES
    )


def _compose(value: object) -> pd.DataFrame:
    if not isinstance(value, pd.DataFrame):
        raise PredictionConfigurationError("components must be a pandas DataFrame.")
    duplicates = value.columns[value.columns.duplicated()].tolist()
    if duplicates:
        raise PredictionConfigurationError(f"Duplicate component columns: {duplicates[:10]!r}.")
    missing = [column for column in COMPONENT_PREDICTION_INPUT_COLUMNS if column not in value]
    if missing:
        raise PredictionConfigurationError(f"components is missing columns: {missing!r}.")
    frame = value.loc[:, list(COMPONENT_PREDICTION_INPUT_COLUMNS)].copy(deep=True)
    if frame.empty:
        raise PredictionConfigurationError("components must contain at least one player row.")
    _validate_ids(frame)
    start_output: list[float | None] = []
    minutes_output: list[float | None] = []
    points_output: list[float] = []

    for offset, row in enumerate(frame.to_dict("records")):
        count = row["fixture_count"]
        if isinstance(count, bool) or not isinstance(count, Integral) or int(count) < 0:
            raise PredictionConfigurationError(
                f"fixture_count must be a non-negative integer at row {offset}."
            )
        fixtures = int(count)
        frame.iat[offset, list(frame.columns).index("fixture_count")] = fixtures
        route, evidence = row["composition_route"], row["evidence_status"]
        if not isinstance(route, str) or route not in COMPONENT_PREDICTION_ROUTES:
            raise PredictionConfigurationError(
                f"composition_route must be one of {list(COMPONENT_PREDICTION_ROUTES)!r}."
            )
        if not isinstance(evidence, str) or evidence not in COMPONENT_EVIDENCE_STATUSES:
            raise PredictionConfigurationError(
                f"evidence_status must be one of {list(COMPONENT_EVIDENCE_STATUSES)!r}."
            )
        numbers = {
            "appearance_probability": _number(
                row["appearance_probability"], f"appearance_probability at row {offset}"
            ),
            "expected_minutes_if_appearance": _number(
                row["expected_minutes_if_appearance"],
                f"expected_minutes_if_appearance at row {offset}",
            ),
            "expected_points_if_appearance": _number(
                row["expected_points_if_appearance"],
                f"expected_points_if_appearance at row {offset}",
                allow_negative=True,
            ),
            "fallback_expected_points": _number(
                row["fallback_expected_points"], f"fallback_expected_points at row {offset}"
            ),
        }
        appearance = numbers["appearance_probability"]
        conditional_minutes = numbers["expected_minutes_if_appearance"]
        conditional_points = numbers["expected_points_if_appearance"]
        fallback = numbers["fallback_expected_points"]
        if route == COMPONENT_MODEL_ROUTE:
            if appearance is None or conditional_minutes is None or conditional_points is None:
                raise PredictionConfigurationError(
                    "component_model rows require appearance_probability and both "
                    "conditional means."
                )
            if appearance > 1.0:
                raise PredictionConfigurationError("Probabilities must lie in [0, 1].")
            if fallback is not None:
                raise PredictionConfigurationError(
                    "component_model rows must not carry fallback_expected_points."
                )
            if conditional_minutes > 90.0 * fixtures:
                raise PredictionConfigurationError(
                    "expected_minutes_if_appearance cannot exceed 90 * fixture_count."
                )
            start = None
            expected_minutes = appearance * conditional_minutes
            expected_points = appearance * conditional_points
            if expected_points < 0.0:
                raise PredictionConfigurationError(
                    "Composed expected_points must be non-negative at the optimizer boundary."
                )
        else:
            if fallback is None:
                raise PredictionConfigurationError(
                    "direct_control rows require fallback_expected_points."
                )
            if fixtures > 0 and any(numbers[column] is not None for column in _COMPONENT_VALUES):
                raise PredictionConfigurationError(
                    "direct_control rows must leave component numeric inputs missing."
                )
            start, expected_minutes, expected_points = None, None, fallback
        if fixtures == 0:
            present = [number for number in numbers.values() if number is not None]
            if any(number != 0.0 for number in present) or expected_points != 0.0:
                raise PredictionConfigurationError(
                    "A zero-fixture row must contain only zero-valued numeric predictions."
                )
            for column in _COMPONENT_VALUES:
                frame.iat[offset, list(frame.columns).index(column)] = 0.0
            start, expected_minutes, expected_points = 0.0, 0.0, 0.0
        start_output.append(start)
        minutes_output.append(expected_minutes)
        points_output.append(expected_points)

    frame["start_probability"] = pd.Series(start_output, index=frame.index, dtype="float64")
    frame["expected_minutes"] = pd.Series(minutes_output, index=frame.index, dtype="float64")
    frame["expected_points"] = pd.Series(points_output, index=frame.index, dtype="float64")
    return (
        frame.sort_values("player_id", kind="stable")
        .reset_index(drop=True)
        .loc[:, list(COMPONENT_PREDICTION_OUTPUT_COLUMNS)]
    )


def _canonical(value: object) -> str | None:
    if _missing(value):
        return None
    number = Decimal(str(value))
    return "0" if number == 0 else format(number.normalize(), "f")


def _fingerprint(table: pd.DataFrame, provenance: PredictionProvenance, timestamp: str) -> str:
    numeric = (
        "fixture_count",
        *_COMPONENT_VALUES,
        "fallback_expected_points",
        "start_probability",
        "expected_minutes",
        "expected_points",
    )
    rows = []
    for row in table.to_dict("records"):
        identifier = _id_key(row["player_id"])
        rows.append(
            {
                "player_id": {
                    "kind": "integer" if identifier[0] == 0 else "string",
                    "value": identifier[1],
                },
                **{column: _canonical(row[column]) for column in numeric},
                "composition_route": str(row["composition_route"]),
                "evidence_status": str(row["evidence_status"]),
            }
        )
    payload = {
        "contract_version": COMPONENT_PREDICTION_CONTRACT_VERSION,
        "decision_timestamp_utc": timestamp,
        "provenance_fingerprint": provenance.provenance_fingerprint,
        "rows": rows,
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _utc(value: str) -> str:
    try:
        return normalize_utc_timestamp(value, label="decision_timestamp_utc")
    except DataSourceError as error:
        raise PredictionConfigurationError(str(error)) from error


@dataclass(frozen=True, slots=True)
class ComponentPredictionSnapshot:
    """Validated component rows and producing-model identity."""

    table: pd.DataFrame
    provenance: PredictionProvenance
    decision_timestamp_utc: str
    component_fingerprint: str
    diagnostics: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.provenance, PredictionProvenance):
            raise PredictionConfigurationError("provenance must be a PredictionProvenance.")
        timestamp, table = _utc(self.decision_timestamp_utc), _compose(self.table)
        if not _derived_values_match(self.table, table):
            raise PredictionConfigurationError("Derived values do not match their components.")
        if self.component_fingerprint != _fingerprint(table, self.provenance, timestamp):
            raise PredictionConfigurationError("component_fingerprint does not match the snapshot.")
        if not isinstance(self.diagnostics, Mapping):
            raise PredictionConfigurationError("diagnostics must be a mapping.")
        object.__setattr__(self, "table", table)
        object.__setattr__(self, "decision_timestamp_utc", timestamp)
        object.__setattr__(self, "diagnostics", MappingProxyType(dict(self.diagnostics)))

    @property
    def contract_version(self) -> str:
        return COMPONENT_PREDICTION_CONTRACT_VERSION

    @property
    def start_component_status(self) -> str:
        """State the unavailable start-label branch without inventing a probability."""

        return START_COMPONENT_UNAVAILABLE

    def validated_copy(self) -> "ComponentPredictionSnapshot":
        """Revalidate mutable table state and return an independent copy."""

        return ComponentPredictionSnapshot(
            self.table,
            self.provenance,
            self.decision_timestamp_utc,
            self.component_fingerprint,
            self.diagnostics,
        )


def prepare_component_prediction(
    components: pd.DataFrame,
    provenance: PredictionProvenance,
    *,
    decision_timestamp_utc: str,
) -> ComponentPredictionSnapshot:
    """Validate and compose one deterministic component snapshot."""

    if not isinstance(provenance, PredictionProvenance):
        raise PredictionConfigurationError("provenance must be a PredictionProvenance.")
    timestamp, table = _utc(decision_timestamp_utc), _compose(components)
    fingerprint = _fingerprint(table, provenance, timestamp)
    routes, evidence = (
        table["composition_route"].value_counts(),
        table["evidence_status"].value_counts(),
    )
    diagnostics = {
        "contract_version": COMPONENT_PREDICTION_CONTRACT_VERSION,
        "player_count": len(table),
        "start_component_status": START_COMPONENT_UNAVAILABLE,
        **{f"route:{name}": int(routes.get(name, 0)) for name in COMPONENT_PREDICTION_ROUTES},
        **{f"evidence:{name}": int(evidence.get(name, 0)) for name in COMPONENT_EVIDENCE_STATUSES},
    }
    return ComponentPredictionSnapshot(table, provenance, timestamp, fingerprint, diagnostics)
