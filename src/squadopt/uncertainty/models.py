"""Immutable public results for projection uncertainty calibration and evaluation."""

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

import pandas as pd

from squadopt.data.schema import Position
from squadopt.uncertainty.config import UncertaintyConfig


@dataclass(frozen=True, slots=True)
class GroupCalibration:
    """Effective residual distribution used for one canonical position."""

    position: Position
    source: str
    group_observations: int
    calibration_observations: int
    residual_mean: float
    residual_stddev: float
    interval_radius: float
    conformal_rank: int


@dataclass(frozen=True, slots=True)
class ProjectionUncertaintyCalibration:
    """Frozen development-only calibration state safe to apply to later projections."""

    config: UncertaintyConfig
    pooled_observations: int
    groups: Mapping[Position, GroupCalibration]
    calibration_fingerprint: str
    diagnostics: Mapping[str, object]

    def __post_init__(self) -> None:
        object.__setattr__(self, "groups", MappingProxyType(dict(self.groups)))
        object.__setattr__(self, "diagnostics", MappingProxyType(dict(self.diagnostics)))


@dataclass(frozen=True, slots=True)
class CalibratedProjectionResult:
    """Independent calibrated projection table plus its provenance."""

    table: pd.DataFrame
    calibration_fingerprint: str
    diagnostics: Mapping[str, object]

    def __post_init__(self) -> None:
        object.__setattr__(self, "table", self.table.copy(deep=True))
        object.__setattr__(self, "diagnostics", MappingProxyType(dict(self.diagnostics)))


@dataclass(frozen=True, slots=True)
class UncertaintyMetrics:
    """Coverage, sharpness, and point-error metrics for one scored population."""

    observations: int
    empirical_coverage: float
    mean_interval_width: float
    mean_absolute_error: float
    root_mean_squared_error: float
    mean_error: float


@dataclass(frozen=True, slots=True)
class UncertaintyFoldResult:
    """Calibrated and later-scored player projections for one holdout gameweek."""

    fold_id: str
    scored_players: pd.DataFrame
    metrics: UncertaintyMetrics
    group_metrics: Mapping[Position, UncertaintyMetrics]
    metadata: Mapping[str, object]

    def __post_init__(self) -> None:
        object.__setattr__(self, "scored_players", self.scored_players.copy(deep=True))
        object.__setattr__(self, "group_metrics", MappingProxyType(dict(self.group_metrics)))
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))


@dataclass(frozen=True, slots=True)
class UncertaintyEvaluationResult:
    """Complete locked-holdout uncertainty evaluation."""

    calibration: ProjectionUncertaintyCalibration
    folds: tuple[UncertaintyFoldResult, ...]
    metrics: UncertaintyMetrics
    group_metrics: Mapping[Position, UncertaintyMetrics]
    diagnostics: Mapping[str, object]

    def __post_init__(self) -> None:
        object.__setattr__(self, "group_metrics", MappingProxyType(dict(self.group_metrics)))
        object.__setattr__(self, "diagnostics", MappingProxyType(dict(self.diagnostics)))
