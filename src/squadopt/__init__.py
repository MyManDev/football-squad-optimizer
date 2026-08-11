"""Public package interface for football squad optimization."""

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
]
