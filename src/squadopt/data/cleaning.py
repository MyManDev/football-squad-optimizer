"""Type coercion and value normalization for canonical player-gameweek data.

Cleaning turns whatever a source provided into the canonical representation, and
names the offending value when it cannot. It is deliberately the only place where
types change: loaders read faithfully and validation only judges, so a coercion
bug has exactly one home.

Coercion is lossless by construction. A text identifier only becomes an integer
when the integer round-trips back to the same text, so an identifier written
``007`` keeps its leading zero instead of silently colliding with ``7``.

Values are converted one at a time rather than with vectorized casts. Vectorized
casting is faster but reports failures as an opaque column-wide error, and an
actionable message naming the bad record matters more than speed at Sprint 0
data sizes.
"""

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from numbers import Integral, Real

import pandas as pd

from squadopt.data.adapters import PriceUnit
from squadopt.data.errors import InvalidValueError, format_examples
from squadopt.data.schema import (
    COLUMN_KINDS,
    PRICE_TENTHS_PER_UNIT,
    ColumnKind,
    canonical_column_order,
    normalize_position,
)

_ONE = Decimal(1)


def _reject_missing(series: pd.Series, column: str) -> None:
    """Refuse missing values, which would otherwise force a nullable dtype.

    A single missing value promotes an integer column to float, and the optimizer
    checks ``price_tenths`` element-wise against ``numbers.Integral``, so the
    whole projection table would be rejected far away from the real cause.
    """

    missing = series.isna()
    if bool(missing.any()):
        raise InvalidValueError(
            f"Column {column!r} contains {int(missing.sum())} missing values at positions "
            f"{format_examples(series.index[missing].tolist())}; canonical data must be "
            "complete, so supply the values or drop the column."
        )


def _as_decimal(value: object, column: str) -> Decimal:
    """Convert one value to a finite Decimal, refusing booleans and junk text."""

    if isinstance(value, bool):
        raise InvalidValueError(f"Column {column!r} must not contain booleans; got {value!r}.")
    if isinstance(value, Decimal):
        candidate = value
    elif isinstance(value, Integral):
        candidate = Decimal(int(value))
    elif isinstance(value, Real):
        candidate = Decimal(str(float(value)))
    elif isinstance(value, str):
        try:
            candidate = Decimal(value.strip())
        except InvalidOperation:
            raise InvalidValueError(f"Column {column!r} expects a number; got {value!r}.") from None
    else:
        raise InvalidValueError(
            f"Column {column!r} expects a number; got {value!r} of type {type(value).__name__}."
        )
    if not candidate.is_finite():
        raise InvalidValueError(f"Column {column!r} must be finite; got {value!r}.")
    return candidate


def _coerce_integer(value: object, column: str) -> int:
    """Convert one value to an integer, refusing fractional input.

    Leading zeros are accepted here because they are mere formatting for a
    quantity. That is the opposite of the identifier rule, where a leading zero
    is part of the identity.
    """

    if isinstance(value, bool):
        raise InvalidValueError(f"Column {column!r} must not contain booleans; got {value!r}.")
    if isinstance(value, Integral):
        return int(value)
    candidate = _as_decimal(value, column)
    if candidate != candidate.to_integral_value():
        raise InvalidValueError(
            f"Column {column!r} expects whole numbers; got the fractional value {value!r}."
        )
    return int(candidate)


def _coerce_boolean(value: object, column: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, Integral) and int(value) in (0, 1):
        return bool(int(value))
    if isinstance(value, str):
        text = value.strip().lower()
        if text in ("true", "1", "yes"):
            return True
        if text in ("false", "0", "no"):
            return False
    raise InvalidValueError(f"Column {column!r} expects a boolean; got {value!r}.")


def _coerce_text(value: object, column: str) -> str:
    if isinstance(value, bool) or not isinstance(value, str | Integral | Real):
        raise InvalidValueError(f"Column {column!r} expects text; got {value!r}.")
    text = str(value).strip()
    if not text:
        raise InvalidValueError(f"Column {column!r} must not contain blank text.")
    return text


