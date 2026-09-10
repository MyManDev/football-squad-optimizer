"""Semantic checks shared by chip publication, API reads and recorded settlement."""

import math
from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any

from squadopt.data.errors import DataError
from squadopt.evaluation.scoring import (
    FPL_SQUAD_POSITION_LIMITS,
    FPL_STARTING_POSITION_MAX,
    FPL_STARTING_POSITION_MIN,
)


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise DataError(f"Invalid chip recommendation: {message}.")


def _number(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool) and math.isfinite(value)


def _identity(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _lineup(decision: Mapping[str, Any]) -> None:
    starters, bench = decision["starting_xi"], decision["bench"]
    _require(isinstance(starters, list) and isinstance(bench, list), "missing lineup")
    _require(
        len(starters) == 11 and len(bench) == 4, "lineup must contain 11 starters and 4 reserves"
    )
    players = [*starters, *bench]
    ids = [row["player_id"] for row in players]
    _require(
        all(_identity(code) for code in ids) and len(set(ids)) == 15,
        "duplicate or invalid player IDs",
    )
    captain, vice = decision["captain"]["player_id"], decision["vice_captain"]["player_id"]
    _require(
        captain in ids[:11] and vice in ids[:11] and captain != vice, "invalid captain or vice"
    )
    squad_counts = Counter(row["position"] for row in players)
    starter_counts = Counter(row["position"] for row in starters)
    _require(dict(squad_counts) == FPL_SQUAD_POSITION_LIMITS, "invalid squad position quotas")
    _require(
        all(
            minimum <= starter_counts[position] <= FPL_STARTING_POSITION_MAX[position]
            for position, minimum in FPL_STARTING_POSITION_MIN.items()
        ),
        "invalid starting formation",
    )
    for key in ("captain", "vice_captain"):
        reference = next(row for row in starters if row["player_id"] == decision[key]["player_id"])
        _require(reference == decision[key], "armband metadata differs from its starter")
    _require(_number(decision["expected_own_points"]), "invalid expected points")
    hits = decision["transfer_hit_points"]
    _require(_number(hits) and hits >= 0, "invalid hit charge")


def validate_chip_recommendations(value: Any, *, gameweeks: Sequence[int]) -> None:
    """Reject contradictory but individually well-typed fields before any publication.

    JSON shape validation belongs to the wire adapter. These relationships also apply
    to immutable records and pure producer output, so they live below that adapter.
    """
    try:
        _validate(value, gameweeks=gameweeks)
    except (KeyError, TypeError, ValueError, AttributeError) as error:
        raise DataError("Invalid chip recommendation: malformed or missing fields.") from error


def _validate(value: Any, *, gameweeks: Sequence[int]) -> None:
    _require(isinstance(value, Mapping), "missing block")
    _require(value["contract_version"] == "member_chip_recommendations_v1", "unknown version")
    _require(
        isinstance(value["planning_policy_id"], str) and bool(value["planning_policy_id"].strip()),
        "missing policy identity",
    )
    control_gap = value["control_optimality_gap"]
    _require(
        control_gap is None or (_number(control_gap) and control_gap >= 0), "invalid control gap"
    )
    weeks = value["gameweeks"]
    _require(isinstance(weeks, list) and len(weeks) in (1, 3, 5), "invalid horizon length")
    _require(all(_identity(week) for week in weeks), "invalid gameweek")
    _require(
        weeks == list(gameweeks) == list(range(weeks[0], weeks[0] + len(weeks))),
        "horizon differs from advice",
    )
    _require(value["control_solver_status"] in ("OPTIMAL", "FEASIBLE"), "control has no solution")
    comparisons = value["comparisons"]
    _require(isinstance(comparisons, list), "missing comparisons")
    seen: dict[str, list[tuple[int, int]]] = {}
    for row in comparisons:
        chip = row["chip"]
        _require(chip in ("3xc", "bboost", "wildcard", "freehit"), "unknown chip")
        start, stop = row["available_from_gameweek"], row["last_usable_gameweek"]
        _require(_identity(start) and _identity(stop) and start <= stop, "invalid chip window")
        _require(_identity(row["remaining"]), "invalid remaining count")
        _require(
            all(stop < low or start > high for low, high in seen.get(chip, [])),
            "duplicate or overlapping chip windows",
        )
        seen.setdefault(chip, []).append((start, stop))
        available = any(start <= week <= stop for week in weeks)
        gain, decision = row["expected_points_gain"], row["decision"]
        _require(gain is None or _number(gain), "invalid price")
        for gap in (row["optimality_gap"], value["control_optimality_gap"]):
            _require(gap is None or (_number(gap) and gap >= 0), "invalid solver gap")
        if row["action"] == "play":
            week = row["gameweek"]
            _require(
                _identity(week) and week in weeks and start <= week <= stop,
                "play week outside window",
            )
            _require(
                row["reason"] == "window_gain" and gain is not None and gain > 0,
                "play needs a positive price",
            )
            _require(row["solver_status"] in ("OPTIMAL", "FEASIBLE"), "alternative has no solution")
            _require(isinstance(decision, Mapping), "play needs its frozen decision")
            _require(
                decision["gameweek"] == week and decision["chip"] == chip,
                "decision disagrees with recommendation",
            )
            _lineup(decision)
        else:
            _require(
                row["action"] == "hold" and row["gameweek"] is None and decision is None,
                "hold must not name a played decision",
            )
            if row["reason"] == "outside_horizon":
                _require(
                    not available
                    and gain is None
                    and row["solver_status"] is None
                    and row["optimality_gap"] is None,
                    "outside window cannot have a price or solution",
                )
            else:
                _require(row["reason"] == "no_positive_gain" and available, "invalid hold reason")
                _require(gain is None or gain <= 0, "hold cannot claim positive chip gain")
                _require(
                    row["solver_status"] in ("OPTIMAL", "FEASIBLE"), "hold needs a compared plan"
                )
