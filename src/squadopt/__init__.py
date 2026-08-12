"""Public package interface for football squad optimization."""

from squadopt.evaluation import (
    EvaluationConfig,
    EvaluationError,
    EvaluationFold,
    EvaluationResult,
    EvaluationSummary,
    EvaluationValidationError,
    FoldEvaluationResult,
    ScoringPolicy,
    evaluate_prepared_folds,
    score_realized_squad_points,
)
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
    "EvaluationConfig",
    "EvaluationError",
    "EvaluationFold",
    "EvaluationResult",
    "EvaluationSummary",
    "EvaluationValidationError",
    "FoldEvaluationResult",
    "InsufficientPlayerPoolError",
    "InvalidConfigurationError",
    "InvalidPlayerDataError",
    "OptimizationConfig",
    "OptimizationResult",
    "OptimizationValidationError",
    "ScoringPolicy",
    "SolverExecutionError",
    "SolverStatus",
    "SquadOptimizationError",
    "evaluate_prepared_folds",
    "optimize_squad",
    "optimize_squad_from_csv",
    "score_realized_squad_points",
]
