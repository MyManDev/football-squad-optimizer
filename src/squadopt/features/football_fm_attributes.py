"""Read a private, explicitly mapped FM attribute export without inferring identities.

The supplied source receipt must cover model development and the exact CSV bytes.
Successful parsing does not prove provider permission. Only blanks mean unknown.
This separately invoked preparer retains every declared UID. Native integration
and the exact temporal catalog scope/filter remain the separately reviewed second
step. No actual dataset admission is established by this reader.
"""

from __future__ import annotations

import csv
import hashlib
import io
import re
from collections.abc import Mapping
from datetime import datetime

from squadopt.features.football_unit_inputs import (
    NumericAttributeSpec,
    PlayerAttributes,
    SourceRecord,
)

FM_ATTRIBUTES_INPUT_VERSION = "football_fm_csv_attributes_v1"
_UID = re.compile(r"[1-9][0-9]*\Z")
_ATTRIBUTE = re.compile(r"(?:[1-9]|1[0-9]|20)\Z")


def _column(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"FM {label} must identify one explicit CSV column.")
    return value


def _selection(
    source: SourceRecord,
    attributes: tuple[NumericAttributeSpec, ...],
    attribute_columns: Mapping[str, str],
    uid_column: str,
) -> dict[str, str]:
    if (
        not isinstance(attributes, tuple)
        or not attributes
        or any(not isinstance(item, NumericAttributeSpec) for item in attributes)
    ):
        raise ValueError("FM attributes need a nonempty tuple of numeric definitions.")
    if any(
        item.source_id != source.source_id or (item.minimum, item.maximum) != (1, 20)
        for item in attributes
    ):
        raise ValueError("FM definitions must belong to the supplied source and declare 1 to 20.")
    names = {item.name for item in attributes}
    if len(names) != len(attributes):
        raise ValueError("FM numeric definitions must have unique declared names.")
    if not isinstance(attribute_columns, Mapping) or set(attribute_columns) != names:
        raise ValueError("FM column mapping must cover exactly the declared attribute names.")
    columns = {
        name: _column(attribute_columns[name], "attribute mapping") for name in sorted(names)
    }
    if len(set(columns.values())) != len(columns) or uid_column in columns.values():
        raise ValueError("FM UID and attribute columns must be distinct and uniquely mapped.")
    return columns


def read_fm_attributes(
    payload: bytes,
    *,
    source: SourceRecord,
    cutoff: datetime,
    attributes: tuple[NumericAttributeSpec, ...],
    attribute_columns: Mapping[str, str],
    uid_column: str,
    allow_unnamed_index: bool = False,
) -> tuple[PlayerAttributes, ...]:
    """Return one immutable attribute snapshot per exact positive decimal FM UID.

    UTF-8 may include its own BOM. Header labels and mapped columns are explicit;
    one unselected blank index header may be explicitly admitted for raw exports.
    names, ages, clubs and FPL identities are never matched. Selected cells accept
    blank or canonical integers 1..20, with no range midpoint or zero imputation.
    Matching duplicate UIDs collapse only when all selected values agree. Output
    keeps the first-seen UID order and includes players whose values are all unknown.
    Temporal persistent-player mappings are a separate caller-supplied contract.
    """
    if not isinstance(payload, bytes):
        raise ValueError("FM attributes require immutable UTF-8 CSV bytes.")
    if not isinstance(allow_unnamed_index, bool):
        raise ValueError("FM unnamed-index admission must be an explicit boolean.")
    if not isinstance(source, SourceRecord) or source.kind != "fm":
        raise ValueError("FM attributes require an explicitly identified FM source receipt.")
    if source.permitted_model_development is not True:
        raise ValueError("FM source permission must explicitly cover model development.")
    source.available_at(cutoff)
    if hashlib.sha256(payload).hexdigest() != source.sha256:
        raise ValueError("FM CSV bytes do not match the supplied source SHA256 receipt.")
    uid_column = _column(uid_column, "UID column")
    columns = _selection(source, attributes, attribute_columns, uid_column)
    try:
        text = payload.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise ValueError("FM attributes must contain valid UTF-8 CSV text.") from error
    if "\x00" in text:
        raise ValueError("FM attributes must contain UTF-8 CSV text without NUL characters.")
    reader = csv.reader(io.StringIO(text, newline=""), strict=True)
    snapshots: dict[str, PlayerAttributes] = {}
    try:
        headers = next(reader, None)
        if not headers or any(
            not header.strip()
            and not (allow_unnamed_index and header == "" and headers.count("") == 1)
            for header in headers
        ):
            raise ValueError("FM CSV requires a named header and an explicit UID column.")
        if len(set(headers)) != len(headers):
            raise ValueError("FM CSV column names must be unique.")
        missing = sorted({uid_column, *columns.values()} - set(headers))
        if missing:
            raise ValueError(f"FM CSV lacks explicitly mapped columns {missing}.")
        uid_index = headers.index(uid_column)
        selected = {name: headers.index(column) for name, column in columns.items()}
        for row_number, row in enumerate(reader, start=2):
            if len(row) != len(headers):
                raise ValueError(f"FM CSV row {row_number} does not match the declared header.")
            uid = row[uid_index].strip()
            if not _UID.fullmatch(uid):
                raise ValueError(f"FM CSV row {row_number} needs a positive decimal UID.")
            values: list[tuple[str, float | None]] = []
            for name, index in selected.items():
                cell = row[index].strip()
                if not cell:
                    value = None
                elif _ATTRIBUTE.fullmatch(cell):
                    value = float(int(cell))
                else:
                    raise ValueError(
                        f"FM CSV row {row_number} attribute {name!r} needs an integer 1 to 20 "
                        "or an explicit blank."
                    )
                values.append((name, value))
            snapshot = PlayerAttributes(source.source_id, uid, tuple(values))
            if uid in snapshots and snapshots[uid] != snapshot:
                raise ValueError(f"FM CSV has conflicting selected attributes for UID {uid}.")
            snapshots.setdefault(uid, snapshot)
    except csv.Error as error:
        raise ValueError("FM attributes must contain structurally valid CSV records.") from error
    if not snapshots:
        raise ValueError("FM CSV must contain at least one explicit UID row.")
    return tuple(snapshots.values())
