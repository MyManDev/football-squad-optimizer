"""Pre-run validation of residual-export handoff and measurement artifacts."""

from squadopt.preflight.measurement import (
    MEASUREMENT_KINDS,
    MEASUREMENT_PREFLIGHT_CONTRACT_VERSION,
    check_measurement_artifact,
    run_measurement_preflight,
)
from squadopt.preflight.models import (
    ALLOWED_POSITIONS,
    MANIFEST_IDENTITY_FIELDS,
    MANIFEST_REQUIRED_FIELDS,
    PREFLIGHT_CONTRACT_VERSION,
    RESIDUAL_EXPORT_COLUMNS,
    RESIDUAL_EXPORT_CONTRACT_VERSION,
    PreflightError,
    PreflightExpectations,
    PreflightFinding,
    PreflightReport,
)
from squadopt.preflight.reporting import (
    preflight_report_to_dict,
    preflight_report_to_markdown,
)
from squadopt.preflight.validator import (
    check_export_pair,
    check_manifest_expectations,
    check_residual_manifest,
    check_residual_table,
    check_table_matches_manifest,
    compute_table_sha256,
    run_export_pair_preflight,
    run_residual_export_preflight,
)

__all__ = [
    "ALLOWED_POSITIONS",
    "MANIFEST_IDENTITY_FIELDS",
    "MANIFEST_REQUIRED_FIELDS",
    "MEASUREMENT_KINDS",
    "MEASUREMENT_PREFLIGHT_CONTRACT_VERSION",
    "PREFLIGHT_CONTRACT_VERSION",
    "RESIDUAL_EXPORT_COLUMNS",
    "RESIDUAL_EXPORT_CONTRACT_VERSION",
    "PreflightError",
    "PreflightExpectations",
    "PreflightFinding",
    "PreflightReport",
    "check_export_pair",
    "check_manifest_expectations",
    "check_measurement_artifact",
    "check_residual_manifest",
    "check_residual_table",
    "check_table_matches_manifest",
    "compute_table_sha256",
    "preflight_report_to_dict",
    "preflight_report_to_markdown",
    "run_export_pair_preflight",
    "run_measurement_preflight",
    "run_residual_export_preflight",
]
