"""Measure planner horizon length across every development season, window by window.

    python -m scripts.run_planner_horizon_seasons
    python -m scripts.run_planner_horizon_seasons --seasons 2023-24,2024-25 --horizons 2,4

The planner control screen (`docs/planner_doe.md`) found horizon two worth +4.83 and
horizon four worth -3.67 against the myopic baseline, on one season and six windows,
with per-window swings from -31 to +22. The horizon-decay measurement then showed the
projection itself drifts only a few percent per gameweek, which points the question at
the planner. This runner asks that question with more evidence: the same one-factor
screen over horizon length, on every development season, and (the part the screen did
not report) every window on its own, so the reader can see whether a long horizon loses
systematically or in a few windows, and whether what it loses is transfer hits or squad
selection.

Every variant shares pools, starting squads, the naive calendar-scaling projection rule,
and the myopic baseline protocol; only the horizon length differs. Measurement only: no
horizon is promoted, and the locked holdout is never read.
"""

import argparse
import logging
import sys
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from statistics import median

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
    NAIVE_PROJECTION_RULE,
    ExperimentError,
    MultiGwRehearsal,
    MultiGwRehearsalConfig,
    RehearsalWindowResult,
)
from squadopt.planning import TransferPlanningConfig

LOGGER = logging.getLogger(__name__)
PLANNER_HORIZON_SEASONS_CONTRACT_VERSION = "planner_horizon_seasons_v1"
DEFAULT_SEASONS = "2021-22,2022-23,2023-24,2024-25"


def _parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive-root", type=Path, default=DEFAULT_ARCHIVE_ROOT)
    parser.add_argument("--seasons", default=DEFAULT_SEASONS)
    parser.add_argument("--start-gameweeks", default="5,10,15,20,25,30")
    parser.add_argument("--horizons", default="2,3,4")
    parser.add_argument("--form-window", type=int, default=5)
    parser.add_argument("--candidate-pool-per-position", type=int, default=20)
    parser.add_argument("--cheap-pool-per-position", type=int, default=8)
    parser.add_argument(
        "--json-output",
        type=Path,
        default=REPOSITORY_ROOT / "docs" / "planner_horizon_seasons.json",
    )
    parser.add_argument(
        "--markdown-output",
        type=Path,
        default=REPOSITORY_ROOT / "docs" / "planner_horizon_seasons.md",
    )
    return parser.parse_args()


def _fixture_counts(archive_root: Path, season: str) -> pd.DataFrame:
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


def _calendar_shape(counts: pd.DataFrame, gameweeks: tuple[int, ...]) -> dict[str, list[int]]:
    """Teams with a double (or more) and teams with a blank, per gameweek of a window."""

    teams = sorted({str(team) for team in counts["team_id"].tolist()})
    doubles: list[int] = []
    blanks: list[int] = []
    for gameweek in gameweeks:
        block = counts.loc[counts["gameweek"] == gameweek]
        played = {
            str(team): int(count)
            for team, count in zip(
                block["team_id"].tolist(), block["fixture_count"].tolist(), strict=True
            )
        }
        doubles.append(sum(1 for team in teams if played.get(team, 0) >= 2))
        blanks.append(sum(1 for team in teams if played.get(team, 0) == 0))
    return {"double_gameweek_teams": doubles, "blank_gameweek_teams": blanks}


def _ints(value: object) -> list[int]:
    assert isinstance(value, list | tuple)
    return [int(item) for item in value]


def _window_record(
    season: str,
    horizon_length: int,
    start: int,
    window: RehearsalWindowResult,
    counts: pd.DataFrame,
) -> dict[str, object]:
    gameweeks = tuple(int(value) for value in window.gameweeks)
    planned = float(window.planned_realized_points)
    planned_hits = float(window.planned_transfer_hit_points)
    myopic = float(window.myopic_realized_points)
    myopic_hits = float(window.myopic_transfer_hit_points)
    advantage = float(window.planning_advantage_points)
    transfers = _ints(window.diagnostics.get("planner_transfers", []))
    return {
        "season": season,
        "horizon_length": horizon_length,
        "start_gameweek": start,
        "gameweeks": list(gameweeks),
        "planned_realized_points": planned,
        "planned_transfer_hit_points": planned_hits,
        "myopic_realized_points": myopic,
        "myopic_transfer_hit_points": myopic_hits,
        "selection_advantage_points": planned - myopic,
        "hit_disadvantage_points": planned_hits - myopic_hits,
        "planning_advantage_points": advantage,
        "advantage_per_gameweek": advantage / horizon_length,
        "planner_transfers_by_week": transfers,
        **_calendar_shape(counts, gameweeks),
    }


