"""Deterministic JSON and Markdown reports for recalibration measurements."""

from dataclasses import asdict

from squadopt.recalibration.models import (
    CALENDAR_RECALIBRATION_ARTIFACT_TYPE,
    CALENDAR_RECALIBRATION_REPORT_SCHEMA_VERSION,
    TIME_AWARE_RECALIBRATION_ARTIFACT_TYPE,
    TIME_AWARE_RECALIBRATION_REPORT_SCHEMA_VERSION,
    CalendarRecalibrationResult,
    TimeAwareRecalibrationResult,
)


def recalibration_to_dict(result: CalendarRecalibrationResult) -> dict[str, object]:
    """Return a JSON-serialisable measurement artifact."""

    return {
        "artifact_type": CALENDAR_RECALIBRATION_ARTIFACT_TYPE,
        "report_schema_version": CALENDAR_RECALIBRATION_REPORT_SCHEMA_VERSION,
        "contract_version": result.config.contract_version,
        "measurement_fingerprint": result.measurement_fingerprint,
        "configuration": {
            "reference_candidate": result.config.reference_candidate,
            "candidate": result.config.candidate,
        },
        "diagnostics": dict(result.diagnostics),
        "comparisons": [asdict(comparison) for comparison in result.comparisons],
        "limitations": [
            "This artifact measures residual behaviour; it does not yet claim conformal "
            "coverage, player-adaptive scale recalibration, or scenario recalibration.",
            "Opening-gameweek uncertainty requires a separate calibration regime and is "
            "not inferred from gameweek-two-and-later residuals.",
        ],
    }


