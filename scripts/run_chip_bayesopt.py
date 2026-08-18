"""Bayesian search over the chip holding values and the planning hit cost, on the season chain.

    python -m scripts.run_chip_bayesopt --evaluation-budget 20 --workers 4

The season chain measured chip policies and transfer discipline one setting at a time
(docs/season_chain_note.md, docs/transfer_discipline_note.md). This searches the
continuous controls those measurements left as knobs — the terminal holding value of
each chip (bench boost, triple captain, wildcard, free hit) and the planner's own hit
cost — with the project's Bayesian optimizer (`deterministic_policy_bo_v1`: maximin
initial design, GP surrogate, expected improvement) over a finite quantized grid.

Objective, per candidate: the four development seasons are walked as chains at
lookahead 1 with every chip offered and held at the candidate's values, and the
**season-robust** score is the mean season net minus one standard deviation across
seasons — a candidate that wins one season and loses three is not a candidate. Every
season's raw net is recorded so the reader can undo the penalty. Four seasons is a
small sample: the recommendation is a **candidate** for the next season chain and the
gates, never a promotion.

Measurement only; the locked 2025-26 holdout is refused; seasons run in parallel
worker processes (one panel build each).
"""

import argparse
import logging
import statistics
import sys
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor
from datetime import UTC, datetime
from numbers import Real
from pathlib import Path

from scripts._experiment_cli import (
    DEFAULT_ARCHIVE_ROOT,
    REPOSITORY_ROOT,
    artifact_metadata,
    write_json,
    write_text,
)
from scripts.run_season_chain_seasons import MAX_FREE_TRANSFERS, _fixture_counts, chip_windows_for

from squadopt.bayesopt import (
    BayesianCandidate,
    BayesianFactor,
    BayesianOptimizationConfig,
    BayesianOptimizationResult,
    FactorKind,
    run_bayesian_optimization,
)
from squadopt.data.sources.vaastav import build_panel
from squadopt.experiments import SeasonChain, SeasonChainConfig
from squadopt.optimization import OptimizationConfig
from squadopt.planning import TransferPlanningConfig

LOGGER = logging.getLogger(__name__)
CHIP_BAYESOPT_CONTRACT_VERSION = "chip_bayesopt_v1"
DEFAULT_SEASONS = "2021-22,2022-23,2023-24,2024-25"
LOCKED_HOLDOUT_SEASON = "2025-26"

_WORKER_STATE: dict[str, object] = {}


def _parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive-root", type=Path, default=DEFAULT_ARCHIVE_ROOT)
    parser.add_argument("--seasons", default=DEFAULT_SEASONS)
    parser.add_argument("--evaluation-budget", type=int, default=20)
    parser.add_argument("--initial-design-size", type=int, default=8)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--deterministic-time-limit", type=float, default=8.0)
    parser.add_argument("--wall-time-limit", type=float, default=60.0)
    parser.add_argument("--chip-mode", choices=("value", "hybrid"), default="hybrid")
    parser.add_argument("--robustness-weight", type=float, default=1.0)
    parser.add_argument(
        "--wildcard-hold-upper",
        type=int,
        default=40,
        help="upper edge of the wildcard_hold grid (step 4; the first run's 24 was hit)",
    )
    parser.add_argument(
        "--json-output", type=Path, default=REPOSITORY_ROOT / "docs" / "chip_bayesopt.json"
    )
    parser.add_argument(
        "--markdown-output", type=Path, default=REPOSITORY_ROOT / "docs" / "chip_bayesopt.md"
    )
    return parser.parse_args()


def _factors(wildcard_upper: int = 40) -> tuple[BayesianFactor, ...]:
    # The first run's recommended wildcard_hold sat on the old upper edge (24); the grid
    # now reaches 40 so the search can say where the value stops rising.
    return (
        BayesianFactor("bboost_hold", 0, 30, 5, FactorKind.INTEGER),
        BayesianFactor("threexc_hold", 0, 30, 5, FactorKind.INTEGER),
        BayesianFactor("wildcard_hold", 0, wildcard_upper, 4, FactorKind.INTEGER),
        BayesianFactor("freehit_hold", 0, 20, 5, FactorKind.INTEGER),
        BayesianFactor("planning_hit_cost", 4, 8, 1, FactorKind.INTEGER),
    )


