"""Read a private, explicitly mapped FM attribute export without inferring identities.

The supplied source receipt must cover model development and the exact CSV bytes.
Successful parsing does not prove provider permission. Only blanks mean unknown.
The full reader retains every declared UID. The scoped reader returns only active
caller-supplied mappings and their attributes for a catalog. Neither reader admits
an actual dataset or infers player identities, club membership or source rights.
"""

from __future__ import annotations

import csv
import hashlib
import io
import re
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime

from squadopt.features.football_unit_inputs import (
    NumericAttributeSpec,
    PlayerAttributes,
    PlayerMapping,
    SourceRecord,
    UnitHistoricalReplay,
    UnitInputCatalog,
    utc_time,
)

FM_ATTRIBUTES_INPUT_VERSION = "football_fm_csv_attributes_v1"
FM_SCOPED_ATTRIBUTES_VERSION = "football_fm_scoped_attributes_v1"
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
    replay: UnitHistoricalReplay | None = None,
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
    _validate_source(source, cutoff, replay)
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


@dataclass(frozen=True, slots=True)
class ScopedFMAttributes:
    """Exact source receipt and cutoff-bound rows, ready to combine with a catalog.

    ``source_player_count`` counts parsed unique UIDs before scoping. Unmapped or
    inactive source rows are omitted, while selected unknown values remain None.
    This receipt records preparation, not source or model admission.
    """

    source: SourceRecord
    cutoff: datetime
    mappings: tuple[PlayerMapping, ...]
    player_attributes: tuple[PlayerAttributes, ...]
    source_player_count: int
    contract_version: str = FM_SCOPED_ATTRIBUTES_VERSION
    replay: UnitHistoricalReplay | None = None

    def __post_init__(self) -> None:
        if self.contract_version != FM_SCOPED_ATTRIBUTES_VERSION:
            raise ValueError("Unsupported scoped FM attributes contract.")
        active = _active_mappings(self.source, self.cutoff, self.mappings, self.replay)
        if len(active) != len(self.mappings):
            raise ValueError("Scoped FM receipt mappings must all be active at its cutoff.")
        if type(self.player_attributes) is not tuple or any(
            not isinstance(row, PlayerAttributes) for row in self.player_attributes
        ):
            raise ValueError("Scoped FM receipt needs immutable typed attribute rows.")
        by_uid = {row.source_player_id: row for row in self.player_attributes}
        if (
            len(by_uid) != len(self.player_attributes)
            or set(by_uid) != {mapping.source_player_id for mapping in active}
            or any(row.source_id != self.source.source_id for row in self.player_attributes)
        ):
            raise ValueError("Scoped FM receipt rows must match its exact source and mappings.")
        names = {name for name, _ in self.player_attributes[0].values}
        if not names or any(not isinstance(name, str) or not name.strip() for name in names):
            raise ValueError("Scoped FM receipt rows need explicit attribute names.")
        for row in self.player_attributes:
            if {name for name, _ in row.values} != names or any(
                value is not None and (not 1 <= value <= 20 or not float(value).is_integer())
                for _, value in row.values
            ):
                raise ValueError("Scoped FM receipt rows need the same integer 1 to 20 fields.")
        if (
            isinstance(self.source_player_count, bool)
            or not isinstance(self.source_player_count, int)
            or self.source_player_count < len(active)
        ):
            raise ValueError("Scoped FM source count must cover every retained unique UID.")
        object.__setattr__(self, "mappings", active)
        object.__setattr__(
            self, "player_attributes", tuple(by_uid[mapping.source_player_id] for mapping in active)
        )

    def add_to_catalog(
        self, catalog: UnitInputCatalog, *, attributes: tuple[NumericAttributeSpec, ...]
    ) -> UnitInputCatalog:
        """Add this whole receipt at exactly the catalog's decision cutoff.

        Keep the scoped receipt intact until this handoff: splitting its mappings
        and rows discards the clock that selected them. The catalog validates the
        combined sources, definitions, mappings and values on construction.
        """
        if not isinstance(catalog, UnitInputCatalog) or self.cutoff != catalog.decision_cutoff:
            raise ValueError("Scoped FM receipt cutoff must equal the catalog decision cutoff.")
        if self.replay != catalog.replay:
            raise ValueError("Scoped FM receipt must retain the catalog's exact replay basis.")
        if (
            not isinstance(attributes, tuple)
            or not attributes
            or any(
                not isinstance(item, NumericAttributeSpec)
                or item.source_id != self.source.source_id
                for item in attributes
            )
        ):
            raise ValueError("Scoped FM handoff needs definitions for its exact source.")
        existing = next(
            (source for source in catalog.sources if source.source_id == self.source.source_id),
            None,
        )
        if existing is not None and existing != self.source:
            raise ValueError("Scoped FM handoff source differs from the catalog receipt.")
        return replace(
            catalog,
            sources=catalog.sources if existing is not None else (*catalog.sources, self.source),
            attributes=(*catalog.attributes, *attributes),
            mappings=(*catalog.mappings, *self.mappings),
            player_attributes=(*catalog.player_attributes, *self.player_attributes),
        )


