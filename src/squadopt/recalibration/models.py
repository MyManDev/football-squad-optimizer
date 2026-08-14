"""Public contracts for calendar-aware residual measurement."""

import hashlib
import json
import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from numbers import Integral, Real
from types import MappingProxyType
from typing import Final

import pandas as pd

from squadopt.data.errors import DataError

CALENDAR_RECALIBRATION_CONTRACT_VERSION: Final = "calendar_recalibration_measurement_v1"
CALENDAR_RECALIBRATION_ARTIFACT_TYPE: Final = "calendar_recalibration_measurement"
CALENDAR_RECALIBRATION_REPORT_SCHEMA_VERSION: Final = "calendar_recalibration_report_v1"
TIME_AWARE_RECALIBRATION_CONTRACT_VERSION: Final = "time_aware_calendar_recalibration_v1"
TIME_AWARE_RECALIBRATION_ARTIFACT_TYPE: Final = "time_aware_calendar_recalibration"
TIME_AWARE_RECALIBRATION_REPORT_SCHEMA_VERSION: Final = (
    "time_aware_calendar_recalibration_report_v1"
)

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


def _probability(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise RecalibrationValidationError(f"{name} must be a finite number in (0, 1).")
    number = float(value)
    if not math.isfinite(number) or not 0.0 < number < 1.0:
        raise RecalibrationValidationError(f"{name} must be a finite number in (0, 1).")
    return number


def _positive_integer(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, Integral) or int(value) < 1:
        raise RecalibrationValidationError(f"{name} must be a positive integer.")
    return int(value)


def _positive_float(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise RecalibrationValidationError(f"{name} must be a positive finite number.")
    number = float(value)
    if not math.isfinite(number) or number <= 0.0:
        raise RecalibrationValidationError(f"{name} must be a positive finite number.")
    return number


@dataclass(frozen=True, slots=True)
class TimeAwareRecalibrationConfig:
    """Controls a chronological scale/conformal/evaluation comparison."""

    residual_config: RecalibrationConfig = field(default_factory=RecalibrationConfig)
    confidence_level: float = 0.90
    scale_training_fraction: float = 0.40
    conformal_calibration_fraction: float = 0.30
    min_position_observations: int = 30
    min_player_observations: int = 5
    shrinkage_observations: float = 10.0
    minimum_scale: float = 0.25
    contract_version: str = TIME_AWARE_RECALIBRATION_CONTRACT_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.residual_config, RecalibrationConfig):
            raise RecalibrationValidationError("residual_config must be a RecalibrationConfig.")
        confidence = _probability(self.confidence_level, "confidence_level")
        scale_fraction = _probability(self.scale_training_fraction, "scale_training_fraction")
        conformal_fraction = _probability(
            self.conformal_calibration_fraction,
            "conformal_calibration_fraction",
        )
        if scale_fraction + conformal_fraction >= 1.0:
            raise RecalibrationValidationError(
                "scale_training_fraction plus conformal_calibration_fraction must be below 1."
            )
        if self.contract_version != TIME_AWARE_RECALIBRATION_CONTRACT_VERSION:
            raise RecalibrationValidationError(
                "contract_version does not match the implemented time-aware contract."
            )
        object.__setattr__(self, "confidence_level", confidence)
        object.__setattr__(self, "scale_training_fraction", scale_fraction)
        object.__setattr__(self, "conformal_calibration_fraction", conformal_fraction)
        for name in ("min_position_observations", "min_player_observations"):
            object.__setattr__(self, name, _positive_integer(getattr(self, name), name))
        for name in ("shrinkage_observations", "minimum_scale"):
            object.__setattr__(self, name, _positive_float(getattr(self, name), name))

    @property
    def configuration_fingerprint(self) -> str:
        """Return a stable digest of every comparison-affecting control."""

        payload = {
            "contract_version": self.contract_version,
            "reference_candidate": self.residual_config.reference_candidate,
            "candidate": self.residual_config.candidate,
            "confidence_level": self.confidence_level,
            "scale_training_fraction": self.scale_training_fraction,
            "conformal_calibration_fraction": self.conformal_calibration_fraction,
            "min_position_observations": self.min_position_observations,
            "min_player_observations": self.min_player_observations,
            "shrinkage_observations": self.shrinkage_observations,
            "minimum_scale": self.minimum_scale,
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class IntervalMetrics:
    """Held-out empirical coverage and interval sharpness."""

    observations: int
    empirical_coverage: float
    mean_interval_width: float


@dataclass(frozen=True, slots=True)
class FixtureIntervalComparison:
    """Matched interval behavior for one fixture-count group."""

    fixture_group: str
    reference: IntervalMetrics
    candidate: IntervalMetrics
    coverage_delta: float
    mean_interval_width_delta: float


@dataclass(frozen=True, slots=True)
class PlayerScaleComparison:
    """Re-estimated effective scale for a player with double-gameweek history."""

    player_id: object
    position: str
    observations: int
    double_plus_observations: int
    reference_source: str
    candidate_source: str
    reference_scale: float
    candidate_scale: float
    scale_delta: float


@dataclass(frozen=True, slots=True)
class ScenarioComponentMetrics:
    """Empirical spread assigned to each hierarchical residual component."""

    candidate: str
    observations: int
    fold_count: int
    team_fold_count: int
    common_stddev: float
    team_stddev: float
    idiosyncratic_stddev: float
    common_variance_share: float
    team_variance_share: float
    idiosyncratic_variance_share: float


@dataclass(frozen=True, slots=True)
class ScenarioComponentComparison:
    """Calendar-aware minus calendar-blind component-spread changes."""

    reference: ScenarioComponentMetrics
    candidate: ScenarioComponentMetrics
    common_stddev_delta: float
    team_stddev_delta: float
    idiosyncratic_stddev_delta: float


@dataclass(frozen=True, slots=True)
class TimeAwareRecalibrationResult:
    """Chronological uncertainty and scenario recalibration evidence."""

    config: TimeAwareRecalibrationConfig
    measurement: CalendarRecalibrationResult
    scale_training_fold_ids: tuple[str, ...]
    conformal_calibration_fold_ids: tuple[str, ...]
    evaluation_fold_ids: tuple[str, ...]
    interval_comparisons: tuple[FixtureIntervalComparison, ...]
    player_scale_comparisons: tuple[PlayerScaleComparison, ...]
    scenario_components: ScenarioComponentComparison
    study_fingerprint: str
    diagnostics: Mapping[str, object]

    def __post_init__(self) -> None:
        object.__setattr__(self, "diagnostics", MappingProxyType(dict(self.diagnostics)))
