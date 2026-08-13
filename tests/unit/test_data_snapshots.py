"""Tests for the immutable pre-deadline snapshot store.

Every payload here is invented. The store is deliberately ignorant of payload
meaning, so exercising it needs no live source and no network.
"""

import json
from pathlib import Path

import pytest

from squadopt.data.errors import (
    DataSourceError,
    SnapshotExistsError,
    SnapshotIntegrityError,
)
from squadopt.data.snapshots import (
    METADATA_FILENAME,
    PAYLOAD_DIRECTORY,
    SNAPSHOT_SCHEMA_VERSION,
    build_snapshot_id,
    list_snapshot_ids,
    normalize_captured_at,
    payload_checksum,
    read_snapshot,
    snapshot_fingerprint,
    write_snapshot,
)

SOURCE = "fpl-live"
CAPTURED_AT = "2026-08-21T16:00:00Z"
PAYLOADS = {
    "bootstrap-static.json": b'{"events": []}',
    "fixtures.json": b"[]",
}


def _write(root: Path, *, captured_at: str = CAPTURED_AT, **overrides: object) -> str:
    payloads = overrides.get("payloads", PAYLOADS)
    assert isinstance(payloads, dict)
    metadata = write_snapshot(
        root,
        source=str(overrides.get("source", SOURCE)),
        captured_at_utc=captured_at,
        payloads=payloads,
    )
    return metadata.snapshot_id


# --- round trip -------------------------------------------------------------


def test_written_payloads_are_returned_unchanged(tmp_path: Path) -> None:
    identifier = _write(tmp_path)

    snapshot = read_snapshot(tmp_path, identifier)

    assert dict(snapshot.payloads) == PAYLOADS


def test_metadata_records_provenance_and_checksums(tmp_path: Path) -> None:
    identifier = _write(tmp_path)

    metadata = read_snapshot(tmp_path, identifier).metadata

    assert metadata.source == SOURCE
    assert metadata.captured_at_utc == CAPTURED_AT
    assert metadata.schema_version == SNAPSHOT_SCHEMA_VERSION
    assert dict(metadata.checksums) == {
        name: payload_checksum(content) for name, content in PAYLOADS.items()
    }


def test_identifier_sorts_by_capture_time_and_names_its_source(tmp_path: Path) -> None:
    identifier = _write(tmp_path)

    assert identifier.startswith(f"{SOURCE}-20260821T160000Z-")


# --- determinism ------------------------------------------------------------


def test_identical_captures_produce_identical_identifiers(tmp_path: Path) -> None:
    """Same source, same instant, same bytes must fingerprint the same way."""

    first = _write(tmp_path / "a")
    second = _write(tmp_path / "b")

    assert first == second


def test_metadata_serialization_is_byte_identical_for_identical_captures(tmp_path: Path) -> None:
    first = _write(tmp_path / "a")
    second = _write(tmp_path / "b")

    assert (tmp_path / "a" / first / METADATA_FILENAME).read_bytes() == (
        tmp_path / "b" / second / METADATA_FILENAME
    ).read_bytes()


def test_a_later_capture_of_the_same_bytes_is_a_different_snapshot(tmp_path: Path) -> None:
    first = _write(tmp_path)
    second = _write(tmp_path, captured_at="2026-08-21T16:00:01Z")

    assert first != second


def test_changed_payload_bytes_change_the_identifier(tmp_path: Path) -> None:
    first = _write(tmp_path)
    second = _write(
        tmp_path,
        payloads={**PAYLOADS, "fixtures.json": b'[{"id": 1}]'},
    )

    assert first != second


def test_payload_ordering_does_not_affect_the_identifier(tmp_path: Path) -> None:
    reversed_payloads = dict(reversed(list(PAYLOADS.items())))

    first = _write(tmp_path / "a")
    second = _write(tmp_path / "b", payloads=reversed_payloads)

    assert first == second


