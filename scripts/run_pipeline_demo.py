"""Run the Sprint 0 chain against the committed synthetic sample and print it.

Run from the repository root:

    python -m scripts.run_pipeline_demo

Nothing here touches the network, and the demonstration is not the implementation:
every step calls the same importable functions the tests exercise. The script exists
so the end-to-end behaviour can be inspected by eye, which a passing test does not
show.
"""

import argparse
from pathlib import Path

import pandas as pd
from tests.fixtures.synthetic_gameweeks import SAMPLE_ADAPTER, SEASON

from squadopt import OptimizationConfig, optimize_squad
from squadopt.data import build_canonical_dataset, load_csv
from squadopt.features import build_feature_dataset
from squadopt.prediction import build_projection_table

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SAMPLE_FILE = REPOSITORY_ROOT / "data" / "sample" / "raw_player_gameweeks.csv"
DEFAULT_GAMEWEEK = 6
PREVIEW_ROWS = 5


def _heading(title: str) -> None:
    print(f"\n{title}\n{'-' * len(title)}")


def _parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--gameweek",
        type=int,
        default=DEFAULT_GAMEWEEK,
        help=f"target gameweek to project and optimize (default: {DEFAULT_GAMEWEEK})",
    )
    parser.add_argument(
        "--season",
        default=SEASON,
        help=f"season label to project (default: {SEASON})",
    )
    return parser.parse_args()


def main() -> None:
    """Print each stage's output for one target gameweek."""

    arguments = _parse_arguments()

    raw = load_csv(SAMPLE_FILE)
    _heading("1. Raw source")
    print(f"{len(raw)} rows, all text, source column names")
    print(raw.head(PREVIEW_ROWS).to_string(index=False))

    canonical = build_canonical_dataset(raw, adapter=SAMPLE_ADAPTER)
    _heading("2. Canonical player-gameweek dataset")
    print(f"{len(canonical)} rows, keyed on (season, gameweek, player_id)")
    print(canonical.dtypes.to_string())

    features = build_feature_dataset(canonical)
    _heading("3. Leakage-safe features for one player")
    single = features.loc[features["player_id"] == features["player_id"].min()]
    print(
        single.loc[
            :,
            ["gameweek", "minutes", "total_points", "points_last_5", "points_per_90_last_5"],
        ].to_string(index=False)
    )
    print("\nGameweek 1 is empty because a shifted window has no history to read.")

    projections = build_projection_table(
        features, season=arguments.season, gameweek=arguments.gameweek
    )
    _heading(f"4. Projection table for gameweek {arguments.gameweek}")
    print(f"{len(projections)} players, exactly the six contract columns")
    print(projections.head(PREVIEW_ROWS).to_string(index=False))

    result = optimize_squad(projections, OptimizationConfig())
    _heading("5. Optimized squad")
    if not result.has_solution:
        print(f"No solution: {result.solver_status}")
        return

    config = OptimizationConfig()
    print(
        f"status={result.solver_status}  "
        f"cost={result.total_cost_tenths}/{config.budget_tenths} tenths  "
        f"projected={result.projected_score:.3f}"
    )
    _heading("Starting XI")
    print(result.starting_xi.to_string(index=False))
    _heading("Bench")
    print(result.bench.to_string(index=False))

    captain = result.captain
    if captain is not None:
        _heading("Captain")
        print(f"{captain['name']} ({captain['position']}), xP {captain['expected_points']:.3f}")


if __name__ == "__main__":
    pd.set_option("display.width", 120)
    main()
