"""Immutable artifact records and a file-backed provenance registry.

The registry records *which bytes* a run consumed or produced.  It deliberately does
not parse those bytes or replace domain validation: snapshots, ledgers, measurements
and UI views keep their own stronger contracts.  This module only binds their file
location and SHA-256 checksum to a run, a role and a schema identity.
"""

import contextlib
import hashlib
import json
import os
import re
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Final, Literal

ARTIFACT_RECORD_CONTRACT_VERSION: Final = "artifact_record_v1"
ARTIFACT_RECORD_SCHEMA_PATH: Final = Path("docs") / "contracts" / "artifact_record_v1.schema.json"
ARTIFACT_RECORD_DIRECTORY: Final = "records"

ArtifactRole = Literal["input", "output"]

_IDENTIFIER_PATTERN: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_NAME_PATTERN: Final = re.compile(r"^[a-z][a-z0-9._-]{0,63}$")
_SHA256_PATTERN: Final = re.compile(r"^[0-9a-f]{64}$")
_ARTIFACT_ID_DIGEST_CHARACTERS: Final = 32
_CHECKSUM_CHUNK_SIZE: Final = 1024 * 1024


class ArtifactRecordError(ValueError):
    """An artifact record is malformed or contradicts its derived identity."""


class ArtifactRegistryError(RuntimeError):
    """A file-backed registry operation cannot be completed safely."""


class ArtifactNotFoundError(ArtifactRegistryError):
    """The requested artifact identity is not registered."""


class ArtifactIntegrityError(ArtifactRegistryError):
    """Registered artifact bytes no longer match their recorded checksum."""


def _require_identifier(value: object, *, label: str) -> str:
    if not isinstance(value, str) or not _IDENTIFIER_PATTERN.fullmatch(value):
        raise ArtifactRecordError(f"{label} has an invalid format: {value!r}.")
    return value


def _require_name(value: object, *, label: str) -> str:
    if not isinstance(value, str) or not _NAME_PATTERN.fullmatch(value):
        raise ArtifactRecordError(f"{label} has an invalid format: {value!r}.")
    return value


def _require_checksum(value: object) -> str:
    if not isinstance(value, str) or not _SHA256_PATTERN.fullmatch(value):
        raise ArtifactRecordError(f"checksum must be a lowercase SHA-256 digest, got {value!r}.")
    return value


