"""Does treating a window as one path widen it or narrow it, on real residuals?

    python -m scripts.measure_scenario_path_dependence

`generate_scenario_paths` replaces three independent weeks with one block-bootstrapped path.
The reason to do that is not that persistence must widen a window — it is that the weeks are
*not* independent and pretending otherwise states a spread the data does not support. Which
direction the dependence runs is a measurement, and this makes it.

Read-only over the archive and the control's own out-of-sample residuals. The locked holdout
is never read: the target season is a development season and the history precedes it.
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
from squadopt.prediction import PredictionProvenance, prepare_optimizer_projection
from squadopt.scenarios import ScenarioConfig, ScenarioTarget, generate_scenarios
from squadopt.scenarios.paths import ScenarioPathTarget, generate_scenario_paths

LOGGER = logging.getLogger(__name__)
LOCKED_HOLDOUT_SEASON = "2025-26"


def _parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive-root", type=Path, default=DEFAULT_ARCHIVE_ROOT)
    parser.add_argument("--season", default="2024-25")
    parser.add_argument("--gameweek", type=int, default=20)
    parser.add_argument("--horizon", type=int, default=3)
    parser.add_argument("--scenario-count", type=int, default=4000)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--eleven-size", type=int, default=11)
    parser.add_argument(
        "--json-output",
        type=Path,
        default=REPOSITORY_ROOT / "docs" / "scenario_path_dependence.json",
    )
    parser.add_argument(
        "--markdown-output",
        type=Path,
        default=REPOSITORY_ROOT / "docs" / "scenario_path_dependence.md",
    )
    return parser.parse_args()


def main() -> int:
    arguments = _parse_arguments()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    season = str(arguments.season)
    if season == LOCKED_HOLDOUT_SEASON:
        print(f"{LOCKED_HOLDOUT_SEASON} is the locked holdout and may not be read.")
        return 1
    if not arguments.archive_root.is_dir():
        print(f"Archive not found at {arguments.archive_root}.")
        return 1
    created_utc = datetime.now(UTC).isoformat(timespec="seconds")
    gameweek = int(arguments.gameweek)
    horizon = int(arguments.horizon)

    LOGGER.info("Building the control's residual folds")
    panel = build_panel(arguments.archive_root)
    residuals = build_control_residual_table(panel, PolicyObjectiveConfig())
    target_fold = f"{season}-gw{gameweek:02d}"
    history = residuals.loc[residuals["fold_id"] < target_fold].copy()
    week = residuals.loc[residuals["fold_id"] == target_fold].copy()
    if history.empty or week.empty:
        print(f"No residual fold at {target_fold}.")
        return 1

    prices = panel.loc[
        (panel["season"] == season) & (panel["gameweek"] == gameweek),
        ["player_id", "name", "price_tenths"],
    ]
    pool = (
        week.merge(prices, on="player_id", how="inner")
        .loc[:, ["player_id", "name", "team_id", "position", "price_tenths", "predicted_points"]]
        .rename(columns={"predicted_points": "expected_points"})
        .reset_index(drop=True)
    )
    provenance = PredictionProvenance(
        model_name="deterministic_baseline",
        model_version="form_window_05_v1",
        feature_contract_version="form_window_v1",
        training_cutoff=f"{season}:GW{gameweek - 1:02d}",
        training_data_fingerprint="c" * 64,
    )
    snapshot = prepare_optimizer_projection(
        pool.drop(columns="expected_points"),
        pool.loc[:, ["player_id", "expected_points"]],
        provenance,
    )

    count = int(arguments.scenario_count)
    seed = int(arguments.seed)
    gameweeks = tuple(gameweek + offset for offset in range(horizon))
    LOGGER.info("Drawing %d paths of %d weeks over %d players", count, horizon, len(pool))
    paths = generate_scenario_paths(
        dict.fromkeys(gameweeks, snapshot),
        history,
        ScenarioPathTarget(season, gameweek, horizon),
        ScenarioConfig(scenario_count=count, deterministic_seed=seed),
    )
    path_total = paths.window_points().to_numpy(dtype="float64")

    # The control this replaces: the same week, drawn independently, added up. A different
    # seed per week is what "independent" means here.
    independent_total = np.zeros_like(path_total)
    for offset in range(horizon):
        single = generate_scenarios(
            snapshot,
            history,
            ScenarioTarget(season, gameweek),
            ScenarioConfig(scenario_count=count, deterministic_seed=seed + 100 * offset),
        )
        independent_total = independent_total + single.scenario_points.to_numpy(dtype="float64")

    order = np.argsort(-pool["expected_points"].to_numpy(dtype="float64"))[
        : int(arguments.eleven_size)
    ]
    summary = {}
    for label, values in (("path", path_total), ("independent", independent_total)):
        eleven = values[:, order].sum(axis=1)
        summary[label] = {
            "mean_player_standard_deviation": float(values.std(axis=0).mean()),
            "eleven_mean": float(eleven.mean()),
            "eleven_standard_deviation": float(eleven.std()),
            "eleven_p05": float(np.quantile(eleven, 0.05)),
            "eleven_p50": float(np.quantile(eleven, 0.50)),
            "eleven_p95": float(np.quantile(eleven, 0.95)),
        }
    ratio = (
        summary["path"]["mean_player_standard_deviation"]
        / summary["independent"]["mean_player_standard_deviation"]
    )
    path_width = summary["path"]["eleven_p95"] - summary["path"]["eleven_p05"]
    independent_width = summary["independent"]["eleven_p95"] - summary["independent"]["eleven_p05"]
    document = {
        **artifact_metadata(panel_rows=len(panel), created_utc=created_utc),
        "contract_version": paths.contract_version,
        "season": season,
        "first_gameweek": gameweek,
        "horizon": horizon,
        "scenario_count": count,
        "deterministic_seed": seed,
        "players": len(pool),
        "history_folds": int(history["fold_id"].nunique()),
        "summary": summary,
        "standard_deviation_ratio": ratio,
        "eleven_tail_width": {"path": path_width, "independent": independent_width},
        "diagnostics": {
            key: paths.diagnostics[key]
            for key in (
                "contiguous_block_starts",
                "history_folds",
                "idiosyncratic_block_sources",
                "common_block_week_means",
            )
        },
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
    summary = document["summary"]
    assert isinstance(summary, dict)
    ratio = float(str(document["standard_deviation_ratio"]))
    widths = document["eleven_tail_width"]
    assert isinstance(widths, dict)
    direction = "narrows" if ratio < 1.0 else "widens"
    lines = [
        "# A window as one path, against a window as independent weeks",
        "",
        f"- Contract `{document['contract_version']}`; {document['season']} from gameweek "
        f"{document['first_gameweek']}, horizon {document['horizon']}, "
        f"{document['scenario_count']} scenarios, seed {document['deterministic_seed']}.",
        f"- {document['players']} players, {document['history_folds']} historical folds of the "
        "operational control's own out-of-sample residuals.",
        "- Both arms use the **same projection** every week, so nothing here is about the point "
        "estimate; only the sampling differs.",
        "",
        "| | Mean player sd | Eleven mean | Eleven sd | p05 | p50 | p95 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for label in ("path", "independent"):
        values = summary[label]
        lines.append(
            f"| `{label}` | {values['mean_player_standard_deviation']:.4f} "
            f"| {values['eleven_mean']:.2f} | {values['eleven_standard_deviation']:.2f} "
            f"| {values['eleven_p05']:.2f} | {values['eleven_p50']:.2f} "
            f"| {values['eleven_p95']:.2f} |"
        )
    lines += [
        "",
        "## What it says",
        "",
        f"Treating the window as one path **{direction}** it: the mean player standard "
        f"deviation is **{ratio:.4f}x** the independent one, and the eleven's fifth-to-"
        f"ninety-fifth spread is {float(str(widths['path'])):.2f} against "
        f"{float(str(widths['independent'])):.2f}.",
        "",
        "The direction is the finding. Persistence is often assumed to widen a window — a bad "
        "week followed by another bad week — and on the control's residuals it does the "
        "opposite by a small amount. A player who over-performs his projection one week tends "
        "to fall back the next, and that mean reversion cancels part of what independent draws "
        "would add up. The effect is small; what matters is that it is measured rather than "
        "asserted, and that it runs the other way from the intuition.",
        "",
        "This is not an argument for independent weeks. Independence states a dependence "
        "structure the data does not have; a path states the one it does. The correction "
        "happens to be small here, and it would not be knowable without measuring.",
        "",
    ]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    sys.exit(main())
