"""Evaluate the complete deterministic policy grid and measure the recorded search.

    python -m scripts.run_exhaustive_policy_grid \
        --bayesopt-artifact docs/baseline_bayesopt.json \
        --json-output docs/baseline_policy_grid.json \
        --markdown-output docs/baseline_policy_grid.md

Every canonical candidate of the finite grid is evaluated exactly once on the real
development folds, turning the grid into ground truth. The recorded budgeted Bayesian
search is then measured against that truth: regret, true rank of its recommendation,
and whether it found the true optimum. The two runs must share the objective
configuration, and every shared candidate must reproduce its value exactly.
"""

import argparse
import json
import logging
import sys
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

from scripts._experiment_cli import (
    DEFAULT_ARCHIVE_ROOT,
    REPOSITORY_ROOT,
    artifact_metadata,
    write_json,
    write_text,
)

from squadopt.bayesopt import BayesianFactor, BayesianOptimizationConfig, FactorKind
from squadopt.data.sources.vaastav import build_panel
from squadopt.experiments import (
    PINNED_RISK_AVERSION,
    POLICY_GRID_CONTRACT_VERSION,
    BaselinePolicyObjective,
    ExperimentError,
    PolicyGridResult,
    PolicyObjectiveConfig,
    evaluate_policy_grid,
    summarize_search_efficiency,
)

LOGGER = logging.getLogger(__name__)


def _parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive-root", type=Path, default=DEFAULT_ARCHIVE_ROOT)
    parser.add_argument("--form-window-minimum", type=int, default=3)
    parser.add_argument("--form-window-maximum", type=int, default=10)
    parser.add_argument("--bench-weight-maximum", type=float, default=0.30)
    parser.add_argument("--bench-weight-step", type=float, default=0.05)
    parser.add_argument(
        "--bayesopt-artifact",
        type=Path,
        default=REPOSITORY_ROOT / "docs" / "baseline_bayesopt.json",
    )
    parser.add_argument(
        "--json-output",
        type=Path,
        default=REPOSITORY_ROOT / "docs" / "baseline_policy_grid.json",
    )
    parser.add_argument(
        "--markdown-output",
        type=Path,
        default=REPOSITORY_ROOT / "docs" / "baseline_policy_grid.md",
    )
    return parser.parse_args()


def _grid_document(
    grid: PolicyGridResult,
    efficiency: Mapping[str, object],
) -> dict[str, object]:
    return {
        "contract_version": POLICY_GRID_CONTRACT_VERSION,
        "objective_configuration_fingerprint": (grid.objective_configuration_fingerprint),
        "development_fold_count": grid.development_fold_count,
        "pinned_risk_aversion": PINNED_RISK_AVERSION,
        "grid_size": len(grid.cells),
        "true_best_candidate_id": grid.best.candidate_id,
        "true_best_mean_realized_squad_points": (grid.best.mean_realized_squad_points),
        "search_efficiency": dict(efficiency),
        "recommendation_only": True,
        "locked_holdout_accessed": False,
        "automatic_promotion": False,
        "cells": [
            {
                "rank": cell.rank,
                "candidate_id": cell.candidate_id,
                "form_window": cell.form_window,
                "bench_weight": cell.bench_weight,
                "mean_realized_squad_points": cell.mean_realized_squad_points,
            }
            for cell in grid.cells
        ],
    }


def _grid_markdown(
    grid: PolicyGridResult,
    efficiency: Mapping[str, object],
) -> str:
    lines = [
        "# Exhaustive deterministic policy grid",
        "",
        f"- Contract: `{POLICY_GRID_CONTRACT_VERSION}`",
        f"- Development folds: {grid.development_fold_count}",
        f"- Grid size: {len(grid.cells)} candidates, all evaluated",
        f"- Pinned risk_aversion: {PINNED_RISK_AVERSION}",
        "",
        f"**True optimum**: `{grid.best.candidate_id}` with mean realized squad "
        f"points {grid.best.mean_realized_squad_points:.4f}.",
        "",
        "## Bayesian search measured against ground truth",
        "",
        f"- Search evaluated {efficiency['search_evaluations']} of "
        f"{efficiency['grid_size']} candidates "
        f"({float(str(efficiency['budget_fraction'])) * 100:.0f}% of the grid)",
        f"- Recommendation: `{efficiency['recommended_candidate_id']}` "
        f"(true rank {efficiency['recommendation_true_rank']})",
        f"- Regret: {float(str(efficiency['recommendation_regret_points'])):.4f} squad points",
        f"- Found the true optimum: {efficiency['search_found_true_best']}"
        + (
            f" (iteration {efficiency['true_best_found_at_iteration']})"
            if efficiency["true_best_found_at_iteration"] is not None
            else ""
        ),
        f"- Top-5 cells evaluated by the search: {efficiency['top_five_evaluated_by_search']}/5",
        "",
        "This is measurement of a recommendation-only search. The locked holdout was",
        "not accessed, nothing was promoted, and the operational control is unchanged.",
        "",
        "## Complete ranking",
        "",
        "| Rank | Candidate | form_window | bench_weight | Mean realized points |",
        "| --- | --- | --- | --- | --- |",
    ]
    for cell in grid.cells:
        lines.append(
            f"| {cell.rank} | `{cell.candidate_id}` | {cell.form_window} "
            f"| {cell.bench_weight:.2f} | {cell.mean_realized_squad_points:.4f} |"
        )
    return "\n".join(lines) + "\n"


def main() -> int:
    arguments = _parse_arguments()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    archive_root: Path = arguments.archive_root
    if not archive_root.is_dir():
        print(
            f"Archive not found at {archive_root}.\n"
            "Run 'python -m scripts.fetch_historical_data' first."
        )
        return 1
    artifact_path: Path = arguments.bayesopt_artifact
    if not artifact_path.is_file():
        print(f"Bayesian search artifact not found at {artifact_path}.")
        return 1
    bayesopt_document = json.loads(artifact_path.read_text(encoding="utf-8"))
    if not isinstance(bayesopt_document, dict):
        print(f"Bayesian search artifact {artifact_path} must contain a JSON object.")
        return 1

    created_utc = datetime.now(UTC).isoformat(timespec="seconds")
    panel = build_panel(archive_root)
    objective = BaselinePolicyObjective(panel, PolicyObjectiveConfig())
    search_config = BayesianOptimizationConfig(
        factors=(
            BayesianFactor(
                "form_window",
                arguments.form_window_minimum,
                arguments.form_window_maximum,
                1,
                FactorKind.INTEGER,
            ),
            BayesianFactor(
                "bench_weight",
                0.0,
                arguments.bench_weight_maximum,
                arguments.bench_weight_step,
            ),
        ),
        evaluation_budget=1,
        initial_design_size=1,
    )

    try:
        LOGGER.info(
            "Evaluating all %s candidates on %s folds",
            search_config.search_space_size,
            len(objective.development_fold_ids),
        )
        grid = evaluate_policy_grid(objective, search_config)
        efficiency = summarize_search_efficiency(grid, bayesopt_document)
    except ExperimentError as error:
        print(f"Could not evaluate the policy grid:\n  {error}")
        return 1

    document = {
        **artifact_metadata(panel_rows=len(panel), created_utc=created_utc),
        **_grid_document(grid, efficiency),
    }
    markdown = _grid_markdown(grid, efficiency)
    write_json(arguments.json_output, document)
    write_text(arguments.markdown_output, markdown)

    print(markdown)
    print(f"Wrote {arguments.json_output}")
    print(f"Wrote {arguments.markdown_output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
