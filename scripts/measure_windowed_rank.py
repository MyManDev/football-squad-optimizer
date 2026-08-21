"""P(ahead of the crowd) over one, three and five weeks, on real residual paths.

    python -m scripts.measure_windowed_rank

The product sentence needs a window: "to pass this rival over the next three weeks, play
this squad; the probability is X and the cost is Y." Until now the rank objective could
only price a single gameweek. The path generator (#144/#146) produces joint multi-week
scenarios, and `as_window_scenario_set` presents a window as one ScenarioSet, so the same
solver prices it unchanged. This runs that end to end on real data: at several origins of
2024-25, against the ownership template (the crowd's most-owned eleven at the origin),
for horizons one, three and five.

Honest limits: the per-week projection inside a window repeats the origin's projection
(the control produces one week; a calendar-aware GW2+ projection is the data side's
deliverable), and realized outcomes are the window's actual totals. Descriptive
measurement — no gate, nothing promoted, the locked holdout never read.
"""

import argparse
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
from scripts._experiment_cli import (
    DEFAULT_ARCHIVE_ROOT,
    REPOSITORY_ROOT,
    artifact_metadata,
    write_json,
    write_text,
)

from squadopt.data.sources.vaastav import build_panel
from squadopt.experiments.control_residuals import build_control_residual_table
from squadopt.experiments.policy_objective import PolicyObjectiveConfig
from squadopt.experiments.residual_signal_scan import load_enrichment_rows
from squadopt.optimization import OptimizationConfig
from squadopt.prediction import PredictionProvenance, prepare_optimizer_projection
from squadopt.scenarios import ScenarioConfig
from squadopt.scenarios.paths import ScenarioPathTarget, generate_scenario_paths
from squadopt.scenarios.rank import RankObjectiveConfig, optimize_rank_probability_squad
from squadopt.scenarios.rivals import template_rival_from_ownership

LOGGER = logging.getLogger(__name__)


def _parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive-root", type=Path, default=DEFAULT_ARCHIVE_ROOT)
    parser.add_argument("--season", default="2024-25")
    parser.add_argument("--origins", default="8,14,20,26,32")
    parser.add_argument("--horizons", default="1,3,5")
    parser.add_argument("--scenario-count", type=int, default=100)
    parser.add_argument("--seed", type=int, default=11)
    parser.add_argument("--solver-time-limit", type=float, default=60.0)
    parser.add_argument(
        "--rival-edge",
        type=float,
        default=0.0,
        help="Points per week added to the rival's scenario scores; the crowd's measured "
        "edge over the projection is +7.19 (template_rival_strength).",
    )
    parser.add_argument("--pool-per-position", type=int, default=20)
    parser.add_argument("--cheap-per-position", type=int, default=8)
    parser.add_argument(
        "--json-output",
        type=Path,
        default=REPOSITORY_ROOT / "docs" / "windowed_rank.json",
    )
    parser.add_argument(
        "--markdown-output",
        type=Path,
        default=REPOSITORY_ROOT / "docs" / "windowed_rank.md",
    )
    return parser.parse_args()


