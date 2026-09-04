"""Measure the mean-versus-downside frontier over a risk-aversion ladder.

    python -m scripts.run_risk_frontier \
        --residuals artifacts/residuals/control_residuals.csv \
        --residuals-manifest artifacts/residuals/control_residuals.manifest.json \
        --form-window 6 --bench-weight 0.0

One fixed policy anchor is evaluated at every risk-aversion level on identical folds
with identical scenarios, so differences between frontier points are attributable to
`risk_aversion` alone. The report answers, in numbers, whether the mean premium risk
aversion pays buys any floor: lower quantile, worst-tail mean, and the probability of
a bad week, per level.

When a manifest is supplied, the residual input is validated by the artifact
preflight before anything runs. The run is measurement only: no locked-holdout
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

from squadopt.data.sources.vaastav import build_panel
from squadopt.experiments import (
    RISK_FRONTIER_CONTRACT_VERSION,
    ExperimentError,
    RiskFrontierResult,
    ScenarioPolicyObjective,
    ScenarioPolicyObjectiveConfig,
    measure_risk_frontier,
)
from squadopt.preflight import (
    compute_table_sha256,
    preflight_report_to_markdown,
    run_residual_export_preflight,
)

LOGGER = logging.getLogger(__name__)
DEFAULT_LEVELS = "0.0,0.1,0.2,0.3,0.4,0.5,0.6,0.7,0.8,0.9,1.0"


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
    parser.add_argument("--projection-shrinkage", type=float, default=0.0)
    parser.add_argument("--risk-aversion-levels", default=DEFAULT_LEVELS)
    parser.add_argument("--lower-quantile", type=float, default=0.10)
    parser.add_argument("--worst-fraction", type=float, default=0.10)
    parser.add_argument("--points-threshold", type=float, default=40.0)
    parser.add_argument(
        "--json-output",
        type=Path,
        default=REPOSITORY_ROOT / "docs" / "risk_frontier.json",
    )
    parser.add_argument(
        "--markdown-output",
        type=Path,
        default=REPOSITORY_ROOT / "docs" / "risk_frontier.md",
    )
    return parser.parse_args()


def _frontier_document(
    frontier: RiskFrontierResult,
    objective: ScenarioPolicyObjective,
    residual_provenance: Mapping[str, object],
) -> dict[str, object]:
    neutral = frontier.risk_neutral
    return {
        "contract_version": RISK_FRONTIER_CONTRACT_VERSION,
        "objective_configuration_fingerprint": (frontier.objective_configuration_fingerprint),
        "anchor": {
            "form_window": frontier.form_window,
            "bench_weight": frontier.bench_weight,
        },
        "evaluated_seasons": list(objective.config.development_seasons),
        "evaluated_fold_count": len(objective.development_fold_ids),
        "scenario_count": objective.config.scenario_count,
        "lower_quantile": frontier.lower_quantile,
        "worst_fraction": frontier.worst_fraction,
        "points_threshold": frontier.points_threshold,
        "residual_input": dict(residual_provenance),
        "reproducibility_note": (
            "Per-fold scenario solves stop at a wall-clock cap, not a deterministic "
            "work budget; the frontier is recommendation-quality measurement, not a "
            "formal reproducible benchmark."
        ),
        "recommendation_only": True,
        "locked_holdout_accessed": False,
        "automatic_promotion": False,
        "frontier": [
            {
                "risk_aversion": point.risk_aversion,
                "mean_realized_squad_points": point.mean_realized_squad_points,
                "realized_stddev": point.realized_stddev,
                "lower_quantile_score": point.lower_quantile_score,
                "worst_tail_mean_score": point.worst_tail_mean_score,
                "probability_below_threshold": point.probability_below_threshold,
                "mean_premium_vs_risk_neutral": (
                    neutral.mean_realized_squad_points - point.mean_realized_squad_points
                ),
                "lower_quantile_gain_vs_risk_neutral": (
                    point.lower_quantile_score - neutral.lower_quantile_score
                ),
                "scored_folds": point.scored_folds,
            }
            for point in frontier.points
        ],
    }


def _frontier_markdown(
    frontier: RiskFrontierResult,
    objective: ScenarioPolicyObjective,
) -> str:
    neutral = frontier.risk_neutral
    lines = [
        "# Risk-aversion frontier (mean versus downside)",
        "",
        f"- Contract: `{RISK_FRONTIER_CONTRACT_VERSION}`",
        f"- Anchor policy: form_window={frontier.form_window}, "
        f"bench_weight={frontier.bench_weight}",
        f"- Evaluated seasons: {', '.join(objective.config.development_seasons)}; "
        f"{len(objective.development_fold_ids)} folds",
        f"- Scenarios per fold: {objective.config.scenario_count}",
        f"- Downside metrics: lower {frontier.lower_quantile:.0%} quantile, "
        f"worst {frontier.worst_fraction:.0%} tail mean, "
        f"P(score < {frontier.points_threshold:g})",
        "- Per-fold solves stop at a wall-clock cap; this is recommendation-quality "
        "measurement, not a formal benchmark",
        "",
        "Each row answers: what does this risk-aversion level pay in mean points, and",
        "what floor does it buy in return, against the risk-neutral baseline?",
        "",
        "| risk_aversion | Mean | Stddev | Lower q | Worst-tail mean | P(bad week) "
        "| Mean premium | Floor gain |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for point in frontier.points:
        premium = neutral.mean_realized_squad_points - point.mean_realized_squad_points
        floor_gain = point.lower_quantile_score - neutral.lower_quantile_score
        lines.append(
            f"| {point.risk_aversion:.1f} | {point.mean_realized_squad_points:.2f} "
            f"| {point.realized_stddev:.2f} | {point.lower_quantile_score:.2f} "
            f"| {point.worst_tail_mean_score:.2f} "
            f"| {point.probability_below_threshold:.2f} "
            f"| {premium:+.2f} | {floor_gain:+.2f} |"
        )
    lines += [
        "",
        "Measurement only: the locked holdout was not accessed, nothing was promoted,",
        "and the operational control is unchanged.",
    ]
    return "\n".join(lines) + "\n"


def main() -> int:
    arguments = _parse_arguments()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    archive_root: Path = arguments.archive_root
    if not archive_root.is_dir():
        print(f"Archive not found at {archive_root}.")
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
        manifest = json.loads(arguments.residuals_manifest.read_text(encoding="utf-8"))
        if not isinstance(manifest, dict):
            print(f"Manifest {arguments.residuals_manifest} must contain a JSON object.")
            return 1
        report = run_residual_export_preflight(
            residuals,
            manifest,
            table_sha256=str(residual_provenance["table_sha256"]),
            artifact_label=residuals_path.name,
        )
        print(preflight_report_to_markdown(report))
        if not report.passed:
            print("Residual preflight failed; the frontier will not run on this input.")
            return 1
        residual_provenance["candidate_label"] = manifest.get("candidate_label")
        residual_provenance["preflight_passed"] = True

    created_utc = datetime.now(UTC).isoformat(timespec="seconds")
    panel = build_panel(archive_root)
    seasons = tuple(season.strip() for season in str(arguments.seasons).split(","))
    levels = tuple(float(level.strip()) for level in str(arguments.risk_aversion_levels).split(","))

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
                projection_shrinkage=arguments.projection_shrinkage,
            ),
        )
        LOGGER.info(
            "Measuring %s risk-aversion levels on %s folds",
            len(levels),
            len(objective.development_fold_ids),
        )
        frontier = measure_risk_frontier(
            objective,
            form_window=arguments.form_window,
            bench_weight=arguments.bench_weight,
            risk_aversion_levels=levels,
            lower_quantile=arguments.lower_quantile,
            worst_fraction=arguments.worst_fraction,
            points_threshold=arguments.points_threshold,
        )
    except ExperimentError as error:
        print(f"Could not measure the risk frontier:\n  {error}")
        return 1

    document = {
        **artifact_metadata(panel_rows=len(panel), created_utc=created_utc),
        **_frontier_document(frontier, objective, residual_provenance),
    }
    markdown = _frontier_markdown(frontier, objective)
    write_json(arguments.json_output, document)
    write_text(arguments.markdown_output, markdown)

    print(markdown)
    print(f"Wrote {arguments.json_output}")
    print(f"Wrote {arguments.markdown_output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
