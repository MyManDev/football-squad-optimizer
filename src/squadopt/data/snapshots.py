"""Immutable on-disk store for pre-deadline captures of a live season.

A historical archive can be re-read at any time, so a backtest over it is
reproducible by construction. A live source cannot: the roster, prices and
availability it reports at a deadline are gone an hour later. Reproducing a
decision therefore means keeping the bytes that were visible when it was made.

This module is that store, and it is deliberately ignorant of what the bytes mean.
It accepts opaque payloads, records how and when they were obtained, and refuses to
hand them back unless they still match what was recorded. Parsing belongs to the
source adapter above it, and fetching belongs to a script outside the package, so
nothing here touches a network or a clock. Both are passed in, which is what makes
the store testable offline and its output deterministic.

Snapshots hold real third-party data and stay in a git-ignored directory. The
repository records that a capture happened, never its contents.
"""

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Final

from squadopt.data.errors import (
    DataSourceError,
    SnapshotExistsError,
    SnapshotIntegrityError,
    format_examples,
)
from squadopt.data.timestamps import as_instant, normalize_utc_timestamp

# Bumped only when the on-disk layout changes in a way an existing reader cannot
# interpret. It is part of the fingerprint, so a layout change can never silently
# reuse the identifier of a snapshot written under the old layout.
SNAPSHOT_SCHEMA_VERSION: Final = "snapshot_v1"

METADATA_FILENAME: Final = "metadata.json"
PAYLOAD_DIRECTORY: Final = "payloads"

# Source names and payload names both become path components, so they are validated
# rather than sanitised. Quietly rewriting a caller's name would make the identifier
# depend on a transformation nobody can see; rejecting it says so out loud, and it
# also closes the path-traversal case where a name contains a separator or "..".
_SOURCE_PATTERN: Final = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_PAYLOAD_NAME_PATTERN: Final = re.compile(r"^[a-z0-9]+(?:[-_.][a-z0-9]+)*$")

# The identifier carries a readable timestamp so a directory listing sorts into
# capture order, and a digest prefix so two captures inside the same second stay
# distinct. Integrity does not rest on this prefix: the full digest lives in the
# metadata and is recomputed on every read.
_ID_TIMESTAMP_FORMAT: Final = "%Y%m%dT%H%M%SZ"
_ID_DIGEST_CHARACTERS: Final = 12


@dataclass(frozen=True, slots=True)
class SnapshotMetadata:
    """What was captured, from where, and when.

    ``fingerprint`` covers the source, the capture time, the schema version and every
    payload checksum. Recomputing it on read is what turns "these files are on disk"
    into "these are the bytes that were captured".
    """

    snapshot_id: str
    source: str
    captured_at_utc: str
    schema_version: str
    checksums: Mapping[str, str]
    fingerprint: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "checksums", MappingProxyType(dict(self.checksums)))


@dataclass(frozen=True, slots=True)
class CapturedSnapshot:
    """A verified snapshot: its metadata and the payload bytes it recorded."""

    metadata: SnapshotMetadata
    payloads: Mapping[str, bytes]

    def __post_init__(self) -> None:
        object.__setattr__(self, "payloads", MappingProxyType(dict(self.payloads)))


def payload_checksum(content: bytes) -> str:
    """Return the SHA-256 digest of one raw payload."""

    return hashlib.sha256(content).hexdigest()


def normalize_captured_at(value: str) -> str:
    """Return the canonical UTC spelling of a capture timestamp.

    The capture time is not decoration. Availability is only usable as an inference
    rule because we can show the capture preceded the deadline, and that argument is
    worthless if the timestamp is ambiguous. A naive timestamp or a non-UTC offset is
    therefore rejected instead of being assumed to mean UTC.

    Whatever precision the caller supplies is preserved. Truncating to whole seconds
    would silently merge two distinct captures.
    """

    return normalize_utc_timestamp(value, label="captured_at_utc")


