"""Thin integration helpers for canonical projection data."""

from os import PathLike
from pathlib import Path

import pandas as pd

from squadopt.data import load_csv
from squadopt.optimization import OptimizationConfig, OptimizationResult, optimize_squad
from squadopt.optimization.models import InvalidPlayerDataError


def _coerce_projection_numeric_columns(players: pd.DataFrame) -> pd.DataFrame:
    """Convert numeric projection columns without inferring identifier types."""

    converted = players.copy(deep=True)
    for column in ("price_tenths", "expected_points"):
        if column not in converted.columns:
            continue
        try:
            converted[column] = pd.to_numeric(converted[column], errors="raise")
        except (TypeError, ValueError) as error:
            raise InvalidPlayerDataError(
                f"{column} CSV values must be numeric; failed to parse the column: {error}"
            ) from error
    return converted


def optimize_squad_from_csv(
    path: str | PathLike[str],
    config: OptimizationConfig,
) -> OptimizationResult:
    """Read canonical player projections from CSV and optimize the squad.

    The CSV must already follow the canonical player schema. Identifier columns
    are read as text so lexical identities such as ``007`` are preserved. The
    adapter parses the two numeric contract columns but does not normalize
    positions, convert decimal prices to tenths, or calculate projections;
    semantic validation is delegated to :func:`optimize_squad`.
    """

    players = _coerce_projection_numeric_columns(load_csv(Path(path)))
    return optimize_squad(players, config)
