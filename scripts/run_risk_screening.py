"""Run the Sprint 4 expanding-season conformal risk screening.

    python -m scripts.run_risk_screening

The pinned archive must first be fetched with:

    python -m scripts.fetch_historical_data
"""

import argparse
import hashlib
import json
import platform
import subprocess
import sys
from dataclasses import asdict
from datetime import UTC, datetime
from importlib.metadata import version
from numbers import Integral, Real
from pathlib import Path

import pandas as pd

from squadopt.backtest import build_walk_forward_folds, make_baseline_projection_builder
from squadopt.data.sources.vaastav import ARCHIVE_COMMIT, ARCHIVE_REPOSITORY, build_panel
from squadopt.prediction import BASELINE_FORM_WINDOW, FEATURE_GENERATION_CONTRACT_VERSION
from squadopt.risk import RiskScreeningConfig, RiskScreeningResult, run_risk_screening
from squadopt.uncertainty import (
    OPERATIONAL_UNCERTAINTY_GROUPING,
    UNCERTAINTY_GROUPINGS,
    attach_fixture_counts_to_folds,
    calendar_from_archive,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ARCHIVE_ROOT = REPOSITORY_ROOT / "data" / "raw" / "vaastav-fpl"
DEFAULT_OUTPUT_ROOT = REPOSITORY_ROOT / "artifacts" / "sprint4"
MANIFEST_PATH = REPOSITORY_ROOT / "data" / "sources" / "vaastav_fpl_manifest.json"


def _parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive-root", type=Path, default=DEFAULT_ARCHIVE_ROOT)
    parser.add_argument(
        "--uncertainty-grouping",
        choices=UNCERTAINTY_GROUPINGS,
        default=OPERATIONAL_UNCERTAINTY_GROUPING,
        help="conformal grouping for the intervals: position (v1) or position_fixture_group "
        "(v2, the operational default; the calendar is attached to every fold)",
    )
    parser.add_argument(
        "--json-output",
        type=Path,
        default=DEFAULT_OUTPUT_ROOT / "risk_screening.json",
    )
    parser.add_argument(
        "--markdown-output",
        type=Path,
        default=DEFAULT_OUTPUT_ROOT / "risk_screening.md",
    )
    return parser.parse_args()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1 << 20):
            digest.update(chunk)
    return digest.hexdigest()


def _git_revision() -> tuple[str, bool]:
    try:
        revision = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPOSITORY_ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        dirty = bool(
            subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=REPOSITORY_ROOT,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
        )
    except (OSError, subprocess.CalledProcessError) as error:
        raise SystemExit(f"Cannot record repository revision: {error}") from error
    return revision, dirty


def _optimization_config(config: RiskScreeningConfig) -> dict[str, object]:
    optimization = config.optimization_config
    return {
        "budget_tenths": optimization.budget_tenths,
        "squad_size": optimization.squad_size,
        "squad_position_limits": dict(optimization.squad_position_limits),
        "starting_size": optimization.starting_size,
        "starting_position_min": dict(optimization.starting_position_min),
        "starting_position_max": dict(optimization.starting_position_max),
        "max_players_per_team": optimization.max_players_per_team,
        "bench_weight": optimization.bench_weight,
        "expected_points_scale": optimization.expected_points_scale,
        "solver_time_limit_seconds": optimization.solver_time_limit_seconds,
        "solver_deterministic_time_limit": optimization.solver_deterministic_time_limit,
        "deterministic_seed": optimization.deterministic_seed,
    }


def _json_identifier(value: object) -> int | str:
    if isinstance(value, Integral) and not isinstance(value, bool):
        return int(value)
    return str(value)


def _json_default(value: object) -> int | float:
    """Convert supported numeric scalar implementations to JSON-native values."""

    if isinstance(value, Integral) and not isinstance(value, bool):
        return int(value)
    if isinstance(value, Real) and not isinstance(value, bool):
        return float(value)
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def _json_document(report: dict[str, object]) -> str:
    """Serialize one report as strict, deterministic JSON."""

    return (
        json.dumps(
            report,
            indent=2,
            sort_keys=True,
            allow_nan=False,
            default=_json_default,
        )
        + "\n"
    )


