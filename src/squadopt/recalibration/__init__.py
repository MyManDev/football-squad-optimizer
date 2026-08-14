"""Calendar-aware residual measurement before uncertainty recalibration."""

from squadopt.recalibration.measurement import (
    measure_calendar_recalibration,
    validate_residual_regimes,
)
from squadopt.recalibration.models import (
    CALENDAR_RECALIBRATION_ARTIFACT_TYPE,
    CALENDAR_RECALIBRATION_CONTRACT_VERSION,
    CALENDAR_RECALIBRATION_REPORT_SCHEMA_VERSION,
    FIXTURE_GROUPS,
    RESIDUAL_COLUMNS,
    CalendarRecalibrationResult,
    FixtureResidualComparison,
    RecalibrationConfig,
    RecalibrationValidationError,
    ResidualMetrics,
)
from squadopt.recalibration.reporting import recalibration_to_dict, recalibration_to_markdown

__all__ = [
    "CALENDAR_RECALIBRATION_ARTIFACT_TYPE",
    "CALENDAR_RECALIBRATION_CONTRACT_VERSION",
    "CALENDAR_RECALIBRATION_REPORT_SCHEMA_VERSION",
    "FIXTURE_GROUPS",
    "RESIDUAL_COLUMNS",
    "CalendarRecalibrationResult",
    "FixtureResidualComparison",
    "RecalibrationConfig",
    "RecalibrationValidationError",
    "ResidualMetrics",
    "measure_calendar_recalibration",
    "recalibration_to_dict",
    "recalibration_to_markdown",
    "validate_residual_regimes",
]
