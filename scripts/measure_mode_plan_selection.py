"""One window, four play modes, a menu of plans: does the mode change the plan?

    python -m scripts.measure_mode_plan_selection

The product flow is: choose a window, choose a mode (Saf Puan / Garantici / Agresif /
Asiri Agresif), get a transfer-and-chip plan with a price tag. This runs that flow once,
end to end, on real data: a real origin of 2024-25, a real held squad, the planner
generating a menu of candidate plans (its own choice, no chips, and every forced chip
placement in the window), joint scenario paths pricing every candidate, the ownership
template as the rival, and each mode picking from the same menu.

The interesting output is disagreement: where the modes pick different plans, the mode
selector earns its place; where they all agree, the selector is decoration for that week.
Descriptive measurement — no gate, nothing promoted, the locked holdout never read.
"""

import argparse
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter

from scripts._experiment_cli import (
    DEFAULT_ARCHIVE_ROOT,
    REPOSITORY_ROOT,
    artifact_metadata,
    write_json,
    write_text,
)

from squadopt.data.sources.vaastav import build_panel
from squadopt.experiments.control_residuals import build_control_residual_table
from squadopt.experiments.plan_selection import (
    PLAN_SELECTION_CONTRACT_VERSION,
    generate_candidate_plans,
    select_plan,
    selection_to_dict,
)
from squadopt.experiments.policy_objective import PolicyObjectiveConfig
from squadopt.experiments.residual_signal_scan import load_enrichment_rows
from squadopt.optimization import OptimizationConfig, optimize_squad
from squadopt.planning import InitialSquadState, PlanningHorizon
from squadopt.prediction import PredictionProvenance, prepare_optimizer_projection
from squadopt.scenarios import ScenarioConfig
from squadopt.scenarios.paths import ScenarioPathTarget, generate_scenario_paths
from squadopt.scenarios.rivals import template_rival_from_ownership

LOGGER = logging.getLogger(__name__)


