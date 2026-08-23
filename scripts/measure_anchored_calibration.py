"""Is the anchored differential a calibrated claim? The gate its prereg fixed, applied.

    python -m scripts.measure_anchored_calibration

`anchored_differential_prereg.md` declares the mechanism and this gate; the code below
applies it as written:

1. **Degenerate identity** — for the risk-neutral candidate the claim must equal the
   share of negative resampled window edges within 0.02 (it is the same draw vector, so
   the recorded maximum deviation should be zero).
2. **Calibration** — pooled per horizon *and per candidate family*:
   |claimed - realized| <= 0.10 with the 90% bootstrap interval on the gap containing
   zero.
3. **Ordering sanity** — the shadow family's mean distance from its degenerate value
   must be smaller than the contrarian family's at every horizon.

Candidate families per fold, each one deterministic CP-SAT solve: the risk-neutral
squad; a contrarian squad (highest projection, the crowd's eleven excluded from the
pool); a shadow squad (highest projection with the crowd's top-eight forced in via
``required_player_ids``; an infeasible requirement skips the cell and is counted).
Population, edge series and leave-one-season-out pools are identical to
`rival_calibration`. Measurement only; the locked 2025-26 holdout is refused.
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
from squadopt.optimization import OptimizationConfig, OptimizationResult, optimize_squad
from squadopt.prediction import PredictionProvenance, prepare_optimizer_projection
from squadopt.scenarios import ScenarioConfig
from squadopt.scenarios.evaluation import anchored_probability_ahead, rival_edge_draws
from squadopt.scenarios.paths import ScenarioPathTarget, generate_scenario_paths
from squadopt.scenarios.rivals import template_rival_from_ownership

LOGGER = logging.getLogger(__name__)

DEVELOPMENT_SEASONS = ("2021-22", "2022-23", "2023-24", "2024-25")
FAMILIES = ("risk_neutral", "contrarian", "shadow")
GAP_TOLERANCE = 0.10
IDENTITY_TOLERANCE = 0.02
BOOTSTRAP_DRAWS = 2_000
MINIMUM_HISTORY_FOLDS = 8


def _edge_series(root: Path) -> dict[str, list[float]]:
    series: dict[str, list[float]] = {}
    for season in DEVELOPMENT_SEASONS:
        suffix = "" if season == "2024-25" else f"_{season}"
        document = json.loads(
            (root / f"template_rival_strength{suffix}.json").read_text(encoding="utf-8")
        )
        series[season] = [float(row["difference"]) for row in document["rows"]]
    return series


def _leave_one_out(series: dict[str, list[float]], season: str) -> tuple[float, ...]:
    return tuple(v for other, values in series.items() if other != season for v in values)


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
        default=REPOSITORY_ROOT / "docs" / "anchored_calibration.json",
    )
    parser.add_argument(
        "--markdown-output",
        type=Path,
        default=REPOSITORY_ROOT / "docs" / "anchored_calibration.md",
    )
    return parser.parse_args()


def main() -> int:
    arguments = _parse_arguments()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    created_utc = datetime.now(UTC).isoformat(timespec="seconds")
    horizons = [int(v) for v in str(arguments.horizons).split(",")]

    series = _edge_series(REPOSITORY_ROOT / "docs")
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
    shadow_infeasible = 0
    for season in DEVELOPMENT_SEASONS:
        pool_samples = _leave_one_out(series, season)
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
            if history["fold_id"].nunique() < MINIMUM_HISTORY_FOLDS:
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
            rival_ids = {int(str(p)) for p in rival.starter_ids}
            keep: set[int] = set(rival_ids)
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
            anchor = optimize_squad(snapshot.table, optimization)
            if not anchor.has_solution or anchor.captain is None:
                continue
            candidates: dict[str, OptimizationResult] = {"risk_neutral": anchor}
            without_rival = snapshot.table.loc[
                ~snapshot.table["player_id"].astype(int).isin(rival_ids)
            ].reset_index(drop=True)
            contrarian = optimize_squad(without_rival, optimization)
            if contrarian.has_solution and contrarian.captain is not None:
                candidates["contrarian"] = contrarian
            top_eight = tuple(
                int(v)
                for v in pool.loc[pool["player_id"].isin(rival_ids)]
                .sort_values("predicted_points", ascending=False)
                .head(8)["player_id"]
            )
            shadow = optimize_squad(snapshot.table, optimization, required_player_ids=top_eight)
            if shadow.has_solution and shadow.captain is not None:
                candidates["shadow"] = shadow
            else:
                shadow_infeasible += 1
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
                drawn = rival_edge_draws(
                    pool_samples,
                    scenarios=int(arguments.scenario_count),
                    weeks=horizon,
                    seed=cell_seed,
                )
                negative_share = float(np.mean(drawn < 0.0))
                realized = (
                    season_panel.loc[
                        (season_panel["gameweek"] >= origin)
                        & (season_panel["gameweek"] < origin + horizon)
                    ]
                    .groupby("player_id")["total_points"]
                    .sum()
                )
                rival_realized = float(
                    sum(float(realized.get(int(str(p)), 0.0)) for p in rival.starter_ids)
                ) + float(realized.get(int(str(rival.captain_id)), 0.0))
                for family, candidate in candidates.items():
                    claim = anchored_probability_ahead(
                        candidate,
                        anchor,
                        window,
                        edge_samples=pool_samples,
                        edge_weeks=horizon,
                        edge_seed=cell_seed,
                    )
                    assert candidate.captain is not None
                    starters = [int(v) for v in candidate.starting_xi["player_id"]]
                    captain = int(candidate.captain["player_id"])
                    my_realized = float(sum(float(realized.get(p, 0.0)) for p in starters)) + float(
                        realized.get(captain, 0.0)
                    )
                    rows.append(
                        {
                            "season": season,
                            "origin": origin,
                            "horizon": horizon,
                            "family": family,
                            "claimed": float(claim.probability_ahead),
                            "negative_edge_share": negative_share,
                            "identity_gap": abs(float(claim.probability_ahead) - negative_share)
                            if family == "risk_neutral"
                            else None,
                            "scenario_differential_mean": claim.scenario_differential_mean,
                            "realized_ahead": bool(my_realized > rival_realized),
                            "my_realized": my_realized,
                            "rival_realized": rival_realized,
                        }
                    )
        LOGGER.info("%s: %d rows so far", season, len(rows))

    if not rows:
        print("No cell could be measured.")
        return 1

    identity_gaps = [float(str(r["identity_gap"])) for r in rows if r["identity_gap"] is not None]
    identity_max = max(identity_gaps)
    passes_identity = identity_max <= IDENTITY_TOLERANCE

    by_cell: dict[str, dict[str, object]] = {}
    passes_calibration = True
    ordering_ok = True
    for horizon in horizons:
        distances: dict[str, float] = {}
        for family in FAMILIES:
            cells = [r for r in rows if r["horizon"] == horizon and r["family"] == family]
            if not cells:
                continue
            claimed = np.asarray([c["claimed"] for c in cells], dtype="float64")
            realized_flags = np.asarray(
                [1.0 if c["realized_ahead"] else 0.0 for c in cells], dtype="float64"
            )
            gap = float(claimed.mean() - realized_flags.mean())
            low, high = _bootstrap_gap_interval(
                claimed, realized_flags, int(arguments.seed) + horizon
            )
            clause = abs(gap) <= GAP_TOLERANCE and low <= 0.0 <= high
            passes_calibration = passes_calibration and clause
            distances[family] = float(
                np.mean(
                    np.abs(
                        claimed
                        - np.asarray([c["negative_edge_share"] for c in cells], dtype="float64")
                    )
                )
            )
            by_cell[f"h{horizon}:{family}"] = {
                "cells": len(cells),
                "mean_claimed": float(claimed.mean()),
                "realized_ahead_share": float(realized_flags.mean()),
                "gap": gap,
                "gap_interval_90": [low, high],
                "clause_passes": bool(clause),
                "mean_distance_from_degenerate": distances[family],
            }
        if "shadow" in distances and "contrarian" in distances:
            ordering_ok = ordering_ok and distances["shadow"] < distances["contrarian"]

    verdict = {
        "passes_identity": bool(passes_identity),
        "identity_max_gap": identity_max,
        "passes_calibration": bool(passes_calibration),
        "passes_ordering": bool(ordering_ok),
        "shadow_infeasible_folds": shadow_infeasible,
        "passes": bool(passes_identity and passes_calibration and ordering_ok),
        "note": (
            "Clauses 1-3 of anchored_differential_prereg.md as declared; a pass here "
            "still requires the mode-ordering re-run before anything ships."
        ),
    }

    document = {
        **artifact_metadata(panel_rows=len(panel), created_utc=created_utc),
        "contract_version": "anchored_calibration_v1",
        "config": {
            "horizons": horizons,
            "scenario_count": int(arguments.scenario_count),
            "seed": int(arguments.seed),
            "gap_tolerance": GAP_TOLERANCE,
            "identity_tolerance": IDENTITY_TOLERANCE,
        },
        "rows": rows,
        "by_cell": by_cell,
        "verdict": verdict,
        "measurement_only": True,
        "locked_holdout_accessed": False,
    }

    lines = [
        "# Anchored calibration: the decomposed claim against what happened",
        "",
        f"- Rows: {len(rows)}; identity max gap {identity_max:.4f} "
        f"({'passes' if passes_identity else 'fails'} at {IDENTITY_TOLERANCE}).",
        f"- Shadow-infeasible folds: {shadow_infeasible}.",
        "",
        "| cell | n | claimed | realized | gap | 90% CI | dist. from degenerate | clause |",
        "| --- | ---: | ---: | ---: | ---: | --- | ---: | --- |",
    ]
    for key, values in by_cell.items():
        low, high = values["gap_interval_90"]  # type: ignore[misc]
        lines.append(
            f"| {key} | {values['cells']} | {values['mean_claimed']:.3f} "
            f"| {values['realized_ahead_share']:.3f} | {values['gap']:+.3f} "
            f"| [{low:+.3f}, {high:+.3f}] | {values['mean_distance_from_degenerate']:.3f} "
            f"| {'passes' if values['clause_passes'] else 'fails'} |"
        )
    lines += [
        "",
        f"**Verdict: {'passes' if verdict['passes'] else 'fails'}** "
        f"(identity {'ok' if passes_identity else 'FAILED'}, "
        f"calibration {'ok' if passes_calibration else 'FAILED'}, "
        f"ordering {'ok' if ordering_ok else 'FAILED'}).",
        "",
        "- Measurement only; the locked 2025-26 holdout is refused by the development season list.",
    ]

    write_json(arguments.json_output, document)
    write_text(arguments.markdown_output, "\n".join(lines) + "\n")
    print("\n".join(lines))
    print(f"Wrote {arguments.json_output}")
    print(f"Wrote {arguments.markdown_output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
