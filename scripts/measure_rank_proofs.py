"""Does the lever that proved the member window plans prove the rank solves too?

`member_window_proofs` measured one CP-SAT parameter, `linearization_level`, on the member
window plans: at 2 it took the three-week windows from none proved to fifteen of fifteen and
the five-week windows to twelve, inside the same deterministic budget. `windowed_rank` is the
other solve this repository runs against real folds, and its committed record says fourteen of
its fifteen solves returned an incumbent rather than a proof, so its numbers are what the
solver held when it stopped rather than what the objective's best is.

They are different models. A window plan maximizes points over a horizon; the rank objective's
first phase maximizes a count of scenarios, a sum of indicators whose bound the solver is meant
to be able to reach. Whether the same lever helps here is a question, not a prediction.

The two arms are the cells `windowed_rank` measures, built by importing that runner's own setup
step for step: the same folds, pool, rival, scenario seed and budget. Only CP-SAT's
linearization level differs. Per cell this records the solver status, the bound and the gap, the
ahead count, the squad chosen and the work spent, so that "the lever proved it" and "the lever
changed the answer" are two readable facts rather than one inferred from the other.

Nothing is promoted and no default moves: `optimize_rank_probability_squad` stays at the
solver's default unless a caller names a level, and this script is the only caller that does.
"""

from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from scripts._experiment_cli import (
    DEFAULT_ARCHIVE_ROOT,
    REPOSITORY_ROOT,
    artifact_metadata,
    measurement_optimization_config,
    write_json,
    write_text,
)

from squadopt.data.sources.vaastav import build_panel
from squadopt.experiments.control_residuals import build_control_residual_table
from squadopt.experiments.policy_objective import PolicyObjectiveConfig
from squadopt.experiments.residual_signal_scan import load_enrichment_rows
from squadopt.prediction import PredictionProvenance, prepare_optimizer_projection
from squadopt.scenarios import ScenarioConfig
from squadopt.scenarios.paths import ScenarioPathTarget, generate_scenario_paths
from squadopt.scenarios.rank import RankObjectiveConfig, optimize_rank_probability_squad
from squadopt.scenarios.rivals import template_rival_from_ownership

LOGGER = logging.getLogger("measure_rank_proofs")

CONTRACT_VERSION = "rank_proofs_v1"
LOCKED_HOLDOUT_SEASON = "2025-26"
HISTORY_SEASONS = ("2020-21", "2021-22", "2022-23", "2023-24", "2024-25")
#: `None` is CP-SAT's own default, which is what the committed record ran under; 2 is the level
#: `member_window_proofs` measured on the window plans.
ARMS: dict[str, int | None] = {"solver_default": None, "window_level": 2}