def _validate_source(
    source: SourceRecord, cutoff: datetime, replay: UnitHistoricalReplay | None
) -> None:
    if not isinstance(source, SourceRecord) or source.kind != "fm":
        raise ValueError("Scoped FM attributes need an explicit FM source receipt.")
    utc_time(cutoff, "FM scope cutoff")
    if replay is None:
        source.available_at(cutoff)
    elif isinstance(replay, UnitHistoricalReplay):
        replay.validate_fm_source(source, decision=cutoff)
    else:
        raise ValueError("Scoped FM replay must be a typed immutable receipt.")


def _active_mappings(
    source: SourceRecord,
    cutoff: datetime,
    mappings: tuple[PlayerMapping, ...],
    replay: UnitHistoricalReplay | None = None,
) -> tuple[PlayerMapping, ...]:
    _validate_source(source, cutoff, replay)
    if type(mappings) is not tuple or not mappings:
        raise ValueError("Scoped FM attributes need immutable explicit player mappings.")
    by_uid: dict[str, list[PlayerMapping]] = {}
    active: dict[int, PlayerMapping] = {}
    for mapping in mappings:
        if not isinstance(mapping, PlayerMapping) or mapping.source_id != source.source_id:
            raise ValueError("Every FM scope mapping must belong to the exact supplied source.")
        if not _UID.fullmatch(mapping.source_player_id):
            raise ValueError("FM scope mappings require canonical positive decimal UIDs.")
        for previous in by_uid.setdefault(mapping.source_player_id, []):
            if max(previous.valid_from, mapping.valid_from) <= min(
                previous.valid_until, mapping.valid_until
            ):
                raise ValueError("FM scope mappings contain overlapping UID validity intervals.")
        by_uid[mapping.source_player_id].append(mapping)
        if mapping.valid_from <= cutoff <= mapping.valid_until:
            if mapping.player_id in active:
                raise ValueError("An active FPL person cannot have two FM UIDs in one source.")
            active[mapping.player_id] = mapping
    if not active:
        raise ValueError("No supplied FM player mapping is active at the explicit cutoff.")
    return tuple(sorted(active.values(), key=lambda item: int(item.source_player_id)))


def read_scoped_fm_attributes(
    payload: bytes,
    *,
    source: SourceRecord,
    cutoff: datetime,
    mappings: tuple[PlayerMapping, ...],
    attributes: tuple[NumericAttributeSpec, ...],
    attribute_columns: Mapping[str, str],
    uid_column: str,
    allow_unnamed_index: bool = False,
    replay: UnitHistoricalReplay | None = None,
) -> ScopedFMAttributes:
    """Verify a complete export, then select exactly the active source UID mappings.

    Scope and source clocks are checked before CSV decoding. The existing full
    reader still validates the original-byte hash, every UID and selected trait
    cell in every row. An unmapped malformed row cannot hide behind this filter.
    Missing mapped UIDs refuse. The result carries just the active mappings, so
    inactive attributes cannot leak into UnitInputCatalog through a wider export.
    """
    active = _active_mappings(source, cutoff, mappings, replay)
    parsed = read_fm_attributes(
        payload,
        source=source,
        cutoff=cutoff,
        attributes=attributes,
        attribute_columns=attribute_columns,
        uid_column=uid_column,
        allow_unnamed_index=allow_unnamed_index,
        replay=replay,
    )
    by_uid = {item.source_player_id: item for item in parsed}
    if any(mapping.source_player_id not in by_uid for mapping in active):
        raise ValueError("An active FM scope mapping names a UID absent from the verified export.")
    return ScopedFMAttributes(
        source,
        cutoff,
        active,
        tuple(by_uid[mapping.source_player_id] for mapping in active),
        len(parsed),
        replay=replay,
    )
