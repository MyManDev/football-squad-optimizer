"""Recommend an opening-gameweek squad from real historical data.

    python -m scripts.recommend_opening_squad
    python -m scripts.recommend_opening_squad --season 2026-27 --budget 1000

Requires the archive to have been fetched:

    python -m scripts.fetch_historical_data

Re-run this close to the deadline. Prices and the roster both move during pre-season,
and the recommendation is only as current as the snapshot it was built from — which is
why the report prints the pinned archive commit alongside the squad.

The projection is the Sprint 1 baseline: a scoring rate scaled by expected playing
time, carried across the season boundary for players who have a record. It is
deterministic, leakage-safe, and explainable. It is **not** a claim of predictive
accuracy, and the report says so where a reader will see it.
"""

import argparse
from pathlib import Path

import pandas as pd

from squadopt import OptimizationConfig, SolverStatus, optimize_squad
from squadopt.data.sources.vaastav import (
    ARCHIVE_COMMIT,
    SUPPORTED_SEASONS,
    build_panel,
    load_upcoming_roster,
)
from squadopt.prediction import build_opening_projection_table

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
ARCHIVE_ROOT = REPOSITORY_ROOT / "data" / "raw" / "vaastav-fpl"
DEFAULT_SEASON = "2026-27"
SQUAD_COLUMNS = ["name", "team_id", "position", "price_tenths", "expected_points"]


def _heading(title: str) -> None:
    print(f"\n{title}\n{'-' * len(title)}")


def _parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season", default=DEFAULT_SEASON, help="season to pick a squad for")
    parser.add_argument(
        "--budget",
        type=int,
        default=OptimizationConfig().budget_tenths,
        help="budget in tenths",
    )
    parser.add_argument(
        "--archive-root",
        type=Path,
        default=ARCHIVE_ROOT,
        help="local archive directory",
    )
    return parser.parse_args()


def main() -> int:
    """Print an opening-gameweek squad and the provenance needed to reproduce it."""

    arguments = _parse_arguments()
    root: Path = arguments.archive_root

    if not root.is_dir():
        print(f"Archive not found at {root}.\nRun 'python -m scripts.fetch_historical_data' first.")
        return 1

    panel = build_panel(root)
    roster = load_upcoming_roster(root, arguments.season)
    projections = build_opening_projection_table(panel, roster, season=arguments.season)

    _heading("Provenance")
    print(f"archive commit   {ARCHIVE_COMMIT}")
    print(f"history seasons  {', '.join(SUPPORTED_SEASONS)}")
    print(f"history rows     {len(panel)}")
    print(f"target season    {arguments.season}")

    carried = int(projections["has_prior_record"].sum())
    _heading("Pool")
    print(f"players            {len(projections)}")
    print(f"with prior record  {carried} ({carried / len(projections):.0%})")
    print(f"on the price prior {len(projections) - carried}")
    print(f"distinct estimates {projections['expected_points'].nunique()}")

    config = OptimizationConfig(budget_tenths=arguments.budget)
    contract = projections.drop(columns=["has_prior_record"])
    result = optimize_squad(contract, config)

    if not result.has_solution:
        print(f"\nNo squad satisfies the constraints: {result.solver_status}")
        return 1

    _heading("Result")
    print(f"status     {result.solver_status}")
    print(f"cost       {result.total_cost_tenths}/{config.budget_tenths} tenths")
    print(f"projected  {result.projected_score:.2f}")
    if result.solver_status is not SolverStatus.OPTIMAL:
        print("note       feasible but not proven optimal within the time limit")

    _heading("Starting XI")
    print(result.starting_xi[SQUAD_COLUMNS].to_string(index=False))

    _heading("Bench")
    print(result.bench[SQUAD_COLUMNS].to_string(index=False))

    captain = result.captain
    if captain is not None:
        _heading("Captain")
        print(f"{captain['name']} ({captain['position']}), xP {captain['expected_points']:.2f}")

    provenance = projections.set_index("player_id")["has_prior_record"]
    squad_carried = int(provenance.loc[result.selected_squad["player_id"]].sum())
    _heading("How much of this rests on real history")
    print(f"{squad_carried} of {len(result.selected_squad)} selected players")
    print(
        "The remainder use the fitted opening-price prior because no usable\n"
        "earlier-season record exists for them."
    )

    _heading("Read this before acting on it")
    print(
        "The projection is a deterministic, leakage-safe baseline, not a tuned predictive\n"
        "model. It has no fixture difficulty, no expected-minutes model, and no\n"
        "availability signal. Treat it as a starting point to argue with, not an answer."
    )
    return 0


if __name__ == "__main__":
    pd.set_option("display.width", 140)
    raise SystemExit(main())
