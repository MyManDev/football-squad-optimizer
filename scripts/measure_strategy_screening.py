"""The overlap-knob screening: does the finer band deserve a search dimension?

    python -m scripts.measure_strategy_screening

Pre-registered in ``docs/strategy_screening_prereg.md`` before this ran. Two knobs are
wired to the solver today — ``ortak-koru``'s ``overlap_floor`` and ``fark-yarat``'s
``overlap_ceiling`` — and each is swept over its declared range on sixteen development
folds at horizon 1, fold-paired against its default level (the bench's gate band).
The verdict per knob is one of ``search``, ``freeze``, or ``no-verdict`` (default band
itself too rarely proven), by the pre-registered rule and nothing else.
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
from squadopt.experiments.design import DesignKind, ExperimentDesign, StrategyObjective
from squadopt.experiments.policy_objective import PolicyObjectiveConfig
from squadopt.experiments.residual_signal_scan import load_enrichment_rows
from squadopt.experiments.statistics import season_aware_moving_block_interval
from squadopt.optimization import OptimizationConfig, SolverStatus, optimize_squad
from squadopt.planning import (
    InitialSquadState,
    PlanningHorizon,
    TransferPlanResult,
    optimize_transfer_plan,
)
from squadopt.scenarios.rivals import template_rival_from_ownership

LOGGER = logging.getLogger(__name__)

STRATEGY_SCREENING_CONTRACT_VERSION = "strategy_screening_v1"
DEVELOPMENT_SEASONS = ("2021-22", "2022-23", "2023-24", "2024-25")
ORIGINS = (5, 15, 25, 33)
SCREENED_SLUGS = ("ortak-koru", "fark-yarat")
DEFAULT_LEVELS: dict[str, int] = {"ortak-koru": 9, "fark-yarat": 5}
FEASIBILITY_FLOOR = 0.75


@dataclass(frozen=True, slots=True)
class Fold:
    season: str
    fold_id: str
    horizon: PlanningHorizon
    initial_state: InitialSquadState
    rival_ids: frozenset[object]


@dataclass(frozen=True, slots=True)
class LevelSweep:
    """One knob level's proven expected points and costs, by fold id."""

    level: float
    values: dict[str, float | None]
    costs: dict[str, float | None]

    @property
    def proven(self) -> int:
        return sum(1 for value in self.values.values() if value is not None)


