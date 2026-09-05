"""Score one frozen squad decision across component scenario outcomes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

import pandas as pd

from squadopt.evaluation.models import FrozenSquadDecision, RealizedSquadScore
from squadopt.evaluation.scoring import (
    complete_optimization_decision,
    score_frozen_squad_decision,
)
from squadopt.optimization import OptimizationResult
from squadopt.scenarios.components import ComponentScenarioDraw
from squadopt.scenarios.models import ScenarioValidationError

COMPONENT_DECISION_SCORING_CONTRACT_VERSION: Final = "component_decision_scoring_v1"


@dataclass(frozen=True, slots=True)
class ComponentDecisionScoringResult:
    """Auditable official-rules scores aligned with one component scenario draw."""

    frozen_decision: FrozenSquadDecision
    scenario_ids: tuple[str, ...]
    scores: tuple[RealizedSquadScore, ...]
    scenario_fingerprint: str
    component_fingerprint: str
    contract_version: str = COMPONENT_DECISION_SCORING_CONTRACT_VERSION

    def __post_init__(self) -> None:
        if self.contract_version != COMPONENT_DECISION_SCORING_CONTRACT_VERSION:
            raise ScenarioValidationError(
                "contract_version does not match component decision scoring."
            )
        if len(self.scenario_ids) != len(self.scores):
            raise ScenarioValidationError("scenario_ids and scores must have equal lengths.")
        if len(set(self.scenario_ids)) != len(self.scenario_ids):
            raise ScenarioValidationError("scenario_ids must be unique.")
        _digest(self.scenario_fingerprint, "scenario_fingerprint")
        _digest(self.component_fingerprint, "component_fingerprint")

    @property
    def total_points(self) -> tuple[float, ...]:
        """Return official-rules scores in scenario order."""

        return tuple(score.total_points for score in self.scores)


def score_component_scenario_decision(
    optimization_result: OptimizationResult,
    draw: ComponentScenarioDraw,
) -> ComponentDecisionScoringResult:
    """Score a decision without re-optimizing or consulting scenario outcomes to complete it.

    The complete draw is required so points, appearances and their component fingerprint
    cannot be mixed across otherwise shape-compatible draws.
    """

    frozen_decision = complete_optimization_decision(optimization_result)
    if not isinstance(draw, ComponentScenarioDraw):
        raise ScenarioValidationError("draw must be a ComponentScenarioDraw.")
    validated_draw = ComponentScenarioDraw(
        scenarios=draw.scenarios,
        inputs=draw.inputs,
        sampled_minutes=draw.sampled_minutes,
        sampled_appearances=draw.sampled_appearances,
        component_fingerprint=draw.component_fingerprint,
    )
    scenario_set = validated_draw.scenarios.validated_copy()
    appearances = validated_draw.sampled_appearances

    squad_ids = tuple(frozen_decision.squad["player_id"].tolist())
    missing = [
        player_id for player_id in squad_ids if player_id not in scenario_set.scenario_points
    ]
    if missing:
        raise ScenarioValidationError(
            "Component scenarios do not cover every selected squad player; "
            f"missing player_id values: {missing[:10]!r}."
        )

    scores: list[RealizedSquadScore] = []
    for scenario_id in scenario_set.scenario_ids:
        outcomes = pd.DataFrame(
            {
                "player_id": squad_ids,
                "total_points": scenario_set.scenario_points.loc[
                    scenario_id, list(squad_ids)
                ].to_numpy(copy=True),
                # The official scorer needs only zero versus positive minutes. These values
                # are appearance indicators, not simulated match-minute claims.
                "minutes": appearances.loc[scenario_id, list(squad_ids)]
                .astype("int64")
                .to_numpy(copy=True),
            }
        )
        scores.append(score_frozen_squad_decision(frozen_decision, outcomes))

    return ComponentDecisionScoringResult(
        frozen_decision=frozen_decision,
        scenario_ids=scenario_set.scenario_ids,
        scores=tuple(scores),
        scenario_fingerprint=scenario_set.scenario_fingerprint,
        component_fingerprint=validated_draw.component_fingerprint,
    )


def _digest(value: object, name: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ScenarioValidationError(f"{name} must be a lowercase SHA-256 digest.")
    return value
