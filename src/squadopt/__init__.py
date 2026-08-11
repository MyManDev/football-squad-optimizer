"""Public package interface for football squad optimization."""

from squadopt.integration import optimize_squad_from_csv
from squadopt.optimization import (
    InsufficientPlayerPoolError,
    InvalidConfigurationError,
    InvalidPlayerDataError,
    OptimizationConfig,
    OptimizationResult,
    OptimizationValidationError,
    SolverExecutionError,
    SolverStatus,
    SquadOptimizationError,
    optimize_squad,
)

__all__ = [
    "InsufficientPlayerPoolError",
    "InvalidConfigurationError",
    "InvalidPlayerDataError",
    "OptimizationConfig",
    "OptimizationResult",
    "OptimizationValidationError",
    "SolverExecutionError",
    "SolverStatus",
    "SquadOptimizationError",
    "optimize_squad",
    "optimize_squad_from_csv",
]
