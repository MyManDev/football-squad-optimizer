"""Artifact provenance records, file-backed storage and run lineage."""

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import jsonschema
import pytest

from squadopt.platform import (
    ARTIFACT_RECORD_CONTRACT_VERSION,
    ARTIFACT_RECORD_DIRECTORY,
    ARTIFACT_RECORD_SCHEMA_PATH,
    ArtifactIntegrityError,
    ArtifactNotFoundError,
    ArtifactRecord,
    ArtifactRecordError,
    ArtifactRegistryError,
    FileArtifactRegistry,
    artifact_checksum,
    artifact_record_schema,
    build_artifact_id,
    parse_artifact_record,
    serialize_artifact_record,
    write_artifact_record_schema,
)

NOW = datetime(2026, 8, 19, 14, 0, 0, 123000, tzinfo=UTC)
CHECKSUM = "d397153254ae1c5c0ff5f3590cdae1ebc66ab63bcd8d228744682d27f838dcc5"
ARTIFACT_ID = "artifact-9aee95a09044ad179590a20f6f41f13d"


def _record(**changes: object) -> ArtifactRecord:
    values: dict[str, object] = {
        "artifact_id": ARTIFACT_ID,
        "run_id": "run-001",
        "role": "output",
        "kind": "decision",
        "location": "outputs/decision.json",
        "checksum": CHECKSUM,
        "schema_version": "decision_v1",
        "created_at_utc": "2026-08-19T14:00:00.123000Z",
    }
    values.update(changes)
    return ArtifactRecord(**values)  # type: ignore[arg-type]


def _registry(tmp_path: Path) -> tuple[FileArtifactRegistry, Path]:
    artifact_root = tmp_path / "artifacts"
    artifact_root.mkdir()
    return (
        FileArtifactRegistry(tmp_path / "registry", artifact_root=artifact_root),
        artifact_root,
    )


def _write(root: Path, location: str, content: bytes) -> Path:
    path = root / location
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def test_record_identity_is_pinned_and_serialization_round_trips() -> None:
    record = _record()

    assert record.contract_version == ARTIFACT_RECORD_CONTRACT_VERSION
    assert (
        build_artifact_id(
            run_id=record.run_id,
            role=record.role,
            kind=record.kind,
            location=record.location,
            checksum=record.checksum,
            schema_version=record.schema_version,
        )
        == ARTIFACT_ID
    )
    encoded = serialize_artifact_record(record)
    assert encoded.endswith(b"\n") and b"\r\n" not in encoded
    assert parse_artifact_record(encoded) == record
    assert parse_artifact_record(encoded.decode("utf-8")) == record


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"artifact_id": "spaces are unsafe"}, "artifact_id"),
        ({"run_id": "bad/run"}, "run_id"),
        ({"role": "cache"}, "role"),
        ({"kind": "Decision"}, "kind"),
        ({"location": "../decision.json"}, "location"),
        ({"location": r"outputs\decision.json"}, "relative POSIX"),
        ({"checksum": "A" * 64}, "checksum"),
        ({"schema_version": "decision v1"}, "schema_version"),
        ({"created_at_utc": "2026-08-19T14:00:00"}, "created_at_utc"),
        ({"contract_version": "artifact_record_v2"}, "contract_version"),
    ],
)
def test_invalid_record_values_are_rejected(changes: dict[str, object], message: str) -> None:
    with pytest.raises(ArtifactRecordError, match=message):
        _record(**changes)


def test_record_rejects_an_id_that_does_not_bind_its_metadata() -> None:
    with pytest.raises(ArtifactRecordError, match="does not match"):
        replace(_record(), kind="projection")