def _parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive-root", type=Path, default=DEFAULT_ARCHIVE_ROOT)
    parser.add_argument("--season", default="2024-25")
    parser.add_argument("--origin", type=int, default=20)
    parser.add_argument("--horizon", type=int, default=3)
    parser.add_argument("--scenario-count", type=int, default=200)
    parser.add_argument("--seed", type=int, default=11)
    parser.add_argument("--solver-time-limit", type=float, default=30.0)
    parser.add_argument("--pool-per-position", type=int, default=15)
    parser.add_argument("--cheap-per-position", type=int, default=5)
    parser.add_argument(
        "--json-output",
        type=Path,
        default=REPOSITORY_ROOT / "docs" / "mode_plan_selection.json",
    )
    parser.add_argument(
        "--markdown-output",
        type=Path,
        default=REPOSITORY_ROOT / "docs" / "mode_plan_selection.md",
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
    origin = int(arguments.origin)
    horizon = int(arguments.horizon)
    started = perf_counter()

    LOGGER.info("Building the control's residual folds")
    panel = build_panel(arguments.archive_root)
    residuals = build_control_residual_table(panel, PolicyObjectiveConfig())
    fold_id = f"{season}-gw{origin:02d}"
    block = residuals.loc[residuals["fold_id"] == fold_id]
    if block.empty:
        print(f"No fold at {fold_id}.")
        return 1
    history = residuals.loc[residuals["fold_id"] < fold_id]
    prices = panel.loc[panel["season"] == season, ["gameweek", "player_id", "price_tenths", "name"]]
    pool = block.merge(
        prices.loc[prices["gameweek"] == origin, ["player_id", "price_tenths", "name"]],
        on="player_id",
        how="inner",
    )
    ownership = load_enrichment_rows(arguments.archive_root, (season,))
    own = ownership.loc[ownership["gameweek"] == origin, ["player_id", "selected"]]
    pool = pool.merge(own, on="player_id", how="left")
    pool["ownership"] = pool["selected"].fillna(0.0)
    rival = template_rival_from_ownership(pool.loc[:, ["player_id", "position", "ownership"]])

    # The same candidate-pool rule the rank rehearsal uses, so the planner and the paths
    # work on a searchable pool; the rival's eleven and the held squad always stay in.
    optimization = OptimizationConfig(solver_time_limit_seconds=float(arguments.solver_time_limit))
    full_projection = pool.loc[
        :, ["player_id", "name", "team_id", "position", "price_tenths"]
    ].copy()
    full_projection["expected_points"] = pool["predicted_points"].clip(lower=0.0)
    held = optimize_squad(full_projection, optimization)
    if not held.has_solution:
        print("The held squad could not be built.")
        return 1
    held_ids = {int(v) for v in held.selected_squad["player_id"]}
    held_cost = int(held.selected_squad["price_tenths"].sum())

    keep: set[int] = {int(str(p)) for p in rival.starter_ids} | held_ids
    for _, block_p in pool.groupby("position"):
        keep.update(
            int(v)
            for v in block_p.sort_values("predicted_points", ascending=False).head(
                int(arguments.pool_per_position)
            )["player_id"]
        )
        keep.update(
            int(v)
            for v in block_p.sort_values("price_tenths", ascending=True).head(
                int(arguments.cheap_per_position)
            )["player_id"]
        )
    pool = pool.loc[pool["player_id"].isin(keep)].reset_index(drop=True)
    LOGGER.info("Pool restricted to %d players", len(pool))

    gameweeks = tuple(range(origin, origin + horizon))
    week_frames = []
    for gameweek in gameweeks:
        frame = pool.loc[
            :, ["player_id", "name", "team_id", "position", "predicted_points", "price_tenths"]
        ].copy()
        frame["gameweek"] = gameweek
        frame["expected_points"] = frame.pop("predicted_points").clip(lower=0.0)
        frame["buy_price_tenths"] = frame["price_tenths"].astype("int64")
        frame["sell_price_tenths"] = frame["price_tenths"].astype("int64")
        week_frames.append(frame.drop(columns=["price_tenths"]))
    import pandas as pd

    horizon_table = PlanningHorizon(pd.concat(week_frames, ignore_index=True))
    initial_state = InitialSquadState(
        squad_player_ids=tuple(sorted(held_ids)),
        bank_tenths=max(0, 1000 - held_cost),
        free_transfers=1,
    )

    LOGGER.info("Generating the candidate menu")
    candidates = generate_candidate_plans(
        horizon_table,
        initial_state,
        optimization,
        gameweeks=gameweeks,
    )
    LOGGER.info("Menu of %d candidates: %s", len(candidates), [c.label for c in candidates])

    snapshot = prepare_optimizer_projection(
        pool.loc[:, ["player_id", "name", "team_id", "position", "price_tenths"]],
        pool.assign(expected_points=pool["predicted_points"].clip(lower=0.0)).loc[
            :, ["player_id", "expected_points"]
        ],
        PredictionProvenance(
            model_name="deterministic_baseline",
            model_version="form_window_05_v1",
            feature_contract_version="form_window_v1",
            training_cutoff="pre_origin",
            training_data_fingerprint="e" * 64,
        ),
    )
    paths = generate_scenario_paths(
        dict.fromkeys(gameweeks, snapshot),
        history,
        ScenarioPathTarget(season, origin, horizon),
        ScenarioConfig(
            scenario_count=int(arguments.scenario_count),
            deterministic_seed=int(arguments.seed),
        ),
    )
    selection = select_plan(candidates, paths, rival)
    elapsed = perf_counter() - started

    document = {
        **artifact_metadata(panel_rows=len(panel), created_utc=created_utc),
        "contract_version": PLAN_SELECTION_CONTRACT_VERSION,
        "season": season,
        "origin": origin,
        "horizon": horizon,
        "scenario_count": int(arguments.scenario_count),
        "pool_players": len(pool),
        "wall_clock_seconds": elapsed,
        "selection": selection_to_dict(selection),
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
    selection = document["selection"]
    assert isinstance(selection, dict)
    recommended = selection["recommended"]
    assert isinstance(recommended, dict)
    lines = [
        "# One window, four modes, one menu of plans",
        "",
        f"- Contract `{document['contract_version']}`; {document['season']} gameweek "
        f"{document['origin']}, horizon {document['horizon']}, "
        f"{document['scenario_count']} joint paths, pool {document['pool_players']} players.",
        f"- Wall clock for the whole flow: **{float(str(document['wall_clock_seconds'])):.0f} "
        "seconds** (menu generation, path generation, scoring, selection).",
        f"- {document['projection_note']}",
        "- The rival is the ownership template at the origin, held fixed across the window.",
        "- Descriptive measurement: no gate, nothing promoted, locked holdout untouched.",
        "",
        "## What each mode picked",
        "",
        "| Mode | Recommended plan |",
        "| --- | --- |",
    ]
    for mode, plan in recommended.items():
        lines.append(f"| {mode} | `{plan}` |")
    lines += [
        "",
        "## The full menu under every mode",
        "",
        "| Mode | Candidate | Expected window score | P(success) | P(behind) | Chips |",
        "| --- | --- | ---: | ---: | ---: | --- |",
    ]
    verdicts = selection["verdicts"]
    assert isinstance(verdicts, list)
    for verdict in verdicts:
        success = verdict["probability_success"]
        behind = verdict["probability_behind"]
        lines.append(
            f"| {verdict['mode']} | `{verdict['candidate']}` "
            f"| {verdict['expected_window_score']:.1f} "
            f"| {'—' if success is None else f'{success:.2f}'} "
            f"| {'—' if behind is None else f'{behind:.2f}'} "
            f"| {', '.join(verdict['chips_consumed']) or '—'} |"
        )
    modes_disagree = len(set(recommended.values())) > 1
    lines += [
        "",
        (
            "**The modes disagree**, which is the mode selector earning its place: the "
            "plan a manager should play depends on what they are playing for."
            if modes_disagree
            else "**Every mode picked the same plan** this week — the selector added "
            "nothing here, and honesty requires saying so."
        ),
        "",
    ]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    sys.exit(main())