def _init_worker(archive_root: str, deterministic: float, wall: float) -> None:
    root = Path(archive_root)
    _WORKER_STATE["archive_root"] = root
    _WORKER_STATE["panel"] = build_panel(root)
    _WORKER_STATE["optimization"] = OptimizationConfig(
        solver_time_limit_seconds=wall, solver_deterministic_time_limit=deterministic
    )
    _WORKER_STATE["counts"] = {}


def _season_net(task: tuple[str, dict[str, float], str]) -> tuple[str, float, dict[str, object]]:
    season, values, mode = task
    root = _WORKER_STATE["archive_root"]
    assert isinstance(root, Path)
    counts_cache = _WORKER_STATE["counts"]
    assert isinstance(counts_cache, dict)
    if season not in counts_cache:
        counts_cache[season] = _fixture_counts(root, season)
    holding = {
        "bboost": float(values["bboost_hold"]),
        "3xc": float(values["threexc_hold"]),
        "wildcard": float(values["wildcard_hold"]),
        "freehit": float(values["freehit_hold"]),
    }
    config = SeasonChainConfig(
        season=season,
        lookahead=1,
        chip_windows=chip_windows_for(season),
        chip_policy="hybrid" if mode == "hybrid" else "planner",
        optimization_config=_WORKER_STATE["optimization"],  # type: ignore[arg-type]
        transfer_config=TransferPlanningConfig(
            max_free_transfers=MAX_FREE_TRANSFERS.get(season, 5),
            transfer_hit_cost_points=float(values["planning_hit_cost"]),
            chip_holding_value_points=holding,
        ),
    )
    result = SeasonChain(_WORKER_STATE["panel"], counts_cache[season], config).run()  # type: ignore[arg-type]
    return (
        season,
        result.net_points,
        {
            "realized_points": result.realized_points,
            "transfer_hit_points": result.transfer_hit_points,
            "chips_played": {str(k): v for k, v in result.chips_played.items()},
            "chip_realized_gains": dict(result.chip_realized_gains),
            "proven_share": result.proven_share,
        },
    )


