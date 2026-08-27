"""The strategy bench: do the constraint's names survive contact with the archive?

    python -m scripts.measure_strategy_bench

Pre-registered in ``docs/strategy_bench_prereg.md`` (#279) **before the catalogue
existed**; this run applies those gates and adds nothing to them. Three bands per
fold — high-overlap (floor 9), differential (ceiling 5), control (unconstrained
saf-puan) — solved by the same deterministic planner on the same restricted pool,
then scored against the archive's actual per-player points over the window, candidate
and rival identically.

Instrument notes pinned before the numbers were read:

- Realized window points are **gross of transfer hits**, matching the claimed side:
  the prereg defines the claimed cost as "the solver's own expected-points differences
  at decision time", and ``expected_points_cost`` is a difference of
  ``total_projected_score`` values, which do not net hits. Hit points are recorded
  per plan as diagnostics.
- "Windows clipped at season end" is implemented as truncation: the effective horizon
  is ``min(h, last_gameweek - origin + 1)``; a fold whose window clips is kept and
  says so in its row.
- A band that cannot be proven in a fold is recorded infeasible there and drops out
  of that band's paired comparisons — the menu shortens, nothing is imputed.
- The interval is the season-aware moving-block bootstrap at 90% with
  ``PromotionPolicy`` defaults; with ~37 folds per season the default block of four
  resamples properly (the screening's degeneracy was a four-folds-per-season
  artifact and does not arise here).
"""

import argparse
import logging
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from statistics import fmean
from time import perf_counter

import pandas as pd
from scripts._experiment_cli import (
    DEFAULT_ARCHIVE_ROOT,
    REPOSITORY_ROOT,
    artifact_metadata,
    write_json,
    write_text,
)

from squadopt.application.strategies import STRATEGY_CATALOG, solve_strategy_plan
from squadopt.data.sources.vaastav import build_panel
from squadopt.experiments.config import PromotionPolicy
from squadopt.experiments.control_residuals import build_control_residual_table
from squadopt.experiments.policy_objective import PolicyObjectiveConfig
from squadopt.experiments.residual_signal_scan import load_enrichment_rows
from squadopt.experiments.statistics import season_aware_moving_block_interval
from squadopt.optimization import OptimizationConfig, SolverStatus, optimize_squad
from squadopt.planning import (
    InitialSquadState,
    PlanningHorizon,
    PlanningWeekResult,
    TransferPlanResult,
    optimize_transfer_plan,
)
from squadopt.scenarios.rivals import template_rival_from_ownership

LOGGER = logging.getLogger(__name__)

STRATEGY_BENCH_CONTRACT_VERSION = "strategy_bench_v1"
DEVELOPMENT_SEASONS = ("2021-22", "2022-23", "2023-24", "2024-25")
HORIZONS = (1, 3, 5)
GATED_HORIZONS = (1, 3)
WINS_BIG_MARGIN = 5.0
BANDS = ("high_overlap", "differential", "control")


@dataclass(frozen=True, slots=True)
class Fold:
    season: str
    fold_id: str
    origin: int
    horizon_table: pd.DataFrame
    initial_state: InitialSquadState
    rival_ids: frozenset[int]
    rival_captain: int


@dataclass(frozen=True, slots=True)
class BandOutcome:
    """One band's plan in one fold at one horizon, scored on the archive."""

    realized_points: float
    rival_realized_points: float
    claimed_cost: float | None
    hit_points: float
    overlap_count: int | None

    @property
    def behind(self) -> bool:
        return self.realized_points < self.rival_realized_points

    @property
    def wins_big(self) -> bool:
        return self.realized_points - self.rival_realized_points > WINS_BIG_MARGIN


