"""Rehearse multi-gameweek planning against the myopic baseline on real windows.

    python -m scripts.run_multi_gw_rehearsal \
        --season 2024-25 --start-gameweeks 5,10,15,20,25,30

Each sampled window plans three gameweeks ahead from decision-time information only
(naive calendar-scaled projections over a shared candidate pool) and executes the plan
as frozen, while the myopic baseline re-optimizes one week at a time from the same
starting squad with each week's fresh projections. Both are scored on realized points
minus transfer hits. Measurement only: no promotion, no locked-holdout access.
"""

import argparse
import logging
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

from squadopt.data.sources.vaastav import build_fixture_panel, build_panel, load_team_codes
from squadopt.experiments import (
    MULTI_GW_REHEARSAL_CONTRACT_VERSION,
    NAIVE_PROJECTION_RULE,
    ExperimentError,
    MultiGwRehearsal,
    MultiGwRehearsalConfig,
    RehearsalWindowResult,
)

LOGGER = logging.getLogger(__name__)


def _parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive-root", type=Path, default=DEFAULT_ARCHIVE_ROOT)
    parser.add_argument("--season", default="2024-25")
    parser.add_argument("--start-gameweeks", default="5,10,15,20,25,30")
    parser.add_argument("--horizon-length", type=int, default=3)
    parser.add_argument("--form-window", type=int, default=5)
    parser.add_argument("--candidate-pool-per-position", type=int, default=20)
    parser.add_argument("--cheap-pool-per-position", type=int, default=8)
    parser.add_argument(
        "--json-output",
        type=Path,
        default=REPOSITORY_ROOT / "docs" / "multi_gw_rehearsal.json",
    )
    parser.add_argument(
        "--markdown-output",
        type=Path,
        default=REPOSITORY_ROOT / "docs" / "multi_gw_rehearsal.md",
    )
    return parser.parse_args()


def _fixture_counts(archive_root: Path, season: str) -> pd.DataFrame:
    """Return known fixtures per (gameweek, panel team label) for one season."""

    fixtures = build_fixture_panel(archive_root, seasons=(season,))
    codes = load_team_codes(archive_root, season)
    name_by_code = {
        int(code): str(name)
        for name, code in zip(codes["name"].tolist(), codes["code"].tolist(), strict=True)
    }
    counts = (
        fixtures.groupby(["gameweek", "team_id"], sort=True)
        .size()
        .reset_index(name="fixture_count")
    )
    counts["team_id"] = counts["team_id"].map(lambda code: name_by_code[int(code)])
    return counts


def _window_record(window: RehearsalWindowResult) -> dict[str, object]:
    return {
        "start_gameweek": window.start_gameweek,
        "gameweeks": list(window.gameweeks),
        "planned_realized_points": window.planned_realized_points,
        "planned_transfer_hit_points": window.planned_transfer_hit_points,
        "planned_net_points": window.planned_net_points,
        "myopic_realized_points": window.myopic_realized_points,
        "myopic_transfer_hit_points": window.myopic_transfer_hit_points,
        "myopic_net_points": window.myopic_net_points,
        "planning_advantage_points": window.planning_advantage_points,
        "candidate_pool_size": window.candidate_pool_size,
        "horizon_fingerprint": window.horizon_fingerprint,
        "planner_transfers": list(window.diagnostics.get("planner_transfers", [])),  # type: ignore[call-overload]
    }


def main() -> int:
    arguments = _parse_arguments()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    if not arguments.archive_root.is_dir():
        print(f"Archive not found at {arguments.archive_root}.")
        return 1

    created_utc = datetime.now(UTC).isoformat(timespec="seconds")
    season = str(arguments.season).strip()
    starts = tuple(int(value.strip()) for value in str(arguments.start_gameweeks).split(","))
    panel = build_panel(arguments.archive_root)
    counts = _fixture_counts(arguments.archive_root, season)
    config = MultiGwRehearsalConfig(
        season=season,
        horizon_length=arguments.horizon_length,
        form_window=arguments.form_window,
        candidate_pool_per_position=arguments.candidate_pool_per_position,
        cheap_pool_per_position=arguments.cheap_pool_per_position,
    )

    try:
        rehearsal = MultiGwRehearsal(panel, counts, config)
        windows: list[RehearsalWindowResult] = []
        for start in starts:
            LOGGER.info("Rehearsing window starting at gameweek %s", start)
            windows.append(rehearsal.rehearse_window(start))
    except ExperimentError as error:
        print(f"Could not rehearse multi-gameweek planning:\n  {error}")
        return 1

    advantages = [window.planning_advantage_points for window in windows]
    mean_advantage = sum(advantages) / len(advantages)
    document = {
        **artifact_metadata(panel_rows=len(panel), created_utc=created_utc),
        "contract_version": MULTI_GW_REHEARSAL_CONTRACT_VERSION,
        "projection_rule": NAIVE_PROJECTION_RULE,
        "season": season,
        "horizon_length": arguments.horizon_length,
        "form_window": arguments.form_window,
        "candidate_pool_per_position": arguments.candidate_pool_per_position,
        "cheap_pool_per_position": arguments.cheap_pool_per_position,
        "window_count": len(windows),
        "mean_planning_advantage_points": mean_advantage,
        "windows": [_window_record(window) for window in windows],
        "recommendation_only": True,
        "locked_holdout_accessed": False,
        "limitations": [
            "Projections over the horizon are naively calendar-scaled decision-time "
            "baselines; projection quality is deliberately out of scope.",
            "Both strategies share one decision-time candidate pool; the myopic "
            "baseline re-projects weekly and so holds an informational edge.",
            "Venue is not modeled (home_fixture_count is recorded as zero).",
        ],
    }

    lines = [
        "# Multi-gameweek planning rehearsal",
        "",
        f"- Contract: `{MULTI_GW_REHEARSAL_CONTRACT_VERSION}`; projection rule "
        f"`{NAIVE_PROJECTION_RULE}`",
        f"- Season {season}; horizon {arguments.horizon_length} gameweeks; "
        f"{len(windows)} sampled windows",
        f"- Shared decision-time candidate pool: top "
        f"{arguments.candidate_pool_per_position} + "
        f"{arguments.cheap_pool_per_position} cheapest per position",
        "",
        f"**Mean planning advantage: {mean_advantage:+.2f} net points per window** "
        "(planner minus myopic, realized points minus transfer hits).",
        "",
        "| Start GW | Planner net | Myopic net | Advantage | Planner hits | Myopic hits |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for window in windows:
        lines.append(
            f"| {window.start_gameweek} | {window.planned_net_points:.1f} "
            f"| {window.myopic_net_points:.1f} "
            f"| {window.planning_advantage_points:+.1f} "
            f"| {window.planned_transfer_hit_points:.0f} "
            f"| {window.myopic_transfer_hit_points:.0f} |"
        )
    lines += [
        "",
        "The myopic baseline re-projects each week from fresh features, so it holds a",
        "real informational edge; the comparison isolates what committing to a plan",
        "costs or earns under deliberately naive projections. Measurement only: no",
        "promotion, no locked-holdout access.",
    ]
    markdown = "\n".join(lines) + "\n"

    write_json(arguments.json_output, document)
    write_text(arguments.markdown_output, markdown)
    print(markdown)
    print(f"Wrote {arguments.json_output}")
    print(f"Wrote {arguments.markdown_output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
