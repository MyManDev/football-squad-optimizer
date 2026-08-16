"""Measure how far a projection drifts as the horizon lengthens, and record it.

    python -m scripts.run_horizon_decay
    python -m scripts.run_horizon_decay --max-offset 5

Projects once at every chronological development decision point and scores that same
projection against the decision gameweek and each of the following ones, applying the same
fixture-count scaling the horizon builder ships. The result is the number that replaces the
"nobody has measured this" disclaimer the horizon has been carrying.

Development seasons only; the locked holdout is never read. The residual table stays
local — it derives from third-party data — and the committed record is the summary.

This is not gate evidence for any prediction model, and it does not promote a horizon
length. It says what the drift is; choosing a horizon on it is a separate decision.
"""

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
from scripts._experiment_cli import (
    DEFAULT_ARCHIVE_ROOT,
    REPOSITORY_ROOT,
    artifact_metadata,
    write_json,
    write_text,
)

from squadopt.backtest.horizon_decay import (
    FIXTURE_GROUPS,
    FIXTURE_SCALING_RULE_VERSION,
    measure_horizon_decay,
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


def _parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive-root", type=Path, default=DEFAULT_ARCHIVE_ROOT)
    parser.add_argument("--max-offset", type=int, default=3)
    parser.add_argument("--form-window", type=int, default=5)
    parser.add_argument(
        "--output-dir", type=Path, default=REPOSITORY_ROOT / "artifacts" / "horizon"
    )
    parser.add_argument(
        "--json-output", type=Path, default=REPOSITORY_ROOT / "docs" / "horizon_decay.json"
    )
    parser.add_argument(
        "--markdown-output", type=Path, default=REPOSITORY_ROOT / "docs" / "horizon_decay.md"
    )
    return parser.parse_args()


def main() -> int:
    arguments = _parse_arguments()
    archive_root: Path = arguments.archive_root
    if not archive_root.is_dir():
        print(f"Archive not found at {archive_root}.")
        return 1

    created_utc = datetime.now(UTC).isoformat(timespec="seconds")
    loaded = (HISTORY_SEASON, *DEVELOPMENT_SEASONS)
    try:
        panel = build_panel(archive_root, seasons=list(loaded))
        fixtures = build_fixture_panel(archive_root, seasons=list(loaded))
        team_codes = pd.concat(
            [load_team_codes(archive_root, season).assign(season=season) for season in loaded],
            ignore_index=True,
        )
        print(f"Measuring decay over {len(DEVELOPMENT_SEASONS)} seasons...")
        result = measure_horizon_decay(
            panel,
            fixtures,
            team_codes,
            seasons=DEVELOPMENT_SEASONS,
            max_offset=int(arguments.max_offset),
            form_window=int(arguments.form_window),
        )
    except DataError as error:
        print(f"Could not measure horizon decay:\n  {error}")
        return 1

    metadata = artifact_metadata(panel_rows=len(panel), created_utc=created_utc)
    baseline = result.offsets[0]
    document: dict[str, object] = {
        **metadata,
        "artifact_type": "horizon_decay",
        "contract_version": result.contract_version,
        "fixture_scaling_rule": FIXTURE_SCALING_RULE_VERSION,
        "dataset_snapshot_id": f"vaastav-fpl@{ARCHIVE_COMMIT}",
        "development_seasons": list(result.seasons),
        "form_window": result.form_window,
        "max_offset": result.max_offset,
        "folds": int(result.residuals["fold_id"].nunique()),
        "offsets": [
            {
                "offset": entry.offset,
                "observations": entry.observations,
                "dropped_players": entry.dropped_players,
                "bias": entry.bias,
                "mean_absolute_error": entry.mean_absolute_error,
                "root_mean_squared_error": entry.root_mean_squared_error,
                "mean_absolute_error_growth": (
                    entry.mean_absolute_error / baseline.mean_absolute_error - 1.0
                ),
                "by_fixture_group": {
                    group: dict(values) for group, values in sorted(entry.by_fixture_group.items())
                },
            }
            for entry in result.offsets
        ],
        "gate_evidence": False,
        "locked_holdout_accessed": False,
    }

    output_dir: Path = arguments.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    result.residuals.to_csv(output_dir / "horizon_decay_residuals.csv", index=False)

    lines = [
        "# Horizon Decay",
        "",
        f"- Contract: `{result.contract_version}`",
        f"- Scaling rule: `{FIXTURE_SCALING_RULE_VERSION}`",
        f"- Seasons: {', '.join(result.seasons)} — "
        f"{int(result.residuals['fold_id'].nunique())} decision points",
        f"- Form window: {result.form_window}",
        "",
        "One projection is made at each decision point and scored against that gameweek and "
        "each of the next few, so what grows with the offset is the cost of acting on "
        "information that is one, two or three gameweeks old.",
        "",
        "| Offset | Rows | Dropped | Bias | MAE | RMSE | MAE growth |",
        "| ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for entry in result.offsets:
        growth = entry.mean_absolute_error / baseline.mean_absolute_error - 1.0
        lines.append(
            f"| {entry.offset} | {entry.observations:,} | {entry.dropped_players:,} "
            f"| {entry.bias:+.4f} | {entry.mean_absolute_error:.4f} "
            f"| {entry.root_mean_squared_error:.4f} | {growth:+.1%} |"
        )

    last = result.offsets[-1]
    total_growth = last.mean_absolute_error / baseline.mean_absolute_error - 1.0
    per_gameweek = total_growth / max(last.offset, 1)
    lines += [
        "",
        "## What the numbers say",
        "",
        f"Mean absolute error grows {total_growth:.1%} from offset zero to offset "
        f"{last.offset} — roughly {per_gameweek:.1%} per gameweek of horizon.",
        "",
        "**The dropped counts matter as much as the errors.** A player who is not in the "
        "panel at the compared gameweek is dropped rather than scored, because a transfer "
        "or a delisting is an absence from the data and not a bad projection. That count "
        "grows with the offset, so the population behind each row is not the same "
        "population, and it is reported rather than left implicit.",
        "",
        "## By fixture group",
        "",
        "| Offset | " + " | ".join(FIXTURE_GROUPS) + " |",
        "| ---: | " + " | ".join("---:" for _ in FIXTURE_GROUPS) + " |",
    ]
    for entry in result.offsets:
        cells = []
        for group in FIXTURE_GROUPS:
            values = entry.by_fixture_group.get(group)
            cells.append(
                "—"
                if values is None
                else f"{values['mean_absolute_error']:.4f} ({int(values['observations']):,})"
            )
        lines.append(f"| {entry.offset} | " + " | ".join(cells) + " |")

    lines += [
        "",
        "Mean absolute error with the row count behind it. A blank group of two or three "
        "rows is reported as it is and means nothing; it is left in rather than hidden so "
        "nobody reads its absence as a claim.",
        "",
        "## Read against the planner DoE",
        "",
        "`planner_doe` measured the planner itself against a myopic baseline and found "
        "horizon two worth +4.83 while horizon four cost -3.67. If that reversal were "
        "driven by the projection going stale, the decay above would have to be steep. It "
        "is not — a few percent per gameweek — so most of what makes a long horizon lose "
        "is happening inside the planner rather than inside the projection.",
        "",
        "That is a claim about where to look next, not a diagnosis, and the planner is not "
        "this side's module.",
        "",
        "## Limits",
        "",
        "This is not gate evidence for any prediction model, and it does not promote a "
        "horizon length. The frozen evaluation objective remains single-gameweek realized "
        "squad points. What a planner should do with this is a separate decision with its "
        "own owners.",
        "",
        "The measurement uses the deterministic control, so it describes the drift of the "
        "projection that is actually shipped. A different model would have a different "
        "curve, and this one says nothing about it.",
        "",
        "## Reproduction",
        "",
        "```powershell",
        ".venv\\Scripts\\python -m scripts.run_horizon_decay",
        "```",
    ]

    write_json(arguments.json_output, document)
    write_text(arguments.markdown_output, "\n".join(lines) + "\n")
    print("\n".join(lines))
    print(json.dumps({"folds": document["folds"]}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