def test_parser_rejects_unknown_fields_bad_json_and_noncanonical_time() -> None:
    document = _record().to_dict()
    document["unexpected"] = True
    with pytest.raises(ArtifactRecordError, match="unexpected"):
        parse_artifact_record(json.dumps(document))
    with pytest.raises(ArtifactRecordError, match="valid JSON"):
        parse_artifact_record("{broken")
    with pytest.raises(ArtifactRecordError, match="UTF-8"):
        parse_artifact_record(b"\xff")

    document = _record().to_dict()
    document["created_at_utc"] = "2026-08-19T14:00:00.123000+00:00"
    with pytest.raises(ArtifactRecordError, match="canonical UTC"):
        parse_artifact_record(json.dumps(document))


def test_schema_is_valid_committed_and_accepts_a_record(tmp_path: Path) -> None:
    schema = artifact_record_schema()
    document = _record().to_dict()

    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.validate(document, schema)
    assert json.loads(ARTIFACT_RECORD_SCHEMA_PATH.read_text(encoding="utf-8")) == schema
    written = write_artifact_record_schema(tmp_path / "schema.json")
    assert json.loads(written.read_text(encoding="utf-8")) == schema


def test_register_get_and_verify_use_relative_portable_locations(tmp_path: Path) -> None:
    registry, root = _registry(tmp_path)
    path = _write(root, "outputs/decision.json", b"decision-v1\n")

    record = registry.register_artifact(
        path,
        run_id="run-001",
        role="output",
        kind="decision",
        schema_version="decision_v1",
        now=NOW,
    )

    assert artifact_checksum(path) == CHECKSUM
    assert record == _record()
    assert record.location == "outputs/decision.json"
    assert registry.get_artifact(ARTIFACT_ID) == record
    assert registry.verify_checksum(ARTIFACT_ID) == record
    record_path = registry.record_directory / f"{ARTIFACT_ID}.json"
    assert record_path.is_file()
    assert record_path.parent.name == ARTIFACT_RECORD_DIRECTORY
    assert not tuple(record_path.parent.glob(f".{ARTIFACT_ID}.json.tmp-*"))


def test_exact_registration_retry_is_idempotent_and_preserves_first_timestamp(
    tmp_path: Path,
) -> None:
    registry, root = _registry(tmp_path)
    path = _write(root, "outputs/decision.json", b"decision-v1\n")
    first = registry.register_artifact(
        path,
        run_id="run-001",
        role="output",
        kind="decision",
        schema_version="decision_v1",
        now=NOW,
    )
    record_path = registry.record_directory / f"{first.artifact_id}.json"
    first_bytes = record_path.read_bytes()

    retry = registry.register_artifact(
        path,
        run_id="run-001",
        role="output",
        kind="decision",
        schema_version="decision_v1",
        now=NOW + timedelta(days=1),
    )

    assert retry == first
    assert retry.created_at_utc == "2026-08-19T14:00:00.123000Z"
    assert record_path.read_bytes() == first_bytes


def test_same_run_slot_cannot_be_reused_with_changed_bytes_or_schema(tmp_path: Path) -> None:
    registry, root = _registry(tmp_path)
    path = _write(root, "outputs/decision.json", b"decision-v1\n")
    registry.register_artifact(
        path,
        run_id="run-001",
        role="output",
        kind="decision",
        schema_version="decision_v1",
        now=NOW,
    )

    path.write_bytes(b"changed\n")
    with pytest.raises(ArtifactRegistryError, match="different bytes or schema"):
        registry.register_artifact(
            path,
            run_id="run-001",
            role="output",
            kind="decision",
            schema_version="decision_v1",
            now=NOW,
        )


def test_checksum_verification_rejects_changed_or_missing_bytes(tmp_path: Path) -> None:
    registry, root = _registry(tmp_path)
    path = _write(root, "outputs/decision.json", b"decision-v1\n")
    record = registry.register_artifact(
        path,
        run_id="run-001",
        role="output",
        kind="decision",
        schema_version="decision_v1",
        now=NOW,
    )

    path.write_bytes(b"tampered\n")
    with pytest.raises(ArtifactIntegrityError, match="checksum mismatch"):
        registry.verify_checksum(record)
    path.unlink()
    with pytest.raises(ArtifactIntegrityError, match="file is missing"):
        registry.verify_checksum(record)