def _parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive-root", type=Path, default=DEFAULT_ARCHIVE_ROOT)
    parser.add_argument(
        "--seasons",
        default=",".join(DEVELOPMENT_SEASONS),
        help="Comma-separated development seasons; anything short of the full four is "
        "an instrument smoke run, not the pre-registered population.",
    )
    parser.add_argument("--solver-time-limit", type=float, default=30.0)
    parser.add_argument("--pool-per-position", type=int, default=15)
    parser.add_argument("--cheap-per-position", type=int, default=5)
    parser.add_argument(
        "--json-output", type=Path, default=REPOSITORY_ROOT / "docs" / "strategy_bench.json"
    )
    parser.add_argument(
        "--markdown-output", type=Path, default=REPOSITORY_ROOT / "docs" / "strategy_bench.md"
    )
    return parser.parse_args()


def _build_fold(
    panel: pd.DataFrame,
    residuals: pd.DataFrame,
    ownership: pd.DataFrame,
    season: str,
    origin: int,
    arguments: argparse.Namespace,
) -> Fold | None:
    """One fold's planner inputs and rival — the mode_plan_selection instrument."""

    fold_id = f"{season}-gw{origin:02d}"
    block = residuals.loc[residuals["fold_id"] == fold_id]
    if block.empty:
        return None
    prices = panel.loc[panel["season"] == season, ["gameweek", "player_id", "price_tenths", "name"]]
    pool = block.merge(
        prices.loc[prices["gameweek"] == origin, ["player_id", "price_tenths", "name"]],
        on="player_id",
        how="inner",
    )
    own = ownership.loc[
        (ownership["season"] == season) & (ownership["gameweek"] == origin),
        ["player_id", "selected"],
    ]
    pool = pool.merge(own, on="player_id", how="left")
    pool["ownership"] = pool["selected"].fillna(0.0)
    rival = template_rival_from_ownership(pool.loc[:, ["player_id", "position", "ownership"]])

    optimization = OptimizationConfig(solver_time_limit_seconds=float(arguments.solver_time_limit))
    full_projection = pool.loc[
        :, ["player_id", "name", "team_id", "position", "price_tenths"]
    ].copy()
    full_projection["expected_points"] = pool["predicted_points"].clip(lower=0.0)
    held = optimize_squad(full_projection, optimization)
    if not held.has_solution:
        return None
    held_ids = {int(v) for v in held.selected_squad["player_id"]}
    held_cost = int(held.selected_squad["price_tenths"].sum())

    keep: set[int] = {int(str(p)) for p in rival.starter_ids} | held_ids
    for _, position_block in pool.groupby("position"):
        keep.update(
            int(v)
            for v in position_block.sort_values("predicted_points", ascending=False).head(
                int(arguments.pool_per_position)
            )["player_id"]
        )
        keep.update(
            int(v)
            for v in position_block.sort_values("price_tenths", ascending=True).head(
                int(arguments.cheap_per_position)
            )["player_id"]
        )
    pool = pool.loc[pool["player_id"].isin(keep)].reset_index(drop=True)
    base = pool.loc[
        :, ["player_id", "name", "team_id", "position", "predicted_points", "price_tenths"]
    ].copy()
    initial_state = InitialSquadState(
        squad_player_ids=tuple(sorted(held_ids)),
        bank_tenths=max(0, 1000 - held_cost),
        free_transfers=1,
    )
    return Fold(
        season=season,
        fold_id=fold_id,
        origin=origin,
        horizon_table=base,
        initial_state=initial_state,
        rival_ids=frozenset(int(str(p)) for p in rival.starter_ids),
        rival_captain=int(str(rival.captain_id)),
    )


def _window_horizon(fold: Fold, gameweeks: tuple[int, ...]) -> PlanningHorizon:
    frames = []
    for gameweek in gameweeks:
        frame = fold.horizon_table.copy()
        frame["gameweek"] = gameweek
        frame["expected_points"] = frame["predicted_points"].clip(lower=0.0)
        frame["buy_price_tenths"] = frame["price_tenths"].astype("int64")
        frame["sell_price_tenths"] = frame["price_tenths"].astype("int64")
        frames.append(frame.drop(columns=["predicted_points", "price_tenths"]))
    return PlanningHorizon(pd.concat(frames, ignore_index=True))


