"""The fixed #1009(b) adjustment and whole-gameweek readings, without input I/O."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

import numpy as np
import pandas as pd

from squadopt.evaluation.promotion import ExperimentExecutionError
from squadopt.experiments.opponent_projection import (
    _bootstrap,
    _rank_correlation,
    _realized,
    _squad,
    apply_adjustment,
)
from squadopt.optimization import OptimizationConfig, SolverStatus, wall_clock_stopped_the_search
from squadopt.optimization.models import SquadOptimizationError

SEASON = "2026-27"
CANDIDATE = "published_difficulty_live_2026_v1"
COEFFICIENT_FILE_SHA256 = "063fa112506b2bfd27e7d189f62adf7fdc5d091f8968ebfd811c9a7f08d2f326"
COEFFICIENTS: Mapping[str, tuple[float, float]] = MappingProxyType(
    {
        "GK": (0.10084782395925615, -2.8167342557251906),
        "DEF": (0.1711733215945405, -2.8166785629312394),
        "MID": (0.07348818963372446, -2.819164220126179),
        "FWD": (0.07265969217343048, -2.8343133137337255),
    }
)
BOOTSTRAP_RESAMPLES = 2000
BOOTSTRAP_SEED = 0
MINIMUM_WEEKS = 8
#: The #844 solver method (docs/football_prospective_prereg.md, reading one).
LINEARIZATION_LEVEL = 2
DETERMINISTIC_UNITS: tuple[float, ...] = (60.0, 240.0)
WALL_CEILING_SECONDS = 1800.0


class DifficultyInputError(ValueError):
    """A fixed identity or input invariant was violated."""


class DifficultyMissingInputs(DifficultyInputError):
    """A week cannot be paired under the frozen rule."""


class DifficultySolveFailure(DifficultyMissingInputs):
    """Retain the actual solve traces when the joint weekly gate is missing."""

    def __init__(self, decisions: dict[str, dict[str, object]]) -> None:
        super().__init__("A free-squad arm is not proven at 240 units; the joint week is missing.")
        self.decisions = decisions


def require_season(season: str) -> None:
    if season != SEASON:
        raise DifficultyInputError("Only 2026-27 is admitted; 2025-26 is refused before loading.")


def decode(content: bytes) -> Any:
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                raise DifficultyInputError("A JSON object has duplicate keys.")
            result[key] = value
        return result

    return json.loads(content, object_pairs_hook=pairs)


def verify_coefficients(content: bytes) -> None:
    """Pin the recorded fit by both file identity and every numerical value."""
    if hashlib.sha256(content.replace(b"\r\n", b"\n")).hexdigest() != COEFFICIENT_FILE_SHA256:
        raise DifficultyInputError("The frozen development coefficient file hash differs.")
    recorded = [
        item for item in decode(content)["candidates"] if item["candidate"] == "P_published_rating"
    ]
    expected = {p: {"slope": values[0], "centre": values[1]} for p, values in COEFFICIENTS.items()}
    if len(recorded) != 1 or recorded[0]["coefficients"] != expected:
        raise DifficultyInputError("The recorded coefficient values differ from the fixed fit.")


def optimization_config(deterministic_units: float) -> OptimizationConfig:
    """Use the protocol's complete configuration, independently of future defaults.

    The squad rules are the study's. The solver follows the #844 method the owner
    accepted on 2026-10-10: seed 0, a deterministic ceiling of 60 units, or of 240
    when 60 does not prove the decision, and a wall ceiling of 1800 seconds per
    solve. ``configure_solver`` gives every solve one search worker.
    """
    if deterministic_units not in DETERMINISTIC_UNITS:
        raise DifficultyInputError("Only the declared deterministic budgets are admitted.")
    return OptimizationConfig(
        budget_tenths=1000,
        squad_size=15,
        squad_position_limits={"GK": 2, "DEF": 5, "MID": 5, "FWD": 3},
        starting_size=11,
        starting_position_min={"GK": 1, "DEF": 3, "MID": 2, "FWD": 1},
        starting_position_max={"GK": 1, "DEF": 5, "MID": 5, "FWD": 3},
        max_players_per_team=3,
        bench_weight=0.1,
        expected_points_scale=1000,
        solver_time_limit_seconds=WALL_CEILING_SECONDS,
        solver_deterministic_time_limit=deterministic_units,
        deterministic_seed=0,
    )


def clock_stopped(attempt: Mapping[str, object]) -> bool:
    """Whether the wall clock, not the deterministic budget, stopped this solve."""
    diagnostics = attempt.get("solver_diagnostics")
    status = attempt.get("solver_status")
    if not isinstance(diagnostics, dict) or not isinstance(status, str):
        return False
    if status not in set(SolverStatus):
        return False
    return wall_clock_stopped_the_search(SolverStatus(status), diagnostics)


def proven(attempt: Mapping[str, object]) -> bool:
    """The primary and the tie-break both proved OPTIMAL under the declared solver.

    A tie-break counts as proven only when it was attempted and completed.
    """
    diagnostics = attempt.get("solver_diagnostics")
    return (
        attempt.get("solver_status") == SolverStatus.OPTIMAL
        and isinstance(diagnostics, dict)
        and diagnostics.get("tiebreak_attempted") is True
        and diagnostics.get("tiebreak_completed") is True
        and diagnostics.get("num_search_workers") == 1
        and diagnostics.get("linearization_level") == LINEARIZATION_LEVEL
        and not clock_stopped(attempt)
    )


@dataclass(frozen=True, slots=True)
class ArmSolve:
    decided: bool
    starters: tuple[int, ...]
    captain: int | None
    record: dict[str, object]


def free_squad(rows: pd.DataFrame, prediction: np.ndarray) -> ArmSolve:
    """Solve one arm at 60 units, and once more at 240 when 60 does not prove it.

    The 240 solve decides an arm 60 left unproven. The arm has no decision, and its
    week is missing for the joint gate, when it is still unproven at 240 or when the
    wall clock stopped any of its solves. Every solve is recorded with its limits,
    its primary and tie-break status, its deterministic time and the clock reading.
    """
    attempts: list[dict[str, object]] = []
    starters: tuple[int, ...] = ()
    captain: int | None = None
    for units in DETERMINISTIC_UNITS:
        attempt: dict[str, object] = {
            "deterministic_units": units,
            "wall_ceiling_seconds": WALL_CEILING_SECONDS,
            "linearization_level": LINEARIZATION_LEVEL,
            "deterministic_seed": 0,
        }
        attempts.append(attempt)
        try:
            starters, captain = _squad(
                rows,
                prediction,
                optimization_config(units),
                diagnostics=attempt,
                linearization_level=LINEARIZATION_LEVEL,
            )
        except (ExperimentExecutionError, SquadOptimizationError) as error:
            attempt["error"] = type(error).__name__
            starters, captain = (), None
        diagnostics = attempt.get("solver_diagnostics")
        held = diagnostics if isinstance(diagnostics, dict) else {}
        attempt["primary_status"] = held.get("solver_status_name")
        attempt["tiebreak_status"] = held.get("tiebreak_status")
        attempt["primary_deterministic_time"] = held.get("primary_deterministic_time")
        attempt["tiebreak_deterministic_time"] = held.get("tiebreak_deterministic_time")
        attempt["wall_clock_stopped"] = clock_stopped(attempt)
        attempt["proven"] = proven(attempt)
        if attempt["proven"] or attempt["wall_clock_stopped"]:
            break
    final = attempts[-1]
    stopped = any(attempt["wall_clock_stopped"] for attempt in attempts)
    decided = final["proven"] is True and not stopped
    record: dict[str, object] = {
        "decided": decided,
        "decided_at_units": final["deterministic_units"],
        "wall_clock_stopped": stopped,
        "solver_status": final.get("solver_status"),
        "squad": final.get("squad", []),
        "starting_xi": final.get("starting_xi", []),
        "captain": final.get("captain"),
        "attempts": attempts,
    }
    return ArmSolve(decided, starters, captain, record)


@dataclass(frozen=True, slots=True)
class DifficultyWeek:
    gameweek: int
    handoff_version: str
    players: int
    squared_error_improvement: float
    rank_improvement: float
    decision_difference: float
    absolute_error_improvement: float
    comparator_mse: float
    candidate_mse: float
    comparator_mae: float
    candidate_mae: float
    comparator_rank: float
    candidate_rank: float
    comparator_realized_points: float
    candidate_realized_points: float
    comparator_decision: dict[str, object]
    candidate_decision: dict[str, object]
    identical_decision: bool


def adjusted_points(rows: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    """Apply the original adjustment without fitting or changing later weeks."""
    if rows.empty or rows["player_id"].duplicated().any():
        raise DifficultyInputError("The paired roster is empty or has duplicate player codes.")
    if not rows["position"].isin(COEFFICIENTS).all():
        raise DifficultyInputError("The paired roster has an unknown position.")
    if not np.isfinite(rows["predicted_points"].to_numpy(dtype=float)).all():
        raise DifficultyInputError("The comparator has non-finite points.")
    if (rows["predicted_points"] < 0).any():
        raise DifficultyInputError("The comparator has negative points.")
    counts = rows["fixture_count"].to_numpy(dtype=float)
    signal = rows["published_signal"].to_numpy(dtype=float)
    if (
        not np.isfinite(counts).all()
        or (counts < 0).any()
        or not np.equal(counts, np.floor(counts)).all()
        or not np.isfinite(signal[counts > 0]).all()
        or ((signal[counts > 0] < -5) | (signal[counts > 0] > -1)).any()
        or not np.isnan(signal[counts == 0]).all()
    ):
        raise DifficultyInputError("The captured fixture counts or difficulty signals are invalid.")
    return apply_adjustment(rows, "P_published_rating", COEFFICIENTS)


def measure_week(
    rows: pd.DataFrame, *, season: str, gameweek: int, handoff_version: str
) -> tuple[DifficultyWeek, pd.DataFrame]:
    """Measure one joined population; the script owns the real-reading gate."""
    require_season(season)
    if type(gameweek) is not int or not 2 <= gameweek <= 20:
        raise DifficultyInputError("The scored gameweek is outside the live population.")
    if not handoff_version:
        raise DifficultyInputError("The comparator version must be recorded.")
    adjusted, multiplier = adjusted_points(rows)
    realized = rows["realized_points"].to_numpy(dtype=float)
    if not np.isfinite(realized).all():
        raise DifficultyMissingInputs("The paired realized points are incomplete.")
    comparator = rows["predicted_points"].to_numpy(dtype=float)
    base = free_squad(rows, comparator)
    candidate = free_squad(rows, adjusted)
    comparator_trace = base.record
    candidate_trace = candidate.record
    if not base.decided or not candidate.decided:
        raise DifficultySolveFailure({"comparator": comparator_trace, "candidate": candidate_trace})
    if base.captain is None or candidate.captain is None:
        raise DifficultyInputError("A proven arm recorded no captain.")
    base_xi, base_captain = base.starters, base.captain
    next_xi, next_captain = candidate.starters, candidate.captain
    base_points = _realized(rows, base_xi, base_captain)
    next_points = _realized(rows, next_xi, next_captain)
    base_mse = float(np.mean((comparator - realized) ** 2))
    next_mse = float(np.mean((adjusted - realized) ** 2))
    base_mae = float(np.mean(np.abs(comparator - realized)))
    next_mae = float(np.mean(np.abs(adjusted - realized)))
    base_rank = _rank_correlation(rows, comparator)
    next_rank = _rank_correlation(rows, adjusted)
    base_squad = comparator_trace["squad"]
    next_squad = candidate_trace["squad"]
    if not isinstance(base_squad, list) or not isinstance(next_squad, list):
        raise DifficultyInputError("The optimizer did not record its selected squad.")
    identical = (
        sorted(base_squad) == sorted(next_squad)
        and set(base_xi) == set(next_xi)
        and base_captain == next_captain
    )
    evidence = rows.copy()
    evidence["candidate_points"] = adjusted
    evidence["multiplier"] = multiplier
    return (
        DifficultyWeek(
            gameweek,
            handoff_version,
            len(rows),
            base_mse - next_mse,
            next_rank - base_rank,
            next_points - base_points,
            base_mae - next_mae,
            base_mse,
            next_mse,
            base_mae,
            next_mae,
            base_rank,
            next_rank,
            base_points,
            next_points,
            comparator_trace,
            candidate_trace,
            identical,
        ),
        evidence,
    )


def summarize(weeks: tuple[DifficultyWeek, ...]) -> dict[str, Any]:
    if len({week.gameweek for week in weeks}) != len(weeks):
        raise DifficultyInputError("A gameweek was scored more than once.")
    ordered = sorted(weeks, key=lambda week: week.gameweek)
    errors = np.array([week.squared_error_improvement for week in ordered], dtype=float)
    ranks = [week.rank_improvement for week in ordered]
    decisions = [week.decision_difference for week in ordered]
    low, high = _bootstrap(errors, resamples=BOOTSTRAP_RESAMPLES, seed=BOOTSTRAP_SEED)
    rank = float(np.mean(ranks)) if ranks else None
    decision = float(np.mean(decisions)) if decisions else None
    passed = (
        len(weeks) >= MINIMUM_WEEKS
        and low > 0
        and rank is not None
        and rank >= 0
        and decision is not None
        and decision >= 0
    )
    if passed:
        verdict = "passed"
    elif len(weeks) < MINIMUM_WEEKS:
        verdict = "insufficient_evidence"
    else:
        verdict = "failed"
    versions = {}
    for version in sorted({week.handoff_version for week in weeks}):
        held = [week for week in ordered if week.handoff_version == version]
        versions[version] = {
            "weeks": len(held),
            "player_rows": sum(week.players for week in held),
            "squared_error_improvement": float(
                np.mean([w.squared_error_improvement for w in held])
            ),
            "rank_improvement": float(np.mean([w.rank_improvement for w in held])),
            "decision_difference": float(np.mean([w.decision_difference for w in held])),
        }
    return {
        "candidate": CANDIDATE,
        "promotion": False,
        "valid_weeks": len(weeks),
        "verdict": verdict,
        "squared_error_improvement": float(np.mean(errors)) if errors.size else None,
        "squared_error_interval_90": {"lower": low, "upper": high} if errors.size else None,
        "rank_improvement": rank,
        "decision_difference": decision,
        "absolute_error_improvement": float(np.mean([w.absolute_error_improvement for w in weeks]))
        if weeks
        else None,
        "identical_decisions": sum(week.identical_decision for week in weeks),
        "by_handoff_version": versions,
        "numerical_environment": {"numpy": np.__version__, "pandas": pd.__version__},
        "constants": {
            "coefficient_file_sha256": COEFFICIENT_FILE_SHA256,
            "coefficients": {p: {"slope": v[0], "centre": v[1]} for p, v in COEFFICIENTS.items()},
            "resamples": BOOTSTRAP_RESAMPLES,
            "seed": BOOTSTRAP_SEED,
            "minimum_weeks": MINIMUM_WEEKS,
            "gameweek_weights": "equal",
            "free_squad_solver": {
                "entry_point": "optimize_squad",
                "linearization_level": LINEARIZATION_LEVEL,
                "num_search_workers": 1,
                "deterministic_seed": 0,
                "deterministic_units": list(DETERMINISTIC_UNITS),
                "wall_ceiling_seconds": WALL_CEILING_SECONDS,
                "scored_only_when": "both arms' primary and tie-break proven OPTIMAL",
            },
        },
    }