def test_checksum_verification_requires_a_registered_record(tmp_path: Path) -> None:
    registry, _ = _registry(tmp_path)

    with pytest.raises(ArtifactNotFoundError, match="not registered"):
        registry.verify_checksum(_record())


def test_registry_rejects_files_outside_its_artifact_root(tmp_path: Path) -> None:
    registry, _ = _registry(tmp_path)
    outside = tmp_path / "outside.json"
    outside.write_bytes(b"outside\n")

    with pytest.raises(ArtifactRegistryError, match="outside artifact_root"):
        registry.register_artifact(
            outside,
            run_id="run-001",
            role="input",
            kind="snapshot",
            schema_version="snapshot_v1",
            now=NOW,
        )


def test_get_rejects_missing_and_tampered_registry_records(tmp_path: Path) -> None:
    registry, root = _registry(tmp_path)
    with pytest.raises(ArtifactNotFoundError, match="not registered"):
        registry.get_artifact(ARTIFACT_ID)

    path = _write(root, "outputs/decision.json", b"decision-v1\n")
    record = registry.register_artifact(
        path,
        run_id="run-001",
        role="output",
        kind="decision",
        schema_version="decision_v1",
        now=NOW,
    )
    record_path = registry.record_directory / f"{record.artifact_id}.json"
    document = json.loads(record_path.read_text(encoding="utf-8"))
    document["kind"] = "projection"
    record_path.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(ArtifactIntegrityError, match="does not match"):
        registry.get_artifact(record.artifact_id)


def test_lineage_separates_runs_and_orders_input_output_edges(tmp_path: Path) -> None:
    registry, root = _registry(tmp_path)
    paths = {
        "snapshot": _write(root, "inputs/snapshot.json", b"snapshot\n"),
        "projection": _write(root, "inputs/projections.parquet", b"projections\n"),
        "metrics": _write(root, "outputs/metrics.json", b"metrics\n"),
        "decision": _write(root, "outputs/decision.json", b"decision\n"),
        "other": _write(root, "outputs/other.json", b"other\n"),
    }
    for kind in ("snapshot", "projection"):
        registry.register_artifact(
            paths[kind],
            run_id="run-001",
            role="input",
            kind=kind,
            schema_version=f"{kind}_v1",
            now=NOW,
        )
    for kind in ("metrics", "decision"):
        registry.register_artifact(
            paths[kind],
            run_id="run-001",
            role="output",
            kind=kind,
            schema_version=f"{kind}_v1",
            now=NOW,
        )
    registry.register_artifact(
        paths["other"],
        run_id="run-002",
        role="output",
        kind="decision",
        schema_version="decision_v1",
        now=NOW,
    )

    lineage = registry.lineage("run-001", verify=True)

    assert lineage.run_id == "run-001"
    assert [record.kind for record in lineage.inputs] == ["projection", "snapshot"]
    assert [record.kind for record in lineage.outputs] == ["decision", "metrics"]
    assert {record.run_id for record in (*lineage.inputs, *lineage.outputs)} == {"run-001"}


def test_factory_clock_must_be_utc(tmp_path: Path) -> None:
    registry, root = _registry(tmp_path)
    path = _write(root, "outputs/decision.json", b"decision-v1\n")
    values = {
        "run_id": "run-001",
        "role": "output",
        "kind": "decision",
        "schema_version": "decision_v1",
    }
    with pytest.raises(ArtifactRecordError, match="now"):
        registry.register_artifact(path, **values, now=datetime(2026, 8, 19, 14, 0))  # type: ignore[arg-type]
    with pytest.raises(ArtifactRecordError, match="now"):
        registry.register_artifact(
            path,
            **values,  # type: ignore[arg-type]
            now=datetime(2026, 8, 19, 17, 0, tzinfo=timezone(timedelta(hours=3))),
        )