def _realized_by_week(
    season_panel: pd.DataFrame, gameweeks: tuple[int, ...]
) -> dict[int, dict[int, float]]:
    by_week: dict[int, dict[int, float]] = {}
    for gameweek in gameweeks:
        week = season_panel.loc[season_panel["gameweek"] == gameweek]
        by_week[gameweek] = {
            int(row.player_id): float(row.total_points)
            for row in week.loc[:, ["player_id", "total_points"]].itertuples()
        }
    return by_week


def _score_plan(
    weeks: tuple[PlanningWeekResult, ...], realized: dict[int, dict[int, float]]
) -> float:
    total = 0.0
    for week in weeks:
        points = realized.get(int(week.gameweek), {})
        starters = [int(v) for v in week.starting_xi["player_id"]]
        captain = int(week.captain["player_id"])
        total += sum(points.get(p, 0.0) for p in starters) + points.get(captain, 0.0)
    return total


def _score_rival(
    fold: Fold, realized: dict[int, dict[int, float]], gameweeks: tuple[int, ...]
) -> float:
    total = 0.0
    for gameweek in gameweeks:
        points = realized.get(gameweek, {})
        total += sum(points.get(p, 0.0) for p in fold.rival_ids) + points.get(
            fold.rival_captain, 0.0
        )
    return total


def _plans_identical(left: TransferPlanResult, right: TransferPlanResult) -> bool:
    if len(left.weeks) != len(right.weeks):
        return False
    for mine, theirs in zip(left.weeks, right.weeks, strict=True):
        if sorted(int(v) for v in mine.selected_squad["player_id"]) != sorted(
            int(v) for v in theirs.selected_squad["player_id"]
        ):
            return False
        if sorted(int(v) for v in mine.starting_xi["player_id"]) != sorted(
            int(v) for v in theirs.starting_xi["player_id"]
        ):
            return False
        if int(mine.captain["player_id"]) != int(theirs.captain["player_id"]):
            return False
    return True


def _interval(
    pairs: list[tuple[str, float]], candidate_id: str, policy: PromotionPolicy
) -> tuple[float, float, float]:
    low, high = season_aware_moving_block_interval(pairs, policy=policy, candidate_id=candidate_id)
    return fmean(value for _, value in pairs), low, high