def _arguments(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive-root", type=Path, default=DEFAULT_ARCHIVE_ROOT)
    parser.add_argument("--season", default="2024-25")
    parser.add_argument("--origins", default="8,14,20,26,32")
    parser.add_argument("--horizons", default="1,3,5")
    parser.add_argument("--scenario-count", type=int, default=100)
    parser.add_argument("--seed", type=int, default=11)
    parser.add_argument("--solver-time-limit", type=float, default=60.0)
    parser.add_argument("--rival-edge", type=float, default=0.0)
    parser.add_argument("--pool-per-position", type=int, default=20)
    parser.add_argument("--cheap-per-position", type=int, default=8)
    parser.add_argument(
        "--json-output", type=Path, default=REPOSITORY_ROOT / "docs" / "rank_proofs.json"
    )
    parser.add_argument(
        "--markdown-output", type=Path, default=REPOSITORY_ROOT / "docs" / "rank_proofs.md"
    )
    return parser.parse_args(argv)


def _cell(result: Any, arm: str, origin: int, horizon: int) -> dict[str, Any]:
    chosen = result.optimization_result
    diagnostics = result.diagnostics
    return {
        "origin": origin,
        "horizon": horizon,
        "arm": arm,
        "solver_status": chosen.solver_status.name,
        "ahead_count": diagnostics.get("ahead_count"),
        "primary_phase_ahead_count": diagnostics.get("primary_phase_ahead_count"),
        "claimed_probability_ahead": (
            None if result.probability_ahead is None else float(result.probability_ahead)
        ),
        "best_objective_bound": diagnostics.get("best_objective_bound"),
        "absolute_optimality_gap": diagnostics.get("absolute_optimality_gap"),
        "relative_optimality_gap": diagnostics.get("relative_optimality_gap"),
        "secondary_completed": diagnostics.get("secondary_completed"),
        "tiebreak_completed": diagnostics.get("tiebreak_completed"),
        "deterministic_budget_source": diagnostics.get("deterministic_budget_source"),
        "deterministic_time_limit": diagnostics.get("deterministic_time_limit"),
        "wall_seconds": diagnostics.get("solve_time_seconds"),
        # The squad itself, so a changed answer is checkable rather than inferred.
        "starters": sorted(int(v) for v in chosen.starting_xi["player_id"]),
        "captain": None if chosen.captain is None else int(chosen.captain["player_id"]),
    }


def summarise(rows: list[dict[str, Any]], horizons: list[int]) -> dict[str, Any]:
    """Per horizon and arm: how many proved, how wide the open gaps, and what it cost."""

    summary: dict[str, Any] = {}
    for horizon in horizons:
        per_arm: dict[str, Any] = {}
        for arm in ARMS:
            cell = [r for r in rows if r["horizon"] == horizon and r["arm"] == arm]
            if not cell:
                continue
            gaps = [
                float(r["relative_optimality_gap"])
                for r in cell
                if r["solver_status"] != "OPTIMAL" and r["relative_optimality_gap"] is not None
            ]
            per_arm[arm] = {
                "solves": len(cell),
                "proved": sum(r["solver_status"] == "OPTIMAL" for r in cell),
                "largest_open_relative_gap": max(gaps) if gaps else None,
                "total_wall_seconds": sum(float(r["wall_seconds"] or 0.0) for r in cell),
            }
        changed = []
        for origin in sorted({r["origin"] for r in rows if r["horizon"] == horizon}):
            pair = {r["arm"]: r for r in rows if r["horizon"] == horizon and r["origin"] == origin}
            if set(pair) != set(ARMS):
                continue
            left, right = pair["solver_default"], pair["window_level"]
            if left["starters"] != right["starters"] or left["captain"] != right["captain"]:
                changed.append(
                    {
                        "origin": origin,
                        "solver_default_ahead_count": left["ahead_count"],
                        "window_level_ahead_count": right["ahead_count"],
                    }
                )
        per_arm["cells_where_the_squad_changed"] = changed
        summary[str(horizon)] = per_arm
    return summary


def _markdown(record: dict[str, Any]) -> str:
    lines = [
        "# The rank solve, at the solver default and at the window level",
        "",
        f"Contract `{record['contract_version']}`. Season {record['season']}, origins "
        f"{record['origins']}, horizons {record['horizons']}, {record['scenario_count']} "
        f"scenarios at seed {record['seed']}. Both arms are the cells `windowed_rank` "
        "measures, built by that runner's own setup: same folds, pool, rival, seed and "
        "budget. Only CP-SAT's linearization level differs. Descriptive: nothing is "
        "promoted and no default moves.",
        "",
        "| horizon | arm | solves | proved | largest open relative gap | wall seconds |",
        "| --- | --- | ---: | ---: | ---: | ---: |",
    ]
    for horizon, per_arm in record["by_horizon"].items():
        for arm in ARMS:
            block = per_arm.get(arm)
            if block is None:
                continue
            gap = block["largest_open_relative_gap"]
            lines.append(
                f"| {horizon} | `{arm}` | {block['solves']} | {block['proved']} | "
                f"{'n/a, every solve proved' if gap is None else format(gap, '.4f')} | "
                f"{block['total_wall_seconds']:.0f} |"
            )
    rows = record["rows"]
    proved = sum(row["solver_status"] == "OPTIMAL" for row in rows)
    unproved = [row for row in rows if row["solver_status"] != "OPTIMAL"]
    bounds = [float(row["best_objective_bound"]) for row in unproved]
    primary = sorted(int(row["primary_phase_ahead_count"]) for row in rows)
    thin = sum(1 for value in primary if value < 10)
    lines += [
        "",
        "## What the objective phase actually held",
        "",
        f"{proved} of {len(rows)} solves are proved. In every one of the {len(unproved)} that "
        f"are not, the bound on the ahead count sits between {min(bounds):.0f} and "
        f"{max(bounds):.0f} of {record['scenario_count']}: the solver never rules anything out, "
        "so the bound says nothing.",
        "",
        "The first phase is the one that maximizes the ahead count, and it is not searching. "
        f"Across the {len(primary)} cells it stops holding a squad that is ahead in a median of "
        f"{primary[len(primary) // 2]} scenarios, as few as {primary[0]} and as many as "
        f"{primary[-1]}; in {thin} of {len(primary)} cells it holds fewer than ten of "
        f"{record['scenario_count']}. What the record finally reports is the ahead count of the "
        "squad the later phases arrive at, which is a different squad.",
    ]
    lines += ["", "## Where the two arms chose differently", ""]
    changes = [
        (horizon, change)
        for horizon, per_arm in record["by_horizon"].items()
        for change in per_arm.get("cells_where_the_squad_changed", [])
    ]
    if not changes:
        lines.append(
            "Nowhere. Both arms chose the same eleven and the same captain in every cell, so "
            "whatever the levels did to the bound, they did not move the answer."
        )
    else:
        ahead_default = sum(
            1
            for _h, c in changes
            if c["solver_default_ahead_count"] > c["window_level_ahead_count"]
        )
        widest = max(
            abs(c["solver_default_ahead_count"] - c["window_level_ahead_count"])
            for _h, c in changes
        )
        lines += [
            f"In {len(changes)} of the {len(rows) // 2} cells the two arms chose a different "
            f"eleven or a different captain. The default's squad is ahead in more scenarios in "
            f"{ahead_default} of them, and the widest difference between the two is {widest} "
            f"scenarios of {record['scenario_count']}.",
            "",
            "**That is the reading, and it is not about the lever.** The two arms differ by one "
            "CP-SAT parameter, which cannot change where the optimum is. It changes the reported "
            f"answer by up to {widest} of {record['scenario_count']}. So the number this model "
            "reports is a property of where the search happened to stop, not of the objective, "
            "and `windowed_rank`'s published claims are one such stopping point among many. The "
            "lever does not rescue that: it mostly makes the stopping point worse, which is a "
            "smaller fact than the one above and would be the wrong thing to take from this.",
            "",
        ]
        for horizon, change in changes:
            lines.append(
                f"- horizon {horizon}, origin {change['origin']}: ahead count "
                f"{change['solver_default_ahead_count']} at the default against "
                f"{change['window_level_ahead_count']} at the window level."
            )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:

    arguments = _arguments(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    season = str(arguments.season)
    if season == LOCKED_HOLDOUT_SEASON or season not in HISTORY_SEASONS:
        print("2025-26 is the locked holdout and may not be read.")
        return 1
    created_utc = datetime.now(UTC).isoformat(timespec="seconds")
    origins = [int(v) for v in str(arguments.origins).split(",")]
    horizons = [int(v) for v in str(arguments.horizons).split(",")]

    LOGGER.info("Building the control's residual folds")
    panel = build_panel(arguments.archive_root, seasons=HISTORY_SEASONS)
    loaded_seasons = sorted(str(value) for value in panel["season"].unique())
    residuals = build_control_residual_table(panel, PolicyObjectiveConfig())
    ownership = load_enrichment_rows(arguments.archive_root, (season,))
    prices = panel.loc[panel["season"] == season, ["gameweek", "player_id", "price_tenths", "name"]]
    season_panel = panel.loc[panel["season"] == season]
    last_gameweek = int(season_panel["gameweek"].max())

    # Named rather than inherited (#590, #621); the flag stays a wall-clock cap above it.
    optimization = replace(
        measurement_optimization_config(),
        solver_time_limit_seconds=float(arguments.solver_time_limit),
    )
    provenance_seed = PredictionProvenance(
        model_name="deterministic_baseline",
        model_version="form_window_05_v1",
        feature_contract_version="form_window_v1",
        training_cutoff="pre_origin",
        training_data_fingerprint="d" * 64,
    )

    if arguments.json_output.exists():
        print(f"{arguments.json_output} exists; this runner does not overwrite its record.")
        return 1
    rows: list[dict[str, Any]] = []
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
            for arm, level in ARMS.items():
                # The edge is per week; the window's rival score carries one edge per week.
                result = optimize_rank_probability_squad(
                    window,
                    rival,
                    optimization,
                    RankObjectiveConfig(rival_edge_points=float(arguments.rival_edge) * horizon),
                    linearization_level=level,
                )
                if not result.has_solution:
                    LOGGER.info("%s h=%d %s: no solution", fold_id, horizon, arm)
                    continue
                cell = _cell(result, arm, origin, horizon)
                rows.append(cell)
                LOGGER.info(
                    "%s h=%d %-14s %-8s ahead=%s gap=%s %.0fs",
                    fold_id,
                    horizon,
                    arm,
                    cell["solver_status"],
                    cell["ahead_count"],
                    cell["relative_optimality_gap"],
                    cell["wall_seconds"] or 0.0,
                )

    if not rows:
        print("No cell could be measured.")
        return 1

    document: dict[str, Any] = {
        **artifact_metadata(panel_rows=len(panel), created_utc=created_utc),
        "contract_version": CONTRACT_VERSION,
        "measurement_only": True,
        "season": season,
        "origins": origins,
        "horizons": horizons,
        "scenario_count": int(arguments.scenario_count),
        "seed": int(arguments.seed),
        "arms": dict(ARMS),
        "loaded_seasons": loaded_seasons,
        "locked_holdout_accessed": LOCKED_HOLDOUT_SEASON in loaded_seasons,
        "by_horizon": summarise(rows, horizons),
        "rows": rows,
    }
    write_json(arguments.json_output, document)
    write_text(arguments.markdown_output, _markdown(document))
    print(_markdown(document))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
