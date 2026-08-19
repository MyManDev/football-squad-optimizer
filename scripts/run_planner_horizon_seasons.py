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
from statistics import median, pstdev

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
from squadopt.experiments.config import PromotionPolicy
from squadopt.experiments.statistics import season_aware_moving_block_interval
from squadopt.optimization import OptimizationConfig
from squadopt.planning import TransferPlanningConfig

LOGGER = logging.getLogger(__name__)
PLANNER_HORIZON_SEASONS_CONTRACT_VERSION = "planner_horizon_seasons_v1"
DEFAULT_SEASONS = "2021-22,2022-23,2023-24,2024-25"


def _parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive-root", type=Path, default=DEFAULT_ARCHIVE_ROOT)
    parser.add_argument("--seasons", default=DEFAULT_SEASONS)
    parser.add_argument(
        "--start-gameweeks",
        default="5,10,15,20,25,30",
        help="comma list, 'all' (every decision gameweek), or 'every:N' (every N-th)",
    )
    parser.add_argument("--horizons", default="2,3,4")
    parser.add_argument(
        "--rolling",
        action="store_true",
        help="also run the rolling-horizon planner (re-plan weekly, apply week one)",
    )
    parser.add_argument(
        "--deterministic-time-limit",
        type=float,
        default=None,
        help="CP-SAT deterministic work budget per solve; when set, the wall-clock cap "
        "is raised so the deterministic budget binds and the run is reproducible",
    )
    parser.add_argument("--wall-time-limit", type=float, default=None)
    parser.add_argument("--bootstrap-resamples", type=int, default=2_000)
    parser.add_argument("--moving-block-length", type=int, default=4)
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