def main() -> int:
    arguments = _parse_arguments()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    season = str(arguments.season)
    if season == "2025-26":
        print("2025-26 is the locked holdout and may not be read.")
        return 1
    created_utc = datetime.now(UTC).isoformat(timespec="seconds")
    origins = [int(v) for v in str(arguments.origins).split(",")]
    horizons = [int(v) for v in str(arguments.horizons).split(",")]

    LOGGER.info("Building the control's residual folds")
    panel = build_panel(arguments.archive_root)
    residuals = build_control_residual_table(panel, PolicyObjectiveConfig())
    ownership = load_enrichment_rows(arguments.archive_root, (season,))
    prices = panel.loc[panel["season"] == season, ["gameweek", "player_id", "price_tenths", "name"]]
    season_panel = panel.loc[panel["season"] == season]
    last_gameweek = int(season_panel["gameweek"].max())

    optimization = OptimizationConfig(solver_time_limit_seconds=float(arguments.solver_time_limit))
    provenance_seed = PredictionProvenance(
        model_name="deterministic_baseline",
        model_version="form_window_05_v1",
        feature_contract_version="form_window_v1",
        training_cutoff="pre_origin",
        training_data_fingerprint="d" * 64,
    )

    rows: list[dict[str, object]] = []
    for origin in origins:
        fold_id = f"{season}-gw{origin:02d}"
        block = residuals.loc[residuals["fold_id"] == fold_id]
        if block.empty:
            LOGGER.info("%s: no fold, skipped", fold_id)
            continue
        history = residuals.loc[residuals["fold_id"] < fold_id]
        pool = block.merge(
            prices.loc[prices["gameweek"] == origin, ["player_id", "price_tenths", "name"]],
            on="player_id",
            how="inner",
        )
        own = ownership.loc[ownership["gameweek"] == origin, ["player_id", "selected"]]
        pool = pool.merge(own, on="player_id", how="left")
        pool["ownership"] = pool["selected"].fillna(0.0)
        rival = template_rival_from_ownership(pool.loc[:, ["player_id", "position", "ownership"]])
        # The full 700-player pool is far beyond what the three-phase rank model can
        # search in a minute. The rehearsal's candidate-pool rule is reused: the best
        # projected players per position, the cheapest per position as enablers, and the
        # rival's whole eleven so the comparison squad is always in the model.
        keep: set[int] = {int(str(p)) for p in rival.starter_ids}
        for _position, block_p in pool.groupby("position"):
            best = block_p.sort_values("predicted_points", ascending=False).head(
                int(arguments.pool_per_position)
            )
            cheap = block_p.sort_values("price_tenths", ascending=True).head(
                int(arguments.cheap_per_position)
            )
            keep.update(int(v) for v in best["player_id"])
            keep.update(int(v) for v in cheap["player_id"])
        pool = pool.loc[pool["player_id"].isin(keep)].reset_index(drop=True)
        snapshot = prepare_optimizer_projection(
            pool.loc[:, ["player_id", "name", "team_id", "position", "price_tenths"]],
            pool.assign(expected_points=pool["predicted_points"].clip(lower=0.0)).loc[
                :, ["player_id", "expected_points"]
            ],
            provenance_seed,
        )
        for horizon in horizons:
            if origin + horizon - 1 > last_gameweek:
                continue
            target = ScenarioPathTarget(season, origin, horizon)
            paths = generate_scenario_paths(
                dict.fromkeys(target.gameweeks, snapshot),
                history,
                target,
                ScenarioConfig(
                    scenario_count=int(arguments.scenario_count),
                    deterministic_seed=int(arguments.seed),
                ),
            )
            window = paths.as_window_scenario_set()
            # The edge is per week; the window's rival score carries one edge per week.
            result = optimize_rank_probability_squad(
                window,
                rival,
                optimization,
                RankObjectiveConfig(rival_edge_points=float(arguments.rival_edge) * horizon),
            )
            if not result.has_solution or result.probability_ahead is None:
                LOGGER.info("%s h=%d: no solution", fold_id, horizon)
                continue
            chosen = result.optimization_result
            assert chosen.captain is not None
            realized = (
                season_panel.loc[
                    (season_panel["gameweek"] >= origin)
                    & (season_panel["gameweek"] < origin + horizon)
                ]
                .groupby("player_id")["total_points"]
                .sum()
            )
            starters = [int(v) for v in chosen.starting_xi["player_id"]]
            captain = int(chosen.captain["player_id"])
            my_realized = float(sum(float(realized.get(p, 0.0)) for p in starters)) + float(
                realized.get(captain, 0.0)
            )
            rival_realized = float(
                sum(float(realized.get(int(str(p)), 0.0)) for p in rival.starter_ids)
            ) + float(realized.get(int(str(rival.captain_id)), 0.0))
            rows.append(
                {
                    "origin": origin,
                    "horizon": horizon,
                    "claimed_probability_ahead": float(result.probability_ahead),
                    "scenario_mean_score": float(result.scenario_mean_score or 0.0),
                    "realized_score": my_realized,
                    "rival_realized_score": rival_realized,
                    "realized_ahead": bool(my_realized > rival_realized),
                    "shared_starters": len(
                        set(starters) & {int(str(p)) for p in rival.starter_ids}
                    ),
                    "solver_status": chosen.solver_status.name,
                }
            )
            LOGGER.info(
                "%s h=%d claimed %.2f realized %s (%.0f vs %.0f)",
                fold_id,
                horizon,
                result.probability_ahead,
                "ahead" if my_realized > rival_realized else "behind",
                my_realized,
                rival_realized,
            )

    if not rows:
        print("No cell could be measured.")
        return 1
    by_horizon: dict[int, dict[str, float]] = {}
    for horizon in horizons:
        cells = [row for row in rows if row["horizon"] == horizon]
        if not cells:
            continue
        by_horizon[horizon] = {
            "cells": len(cells),
            "mean_claimed": float(np.mean([c["claimed_probability_ahead"] for c in cells])),
            "realized_ahead_share": float(np.mean([c["realized_ahead"] for c in cells])),
            "mean_shared_starters": float(np.mean([c["shared_starters"] for c in cells])),
        }
    document = {
        **artifact_metadata(panel_rows=len(panel), created_utc=created_utc),
        "contract_version": "windowed_rank_v1",
        "season": season,
        "origins": origins,
        "horizons": horizons,
        "scenario_count": int(arguments.scenario_count),
        "rival_edge_points_per_week": float(arguments.rival_edge),
        "by_horizon": {str(k): v for k, v in by_horizon.items()},
        "rows": rows,
        "projection_note": (
            "Each window week repeats the origin's projection; the control produces one "
            "week and the calendar-aware GW2+ projection is the data side's deliverable."
        ),
        "measurement_only": True,
        "locked_holdout_accessed": False,
    }
    markdown = _to_markdown(document)
    write_json(arguments.json_output, document)
    write_text(arguments.markdown_output, markdown)
    print(markdown)
    print(f"Wrote {arguments.json_output}")
    print(f"Wrote {arguments.markdown_output}")
    return 0


