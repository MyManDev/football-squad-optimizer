"""Public result, status, and exception models."""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType

import pandas as pd


class SquadOptimizationError(Exception):
    """Base exception for the optimization package."""


class OptimizationValidationError(SquadOptimizationError):
    """Base exception for errors detected before solving."""


class InvalidConfigurationError(OptimizationValidationError):
    """Raised when an optimization configuration is inconsistent."""


class InvalidPlayerDataError(OptimizationValidationError):
    """Raised when player data violates the canonical data contract."""


class InsufficientPlayerPoolError(OptimizationValidationError):
    """Raised when basic squad cardinality requirements cannot be met."""


class SolverExecutionError(SquadOptimizationError):
    """Raised when the generated model or solver fails unexpectedly."""


class SolverStatus(StrEnum):
    """Solver-independent termination status."""

    OPTIMAL = "OPTIMAL"
    FEASIBLE = "FEASIBLE"
    INFEASIBLE = "INFEASIBLE"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class OptimizationResult:
    """Structured squad optimization result."""

    solver_status: SolverStatus
    selected_squad: pd.DataFrame
    starting_xi: pd.DataFrame
    bench: pd.DataFrame
    captain: pd.Series | None
    total_cost_tenths: int | None
    projected_score: float | None
    objective_value: float | None
    diagnostics: Mapping[str, object]

    def __post_init__(self) -> None:
        object.__setattr__(self, "diagnostics", MappingProxyType(dict(self.diagnostics)))

    @property
    def has_solution(self) -> bool:
        """Return whether the result contains a feasible squad."""

        return self.solver_status in {SolverStatus.OPTIMAL, SolverStatus.FEASIBLE}
