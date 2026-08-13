"""Run Sprint 5 player-adaptive risk screening on development seasons only.

    python -m scripts.run_player_risk_screening

The pinned archive must first be fetched with:

    python -m scripts.fetch_historical_data
"""

import argparse
import platform
import sys
from collections.abc import Callable
from dataclasses import asdict
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path

import pandas as pd
from scripts.run_risk_screening import (
    _git_revision,
    _json_document,
    _json_identifier,
    _optimization_config,
    _sha256,
    _write,
)

from squadopt.backtest import (
    DecisionPoint,
    build_walk_forward_folds,
    make_baseline_projection_builder,
)
from squadopt.data.sources.vaastav import ARCHIVE_COMMIT, ARCHIVE_REPOSITORY, build_panel
from squadopt.evaluation import EvaluationFold
from squadopt.prediction import (
    BASELINE_FORM_WINDOW,
    FEATURE_GENERATION_CONTRACT_VERSION,
    PredictionProvenance,
    PredictionSnapshot,
    prepare_optimizer_projection,
)
from squadopt.risk import (
    PlayerRiskScreeningConfig,
    RiskScreeningResult,
    run_player_risk_screening,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ARCHIVE_ROOT = REPOSITORY_ROOT / "data" / "raw" / "vaastav-fpl"
DEFAULT_OUTPUT_ROOT = REPOSITORY_ROOT / "artifacts" / "sprint5"
MANIFEST_PATH = REPOSITORY_ROOT / "data" / "sources" / "vaastav_fpl_manifest.json"


def _parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive-root", type=Path, default=DEFAULT_ARCHIVE_ROOT)
    parser.add_argument(
        "--json-output",
        type=Path,
        default=DEFAULT_OUTPUT_ROOT / "player_risk_screening.json",
    )
    parser.add_argument(
        "--markdown-output",
        type=Path,
        default=DEFAULT_OUTPUT_ROOT / "player_risk_screening.md",
    )
    return parser.parse_args()


def _prediction_builder(
    training_data_fingerprint: str,
) -> Callable[[pd.DataFrame, DecisionPoint], PredictionSnapshot]:
    baseline = make_baseline_projection_builder(form_window=BASELINE_FORM_WINDOW)

    def build(visible: pd.DataFrame, decision: DecisionPoint) -> PredictionSnapshot:
        table = baseline(visible, decision)
        provenance = PredictionProvenance(
            model_name="deterministic-rate-minutes-baseline",
            model_version="baseline-v1",
            feature_contract_version=FEATURE_GENERATION_CONTRACT_VERSION,
            training_cutoff=(f"{decision.season}:before-GW{decision.gameweek:02d}-outcomes"),
            training_data_fingerprint=training_data_fingerprint,
        )
        return prepare_optimizer_projection(
            table.loc[:, ["player_id", "name", "team_id", "position", "price_tenths"]],
            table.loc[:, ["player_id", "expected_points"]],
            provenance,
        )

    return build


def _prediction_provenance(folds: tuple[EvaluationFold, ...]) -> dict[str, object]:
    metadata_rows: list[dict[str, object]] = []
    for fold in folds:
        metadata = fold.metadata
        fingerprint = metadata.get("prediction_fingerprint")
        provenance_fingerprint = metadata.get("prediction_provenance_fingerprint")
        if not isinstance(fingerprint, str) or not isinstance(provenance_fingerprint, str):
            raise ValueError("Every prepared fold must carry prediction provenance.")
        metadata_rows.append(
            {
                "fold_id": fold.fold_id,
                "prediction_fingerprint": fingerprint,
                "prediction_provenance_fingerprint": provenance_fingerprint,
                "model_name": metadata.get("prediction_model_name"),
                "model_version": metadata.get("prediction_model_version"),
                "training_cutoff": metadata.get("prediction_training_cutoff"),
                "training_data_fingerprint": metadata.get("prediction_training_data_fingerprint"),
            }
        )
    return {
        "fold_count": len(metadata_rows),
        "all_folds_provenanced": len(metadata_rows) == len(folds),
        "prediction_fingerprints": metadata_rows,
    }


def _build_report(
    result: RiskScreeningResult,
    *,
    panel_rows: int,
    folds: tuple[EvaluationFold, ...],
    created_utc: str,
) -> dict[str, object]:
    revision, dirty = _git_revision()
    config = result.config
    if not isinstance(config, PlayerRiskScreeningConfig):
        raise TypeError("Sprint 5 report requires a PlayerRiskScreeningConfig.")
    return {
        "artifact_type": "sprint5_player_risk_screening",
        "created_utc": created_utc,
        "provenance": {
            "repository_commit": revision,
            "working_tree_dirty": dirty,
            "archive_repository": ARCHIVE_REPOSITORY,
            "archive_commit": ARCHIVE_COMMIT,
            "archive_manifest_sha256": _sha256(MANIFEST_PATH),
            "panel_rows": panel_rows,
            "prepared_fold_count": len(folds),
            "feature_generation_contract_version": FEATURE_GENERATION_CONTRACT_VERSION,
            "baseline_form_window": BASELINE_FORM_WINDOW,
            "risk_screening_contract_version": config.contract_version,
            "configuration_fingerprint": config.configuration_fingerprint,
            "prediction_integration": _prediction_provenance(folds),
        },
        "configuration": {
            "season_order": config.season_order,
            "risk_aversion_levels": config.risk_aversion_levels,
            "downside_quantile": config.downside_quantile,
            "uncertainty_confidence_level": config.uncertainty_confidence_level,
            "scale_training_fraction": config.scale_training_fraction,
            "min_pooled_observations": config.min_pooled_observations,
            "min_position_observations": config.min_group_observations,
            "min_player_observations": config.min_player_observations,
            "shrinkage_observations": config.shrinkage_observations,
            "minimum_scale": config.minimum_scale,
            "min_prior_gameweeks_in_season": config.min_prior_gameweeks_in_season,
            "optimization": _optimization_config(config),
        },
        "candidates": [
            {
                "candidate_id": candidate.risk_config.candidate_id,
                "risk_aversion": candidate.risk_config.risk_aversion,
                "risk_configuration_fingerprint": (candidate.risk_config.configuration_fingerprint),
                "metrics": asdict(candidate.metrics),
                "comparison": asdict(candidate.comparison),
                "folds": [
                    {
                        "fold_id": fold.fold_id,
                        "season": fold.season,
                        "gameweek": fold.gameweek,
                        "calibration_seasons": fold.calibration_seasons,
                        "calibration_fingerprint": fold.result.calibration_fingerprint,
                        "solver_status": fold.result.solver_status.value,
                        "realized_squad_points": fold.realized_squad_points,
                        "expected_points_objective_value": (
                            fold.result.expected_points_objective_value
                        ),
                        "risk_adjusted_objective_value": (
                            fold.result.risk_adjusted_objective_value
                        ),
                        "risk_penalty_value": fold.result.risk_penalty_value,
                        "selected_squad_player_ids": [
                            _json_identifier(value)
                            for value in fold.result.optimization_result.selected_squad[
                                "player_id"
                            ].tolist()
                        ],
                        "starting_xi_player_ids": [
                            _json_identifier(value)
                            for value in fold.result.optimization_result.starting_xi[
                                "player_id"
                            ].tolist()
                        ],
                        "captain_player_id": (
                            None
                            if fold.result.optimization_result.captain is None
                            else _json_identifier(
                                fold.result.optimization_result.captain["player_id"]
                            )
                        ),
                    }
                    for fold in candidate.folds
                ],
            }
            for candidate in result.candidates
        ],
        "diagnostics": dict(result.diagnostics),
        "environment": {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "pandas": pd.__version__,
            "ortools": version("ortools"),
        },
        "limitations": [
            "This is development-only diagnostic screening and performs no promotion.",
            "The 2025-26 reused benchmark season is not accessed.",
            "The current real-data run uses the deterministic baseline, not a learned model.",
            "Intervals are marginal player intervals, not joint squad confidence bounds.",
            "Player scales use finite historical residuals and deterministic shrinkage/fallback.",
            "Player dependence and cross-player correlation are not modeled.",
            "No Monte Carlo, CVaR, Gaussian Process, Bayesian Optimization, or RL is run.",
        ],
    }


def _markdown(report: dict[str, object]) -> str:
    provenance = report["provenance"]
    configuration = report["configuration"]
    candidates = report["candidates"]
    diagnostics = report["diagnostics"]
    assert isinstance(provenance, dict)
    assert isinstance(configuration, dict)
    assert isinstance(candidates, list)
    assert isinstance(diagnostics, dict)

    def number(value: object) -> str:
        return "n/a" if value is None else f"{float(value):.6f}"

    lines = [
        "# Sprint 5 player-adaptive risk screening",
        "",
        (
            "Generated by `python -m scripts.run_player_risk_screening` at "
            f"`{report['created_utc']}`."
        ),
        "",
        "## Provenance",
        "",
        f"- Repository commit: `{provenance['repository_commit']}`",
        f"- Working tree dirty: `{str(provenance['working_tree_dirty']).lower()}`",
        f"- Archive: `{provenance['archive_repository']}@{provenance['archive_commit']}`",
        f"- Feature contract: `{provenance['feature_generation_contract_version']}`",
        f"- Screening fingerprint: `{provenance['configuration_fingerprint']}`",
        "",
        "## Leakage boundary",
        "",
        f"- Calibration policy: `{diagnostics['calibration_policy']}`",
        f"- Calibration split: `{diagnostics['calibration_split']}`",
        f"- Evaluation seasons: `{', '.join(diagnostics['evaluation_seasons'])}`",
        f"- Reused 2025-26 benchmark accessed: `{str(diagnostics['holdout_accessed']).lower()}`",
        f"- Promotion performed: `{str(diagnostics['promotion_performed']).lower()}`",
        "",
        "## Adaptive uncertainty controls",
        "",
        f"- Scale-training fraction: `{configuration['scale_training_fraction']}`",
        f"- Minimum player observations: `{configuration['min_player_observations']}`",
        f"- Shrinkage observations: `{configuration['shrinkage_observations']}`",
        f"- Minimum scale: `{configuration['minimum_scale']}`",
        "",
        "## Candidate metrics",
        "",
        (
            "| Risk aversion | Folds | Feasibility | Mean score | Stddev | Downside quantile | "
            "Mean worst fraction | Mean vs control | Mean penalty | Squad/XI/captain changes |"
        ),
        "| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for candidate in candidates:
        assert isinstance(candidate, dict)
        metrics = candidate["metrics"]
        comparison = candidate["comparison"]
        assert isinstance(metrics, dict)
        assert isinstance(comparison, dict)
        lines.append(
            f"| {float(candidate['risk_aversion']):.2f} | {metrics['attempted_folds']} | "
            f"{float(metrics['feasibility_rate']):.6f} | "
            f"{number(metrics['mean_realized_squad_points'])} | "
            f"{number(metrics['realized_squad_points_stddev'])} | "
            f"{number(metrics['downside_quantile_score'])} | "
            f"{number(metrics['mean_worst_fraction_score'])} | "
            f"{number(comparison['mean_difference'])} | "
            f"{number(metrics['mean_risk_penalty_value'])} | "
            f"{comparison['squad_changed_folds']}/"
            f"{comparison['starting_xi_changed_folds']}/"
            f"{comparison['captain_changed_folds']} |"
        )
    lines.extend(["", "## Limitations", ""])
    lines.extend(f"- {item}" for item in report["limitations"])
    return "\n".join(lines) + "\n"


def main() -> int:
    """Run the pre-registered Sprint 5 development-only screening."""

    arguments = _parse_arguments()
    if not arguments.archive_root.is_dir():
        print(
            f"Archive not found at {arguments.archive_root}.\n"
            "Run 'python -m scripts.fetch_historical_data' first."
        )
        return 1

    config = PlayerRiskScreeningConfig()
    panel = build_panel(arguments.archive_root, seasons=config.season_order)
    manifest_fingerprint = _sha256(MANIFEST_PATH)
    folds = build_walk_forward_folds(
        panel,
        seasons=config.season_order,
        min_prior_gameweeks_in_season=config.min_prior_gameweeks_in_season,
        projection_builder=_prediction_builder(manifest_fingerprint),
    )
    result = run_player_risk_screening(folds, config)
    report = _build_report(
        result,
        panel_rows=len(panel),
        folds=folds,
        created_utc=datetime.now(UTC).isoformat(timespec="seconds"),
    )
    markdown = _markdown(report)
    _write(arguments.json_output, _json_document(report))
    _write(arguments.markdown_output, markdown)
    print(markdown)
    print(f"JSON: {arguments.json_output}")
    print(f"Markdown: {arguments.markdown_output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
