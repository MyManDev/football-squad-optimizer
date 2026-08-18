"""Joint point scenarios and fixed-decision distribution summaries."""

from squadopt.scenarios.evaluation import (
    RivalSquad,
    ScenarioComparisonResult,
    compare_fixed_decisions,
    evaluate_fixed_decision,
    wilson_interval,
)
from squadopt.scenarios.generator import generate_scenarios, validate_residual_history
from squadopt.scenarios.models import (
    RESIDUAL_HISTORY_COLUMNS,
    SCENARIO_CONTRACT_VERSION,
    SCENARIO_EVALUATION_CONTRACT_VERSION,
    SCENARIO_OPTIMIZATION_CONTRACT_VERSION,
    ScenarioConfig,
    ScenarioConfigurationError,
    ScenarioError,
    ScenarioEvaluationConfig,
    ScenarioEvaluationResult,
    ScenarioOptimizationConfig,
    ScenarioOptimizationResult,
    ScenarioRiskMetrics,
    ScenarioSet,
    ScenarioTarget,
    ScenarioValidationError,
)
from squadopt.scenarios.optimization import optimize_scenario_aware_squad
from squadopt.scenarios.reporting import (
    scenario_result_to_dict,
    scenario_result_to_markdown,
)

__all__ = [
    "RESIDUAL_HISTORY_COLUMNS",
    "SCENARIO_CONTRACT_VERSION",
    "SCENARIO_EVALUATION_CONTRACT_VERSION",
    "SCENARIO_OPTIMIZATION_CONTRACT_VERSION",
    "RivalSquad",
    "ScenarioComparisonResult",
    "ScenarioConfig",
    "ScenarioConfigurationError",
    "ScenarioError",
    "ScenarioEvaluationConfig",
    "ScenarioEvaluationResult",
    "ScenarioOptimizationConfig",
    "ScenarioOptimizationResult",
    "ScenarioRiskMetrics",
    "ScenarioSet",
    "ScenarioTarget",
    "ScenarioValidationError",
    "compare_fixed_decisions",
    "evaluate_fixed_decision",
    "generate_scenarios",
    "optimize_scenario_aware_squad",
    "scenario_result_to_dict",
    "scenario_result_to_markdown",
    "validate_residual_history",
    "wilson_interval",
]