def main() -> int:
    arguments = _parse_arguments()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    seasons = tuple(s.strip() for s in str(arguments.seasons).split(","))
    if LOCKED_HOLDOUT_SEASON in seasons:
        print(f"{LOCKED_HOLDOUT_SEASON} is the locked holdout and may not be walked.")
        return 1
    if not arguments.archive_root.is_dir():
        print(f"Archive not found at {arguments.archive_root}.")
        return 1
    created_utc = datetime.now(UTC).isoformat(timespec="seconds")
    config = BayesianOptimizationConfig(
        factors=_factors(int(arguments.wildcard_hold_upper)),
        evaluation_budget=arguments.evaluation_budget,
        initial_design_size=arguments.initial_design_size,
        deterministic_seed=arguments.seed,
    )
    weight = float(arguments.robustness_weight)
    mode = str(arguments.chip_mode)
    evaluations: dict[str, dict[str, object]] = {}

    def evaluate_with(
        run_tasks: Callable[
            [list[tuple[str, dict[str, float], str]]],
            list[tuple[str, float, dict[str, object]]],
        ],
    ) -> BayesianOptimizationResult:
        def evaluator(candidate: BayesianCandidate, fold_ids: tuple[str, ...]) -> Real:
            values = {name: float(v) for name, v in candidate.values.items()}
            outcomes = run_tasks([(season, values, mode) for season in fold_ids])
            nets = {season: net for season, net, _ in outcomes}
            mean = statistics.fmean(nets.values())
            spread = statistics.pstdev(nets.values()) if len(nets) > 1 else 0.0
            score = mean - weight * spread
            evaluations[candidate.candidate_id] = {
                "values": values,
                "season_net": nets,
                "mean_net": mean,
                "season_spread": spread,
                "robust_score": score,
                "details": {season: detail for season, _, detail in outcomes},
            }
            LOGGER.info(
                "%s -> mean %.1f, spread %.1f, robust %.1f",
                candidate.candidate_id,
                mean,
                spread,
                score,
            )
            return score  # type: ignore[return-value]  # float is a registered Real

        return run_bayesian_optimization(evaluator, seasons, config)

    worker_args = (
        str(arguments.archive_root),
        float(arguments.deterministic_time_limit),
        float(arguments.wall_time_limit),
    )
    workers = max(1, min(int(arguments.workers), len(seasons)))
    started = datetime.now(UTC)
    if workers == 1:
        # In-process: no pool, so a test can stand in for the season chain.
        _init_worker(*worker_args)
        result = evaluate_with(lambda tasks: [_season_net(task) for task in tasks])
    else:
        with ProcessPoolExecutor(
            max_workers=workers, initializer=_init_worker, initargs=worker_args
        ) as pool:
            result = evaluate_with(lambda tasks: list(pool.map(_season_net, tasks)))
    elapsed = (datetime.now(UTC) - started).total_seconds()

    best = result.recommended_candidate
    document = {
        **artifact_metadata(panel_rows=0, created_utc=created_utc),
        "contract_version": CHIP_BAYESOPT_CONTRACT_VERSION,
        "bayesopt_contract_version": config.contract_version,
        "seasons": list(seasons),
        "chip_mode": mode,
        "objective": (
            f"mean season net over the development seasons minus {weight:g} x the standard "
            "deviation across seasons (season-robust); raw nets recorded per evaluation"
        ),
        "factors": [
            {"name": f.name, "lower": f.lower_bound, "upper": f.upper_bound, "step": f.step}
            for f in config.factors
        ],
        "evaluation_budget": arguments.evaluation_budget,
        "initial_design_size": arguments.initial_design_size,
        "solver_limits": {
            "deterministic_time_limit": arguments.deterministic_time_limit,
            "wall_time_limit": arguments.wall_time_limit,
        },
        "recommended_candidate": dict(best.values),
        "recommended_evaluation": evaluations.get(best.candidate_id),
        "evaluations": [
            {
                "iteration": e.iteration,
                "phase": e.phase,
                "candidate": dict(e.candidate.values),
                "objective_value": e.objective_value,
                "predicted_mean": e.predicted_mean,
                "expected_improvement": e.expected_improvement,
                **{
                    key: evaluations[e.candidate.candidate_id][key]
                    for key in ("season_net", "mean_net", "season_spread")
                    if e.candidate.candidate_id in evaluations
                },
            }
            for e in result.evaluations
        ],
        "elapsed_seconds": elapsed,
        "measurement_only": True,
        "locked_holdout_accessed": False,
        "promotion": "none - a candidate for the next season chain and the gates",
    }
    lines = [
        "# Bayesian search over chip holding values and planning hit cost (season chain)",
        "",
        f"- Contract `{CHIP_BAYESOPT_CONTRACT_VERSION}` on `{config.contract_version}`; seasons "
        f"{', '.join(seasons)}; chip mode {mode}; budget {arguments.evaluation_budget} "
        f"({arguments.initial_design_size} initial); {elapsed / 60:.0f} min.",
        f"- Objective: mean season net minus {weight:g} x season standard deviation.",
        "",
        "| Iteration | Phase | bboost | 3xc | wildcard | freehit | hit cost "
        "| Mean net | Spread | Robust |",
        "| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for e in result.evaluations:
        v = e.candidate.values
        detail = evaluations.get(e.candidate.candidate_id, {})
        lines.append(
            f"| {e.iteration} | {e.phase} | {v['bboost_hold']} | {v['threexc_hold']} "
            f"| {v['wildcard_hold']} | {v['freehit_hold']} | {v['planning_hit_cost']} "
            f"| {float(str(detail.get('mean_net', 0.0))):.0f} "
            f"| {float(str(detail.get('season_spread', 0.0))):.0f} | {e.objective_value:.1f} |"
        )
    lines += [
        "",
        f"Recommended candidate: `{best.candidate_id}` — a candidate for the next season chain "
        "and the gates, not a promotion. Measurement only; the 2025-26 holdout was not read.",
        "",
    ]
    markdown = "\n".join(lines)
    write_json(arguments.json_output, document)
    write_text(arguments.markdown_output, markdown)
    print(markdown)
    print(f"Wrote {arguments.json_output}")
    print(f"Wrote {arguments.markdown_output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