def recalibration_to_markdown(result: CalendarRecalibrationResult) -> str:
    """Render the fixture-conditioned comparison as a compact audit report."""

    lines = [
        "# Calendar-aware residual measurement",
        "",
        f"- Report schema: `{CALENDAR_RECALIBRATION_REPORT_SCHEMA_VERSION}`",
        f"- Contract: `{result.config.contract_version}`",
        f"- Fingerprint: `{result.measurement_fingerprint}`",
        f"- Reference: `{result.config.reference_candidate}`",
        f"- Candidate: `{result.config.candidate}`",
        f"- Paired rows: {result.diagnostics['paired_rows']}",
        f"- Folds: {result.diagnostics['folds']}",
        "",
        "| Fixture group | Rows | Reference bias | Candidate bias | Bias delta | "
        "Reference SD | Candidate SD | SD delta | MAE delta | RMSE delta |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for comparison in result.comparisons:
        lines.append(
            f"| {comparison.fixture_group} | {comparison.observations} | "
            f"{comparison.reference.mean_residual:+.4f} | "
            f"{comparison.candidate.mean_residual:+.4f} | "
            f"{comparison.mean_residual_delta:+.4f} | "
            f"{comparison.reference.residual_stddev:.4f} | "
            f"{comparison.candidate.residual_stddev:.4f} | "
            f"{comparison.residual_stddev_delta:+.4f} | "
            f"{comparison.mean_absolute_error_delta:+.4f} | "
            f"{comparison.root_mean_squared_error_delta:+.4f} |"
        )
    lines += [
        "",
        "## Scope boundary",
        "",
        "This is the measurement-contract stage. Conformal coverage, player-adaptive "
        "scales and scenario decomposition remain explicitly unclaimed until their "
        "time-aware recalibration runs are added.",
        "",
        "Opening-gameweek uncertainty is a separate regime and is not inferred from "
        "gameweek-two-and-later residuals.",
    ]
    return "\n".join(lines) + "\n"


def time_aware_recalibration_to_dict(
    result: TimeAwareRecalibrationResult,
) -> dict[str, object]:
    """Return the chronological recalibration study as strict JSON data."""

    return {
        "artifact_type": TIME_AWARE_RECALIBRATION_ARTIFACT_TYPE,
        "report_schema_version": TIME_AWARE_RECALIBRATION_REPORT_SCHEMA_VERSION,
        "contract_version": result.config.contract_version,
        "configuration_fingerprint": result.config.configuration_fingerprint,
        "measurement_fingerprint": result.measurement.measurement_fingerprint,
        "study_fingerprint": result.study_fingerprint,
        "configuration": {
            "reference_candidate": result.config.residual_config.reference_candidate,
            "candidate": result.config.residual_config.candidate,
            "confidence_level": result.config.confidence_level,
            "scale_training_fraction": result.config.scale_training_fraction,
            "conformal_calibration_fraction": (result.config.conformal_calibration_fraction),
            "min_position_observations": result.config.min_position_observations,
            "min_player_observations": result.config.min_player_observations,
            "shrinkage_observations": result.config.shrinkage_observations,
            "minimum_scale": result.config.minimum_scale,
        },
        "chronological_split": {
            "scale_training_fold_ids": list(result.scale_training_fold_ids),
            "conformal_calibration_fold_ids": list(result.conformal_calibration_fold_ids),
            "evaluation_fold_ids": list(result.evaluation_fold_ids),
        },
        "interval_comparisons": [asdict(comparison) for comparison in result.interval_comparisons],
        "double_gameweek_player_scales": [
            asdict(comparison) for comparison in result.player_scale_comparisons
        ],
        "scenario_component_comparison": asdict(result.scenario_components),
        "diagnostics": dict(result.diagnostics),
        "limitations": [
            "The report is development recalibration evidence, not model-promotion evidence.",
            "Opening-gameweek uncertainty is not inferred from later-gameweek residuals.",
            "Conformal intervals are marginal and their interpretation still depends on "
            "exchangeability.",
            "Scenario component spreads are re-estimated empirically; no parametric joint "
            "distribution is claimed.",
        ],
    }


def time_aware_recalibration_to_markdown(
    result: TimeAwareRecalibrationResult,
) -> str:
    """Render the chronological uncertainty and component comparison."""

    lines = [
        "# Time-aware calendar recalibration",
        "",
        f"- Report schema: `{TIME_AWARE_RECALIBRATION_REPORT_SCHEMA_VERSION}`",
        f"- Contract: `{result.config.contract_version}`",
        f"- Study fingerprint: `{result.study_fingerprint}`",
        f"- Reference: `{result.config.residual_config.reference_candidate}`",
        f"- Candidate: `{result.config.residual_config.candidate}`",
        "- Split: scale training "
        f"`{len(result.scale_training_fold_ids)}` folds, conformal calibration "
        f"`{len(result.conformal_calibration_fold_ids)}` folds, evaluation "
        f"`{len(result.evaluation_fold_ids)}` folds.",
        "",
        "## Held-out conformal coverage and width",
        "",
        "| Fixture group | Rows | Reference coverage | Candidate coverage | Delta | "
        "Reference width | Candidate width | Width delta |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for interval_comparison in result.interval_comparisons:
        lines.append(
            f"| {interval_comparison.fixture_group} | "
            f"{interval_comparison.reference.observations} | "
            f"{interval_comparison.reference.empirical_coverage:.4f} | "
            f"{interval_comparison.candidate.empirical_coverage:.4f} | "
            f"{interval_comparison.coverage_delta:+.4f} | "
            f"{interval_comparison.reference.mean_interval_width:.4f} | "
            f"{interval_comparison.candidate.mean_interval_width:.4f} | "
            f"{interval_comparison.mean_interval_width_delta:+.4f} |"
        )
    components = result.scenario_components
    lines += [
        "",
        "## Scenario residual decomposition",
        "",
        "| Component | Reference SD | Candidate SD | Delta |",
        "| --- | ---: | ---: | ---: |",
        f"| Common gameweek | {components.reference.common_stddev:.4f} | "
        f"{components.candidate.common_stddev:.4f} | "
        f"{components.common_stddev_delta:+.4f} |",
        f"| Team-gameweek | {components.reference.team_stddev:.4f} | "
        f"{components.candidate.team_stddev:.4f} | "
        f"{components.team_stddev_delta:+.4f} |",
        f"| Player idiosyncratic | {components.reference.idiosyncratic_stddev:.4f} | "
        f"{components.candidate.idiosyncratic_stddev:.4f} | "
        f"{components.idiosyncratic_stddev_delta:+.4f} |",
        "",
        "## Double-gameweek player scales",
        "",
    ]
    if result.player_scale_comparisons:
        lines += [
            "| Player | Position | History | DGW rows | Reference scale | Candidate scale | "
            "Delta |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: |",
        ]
        for scale_comparison in result.player_scale_comparisons:
            lines.append(
                f"| {scale_comparison.player_id} | {scale_comparison.position} | "
                f"{scale_comparison.observations} | "
                f"{scale_comparison.double_plus_observations} | "
                f"{scale_comparison.reference_scale:.4f} | "
                f"{scale_comparison.candidate_scale:.4f} | "
                f"{scale_comparison.scale_delta:+.4f} |"
            )
    else:
        lines.append("No player had double-gameweek history in the scale-training slice.")
    lines += [
        "",
        "## Interpretation boundary",
        "",
        "Every fitted quantity uses folds strictly before the evaluation slice. The two "
        "residual regimes use identical rows and fixture groups. This is recalibration "
        "evidence, not automatic model promotion.",
        "",
        "Opening-gameweek uncertainty remains unavailable from this evidence; later-gameweek "
        "residuals are not silently reused for GW1.",
    ]
    return "\n".join(lines) + "\n"
