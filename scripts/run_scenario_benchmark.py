"""Run a real-data Sprint 7 scenario smoke benchmark before the locked holdout."""

import argparse
import json
import sys
from pathlib import Path

from squadopt.backtest import (
    DecisionPoint,
    build_residual_history,
    build_walk_forward_fold,
    make_ridge_projection_builder,
    rows_through,
)
from squadopt.data.sources.vaastav import (
    ARCHIVE_COMMIT,
    ARCHIVE_REPOSITORY,
    build_panel,
)
from squadopt.optimization import OptimizationConfig, optimize_squad
from squadopt.prediction import PredictionSnapshot, RidgeProjectionConfig
from squadopt.scenarios import (
    ScenarioConfig,
    ScenarioEvaluationConfig,
    ScenarioTarget,
    evaluate_fixed_decision,
    generate_scenarios,
    scenario_result_to_dict,
    scenario_result_to_markdown,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ARCHIVE_ROOT = REPOSITORY_ROOT / "data" / "raw" / "vaastav-fpl"
DEFAULT_JSON_OUTPUT = REPOSITORY_ROOT / "artifacts" / "sprint7" / "scenario_benchmark.json"
DEFAULT_MARKDOWN_OUTPUT = REPOSITORY_ROOT / "artifacts" / "sprint7" / "scenario_benchmark.md"
LOCKED_HOLDOUT_SEASON = "2025-26"


def _parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season", default="2024-25")
    parser.add_argument("--target-gameweek", type=int, default=10)
    parser.add_argument("--history-start-gameweek", type=int, default=2)
    parser.add_argument("--scenario-count", type=int, default=2_000)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--archive-root", type=Path, default=DEFAULT_ARCHIVE_ROOT)
    parser.add_argument("--json-output", type=Path, default=DEFAULT_JSON_OUTPUT)
    parser.add_argument("--markdown-output", type=Path, default=DEFAULT_MARKDOWN_OUTPUT)
    return parser.parse_args()


def main() -> int:
    """Build past learned residuals, generate scenarios, and score one fixed decision."""

    arguments = _parse_arguments()
    if arguments.season == LOCKED_HOLDOUT_SEASON:
        print(f"{LOCKED_HOLDOUT_SEASON} is the locked holdout and is rejected by this command.")
        return 2
    if arguments.history_start_gameweek < 2:
        print("history-start-gameweek must be at least 2; GW1 uses a different information set.")
        return 2
    history_gameweeks = tuple(range(arguments.history_start_gameweek, arguments.target_gameweek))
    if len(history_gameweeks) < 2:
        print("At least two historical gameweeks must precede the target.")
        return 2
    if not arguments.archive_root.is_dir():
        print("Historical archive is absent; run python -m scripts.fetch_historical_data first.")
        return 1

    panel = build_panel(arguments.archive_root)
    ridge = RidgeProjectionConfig()
    builder = make_ridge_projection_builder(config=ridge)
    folds = tuple(
        build_walk_forward_fold(
            panel,
            DecisionPoint(arguments.season, gameweek),
            projection_builder=builder,
        )
        for gameweek in history_gameweeks
    )
    residuals = build_residual_history(folds)
    target = ScenarioTarget(arguments.season, arguments.target_gameweek)
    built = builder(
        rows_through(panel, DecisionPoint(target.season, target.gameweek)),
        DecisionPoint(target.season, target.gameweek),
    )
    if not isinstance(built, PredictionSnapshot):
        raise RuntimeError("The Ridge projection builder did not return PredictionSnapshot.")
    scenarios = generate_scenarios(
        built,
        residuals,
        target,
        ScenarioConfig(
            scenario_count=arguments.scenario_count,
            deterministic_seed=arguments.seed,
            min_history_folds=len(history_gameweeks),
            min_player_observations=max(2, min(8, len(history_gameweeks))),
        ),
    )
    decision = optimize_squad(built.table, OptimizationConfig())
    evaluation = evaluate_fixed_decision(
        decision,
        scenarios,
        ScenarioEvaluationConfig(),
    )
    report = scenario_result_to_dict(scenarios, evaluation)
    report["run_provenance"] = {
        "archive_repository": ARCHIVE_REPOSITORY,
        "archive_commit": ARCHIVE_COMMIT,
        "history_gameweeks": list(history_gameweeks),
        "locked_holdout_accessed": False,
    }
    arguments.json_output.parent.mkdir(parents=True, exist_ok=True)
    arguments.markdown_output.parent.mkdir(parents=True, exist_ok=True)
    arguments.json_output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    arguments.markdown_output.write_text(
        scenario_result_to_markdown(scenarios, evaluation),
        encoding="utf-8",
    )
    print(f"Wrote {arguments.json_output}")
    print(f"Wrote {arguments.markdown_output}")
    print(
        f"Scenarios: {evaluation.metrics.scenario_count}; mean: "
        f"{evaluation.metrics.mean_score:.4f}; lower quantile: "
        f"{evaluation.metrics.lower_quantile_score:.4f}; "
        f"mean worst tail: {evaluation.metrics.mean_worst_fraction_score:.4f}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
