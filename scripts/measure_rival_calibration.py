"""Does the resampled rival edge make windowed P(ahead) a calibrated number?

    python -m scripts.measure_rival_calibration

The measurement `rival_scenario_prereg.md` (as amended 2026-08-23, before this script
existed) declares, with its gate applied by the code below:

- every fold of the four development seasons, horizons 1/3/5 (clipped at season end);
- the fold's risk-neutral squad, held fixed — the cheap `compare_fixed_decisions` path,
  so the population is ~140 windows per horizon rather than the five the three-phase
  solver could afford;
- season S's rival-edge draws resample only the *other* seasons' measured weekly edge
  series (leave-one-season-out; `template_rival_strength*.json`), one draw per week of
  the window;
- the constant-edge baseline (the same leave-one-season-out mean, times the horizon) is
  scored on the same cells, because gate clause 4 compares against it.

Gate, verbatim from the prereg: pooled `|claimed - realized| <= 0.10` per horizon with a
90% bootstrap interval on the gap containing zero; and h=1 must not worsen by more than
0.02 against the constant-edge baseline. Clause 5 (mode-ordering stability) is a
separate run and is recorded as not-covered-here. Measurement only; the locked 2025-26
holdout is refused; nothing consumes this result until the gate says so.
"""

import argparse
import json
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
from squadopt.optimization import OptimizationConfig, optimize_squad
from squadopt.prediction import PredictionProvenance, prepare_optimizer_projection
from squadopt.scenarios import ScenarioConfig
from squadopt.scenarios.evaluation import compare_fixed_decisions
from squadopt.scenarios.paths import ScenarioPathTarget, generate_scenario_paths
from squadopt.scenarios.rivals import template_rival_from_ownership

LOGGER = logging.getLogger(__name__)

DEVELOPMENT_SEASONS = ("2021-22", "2022-23", "2023-24", "2024-25")
GAP_TOLERANCE = 0.10
H1_REGRESSION_TOLERANCE = 0.02
BOOTSTRAP_DRAWS = 2_000


def _edge_series(root: Path) -> dict[str, list[float]]:
    series: dict[str, list[float]] = {}
    for season in DEVELOPMENT_SEASONS:
        suffix = "" if season == "2024-25" else f"_{season}"
        path = root / f"template_rival_strength{suffix}.json"
        document = json.loads(path.read_text(encoding="utf-8"))
        series[season] = [float(row["difference"]) for row in document["rows"]]
    return series


def _leave_one_out(series: dict[str, list[float]], season: str) -> tuple[float, ...]:
    pooled = [v for other, values in series.items() if other != season for v in values]
    return tuple(pooled)


def _bootstrap_gap_interval(
    claimed: np.ndarray, realized: np.ndarray, seed: int
) -> tuple[float, float]:
    generator = np.random.default_rng(seed)
    gaps = []
    n = len(claimed)
    for _ in range(BOOTSTRAP_DRAWS):
        pick = generator.integers(0, n, size=n)
        gaps.append(float(claimed[pick].mean() - realized[pick].mean()))
    return float(np.quantile(gaps, 0.05)), float(np.quantile(gaps, 0.95))


def _parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive-root", type=Path, default=DEFAULT_ARCHIVE_ROOT)
    parser.add_argument("--horizons", default="1,3,5")
    parser.add_argument("--scenario-count", type=int, default=200)
    parser.add_argument("--seed", type=int, default=11)
    parser.add_argument("--pool-per-position", type=int, default=20)
    parser.add_argument("--cheap-per-position", type=int, default=8)
    parser.add_argument(
        "--json-output",
        type=Path,
        default=REPOSITORY_ROOT / "docs" / "rival_calibration.json",
    )
    parser.add_argument(
        "--markdown-output",
        type=Path,
        default=REPOSITORY_ROOT / "docs" / "rival_calibration.md",
    )
    return parser.parse_args()