def _variant_summary(
    horizon_length: int,
    rows: list[dict[str, object]],
    seasons: tuple[str, ...],
) -> dict[str, object]:
    advantages = [float(str(row["planning_advantage_points"])) for row in rows]
    per_gw = [float(str(row["advantage_per_gameweek"])) for row in rows]
    selection = [float(str(row["selection_advantage_points"])) for row in rows]
    hits = [float(str(row["hit_disadvantage_points"])) for row in rows]
    by_season: dict[str, float | None] = {}
    for season in seasons:
        season_rows = [
            float(str(row["planning_advantage_points"])) for row in rows if row["season"] == season
        ]
        by_season[season] = sum(season_rows) / len(season_rows) if season_rows else None
    return {
        "horizon_length": horizon_length,
        "windows": len(rows),
        "mean_planning_advantage_points": sum(advantages) / len(advantages),
        "median_planning_advantage_points": float(median(advantages)),
        "mean_advantage_per_gameweek": sum(per_gw) / len(per_gw),
        "positive_window_share": sum(1 for value in advantages if value > 0) / len(advantages),
        "min_advantage": min(advantages),
        "max_advantage": max(advantages),
        "mean_selection_advantage_points": sum(selection) / len(selection),
        "mean_hit_disadvantage_points": sum(hits) / len(hits),
        "total_planner_transfers": sum(
            sum(_ints(row["planner_transfers_by_week"])) for row in rows
        ),
        "total_planner_hit_points": sum(
            float(str(row["planned_transfer_hit_points"])) for row in rows
        ),
        "mean_advantage_by_season": by_season,
    }


