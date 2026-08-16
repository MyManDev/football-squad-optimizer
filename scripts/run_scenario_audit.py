"""Audit scenario calibration against realized outcomes on real folds.

    python -m scripts.run_scenario_audit \
        --residuals artifacts/residuals/control_residuals.csv \
        --residuals-manifest artifacts/residuals/control_residuals.manifest.json

For each eligible fold the risk-neutral deterministic squad is frozen, its scenario
score distribution is generated from strictly earlier residual folds, and the realized
score is compared against that distribution. If the scenarios are honest, PIT values
are uniform, about 10% of realized scores fall below the scenario q10, and the
scenario-implied bad-week probability matches the bad-week frequency. The audit
measures; it does not repair, reweight, or decide.
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
    SCENARIO_AUDIT_CONTRACT_VERSION,
    ExperimentError,
    ScenarioAuditResult,
    ScenarioPolicyObjective,
    ScenarioPolicyObjectiveConfig,
    audit_scenario_calibration,
)
from squadopt.preflight import (
    compute_table_sha256,
    preflight_report_to_markdown,
    run_residual_export_preflight,
)

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
    parser.add_argument(
        "--player-location-shrinkage",
        type=float,
        default=None,
        help="Opt-in per-player location component; omitted keeps centered scenarios.",
    )
    parser.add_argument("--lower-quantile", type=float, default=0.10)
    parser.add_argument("--points-threshold", type=float, default=40.0)
    parser.add_argument(
        "--json-output",
        type=Path,
        default=REPOSITORY_ROOT / "docs" / "scenario_calibration_audit.json",
    )
    parser.add_argument(
        "--markdown-output",
        type=Path,
        default=REPOSITORY_ROOT / "docs" / "scenario_calibration_audit.md",
    )
    return parser.parse_args()


def _document(
    audit: ScenarioAuditResult,
    residual_provenance: Mapping[str, object],
) -> dict[str, object]:
    return {
        "contract_version": SCENARIO_AUDIT_CONTRACT_VERSION,
        "lower_quantile": audit.lower_quantile,
        "points_threshold": audit.points_threshold,
        "decision_level": {
            "fold_count": len(audit.rows),
            "realized_below_scenario_quantile_rate": (audit.realized_below_scenario_quantile_rate),
            "target_rate": audit.lower_quantile,
            "mean_pit": audit.mean_pit,
            "pit_below_10_rate": audit.pit_below_10_rate,
            "pit_above_90_rate": audit.pit_above_90_rate,
            "mean_score_bias": audit.mean_score_bias,
            "predicted_bad_week_probability": audit.predicted_bad_week_probability,
            "realized_bad_week_frequency": audit.realized_bad_week_frequency,
        },
        "player_level": {
            "interval_nominal": audit.player_interval_nominal,
            "coverage_by_position": dict(audit.player_interval_coverage),
        },
        "rows": [
            {
                "fold_id": row.fold_id,
                "realized_score": row.realized_score,
                "scenario_mean_score": row.scenario_mean_score,
                "scenario_lower_quantile_score": row.scenario_lower_quantile_score,
                "probability_below_threshold": row.probability_below_threshold,
                "probability_integral_transform": row.probability_integral_transform,
            }
            for row in audit.rows
        ],
        "residual_input": dict(residual_provenance),
        "diagnostics": dict(audit.diagnostics),
        "measurement_only": True,
        "locked_holdout_accessed": False,
    }


def _markdown(audit: ScenarioAuditResult) -> str:
    lines = [
        "# Scenario calibration audit",
        "",
        f"- Contract: `{SCENARIO_AUDIT_CONTRACT_VERSION}`",
        f"- Folds: {len(audit.rows)}; decision rule: frozen risk-neutral squad "
        "(scenarios never influence the decision)",
        f"- Anchor: form_window={audit.diagnostics['form_window']}, "
        f"bench_weight={audit.diagnostics['bench_weight']}; "
        f"{audit.diagnostics['scenario_count']} scenarios/fold",
        "",
        "## Decision-level calibration",
        "",
        "| Question | Scenario claim | Reality | Verdict basis |",
        "| --- | ---: | ---: | --- |",
        f"| Realized below scenario q{audit.lower_quantile:.0%} "
        f"| {audit.lower_quantile:.2f} "
        f"| {audit.realized_below_scenario_quantile_rate:.2f} "
        "| calibrated if close |",
        f"| Mean PIT (uniform target 0.50) | 0.50 | {audit.mean_pit:.2f} | bias if far from 0.5 |",
        f"| PIT < 0.10 rate | 0.10 | {audit.pit_below_10_rate:.2f} | lower-tail honesty |",
        f"| PIT > 0.90 rate | 0.10 | {audit.pit_above_90_rate:.2f} | upper-tail honesty |",
        f"| Bad week P(score < {audit.points_threshold:g}) "
        f"| {audit.predicted_bad_week_probability:.2f} "
        f"| {audit.realized_bad_week_frequency:.2f} "
        "| reliability |",
        f"| Scenario mean minus realized | 0.00 | {audit.mean_score_bias:+.2f} | location bias |",
        "",
        f"## Player-level interval coverage (nominal {audit.player_interval_nominal:.0%})",
        "",
        "| Position | Coverage |",
        "| --- | ---: |",
    ]
    for position, coverage in audit.player_interval_coverage.items():
        lines.append(f"| {position} | {coverage:.3f} |")
    lines += [
        "",
        "Measurement only: nothing was repaired, reweighted, promoted, or read from",
        "the locked holdout.",
    ]
    return "\n".join(lines) + "\n"


def main() -> int:
    arguments = _parse_arguments()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    if not arguments.archive_root.is_dir():
        print(f"Archive not found at {arguments.archive_root}.")
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
            print("Residual preflight failed; the audit will not run on this input.")
            return 1
        residual_provenance["candidate_label"] = manifest.get("candidate_label")
        residual_provenance["preflight_passed"] = True

    created_utc = datetime.now(UTC).isoformat(timespec="seconds")
    panel = build_panel(arguments.archive_root)
    seasons = tuple(season.strip() for season in str(arguments.seasons).split(","))

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
                player_location_shrinkage=arguments.player_location_shrinkage,
            ),
        )
        LOGGER.info(
            "Auditing scenario calibration on %s folds",
            len(objective.development_fold_ids),
        )
        audit = audit_scenario_calibration(
            objective,
            residuals,
            form_window=arguments.form_window,
            bench_weight=arguments.bench_weight,
            lower_quantile=arguments.lower_quantile,
            points_threshold=arguments.points_threshold,
        )
    except ExperimentError as error:
        print(f"Could not audit scenario calibration:\n  {error}")
        return 1

    document = {
        **artifact_metadata(panel_rows=len(panel), created_utc=created_utc),
        **_document(audit, residual_provenance),
    }
    markdown = _markdown(audit)
    write_json(arguments.json_output, document)
    write_text(arguments.markdown_output, markdown)
    print(markdown)
    print(f"Wrote {arguments.json_output}")
    print(f"Wrote {arguments.markdown_output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
