"""Deterministic integer objective coefficients shared with experiment runners."""

import hashlib
import json
from collections.abc import Sequence
from decimal import ROUND_HALF_UP, Decimal
from numbers import Integral

import pandas as pd

from squadopt.optimization.config import POSITIONS, OptimizationConfig


def round_half_up(value: Decimal) -> int:
    """Round one decimal value to an integer using the optimizer's declared rule."""

    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def scale_expected_points(value: object, scale: int) -> int:
    """Convert a validated projection to its exact CP-SAT integer coefficient."""

    return round_half_up(Decimal(str(value)) * scale)


def scale_bench_coefficient(scaled_points: int, bench_weight: float) -> int:
    """Convert a bench contribution to its exact CP-SAT integer coefficient."""

    return round_half_up(Decimal(scaled_points) * Decimal(str(bench_weight)))


def objective_coefficients(
    expected_points: Sequence[object],
    config: OptimizationConfig,
) -> tuple[tuple[int, int, int], ...]:
    """Return ``(squad, starter, captain)`` coefficients for every player."""

    rows: list[tuple[int, int, int]] = []
    for value in expected_points:
        points = scale_expected_points(value, config.expected_points_scale)
        bench = scale_bench_coefficient(points, config.bench_weight)
        rows.append((bench, points - bench, points))
    return tuple(rows)


def sort_players_by_id(players: pd.DataFrame) -> pd.DataFrame:
    """Return the stable player ordering used by the model and its fingerprints."""

    player_ids = players["player_id"].tolist()
    if player_ids and isinstance(player_ids[0], Integral):
        order = sorted(range(len(players)), key=lambda index: int(player_ids[index]))
    else:
        order = sorted(range(len(players)), key=lambda index: str(player_ids[index]))
    return players.iloc[order].reset_index(drop=True).copy(deep=True)


def _typed_identifier(value: object) -> dict[str, object]:
    if isinstance(value, Integral) and not isinstance(value, bool):
        return {"kind": "integer", "value": int(value)}
    return {"kind": "string", "value": str(value)}


def objective_coefficient_fingerprint(
    players: pd.DataFrame,
    config: OptimizationConfig,
) -> str:
    """Fingerprint the exact integer objective and feasible-set inputs.

    Callers validate the canonical player contract before invoking this function.
    Static model inputs are included alongside the integer coefficients so a digest
    collision cannot incorrectly equate candidates with different feasible sets.
    """

    ordered = sort_players_by_id(players)
    coefficients = objective_coefficients(ordered["expected_points"].tolist(), config)
    player_rows = []
    for row, coefficient in zip(ordered.to_dict("records"), coefficients, strict=True):
        player_rows.append(
            {
                "player_id": _typed_identifier(row["player_id"]),
                "team_id": _typed_identifier(row["team_id"]),
                "position": str(row["position"]),
                "price_tenths": int(row["price_tenths"]),
                "objective_coefficients": list(coefficient),
            }
        )

    payload = {
        "coefficient_contract": "cp_sat_objective_v1",
        "players": player_rows,
        "constraints": {
            "budget_tenths": config.budget_tenths,
            "squad_size": config.squad_size,
            "squad_position_limits": [
                [position, config.squad_position_limits[position]] for position in POSITIONS
            ],
            "starting_size": config.starting_size,
            "starting_position_min": [
                [position, config.starting_position_min[position]] for position in POSITIONS
            ],
            "starting_position_max": [
                [position, config.starting_position_max[position]] for position in POSITIONS
            ],
            "max_players_per_team": config.max_players_per_team,
            "expected_points_scale": config.expected_points_scale,
        },
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