def _markdown(
    seasons: tuple[str, ...],
    starts: tuple[int, ...],
    variants: list[Mapping[str, object]],
    windows: list[dict[str, object]],
) -> str:
    lines = [
        "# Planner horizon length across the development seasons",
        "",
        f"- Contract: `{PLANNER_HORIZON_SEASONS_CONTRACT_VERSION}`; projection rule "
        f"`{NAIVE_PROJECTION_RULE}`",
        f"- Seasons {', '.join(seasons)}; windows starting at {', '.join(map(str, starts))}",
        "- Only the horizon length varies; hit cost 4.0 and discount 1.0 stay at the "
        "defaults; every variant shares pools, starting squads, and the myopic baseline",
        "- Advantage = planner net minus myopic net over the window. Selection = realized "
        "points difference before hits; hit disadvantage = planner hits minus myopic hits",
        "",
        "## Per horizon",
        "",
        "| Horizon | Windows | Mean adv | Median | Per GW | Positive share "
        "| Min | Max | Selection | Hit disadv | Transfers | Hit pts |",
        "| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for record in variants:
        lines.append(
            f"| {record['horizon_length']} | {record['windows']} "
            f"| {float(str(record['mean_planning_advantage_points'])):+.2f} "
            f"| {float(str(record['median_planning_advantage_points'])):+.1f} "
            f"| {float(str(record['mean_advantage_per_gameweek'])):+.2f} "
            f"| {float(str(record['positive_window_share'])):.2f} "
            f"| {float(str(record['min_advantage'])):+.1f} "
            f"| {float(str(record['max_advantage'])):+.1f} "
            f"| {float(str(record['mean_selection_advantage_points'])):+.2f} "
            f"| {float(str(record['mean_hit_disadvantage_points'])):+.2f} "
            f"| {record['total_planner_transfers']} "
            f"| {float(str(record['total_planner_hit_points'])):.0f} |"
        )
    lines += ["", "## Per horizon and season (mean advantage)", ""]
    lines.append("| Horizon | " + " | ".join(seasons) + " |")
    lines.append("| ---: | " + " | ".join("---:" for _ in seasons) + " |")
    for record in variants:
        by_season = record["mean_advantage_by_season"]
        assert isinstance(by_season, dict)
        cells = []
        for season in seasons:
            value = by_season.get(season)
            cells.append("-" if value is None else f"{float(str(value)):+.2f}")
        lines.append(f"| {record['horizon_length']} | " + " | ".join(cells) + " |")
    lines += [
        "",
        "## Every window",
        "",
        "| Season | H | Start | Gameweeks | Planned | Myopic | Selection | Hit disadv "
        "| Advantage | Transfers by week | DGW teams by week | Blank teams by week |",
        "| --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: | --- | --- | --- |",
    ]
    for row in windows:
        gameweeks = ",".join(str(value) for value in _ints(row["gameweeks"]))
        transfers = ",".join(str(value) for value in _ints(row["planner_transfers_by_week"]))
        doubles = ",".join(str(value) for value in _ints(row["double_gameweek_teams"]))
        blanks = ",".join(str(value) for value in _ints(row["blank_gameweek_teams"]))
        lines.append(
            f"| {row['season']} | {row['horizon_length']} | {row['start_gameweek']} "
            f"| {gameweeks} | {float(str(row['planned_realized_points'])):.0f} "
            f"| {float(str(row['myopic_realized_points'])):.0f} "
            f"| {float(str(row['selection_advantage_points'])):+.0f} "
            f"| {float(str(row['hit_disadvantage_points'])):+.0f} "
            f"| {float(str(row['planning_advantage_points'])):+.0f} "
            f"| {transfers} | {doubles} | {blanks} |"
        )
    lines += [
        "",
        "Measurement only: no horizon is promoted, the transfer planner is unchanged, and",
        "the locked holdout was not read.",
    ]
    return "\n".join(lines) + "\n"


def main() -> int:
    arguments = _parse_arguments()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    if not arguments.archive_root.is_dir():
        print(f"Archive not found at {arguments.archive_root}.")
        return 1

    created_utc = datetime.now(UTC).isoformat(timespec="seconds")
    seasons = tuple(value.strip() for value in str(arguments.seasons).split(","))
    starts = tuple(int(value.strip()) for value in str(arguments.start_gameweeks).split(","))
    horizons = tuple(int(value.strip()) for value in str(arguments.horizons).split(","))
    panel = build_panel(arguments.archive_root)

    window_records: list[dict[str, object]] = []
    try:
        for season in seasons:
            counts = _fixture_counts(arguments.archive_root, season)
            for horizon_length in horizons:
                config = MultiGwRehearsalConfig(
                    season=season,
                    horizon_length=horizon_length,
                    form_window=arguments.form_window,
                    candidate_pool_per_position=arguments.candidate_pool_per_position,
                    cheap_pool_per_position=arguments.cheap_pool_per_position,
                    transfer_config=TransferPlanningConfig(),
                )
                rehearsal = MultiGwRehearsal(panel, counts, config)
                for start in starts:
                    if start + horizon_length - 1 > max(rehearsal.available_gameweeks):
                        continue
                    LOGGER.info("Season %s horizon %s: window %s", season, horizon_length, start)
                    window = rehearsal.rehearse_window(start)
                    window_records.append(
                        _window_record(season, horizon_length, start, window, counts)
                    )
    except ExperimentError as error:
        print(f"Could not measure planner horizons:\n  {error}")
        return 1
    if not window_records:
        print("No windows were evaluated; widen the start gameweeks or seasons.")
        return 1

    variants: list[Mapping[str, object]] = []
    for horizon_length in horizons:
        rows = [row for row in window_records if row["horizon_length"] == horizon_length]
        if rows:
            variants.append(_variant_summary(horizon_length, rows, seasons))

    defaults = TransferPlanningConfig()
    document = {
        **artifact_metadata(panel_rows=len(panel), created_utc=created_utc),
        "contract_version": PLANNER_HORIZON_SEASONS_CONTRACT_VERSION,
        "projection_rule": NAIVE_PROJECTION_RULE,
        "seasons": list(seasons),
        "start_gameweeks": list(starts),
        "horizons": list(horizons),
        "transfer_config": {
            "transfer_hit_cost_points": defaults.transfer_hit_cost_points,
            "horizon_discount_factor": defaults.horizon_discount_factor,
        },
        "variants": variants,
        "windows": window_records,
        "measurement_only": True,
        "locked_holdout_accessed": False,
    }
    markdown = _markdown(seasons, starts, variants, window_records)
    write_json(arguments.json_output, document)
    write_text(arguments.markdown_output, markdown)
    print(markdown)
    print(f"Wrote {arguments.json_output}")
    print(f"Wrote {arguments.markdown_output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
