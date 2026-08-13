"""Public optimization interface."""

from squadopt.optimization.coefficients import objective_coefficient_fingerprint
from squadopt.optimization.config import OptimizationConfig, Position
from squadopt.optimization.models import (
    InsufficientPlayerPoolError,
    InvalidConfigurationError,
    InvalidPlayerDataError,
    OptimizationResult,
    OptimizationValidationError,
    SolverExecutionError,
    SolverStatus,
    SquadOptimizationError,
)
from squadopt.optimization.optimizer import optimize_squad

__all__ = [
    "InsufficientPlayerPoolError",
    "InvalidConfigurationError",
    "InvalidPlayerDataError",
    "OptimizationConfig",
    "OptimizationResult",
    "OptimizationValidationError",
    "Position",
    "SolverExecutionError",
    "SolverStatus",
    "SquadOptimizationError",
    "objective_coefficient_fingerprint",
    "optimize_squad",
]
