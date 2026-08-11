"""Public optimization interface."""

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
    "optimize_squad",
]
