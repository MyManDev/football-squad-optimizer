"""Thin integration helpers for canonical projection data."""

from os import PathLike

import pandas as pd

from squadopt.optimization import OptimizationConfig, OptimizationResult, optimize_squad


def optimize_squad_from_csv(
    path: str | PathLike[str],
    config: OptimizationConfig,
) -> OptimizationResult:
    """Read canonical player projections from CSV and optimize the squad.

    The CSV must already follow the canonical player schema. This adapter does
    not normalize identifiers, positions, prices, or projections; validation is
    delegated to :func:`optimize_squad`.
    """

    players = pd.read_csv(path, encoding="utf-8")
    return optimize_squad(players, config)
