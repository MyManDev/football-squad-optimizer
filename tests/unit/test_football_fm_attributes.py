"""Synthetic FM23-style CSV source preparation, without real export ingestion."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import MappingProxyType
from typing import Any

import pytest

from squadopt.features.football_fm_attributes import (
    FM_ATTRIBUTES_INPUT_VERSION,
    read_fm_attributes,
)
from squadopt.features.football_unit_inputs import (
    NumericAttributeSpec,
    PlayerAttributes,
    SourceRecord,
)

CUTOFF = datetime(2024, 8, 1, 10, tzinfo=UTC)
CSV = (
    b"UID,Name,Heading,Positioning,Age\r\n"
    b"1001,Synthetic One,12,14,25\r\n"
    b"1002,Synthetic Two,,20,19\r\n"
    b"1003,Synthetic Three,1,,31\r\n"
    b"1004,Synthetic Four,,,20\r\n"
)


def _source(payload: bytes, **changes: Any) -> SourceRecord:
    return replace(
        SourceRecord(
            source_id="synthetic-fm-export",
            provider="fictional-FM23-export",
            version="FM23-synthetic-edition",
            kind="fm",
            sha256=hashlib.sha256(payload).hexdigest(),
            published_at=CUTOFF - timedelta(days=2),
            captured_at=CUTOFF - timedelta(days=1),
            effective_at=CUTOFF - timedelta(days=3),
            valid_until=CUTOFF + timedelta(days=1),
            rights_reference="fictional-test-license:model-development",
            permitted_model_development=True,
        ),
        **changes,
    )


def _specs() -> tuple[NumericAttributeSpec, ...]:
    return (
        NumericAttributeSpec(
            "heading", "synthetic-fm-export", 1, 20, "rating", "Synthetic FM23-style heading"
        ),
        NumericAttributeSpec(
            "positioning",
            "synthetic-fm-export",
            1,
            20,
            "rating",
            "Synthetic FM23-style positioning",
        ),
    )


def _read(payload: bytes = CSV, **options: Any) -> tuple[PlayerAttributes, ...]:
    arguments = {
        "source": _source(payload),
        "cutoff": CUTOFF,
        "attributes": _specs(),
        "attribute_columns": {"heading": "Heading", "positioning": "Positioning"},
        "uid_column": "UID",
        **options,
    }
    return read_fm_attributes(payload, **arguments)


def test_all_uid_rows_remain_with_known_and_explicitly_unknown_attributes() -> None:
    result = _read()
    assert FM_ATTRIBUTES_INPUT_VERSION == "football_fm_csv_attributes_v1"
    assert result == (
        PlayerAttributes("synthetic-fm-export", "1001", (("heading", 12.0), ("positioning", 14.0))),
        PlayerAttributes("synthetic-fm-export", "1002", (("heading", None), ("positioning", 20.0))),
        PlayerAttributes("synthetic-fm-export", "1003", (("heading", 1.0), ("positioning", None))),
        PlayerAttributes("synthetic-fm-export", "1004", (("heading", None), ("positioning", None))),
    )
    assert all(set(dict(row.values)) == {"heading", "positioning"} for row in result)
    assert all(not hasattr(row, "player_id") and not hasattr(row, "club") for row in result)


def test_actual_fm23_style_blank_index_and_nat_alias_need_explicit_admission():
    raw = b",UID,Nat,Nat.1,Hea,Pos\n0,2001,ENG,16,12,14\n"
    with pytest.raises(ValueError, match="named header"):
        _read(raw, attribute_columns={"heading": "Hea", "positioning": "Pos"})
    parsed = _read(
        raw, allow_unnamed_index=True, attribute_columns={"heading": "Hea", "positioning": "Pos"}
    )
    assert parsed[0].source_player_id == "2001"
    assert dict(parsed[0].values) == {"heading": 12.0, "positioning": 14.0}


@pytest.mark.parametrize("value", [1, "true", None])
def test_unnamed_index_policy_requires_boolean(value):
    with pytest.raises(ValueError, match="explicit boolean"):
        _read(allow_unnamed_index=value)


def test_explicit_generic_column_mapping_handles_quoted_names_without_matching_them() -> None:
    raw = 'Age,Unique ID,Pos,Name,Hea\n22,2001,11,"Synthetic, Örnek",16\n'.encode()
    result = _read(
        raw,
        uid_column="Unique ID",
        attribute_columns=MappingProxyType({"positioning": "Pos", "heading": "Hea"}),
    )
    assert result[0].source_player_id == "2001"
    assert dict(result[0].values) == {"heading": 16.0, "positioning": 11.0}


def test_utf8_bom_and_whitespace_are_explicitly_supported_without_changing_uid() -> None:
    raw = b"\xef\xbb\xbfUID,Heading,Positioning\n 2001 , 20 ,   \n"
    result = _read(raw)
    assert result == (
        PlayerAttributes("synthetic-fm-export", "2001", (("heading", 20.0), ("positioning", None))),
    )


def test_equal_selected_attributes_collapse_duplicate_uid_but_ignore_other_columns() -> None:
    raw = b"UID,Heading,Positioning,Name,Age\n3001,10,15,One,25\n3001,10,15,Other,30\n"
    assert _read(raw) == (
        PlayerAttributes("synthetic-fm-export", "3001", (("heading", 10.0), ("positioning", 15.0))),
    )


@pytest.mark.parametrize("second", ["11,15", "10,16", ",15"])
def test_duplicate_uid_with_conflicting_or_missing_selected_attributes_refuses(second: str) -> None:
    raw = f"UID,Heading,Positioning\n3001,10,15\n3001,{second}\n".encode()
    with pytest.raises(ValueError, match="conflicting selected attributes"):
        _read(raw)


@pytest.mark.parametrize(
    "cell", ["0", "21", "-1", "10-14", "12.0", "+12", "01", "NaN", "Infinity", "?", "N/A", "=10+2"]
)
def test_unknown_ranges_and_nonnumeric_or_unsupported_attribute_cells_refuse(cell: str) -> None:
    raw = f"UID,Heading,Positioning\n1001,{cell},12\n".encode()
    with pytest.raises(ValueError, match="integer 1 to 20"):
        _read(raw)


@pytest.mark.parametrize(
    "uid", ["", " ", "0", "001", "1.0", "-1", "Synthetic Player", "\uff11\uff12\uff13"]
)
def test_uid_must_be_an_explicit_positive_decimal_identity(uid: str) -> None:
    raw = f"UID,Heading,Positioning\n{uid},12,14\n".encode()
    with pytest.raises(ValueError, match="positive decimal UID"):
        _read(raw)


def test_dataset_without_uid_refuses_instead_of_using_age_or_player_name() -> None:
    raw = b"Name,Age,Heading,Positioning\nSynthetic Player,22,12,14\n"
    with pytest.raises(ValueError, match="explicitly mapped columns"):
        _read(raw)


def test_raw_source_hash_includes_encoding_and_every_unselected_cell() -> None:
    changed = CSV.replace(b"Synthetic One", b"Synthetic New")
    with pytest.raises(ValueError, match="SHA256"):
        _read(changed, source=_source(CSV))
    with pytest.raises(ValueError, match="SHA256"):
        _read(b"\xef\xbb\xbf" + CSV, source=_source(CSV))


@pytest.mark.parametrize("encoding", ["utf-16", "utf-16-be", "utf-32"])
def test_non_utf8_source_bytes_are_not_autodetected(encoding: str) -> None:
    raw = CSV.decode().encode(encoding)
    with pytest.raises(ValueError, match="UTF-8"):
        _read(raw)


@pytest.mark.parametrize("kind", ["provider", "synthetic"])
def test_other_source_kinds_cannot_claim_fm_attribute_semantics(kind: str) -> None:
    rights = (
        "synthetic:unit-test" if kind == "synthetic" else "fictional-test-license:model-development"
    )
    source = _source(CSV, kind=kind, rights_reference=rights)
    with pytest.raises(ValueError, match="FM source receipt"):
        _read(source=source)


def test_missing_model_use_permission_refuses_without_inventing_a_grant() -> None:
    with pytest.raises(ValueError, match="permission"):
        _read(source=_source(CSV, permitted_model_development=False))
    with pytest.raises(ValueError, match="Synthetic receipts"):
        _read(source=_source(CSV, rights_reference="synthetic:unit-test"))


@pytest.mark.parametrize("field", ["published_at", "captured_at", "effective_at"])
def test_source_information_after_cutoff_refuses(field: str) -> None:
    changes = {field: CUTOFF + timedelta(seconds=1)}
    if field == "published_at":
        changes["captured_at"] = CUTOFF + timedelta(seconds=2)
    with pytest.raises(ValueError, match="decision cutoff"):
        _read(source=_source(CSV, **changes))


def test_expired_source_or_naive_cutoff_refuses() -> None:
    with pytest.raises(ValueError, match="stale"):
        _read(source=_source(CSV, valid_until=CUTOFF - timedelta(seconds=1)))
    with pytest.raises(ValueError, match="timezone"):
        _read(cutoff=CUTOFF.replace(tzinfo=None))


@pytest.mark.parametrize("range_values", [(0, 20), (1, 100), (0, 1)])
def test_declared_source_scale_must_be_exactly_fm_one_to_twenty(
    range_values: tuple[float, float],
) -> None:
    changed = replace(_specs()[0], minimum=range_values[0], maximum=range_values[1])
    with pytest.raises(ValueError, match="1 to 20"):
        _read(attributes=(changed, _specs()[1]))


def test_attribute_definitions_cannot_belong_to_another_source() -> None:
    other = replace(_specs()[0], source_id="other-export")
    with pytest.raises(ValueError, match="supplied source"):
        _read(attributes=(other, _specs()[1]))


@pytest.mark.parametrize(
    "mapping",
    [
        {},
        {"heading": "Heading"},
        {"heading": "Heading", "positioning": "Positioning", "invented": "Age"},
        {"heading": "Heading", "positioning": "Heading"},
        {"heading": "UID", "positioning": "Positioning"},
        {"heading": "", "positioning": "Positioning"},
        {"heading": True, "positioning": "Positioning"},
    ],
)
def test_column_mapping_must_cover_unique_declared_attributes_only(mapping: Any) -> None:
    with pytest.raises(ValueError):
        _read(attribute_columns=mapping)


@pytest.mark.parametrize("attributes", [(), [], (True,), (_specs()[0], _specs()[0])])
def test_attribute_definitions_are_a_nonempty_unique_immutable_selection(attributes: Any) -> None:
    with pytest.raises(ValueError):
        _read(attributes=attributes)


@pytest.mark.parametrize(
    "raw",
    [
        b"UID,Heading,Heading\n1001,12,14\n",
        b"UID,Heading,Positioning,UID\n1001,12,14,1001\n",
        b"UID,Heading,Positioning\n1001,12\n",
        b"UID,Heading,Positioning\n1001,12,14,extra\n",
        b"UID,Heading,Positioning\n\n",
        b'UID,Heading,Positioning\n1001,"unterminated,14\n',
        b"UID,Heading,Positioning\n",
        b"",
    ],
)
def test_csv_structure_refuses_ambiguous_headers_partial_rows_or_empty_population(
    raw: bytes,
) -> None:
    with pytest.raises(ValueError):
        _read(raw)


@pytest.mark.parametrize("payload", [CSV.decode(), bytearray(CSV), memoryview(CSV)])
def test_mutable_or_decoded_payloads_are_not_source_receipts(payload: Any) -> None:
    with pytest.raises(ValueError, match="immutable"):
        read_fm_attributes(
            payload,
            source=_source(CSV),
            cutoff=CUTOFF,
            attributes=_specs(),
            attribute_columns={"heading": "Heading", "positioning": "Positioning"},
            uid_column="UID",
        )


def test_input_mapping_source_and_bytes_remain_unchanged() -> None:
    mapping = {"heading": "Heading", "positioning": "Positioning"}
    receipt = _source(CSV)
    before = mapping.copy()
    read_fm_attributes(
        CSV,
        source=receipt,
        cutoff=CUTOFF,
        attributes=_specs(),
        attribute_columns=mapping,
        uid_column="UID",
    )
    assert mapping == before
    assert receipt == _source(CSV)
    assert hashlib.sha256(CSV).hexdigest() == receipt.sha256
