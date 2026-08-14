"""Deterministic JSON and Markdown reports for recalibration measurements."""

from dataclasses import asdict

from squadopt.recalibration.models import (
    CALENDAR_RECALIBRATION_ARTIFACT_TYPE,
    CALENDAR_RECALIBRATION_REPORT_SCHEMA_VERSION,
    CalendarRecalibrationResult,
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