def test_schema_version_participates_in_the_fingerprint() -> None:
    """A layout change must not be able to reuse an existing snapshot's identity."""

    arguments = {
        "source": SOURCE,
        "captured_at_utc": CAPTURED_AT,
        "checksums": {"a.json": payload_checksum(b"{}")},
    }

    assert snapshot_fingerprint(schema_version="snapshot_v1", **arguments) != snapshot_fingerprint(
        schema_version="snapshot_v2", **arguments
    )


# --- immutability -----------------------------------------------------------


def test_rewriting_a_snapshot_is_refused(tmp_path: Path) -> None:
    _write(tmp_path)

    with pytest.raises(SnapshotExistsError, match="never overwritten"):
        _write(tmp_path)


# --- capture timestamps -----------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("2026-08-21T16:00:00Z", "2026-08-21T16:00:00Z"),
        ("2026-08-21T16:00:00+00:00", "2026-08-21T16:00:00Z"),
        ("2026-08-21T16:00:00.123456Z", "2026-08-21T16:00:00.123456Z"),
    ],
)
def test_utc_timestamps_normalize_to_one_spelling(value: str, expected: str) -> None:
    assert normalize_captured_at(value) == expected


def test_sub_second_precision_is_preserved_rather_than_truncated() -> None:
    """Truncating would silently merge two captures taken inside the same second."""

    first = build_snapshot_id(
        source=SOURCE,
        captured_at_utc=normalize_captured_at("2026-08-21T16:00:00.000001Z"),
        fingerprint=payload_checksum(b"a"),
    )
    second = build_snapshot_id(
        source=SOURCE,
        captured_at_utc=normalize_captured_at("2026-08-21T16:00:00.000002Z"),
        fingerprint=payload_checksum(b"b"),
    )

    assert first != second


def test_a_naive_timestamp_is_rejected() -> None:
    with pytest.raises(DataSourceError, match="must state a timezone"):
        normalize_captured_at("2026-08-21T16:00:00")


def test_a_non_utc_offset_is_rejected() -> None:
    """A deadline argument made in local time cannot be audited later."""

    with pytest.raises(DataSourceError, match="must be expressed in UTC"):
        normalize_captured_at("2026-08-21T16:00:00+03:00")


def test_an_unparseable_timestamp_is_rejected() -> None:
    with pytest.raises(DataSourceError, match="ISO-8601"):
        normalize_captured_at("last Tuesday")


# --- name validation --------------------------------------------------------


@pytest.mark.parametrize("source", ["../escape", "FPL-Live", "fpl live", "", "fpl/live"])
def test_a_source_name_that_is_not_a_plain_identifier_is_rejected(
    tmp_path: Path, source: str
) -> None:
    with pytest.raises(DataSourceError, match="lowercase hyphenated identifier"):
        write_snapshot(
            tmp_path,
            source=source,
            captured_at_utc=CAPTURED_AT,
            payloads=PAYLOADS,
        )


@pytest.mark.parametrize("name", ["../escape.json", "nested/file.json", "Bootstrap.json"])
def test_a_payload_name_that_could_escape_the_snapshot_is_rejected(
    tmp_path: Path, name: str
) -> None:
    with pytest.raises(DataSourceError, match="Payload names must be lowercase"):
        write_snapshot(
            tmp_path,
            source=SOURCE,
            captured_at_utc=CAPTURED_AT,
            payloads={name: b"{}"},
        )


def test_decoded_text_is_rejected_in_place_of_raw_bytes(tmp_path: Path) -> None:
    """Storing decoded text would make the checksum depend on the decoder."""

    with pytest.raises(DataSourceError, match="raw bytes"):
        write_snapshot(
            tmp_path,
            source=SOURCE,
            captured_at_utc=CAPTURED_AT,
            payloads={"bootstrap-static.json": "{}"},  # type: ignore[dict-item]
        )


def test_a_snapshot_with_no_payloads_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(DataSourceError, match="at least one named payload"):
        write_snapshot(
            tmp_path,
            source=SOURCE,
            captured_at_utc=CAPTURED_AT,
            payloads={},
        )


# --- integrity --------------------------------------------------------------


