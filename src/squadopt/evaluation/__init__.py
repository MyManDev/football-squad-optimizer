"""Public prepared-fold evaluation interface."""

from squadopt.evaluation.evaluator import evaluate_prepared_folds
from squadopt.evaluation.models import (
    EvaluationConfig,
    EvaluationError,
    EvaluationFold,
    EvaluationResult,
    EvaluationSummary,
    EvaluationValidationError,
    FoldEvaluationResult,
    ScoringPolicy,
)
from squadopt.evaluation.scoring import score_realized_squad_points

__all__ = [
    "EvaluationConfig",
    "EvaluationError",
    "EvaluationFold",
    "EvaluationResult",
    "EvaluationSummary",
    "EvaluationValidationError",
    "FoldEvaluationResult",
    "ScoringPolicy",
    "evaluate_prepared_folds",
    "score_realized_squad_points",
]
