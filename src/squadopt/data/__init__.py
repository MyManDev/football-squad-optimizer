"""Canonical data layer.

Converts local raw player-gameweek records into a validated, cleaned, and
deterministically ordered canonical dataset. The layer is platform-independent:
raw column names, source quirks, and cleaning rules never reach the optimizer.
"""

from squadopt.data.adapters import (
    IDENTITY_ADAPTER,
    PRICE_UNITS,
    PriceUnit,
    SourceAdapter,
    apply_adapter,
)
from squadopt.data.cleaning import (
    clean_canonical_dataset,
    normalize_positions,
    to_price_tenths,
)
from squadopt.data.errors import (
    DataError,
    DataSourceError,
    DataValidationError,
    DuplicateRecordsError,
    InvalidValueError,
    MissingColumnsError,
)
from squadopt.data.loaders import (
    CSV_SUFFIXES,
    PARQUET_SUFFIXES,
    load_csv,
    load_local_dataset,
    load_parquet,
)
from squadopt.data.pipeline import build_canonical_dataset
from squadopt.data.schema import (
    AMBIGUOUS_TIMING_COLUMNS,
    CANONICAL_COLUMNS,
    CANONICAL_SORT_COLUMNS,
    COLUMN_KINDS,
    EXTERNALLY_SUPPLIED_COLUMNS,
    KEY_COLUMNS,
    MIN_GAMEWEEK,
    NON_NEGATIVE_COLUMNS,
    OPTIONAL_COLUMNS,
    OUTCOME_COLUMNS,
    PLAYER_GROUP_COLUMNS,
    PLAYER_TIME_SORT_COLUMNS,
    POSITION_ALIASES,
    POSITIONS,
    PRE_MATCH_COLUMNS,
    PRICE_TENTHS_PER_UNIT,
    PROJECTION_REQUIRED_COLUMNS,
    REQUIRED_COLUMNS,
    ColumnKind,
    Position,
    canonical_column_order,
    is_outcome_column,
    normalize_position,
)
from squadopt.data.validation import validate_canonical_dataset

__all__ = [
    "AMBIGUOUS_TIMING_COLUMNS",
    "CANONICAL_COLUMNS",
    "CANONICAL_SORT_COLUMNS",
    "COLUMN_KINDS",
    "CSV_SUFFIXES",
    "EXTERNALLY_SUPPLIED_COLUMNS",
    "IDENTITY_ADAPTER",
    "KEY_COLUMNS",
    "MIN_GAMEWEEK",
    "NON_NEGATIVE_COLUMNS",
    "OPTIONAL_COLUMNS",
    "OUTCOME_COLUMNS",
    "PARQUET_SUFFIXES",
    "PLAYER_GROUP_COLUMNS",
    "PLAYER_TIME_SORT_COLUMNS",
    "POSITIONS",
    "POSITION_ALIASES",
    "PRE_MATCH_COLUMNS",
    "PRICE_TENTHS_PER_UNIT",
    "PRICE_UNITS",
    "PROJECTION_REQUIRED_COLUMNS",
    "REQUIRED_COLUMNS",
    "ColumnKind",
    "DataError",
    "DataSourceError",
    "DataValidationError",
    "DuplicateRecordsError",
    "InvalidValueError",
    "MissingColumnsError",
    "Position",
    "PriceUnit",
    "SourceAdapter",
    "apply_adapter",
    "build_canonical_dataset",
    "canonical_column_order",
    "clean_canonical_dataset",
    "is_outcome_column",
    "load_csv",
    "load_local_dataset",
    "load_parquet",
    "normalize_position",
    "normalize_positions",
    "to_price_tenths",
    "validate_canonical_dataset",
]
