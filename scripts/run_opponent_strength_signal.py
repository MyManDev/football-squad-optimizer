"""Ask whether opponent strength is signal the operational control leaves on the table.

    python -m scripts.run_opponent_strength_signal

Attaches the shifted opponent-strength estimate to the committed control residual export
and reports how the residual moves with it. A residual that still moves with something the
model could have seen is signal not yet spent.

Requires the control residual export produced by `scripts.export_candidate_residuals`; that
table stays local, and so does this measurement's own detail. The committed record is the
summary.

Not gate evidence and not a candidate: a model that consumes opponent strength changes the
expected-points rate and needs its own declaration and a single run under the frozen gates.
"""

import argparse
import sys
from pathlib import Path

import pandas as pd
from scripts._experiment_cli import (
    DEFAULT_ARCHIVE_ROOT,
    REPOSITORY_ROOT,
    artifact_metadata,
    write_json,
    write_text,
)

from squadopt.backtest.opponent_strength_signal import (
    measure_opponent_strength_signal,
    signal_to_dict,
    signal_to_markdown,
)
from squadopt.data.errors import DataError
from squadopt.data.sources.vaastav import (
    ARCHIVE_COMMIT,
    build_fixture_panel,
    build_panel,
    load_team_codes,
)

HISTORY_SEASON = "2020-21"
DEVELOPMENT_SEASONS = ("2021-22", "2022-23", "2023-24", "2024-25")
DEFAULT_RESIDUALS = REPOSITORY_ROOT / "artifacts" / "residuals" / "control_residuals.csv"


def _parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--residuals", type=Path, default=DEFAULT_RESIDUALS)
    parser.add_argument("--archive-root", type=Path, default=DEFAULT_ARCHIVE_ROOT)
    parser.add_argument("--window", type=int, default=6)
    parser.add_argument(
        "--json-output",
        type=Path,
        default=REPOSITORY_ROOT / "docs" / "opponent_strength_signal.json",
    )
    parser.add_argument(
        "--markdown-output",
        type=Path,
        default=REPOSITORY_ROOT / "docs" / "opponent_strength_signal.md",
    )
    return parser.parse_args()


def main() -> int:
    arguments = _parse_arguments()
    residual_path: Path = arguments.residuals
    if not residual_path.is_file():
        print(
            f"Control residual export not found at {residual_path}.\n"
            "Produce it first with 'python -m scripts.export_candidate_residuals'."
        )
        return 1

    loaded = (HISTORY_SEASON, *DEVELOPMENT_SEASONS)
    try:
        residuals = pd.read_csv(residual_path)
        panel = build_panel(arguments.archive_root, seasons=list(loaded))
        fixtures = build_fixture_panel(arguments.archive_root, seasons=list(loaded))
        team_codes = pd.concat(
            [
                load_team_codes(arguments.archive_root, season).assign(season=season)
                for season in loaded
            ],
            ignore_index=True,
        )
        result = measure_opponent_strength_signal(
            residuals, panel, fixtures, team_codes, window=int(arguments.window)
        )
    except (DataError, OSError, ValueError) as error:
        print(f"Could not measure the opponent-strength signal:\n  {error}")
        return 1

    document = {
        **artifact_metadata(panel_rows=len(panel)),
        **signal_to_dict(result),
        "dataset_snapshot_id": f"vaastav-fpl@{ARCHIVE_COMMIT}",
        "residual_source": residual_path.name,
    }
    markdown = signal_to_markdown(result)

    write_json(arguments.json_output, document)
    write_text(arguments.markdown_output, markdown)
    print(markdown)
    print(f"Wrote {arguments.json_output}")
    print(f"Wrote {arguments.markdown_output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
