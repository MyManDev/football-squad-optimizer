"""The job lifecycle contract for queued advice work: ``backend_jobs_v1``.

``backend_api_v1`` is deliberately terminal — a run response is ``completed`` or
``failed``, and its own documentation says a future queue needs a *separately
versioned* job resource for ``queued`` and ``running`` rather than states added
speculatively. This module is that resource, and it exists **before** the queue
implementation: the lifecycle is the contract the queue must satisfy, not a
description of whatever the queue happened to do.

The lifecycle is a small machine and every edge is a rule:

- ``queued -> running``: a worker picked the job up.
- ``running -> completed``: the advice was computed and written to the cache; the job
  must say where (``result_ref``), because a completed job whose result cannot be
  found is indistinguishable from a failed one.
- ``running -> failed``: the job must say why (``error``), in ``ApiError`` shape.
- ``running -> queued``: the disposable-worker rule — a worker that dies mid-job
  leaves the record re-queueable, ``attempt`` incremented, and the retry is safe
  because cache writes are immutable-key, never overwrites.

Terminal states are terminal. There is no edge out of ``completed`` or ``failed``,
so a record cannot be laundered back into progress.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Final, Literal, TypeAlias

BACKEND_JOBS_CONTRACT_VERSION: Final = "backend_jobs_v1"

JobStatus: TypeAlias = Literal["queued", "running", "completed", "failed"]

_STATUSES: Final = frozenset({"queued", "running", "completed", "failed"})
_TERMINAL: Final = frozenset({"completed", "failed"})
_TRANSITIONS: Final[frozenset[tuple[str, str]]] = frozenset(
    {
        ("queued", "running"),
        ("running", "completed"),
        ("running", "failed"),
        ("running", "queued"),
    }
)
_JOB_ID_PATTERN: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_SHA256_PATTERN: Final = re.compile(r"^[0-9a-f]{64}$")
_ERROR_CODE_PATTERN: Final = re.compile(r"^[A-Z][A-Z0-9_]{1,63}$")


class BackendJobsContractError(ValueError):
    """A value or transition cannot be represented by ``backend_jobs_v1``."""


def _instant(value: str) -> datetime:
    """The parsed instant of an already-normalized UTC timestamp."""

    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _utc(value: object, *, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise BackendJobsContractError(f"{label} must be a non-empty ISO-8601 UTC timestamp.")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as error:
        raise BackendJobsContractError(
            f"{label} must be an ISO-8601 UTC timestamp, got {value!r}."
        ) from error
    offset = parsed.utcoffset()
    if parsed.tzinfo is None or offset is None or offset.total_seconds() != 0.0:
        raise BackendJobsContractError(f"{label} must state UTC explicitly, got {value!r}.")
    return parsed.isoformat().replace("+00:00", "Z")


@dataclass(frozen=True, slots=True)
class JobError:
    """Why a job failed, in the API's own error vocabulary."""

    code: str
    message: str

    def __post_init__(self) -> None:
        if not isinstance(self.code, str) or not _ERROR_CODE_PATTERN.fullmatch(self.code):
            raise BackendJobsContractError(f"error code has an invalid format: {self.code!r}.")
        if not isinstance(self.message, str) or not self.message.strip():
            raise BackendJobsContractError("error message must be non-empty text.")
        object.__setattr__(self, "message", self.message.strip())