def _normalize_utc_timestamp(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ArtifactRecordError("created_at_utc must be a non-empty ISO-8601 UTC timestamp.")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as error:
        raise ArtifactRecordError(
            f"created_at_utc must be an ISO-8601 UTC timestamp, got {value!r}."
        ) from error
    offset = parsed.utcoffset()
    if parsed.tzinfo is None or offset is None or offset.total_seconds() != 0.0:
        raise ArtifactRecordError(f"created_at_utc must state UTC explicitly, got {value!r}.")
    return parsed.isoformat().replace("+00:00", "Z")


def _normalize_location(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise ArtifactRecordError("location must be a non-empty relative POSIX path.")
    if "\\" in value or value.startswith("/") or re.match(r"^[A-Za-z]:", value):
        raise ArtifactRecordError(f"location must be a relative POSIX path, got {value!r}.")
    parts = value.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise ArtifactRecordError(
            f"location must be canonical and cannot traverse directories, got {value!r}."
        )
    normalized = PurePosixPath(value).as_posix()
    if normalized != value:
        raise ArtifactRecordError(f"location must use its canonical POSIX spelling, got {value!r}.")
    return normalized


def artifact_checksum(path: Path | str) -> str:
    """Return the SHA-256 digest of the raw bytes in one regular file."""

    source = Path(path)
    if not source.is_file():
        raise ArtifactRegistryError(f"Artifact file does not exist or is not regular: {source}.")
    digest = hashlib.sha256()
    with source.open("rb") as stream:
        while chunk := stream.read(_CHECKSUM_CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest()


def build_artifact_id(
    *,
    run_id: str,
    role: ArtifactRole,
    kind: str,
    location: str,
    checksum: str,
    schema_version: str,
) -> str:
    """Build the stable identity binding provenance metadata to artifact bytes."""

    validated_run_id = _require_identifier(run_id, label="run_id")
    if role not in {"input", "output"}:
        raise ArtifactRecordError(f"role must be 'input' or 'output', got {role!r}.")
    document = {
        "run_id": validated_run_id,
        "role": role,
        "kind": _require_name(kind, label="kind"),
        "location": _normalize_location(location),
        "checksum": _require_checksum(checksum),
        "schema_version": _require_name(schema_version, label="schema_version"),
    }
    encoded = json.dumps(document, sort_keys=True, separators=(",", ":")).encode("utf-8")
    digest = hashlib.sha256(encoded).hexdigest()
    return f"artifact-{digest[:_ARTIFACT_ID_DIGEST_CHARACTERS]}"


@dataclass(frozen=True, slots=True)
class ArtifactRecord:
    """Immutable provenance for one artifact consumed or produced by a run."""

    artifact_id: str
    run_id: str
    role: ArtifactRole
    kind: str
    location: str
    checksum: str
    schema_version: str
    created_at_utc: str
    contract_version: str = ARTIFACT_RECORD_CONTRACT_VERSION

    def __post_init__(self) -> None:
        if self.contract_version != ARTIFACT_RECORD_CONTRACT_VERSION:
            raise ArtifactRecordError(
                f"contract_version must be {ARTIFACT_RECORD_CONTRACT_VERSION!r}, "
                f"got {self.contract_version!r}."
            )
        object.__setattr__(
            self,
            "artifact_id",
            _require_identifier(self.artifact_id, label="artifact_id"),
        )
        object.__setattr__(self, "run_id", _require_identifier(self.run_id, label="run_id"))
        if self.role not in {"input", "output"}:
            raise ArtifactRecordError(f"role must be 'input' or 'output', got {self.role!r}.")
        object.__setattr__(self, "kind", _require_name(self.kind, label="kind"))
        object.__setattr__(self, "location", _normalize_location(self.location))
        object.__setattr__(self, "checksum", _require_checksum(self.checksum))
        object.__setattr__(
            self,
            "schema_version",
            _require_name(self.schema_version, label="schema_version"),
        )
        object.__setattr__(
            self,
            "created_at_utc",
            _normalize_utc_timestamp(self.created_at_utc),
        )
        expected_id = build_artifact_id(
            run_id=self.run_id,
            role=self.role,
            kind=self.kind,
            location=self.location,
            checksum=self.checksum,
            schema_version=self.schema_version,
        )
        if self.artifact_id != expected_id:
            raise ArtifactRecordError(
                f"artifact_id does not match the record identity: expected {expected_id!r}, "
                f"got {self.artifact_id!r}."
            )

    def to_dict(self) -> dict[str, object]:
        """Return the strict JSON-native ``artifact_record_v1`` document."""

        return {
            "contract_version": self.contract_version,
            "artifact_id": self.artifact_id,
            "run_id": self.run_id,
            "role": self.role,
            "kind": self.kind,
            "location": self.location,
            "checksum": self.checksum,
            "schema_version": self.schema_version,
            "created_at_utc": self.created_at_utc,
        }

    @classmethod
    def from_dict(cls, document: dict[str, object]) -> "ArtifactRecord":
        """Validate and rebuild one strict artifact record document."""

        expected_keys = {
            "contract_version",
            "artifact_id",
            "run_id",
            "role",
            "kind",
            "location",
            "checksum",
            "schema_version",
            "created_at_utc",
        }
        actual_keys = set(document)
        if actual_keys != expected_keys:
            missing = sorted(expected_keys - actual_keys)
            unexpected = sorted(actual_keys - expected_keys)
            raise ArtifactRecordError(
                f"Artifact record fields do not match {ARTIFACT_RECORD_CONTRACT_VERSION}: "
                f"missing={missing!r}, unexpected={unexpected!r}."
            )
        record = cls(
            contract_version=document["contract_version"],  # type: ignore[arg-type]
            artifact_id=document["artifact_id"],  # type: ignore[arg-type]
            run_id=document["run_id"],  # type: ignore[arg-type]
            role=document["role"],  # type: ignore[arg-type]
            kind=document["kind"],  # type: ignore[arg-type]
            location=document["location"],  # type: ignore[arg-type]
            checksum=document["checksum"],  # type: ignore[arg-type]
            schema_version=document["schema_version"],  # type: ignore[arg-type]
            created_at_utc=document["created_at_utc"],  # type: ignore[arg-type]
        )
        if document["created_at_utc"] != record.created_at_utc:
            raise ArtifactRecordError(
                "created_at_utc must use the canonical UTC spelling ending in Z."
            )
        return record


@dataclass(frozen=True, slots=True)
class ArtifactLineage:
    """The input and output artifact edges attached to one run."""

    run_id: str
    inputs: tuple[ArtifactRecord, ...]
    outputs: tuple[ArtifactRecord, ...]


def serialize_artifact_record(record: ArtifactRecord) -> bytes:
    """Return deterministic UTF-8 JSON bytes for an artifact record."""

    if not isinstance(record, ArtifactRecord):
        raise ArtifactRecordError("record must be an ArtifactRecord.")
    text = json.dumps(record.to_dict(), indent=2, sort_keys=True, ensure_ascii=False)
    return (text + "\n").encode("utf-8")


def parse_artifact_record(data: bytes | str) -> ArtifactRecord:
    """Parse and fully validate one serialized artifact record."""

    try:
        text = data.decode("utf-8") if isinstance(data, bytes) else data
    except UnicodeDecodeError as error:
        raise ArtifactRecordError("Artifact record is not valid UTF-8.") from error
    if not isinstance(text, str):
        raise ArtifactRecordError("Artifact record must be bytes or text.")
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as error:
        raise ArtifactRecordError(f"Artifact record is not valid JSON: {error}.") from error
    if not isinstance(parsed, dict):
        raise ArtifactRecordError("Artifact record must be a JSON object.")
    return ArtifactRecord.from_dict(parsed)


def artifact_record_schema() -> dict[str, object]:
    """Return the JSON Schema for ``artifact_record_v1``."""

    name_pattern = "^[a-z][a-z0-9._-]{0,63}$"
    identifier_pattern = "^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$"
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": (f"https://squadopt.dev/contracts/{ARTIFACT_RECORD_CONTRACT_VERSION}.schema.json"),
        "title": "SquadOpt artifact record",
        "description": "Immutable file provenance attached to one platform run.",
        "type": "object",
        "properties": {
            "contract_version": {
                "type": "string",
                "const": ARTIFACT_RECORD_CONTRACT_VERSION,
            },
            "artifact_id": {"type": "string", "pattern": identifier_pattern},
            "run_id": {"type": "string", "pattern": identifier_pattern},
            "role": {"type": "string", "enum": ["input", "output"]},
            "kind": {"type": "string", "pattern": name_pattern},
            "location": {
                "type": "string",
                "minLength": 1,
                "pattern": (
                    r"^(?!/)(?![A-Za-z]:)(?!.*(?:^|/)\.{1,2}(?:/|$))"
                    r"(?!.*\\)[^/]+(?:/[^/]+)*$"
                ),
            },
            "checksum": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
            "schema_version": {"type": "string", "pattern": name_pattern},
            "created_at_utc": {
                "type": "string",
                "format": "date-time",
                "pattern": "Z$",
            },
        },
        "required": [
            "artifact_id",
            "checksum",
            "contract_version",
            "created_at_utc",
            "kind",
            "location",
            "role",
            "run_id",
            "schema_version",
        ],
        "additionalProperties": False,
    }


def write_artifact_record_schema(path: Path | str | None = None) -> Path:
    """Write the deterministic schema document to ``path`` or its committed location."""

    target = Path(path) if path is not None else ARTIFACT_RECORD_SCHEMA_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(artifact_record_schema(), indent=2, sort_keys=True) + "\n"
    target.write_text(text, encoding="utf-8")
    return target


def _write_immutable(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}-{secrets.token_hex(4)}")
    try:
        temporary.write_bytes(payload)
        try:
            os.link(temporary, path)
        except FileExistsError:
            if path.read_bytes() != payload:
                raise ArtifactRegistryError(
                    f"Artifact record {path} already exists with different content."
                ) from None
    finally:
        with contextlib.suppress(FileNotFoundError):
            temporary.unlink()


class FileArtifactRegistry:
    """Immutable JSON records backed by a directory on the local filesystem.

    ``artifact_root`` is the portability and safety boundary for registered files.
    Locations are persisted relative to it using POSIX separators.  The metadata
    registry may therefore move together with its artifact tree without recording
    machine-specific absolute paths.
    """

    def __init__(
        self,
        root: Path | str,
        *,
        artifact_root: Path | str | None = None,
    ) -> None:
        self.root = Path(root).resolve()
        configured_artifact_root = (
            Path(artifact_root) if artifact_root is not None else self.root.parent
        )
        self.artifact_root = configured_artifact_root.resolve()

    @property
    def record_directory(self) -> Path:
        """Directory containing the immutable JSON record files."""

        return self.root / ARTIFACT_RECORD_DIRECTORY

    def _record_path(self, artifact_id: str) -> Path:
        validated = _require_identifier(artifact_id, label="artifact_id")
        return self.record_directory / f"{validated}.json"

    def _relative_location(self, path: Path | str) -> tuple[Path, str]:
        source = Path(path)
        try:
            resolved_source = source.resolve(strict=True)
        except FileNotFoundError as error:
            raise ArtifactRegistryError(f"Artifact file does not exist: {source}.") from error
        if not resolved_source.is_file():
            raise ArtifactRegistryError(f"Artifact path is not a regular file: {source}.")
        resolved_root = self.artifact_root.resolve()
        try:
            relative = resolved_source.relative_to(resolved_root)
        except ValueError as error:
            raise ArtifactRegistryError(
                f"Artifact {resolved_source} is outside artifact_root {resolved_root}."
            ) from error
        return resolved_source, relative.as_posix()

    def _resolve_location(self, location: str) -> Path:
        normalized = _normalize_location(location)
        root = self.artifact_root.resolve()
        candidate = (root / Path(PurePosixPath(normalized))).resolve()
        try:
            candidate.relative_to(root)
        except ValueError as error:
            raise ArtifactIntegrityError(
                f"Registered location {location!r} escapes artifact_root {root}."
            ) from error
        return candidate

    def register_artifact(
        self,
        path: Path | str,
        *,
        run_id: str,
        role: ArtifactRole,
        kind: str,
        schema_version: str,
        now: datetime | None = None,
    ) -> ArtifactRecord:
        """Register current file bytes, returning the existing record on an exact retry."""

        source, location = self._relative_location(path)
        checksum = artifact_checksum(source)
        artifact_id = build_artifact_id(
            run_id=run_id,
            role=role,
            kind=kind,
            location=location,
            checksum=checksum,
            schema_version=schema_version,
        )
        record_path = self._record_path(artifact_id)
        lineage = self.lineage(run_id)
        for existing in (*lineage.inputs, *lineage.outputs):
            same_slot = (
                existing.role == role and existing.kind == kind and existing.location == location
            )
            if not same_slot:
                continue
            if existing.artifact_id != artifact_id:
                raise ArtifactRegistryError(
                    f"Run {run_id!r} already registers {role} {kind!r} at {location!r} "
                    "with different bytes or schema. Artifact records are immutable."
                )
            self.verify_checksum(existing)
            return existing
        if record_path.exists():
            raise ArtifactRegistryError(
                f"Artifact record path {record_path} exists but is absent from run lineage."
            )

        moment = now or datetime.now(UTC)
        if not isinstance(moment, datetime):
            raise ArtifactRecordError("now must be a datetime.")
        offset = moment.utcoffset()
        if moment.tzinfo is None or offset is None or offset.total_seconds() != 0.0:
            raise ArtifactRecordError("now must be timezone-aware and expressed in UTC.")
        record = ArtifactRecord(
            artifact_id=artifact_id,
            run_id=run_id,
            role=role,
            kind=kind,
            location=location,
            checksum=checksum,
            schema_version=schema_version,
            created_at_utc=moment.isoformat().replace("+00:00", "Z"),
        )
        try:
            _write_immutable(record_path, serialize_artifact_record(record))
        except ArtifactRegistryError:
            # Another exact registration may have won the atomic link between our
            # lineage scan and publication. Its timestamp is operational metadata;
            # preserve the winner when every identity-bearing field is identical.
            existing = self.get_artifact(artifact_id)
            self.verify_checksum(existing)
            return existing
        return record

    def get_artifact(self, artifact_id: str) -> ArtifactRecord:
        """Load and validate a registered record without reading artifact bytes."""

        path = self._record_path(artifact_id)
        if not path.is_file():
            raise ArtifactNotFoundError(f"Artifact {artifact_id!r} is not registered at {path}.")
        try:
            record = parse_artifact_record(path.read_bytes())
        except (OSError, ArtifactRecordError) as error:
            raise ArtifactIntegrityError(f"Artifact record {path} is invalid: {error}") from error
        if record.artifact_id != artifact_id:
            raise ArtifactIntegrityError(
                f"Artifact record filename identifies {artifact_id!r} but contains "
                f"{record.artifact_id!r}."
            )
        return record

    def verify_checksum(self, artifact: str | ArtifactRecord) -> ArtifactRecord:
        """Verify registered bytes and return the validated record, otherwise raise."""

        if isinstance(artifact, str):
            record = self.get_artifact(artifact)
        elif isinstance(artifact, ArtifactRecord):
            record = self.get_artifact(artifact.artifact_id)
            if record != artifact:
                raise ArtifactIntegrityError(
                    f"Artifact record {artifact.artifact_id!r} differs from its registered record."
                )
        else:
            raise ArtifactRegistryError("artifact must be an artifact id or ArtifactRecord.")
        path = self._resolve_location(record.location)
        if not path.is_file():
            raise ArtifactIntegrityError(
                f"Artifact {record.artifact_id!r} records {path}, but the file is missing."
            )
        actual = artifact_checksum(path)
        if actual != record.checksum:
            raise ArtifactIntegrityError(
                f"Artifact {record.artifact_id!r} checksum mismatch: expected "
                f"{record.checksum!r}, computed {actual!r}."
            )
        return record

    def lineage(self, run_id: str, *, verify: bool = False) -> ArtifactLineage:
        """Return deterministic input and output edges for ``run_id``.

        Metadata is always validated.  ``verify=True`` additionally re-reads every
        artifact and checks its current bytes, which callers should use before a replay.
        """

        validated_run_id = _require_identifier(run_id, label="run_id")
        inputs: list[ArtifactRecord] = []
        outputs: list[ArtifactRecord] = []
        if self.record_directory.exists():
            for path in sorted(self.record_directory.glob("*.json")):
                artifact_id = path.stem
                record = self.get_artifact(artifact_id)
                if record.run_id != validated_run_id:
                    continue
                if verify:
                    self.verify_checksum(record)
                (inputs if record.role == "input" else outputs).append(record)

        def lineage_key(record: ArtifactRecord) -> tuple[str, str, str]:
            return (record.kind, record.location, record.artifact_id)

        return ArtifactLineage(
            run_id=validated_run_id,
            inputs=tuple(sorted(inputs, key=lineage_key)),
            outputs=tuple(sorted(outputs, key=lineage_key)),
        )
