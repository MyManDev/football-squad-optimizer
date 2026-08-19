"""Local file loaders for raw player-gameweek data.

Loaders read; they do not transform. Renaming, type coercion, normalization,
deduplication, and ordering all belong to later stages. Keeping this boundary
sharp means a faithful record of what the file actually contained is still
available when a validation error has to name the offending value.

Nothing here reaches the network. Live fetching and scraping are out of scope.
"""

from pathlib import Path

import pandas as pd

from squadopt.data.errors import DataSourceError

CSV_SUFFIXES: tuple[str, ...] = (".csv",)
PARQUET_SUFFIXES: tuple[str, ...] = (".parquet", ".pq")


def _resolve_existing_file(path: str | Path) -> Path:
    resolved = Path(path)
    if not resolved.exists():
        raise DataSourceError(f"Data source not found: {resolved}")
    if not resolved.is_file():
        raise DataSourceError(f"Data source is not a readable file: {resolved}")
    return resolved


def load_csv(path: str | Path) -> pd.DataFrame:
    """Read a CSV with every column as text, deferring all type decisions.

    Text is read verbatim so pandas type inference cannot quietly reinterpret
    the file: identifiers keep leading zeros, wide integers keep their digits,
    and no column is promoted to float merely because one of its rows was empty.
    Empty fields still arrive as missing values, so validation can detect them.
    """

    resolved = _resolve_existing_file(path)
    try:
        return pd.read_csv(resolved, dtype=str)
    except (OSError, ValueError, pd.errors.ParserError) as error:
        raise DataSourceError(f"Failed to read CSV {resolved}: {error}") from error


def load_parquet(path: str | Path) -> pd.DataFrame:
    """Read a Parquet file, preserving the dtypes recorded in the file.

    Unlike the CSV loader this keeps native types, because Parquet stores them
    explicitly and re-reading them as text would discard information. Cleaning
    coercion therefore has to accept both text and native input.

    Parquet needs an engine that is not a required project dependency, so a
    missing engine is reported as a data-source problem rather than propagating
    a bare ``ImportError``.
    """

    resolved = _resolve_existing_file(path)
    try:
        return pd.read_parquet(resolved)
    except ImportError as error:
        raise DataSourceError(
            f"Reading Parquet requires an engine that is not installed "
            f"(install 'pyarrow' or use CSV instead): {error}"
        ) from error
    except (OSError, ValueError) as error:
        raise DataSourceError(f"Failed to read Parquet {resolved}: {error}") from error


def load_local_dataset(path: str | Path) -> pd.DataFrame:
    """Read a local dataset, choosing the reader from the file suffix."""

    resolved = Path(path)
    suffix = resolved.suffix.lower()
    if suffix in CSV_SUFFIXES:
        return load_csv(resolved)
    if suffix in PARQUET_SUFFIXES:
        return load_parquet(resolved)
    supported = [*CSV_SUFFIXES, *PARQUET_SUFFIXES]
    raise DataSourceError(
        f"Unsupported data source suffix {resolved.suffix!r} for {resolved}; "
        f"expected one of {supported!r}."
    )