def main() -> int:
    arguments = _parse_arguments()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    created_utc = datetime.now(UTC).isoformat(timespec="seconds")
    started = perf_counter()

    LOGGER.info("Building the panel and the control's residual folds")
    panel = build_panel(arguments.archive_root)
    residuals = build_control_residual_table(panel, PolicyObjectiveConfig())
    ownership = load_enrichment_rows(arguments.archive_root, DEVELOPMENT_SEASONS)
    optimization = OptimizationConfig(solver_time_limit_seconds=float(arguments.solver_time_limit))
    high = STRATEGY_CATALOG["ortak-koru"]
    differential = STRATEGY_CATALOG["fark-yarat"]

    folds: list[Fold] = []
    seasons = tuple(s for s in str(arguments.seasons).split(",") if s)
    if "2025-26" in seasons:
        print("2025-26 is the locked holdout and may not be read.")
        return 1
    for season in seasons:
        season_ids = sorted(
            residuals.loc[residuals["fold_id"].str.startswith(season), "fold_id"].unique()
        )
        for fold_id in season_ids:
            origin = int(fold_id.rsplit("gw", 1)[1])
            fold = _build_fold(panel, residuals, ownership, season, origin, arguments)
            if fold is None:
                LOGGER.info("%s: not built; recorded, not imputed", fold_id)
                continue
            folds.append(fold)
    LOGGER.info("%d folds built", len(folds))

    outcomes: dict[int, dict[str, dict[str, BandOutcome]]] = {h: {} for h in HORIZONS}
    seasons_of: dict[str, str] = {}
    mirror_failures: list[str] = []
    clipped_windows = 0
    for fold in folds:
        seasons_of[fold.fold_id] = fold.season
        season_panel = panel.loc[panel["season"] == fold.season]
        last_gameweek = int(season_panel["gameweek"].max())
        for horizon in HORIZONS:
            effective = min(horizon, last_gameweek - fold.origin + 1)
            if effective < 1:
                continue
            if effective < horizon:
                clipped_windows += 1
            gameweeks = tuple(range(fold.origin, fold.origin + effective))
            horizon_table = _window_horizon(fold, gameweeks)
            realized = _realized_by_week(season_panel, gameweeks)
            control = optimize_transfer_plan(horizon_table, fold.initial_state, optimization)
            if control.solver_status is not SolverStatus.OPTIMAL or not control.weeks:
                continue
            if horizon == 1:
                mirror = optimize_transfer_plan(horizon_table, fold.initial_state, optimization)
                if not _plans_identical(control, mirror):
                    mirror_failures.append(fold.fold_id)
            row: dict[str, BandOutcome] = {
                "control": BandOutcome(
                    realized_points=_score_plan(control.weeks, realized),
                    rival_realized_points=_score_rival(fold, realized, gameweeks),
                    claimed_cost=None,
                    hit_points=float(control.total_transfer_hit_points or 0.0),
                    overlap_count=None,
                )
            }
            for band_name, strategy in (("high_overlap", high), ("differential", differential)):
                plan = solve_strategy_plan(
                    strategy,
                    horizon_table,
                    fold.initial_state,
                    optimization,
                    rival_player_ids=frozenset(fold.rival_ids),
                    control_plan=control,
                )
                if plan is None:
                    continue
                row[band_name] = BandOutcome(
                    realized_points=_score_plan(plan.plan.weeks, realized),
                    rival_realized_points=row["control"].rival_realized_points,
                    claimed_cost=float(plan.expected_points_cost),
                    hit_points=float(plan.plan.total_transfer_hit_points or 0.0),
                    overlap_count=plan.overlap_count,
                )
            outcomes[horizon][fold.fold_id] = row
        LOGGER.info("%s scored", fold.fold_id)

    policy = PromotionPolicy()
    horizons_report: dict[str, dict[str, object]] = {}
    for horizon in HORIZONS:
        rows = outcomes[horizon]
        feasibility = {
            band: (sum(1 for row in rows.values() if band in row) / len(rows) if rows else 0.0)
            for band in BANDS
        }
        # Diagnostics, not gates: a band whose claimed cost is zero solved to the same
        # objective as the control, and the deterministic tie-break makes that the same
        # plan — a constraint that never binds is a product finding worth surfacing.
        binding: dict[str, object] = {}
        for band in ("high_overlap", "differential"):
            present = [row[band] for row in rows.values() if band in row]
            if present:
                binding[band] = {
                    "share_cost_zero": fmean(
                        1.0 if float(outcome.claimed_cost or 0.0) == 0.0 else 0.0
                        for outcome in present
                    ),
                    "mean_overlap_count": fmean(
                        float(outcome.overlap_count)
                        for outcome in present
                        if outcome.overlap_count is not None
                    ),
                }

        separation_pairs = [
            (
                seasons_of[fold_id],
                float(row["high_overlap"].behind) - float(row["differential"].behind),
            )
            for fold_id, row in rows.items()
            if "high_overlap" in row and "differential" in row
        ]
        separation: dict[str, object] = {"paired_folds": len(separation_pairs)}
        if separation_pairs:
            mean, low, high_bound = _interval(separation_pairs, f"separation-h{horizon}", policy)
            separation.update(
                {
                    "mean_difference": mean,
                    "interval_90": [low, high_bound],
                    "passes": bool(mean < 0.0 and (low > 0.0 or high_bound < 0.0)),
                }
            )

        wins_big = {
            band: (
                fmean(float(row[band].wins_big) for row in rows.values() if band in row)
                if any(band in row for row in rows.values())
                else None
            )
            for band in BANDS
        }
        direction_passes = None
        if all(value is not None for value in wins_big.values()):
            direction_passes = bool(
                wins_big["differential"] is not None
                and wins_big["differential"] == max(v for v in wins_big.values() if v is not None)
                and all(
                    wins_big["differential"] >= v
                    for k, v in wins_big.items()
                    if k != "differential" and v is not None
                )
            )

        price: dict[str, dict[str, object]] = {}
        for band in ("high_overlap", "differential"):
            pairs = [
                (
                    seasons_of[fold_id],
                    (row["control"].realized_points - row[band].realized_points)
                    - float(row[band].claimed_cost or 0.0),
                )
                for fold_id, row in rows.items()
                if band in row and "control" in row
            ]
            entry: dict[str, object] = {"paired_folds": len(pairs)}
            if pairs:
                mean, low, high_bound = _interval(pairs, f"price-{band}-h{horizon}", policy)
                entry.update(
                    {
                        "mean_realized_minus_claimed": mean,
                        "interval_90": [low, high_bound],
                        "passes": bool(not low > 0.0),
                    }
                )
            price[band] = entry

        horizons_report[str(horizon)] = {
            "folds": len(rows),
            "feasibility_share": feasibility,
            "gate1_separation": separation,
            "gate2_wins_big_frequency": wins_big,
            "gate2_direction_passes": direction_passes,
            "gate3_price_honesty": price,
            "band_binding_diagnostics": binding,
            "gated": horizon in GATED_HORIZONS,
        }

    h1_report = horizons_report.get("1", {})
    gate4 = {
        "mirrored_folds": len(outcomes[1]),
        "mismatches": mirror_failures,
        "passes": not mirror_failures,
    }

    document: dict[str, object] = {
        "contract_version": STRATEGY_BENCH_CONTRACT_VERSION,
        "created_utc": created_utc,
        "prereg": "docs/strategy_bench_prereg.md",
        "population": {
            "seasons": list(seasons),
            "is_declared_population": tuple(seasons) == DEVELOPMENT_SEASONS,
            "horizons": list(HORIZONS),
            "folds_built": len(folds),
            "clipped_windows": clipped_windows,
        },
        "bands": {
            "high_overlap": {"strategy": "ortak-koru", "overlap_floor": 9},
            "differential": {"strategy": "fark-yarat", "overlap_ceiling": 5},
            "control": {"strategy": "saf-puan"},
        },
        "interval_policy": {
            "confidence_level": 0.90,
            "bootstrap_resamples": 5000,
            "moving_block_length": 4,
            "deterministic_seed": 0,
        },
        "horizons": horizons_report,
        "gate4_h1_not_sacrificed": gate4,
        "holdout_untouched": True,
        "elapsed_seconds": round(perf_counter() - started, 1),
        "metadata": artifact_metadata(panel_rows=len(panel), created_utc=created_utc),
    }
    write_json(arguments.json_output, document)
    write_text(arguments.markdown_output, _to_markdown(document))
    LOGGER.info(
        "Wrote %s in %.1fs (h1 folds: %s)",
        arguments.json_output,
        document["elapsed_seconds"],
        h1_report.get("folds"),
    )
    return 0