def _seq(value: object) -> list[object]:
    assert isinstance(value, list | tuple)
    return list(value)


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
    rolling_advantage = window.rolling_advantage_points
    rolling_statuses = window.diagnostics.get("rolling_solver_statuses", [])
    assert isinstance(rolling_statuses, list | tuple)
    rolling_gaps = window.diagnostics.get("rolling_relative_gaps", [])
    assert isinstance(rolling_gaps, list | tuple)
    return {
        "rolling_realized_points": window.rolling_realized_points,
        "rolling_transfer_hit_points": window.rolling_transfer_hit_points,
        "rolling_advantage_points": rolling_advantage,
        "rolling_selection_advantage_points": (
            None
            if window.rolling_realized_points is None
            else float(window.rolling_realized_points) - myopic
        ),
        "rolling_transfers_by_week": _ints(window.diagnostics.get("rolling_transfers", [])),
        "rolling_solver_statuses": [str(value) for value in rolling_statuses],
        "rolling_relative_gaps": [
            None if value is None else float(str(value)) for value in rolling_gaps
        ],
        "planner_solver_status": str(window.diagnostics.get("planner_solver_status")),
        "planner_relative_gap": window.diagnostics.get("planner_relative_gap"),
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


def _interval(
    rows: list[dict[str, object]],
    key: str,
    *,
    resamples: int,
    block_length: int,
    label: str,
) -> tuple[float, float] | None:
    pairs = [(str(row["season"]), float(str(row[key]))) for row in rows if row.get(key) is not None]
    if len(pairs) < 2:
        return None
    policy = PromotionPolicy(
        bootstrap_resamples=resamples,
        moving_block_length=block_length,
    )
    return season_aware_moving_block_interval(pairs, policy=policy, candidate_id=label)


def _proven_share(rows: list[dict[str, object]], key: str) -> float | None:
    statuses = [str(status) for row in rows for status in _seq(row.get(key, []))]
    if not statuses:
        return None
    return sum(1 for status in statuses if status == "OPTIMAL") / len(statuses)


def _mean_gap(rows: list[dict[str, object]], key: str) -> float | None:
    gaps = [float(str(gap)) for row in rows for gap in _seq(row.get(key, [])) if gap is not None]
    return sum(gaps) / len(gaps) if gaps else None


def _variant_summary(
    horizon_length: int,
    rows: list[dict[str, object]],
    seasons: tuple[str, ...],
    *,
    resamples: int = 2_000,
    block_length: int = 4,
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
    # A window is "calendar-structured" when some team has a double or a blank in a
    # week the plan looks ahead to (week two onward). Under naive calendar scaling that
    # structure is the only thing that makes one week's projection differ from another,
    # so it separates windows where a plan can differ from a repeated weekly choice
    # from windows where only information staleness can.
    structured = [row for row in rows if _looks_ahead_at_structure(row)]
    plain = [row for row in rows if not _looks_ahead_at_structure(row)]
    stdev = float(pstdev(advantages)) if len(advantages) > 1 else 0.0
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
        "mean_myopic_hit_points_per_window": sum(
            float(str(row["myopic_transfer_hit_points"])) for row in rows
        )
        / len(rows),
        "advantage_stdev": stdev,
        "advantage_standard_error": stdev / len(advantages) ** 0.5,
        "mean_advantage_by_season": by_season,
        "calendar_structured_windows": _split_summary(structured),
        "plain_windows": _split_summary(plain),
        "advantage_block_bootstrap_interval": _interval(
            rows,
            "planning_advantage_points",
            resamples=resamples,
            block_length=block_length,
            label=f"one_shot_h{horizon_length}",
        ),
        "planner_proven_share": (
            sum(1 for row in rows if row.get("planner_solver_status") == "OPTIMAL") / len(rows)
        ),
        "rolling": _rolling_summary(
            horizon_length, rows, resamples=resamples, block_length=block_length
        ),
    }


def _rolling_summary(
    horizon_length: int,
    rows: list[dict[str, object]],
    *,
    resamples: int,
    block_length: int,
) -> dict[str, object] | None:
    scored = [row for row in rows if row.get("rolling_advantage_points") is not None]
    if not scored:
        return None
    advantages = [float(str(row["rolling_advantage_points"])) for row in scored]
    selection = [float(str(row["rolling_selection_advantage_points"])) for row in scored]
    hits = [
        float(str(row["rolling_transfer_hit_points"]))
        - float(str(row["myopic_transfer_hit_points"]))
        for row in scored
    ]
    stdev = float(pstdev(advantages)) if len(advantages) > 1 else 0.0
    return {
        "windows": len(scored),
        "mean_advantage_points": sum(advantages) / len(advantages),
        "median_advantage_points": float(median(advantages)),
        "advantage_standard_error": stdev / len(advantages) ** 0.5,
        "positive_window_share": sum(1 for value in advantages if value > 0) / len(advantages),
        "mean_selection_advantage_points": sum(selection) / len(selection),
        "mean_hit_disadvantage_points": sum(hits) / len(hits),
        "advantage_block_bootstrap_interval": _interval(
            scored,
            "rolling_advantage_points",
            resamples=resamples,
            block_length=block_length,
            label=f"rolling_h{horizon_length}",
        ),
        "proven_week_share": _proven_share(scored, "rolling_solver_statuses"),
        "mean_relative_gap_unproven": _mean_gap(scored, "rolling_relative_gaps"),
        "total_transfers": sum(sum(_ints(row["rolling_transfers_by_week"])) for row in scored),
    }


def _looks_ahead_at_structure(row: dict[str, object]) -> bool:
    doubles = _ints(row["double_gameweek_teams"])[1:]
    blanks = _ints(row["blank_gameweek_teams"])[1:]
    return any(value > 0 for value in doubles) or any(value > 0 for value in blanks)


def _split_summary(rows: list[dict[str, object]]) -> dict[str, object]:
    if not rows:
        return {
            "windows": 0,
            "mean_planning_advantage_points": None,
            "mean_selection_advantage_points": None,
            "mean_hit_disadvantage_points": None,
        }
    return {
        "windows": len(rows),
        "mean_planning_advantage_points": sum(
            float(str(row["planning_advantage_points"])) for row in rows
        )
        / len(rows),
        "mean_selection_advantage_points": sum(
            float(str(row["selection_advantage_points"])) for row in rows
        )
        / len(rows),
        "mean_hit_disadvantage_points": sum(
            float(str(row["hit_disadvantage_points"])) for row in rows
        )
        / len(rows),
    }


def _markdown(
    seasons: tuple[str, ...],
    starts: tuple[int, ...],
    variants: list[Mapping[str, object]],
    windows: list[dict[str, object]],
    skipped: list[dict[str, object]],
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
        "| Horizon | Windows | Mean adv | SE | Median | Per GW | Positive share "
        "| Min | Max | Selection | Hit disadv | Transfers | Hit pts | Myopic hits/window |",
        "| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: "
        "| ---: | ---: |",
    ]
    for record in variants:
        lines.append(
            f"| {record['horizon_length']} | {record['windows']} "
            f"| {float(str(record['mean_planning_advantage_points'])):+.2f} "
            f"| {float(str(record['advantage_standard_error'])):.2f} "
            f"| {float(str(record['median_planning_advantage_points'])):+.1f} "
            f"| {float(str(record['mean_advantage_per_gameweek'])):+.2f} "
            f"| {float(str(record['positive_window_share'])):.2f} "
            f"| {float(str(record['min_advantage'])):+.1f} "
            f"| {float(str(record['max_advantage'])):+.1f} "
            f"| {float(str(record['mean_selection_advantage_points'])):+.2f} "
            f"| {float(str(record['mean_hit_disadvantage_points'])):+.2f} "
            f"| {record['total_planner_transfers']} "
            f"| {float(str(record['total_planner_hit_points'])):.0f} "
            f"| {float(str(record['mean_myopic_hit_points_per_window'])):.2f} |"
        )
    lines += [
        "",
        "## Calendar-structured versus plain windows",
        "",
        "A window is calendar-structured when a double or blank gameweek falls in a week "
        "the plan looks ahead to (week two onward); under naive calendar scaling that is "
        "the only way one week's projection differs from another's.",
        "",
        "| Horizon | Structured windows | Adv | Selection | Hit disadv "
        "| Plain windows | Adv | Selection | Hit disadv |",
        "| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for record in variants:
        cells = [str(record["horizon_length"])]
        for key in ("calendar_structured_windows", "plain_windows"):
            split = record[key]
            assert isinstance(split, dict)
            cells.append(str(split["windows"]))
            for metric in (
                "mean_planning_advantage_points",
                "mean_selection_advantage_points",
                "mean_hit_disadvantage_points",
            ):
                value = split[metric]
                cells.append("-" if value is None else f"{float(str(value)):+.2f}")
        lines.append("| " + " | ".join(cells) + " |")
    lines += [
        "",
        "## Confidence and solve quality",
        "",
        "Season-aware moving-block bootstrap intervals (90%) on the per-window advantages; "
        "proven share = solves that reached OPTIMAL under the run's solver limits.",
        "",
        "| Horizon | One-shot 90% interval | One-shot proven | Rolling windows | Rolling mean "
        "| Rolling SE | Rolling 90% interval | Rolling positive | Rolling selection "
        "| Rolling hit disadv | Rolling proven weeks | Mean gap (unproven) |",
        "| ---: | --- | ---: | ---: | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for record in variants:
        interval = record.get("advantage_block_bootstrap_interval")
        one_shot_interval = (
            "-" if interval is None else f"[{float(interval[0]):+.2f}, {float(interval[1]):+.2f}]"  # type: ignore[index]
        )
        rolling = record.get("rolling")
        if isinstance(rolling, dict):
            r_interval = rolling.get("advantage_block_bootstrap_interval")
            r_text = (
                "-"
                if r_interval is None
                else f"[{float(r_interval[0]):+.2f}, {float(r_interval[1]):+.2f}]"
            )
            proven = rolling.get("proven_week_share")
            gap = rolling.get("mean_relative_gap_unproven")
            rolling_cells = (
                f"| {rolling['windows']} | {float(str(rolling['mean_advantage_points'])):+.2f} "
                f"| {float(str(rolling['advantage_standard_error'])):.2f} | {r_text} "
                f"| {float(str(rolling['positive_window_share'])):.2f} "
                f"| {float(str(rolling['mean_selection_advantage_points'])):+.2f} "
                f"| {float(str(rolling['mean_hit_disadvantage_points'])):+.2f} "
                f"| {'-' if proven is None else f'{float(str(proven)):.2f}'} "
                f"| {'-' if gap is None else f'{float(str(gap)):.3f}'} |"
            )
        else:
            rolling_cells = "| - | - | - | - | - | - | - | - | - |"
        lines.append(
            f"| {record['horizon_length']} | {one_shot_interval} "
            f"| {float(str(record['planner_proven_share'])):.2f} " + rolling_cells
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
        "| Advantage | Rolling adv | Transfers by week | DGW teams by week "
        "| Blank teams by week |",
        "| --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- | --- |",
    ]
    for row in windows:
        rolling_value = row.get("rolling_advantage_points")
        rolling_text = "-" if rolling_value is None else f"{float(str(rolling_value)):+.0f}"
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
            f"| {rolling_text} | {transfers} | {doubles} | {blanks} |"
        )
    if skipped:
        lines += ["", "## Skipped windows", ""]
        for entry in skipped:
            lines.append(f"- {entry['season']} start {entry['start_gameweek']}: {entry['reason']}")
    lines += [
        "",
        "Every horizon is measured on the same windows; a start is dropped for all",
        "horizons when the longest one does not fit the season's decision points.",
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
    horizons = tuple(int(value.strip()) for value in str(arguments.horizons).split(","))
    panel = build_panel(arguments.archive_root)
    start_spec = str(arguments.start_gameweeks).strip()
    if start_spec == "all":
        starts = tuple(range(2, 39))
    elif start_spec.startswith("every:"):
        stride = int(start_spec.split(":", 1)[1])
        starts = tuple(range(2, 39, stride))
    else:
        starts = tuple(int(value.strip()) for value in start_spec.split(","))
    optimization_config = OptimizationConfig()
    if arguments.deterministic_time_limit is not None or arguments.wall_time_limit is not None:
        wall = arguments.wall_time_limit
        if wall is None:
            # Raise the wall-clock cap well above the deterministic budget so the
            # deterministic budget is the binding stopping rule.
            wall = max(60.0, 6.0 * float(arguments.deterministic_time_limit or 10.0))
        optimization_config = OptimizationConfig(
            solver_time_limit_seconds=wall,
            solver_deterministic_time_limit=arguments.deterministic_time_limit,
        )

    window_records: list[dict[str, object]] = []
    skipped: list[dict[str, object]] = []
    longest = max(horizons)
    try:
        for season in seasons:
            counts = _fixture_counts(arguments.archive_root, season)
            season_starts: tuple[int, ...] | None = None
            for horizon_length in horizons:
                config = MultiGwRehearsalConfig(
                    season=season,
                    horizon_length=horizon_length,
                    form_window=arguments.form_window,
                    candidate_pool_per_position=arguments.candidate_pool_per_position,
                    cheap_pool_per_position=arguments.cheap_pool_per_position,
                    transfer_config=TransferPlanningConfig(),
                    optimization_config=optimization_config,
                    rolling_replan=bool(arguments.rolling),
                )
                rehearsal = MultiGwRehearsal(panel, counts, config)
                if season_starts is None:
                    # Every horizon is measured on the same windows: a start is kept
                    # only if the longest horizon fits inside the season's decision
                    # points, so a postponed gameweek (2022-23 GW7) removes the window
                    # for all horizons rather than for the long ones alone.
                    available = set(rehearsal.available_gameweeks)
                    kept: list[int] = []
                    for start in starts:
                        span = range(start, start + longest)
                        if all(gameweek in available for gameweek in span):
                            kept.append(start)
                        else:
                            skipped.append(
                                {
                                    "season": season,
                                    "start_gameweek": start,
                                    "reason": "a gameweek of the longest window is not a "
                                    "decision point in this season",
                                }
                            )
                    season_starts = tuple(kept)
                for start in season_starts:
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
            variants.append(
                _variant_summary(
                    horizon_length,
                    rows,
                    seasons,
                    resamples=arguments.bootstrap_resamples,
                    block_length=arguments.moving_block_length,
                )
            )

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
        "solver_limits": {
            "solver_time_limit_seconds": optimization_config.solver_time_limit_seconds,
            "solver_deterministic_time_limit": optimization_config.solver_deterministic_time_limit,
        },
        "rolling_replan": bool(arguments.rolling),
        "start_gameweeks_spec": start_spec,
        "bootstrap": {
            "resamples": arguments.bootstrap_resamples,
            "moving_block_length": arguments.moving_block_length,
            "confidence_level": 0.90,
        },
        "variants": variants,
        "windows": window_records,
        "skipped_windows": skipped,
        "measurement_only": True,
        "locked_holdout_accessed": False,
    }
    markdown = _markdown(seasons, starts, variants, window_records, skipped)
    write_json(arguments.json_output, document)
    write_text(arguments.markdown_output, markdown)
    print(markdown)
    print(f"Wrote {arguments.json_output}")
    print(f"Wrote {arguments.markdown_output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
