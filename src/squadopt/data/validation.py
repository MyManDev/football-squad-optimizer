"""Integrity validation for the cleaned canonical player-gameweek dataset.

Validation judges; it never repairs. Cleaning has already decided types, so a
failure here means the data itself is contradictory, and silently patching it
would hide a source problem the data owner needs to see.

Every rejection names the offending column, key, or values. A message like
"invalid data" forces the reader into a debugger, which is why the duplicate-key
error reports the exact season, gameweek, and player.
"""

import math
from numbers import Integral, Real

import pandas as pd

from squadopt.data.errors import (
    MAX_ERROR_EXAMPLES,
    DuplicateRecordsError,
    InvalidValueError,
    MissingColumnsError,
    format_examples,
)
from squadopt.data.schema import (
    COLUMN_KINDS,
    KEY_COLUMNS,
    MIN_GAMEWEEK,
    NON_NEGATIVE_COLUMNS,
    POSITIONS,
    REQUIRED_COLUMNS,
)


def _require_columns(frame: pd.DataFrame) -> None:
    missing = [column for column in REQUIRED_COLUMNS if column not in frame.columns]
    if missing:
        raise MissingColumnsError(
            f"Canonical dataset is missing required columns: {missing!r}; "
            f"available columns are {sorted(frame.columns)!r}."
        )


def _require_complete(frame: pd.DataFrame) -> None:
    incomplete = [column for column in REQUIRED_COLUMNS if bool(frame[column].isna().any())]
    if incomplete:
        raise InvalidValueError(f"Required columns contain missing values: {incomplete!r}.")


def _require_unique_key(frame: pd.DataFrame) -> None:
    duplicated = frame.duplicated(subset=list(KEY_COLUMNS), keep=False)
    if not bool(duplicated.any()):
        return

    offenders = frame.loc[duplicated, list(KEY_COLUMNS)].drop_duplicates()
    # `tolist` rather than `iterrows`: it yields native Python scalars, so the
    # message reads `gameweek=4` instead of leaking `np.int64(4)` at the reader.
    key_values = {column: offenders[column].tolist() for column in KEY_COLUMNS}
    descriptions = [
        ", ".join(f"{column}={key_values[column][position]!r}" for column in KEY_COLUMNS)
        for position in range(len(offenders))
    ]
    shown = "; ".join(descriptions[:MAX_ERROR_EXAMPLES])
    if len(descriptions) > MAX_ERROR_EXAMPLES:
        shown += f"; ... ({len(descriptions)} duplicated keys total)"
    raise DuplicateRecordsError(f"Duplicate player-gameweek records found for {shown}.")


def _require_identifier_consistency(frame: pd.DataFrame, column: str) -> None:
    """Refuse a mix of integer and text identifiers within one column.

    The optimizer checks identifier type element-wise and rejects a column that
    uses both, so catching it here keeps the failure close to its cause.
    """

    kinds: set[str] = set()
    invalid: list[object] = []
    for value in frame[column].tolist():
        if isinstance(value, bool):
            invalid.append(value)
        elif isinstance(value, Integral):
            kinds.add("integer")
        elif isinstance(value, str) and value.strip():
            kinds.add("string")
        else:
            invalid.append(value)
    if invalid:
        raise InvalidValueError(
            f"Column {column!r} must contain non-empty text or integer identifiers; "
            f"invalid values: {format_examples(invalid)}."
        )
    if len(kinds) > 1:
        raise InvalidValueError(
            f"Column {column!r} mixes identifier types {sorted(kinds)!r}; "
            "one consistent type per column is required."
        )


def _require_non_empty_text(frame: pd.DataFrame, column: str) -> None:
    invalid = [
        value for value in frame[column].tolist() if not isinstance(value, str) or not value.strip()
    ]
    if invalid:
        raise InvalidValueError(
            f"Column {column!r} must contain non-empty text; "
            f"invalid values: {format_examples(invalid)}."
        )


