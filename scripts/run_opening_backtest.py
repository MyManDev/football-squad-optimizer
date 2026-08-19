"""Backtest opening-gameweek squad decisions on historical GW1s.

    python -m scripts.run_opening_backtest

The season opens in days, and the GW1 decision runs on a different pipeline than
every midseason fold: carry-over plus the fitted price prior, no within-season form.
This backtest asks the decision-level question for each historical development GW1 -
what did the opening pipeline's chosen squad actually score, and does the bench
weight matter at GW1? History is strictly prior completed seasons; the 2025-26
locked holdout is never read.
"""

import argparse
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path

from scripts._experiment_cli import (
    DEFAULT_ARCHIVE_ROOT,
    REPOSITORY_ROOT,
    artifact_metadata,
    write_json,
    write_text,
)

from squadopt.backtest import season_ranks
from squadopt.data.sources.vaastav import build_panel
from squadopt.optimization import OptimizationConfig, optimize_squad
from squadopt.prediction import build_opening_projection_table

LOGGER = logging.getLogger(__name__)
OPENING_BACKTEST_CONTRACT_VERSION = "opening_decision_backtest_v1"
BACKTEST_SEASONS = ("2021-22", "2022-23", "2023-24", "2024-25")
BENCH_WEIGHTS = (0.0, 0.1, 0.25)


def _parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive-root", type=Path, default=DEFAULT_ARCHIVE_ROOT)
    parser.add_argument(
        "--json-output",
        type=Path,
        default=REPOSITORY_ROOT / "docs" / "opening_backtest.json",
    )
    parser.add_argument(
        "--markdown-output",
        type=Path,
        default=REPOSITORY_ROOT / "docs" / "opening_backtest.md",
    )
    return parser.parse_args()


def main() -> int:
    arguments = _parse_arguments()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    if not arguments.archive_root.is_dir():
        print(f"Archive not found at {arguments.archive_root}.")
        return 1

    created_utc = datetime.now(UTC).isoformat(timespec="seconds")
    panel = build_panel(arguments.archive_root)
    ranks = season_ranks(panel)
    rank_of_row = panel["season"].map(lambda value: ranks[str(value)])
    rows: list[dict[str, object]] = []
    for season in BACKTEST_SEASONS:
        LOGGER.info("Opening decision for %s", season)
        history = panel.loc[rank_of_row < ranks[season]]
        opening_rows = panel.loc[(panel["season"] == season) & (panel["gameweek"] == 1)]
        if opening_rows.empty:
            print(f"Season {season} has no GW1 rows in the panel.")
            return 1
        # The opening builder expects the live roster's raw shape; team names are
        # factorized to stable integers, which only the per-club limit reads.
        team_code = {
            name: index
            for index, name in enumerate(sorted(set(opening_rows["team_id"].astype(str))), 1)
        }
        roster = (
            opening_rows.assign(
                code=opening_rows["player_id"],
                web_name=opening_rows["name"],
                team=opening_rows["team_id"].astype(str).map(team_code),
                now_cost=opening_rows["price_tenths"],
            )
            .loc[:, ["code", "web_name", "team", "position", "now_cost"]]
            .reset_index(drop=True)
        )
        projection = build_opening_projection_table(history, roster, season=season)
        prior_share = float(projection["has_prior_record"].mean())
        realized = opening_rows.loc[:, ["player_id", "total_points"]].reset_index(drop=True)
        points = {
            player_id: float(total)
            for player_id, total in zip(
                realized["player_id"].tolist(), realized["total_points"].tolist(), strict=True
            )
        }
        for bench_weight in BENCH_WEIGHTS:
            result = optimize_squad(
                projection.loc[
                    :,
                    [
                        "player_id",
                        "name",
                        "team_id",
                        "position",
                        "price_tenths",
                        "expected_points",
                    ],
                ],
                OptimizationConfig(bench_weight=bench_weight),
            )
            if not result.has_solution or result.captain is None:
                print(f"Season {season} bench_weight {bench_weight}: no feasible squad.")
                return 1
            starters = result.starting_xi["player_id"].tolist()
            captain = result.captain["player_id"]
            score = sum(points[player] for player in starters) + points[captain]
            rows.append(
                {
                    "season": season,
                    "bench_weight": bench_weight,
                    "realized_gw1_score": score,
                    "projected_gw1_score": float(result.projected_score or 0.0),
                    "prior_record_share": prior_share,
                }
            )

    by_weight: dict[float, list[float]] = {weight: [] for weight in BENCH_WEIGHTS}
    for row in rows:
        weight = row["bench_weight"]
        score = row["realized_gw1_score"]
        assert isinstance(weight, float) and isinstance(score, float)
        by_weight[weight].append(score)

    document = {
        **artifact_metadata(panel_rows=len(panel), created_utc=created_utc),
        "contract_version": OPENING_BACKTEST_CONTRACT_VERSION,
        "seasons": list(BACKTEST_SEASONS),
        "bench_weights": list(BENCH_WEIGHTS),
        "rows": rows,
        "mean_realized_by_bench_weight": {
            f"{weight:.2f}": sum(scores) / len(scores) for weight, scores in by_weight.items()
        },
        "measurement_only": True,
        "locked_holdout_accessed": False,
    }

    lines = [
        "# Opening-gameweek decision backtest",
        "",
        f"- Contract: `{OPENING_BACKTEST_CONTRACT_VERSION}`",
        "- History strictly prior completed seasons; the 2025-26 locked holdout was not read",
        "",
        "| Season | bench_weight | Realized GW1 | Projected | Prior-record share |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for row in rows:
        lines.append(
            f"| {row['season']} | {row['bench_weight']:.2f} "
            f"| {row['realized_gw1_score']:.0f} | {row['projected_gw1_score']:.1f} "
            f"| {row['prior_record_share']:.2%} |"
        )
    lines += ["", "| bench_weight | Mean realized GW1 |", "| ---: | ---: |"]
    for weight, scores in by_weight.items():
        lines.append(f"| {weight:.2f} | {sum(scores) / len(scores):.1f} |")
    lines += [
        "",
        "Measurement only, ahead of the 2026-27 opening deadline. Nothing is",
        "promoted; the live GW1 decision still uses the operational control.",
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