def _coerce_identifier_column(series: pd.Series, column: str) -> pd.Series:
    """Return int64 when every value round-trips exactly, otherwise text.

    Integers are preferred because they sort and compare naturally, but only when
    the conversion is provably reversible. As soon as one value would lose
    information the entire column stays text, because the contract requires one
    consistent identifier type per column.
    """

    texts: list[str] = []
    integers: list[int] = []
    reversible = True
    for value in series.tolist():
        if isinstance(value, bool):
            raise InvalidValueError(f"Column {column!r} must not contain booleans; got {value!r}.")
        if isinstance(value, Integral):
            parsed = int(value)
            integers.append(parsed)
            texts.append(str(parsed))
            continue
        if not isinstance(value, str):
            raise InvalidValueError(
                f"Column {column!r} expects an integer or text identifier; got {value!r} "
                f"of type {type(value).__name__}."
            )
        text = value.strip()
        if not text:
            raise InvalidValueError(f"Column {column!r} must not contain blank identifiers.")
        texts.append(text)
        try:
            parsed = int(text)
        except ValueError:
            reversible = False
            continue
        if str(parsed) != text:
            # Leading zeros, explicit signs, or padding: converting would change identity.
            reversible = False
            continue
        integers.append(parsed)

    if reversible and len(integers) == len(texts):
        return pd.Series(integers, index=series.index, dtype="int64")
    return pd.Series(texts, index=series.index, dtype="string")


def to_price_tenths(values: pd.Series, *, unit: PriceUnit) -> pd.Series:
    """Convert a price column to non-nullable integer tenths.

    ``unit="tenths"`` means the source already stores integer tenths, so a
    fractional value is an error rather than something to round. ``unit="units"``
    means whole currency units such as ``5.5``, which are multiplied by ten with
    decimal arithmetic and ROUND_HALF_UP, matching the optimizer's convention.

    Binary floating point is never used for this: ``5.5 * 10`` is not exactly
    ``55`` in binary, and a price that is one tenth off changes which squads are
    affordable.
    """

    _reject_missing(values, "price_tenths")
    if unit == "tenths":
        converted = [_coerce_integer(value, "price_tenths") for value in values.tolist()]
        return pd.Series(converted, index=values.index, dtype="int64")

    scaled: list[int] = []
    for value in values.tolist():
        candidate = _as_decimal(value, "price_tenths") * PRICE_TENTHS_PER_UNIT
        scaled.append(int(candidate.quantize(_ONE, rounding=ROUND_HALF_UP)))
    return pd.Series(scaled, index=values.index, dtype="int64")


def normalize_positions(values: pd.Series) -> pd.Series:
    """Map a position column onto the canonical GK/DEF/MID/FWD vocabulary."""

    _reject_missing(values, "position")
    normalized = [normalize_position(value) for value in values.tolist()]
    return pd.Series(normalized, index=values.index, dtype="string")


def _clean_column(series: pd.Series, column: str, kind: ColumnKind) -> pd.Series:
    _reject_missing(series, column)
    if kind == "identifier":
        return _coerce_identifier_column(series, column)
    if kind == "position":
        return normalize_positions(series)
    if kind == "integer":
        return pd.Series(
            [_coerce_integer(value, column) for value in series.tolist()],
            index=series.index,
            dtype="int64",
        )
    if kind == "float":
        return pd.Series(
            [float(_as_decimal(value, column)) for value in series.tolist()],
            index=series.index,
            dtype="float64",
        )
    if kind == "boolean":
        return pd.Series(
            [_coerce_boolean(value, column) for value in series.tolist()],
            index=series.index,
            dtype="bool",
        )
    return pd.Series(
        [_coerce_text(value, column) for value in series.tolist()],
        index=series.index,
        dtype="string",
    )


def clean_canonical_dataset(
    frame: pd.DataFrame, *, price_unit: PriceUnit = "tenths"
) -> pd.DataFrame:
    """Coerce an adapted frame into the canonical representation.

    Returns an independent copy; the input frame is never modified. Every
    recognized canonical column is converted according to its declared kind, and
    columns are placed in canonical order so output does not inherit whatever
    order the source happened to use.

    Row order, duplicate detection, and semantic range checks are not this
    function's job: ordering is imposed by the pipeline and integrity is judged by
    validation.
    """

    if not isinstance(frame, pd.DataFrame):
        raise InvalidValueError("clean_canonical_dataset expects a pandas DataFrame.")

    duplicates = frame.columns[frame.columns.duplicated()].tolist()
    if duplicates:
        raise InvalidValueError(f"Duplicate columns are not allowed: {duplicates!r}.")

    cleaned: dict[str, pd.Series] = {}
    for column in frame.columns:
        series = frame[column]
        if column == "price_tenths":
            cleaned[column] = to_price_tenths(series, unit=price_unit)
            continue
        kind = COLUMN_KINDS.get(column)
        if kind is None:
            # Unrecognized columns are carried through untouched rather than
            # guessed at; adapters are responsible for dropping source noise.
            cleaned[column] = series.copy(deep=True)
            continue
        cleaned[column] = _clean_column(series, column, kind)

    result = pd.DataFrame(cleaned, index=frame.index.copy())
    return result.loc[:, canonical_column_order(result.columns)]
