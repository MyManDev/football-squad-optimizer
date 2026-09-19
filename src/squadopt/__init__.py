"""Public package interface for football squad optimization."""

from importlib import import_module as _import_module
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _distribution_version
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
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
        ScoringBasis,
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
    "ScoringBasis",
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

# Resolve public exports only when requested; importing a submodule must not load
# evaluation and optimization just because Python first imports the package root.
_EXPORT_MODULES = {
    "EvaluationConfig": "squadopt.evaluation",
    "EvaluationError": "squadopt.evaluation",
    "EvaluationFold": "squadopt.evaluation",
    "EvaluationResult": "squadopt.evaluation",
    "EvaluationSummary": "squadopt.evaluation",
    "EvaluationValidationError": "squadopt.evaluation",
    "FoldEvaluationResult": "squadopt.evaluation",
    "FrozenSquadDecision": "squadopt.evaluation",
    "InsufficientPlayerPoolError": "squadopt.optimization",
    "InvalidConfigurationError": "squadopt.optimization",
    "InvalidPlayerDataError": "squadopt.optimization",
    "OptimizationConfig": "squadopt.optimization",
    "OptimizationResult": "squadopt.optimization",
    "OptimizationValidationError": "squadopt.optimization",
    "RealizedSquadScore": "squadopt.evaluation",
    "ScoringBasis": "squadopt.evaluation",
    "ScoringPolicy": "squadopt.evaluation",
    "SolverExecutionError": "squadopt.optimization",
    "SolverStatus": "squadopt.optimization",
    "SquadOptimizationError": "squadopt.optimization",
    "complete_optimization_decision": "squadopt.evaluation",
    "evaluate_prepared_folds": "squadopt.evaluation",
    "optimize_squad": "squadopt.optimization",
    "optimize_squad_from_csv": "squadopt.integration",
    "score_frozen_squad_decision": "squadopt.evaluation",
    "score_realized_squad_points": "squadopt.evaluation",
}


def __getattr__(name: str) -> Any:
    module_name = _EXPORT_MODULES.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(_import_module(module_name), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