def _require_gameweek_range(frame: pd.DataFrame, max_gameweek: int | None) -> None:
    values = frame["gameweek"].tolist()
    non_integer = [
        value for value in values if isinstance(value, bool) or not isinstance(value, Integral)
    ]
    if non_integer:
        raise InvalidValueError(
            "Column 'gameweek' must contain integers; "
            f"invalid values: {format_examples(non_integer)}."
        )
    too_small = [int(value) for value in values if int(value) < MIN_GAMEWEEK]
    if too_small:
        raise InvalidValueError(
            f"Column 'gameweek' must be at least {MIN_GAMEWEEK}; "
            f"invalid values: {format_examples(too_small)}."
        )
    if max_gameweek is not None:
        too_large = [int(value) for value in values if int(value) > max_gameweek]
        if too_large:
            raise InvalidValueError(
                f"Column 'gameweek' must be at most {max_gameweek}; "
                f"invalid values: {format_examples(too_large)}."
            )


def _require_positions(frame: pd.DataFrame) -> None:
    invalid = [value for value in frame["position"].tolist() if value not in POSITIONS]
    if invalid:
        raise InvalidValueError(
            f"Column 'position' contains values outside {list(POSITIONS)!r}: "
            f"{format_examples(dict.fromkeys(invalid))}."
        )


def _require_integer_column(frame: pd.DataFrame, column: str) -> None:
    invalid = [
        value
        for value in frame[column].tolist()
        if isinstance(value, bool) or not isinstance(value, Integral)
    ]
    if invalid:
        raise InvalidValueError(
            f"Column {column!r} must contain integers; invalid values: {format_examples(invalid)}."
        )


def _require_finite_numeric(frame: pd.DataFrame, column: str) -> None:
    invalid = [
        value
        for value in frame[column].tolist()
        if (
            isinstance(value, bool)
            or not isinstance(value, Real)
            or not math.isfinite(float(value))
        )
    ]
    if invalid:
        raise InvalidValueError(
            f"Column {column!r} must contain finite numbers; "
            f"invalid values: {format_examples(invalid)}."
        )


def _require_non_negative(frame: pd.DataFrame, column: str) -> None:
    negative = [value for value in frame[column].tolist() if float(value) < 0]
    if negative:
        raise InvalidValueError(
            f"Column {column!r} must not be negative; invalid values: {format_examples(negative)}."
        )


def validate_canonical_dataset(
    frame: pd.DataFrame,
    *,
    max_gameweek: int | None = None,
) -> pd.DataFrame:
    """Validate a cleaned canonical dataset and return an independent copy.

    Checks structure (required columns, completeness), identity (unique
    season/gameweek/player key, one identifier type per column), and semantics
    (gameweek range, controlled positions, non-negative quantities).

    ``total_points`` is deliberately allowed to be negative: cards and own goals
    produce genuinely negative scores, and clamping realized results would
    corrupt the history. Only projections are clamped, and that happens later.
    """

    if not isinstance(frame, pd.DataFrame):
        raise InvalidValueError("validate_canonical_dataset expects a pandas DataFrame.")

    duplicate_columns = frame.columns[frame.columns.duplicated()].tolist()
    if duplicate_columns:
        raise InvalidValueError(f"Duplicate columns are not allowed: {duplicate_columns!r}.")

    _require_columns(frame)

    validated = frame.copy(deep=True)
    _require_complete(validated)
    _require_unique_key(validated)

    _require_non_empty_text(validated, "season")
    _require_non_empty_text(validated, "name")
    _require_identifier_consistency(validated, "player_id")
    _require_identifier_consistency(validated, "team_id")
    _require_gameweek_range(validated, max_gameweek)
    _require_positions(validated)
    _require_integer_column(validated, "price_tenths")

    for column in validated.columns:
        kind = COLUMN_KINDS.get(column)
        if kind == "integer":
            _require_integer_column(validated, column)
        elif kind == "float":
            _require_finite_numeric(validated, column)
        elif kind == "identifier" and column not in ("player_id", "team_id"):
            _require_identifier_consistency(validated, column)

    for column in NON_NEGATIVE_COLUMNS:
        if column in validated.columns:
            _require_non_negative(validated, column)

    return validated