def main() -> int:
    arguments = _parse_arguments()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    created_utc = datetime.now(UTC).isoformat(timespec="seconds")
    horizons = [int(v) for v in str(arguments.horizons).split(",")]

    series = _edge_series(REPOSITORY_ROOT / "docs")
    LOGGER.info("Edge series loaded: %s", {s: len(v) for s, v in series.items()})

    LOGGER.info("Building the control's residual folds")
    panel = build_panel(arguments.archive_root)
    residuals = build_control_residual_table(panel, PolicyObjectiveConfig())
    optimization = OptimizationConfig()
    provenance_seed = PredictionProvenance(
        model_name="deterministic_baseline",
        model_version="form_window_05_v1",
        feature_contract_version="form_window_v1",
        training_cutoff="pre_origin",
        training_data_fingerprint="d" * 64,
    )

    rows: list[dict[str, object]] = []
    for season in DEVELOPMENT_SEASONS:
        pool_samples = _leave_one_out(series, season)
        constant_edge = float(np.mean(pool_samples))
        ownership = load_enrichment_rows(arguments.archive_root, (season,))
        prices = panel.loc[
            panel["season"] == season, ["gameweek", "player_id", "price_tenths", "name"]
        ]
        season_panel = panel.loc[panel["season"] == season]
        last_gameweek = int(season_panel["gameweek"].max())
        fold_ids = sorted(
            set(residuals.loc[residuals["fold_id"].str.startswith(season), "fold_id"].tolist())
        )
        for fold_id in fold_ids:
            origin = int(fold_id.rsplit("gw", 1)[1])
            block = residuals.loc[residuals["fold_id"] == fold_id]
            history = residuals.loc[residuals["fold_id"] < fold_id]
            if block.empty or history.empty:
                continue
            if history["fold_id"].nunique() < 8:
                # The generator needs eight historical folds; the season's opening weeks
                # cannot be scored and are skipped rather than crashing the run.
                continue
            pool = block.merge(
                prices.loc[prices["gameweek"] == origin, ["player_id", "price_tenths", "name"]],
                on="player_id",
                how="inner",
            )
            own = ownership.loc[ownership["gameweek"] == origin, ["player_id", "selected"]]
            pool = pool.merge(own, on="player_id", how="left")
            pool["ownership"] = pool["selected"].fillna(0.0)
            if pool.empty:
                continue
            rival = template_rival_from_ownership(
                pool.loc[:, ["player_id", "position", "ownership"]]
            )
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
            decision = optimize_squad(snapshot.table, optimization)
            if not decision.has_solution or decision.captain is None:
                LOGGER.info("%s: infeasible fold, skipped", fold_id)
                continue
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
                cell_seed = int(arguments.seed) * 1_000_000 + origin * 100 + horizon
                sampled = compare_fixed_decisions(
                    decision,
                    rival,
                    window,
                    rival_edge_samples=pool_samples,
                    rival_edge_weeks=horizon,
                    rival_edge_seed=cell_seed,
                )
                constant = compare_fixed_decisions(
                    decision,
                    rival,
                    window,
                    rival_edge_points=constant_edge * horizon,
                )
                realized = (
                    season_panel.loc[
                        (season_panel["gameweek"] >= origin)
                        & (season_panel["gameweek"] < origin + horizon)
                    ]
                    .groupby("player_id")["total_points"]
                    .sum()
                )
                starters = [int(v) for v in decision.starting_xi["player_id"]]
                captain = int(decision.captain["player_id"])
                my_realized = float(sum(float(realized.get(p, 0.0)) for p in starters)) + float(
                    realized.get(captain, 0.0)
                )
                rival_realized = float(
                    sum(float(realized.get(int(str(p)), 0.0)) for p in rival.starter_ids)
                ) + float(realized.get(int(str(rival.captain_id)), 0.0))
                rows.append(
                    {
                        "season": season,
                        "origin": origin,
                        "horizon": horizon,
                        "claimed_sampled": float(sampled.probability_ahead),
                        "claimed_constant": float(constant.probability_ahead),
                        "realized_ahead": bool(my_realized > rival_realized),
                        "my_realized": my_realized,
                        "rival_realized": rival_realized,
                        "edge_seed": cell_seed,
                    }
                )
        LOGGER.info("%s: %d cells so far", season, len(rows))

    if not rows:
        print("No cell could be measured.")
        return 1

    by_horizon: dict[str, dict[str, object]] = {}
    passes_calibration = True
    h1_sampled_gap: float | None = None
    h1_constant_gap: float | None = None
    for horizon in horizons:
        cells = [row for row in rows if row["horizon"] == horizon]
        if not cells:
            continue
        claimed = np.asarray([c["claimed_sampled"] for c in cells], dtype="float64")
        claimed_const = np.asarray([c["claimed_constant"] for c in cells], dtype="float64")
        realized_flags = np.asarray(
            [1.0 if c["realized_ahead"] else 0.0 for c in cells], dtype="float64"
        )
        gap = float(claimed.mean() - realized_flags.mean())
        gap_const = float(claimed_const.mean() - realized_flags.mean())
        low, high = _bootstrap_gap_interval(claimed, realized_flags, int(arguments.seed) + horizon)
        clause = abs(gap) <= GAP_TOLERANCE and low <= 0.0 <= high
        passes_calibration = passes_calibration and clause
        if horizon == 1:
            h1_sampled_gap, h1_constant_gap = abs(gap), abs(gap_const)
        by_horizon[str(horizon)] = {
            "cells": len(cells),
            "mean_claimed_sampled": float(claimed.mean()),
            "mean_claimed_constant": float(claimed_const.mean()),
            "realized_ahead_share": float(realized_flags.mean()),
            "gap_sampled": gap,
            "gap_constant": gap_const,
            "gap_interval_90": [low, high],
            "clause_passes": bool(clause),
        }
    h1_not_sacrificed = (
        h1_sampled_gap is not None
        and h1_constant_gap is not None
        and h1_sampled_gap <= h1_constant_gap + H1_REGRESSION_TOLERANCE
    )
    verdict = {
        "passes_calibration": bool(passes_calibration),
        "passes_h1_not_sacrificed": bool(h1_not_sacrificed),
        "mode_ordering_clause": "not_covered_here (separate plan-selection run)",
        "passes": bool(passes_calibration and h1_not_sacrificed),
        "note": (
            "Clauses 3 and 4 of rival_scenario_prereg.md, applied as declared; clause 5 "
            "runs separately. A pass here alone does not ship a probability."
        ),
    }

    document = {
        **artifact_metadata(panel_rows=len(panel), created_utc=created_utc),
        "contract_version": "rival_calibration_v1",
        "config": {
            "horizons": horizons,
            "scenario_count": int(arguments.scenario_count),
            "seed": int(arguments.seed),
            "pool_per_position": int(arguments.pool_per_position),
            "cheap_per_position": int(arguments.cheap_per_position),
            "gap_tolerance": GAP_TOLERANCE,
            "h1_regression_tolerance": H1_REGRESSION_TOLERANCE,
            "edge_series_sizes": {s: len(v) for s, v in series.items()},
        },
        "rows": rows,
        "by_horizon": by_horizon,
        "verdict": verdict,
        "measurement_only": True,
        "locked_holdout_accessed": False,
    }

    lines = [
        "# Rival calibration: the resampled edge against what happened",
        "",
        f"- Cells: {len(rows)} over {len(DEVELOPMENT_SEASONS)} seasons; "
        f"{int(arguments.scenario_count)} scenarios per window.",
        "- Season S resamples only the other seasons' measured weekly edges "
        "(leave-one-season-out); the constant baseline is the same pool's mean.",
        "",
        "| h | cells | claimed (sampled) | claimed (constant) | realized | gap | 90% CI | clause |",
        "| ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |",
    ]
    for horizon_key, values in by_horizon.items():
        low, high = values["gap_interval_90"]  # type: ignore[misc]
        lines.append(
            f"| {horizon_key} | {values['cells']} | {values['mean_claimed_sampled']:.3f} "
            f"| {values['mean_claimed_constant']:.3f} | {values['realized_ahead_share']:.3f} "
            f"| {values['gap_sampled']:+.3f} | [{low:+.3f}, {high:+.3f}] "
            f"| {'passes' if values['clause_passes'] else 'fails'} |"
        )
    lines += [
        "",
        f"**Verdict: {'passes' if verdict['passes'] else 'fails'}** "
        "(clauses 3-4 as declared; clause 5 — mode-ordering stability — runs separately).",
        "",
        "- Measurement only. The locked 2025-26 holdout is refused by the development "
        "season list; nothing consumes this result until the full gate says so.",
    ]

    write_json(arguments.json_output, document)
    write_text(arguments.markdown_output, "\n".join(lines) + "\n")
    print("\n".join(lines))
    print(f"Wrote {arguments.json_output}")
    print(f"Wrote {arguments.markdown_output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