def _parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive-root", type=Path, default=DEFAULT_ARCHIVE_ROOT)
    parser.add_argument("--solver-time-limit", type=float, default=30.0)
    parser.add_argument("--pool-per-position", type=int, default=15)
    parser.add_argument("--cheap-per-position", type=int, default=5)
    parser.add_argument(
        "--json-output", type=Path, default=REPOSITORY_ROOT / "docs" / "strategy_screening.json"
    )
    parser.add_argument(
        "--markdown-output", type=Path, default=REPOSITORY_ROOT / "docs" / "strategy_screening.md"
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
    """One fold's planner inputs and rival eleven — the mode_plan_selection instrument."""

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

    frame = pool.loc[
        :, ["player_id", "name", "team_id", "position", "predicted_points", "price_tenths"]
    ].copy()
    frame["gameweek"] = origin
    frame["expected_points"] = frame.pop("predicted_points").clip(lower=0.0)
    frame["buy_price_tenths"] = frame["price_tenths"].astype("int64")
    frame["sell_price_tenths"] = frame["price_tenths"].astype("int64")
    horizon = PlanningHorizon(frame.drop(columns=["price_tenths"]))
    initial_state = InitialSquadState(
        squad_player_ids=tuple(sorted(held_ids)),
        bank_tenths=max(0, 1000 - held_cost),
        free_transfers=1,
    )
    return Fold(
        season=season,
        fold_id=fold_id,
        horizon=horizon,
        initial_state=initial_state,
        rival_ids=frozenset(int(str(p)) for p in rival.starter_ids),
    )


def _screening_objective(slug: str, factors: tuple[object, ...]) -> StrategyObjective:
    """The declared-space identity; the sweep records per-fold values itself."""

    def _unused(candidate: object) -> tuple[float, ...]:
        raise NotImplementedError("The screening sweep records fold values directly.")

    return StrategyObjective(
        strategy_slug=slug,
        factors=factors,  # type: ignore[arg-type]
        population_id="development-seasons-origins-5-15-25-33-h1",
        evaluate_folds=_unused,
    )


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
    folds: list[Fold] = []
    for season in DEVELOPMENT_SEASONS:
        for origin in ORIGINS:
            fold = _build_fold(panel, residuals, ownership, season, origin, arguments)
            if fold is None:
                LOGGER.info(
                    "Fold %s-gw%02d could not be built; recorded, not imputed", season, origin
                )
                continue
            folds.append(fold)
    LOGGER.info(
        "%d of %d declared folds built", len(folds), len(DEVELOPMENT_SEASONS) * len(ORIGINS)
    )

    controls: dict[str, TransferPlanResult | None] = {}
    for fold in folds:
        control = optimize_transfer_plan(fold.horizon, fold.initial_state, optimization)
        controls[fold.fold_id] = (
            control if control.solver_status is SolverStatus.OPTIMAL and control.weeks else None
        )
    LOGGER.info(
        "Controls proven in %d/%d folds",
        sum(1 for value in controls.values() if value is not None),
        len(folds),
    )

    strategies: dict[str, dict[str, object]] = {}
    for slug in SCREENED_SLUGS:
        strategy = STRATEGY_CATALOG[slug]
        design = ExperimentDesign(kind=DesignKind.FULL_FACTORIAL, factors=strategy.search_factors())
        knob_name = design.factors[0].name
        objective = _screening_objective(slug, design.factors)

        sweeps: list[LevelSweep] = []
        for candidate in design.candidates():
            level = float(candidate.values[knob_name])
            values: dict[str, float | None] = {}
            costs: dict[str, float | None] = {}
            for fold in folds:
                control = controls[fold.fold_id]
                if control is None:
                    values[fold.fold_id] = None
                    costs[fold.fold_id] = None
                    continue
                plan = solve_strategy_plan(
                    strategy,
                    fold.horizon,
                    fold.initial_state,
                    optimization,
                    rival_player_ids=fold.rival_ids,
                    knob_values={knob_name: int(level)},
                    control_plan=control,
                )
                if plan is None:
                    values[fold.fold_id] = None
                    costs[fold.fold_id] = None
                else:
                    values[fold.fold_id] = float(plan.plan.total_projected_score or 0.0)
                    costs[fold.fold_id] = float(plan.expected_points_cost)
            sweep = LevelSweep(level=level, values=values, costs=costs)
            sweeps.append(sweep)
            LOGGER.info(
                "%s %s=%d: proven %d/%d", slug, knob_name, int(level), sweep.proven, len(folds)
            )

        default_level = float(DEFAULT_LEVELS[slug])
        default_sweep = next(sweep for sweep in sweeps if sweep.level == default_level)
        share = default_sweep.proven / len(folds) if folds else 0.0
        default_ok = share >= FEASIBILITY_FLOOR
        # moving_block_length=2: with four folds per season the default block of 4
        # admits a single block per season and the bootstrap degenerates to a point
        # (see the prereg's amendment); two is the largest length that resamples.
        policy = PromotionPolicy(moving_block_length=2)
        level_reports: list[dict[str, object]] = []
        any_movement = False
        for sweep in sweeps:
            feasibility_share = sweep.proven / len(folds) if folds else 0.0
            proven_values = [value for value in sweep.values.values() if value is not None]
            proven_costs = [cost for cost in sweep.costs.values() if cost is not None]
            report: dict[str, object] = {
                "level": int(sweep.level),
                "feasibility_share": feasibility_share,
                "mean_expected_points": fmean(proven_values) if proven_values else None,
                "mean_cost": fmean(proven_costs) if proven_costs else None,
                "paired_delta_vs_default": None,
                "interval_90": None,
                "moves": None,
            }
            if sweep.level != default_level and default_ok:
                paired = [
                    (fold.season, sweep.values[fold.fold_id] - default_sweep.values[fold.fold_id])
                    for fold in folds
                    if sweep.values[fold.fold_id] is not None
                    and default_sweep.values[fold.fold_id] is not None
                ]
                if paired:
                    low, high = season_aware_moving_block_interval(
                        [(season, float(delta)) for season, delta in paired],
                        policy=policy,
                        candidate_id=f"{slug}-{knob_name}-{int(sweep.level)}",
                    )
                    delta = fmean(float(value) for _, value in paired)
                    excludes_zero = low > 0.0 or high < 0.0
                    moves = bool(excludes_zero and feasibility_share >= FEASIBILITY_FLOOR)
                    report["paired_delta_vs_default"] = delta
                    report["interval_90"] = [low, high]
                    report["moves"] = moves
                    any_movement = any_movement or moves
            level_reports.append(report)

        verdict = "no-verdict" if not default_ok else ("search" if any_movement else "freeze")
        strategies[slug] = {
            "knob": knob_name,
            "default_level": DEFAULT_LEVELS[slug],
            "default_feasibility_share": share,
            "objective_fingerprint": objective.objective_fingerprint,
            "design_fingerprint": design.design_fingerprint,
            "levels": level_reports,
            "verdict": verdict,
        }
        LOGGER.info("%s verdict: %s", slug, verdict)

    document: dict[str, object] = {
        "contract_version": STRATEGY_SCREENING_CONTRACT_VERSION,
        "created_utc": created_utc,
        "prereg": "docs/strategy_screening_prereg.md",
        "population": {
            "seasons": list(DEVELOPMENT_SEASONS),
            "origins": list(ORIGINS),
            "horizon": 1,
            "declared_folds": len(DEVELOPMENT_SEASONS) * len(ORIGINS),
            "built_folds": len(folds),
            "control_proven_folds": sum(1 for value in controls.values() if value is not None),
        },
        "feasibility_floor": FEASIBILITY_FLOOR,
        "interval_policy": {
            "confidence_level": 0.90,
            "bootstrap_resamples": 5000,
            "moving_block_length": 2,
            "deterministic_seed": 0,
        },
        "strategies": strategies,
        "holdout_untouched": True,
        "elapsed_seconds": round(perf_counter() - started, 1),
        "metadata": artifact_metadata(panel_rows=len(panel), created_utc=created_utc),
    }
    write_json(arguments.json_output, document)
    write_text(arguments.markdown_output, _to_markdown(document))
    LOGGER.info("Wrote %s in %.1fs", arguments.json_output, document["elapsed_seconds"])
    return 0


def _to_markdown(document: dict[str, object]) -> str:
    population = document["population"]
    lines = [
        "# Strategy screening: the overlap knobs",
        "",
        f"- Contract: `{document['contract_version']}`; pre-registered in "
        "`strategy_screening_prereg.md` before the run",
        f"- Population: {population}",
        "- The locked holdout was not accessed by this run.",
        "",
    ]
    strategies = document["strategies"]
    assert isinstance(strategies, dict)
    for slug, entry in strategies.items():
        lines.append(f"## `{slug}` — knob `{entry['knob']}` (default {entry['default_level']})")
        lines.append("")
        lines.append(
            "| Level | Proven share | Mean E[pts] | Mean cost | Δ vs default | 90% CI | Moves |"
        )
        lines.append("| ---: | ---: | ---: | ---: | ---: | --- | --- |")
        for row in entry["levels"]:
            interval = row["interval_90"]
            interval_text = f"[{interval[0]:+.3f}, {interval[1]:+.3f}]" if interval else "-"
            moves = row["moves"]
            lines.append(
                f"| {row['level']} | {row['feasibility_share']:.3f} "
                f"| {_fmt(row['mean_expected_points'])} | {_fmt(row['mean_cost'])} "
                f"| {_fmt(row['paired_delta_vs_default'])} "
                f"| {interval_text} "
                f"| {moves if moves is not None else '-'} |"
            )
        lines.append("")
        lines.append(f"**Verdict: `{entry['verdict']}`** — by the pre-registered rule.")
        lines.append("")
    return "\n".join(lines)


def _fmt(value: object) -> str:
    return f"{value:+.3f}" if isinstance(value, float) else "-"


if __name__ == "__main__":
    sys.exit(main())
