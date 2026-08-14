"""Repeat one representative Ridge fold under a deterministic CP-SAT budget.

This is a calibration smoke test, not a model benchmark. It builds the chronological
Ridge projections once, selects one fold, solves the identical squad model repeatedly,
and compares a canonical fingerprint of the decision.

    python -m scripts.check_solver_reproducibility --season 2024-25 --gameweek 38
"""

import argparse
import hashlib
import json
import sys
from numbers import Integral
from pathlib import Path

from squadopt.backtest.folds import build_walk_forward_folds
from squadopt.backtest.learned import make_ridge_projection_builder
from squadopt.data.errors import DataError
from squadopt.data.sources.vaastav import SUPPORTED_SEASONS, build_panel
from squadopt.features import CrossSeasonConfig
from squadopt.optimization import OptimizationConfig, OptimizationResult, optimize_squad

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
ARCHIVE_ROOT = REPOSITORY_ROOT / "data" / "raw" / "vaastav-fpl"


def _history_seasons(evaluated: str) -> list[str]:
    earlier = [season for season in SUPPORTED_SEASONS if season < evaluated]
    return [*earlier[-1:], evaluated]


def _decision_fingerprint(result: OptimizationResult) -> str:
    def player_id(value: object) -> int | str:
        return int(value) if isinstance(value, Integral) else str(value)

    captain_id = None if result.captain is None else player_id(result.captain["player_id"])
    payload = {
        "solver_status": result.solver_status.value,
        "selected_squad": [player_id(value) for value in result.selected_squad["player_id"]],
        "starting_xi": [player_id(value) for value in result.starting_xi["player_id"]],
        "bench": [player_id(value) for value in result.bench["player_id"]],
        "captain": captain_id,
        "objective_value": result.objective_value,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season", default="2024-25", choices=SUPPORTED_SEASONS)
    parser.add_argument("--gameweek", type=int)
    parser.add_argument("--repeats", type=int, default=2)
    parser.add_argument(
        "--deterministic-time-limit",
        type=float,
        action="append",
        dest="deterministic_time_limits",
        help="budget to check; repeatable, defaults to 0.1",
    )
    parser.add_argument("--wall-time-limit-seconds", type=float, default=120.0)
    parser.add_argument("--archive-root", default=str(ARCHIVE_ROOT))
    arguments = parser.parse_args()

    if arguments.repeats < 2:
        parser.error("--repeats must be at least 2")

    try:
        panel = build_panel(
            arguments.archive_root,
            seasons=_history_seasons(arguments.season),
        )
    except DataError as error:
        print(f"Could not load the archive:\n  {error}")
        return 1

    folds = build_walk_forward_folds(
        panel,
        seasons=(arguments.season,),
        projection_builder=make_ridge_projection_builder(cross_season=CrossSeasonConfig()),
    )
    if not folds:
        print(f"No evaluation folds were built for {arguments.season}.")
        return 1

    if arguments.gameweek is None:
        fold = folds[-1]
    else:
        matches = [
            item for item in folds if int(item.metadata.get("gameweek", -1)) == arguments.gameweek
        ]
        if not matches:
            available = [int(item.metadata.get("gameweek", -1)) for item in folds]
            print(f"Gameweek {arguments.gameweek} is unavailable; choose from {available!r}.")
            return 1
        fold = matches[0]

    print(f"Fold: {fold.fold_id}")
    limits = arguments.deterministic_time_limits or [0.1]
    all_passed = True
    for limit in limits:
        budget_passed = True
        config = OptimizationConfig(
            solver_time_limit_seconds=arguments.wall_time_limit_seconds,
            solver_deterministic_time_limit=limit,
        )
        results = [optimize_squad(fold.projections, config) for _ in range(arguments.repeats)]
        fingerprints = [_decision_fingerprint(result) for result in results]
        print(f"Budget: {limit}")
        for index, (result, fingerprint) in enumerate(
            zip(results, fingerprints, strict=True), start=1
        ):
            print(
                f"  run {index}: status={result.solver_status.value} "
                f"deterministic_time={result.diagnostics['deterministic_time_used']:.9f} "
                f"wall_time={result.diagnostics['solve_time_seconds']:.3f}s "
                f"fingerprint={fingerprint}"
            )
            incomplete = result.solver_status.value in {"FEASIBLE", "UNKNOWN"} or (
                result.diagnostics.get("tiebreak_attempted") is True
                and result.diagnostics.get("tiebreak_completed") is not True
            )
            if incomplete and (
                result.diagnostics.get("deterministic_time_budget_exhausted") is not True
            ):
                print("  FAIL: wall-clock safety cap bound before deterministic work.")
                budget_passed = False
        if not all(result.has_solution for result in results):
            print("  FAIL: budget did not produce a feasible decision on every repeat.")
            budget_passed = False
        if len(set(fingerprints)) != 1:
            print("  FAIL: repeated runs produced different decisions.")
            budget_passed = False
        if budget_passed:
            print("  PASS: repeated feasible decision fingerprints match.")
        all_passed = all_passed and budget_passed
    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