def _to_markdown(document: dict[str, object]) -> str:
    lines = [
        "# P(ahead of the crowd) over a window",
        "",
        f"- Contract `{document['contract_version']}`; {document['season']}, origins "
        f"{document['origins']}, horizons {document['horizons']}, "
        f"{document['scenario_count']} paths per window.",
        "- The rival is the ownership template at the origin; the squad is chosen by the "
        "rank objective on the window's joint path totals via `as_window_scenario_set` — "
        "the same solver that prices a single week, unchanged.",
        f"- {document['projection_note']}",
        f"- Rival edge: **{float(str(document.get('rival_edge_points_per_week', 0.0))):+.2f} "
        "points per week** added to the rival's scenario scores (zero = the crowd priced at "
        "the projection, the historical behaviour).",
        "- Descriptive measurement: no gate, nothing promoted, locked holdout untouched.",
        "",
        "| Horizon | Windows | Mean claimed P(ahead) | Realized ahead share | Shared starters |",
        "| ---: | ---: | ---: | ---: | ---: |",
    ]
    by_horizon = document["by_horizon"]
    assert isinstance(by_horizon, dict)
    for horizon, values in sorted(by_horizon.items(), key=lambda kv: int(kv[0])):
        lines.append(
            f"| {horizon} | {values['cells']:.0f} | {values['mean_claimed']:.2f} "
            f"| {values['realized_ahead_share']:.2f} | {values['mean_shared_starters']:.1f} |"
        )
    lines += [
        "",
        "Per window:",
        "",
        "| Origin | Horizon | Claimed | Realized | Mine | Crowd |",
        "| ---: | ---: | ---: | --- | ---: | ---: |",
    ]
    rows = document["rows"]
    assert isinstance(rows, list)
    for row in rows:
        lines.append(
            f"| {row['origin']} | {row['horizon']} | {row['claimed_probability_ahead']:.2f} "
            f"| {'ahead' if row['realized_ahead'] else 'behind'} "
            f"| {row['realized_score']:.0f} | {row['rival_realized_score']:.0f} |"
        )
    lines.append("")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    sys.exit(main())
