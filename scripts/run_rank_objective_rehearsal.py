"""Rehearse the rank-probability objective against a template rival on real folds.

    python -m scripts.run_rank_objective_rehearsal \\
        --residuals artifacts/residuals-verify/control_residuals.csv \\
        --residuals-manifest artifacts/residuals-verify/control_residuals.manifest.json

Per fold the risk-neutral squad is the template rival; the rank objective picks the
squad most likely to finish ahead of it at each expected-points budget; the claimed
probability is compared with the realized frequency of actually finishing ahead. This is
the first evidence for the goal-based recommender: does "P(ahead) = 0.6" mean anything?
Measurement only; the locked holdout is never read.
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

from squadopt.data.sources.vaastav import build_panel
from squadopt.experiments import (
    RANK_REHEARSAL_CONTRACT_VERSION,
    ExperimentError,
    RankRehearsalResult,
    ScenarioPolicyObjective,
    ScenarioPolicyObjectiveConfig,
    rehearse_rank_objective,
)
from squadopt.optimization import OptimizationConfig
from squadopt.preflight import (
    compute_table_sha256,
    preflight_report_to_markdown,
    run_residual_export_preflight,
)
from squadopt.scenarios import CLAIM_SCENARIO_MODES

LOGGER = logging.getLogger(__name__)


def _parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive-root", type=Path, default=DEFAULT_ARCHIVE_ROOT)
    parser.add_argument("--residuals", type=Path, required=True)
    parser.add_argument("--residuals-manifest", type=Path)
    parser.add_argument("--seasons", default="2024-25")
    parser.add_argument("--scenario-count", type=int, default=100)
    parser.add_argument("--min-history-folds", type=int, default=8)
    parser.add_argument("--candidate-pool-per-position", type=int, default=20)
    parser.add_argument("--cheap-pool-per-position", type=int, default=8)
    parser.add_argument("--form-window", type=int, default=6)
    parser.add_argument("--bench-weight", type=float, default=0.0)
    parser.add_argument("--budgets", default="0,2,4,none", help="expected-points budgets")
    parser.add_argument("--margin-points", type=float, default=0.0)
    parser.add_argument("--max-folds", type=int, default=None, help="smoke: first N folds only")
    parser.add_argument(
        "--claim-scenarios",
        choices=CLAIM_SCENARIO_MODES,
        default="held_out_half",
        help="in_sample: report the probability on the scenarios the squad was chosen on; "
        "held_out_half: choose on the first half, report on the second half it never saw",
    )
    parser.add_argument("--solver-time-limit", type=float, default=30.0)
    parser.add_argument("--deterministic-time-limit", type=float, default=None)
    parser.add_argument(
        "--json-output",
        type=Path,
        default=REPOSITORY_ROOT / "docs" / "rank_objective_rehearsal.json",
    )
    parser.add_argument(
        "--markdown-output",
        type=Path,
        default=REPOSITORY_ROOT / "docs" / "rank_objective_rehearsal.md",
    )
    return parser.parse_args()


def _budgets(text: str) -> tuple[float | None, ...]:
    out: list[float | None] = []
    for token in str(text).split(","):
        token = token.strip().lower()
        out.append(None if token in {"none", ""} else float(token))
    return tuple(out)


def _markdown(result: RankRehearsalResult, provenance: Mapping[str, object]) -> str:
    lines = [
        "# Rank-probability objective rehearsal (template rival)",
        "",
        f"- Contract: `{RANK_REHEARSAL_CONTRACT_VERSION}`; folds: "
        f"{result.diagnostics['fold_count']}; scenarios/fold: "
        f"{result.diagnostics['scenario_count']}; anchor form_window="
        f"{result.diagnostics['form_window']}, bench_weight={result.diagnostics['bench_weight']}"
        f"; claim scenarios: {result.diagnostics['claim_scenarios']}",
        "- Rival: the fold's own risk-neutral squad (template). Claimed = the optimizer's "
        "reported probability of finishing ahead (in-sample = on the scenarios it was chosen "
        "on); realized = share of folds it actually did; level = ended equal.",
        "",
        "| Budget (xP) | Folds | Claimed P(ahead) | In-sample | Realized ahead [90%] | Level | "
        "Expected cost | Realized cost | Starters changed | Captain changed | Proven |",
        "| ---: | ---: | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for s in result.summaries:
        low, high = s.realized_ahead_interval
        budget = "none" if s.expected_points_budget is None else f"{s.expected_points_budget:g}"
        lines.append(
            f"| {budget} | {s.folds} | {s.mean_claimed_probability:.2f} "
            f"| {s.mean_selection_probability:.2f} "
            f"| {s.realized_ahead_frequency:.2f} [{low:.2f}, {high:.2f}] "
            f"| {s.realized_level_share:.2f} "
            f"| {s.mean_expected_cost:+.2f} | {s.mean_realized_cost:+.2f} "
            f"| {s.mean_starters_changed:.1f} | {s.captain_changed_share:.2f} "
            f"| {s.proven_share:.2f} |"
        )
    lines += [
        "",
        f"Residual input: `{provenance.get('candidate_label')}` "
        f"(`{str(provenance.get('table_sha256'))[:16]}…`). Measurement only; the locked "
        "holdout was not read.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    arguments = _parse_arguments()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    if not arguments.archive_root.is_dir():
        print(f"Archive not found at {arguments.archive_root}.")
        return 1
    if not arguments.residuals.is_file():
        print(f"Residual history not found at {arguments.residuals}.")
        return 1
    residuals = pd.read_csv(arguments.residuals)
    provenance: dict[str, object] = {
        "path": arguments.residuals.as_posix(),
        "table_sha256": compute_table_sha256(arguments.residuals),
        "rows": len(residuals),
    }
    if arguments.residuals_manifest is not None:
        manifest = json.loads(arguments.residuals_manifest.read_text(encoding="utf-8"))
        report = run_residual_export_preflight(
            residuals,
            manifest,
            table_sha256=str(provenance["table_sha256"]),
            artifact_label=arguments.residuals.name,
        )
        print(preflight_report_to_markdown(report))
        if not report.passed:
            print("Residual preflight failed; the rehearsal will not run on this input.")
            return 1
        provenance["candidate_label"] = manifest.get("candidate_label")
        provenance["preflight_passed"] = True

    created_utc = datetime.now(UTC).isoformat(timespec="seconds")
    panel = build_panel(arguments.archive_root)
    seasons = tuple(s.strip() for s in str(arguments.seasons).split(","))
    optimization = OptimizationConfig(
        solver_time_limit_seconds=arguments.solver_time_limit,
        solver_deterministic_time_limit=arguments.deterministic_time_limit,
    )
    try:
        objective = ScenarioPolicyObjective(
            panel,
            residuals,
            ScenarioPolicyObjectiveConfig(
                development_seasons=seasons,
                scenario_count=arguments.scenario_count,
                min_history_folds=arguments.min_history_folds,
                candidate_pool_per_position=arguments.candidate_pool_per_position,
                cheap_pool_per_position=arguments.cheap_pool_per_position,
            ),
        )
        LOGGER.info(
            "Rehearsing the rank objective on %s folds", len(objective.development_fold_ids)
        )
        result = rehearse_rank_objective(
            objective,
            residuals,
            form_window=arguments.form_window,
            bench_weight=arguments.bench_weight,
            budgets=_budgets(arguments.budgets),
            margin_points=arguments.margin_points,
            claim_scenarios=str(arguments.claim_scenarios),
            optimization_config=optimization,
            max_folds=arguments.max_folds,
        )
    except ExperimentError as error:
        print(f"Could not rehearse the rank objective:\n  {error}")
        return 1
    document = {
        **artifact_metadata(panel_rows=len(panel), created_utc=created_utc),
        "contract_version": RANK_REHEARSAL_CONTRACT_VERSION,
        "summaries": [
            {
                "expected_points_budget": s.expected_points_budget,
                "folds": s.folds,
                "mean_claimed_probability": s.mean_claimed_probability,
                "mean_selection_probability": s.mean_selection_probability,
                "realized_ahead_frequency": s.realized_ahead_frequency,
                "realized_ahead_interval": list(s.realized_ahead_interval),
                "realized_level_share": s.realized_level_share,
                "mean_expected_cost": s.mean_expected_cost,
                "mean_realized_cost": s.mean_realized_cost,
                "mean_starters_changed": s.mean_starters_changed,
                "captain_changed_share": s.captain_changed_share,
                "proven_share": s.proven_share,
            }
            for s in result.summaries
        ],
        "rows": [
            {
                "fold_id": r.fold_id,
                "expected_points_budget": r.expected_points_budget,
                "claimed_probability_ahead": r.claimed_probability_ahead,
                "selection_probability_ahead": r.selection_probability_ahead,
                "scenario_mean_score": r.scenario_mean_score,
                "template_scenario_mean_score": r.template_scenario_mean_score,
                "realized_score": r.realized_score,
                "template_realized_score": r.template_realized_score,
                "realized_ahead": r.realized_ahead,
                "realized_level": r.realized_level,
                "starters_changed": r.starters_changed,
                "captain_changed": r.captain_changed,
                "solver_status": r.solver_status,
            }
            for r in result.rows
        ],
        "residual_input": provenance,
        "diagnostics": dict(result.diagnostics),
        "measurement_only": True,
        "locked_holdout_accessed": False,
    }
    markdown = _markdown(result, provenance)
    write_json(arguments.json_output, document)
    write_text(arguments.markdown_output, markdown)
    print(markdown)
    print(f"Wrote {arguments.json_output}")
    print(f"Wrote {arguments.markdown_output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
