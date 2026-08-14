"""Judge the production projection against the pre-registered gates.

    python -m scripts.run_production_benchmark
    python -m scripts.run_production_benchmark --season 2024-25
    python -m scripts.run_production_benchmark --json-output out.json --markdown-output out.md

Three candidates run over one fold set: the deterministic baseline, which is the
operational control; the Ridge reference, which is a mandatory second comparison; and the
production projection. All three are measured in the same run rather than compared against
recorded figures, because a least-squares reference moves with the numerical environment
while a deterministic baseline does not — comparing across runs would measure the machines
as much as the models.

What this produces is a development gate verdict, not an operational promotion. Clearing
the gates makes a candidate eligible for the locked holdout protocol and nothing more. The
2025-26 holdout is not read here.
"""

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

from squadopt.backtest.production_benchmark import (
    DEFAULT_DEVELOPMENT_SEASONS,
    ProductionBenchmarkConfig,
    run_production_benchmark,
)
from squadopt.backtest.production_reporting import judgement_to_dict, judgement_to_markdown
from squadopt.data.errors import DataError
from squadopt.data.sources.vaastav import (
    SUPPORTED_SEASONS,
    build_fixture_panel,
    build_panel,
    load_team_codes,
)
from squadopt.prediction.minutes import ExpectedMinutesConfig
from squadopt.prediction.production import ProductionProjectionConfig

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
ARCHIVE_ROOT = REPOSITORY_ROOT / "data" / "raw" / "vaastav-fpl"
DEFAULT_WINDOW = 6


def history_seasons(evaluated: tuple[str, ...]) -> list[str]:
    """Return the seasons to load: those evaluated, plus the one before the earliest.

    Cross-season carry-over needs a completed season before the first evaluated one,
    otherwise every player entering that season looks like a debutant.
    """

    earliest = min(evaluated)
    earlier = [season for season in SUPPORTED_SEASONS if season < earliest]
    return sorted({*evaluated, *earlier[-1:]})


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--season",
        dest="seasons",
        action="append",
        help="evaluate this season; repeatable, defaults to the development seasons",
    )
    parser.add_argument("--window", type=int, default=DEFAULT_WINDOW)
    parser.add_argument("--archive-root", default=str(ARCHIVE_ROOT))
    parser.add_argument("--json-output")
    parser.add_argument("--markdown-output")
    arguments = parser.parse_args()

    evaluated = tuple(arguments.seasons or DEFAULT_DEVELOPMENT_SEASONS)
    unsupported = [season for season in evaluated if season not in SUPPORTED_SEASONS]
    if unsupported:
        print(f"Seasons {unsupported!r} are outside the supported range.")
        return 1

    loaded = history_seasons(evaluated)
    print(f"Loading {', '.join(loaded)} from {arguments.archive_root}")
    try:
        panel = build_panel(arguments.archive_root, seasons=loaded)
        fixtures = build_fixture_panel(arguments.archive_root, seasons=loaded)
        team_codes = pd.concat(
            [
                load_team_codes(arguments.archive_root, season).assign(season=season)
                for season in loaded
            ],
            ignore_index=True,
        )
    except DataError as error:
        print(f"Could not load the archive:\n  {error}")
        return 1

    config = ProductionBenchmarkConfig(
        seasons=evaluated,
        production_config=ProductionProjectionConfig(
            rate_window=arguments.window,
            minutes=ExpectedMinutesConfig(window=arguments.window),
        ),
    )

    print(f"Judging {len(evaluated)} season(s) over {len(panel):,} player-gameweek rows")
    result = run_production_benchmark(panel, fixtures, team_codes, config)

    print(f"\nFolds: {result.fold_count}")
    for label, value in sorted(result.mean_realized_points.items()):
        print(f"  {label:<11} mean realized {value:.4f}")
    print()
    for gate in result.gates:
        print(f"  {'PASS' if gate.passed else 'FAIL'}  {gate.name}: {gate.measured:+.4f}")
    print(f"\nVerdict: {result.verdict}")
    print("A development gate verdict is not an operational promotion.")

    if arguments.json_output:
        destination = Path(arguments.json_output)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(
            json.dumps(judgement_to_dict(result), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(f"Wrote {destination}")
    if arguments.markdown_output:
        destination = Path(arguments.markdown_output)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(judgement_to_markdown(result), encoding="utf-8")
        print(f"Wrote {destination}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
