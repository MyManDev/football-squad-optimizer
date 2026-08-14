"""Public contracts for calendar-aware residual measurement."""

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final

import pandas as pd

from squadopt.data.errors import DataError

CALENDAR_RECALIBRATION_CONTRACT_VERSION: Final = "calendar_recalibration_measurement_v1"
CALENDAR_RECALIBRATION_ARTIFACT_TYPE: Final = "calendar_recalibration_measurement"
CALENDAR_RECALIBRATION_REPORT_SCHEMA_VERSION: Final = "calendar_recalibration_report_v1"

RESIDUAL_COLUMNS: Final = (
    "candidate",
    "fold_id",
    "season",
    "gameweek",
    "player_id",
    "team_id",
    "position",
    "predicted_points",
    "realized_points",
    "residual",
)

FIXTURE_GROUPS: Final = ("blank", "single", "double_plus")


class RecalibrationValidationError(DataError):
    """Raised when residual regimes cannot be compared safely."""


@dataclass(frozen=True, slots=True)
class RecalibrationConfig:
    """Names the two residual regimes compared by one measurement run."""

    reference_candidate: str = "calendar_blind_baseline"
    candidate: str = "calendar_aware_production"
    contract_version: str = CALENDAR_RECALIBRATION_CONTRACT_VERSION

    def __post_init__(self) -> None:
        reference = _label(self.reference_candidate, "reference_candidate")
        candidate = _label(self.candidate, "candidate")
        if reference == candidate:
            raise RecalibrationValidationError(
                "reference_candidate and candidate must name different residual regimes."
            )
        if self.contract_version != CALENDAR_RECALIBRATION_CONTRACT_VERSION:
            raise RecalibrationValidationError(
                "contract_version does not match the implemented recalibration contract."
            )
        object.__setattr__(self, "reference_candidate", reference)
        object.__setattr__(self, "candidate", candidate)


def _label(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RecalibrationValidationError(f"{name} must be a non-empty string.")
    return value.strip()


@dataclass(frozen=True, slots=True)
class ResidualMetrics:
    """Point-error and spread metrics for one residual population."""

    observations: int
    mean_residual: float
    residual_stddev: float
    mean_absolute_error: float
    root_mean_squared_error: float


@dataclass(frozen=True, slots=True)
class FixtureResidualComparison:
    """Matched residual metrics for one fixture-count population."""

    fixture_group: str
    observations: int
    reference: ResidualMetrics
    candidate: ResidualMetrics
    mean_residual_delta: float
    residual_stddev_delta: float
    mean_absolute_error_delta: float
    root_mean_squared_error_delta: float


@dataclass(frozen=True, slots=True)
class CalendarRecalibrationResult:
    """Structured residual measurement with its fixture-conditioned rows."""

    config: RecalibrationConfig
    comparisons: tuple[FixtureResidualComparison, ...]
    residuals_with_fixture_context: pd.DataFrame
    measurement_fingerprint: str
    diagnostics: Mapping[str, object]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "residuals_with_fixture_context",
            self.residuals_with_fixture_context.copy(deep=True),
        )
        object.__setattr__(self, "diagnostics", MappingProxyType(dict(self.diagnostics)))
