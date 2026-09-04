"""Run deterministic Bayesian policy search on the real development folds.

    python -m scripts.run_baseline_bayesopt \
        --evaluation-budget 16 \
        --initial-design-size 6 \
        --json-output artifacts/bayesopt/baseline_bayesopt.json \
        --markdown-output artifacts/bayesopt/baseline_bayesopt.md

The search covers the deterministic baseline policy factors (`form_window`,
`bench_weight`) under the frozen `single_gameweek_realized_squad_points_v1` objective.
`risk_aversion` stays pinned at the operational control's 0.0, because the
deterministic evaluator has no scenario input that a nonzero value could act on.

The run is a recommendation only: it never touches the locked holdout, never promotes
a candidate, and never changes the operational control.
"""

import argparse
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path

from scripts._experiment_cli import (
    DEFAULT_ARCHIVE_ROOT,
    REPOSITORY_ROOT,
    artifact_metadata,
    write_json,
    write_text,
)

from squadopt.bayesopt import (
    BayesianFactor,
    BayesianOptimizationConfig,
    BayesianOptimizationResult,
    FactorKind,
    run_bayesian_optimization,
)
from squadopt.data.sources.vaastav import build_panel
from squadopt.experiments import (
    PINNED_RISK_AVERSION,
    POLICY_OBJECTIVE_CONTRACT_VERSION,
    BaselinePolicyObjective,
    PolicyObjectiveConfig,
)

DEFAULT_ARTIFACT_ROOT = REPOSITORY_ROOT / "artifacts" / "bayesopt"


def _parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive-root", type=Path, default=DEFAULT_ARCHIVE_ROOT)
    parser.add_argument("--form-window-minimum", type=int, default=3)
    parser.add_argument("--form-window-maximum", type=int, default=10)
    parser.add_argument("--bench-weight-maximum", type=float, default=0.30)
    parser.add_argument("--bench-weight-step", type=float, default=0.05)
    parser.add_argument("--evaluation-budget", type=int, default=16)
    parser.add_argument("--initial-design-size", type=int, default=6)
    parser.add_argument("--deterministic-seed", type=int, default=0)
    parser.add_argument(
        "--json-output",
        type=Path,
        default=DEFAULT_ARTIFACT_ROOT / "baseline_bayesopt.json",
    )
    parser.add_argument(
        "--markdown-output",
        type=Path,
        default=DEFAULT_ARTIFACT_ROOT / "baseline_bayesopt.md",
    )
    return parser.parse_args()


def _result_document(
    result: BayesianOptimizationResult,
    objective: BaselinePolicyObjective,
) -> dict[str, object]:
    return {
        "policy_objective_contract_version": POLICY_OBJECTIVE_CONTRACT_VERSION,
        "objective_configuration_fingerprint": (objective.config.configuration_fingerprint),
        "search_configuration_fingerprint": result.config.configuration_fingerprint,
        "run_fingerprint": result.run_fingerprint,
        "development_seasons": list(objective.config.development_seasons),
        "development_fold_count": len(objective.development_fold_ids),
        "pinned_risk_aversion": PINNED_RISK_AVERSION,
        "search_space_size": result.config.search_space_size,
        "evaluation_count": len(result.evaluations),
        "stopped_reason": result.stopped_reason,
        "recommended_candidate": dict(result.recommended_candidate.values),
        "recommended_candidate_id": result.recommended_candidate.candidate_id,
        "best_mean_realized_squad_points": result.best_objective_value,
        "recommendation_only": True,
        "locked_holdout_accessed": False,
        "automatic_promotion": False,
        "trace": [
            {
                "iteration": item.iteration,
                "phase": item.phase,
                "candidate_id": item.candidate.candidate_id,
                "mean_realized_squad_points": item.objective_value,
                "expected_improvement": item.expected_improvement,
            }
            for item in result.evaluations
        ],
        "candidate_records": {
            candidate_id: dict(record) for candidate_id, record in objective.records.items()
        },
    }


def _result_markdown(
    result: BayesianOptimizationResult,
    objective: BaselinePolicyObjective,
) -> str:
    lines = [
        "# Baseline deterministic policy search (Bayesian optimization)",
        "",
        f"- Objective contract: `{POLICY_OBJECTIVE_CONTRACT_VERSION}`",
        f"- Development seasons: {', '.join(objective.config.development_seasons)}",
        f"- Development folds: {len(objective.development_fold_ids)}",
        f"- Search space: {result.config.search_space_size} candidates; "
        f"evaluated {len(result.evaluations)}",
        f"- Pinned risk_aversion: {PINNED_RISK_AVERSION} (no scenario input in the "
        "deterministic evaluator)",
        f"- Stopped: {result.stopped_reason}",
        f"- Run fingerprint: `{result.run_fingerprint}`",
        "",
        f"**Recommended candidate**: `{result.recommended_candidate.candidate_id}` "
        f"with mean realized squad points {result.best_objective_value:.4f}.",
        "",
        "This is a recommendation only. The locked holdout was not accessed, nothing",
        "was promoted, and the operational control is unchanged.",
        "",
        "| Iteration | Phase | Candidate | Mean realized points |",
        "| --- | --- | --- | --- |",
    ]
    for item in result.evaluations:
        lines.append(
            f"| {item.iteration} | {item.phase} | `{item.candidate.candidate_id}` "
            f"| {item.objective_value:.4f} |"
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
        evaluation_budget=arguments.evaluation_budget,
        initial_design_size=arguments.initial_design_size,
        deterministic_seed=arguments.deterministic_seed,
    )
    result = run_bayesian_optimization(
        objective,
        objective.development_fold_ids,
        search_config,
    )

    document = {
        **artifact_metadata(panel_rows=len(panel), created_utc=created_utc),
        **_result_document(result, objective),
    }
    markdown = _result_markdown(result, objective)
    write_json(arguments.json_output, document)
    write_text(arguments.markdown_output, markdown)

    print(markdown)
    print(f"Wrote {arguments.json_output}")
    print(f"Wrote {arguments.markdown_output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
