"""Immutable public results for risk-aware optimization and screening."""

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from squadopt.optimization import OptimizationResult, SolverStatus
from squadopt.risk.config import RiskOptimizationConfig, RiskScreeningConfig


@dataclass(frozen=True, slots=True)
class RiskAwareOptimizationResult:
    """One squad decision optimized against a conformal lower-bound objective."""

    optimization_result: OptimizationResult
    risk_config: RiskOptimizationConfig
    calibration_fingerprint: str
    expected_points_objective_value: float | None
    risk_adjusted_projected_score: float | None
    risk_penalty_value: float | None
    diagnostics: Mapping[str, object]

    def __post_init__(self) -> None:
        object.__setattr__(self, "diagnostics", MappingProxyType(dict(self.diagnostics)))

    @property
    def solver_status(self) -> SolverStatus:
        """Expose the solver-independent status of the underlying decision."""

        return self.optimization_result.solver_status

    @property
    def has_solution(self) -> bool:
        """Return whether the underlying optimization produced a feasible squad."""

        return self.optimization_result.has_solution

    @property
    def risk_adjusted_objective_value(self) -> float | None:
        """Return the complete risk-adjusted starter/captain/bench objective."""

        return self.optimization_result.objective_value


@dataclass(frozen=True, slots=True)
class RiskScreeningFoldResult:
    """One season-safe calibrated and realized-scored risk decision."""

    fold_id: str
    season: str
    gameweek: int
    calibration_seasons: tuple[str, ...]
    result: RiskAwareOptimizationResult
    realized_squad_points: float | None


@dataclass(frozen=True, slots=True)
class RiskScreeningMetrics:
    """Mean and downside diagnostics for one risk-aversion level."""

    attempted_folds: int
    feasible_folds: int
    scored_folds: int
    feasibility_rate: float
    mean_realized_squad_points: float | None
    realized_squad_points_stddev: float | None
    downside_quantile_score: float | None
    mean_worst_fraction_score: float | None
    minimum_realized_squad_points: float | None
    mean_expected_points_objective_value: float | None
    mean_risk_adjusted_objective_value: float | None
    mean_risk_penalty_value: float | None


@dataclass(frozen=True, slots=True)
class RiskPairedComparison:
    """Exact-fold realized-score differences against risk_aversion=0."""

    control_id: str
    candidate_id: str
    comparable_folds: int
    mean_difference: float | None
    difference_stddev: float | None
    downside_quantile_difference: float | None
    mean_worst_fraction_difference: float | None
    minimum_difference: float | None
    comparable_decision_folds: int
    squad_changed_folds: int
    starting_xi_changed_folds: int
    captain_changed_folds: int


@dataclass(frozen=True, slots=True)
class RiskCandidateResult:
    """All fold decisions and summaries for one risk-aversion level."""

    risk_config: RiskOptimizationConfig
    folds: tuple[RiskScreeningFoldResult, ...]
    metrics: RiskScreeningMetrics
    comparison: RiskPairedComparison


@dataclass(frozen=True, slots=True)
class RiskScreeningResult:
    """Development-only expanding-season risk screening result."""

    config: RiskScreeningConfig
    candidates: tuple[RiskCandidateResult, ...]
    diagnostics: Mapping[str, object]

    def __post_init__(self) -> None:
        object.__setattr__(self, "diagnostics", MappingProxyType(dict(self.diagnostics)))
