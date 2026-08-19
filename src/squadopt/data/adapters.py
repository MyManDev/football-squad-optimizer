"""Explicit mapping from a raw source's layout onto canonical column names.

Everything platform-specific is declared here: raw column names, encoded
position values, and the unit a source stores prices in. Later stages read the
declaration instead of branching on which source produced a frame, which is what
keeps raw column names from ever reaching the optimizer.

Adapters never invent data. A source that does not carry a canonical field
simply cannot be adapted to it, and that is reported instead of filled in.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Literal, TypeAlias

import pandas as pd

from squadopt.data.errors import InvalidValueError, MissingColumnsError
from squadopt.data.schema import (
    CANONICAL_COLUMNS,
    EXTERNALLY_SUPPLIED_COLUMNS,
    REQUIRED_COLUMNS,
    Position,
    canonical_column_order,
    normalize_position,
)

PriceUnit: TypeAlias = Literal["tenths", "units"]
PRICE_UNITS: tuple[PriceUnit, ...] = ("tenths", "units")


def _code_key(value: object) -> str:
    """Normalize a raw encoded value so text and native sources match alike."""

    return str(value).strip().upper()


@dataclass(frozen=True, slots=True)
class SourceAdapter:
    """Declarative description of one raw source's column layout.

    ``column_map`` maps raw column names to canonical ones and must cover every
    required canonical column: an adapter that cannot produce the required schema
    is rejected at construction rather than failing confusingly later. Sources
    split across several files are combined before being adapted.

    ``position_codes`` translates source-specific encodings, such as numeric
    position codes, into canonical labels. Values are validated and normalized
    when the adapter is built, so an encoding that maps to a non-existent
    position cannot be declared at all.

    ``price_unit`` records whether the source stores prices already in integer
    tenths or in whole units such as ``5.5``. The cleaning stage performs the
    conversion; this field only states which one is needed.
    """

    name: str
    column_map: Mapping[str, str]
    position_codes: Mapping[str, str] = field(default_factory=dict)
    price_unit: PriceUnit = "tenths"

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise InvalidValueError("SourceAdapter.name must be a non-empty string.")

        if not isinstance(self.column_map, Mapping) or not self.column_map:
            raise InvalidValueError(
                f"Adapter {self.name!r} must declare a non-empty raw-to-canonical column_map."
            )

        if self.price_unit not in PRICE_UNITS:
            raise InvalidValueError(
                f"Adapter {self.name!r} has unsupported price_unit {self.price_unit!r}; "
                f"expected one of {list(PRICE_UNITS)!r}."
            )

        copied_map: dict[str, str] = {}
        seen_targets: dict[str, str] = {}
        for raw_name, canonical_name in self.column_map.items():
            if not isinstance(raw_name, str) or not raw_name.strip():
                raise InvalidValueError(
                    f"Adapter {self.name!r} has a non-string or empty raw column name: "
                    f"{raw_name!r}."
                )
            if canonical_name not in CANONICAL_COLUMNS:
                raise InvalidValueError(
                    f"Adapter {self.name!r} maps {raw_name!r} to unknown canonical column "
                    f"{canonical_name!r}; expected one of {list(CANONICAL_COLUMNS)!r}."
                )
            if canonical_name in seen_targets:
                raise InvalidValueError(
                    f"Adapter {self.name!r} maps both {seen_targets[canonical_name]!r} and "
                    f"{raw_name!r} to canonical column {canonical_name!r}."
                )
            seen_targets[canonical_name] = raw_name
            copied_map[raw_name] = canonical_name

        uncovered = [
            column
            for column in REQUIRED_COLUMNS
            if column not in seen_targets and column not in EXTERNALLY_SUPPLIED_COLUMNS
        ]
        if uncovered:
            raise MissingColumnsError(
                f"Adapter {self.name!r} does not map any raw column to required canonical "
                f"columns: {uncovered!r}."
            )

        if not isinstance(self.position_codes, Mapping):
            raise InvalidValueError(
                f"Adapter {self.name!r} position_codes must be a mapping of raw code to position."
            )
        normalized_codes: dict[str, Position] = {}
        for raw_code, position in self.position_codes.items():
            key = _code_key(raw_code)
            if not key:
                raise InvalidValueError(
                    f"Adapter {self.name!r} declares an empty raw position code."
                )
            if key in normalized_codes:
                raise InvalidValueError(
                    f"Adapter {self.name!r} declares raw position code {key!r} more than once."
                )
            normalized_codes[key] = normalize_position(position)

        object.__setattr__(self, "column_map", MappingProxyType(copied_map))
        object.__setattr__(self, "position_codes", MappingProxyType(normalized_codes))


# Already-canonical input, such as a previously exported canonical dataset.
IDENTITY_ADAPTER = SourceAdapter(
    name="canonical",
    column_map={column: column for column in CANONICAL_COLUMNS},
)


def apply_adapter(frame: pd.DataFrame, adapter: SourceAdapter) -> pd.DataFrame:
    """Rename a raw frame's columns to canonical names and drop everything else.

    Returns an independent copy; the input frame is never modified. Unmapped
    source columns are dropped rather than passed through, so a raw platform
    column name cannot leak downstream. Optional canonical columns the source
    does not carry are simply absent, never created.

    No type coercion, value normalization, deduplication, or reordering happens
    here beyond translating declared position encodings. Canonical column order
    is applied so output is deterministic regardless of source column order.
    """

    if not isinstance(frame, pd.DataFrame):
        raise InvalidValueError(f"Adapter {adapter.name!r} expects a pandas DataFrame.")

    duplicates = frame.columns[frame.columns.duplicated()].tolist()
    if duplicates:
        raise InvalidValueError(
            f"Source for adapter {adapter.name!r} has duplicate columns: {duplicates!r}."
        )

    available = set(frame.columns)
    missing_required = sorted(
        raw_name
        for raw_name, canonical_name in adapter.column_map.items()
        if canonical_name in REQUIRED_COLUMNS and raw_name not in available
    )
    if missing_required:
        raise MissingColumnsError(
            f"Source for adapter {adapter.name!r} is missing raw columns "
            f"{missing_required!r} needed for required canonical columns; "
            f"source provides {sorted(available)!r}."
        )

    selected = {
        raw_name: canonical_name
        for raw_name, canonical_name in adapter.column_map.items()
        if raw_name in available
    }
    canonical_order = canonical_column_order(selected.values())
    ordered_raw = sorted(selected, key=lambda raw: canonical_order.index(selected[raw]))
    adapted = frame.loc[:, ordered_raw].rename(columns=selected).copy(deep=True)

    if adapter.position_codes and "position" in adapted.columns:
        codes = adapter.position_codes
        adapted["position"] = [
            value if pd.isna(value) else codes.get(_code_key(value), value)
            for value in adapted["position"]
        ]

    return adapted