def _to_markdown(document: dict[str, object]) -> str:
    lines = [
        "# Strategy bench: the pre-registered gates, applied",
        "",
        f"- Contract: `{document['contract_version']}`; gates fixed in "
        "`strategy_bench_prereg.md` (#279) before the catalogue existed",
        f"- Population: {document['population']}",
        f"- Bands: {document['bands']}",
        "- The locked holdout was not accessed by this run.",
        "",
    ]
    horizons = document["horizons"]
    assert isinstance(horizons, dict)
    for horizon, entry in horizons.items():
        gated = "gated" if entry["gated"] else "reported"
        lines.append(f"## h={horizon} ({gated}) — {entry['folds']} folds")
        lines.append("")
        lines.append(f"- Feasibility: {entry['feasibility_share']}")
        lines.append(f"- Gate 1 (separation): {entry['gate1_separation']}")
        lines.append(
            f"- Gate 2 (direction): frequencies {entry['gate2_wins_big_frequency']}, "
            f"passes: {entry['gate2_direction_passes']}"
        )
        lines.append(f"- Gate 3 (price honesty): {entry['gate3_price_honesty']}")
        lines.append(f"- Band binding (diagnostic): {entry['band_binding_diagnostics']}")
        lines.append("")
    lines.append(f"## Gate 4 (h=1 not sacrificed): {document['gate4_h1_not_sacrificed']}")
    lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    sys.exit(main())
