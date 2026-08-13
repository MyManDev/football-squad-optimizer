"""Joint point scenarios and fixed-decision distribution summaries."""

from squadopt.scenarios.evaluation import evaluate_fixed_decision
from squadopt.scenarios.generator import generate_scenarios, validate_residual_history
from squadopt.scenarios.models import (
    RESIDUAL_HISTORY_COLUMNS,
    SCENARIO_CONTRACT_VERSION,
    SCENARIO_EVALUATION_CONTRACT_VERSION,
    ScenarioConfig,
    ScenarioConfigurationError,
    ScenarioError,
    ScenarioEvaluationConfig,
    ScenarioEvaluationResult,
    ScenarioRiskMetrics,
    ScenarioSet,
    ScenarioTarget,
    ScenarioValidationError,
)
from squadopt.scenarios.reporting import (
    scenario_result_to_dict,
    scenario_result_to_markdown,
)

__all__ = [
    "RESIDUAL_HISTORY_COLUMNS",
    "SCENARIO_CONTRACT_VERSION",
    "SCENARIO_EVALUATION_CONTRACT_VERSION",
    "ScenarioConfig",
    "ScenarioConfigurationError",
    "ScenarioError",
    "ScenarioEvaluationConfig",
    "ScenarioEvaluationResult",
    "ScenarioRiskMetrics",
    "ScenarioSet",
    "ScenarioTarget",
    "ScenarioValidationError",
    "evaluate_fixed_decision",
    "generate_scenarios",
    "scenario_result_to_dict",
    "scenario_result_to_markdown",
    "validate_residual_history",
]
