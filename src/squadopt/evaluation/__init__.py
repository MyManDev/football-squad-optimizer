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
    FrozenSquadDecision,
    RealizedSquadScore,
    ScoringPolicy,
)
from squadopt.evaluation.scoring import (
    complete_optimization_decision,
    score_frozen_squad_decision,
    score_realized_squad_points,
)

__all__ = [
    "EvaluationConfig",
    "EvaluationError",
    "EvaluationFold",
    "EvaluationResult",
    "EvaluationSummary",
    "EvaluationValidationError",
    "FoldEvaluationResult",
    "FrozenSquadDecision",
    "RealizedSquadScore",
    "ScoringPolicy",
    "complete_optimization_decision",
    "evaluate_prepared_folds",
    "score_frozen_squad_decision",
    "score_realized_squad_points",
]