@dataclass(frozen=True, slots=True)
class AdviceJob:
    """One queued advice computation's lifecycle record.

    Three identities travel with a job and they are deliberately distinct: the
    ``job_id`` names this record; the ``request_fingerprint`` names the normalized
    client request (idempotency reads it); the ``cache_key`` names the answer's
    address, which many requests may share. Conflating any two of them is how a
    cache ends up serving one member another member's plan.
    """

    job_id: str
    status: JobStatus
    request_fingerprint: str
    cache_key: str
    created_at_utc: str
    updated_at_utc: str
    attempt: int = 1
    idempotency_key: str | None = None
    result_ref: str | None = None
    error: JobError | None = None
    contract_version: str = BACKEND_JOBS_CONTRACT_VERSION

    def __post_init__(self) -> None:
        if self.contract_version != BACKEND_JOBS_CONTRACT_VERSION:
            raise BackendJobsContractError("Unsupported jobs contract_version.")
        if not isinstance(self.job_id, str) or not _JOB_ID_PATTERN.fullmatch(self.job_id):
            raise BackendJobsContractError(f"job_id has an invalid format: {self.job_id!r}.")
        if self.status not in _STATUSES:
            raise BackendJobsContractError(f"Unknown job status {self.status!r}.")
        for label, value in (
            ("request_fingerprint", self.request_fingerprint),
            ("cache_key", self.cache_key),
        ):
            if not isinstance(value, str) or not _SHA256_PATTERN.fullmatch(value):
                raise BackendJobsContractError(f"{label} must be a lowercase SHA-256 digest.")
        object.__setattr__(
            self, "created_at_utc", _utc(self.created_at_utc, label="created_at_utc")
        )
        object.__setattr__(
            self, "updated_at_utc", _utc(self.updated_at_utc, label="updated_at_utc")
        )
        # Compare instants, never strings: a later value that carries fractional
        # seconds sorts lexicographically before one that does not ('.' < 'Z').
        if _instant(self.updated_at_utc) < _instant(self.created_at_utc):
            raise BackendJobsContractError("updated_at_utc may not precede created_at_utc.")
        if isinstance(self.attempt, bool) or not isinstance(self.attempt, int) or self.attempt < 1:
            raise BackendJobsContractError("attempt must be a positive integer.")
        if self.idempotency_key is not None and (
            not isinstance(self.idempotency_key, str) or not self.idempotency_key.strip()
        ):
            raise BackendJobsContractError("idempotency_key must be None or non-empty text.")
        if self.result_ref is not None and (
            not isinstance(self.result_ref, str) or not _SHA256_PATTERN.fullmatch(self.result_ref)
        ):
            raise BackendJobsContractError("result_ref must be None or a lowercase SHA-256 digest.")
        if self.error is not None and not isinstance(self.error, JobError):
            raise BackendJobsContractError("error must be None or a JobError.")
        # State invariants: a completed job names its result and carries no error; a
        # failed job names its error and carries no result; open states carry neither.
        if self.status == "completed":
            if self.result_ref is None or self.error is not None:
                raise BackendJobsContractError(
                    "A completed job must carry result_ref and no error; a completed job "
                    "whose result cannot be found is indistinguishable from a failed one."
                )
        elif self.status == "failed":
            if self.error is None or self.result_ref is not None:
                raise BackendJobsContractError("A failed job must carry error and no result_ref.")
        elif self.result_ref is not None or self.error is not None:
            raise BackendJobsContractError(
                f"A {self.status} job may carry neither result_ref nor error."
            )

    @property
    def is_terminal(self) -> bool:
        return self.status in _TERMINAL

    def transition(
        self,
        to: JobStatus,
        *,
        at_utc: str,
        result_ref: str | None = None,
        error: JobError | None = None,
    ) -> AdviceJob:
        """Return the record after one legal lifecycle step; refuse everything else.

        ``running -> queued`` is the disposable-worker edge: the attempt count
        increments so a crash-looping job is visible as one, and nothing else about
        the record changes — the retry recomputes rather than trusting a half-done
        worker's leavings.
        """

        if (self.status, to) not in _TRANSITIONS:
            raise BackendJobsContractError(
                f"No edge {self.status!r} -> {to!r} in {BACKEND_JOBS_CONTRACT_VERSION}; "
                "terminal states are terminal."
            )
        stamped = _utc(at_utc, label="at_utc")
        if _instant(stamped) < _instant(self.updated_at_utc):
            raise BackendJobsContractError("A transition may not move time backwards.")
        return replace(
            self,
            status=to,
            updated_at_utc=stamped,
            attempt=self.attempt + 1 if to == "queued" else self.attempt,
            result_ref=result_ref,
            error=error,
        )

    def as_payload(self) -> dict[str, object]:
        """The record as JSON-native data, for the file-backed store and the API."""

        payload: dict[str, object] = {
            "contract_version": self.contract_version,
            "job_id": self.job_id,
            "status": self.status,
            "request_fingerprint": self.request_fingerprint,
            "cache_key": self.cache_key,
            "created_at_utc": self.created_at_utc,
            "updated_at_utc": self.updated_at_utc,
            "attempt": self.attempt,
            "idempotency_key": self.idempotency_key,
            "result_ref": self.result_ref,
            "error": (
                None
                if self.error is None
                else {"code": self.error.code, "message": self.error.message}
            ),
        }
        return payload

    @classmethod
    def from_payload(cls, payload: object) -> AdviceJob:
        """Rebuild a record from its payload; anything malformed is refused loudly.

        The parser enforces exactly what construction enforces — the same field set,
        the same types, no coercion — because a store or a wire that can smuggle an
        extra key or a stringified number past the boundary is a store the contract
        no longer describes.
        """

        if not isinstance(payload, dict):
            raise BackendJobsContractError("A job payload must be a JSON object.")
        expected = {
            "contract_version",
            "job_id",
            "status",
            "request_fingerprint",
            "cache_key",
            "created_at_utc",
            "updated_at_utc",
            "attempt",
            "idempotency_key",
            "result_ref",
            "error",
        }
        actual = set(payload)
        if actual != expected:
            raise BackendJobsContractError(
                "A job payload's fields do not match backend_jobs_v1: "
                f"missing={sorted(expected - actual)!r}, unexpected={sorted(actual - expected)!r}."
            )
        for name in (
            "contract_version",
            "job_id",
            "status",
            "request_fingerprint",
            "cache_key",
            "created_at_utc",
            "updated_at_utc",
        ):
            if not isinstance(payload[name], str):
                raise BackendJobsContractError(f"{name} must be a string.")
        if isinstance(payload["attempt"], bool) or not isinstance(payload["attempt"], int):
            raise BackendJobsContractError("attempt must be an integer.")
        for name in ("idempotency_key", "result_ref"):
            if payload[name] is not None and not isinstance(payload[name], str):
                raise BackendJobsContractError(f"{name} must be null or a string.")
        raw_error = payload["error"]
        error: JobError | None = None
        if raw_error is not None:
            if not isinstance(raw_error, dict) or set(raw_error) != {"code", "message"}:
                raise BackendJobsContractError("error must be null or {code, message}.")
            if not isinstance(raw_error["code"], str) or not isinstance(raw_error["message"], str):
                raise BackendJobsContractError("error code and message must be strings.")
            error = JobError(code=raw_error["code"], message=raw_error["message"])
        return cls(
            job_id=payload["job_id"],
            status=payload["status"],
            request_fingerprint=payload["request_fingerprint"],
            cache_key=payload["cache_key"],
            created_at_utc=payload["created_at_utc"],
            updated_at_utc=payload["updated_at_utc"],
            attempt=payload["attempt"],
            idempotency_key=payload["idempotency_key"],
            result_ref=payload["result_ref"],
            error=error,
            contract_version=payload["contract_version"],
        )


