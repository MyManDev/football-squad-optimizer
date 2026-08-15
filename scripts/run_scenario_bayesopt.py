"""Run scenario-aware Bayesian policy search with a live risk_aversion axis.

    python -m scripts.run_scenario_bayesopt \
        --residuals artifacts/residuals/control_residuals.csv \
        --residuals-manifest artifacts/residuals/control_residuals.manifest.json \
        --seasons 2023-24,2024-25 \
        --evaluation-budget 12

Every candidate's decisions are optimized against joint player-point scenarios drawn
from the control regime's out-of-sample residual history, restricted per fold to
strictly earlier folds. `risk_aversion` therefore changes real decisions here — this
is the first search in which the three-factor space is meaningful.

When a manifest is supplied, the residual input is validated by the artifact
preflight before anything runs. The run is a recommendation only: no locked-holdout
access, no promotion, no control change.
"""

import argparse
import json
import logging
import sys
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
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
    SCENARIO_POLICY_OBJECTIVE_CONTRACT_VERSION,
    ExperimentError,
    ScenarioPolicyObjective,
    ScenarioPolicyObjectiveConfig,
)
from squadopt.preflight import (
    compute_table_sha256,
    preflight_report_to_markdown,
    run_residual_export_preflight,
)

LOGGER = logging.getLogger(__name__)
DEFAULT_SEASONS = "2023-24,2024-25"


def _parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive-root", type=Path, default=DEFAULT_ARCHIVE_ROOT)
    parser.add_argument("--residuals", type=Path, required=True)
    parser.add_argument("--residuals-manifest", type=Path)
    parser.add_argument(
        "--seasons",
        default=DEFAULT_SEASONS,
        help="Comma-separated seasons whose folds are evaluated.",
    )
    parser.add_argument("--scenario-count", type=int, default=200)
    parser.add_argument("--min-history-folds", type=int, default=8)
    parser.add_argument("--form-window-minimum", type=int, default=3)
    parser.add_argument("--form-window-maximum", type=int, default=10)
    parser.add_argument("--bench-weight-maximum", type=float, default=0.30)
    parser.add_argument("--bench-weight-step", type=float, default=0.05)
    parser.add_argument("--risk-aversion-step", type=float, default=0.10)
    parser.add_argument("--evaluation-budget", type=int, default=12)
    parser.add_argument("--initial-design-size", type=int, default=5)
    parser.add_argument("--deterministic-seed", type=int, default=0)
    parser.add_argument(
        "--json-output",
        type=Path,
        default=REPOSITORY_ROOT / "docs" / "scenario_bayesopt.json",
    )
    parser.add_argument(
        "--markdown-output",
        type=Path,
        default=REPOSITORY_ROOT / "docs" / "scenario_bayesopt.md",
    )
    return parser.parse_args()


def _read_manifest(path: Path) -> Mapping[str, object]:
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise SystemExit(f"Manifest {path} must contain a JSON object.")
    return document


def _result_document(
    result: BayesianOptimizationResult,
    objective: ScenarioPolicyObjective,
    residual_provenance: Mapping[str, object],
) -> dict[str, object]:
    return {
        "scenario_policy_objective_contract_version": (SCENARIO_POLICY_OBJECTIVE_CONTRACT_VERSION),
        "objective_configuration_fingerprint": (objective.config.configuration_fingerprint),
        "search_configuration_fingerprint": result.config.configuration_fingerprint,
        "run_fingerprint": result.run_fingerprint,
        "evaluated_seasons": list(objective.config.development_seasons),
        "evaluated_fold_count": len(objective.development_fold_ids),
        "scenario_count": objective.config.scenario_count,
        "min_history_folds": objective.config.min_history_folds,
        "tail_fraction": objective.config.tail_fraction,
        "residual_input": dict(residual_provenance),
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
    objective: ScenarioPolicyObjective,
) -> str:
    recommended = result.recommended_candidate.values
    lines = [
        "# Scenario-aware policy search (Bayesian optimization)",
        "",
        f"- Objective contract: `{SCENARIO_POLICY_OBJECTIVE_CONTRACT_VERSION}`",
        f"- Evaluated seasons: {', '.join(objective.config.development_seasons)}",
        f"- Evaluated folds: {len(objective.development_fold_ids)} "
        f"(each fold's scenarios use only strictly earlier residual folds)",
        f"- Scenarios per fold: {objective.config.scenario_count}; "
        f"tail fraction {objective.config.tail_fraction}",
        f"- Search space: {result.config.search_space_size} candidates; "
        f"evaluated {len(result.evaluations)}",
        f"- Stopped: {result.stopped_reason}",
        f"- Run fingerprint: `{result.run_fingerprint}`",
        "",
        f"**Recommended candidate**: `{result.recommended_candidate.candidate_id}` "
        f"(form_window={recommended['form_window']}, "
        f"bench_weight={recommended['bench_weight']}, "
        f"risk_aversion={recommended['risk_aversion']}) with mean realized squad "
        f"points {result.best_objective_value:.4f}.",
        "",
        "`risk_aversion` is a live axis in this search: every decision was optimized",
        "against an empirical scenario tail. This is a recommendation only — the",
        "locked holdout was not accessed, nothing was promoted, and the operational",
        "control is unchanged.",
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
    residuals_path: Path = arguments.residuals
    if not residuals_path.is_file():
        print(f"Residual history not found at {residuals_path}.")
        return 1

    residuals = pd.read_csv(residuals_path)
    residual_provenance: dict[str, object] = {
        "path": residuals_path.as_posix(),
        "table_sha256": compute_table_sha256(residuals_path),
        "rows": len(residuals),
    }
    if arguments.residuals_manifest is not None:
        manifest = _read_manifest(arguments.residuals_manifest)
        report = run_residual_export_preflight(
            residuals,
            manifest,
            table_sha256=str(residual_provenance["table_sha256"]),
            artifact_label=residuals_path.name,
        )
        print(preflight_report_to_markdown(report))
        if not report.passed:
            print("Residual preflight failed; the search will not run on this input.")
            return 1
        residual_provenance["candidate_label"] = manifest.get("candidate_label")
        residual_provenance["model_name"] = manifest.get("model_name")
        residual_provenance["model_version"] = manifest.get("model_version")
        residual_provenance["preflight_passed"] = True

    created_utc = datetime.now(UTC).isoformat(timespec="seconds")
    panel = build_panel(archive_root)
    seasons = tuple(season.strip() for season in str(arguments.seasons).split(","))
    objective_config = ScenarioPolicyObjectiveConfig(
        development_seasons=seasons,
        scenario_count=arguments.scenario_count,
        min_history_folds=arguments.min_history_folds,
    )
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
            BayesianFactor("risk_aversion", 0.0, 1.0, arguments.risk_aversion_step),
        ),
        evaluation_budget=arguments.evaluation_budget,
        initial_design_size=arguments.initial_design_size,
        deterministic_seed=arguments.deterministic_seed,
    )

    try:
        objective = ScenarioPolicyObjective(panel, residuals, objective_config)
        LOGGER.info(
            "Searching %s candidates on %s eligible folds",
            search_config.search_space_size,
            len(objective.development_fold_ids),
        )
        result = run_bayesian_optimization(
            objective,
            objective.development_fold_ids,
            search_config,
        )
    except ExperimentError as error:
        print(f"Could not run the scenario-aware policy search:\n  {error}")
        return 1

    document = {
        **artifact_metadata(panel_rows=len(panel), created_utc=created_utc),
        **_result_document(result, objective, residual_provenance),
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