def snapshot_fingerprint(
    *,
    source: str,
    captured_at_utc: str,
    schema_version: str,
    checksums: Mapping[str, str],
) -> str:
    """Return the digest binding a capture's provenance to its contents.

    Serialisation is sorted and separator-fixed so the digest depends on the values
    and not on dictionary ordering or formatting choices.
    """

    document = json.dumps(
        {
            "source": source,
            "captured_at_utc": captured_at_utc,
            "schema_version": schema_version,
            "checksums": dict(sorted(checksums.items())),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(document.encode("utf-8")).hexdigest()


def build_snapshot_id(*, source: str, captured_at_utc: str, fingerprint: str) -> str:
    """Return the directory-safe identifier for a capture."""

    stamp = as_instant(captured_at_utc).strftime(_ID_TIMESTAMP_FORMAT)
    return f"{source}-{stamp}-{fingerprint[:_ID_DIGEST_CHARACTERS]}"


def _require_source(source: str) -> str:
    if not isinstance(source, str) or not _SOURCE_PATTERN.match(source):
        raise DataSourceError(
            f"source must be a lowercase hyphenated identifier such as 'fpl-live', got {source!r}."
        )
    return source


def _require_payloads(payloads: Mapping[str, bytes]) -> Mapping[str, bytes]:
    if not isinstance(payloads, Mapping) or not payloads:
        raise DataSourceError("A snapshot must carry at least one named payload.")
    invalid_names = [name for name in payloads if not _PAYLOAD_NAME_PATTERN.match(str(name))]
    if invalid_names:
        raise DataSourceError(
            "Payload names must be lowercase, and may contain only digits, hyphens, "
            f"underscores and dots: {format_examples(invalid_names)}."
        )
    non_bytes = [name for name, content in payloads.items() if not isinstance(content, bytes)]
    if non_bytes:
        raise DataSourceError(
            f"Payload contents must be raw bytes, not decoded text: {format_examples(non_bytes)}."
        )
    return payloads


def write_snapshot(
    root: Path | str,
    *,
    source: str,
    captured_at_utc: str,
    payloads: Mapping[str, bytes],
    schema_version: str = SNAPSHOT_SCHEMA_VERSION,
) -> SnapshotMetadata:
    """Write one capture and return its metadata.

    The write refuses to touch an existing snapshot directory. A capture is a record
    of what the world looked like at a moment, and a store that lets a record be
    rewritten cannot be used to defend a past decision.

    Metadata is written last. A capture interrupted midway therefore leaves a
    directory with no metadata, which reads as incomplete rather than as a snapshot
    whose payloads happen to be truncated.
    """

    validated_source = _require_source(source)
    validated_payloads = _require_payloads(payloads)
    captured_at = normalize_captured_at(captured_at_utc)

    checksums = {name: payload_checksum(content) for name, content in validated_payloads.items()}
    fingerprint = snapshot_fingerprint(
        source=validated_source,
        captured_at_utc=captured_at,
        schema_version=schema_version,
        checksums=checksums,
    )
    identifier = build_snapshot_id(
        source=validated_source,
        captured_at_utc=captured_at,
        fingerprint=fingerprint,
    )

    directory = Path(root) / identifier
    if directory.exists():
        raise SnapshotExistsError(
            f"Snapshot {identifier!r} already exists at {directory}. A capture is never "
            "overwritten; capture again to produce a new snapshot."
        )

    payload_directory = directory / PAYLOAD_DIRECTORY
    payload_directory.mkdir(parents=True)
    for name in sorted(validated_payloads):
        (payload_directory / name).write_bytes(validated_payloads[name])

    metadata = SnapshotMetadata(
        snapshot_id=identifier,
        source=validated_source,
        captured_at_utc=captured_at,
        schema_version=schema_version,
        checksums=checksums,
        fingerprint=fingerprint,
    )
    _write_metadata(directory / METADATA_FILENAME, metadata)
    return metadata


def _write_metadata(path: Path, metadata: SnapshotMetadata) -> None:
    document = {
        "snapshot_id": metadata.snapshot_id,
        "source": metadata.source,
        "captured_at_utc": metadata.captured_at_utc,
        "schema_version": metadata.schema_version,
        "checksums": dict(sorted(metadata.checksums.items())),
        "fingerprint": metadata.fingerprint,
    }
    path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _require_text(document: Mapping[str, object], key: str, path: Path) -> str:
    value = document.get(key)
    if not isinstance(value, str) or not value:
        raise SnapshotIntegrityError(
            f"Snapshot metadata at {path} is missing a text {key!r}, got {value!r}."
        )
    return value


def _require_checksums(document: Mapping[str, object], path: Path) -> dict[str, str]:
    value = document.get("checksums")
    if not isinstance(value, dict) or not value:
        raise SnapshotIntegrityError(
            f"Snapshot metadata at {path} is missing a non-empty 'checksums' mapping."
        )
    invalid = [name for name, digest in value.items() if not isinstance(digest, str)]
    if invalid:
        raise SnapshotIntegrityError(
            f"Snapshot metadata at {path} has non-text checksums: {format_examples(invalid)}."
        )
    return {str(name): str(digest) for name, digest in value.items()}


def read_snapshot(root: Path | str, snapshot_id: str) -> CapturedSnapshot:
    """Load one capture, verifying that it still matches what was recorded.

    Three things are checked, because they fail in three different ways: each payload
    against its own checksum, the recorded fingerprint against a fingerprint
    recomputed from the metadata, and the identifier against one rebuilt from the
    metadata. The first catches edited payloads, the second catches edited provenance,
    and the third catches a snapshot moved into another snapshot's directory.
    """

    directory = Path(root) / snapshot_id
    metadata_path = directory / METADATA_FILENAME
    if not metadata_path.is_file():
        raise DataSourceError(
            f"No snapshot metadata at {metadata_path}. Expected a snapshot directory named "
            f"{snapshot_id!r} containing {METADATA_FILENAME}."
        )

    try:
        parsed = json.loads(metadata_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise SnapshotIntegrityError(
            f"Snapshot metadata at {metadata_path} is not valid JSON: {error}"
        ) from error
    if not isinstance(parsed, dict):
        raise SnapshotIntegrityError(
            f"Snapshot metadata at {metadata_path} must be a JSON object, got {type(parsed)!r}."
        )

    document: Mapping[str, object] = parsed
    recorded_checksums = _require_checksums(document, metadata_path)
    metadata = SnapshotMetadata(
        snapshot_id=_require_text(document, "snapshot_id", metadata_path),
        source=_require_text(document, "source", metadata_path),
        captured_at_utc=_require_text(document, "captured_at_utc", metadata_path),
        schema_version=_require_text(document, "schema_version", metadata_path),
        checksums=recorded_checksums,
        fingerprint=_require_text(document, "fingerprint", metadata_path),
    )

    payloads: dict[str, bytes] = {}
    payload_directory = directory / PAYLOAD_DIRECTORY
    for name in sorted(recorded_checksums):
        payload_path = payload_directory / name
        if not payload_path.is_file():
            raise SnapshotIntegrityError(
                f"Snapshot {snapshot_id!r} records payload {name!r} but {payload_path} is missing."
            )
        content = payload_path.read_bytes()
        actual = payload_checksum(content)
        if actual != recorded_checksums[name]:
            raise SnapshotIntegrityError(
                f"Payload {name!r} in snapshot {snapshot_id!r} does not match its recorded "
                f"checksum: expected {recorded_checksums[name]!r}, computed {actual!r}."
            )
        payloads[name] = content

    unexpected = sorted(
        entry.name
        for entry in payload_directory.iterdir()
        if entry.is_file() and entry.name not in recorded_checksums
    )
    if unexpected:
        raise SnapshotIntegrityError(
            f"Snapshot {snapshot_id!r} contains payloads its metadata does not record: "
            f"{format_examples(unexpected)}."
        )

    expected_fingerprint = snapshot_fingerprint(
        source=metadata.source,
        captured_at_utc=metadata.captured_at_utc,
        schema_version=metadata.schema_version,
        checksums=metadata.checksums,
    )
    if metadata.fingerprint != expected_fingerprint:
        raise SnapshotIntegrityError(
            f"Snapshot {snapshot_id!r} records fingerprint {metadata.fingerprint!r} but its "
            f"metadata fingerprints to {expected_fingerprint!r}."
        )

    expected_id = build_snapshot_id(
        source=metadata.source,
        captured_at_utc=metadata.captured_at_utc,
        fingerprint=metadata.fingerprint,
    )
    if metadata.snapshot_id != expected_id or metadata.snapshot_id != snapshot_id:
        raise SnapshotIntegrityError(
            f"Snapshot directory {snapshot_id!r} holds metadata identifying itself as "
            f"{metadata.snapshot_id!r}, which rebuilds to {expected_id!r}."
        )

    return CapturedSnapshot(metadata=metadata, payloads=payloads)


def list_snapshot_ids(root: Path | str) -> tuple[str, ...]:
    """Return the identifiers of every snapshot under ``root``, in capture order.

    The identifier embeds a fixed-width UTC timestamp, so lexical order is capture
    order and no metadata has to be opened to sort the listing.
    """

    directory = Path(root)
    if not directory.is_dir():
        return ()
    return tuple(
        sorted(entry.name for entry in directory.iterdir() if (entry / METADATA_FILENAME).is_file())
    )