def _build_report(
    result: RiskScreeningResult,
    *,
    panel_rows: int,
    prepared_fold_count: int,
    created_utc: str,
) -> dict[str, object]:
    revision, dirty = _git_revision()
    return {
        "artifact_type": "sprint4_risk_screening",
        "created_utc": created_utc,
        "provenance": {
            "repository_commit": revision,
            "working_tree_dirty": dirty,
            "archive_repository": ARCHIVE_REPOSITORY,
            "archive_commit": ARCHIVE_COMMIT,
            "archive_manifest_sha256": _sha256(MANIFEST_PATH),
            "panel_rows": panel_rows,
            "prepared_fold_count": prepared_fold_count,
            "feature_generation_contract_version": FEATURE_GENERATION_CONTRACT_VERSION,
            "baseline_form_window": BASELINE_FORM_WINDOW,
            "risk_screening_contract_version": result.config.contract_version,
            "configuration_fingerprint": result.config.configuration_fingerprint,
        },
        "configuration": {
            "season_order": result.config.season_order,
            "risk_aversion_levels": result.config.risk_aversion_levels,
            "downside_quantile": result.config.downside_quantile,
            "uncertainty_confidence_level": result.config.uncertainty_confidence_level,
            "min_pooled_observations": result.config.min_pooled_observations,
            "min_group_observations": result.config.min_group_observations,
            "min_prior_gameweeks_in_season": result.config.min_prior_gameweeks_in_season,
            "optimization": _optimization_config(result.config),
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
                        "selected_squad_player_ids": (
                            [
                                _json_identifier(value)
                                for value in fold.result.optimization_result.selected_squad[
                                    "player_id"
                                ].tolist()
                            ]
                        ),
                        "starting_xi_player_ids": (
                            [
                                _json_identifier(value)
                                for value in fold.result.optimization_result.starting_xi[
                                    "player_id"
                                ].tolist()
                            ]
                        ),
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
            "Conformal interval radii are position-level, not player-specific.",
            "Player dependence and cross-player correlation are not modeled.",
            "The lower-bound blend is not a portfolio confidence bound or CVaR objective.",
            "No Monte Carlo, Gaussian Process, Bayesian Optimization, or transfer planning is run.",
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
        "# Sprint 4 conformal risk screening",
        "",
        f"Generated at `{report['created_utc']}` by `python -m scripts.run_risk_screening`.",
        "",
        "## Provenance",
        "",
        f"- Repository commit: `{provenance['repository_commit']}`",
        f"- Working tree dirty: `{str(provenance['working_tree_dirty']).lower()}`",
        f"- Archive: `{provenance['archive_repository']}@{provenance['archive_commit']}`",
        f"- Feature contract: `{provenance['feature_generation_contract_version']}`",
        f"- Baseline form window: `{provenance['baseline_form_window']}`",
        f"- Screening fingerprint: `{provenance['configuration_fingerprint']}`",
        "",
        "## Leakage boundary",
        "",
        f"- Calibration policy: `{diagnostics['calibration_policy']}`",
        f"- Seed season: `{diagnostics['seed_season']}`",
        f"- Evaluation seasons: `{', '.join(diagnostics['evaluation_seasons'])}`",
        f"- Reused 2025-26 benchmark accessed: `{str(diagnostics['holdout_accessed']).lower()}`",
        f"- Promotion performed: `{str(diagnostics['promotion_performed']).lower()}`",
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


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def main() -> int:
    """Run the pre-registered development-only Sprint 4 screening."""

    arguments = _parse_arguments()
    if not arguments.archive_root.is_dir():
        print(
            f"Archive not found at {arguments.archive_root}.\n"
            "Run 'python -m scripts.fetch_historical_data' first."
        )
        return 1

    config = RiskScreeningConfig(uncertainty_grouping=str(arguments.uncertainty_grouping))
    panel = build_panel(arguments.archive_root)
    folds = build_walk_forward_folds(
        panel,
        seasons=config.season_order,
        min_prior_gameweeks_in_season=config.min_prior_gameweeks_in_season,
        projection_builder=make_baseline_projection_builder(form_window=BASELINE_FORM_WINDOW),
    )
    if config.uncertainty_grouping == "position_fixture_group":
        folds = attach_fixture_counts_to_folds(
            folds, calendar_from_archive(arguments.archive_root, config.season_order)
        )
    result = run_risk_screening(folds, config)
    report = _build_report(
        result,
        panel_rows=len(panel),
        prepared_fold_count=len(folds),
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
