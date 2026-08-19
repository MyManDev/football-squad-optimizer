"""Validation for the canonical player DataFrame."""

from collections.abc import Sequence
from decimal import Decimal, InvalidOperation
from numbers import Integral, Real

import pandas as pd

from squadopt.optimization.config import POSITIONS, OptimizationConfig
from squadopt.optimization.models import (
    InsufficientPlayerPoolError,
    InvalidPlayerDataError,
)

REQUIRED_COLUMNS: tuple[str, ...] = (
    "player_id",
    "name",
    "team_id",
    "position",
    "price_tenths",
    "expected_points",
)
MAX_ERROR_EXAMPLES = 10


def _examples(values: Sequence[object]) -> list[object]:
    return list(values[:MAX_ERROR_EXAMPLES])


def _identifier_kind(value: object) -> str | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, Integral):
        return "integer"
    if isinstance(value, str) and value.strip():
        return "string"
    return None


def _validate_identifier_column(players: pd.DataFrame, column: str) -> None:
    values = players[column].tolist()
    invalid: list[object] = []
    kinds: set[str] = set()
    for value in values:
        kind = _identifier_kind(value)
        if kind is None:
            invalid.append(value)
        else:
            kinds.add(kind)
    if invalid:
        raise InvalidPlayerDataError(
            f"{column} values must be non-empty strings or integers; "
            f"invalid examples: {_examples(invalid)!r}."
        )
    if len(kinds) > 1:
        raise InvalidPlayerDataError(
            f"{column} must use one consistent ID type; found {sorted(kinds)!r}."
        )


def _validate_expected_points(players: pd.DataFrame) -> None:
    invalid: list[object] = []
    for value in players["expected_points"].tolist():
        if isinstance(value, bool) or not isinstance(value, (Real, Decimal)):
            invalid.append(value)
            continue
        try:
            decimal_value = Decimal(str(value))
        except (InvalidOperation, ValueError):
            invalid.append(value)
            continue
        if not decimal_value.is_finite() or decimal_value < 0:
            invalid.append(value)
    if invalid:
        raise InvalidPlayerDataError(
            "expected_points values must be finite, numeric, and non-negative; "
            f"invalid examples: {_examples(invalid)!r}."
        )


def validate_players(
    players: pd.DataFrame,
    config: OptimizationConfig,
) -> pd.DataFrame:
    """Validate player data and return an independent copy."""

    if not isinstance(players, pd.DataFrame):
        raise InvalidPlayerDataError("players must be a pandas DataFrame.")

    duplicate_columns = players.columns[players.columns.duplicated()].tolist()
    if duplicate_columns:
        raise InvalidPlayerDataError(
            f"Duplicate DataFrame columns are not allowed: {_examples(duplicate_columns)!r}."
        )

    missing_columns = [column for column in REQUIRED_COLUMNS if column not in players.columns]
    if missing_columns:
        raise InvalidPlayerDataError(f"Missing required columns: {missing_columns!r}.")

    validated = players.copy(deep=True)
    columns_with_missing = [
        column for column in REQUIRED_COLUMNS if bool(validated[column].isna().any())
    ]
    if columns_with_missing:
        raise InvalidPlayerDataError(
            f"Required columns contain missing values: {columns_with_missing!r}."
        )

    _validate_identifier_column(validated, "player_id")
    _validate_identifier_column(validated, "team_id")

    invalid_names = [
        value
        for value in validated["name"].tolist()
        if not isinstance(value, str) or not value.strip()
    ]
    if invalid_names:
        raise InvalidPlayerDataError(
            "name values must be non-empty strings; "
            f"invalid examples: {_examples(invalid_names)!r}."
        )

    duplicate_player_ids = (
        validated.loc[validated["player_id"].duplicated(keep=False), "player_id"]
        .drop_duplicates()
        .tolist()
    )
    if duplicate_player_ids:
        raise InvalidPlayerDataError(
            f"Duplicate player_id values: {_examples(duplicate_player_ids)!r}."
        )

    invalid_positions = [
        value for value in validated["position"].tolist() if value not in POSITIONS
    ]
    if invalid_positions:
        raise InvalidPlayerDataError(
            f"Invalid positions: {_examples(list(dict.fromkeys(invalid_positions)))!r}; "
            f"expected one of {list(POSITIONS)!r}."
        )

    invalid_prices = [
        value
        for value in validated["price_tenths"].tolist()
        if isinstance(value, bool) or not isinstance(value, Integral) or int(value) < 0
    ]
    if invalid_prices:
        raise InvalidPlayerDataError(
            "price_tenths values must be non-negative integers; "
            f"invalid examples: {_examples(invalid_prices)!r}."
        )

    _validate_expected_points(validated)

    if len(validated) < config.squad_size:
        raise InsufficientPlayerPoolError(
            f"Insufficient total players: required {config.squad_size}, available {len(validated)}."
        )
    for position in POSITIONS:
        available = int((validated["position"] == position).sum())
        required = config.squad_position_limits[position]
        if available < required:
            raise InsufficientPlayerPoolError(
                f"Insufficient {position} players: required {required}, available {available}."
            )

    return validated