#: The whole machine, readable at a glance and importable by the queue and its tests.
ALLOWED_TRANSITIONS: Final[frozenset[tuple[str, str]]] = _TRANSITIONS

BACKEND_JOBS_SCHEMA_PATH: Final = Path("docs") / "contracts" / "backend_jobs_v1.schema.json"


def backend_jobs_schema() -> dict[str, object]:
    """The strict JSON Schema for one ``backend_jobs_v1`` record."""

    fingerprint = {"type": "string", "pattern": _SHA256_PATTERN.pattern}
    timestamp = {"type": "string", "format": "date-time", "pattern": "Z$"}
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://squadopt.dev/contracts/backend_jobs_v1.schema.json",
        "title": "SquadOpt advice job record",
        "type": "object",
        "properties": {
            "contract_version": {"type": "string", "const": BACKEND_JOBS_CONTRACT_VERSION},
            "job_id": {"type": "string", "pattern": _JOB_ID_PATTERN.pattern},
            "status": {"type": "string", "enum": sorted(_STATUSES)},
            "request_fingerprint": fingerprint,
            "cache_key": fingerprint,
            "created_at_utc": timestamp,
            "updated_at_utc": timestamp,
            "attempt": {"type": "integer", "minimum": 1},
            "idempotency_key": {"anyOf": [{"type": "string", "minLength": 1}, {"type": "null"}]},
            "result_ref": {"anyOf": [fingerprint, {"type": "null"}]},
            "error": {
                "anyOf": [
                    {
                        "type": "object",
                        "properties": {
                            "code": {"type": "string", "pattern": _ERROR_CODE_PATTERN.pattern},
                            "message": {"type": "string", "minLength": 1},
                        },
                        "required": ["code", "message"],
                        "additionalProperties": False,
                    },
                    {"type": "null"},
                ]
            },
        },
        "required": [
            "contract_version",
            "job_id",
            "status",
            "request_fingerprint",
            "cache_key",
            "created_at_utc",
            "updated_at_utc",
            "attempt",
            "idempotency_key",
            "result_ref",
            "error",
        ],
        "additionalProperties": False,
    }


def write_backend_jobs_schema(path: Path | str | None = None) -> Path:
    import json as _json

    target = Path(path) if path is not None else BACKEND_JOBS_SCHEMA_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        _json.dumps(backend_jobs_schema(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return target
