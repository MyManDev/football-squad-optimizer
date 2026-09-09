"""The strategy catalogue: declared constraints, expected-points pricing, closed envelope."""

from squadopt.application.strategies.candidates import (
    StrategyPlan,
    solve_strategy_plan,
)
from squadopt.application.strategies.catalog import (
    PUBLISHABLE_FIELDS,
    STRATEGY_CATALOG,
    CandidateConstraints,
    EvidenceStatus,
    RankingCriterion,
    Strategy,
    StrategyConfigurationError,
    strategy,
)
from squadopt.application.strategies.rule import (
    RIVAL_RULE_STRATEGIES,
    RULE_STRATEGIES,
    STRATEGY_RULE_ID,
    WEEKLY_POINTS_DIFFERENTIAL_POINTS,
    GapBand,
    StrategySuggestion,
    band_edge_points,
    gameweeks_remaining,
    suggest_strategy,
)

__all__ = [
    "PUBLISHABLE_FIELDS",
    "RIVAL_RULE_STRATEGIES",
    "RULE_STRATEGIES",
    "STRATEGY_CATALOG",
    "STRATEGY_RULE_ID",
    "WEEKLY_POINTS_DIFFERENTIAL_POINTS",
    "CandidateConstraints",
    "EvidenceStatus",
    "GapBand",
    "RankingCriterion",
    "Strategy",
    "StrategyConfigurationError",
    "StrategyPlan",
    "StrategySuggestion",
    "band_edge_points",
    "gameweeks_remaining",
    "solve_strategy_plan",
    "strategy",
    "suggest_strategy",
]
