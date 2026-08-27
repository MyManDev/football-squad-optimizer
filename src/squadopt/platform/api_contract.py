"""Transport-neutral request and response contracts for the future HTTP API.

FastAPI will translate route parameters, headers and JSON bodies into these values.  The
contracts deliberately contain no framework types and no server filesystem paths.  Read
endpoints reuse ``ui_view_v1`` directly; this module owns only service metadata, normalized
commands, run results and errors.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final, Literal, Protocol, TypeAlias

BACKEND_API_CONTRACT_VERSION: Final = "backend_api_v1"
BACKEND_API_VERSION: Final = "v1"
BACKEND_API_SCHEMA_PATH: Final = Path("docs") / "contracts" / "backend_api_v1.schema.json"

ApiOperation: TypeAlias = Literal[
    "gameweek.decide", "gameweek.settle", "season.tick", "league.advise"
]
ApiRunStatus: TypeAlias = Literal["completed", "failed"]
JsonValue: TypeAlias = str | int | float | bool | list["JsonValue"] | dict[str, "JsonValue"] | None

_OPERATIONS: Final = frozenset(
    {"gameweek.decide", "gameweek.settle", "season.tick", "league.advise"}
)
_RUN_STATUSES: Final = frozenset({"completed", "failed"})
_IDENTIFIER_PATTERN: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_IDEMPOTENCY_PATTERN: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")
_SEASON_PATTERN: Final = re.compile(r"^[0-9]{4}-[0-9]{2}$")
_NAME_PATTERN: Final = re.compile(r"^[a-z][a-z0-9._-]{0,63}$")
_ERROR_CODE_PATTERN: Final = re.compile(r"^[A-Z][A-Z0-9_]{1,63}$")
_SHA256_PATTERN: Final = re.compile(r"^[0-9a-f]{64}$")


class BackendApiContractError(ValueError):
    """A value cannot be represented by ``backend_api_v1``."""


def _require_pattern(value: object, *, label: str, pattern: re.Pattern[str]) -> str:
    if not isinstance(value, str) or not pattern.fullmatch(value):
        raise BackendApiContractError(f"{label} has an invalid format: {value!r}.")
    return value


def _optional_pattern(
    value: object,
    *,
    label: str,
    pattern: re.Pattern[str],
) -> str | None:
    if value is None:
        return None
    return _require_pattern(value, label=label, pattern=pattern)


def _require_gameweek(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise BackendApiContractError("gameweek must be a positive integer.")
    return value


def _normalize_utc_timestamp(value: object, *, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise BackendApiContractError(f"{label} must be a non-empty ISO-8601 UTC timestamp.")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as error:
        raise BackendApiContractError(
            f"{label} must be an ISO-8601 UTC timestamp, got {value!r}."
        ) from error
    offset = parsed.utcoffset()
    if parsed.tzinfo is None or offset is None or offset.total_seconds() != 0.0:
        raise BackendApiContractError(f"{label} must state UTC explicitly, got {value!r}.")
    return parsed.isoformat().replace("+00:00", "Z")


def _json_value(value: object, *, label: str) -> JsonValue:
    if value is None or isinstance(value, bool | int | str):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise BackendApiContractError(f"{label} cannot contain non-finite numbers.")
        return value
    if isinstance(value, Mapping):
        result: dict[str, JsonValue] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise BackendApiContractError(f"{label} object keys must be strings.")
            result[key] = _json_value(item, label=f"{label}.{key}")
        return result
    if isinstance(value, list | tuple):
        return [_json_value(item, label=f"{label}[]") for item in value]
    raise BackendApiContractError(
        f"{label} must contain JSON-native values, got {type(value).__name__}."
    )


def _json_object(value: object, *, label: str) -> dict[str, JsonValue]:
    normalized = _json_value(value, label=label)
    if not isinstance(normalized, dict):
        raise BackendApiContractError(f"{label} must be a JSON object.")
    return normalized


@dataclass(frozen=True, slots=True)
class ApiCommandRequest:
    """One normalized write request after route/header/body values are combined.

    ``idempotency_key`` distinguishes client intent and is deliberately excluded from
    :attr:`request_fingerprint`. Reusing one key with a different fingerprint is a conflict;
    using another key for the same determining inputs is a distinct attempt with the same
    request identity.
    """

    operation: ApiOperation
    idempotency_key: str
    season: str | None = None
    gameweek: int | None = None
    snapshot_id: str | None = None
    projection_artifact_id: str | None = None
    chip: str | None = None
    mode: Literal["live", "replay"] | None = None
    dry_run: bool = False
    league_id: int | None = None
    entry_id: int | None = None
    strategy: str | None = None
    window: int | None = None
    rival_entry_id: int | None = None
    contract_version: str = BACKEND_API_CONTRACT_VERSION

    def __post_init__(self) -> None:
        if self.contract_version != BACKEND_API_CONTRACT_VERSION:
            raise BackendApiContractError(
                f"contract_version must be {BACKEND_API_CONTRACT_VERSION!r}."
            )
        if self.operation not in _OPERATIONS:
            raise BackendApiContractError(f"operation is not supported: {self.operation!r}.")
        object.__setattr__(
            self,
            "idempotency_key",
            _require_pattern(
                self.idempotency_key,
                label="idempotency_key",
                pattern=_IDEMPOTENCY_PATTERN,
            ),
        )
        object.__setattr__(
            self,
            "season",
            _optional_pattern(self.season, label="season", pattern=_SEASON_PATTERN),
        )
        if self.gameweek is not None:
            object.__setattr__(self, "gameweek", _require_gameweek(self.gameweek))
        object.__setattr__(
            self,
            "snapshot_id",
            _optional_pattern(
                self.snapshot_id,
                label="snapshot_id",
                pattern=_IDENTIFIER_PATTERN,
            ),
        )
        object.__setattr__(
            self,
            "projection_artifact_id",
            _optional_pattern(
                self.projection_artifact_id,
                label="projection_artifact_id",
                pattern=_IDENTIFIER_PATTERN,
            ),
        )
        object.__setattr__(
            self,
            "chip",
            _optional_pattern(self.chip, label="chip", pattern=_NAME_PATTERN),
        )
        if self.mode not in {None, "live", "replay"}:
            raise BackendApiContractError("mode must be 'live' or 'replay'.")
        if not isinstance(self.dry_run, bool):
            raise BackendApiContractError("dry_run must be boolean.")
        for name in ("league_id", "entry_id", "rival_entry_id"):
            value = getattr(self, name)
            if value is not None and (
                isinstance(value, bool) or not isinstance(value, int) or value < 1
            ):
                raise BackendApiContractError(f"{name} must be a positive integer.")
        object.__setattr__(
            self,
            "strategy",
            _optional_pattern(self.strategy, label="strategy", pattern=_NAME_PATTERN),
        )
        if self.window is not None and self.window not in {1, 3, 5}:
            raise BackendApiContractError("window must be 1, 3, or 5.")
        self._validate_shape()

    def _validate_shape(self) -> None:
        if self.operation != "league.advise" and any(
            value is not None
            for value in (
                self.league_id,
                self.entry_id,
                self.strategy,
                self.window,
                self.rival_entry_id,
            )
        ):
            raise BackendApiContractError(
                f"{self.operation} accepts no league, entry, strategy, window, or rival."
            )
        if self.operation == "league.advise":
            if (
                self.season is None
                or self.gameweek is None
                or self.league_id is None
                or self.entry_id is None
                or self.strategy is None
                or self.window is None
            ):
                raise BackendApiContractError(
                    "league.advise requires season, gameweek, league_id, entry_id, "
                    "strategy, and window."
                )
            if self.rival_entry_id is not None and self.rival_entry_id == self.entry_id:
                raise BackendApiContractError("rival_entry_id may not equal entry_id.")
            if (
                any(
                    value is not None
                    for value in (
                        self.snapshot_id,
                        self.projection_artifact_id,
                        self.chip,
                        self.mode,
                    )
                )
                or self.dry_run
            ):
                raise BackendApiContractError(
                    "league.advise accepts no snapshot, projection, chip, mode, or "
                    "dry_run; the server answers from the current capture."
                )
            return
        if self.operation == "gameweek.decide":
            if self.season is None or self.gameweek is None or self.mode is None:
                raise BackendApiContractError(
                    "gameweek.decide requires season, gameweek, and mode."
                )
            if self.dry_run:
                raise BackendApiContractError("dry_run belongs only to season.tick.")
            if self.mode == "replay" and self.snapshot_id is None:
                raise BackendApiContractError("replay mode requires snapshot_id.")
            return
        if self.operation == "gameweek.settle":
            if self.season is None or self.gameweek is None:
                raise BackendApiContractError("gameweek.settle requires season and gameweek.")
            if (
                any(
                    value is not None
                    for value in (self.projection_artifact_id, self.chip, self.mode)
                )
                or self.dry_run
            ):
                raise BackendApiContractError(
                    "gameweek.settle accepts no projection, chip, mode, or dry_run."
                )
            return
        if self.gameweek is not None or any(
            value is not None
            for value in (self.snapshot_id, self.projection_artifact_id, self.chip, self.mode)
        ):
            raise BackendApiContractError(
                "season.tick accepts only an optional season and dry_run."
            )

    def _fingerprint_payload(self) -> dict[str, JsonValue]:
        payload: dict[str, JsonValue] = {
            "contract_version": self.contract_version,
            "operation": self.operation,
            "season": self.season,
        }
        if self.operation == "gameweek.decide":
            payload.update(
                {
                    "gameweek": self.gameweek,
                    "snapshot_id": self.snapshot_id,
                    "projection_artifact_id": self.projection_artifact_id,
                    "chip": self.chip,
                    "mode": self.mode,
                }
            )
        elif self.operation == "gameweek.settle":
            payload.update({"gameweek": self.gameweek, "snapshot_id": self.snapshot_id})
        elif self.operation == "league.advise":
            payload.update(
                {
                    "gameweek": self.gameweek,
                    "league_id": self.league_id,
                    "entry_id": self.entry_id,
                    "strategy": self.strategy,
                    "window": self.window,
                    "rival_entry_id": self.rival_entry_id,
                }
            )
        else:
            payload["dry_run"] = self.dry_run
        return payload

    @property
    def request_fingerprint(self) -> str:
        encoded = json.dumps(
            self._fingerprint_payload(),
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            **self._fingerprint_payload(),
            "idempotency_key": self.idempotency_key,
            "request_fingerprint": self.request_fingerprint,
        }

    @classmethod
    def from_dict(cls, document: Mapping[str, object]) -> ApiCommandRequest:
        if not isinstance(document, Mapping):
            raise BackendApiContractError("API command must be a JSON object.")
        operation = document.get("operation")
        if operation not in _OPERATIONS:
            raise BackendApiContractError(f"operation is not supported: {operation!r}.")
        common = {
            "contract_version",
            "operation",
            "season",
            "idempotency_key",
            "request_fingerprint",
        }
        specific = {
            "gameweek.decide": {
                "gameweek",
                "snapshot_id",
                "projection_artifact_id",
                "chip",
                "mode",
            },
            "gameweek.settle": {"gameweek", "snapshot_id"},
            "season.tick": {"dry_run"},
            "league.advise": {
                "gameweek",
                "league_id",
                "entry_id",
                "strategy",
                "window",
                "rival_entry_id",
            },
        }[operation]
        expected = common | specific
        actual = set(document)
        if actual != expected:
            raise BackendApiContractError(
                "API command fields do not match its operation: "
                f"missing={sorted(expected - actual)!r}, "
                f"unexpected={sorted(actual - expected)!r}."
            )
        request = cls(
            contract_version=document["contract_version"],  # type: ignore[arg-type]
            operation=document["operation"],  # type: ignore[arg-type]
            idempotency_key=document["idempotency_key"],  # type: ignore[arg-type]
            season=document["season"],  # type: ignore[arg-type]
            gameweek=document.get("gameweek"),  # type: ignore[arg-type]
            snapshot_id=document.get("snapshot_id"),  # type: ignore[arg-type]
            projection_artifact_id=document.get("projection_artifact_id"),  # type: ignore[arg-type]
            chip=document.get("chip"),  # type: ignore[arg-type]
            mode=document.get("mode"),  # type: ignore[arg-type]
            dry_run=document.get("dry_run", False),  # type: ignore[arg-type]
            league_id=document.get("league_id"),  # type: ignore[arg-type]
            entry_id=document.get("entry_id"),  # type: ignore[arg-type]
            strategy=document.get("strategy"),  # type: ignore[arg-type]
            window=document.get("window"),  # type: ignore[arg-type]
            rival_entry_id=document.get("rival_entry_id"),  # type: ignore[arg-type]
        )
        if document["request_fingerprint"] != request.request_fingerprint:
            raise BackendApiContractError(
                "request_fingerprint does not match the normalized command."
            )
        return request


@dataclass(frozen=True, slots=True)
class ApiError:
    """Public failure detail; never an exception repr, traceback, or filesystem path."""

    code: str
    message: str
    run_id: str | None = None
    details: Mapping[str, JsonValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "code",
            _require_pattern(self.code, label="error code", pattern=_ERROR_CODE_PATTERN),
        )
        if not isinstance(self.message, str) or not self.message.strip():
            raise BackendApiContractError("error message must be non-empty text.")
        if self.message != self.message.strip():
            raise BackendApiContractError("error message cannot have surrounding whitespace.")
        object.__setattr__(
            self,
            "run_id",
            _optional_pattern(self.run_id, label="run_id", pattern=_IDENTIFIER_PATTERN),
        )
        object.__setattr__(
            self,
            "details",
            MappingProxyType(_json_object(self.details, label="error details")),
        )

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "code": self.code,
            "message": self.message,
            "run_id": self.run_id,
            "details": dict(self.details),
        }


@dataclass(frozen=True, slots=True)
class ApiRunResponse:
    """Terminal HTTP representation of one execution through ``RuntimeRunner``."""

    run_id: str
    operation: ApiOperation
    status: ApiRunStatus
    request_fingerprint: str
    reproducibility_fingerprint: str
    started_at_utc: str
    finished_at_utc: str
    runtime_seconds: float
    output_artifact_ids: tuple[str, ...] = ()
    result: Mapping[str, JsonValue] | None = None
    error: ApiError | None = None
    contract_version: str = BACKEND_API_CONTRACT_VERSION

    def __post_init__(self) -> None:
        if self.contract_version != BACKEND_API_CONTRACT_VERSION:
            raise BackendApiContractError(
                f"contract_version must be {BACKEND_API_CONTRACT_VERSION!r}."
            )
        object.__setattr__(
            self,
            "run_id",
            _require_pattern(self.run_id, label="run_id", pattern=_IDENTIFIER_PATTERN),
        )
        if self.operation not in _OPERATIONS:
            raise BackendApiContractError(f"operation is not supported: {self.operation!r}.")
        if self.status not in _RUN_STATUSES:
            raise BackendApiContractError(f"run status is not supported: {self.status!r}.")
        for name in ("request_fingerprint", "reproducibility_fingerprint"):
            object.__setattr__(
                self,
                name,
                _require_pattern(getattr(self, name), label=name, pattern=_SHA256_PATTERN),
            )
        object.__setattr__(
            self,
            "started_at_utc",
            _normalize_utc_timestamp(self.started_at_utc, label="started_at_utc"),
        )
        object.__setattr__(
            self,
            "finished_at_utc",
            _normalize_utc_timestamp(self.finished_at_utc, label="finished_at_utc"),
        )
        if (
            isinstance(self.runtime_seconds, bool)
            or not isinstance(self.runtime_seconds, int | float)
            or not math.isfinite(float(self.runtime_seconds))
            or self.runtime_seconds < 0
        ):
            raise BackendApiContractError("runtime_seconds must be a finite non-negative number.")
        outputs = tuple(
            _require_pattern(item, label="output_artifact_id", pattern=_IDENTIFIER_PATTERN)
            for item in self.output_artifact_ids
        )
        if len(outputs) != len(set(outputs)):
            raise BackendApiContractError("output_artifact_ids cannot contain duplicates.")
        object.__setattr__(self, "output_artifact_ids", outputs)
        if self.result is not None:
            object.__setattr__(
                self,
                "result",
                MappingProxyType(_json_object(self.result, label="run result")),
            )
        if self.status == "completed" and self.error is not None:
            raise BackendApiContractError("a completed run cannot contain an error.")
        if self.status == "failed":
            if self.result is not None or not isinstance(self.error, ApiError):
                raise BackendApiContractError("a failed run requires an error and no result.")
            if self.error.run_id != self.run_id:
                raise BackendApiContractError("a failed run error must carry the same run_id.")

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "contract_version": self.contract_version,
            "run_id": self.run_id,
            "operation": self.operation,
            "status": self.status,
            "request_fingerprint": self.request_fingerprint,
            "reproducibility_fingerprint": self.reproducibility_fingerprint,
            "started_at_utc": self.started_at_utc,
            "finished_at_utc": self.finished_at_utc,
            "runtime_seconds": float(self.runtime_seconds),
            "output_artifact_ids": list(self.output_artifact_ids),
            "result": None if self.result is None else dict(self.result),
            "error": None if self.error is None else self.error.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class ApiErrorResponse:
    """Error envelope for a request rejected before or outside a started run."""

    error: ApiError
    contract_version: str = BACKEND_API_CONTRACT_VERSION

    def __post_init__(self) -> None:
        if self.contract_version != BACKEND_API_CONTRACT_VERSION:
            raise BackendApiContractError(
                f"contract_version must be {BACKEND_API_CONTRACT_VERSION!r}."
            )
        if not isinstance(self.error, ApiError):
            raise BackendApiContractError("error must be an ApiError.")

    def to_dict(self) -> dict[str, JsonValue]:
        return {"contract_version": self.contract_version, "error": self.error.to_dict()}


@dataclass(frozen=True, slots=True)
class ApiServiceInfo:
    """Stable response shared by ``/health`` and ``/api/v1/info``."""

    service: str = "squadopt"
    status: str = "ok"
    api_version: str = BACKEND_API_VERSION
    contract_version: str = BACKEND_API_CONTRACT_VERSION

    def __post_init__(self) -> None:
        expected = ("squadopt", "ok", BACKEND_API_VERSION, BACKEND_API_CONTRACT_VERSION)
        if (self.service, self.status, self.api_version, self.contract_version) != expected:
            raise BackendApiContractError("service info constants cannot be overridden.")

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "contract_version": self.contract_version,
            "service": self.service,
            "status": self.status,
            "api_version": self.api_version,
        }


class ApiDocument(Protocol):
    def to_dict(self) -> dict[str, JsonValue]: ...


def serialize_api_document(document: ApiDocument) -> bytes:
    """Serialize one API document deterministically as UTF-8 JSON."""

    if not isinstance(
        document,
        ApiCommandRequest | ApiRunResponse | ApiErrorResponse | ApiServiceInfo,
    ):
        raise BackendApiContractError("document is not a backend API contract value.")
    return (
        json.dumps(document.to_dict(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    ).encode("utf-8")


def _nullable(schema: dict[str, Any]) -> dict[str, Any]:
    return {"anyOf": [schema, {"type": "null"}]}


def _object(properties: dict[str, Any], *, required: list[str] | None = None) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties) if required is None else required,
        "additionalProperties": False,
    }


def backend_api_schema() -> dict[str, Any]:
    """Return the strict JSON Schema for ``backend_api_v1`` wire documents."""

    identifier = {"type": "string", "pattern": _IDENTIFIER_PATTERN.pattern}
    nullable_identifier = _nullable(identifier)
    season = {"type": "string", "pattern": _SEASON_PATTERN.pattern}
    nullable_season = _nullable(season)
    fingerprint = {"type": "string", "pattern": _SHA256_PATTERN.pattern}
    version = {"type": "string", "const": BACKEND_API_CONTRACT_VERSION}
    idempotency = {"type": "string", "pattern": _IDEMPOTENCY_PATTERN.pattern}
    timestamp = {"type": "string", "format": "date-time", "pattern": "Z$"}
    json_object = {"type": "object", "additionalProperties": True}

    common_request = {
        "contract_version": version,
        "idempotency_key": idempotency,
        "request_fingerprint": fingerprint,
        "season": nullable_season,
    }
    decide = _object(
        {
            **common_request,
            "operation": {"type": "string", "const": "gameweek.decide"},
            "gameweek": {"type": "integer", "minimum": 1},
            "snapshot_id": nullable_identifier,
            "projection_artifact_id": nullable_identifier,
            "chip": _nullable({"type": "string", "pattern": _NAME_PATTERN.pattern}),
            "mode": {"type": "string", "enum": ["live", "replay"]},
        }
    )
    settle = _object(
        {
            **common_request,
            "operation": {"type": "string", "const": "gameweek.settle"},
            "gameweek": {"type": "integer", "minimum": 1},
            "snapshot_id": nullable_identifier,
        }
    )
    tick = _object(
        {
            **common_request,
            "operation": {"type": "string", "const": "season.tick"},
            "dry_run": {"type": "boolean"},
        }
    )
    advise = _object(
        {
            **common_request,
            "operation": {"type": "string", "const": "league.advise"},
            "gameweek": {"type": "integer", "minimum": 1},
            "league_id": {"type": "integer", "minimum": 1},
            "entry_id": {"type": "integer", "minimum": 1},
            "strategy": {"type": "string", "pattern": _NAME_PATTERN.pattern},
            "window": {"type": "integer", "enum": [1, 3, 5]},
            "rival_entry_id": _nullable({"type": "integer", "minimum": 1}),
        }
    )
    decide_body = _object(
        {
            "snapshot_id": nullable_identifier,
            "projection_artifact_id": nullable_identifier,
            "chip": _nullable({"type": "string", "pattern": _NAME_PATTERN.pattern}),
            "mode": {"type": "string", "enum": ["live", "replay"]},
        },
        required=["mode"],
    )
    settle_body = _object(
        {"snapshot_id": nullable_identifier},
        required=[],
    )
    tick_body = _object(
        {"dry_run": {"type": "boolean"}},
        required=[],
    )
    advise_body = _object(
        {
            "strategy": {"type": "string", "pattern": _NAME_PATTERN.pattern},
            "window": {"type": "integer", "enum": [1, 3, 5]},
            "rival_entry_id": _nullable({"type": "integer", "minimum": 1}),
        },
        required=["strategy", "window"],
    )
    error = _object(
        {
            "code": {"type": "string", "pattern": _ERROR_CODE_PATTERN.pattern},
            "message": {"type": "string", "minLength": 1},
            "run_id": nullable_identifier,
            "details": json_object,
        }
    )
    run = _object(
        {
            "contract_version": version,
            "run_id": identifier,
            "operation": {"type": "string", "enum": sorted(_OPERATIONS)},
            "status": {"type": "string", "enum": sorted(_RUN_STATUSES)},
            "request_fingerprint": fingerprint,
            "reproducibility_fingerprint": fingerprint,
            "started_at_utc": timestamp,
            "finished_at_utc": timestamp,
            "runtime_seconds": {"type": "number", "minimum": 0},
            "output_artifact_ids": {
                "type": "array",
                "items": identifier,
                "uniqueItems": True,
            },
            "result": _nullable(json_object),
            "error": _nullable({"$ref": "#/$defs/ApiError"}),
        }
    )
    run["allOf"] = [
        {
            "if": {"properties": {"status": {"const": "completed"}}},
            "then": {"properties": {"error": {"type": "null"}}},
        },
        {
            "if": {"properties": {"status": {"const": "failed"}}},
            "then": {
                "properties": {
                    "result": {"type": "null"},
                    "error": {"$ref": "#/$defs/ApiError"},
                }
            },
        },
    ]
    error_response = _object(
        {
            "contract_version": version,
            "error": {"$ref": "#/$defs/ApiError"},
        }
    )
    service_info = _object(
        {
            "contract_version": version,
            "service": {"type": "string", "const": "squadopt"},
            "status": {"type": "string", "const": "ok"},
            "api_version": {"type": "string", "const": BACKEND_API_VERSION},
        }
    )
    definitions = {
        "ApiCommandRequest": {
            "oneOf": [
                {"$ref": "#/$defs/DecideCommandRequest"},
                {"$ref": "#/$defs/SettleCommandRequest"},
                {"$ref": "#/$defs/TickCommandRequest"},
                {"$ref": "#/$defs/AdviseCommandRequest"},
            ]
        },
        "ApiError": error,
        "ApiErrorResponse": error_response,
        "ApiRunResponse": run,
        "ApiServiceInfo": service_info,
        "AdviseCommandRequest": advise,
        "AdviseRequestBody": advise_body,
        "DecideCommandRequest": decide,
        "DecideRequestBody": decide_body,
        "SettleCommandRequest": settle,
        "SettleRequestBody": settle_body,
        "TickCommandRequest": tick,
        "TickRequestBody": tick_body,
    }
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://squadopt.dev/contracts/backend_api_v1.schema.json",
        "title": "SquadOpt backend API contract",
        "description": (
            "Normalized commands and service/run/error responses. Read endpoints reuse "
            "ui_view_v1 without another envelope."
        ),
        "oneOf": [
            {"$ref": "#/$defs/ApiCommandRequest"},
            {"$ref": "#/$defs/ApiRunResponse"},
            {"$ref": "#/$defs/ApiErrorResponse"},
            {"$ref": "#/$defs/ApiServiceInfo"},
        ],
        "$defs": definitions,
    }


def write_backend_api_schema(path: Path | str | None = None) -> Path:
    target = Path(path) if path is not None else BACKEND_API_SCHEMA_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(backend_api_schema(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return target
