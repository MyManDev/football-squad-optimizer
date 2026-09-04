"""Public package interface for football squad optimization."""

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _distribution_version

from squadopt.evaluation import (
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
    complete_optimization_decision,
    evaluate_prepared_folds,
    score_frozen_squad_decision,
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

# The installed distribution's version, read rather than copied: a second literal here would
# be a second place for the number to drift from `pyproject.toml`. The import package is
# `squadopt` but the distribution is `football-squad-optimizer`, which is the name to ask for.
#
# This reports what is *installed*, not what the working tree says. A stale editable install
# therefore reports a stale number — see the release procedure in `CHANGELOG.md`. It is not an
# operational identifier: what decided a squad is recorded per decision (`model_version`,
# `feature_contract_version`, `prediction_fingerprint`, `repository_commit`).
DISTRIBUTION_NAME = "football-squad-optimizer"

try:
    __version__ = _distribution_version(DISTRIBUTION_NAME)
except PackageNotFoundError:  # pragma: no cover - only when the tree is not installed at all
    __version__ = "0+unknown"

__all__ = [
    "DISTRIBUTION_NAME",
    "EvaluationConfig",
    "EvaluationError",
    "EvaluationFold",
    "EvaluationResult",
    "EvaluationSummary",
    "EvaluationValidationError",
    "FoldEvaluationResult",
    "FrozenSquadDecision",
    "InsufficientPlayerPoolError",
    "InvalidConfigurationError",
    "InvalidPlayerDataError",
    "OptimizationConfig",
    "OptimizationResult",
    "OptimizationValidationError",
    "RealizedSquadScore",
    "ScoringPolicy",
    "SolverExecutionError",
    "SolverStatus",
    "SquadOptimizationError",
    "__version__",
    "complete_optimization_decision",
    "evaluate_prepared_folds",
    "optimize_squad",
    "optimize_squad_from_csv",
    "score_frozen_squad_decision",
    "score_realized_squad_points",
]