def test_an_edited_payload_is_detected(tmp_path: Path) -> None:
    identifier = _write(tmp_path)
    (tmp_path / identifier / PAYLOAD_DIRECTORY / "fixtures.json").write_bytes(b'[{"id": 99}]')

    with pytest.raises(SnapshotIntegrityError, match="does not match its recorded checksum"):
        read_snapshot(tmp_path, identifier)


def test_edited_provenance_is_detected(tmp_path: Path) -> None:
    """Moving the capture time later would make a leaky decision look timely."""

    identifier = _write(tmp_path)
    path = tmp_path / identifier / METADATA_FILENAME
    document = json.loads(path.read_text(encoding="utf-8"))
    document["captured_at_utc"] = "2026-08-21T18:00:00Z"
    path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    with pytest.raises(SnapshotIntegrityError, match="metadata fingerprints to"):
        read_snapshot(tmp_path, identifier)


def test_an_edited_fingerprint_is_detected(tmp_path: Path) -> None:
    identifier = _write(tmp_path)
    path = tmp_path / identifier / METADATA_FILENAME
    document = json.loads(path.read_text(encoding="utf-8"))
    document["fingerprint"] = payload_checksum(b"forged")
    path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    with pytest.raises(SnapshotIntegrityError):
        read_snapshot(tmp_path, identifier)


def test_metadata_relocated_into_another_directory_is_detected(tmp_path: Path) -> None:
    identifier = _write(tmp_path)
    (tmp_path / identifier).rename(tmp_path / "fpl-live-20260821T160000Z-000000000000")

    with pytest.raises(SnapshotIntegrityError, match="identifying itself as"):
        read_snapshot(tmp_path, "fpl-live-20260821T160000Z-000000000000")


def test_a_missing_payload_file_is_detected(tmp_path: Path) -> None:
    identifier = _write(tmp_path)
    (tmp_path / identifier / PAYLOAD_DIRECTORY / "fixtures.json").unlink()

    with pytest.raises(SnapshotIntegrityError, match="is missing"):
        read_snapshot(tmp_path, identifier)


def test_an_unrecorded_extra_payload_is_detected(tmp_path: Path) -> None:
    """An unrecorded file would otherwise be invisible to the checksum pass."""

    identifier = _write(tmp_path)
    (tmp_path / identifier / PAYLOAD_DIRECTORY / "smuggled.json").write_bytes(b"{}")

    with pytest.raises(SnapshotIntegrityError, match="does not record"):
        read_snapshot(tmp_path, identifier)


def test_reading_an_absent_snapshot_names_what_was_expected(tmp_path: Path) -> None:
    with pytest.raises(DataSourceError, match="No snapshot metadata at"):
        read_snapshot(tmp_path, "fpl-live-20260821T160000Z-000000000000")


def test_unparseable_metadata_is_reported_as_an_integrity_failure(tmp_path: Path) -> None:
    identifier = _write(tmp_path)
    (tmp_path / identifier / METADATA_FILENAME).write_text("{not json", encoding="utf-8")

    with pytest.raises(SnapshotIntegrityError, match="not valid JSON"):
        read_snapshot(tmp_path, identifier)


# --- listing ----------------------------------------------------------------


def test_snapshots_list_in_capture_order(tmp_path: Path) -> None:
    later = _write(tmp_path, captured_at="2026-08-21T17:00:00Z")
    earlier = _write(tmp_path, captured_at="2026-08-21T16:00:00Z")

    assert list_snapshot_ids(tmp_path) == (earlier, later)


def test_a_directory_without_metadata_is_not_listed_as_a_snapshot(tmp_path: Path) -> None:
    """An interrupted capture must not be mistaken for a usable one."""

    identifier = _write(tmp_path)
    (tmp_path / "fpl-live-20260821T170000Z-abcabcabcabc" / PAYLOAD_DIRECTORY).mkdir(parents=True)

    assert list_snapshot_ids(tmp_path) == (identifier,)


def test_listing_an_absent_root_is_empty_rather_than_an_error(tmp_path: Path) -> None:
    assert list_snapshot_ids(tmp_path / "never-captured") == ()
