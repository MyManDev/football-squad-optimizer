"""Score one frozen squad decision across component scenario outcomes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

import pandas as pd
from pandas.api.types import is_bool_dtype

from squadopt.evaluation.models import FrozenSquadDecision, RealizedSquadScore
from squadopt.evaluation.scoring import (
    complete_optimization_decision,
    score_frozen_squad_decision,
)
from squadopt.optimization import OptimizationResult
from squadopt.scenarios.models import ScenarioSet, ScenarioValidationError

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
    scenarios: ScenarioSet,
    sampled_appearances: pd.DataFrame,
    *,
    component_fingerprint: str,
) -> ComponentDecisionScoringResult:
    """Score a decision without re-optimizing or consulting scenario outcomes to complete it.

    ``sampled_appearances`` is required explicitly because continuous sampled minutes cannot
    distinguish a non-appearance from an appeared draw clipped to zero minutes. The frame
    must therefore contain the sampler's actual Bernoulli states, not values inferred from
    its minutes matrix.
    """

    frozen_decision = complete_optimization_decision(optimization_result)
    scenario_set = scenarios.validated_copy()
    appearances = _validated_appearance_matrix(sampled_appearances, scenario_set)
    fingerprint = _digest(component_fingerprint, "component_fingerprint")

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
        component_fingerprint=fingerprint,
    )


def _validated_appearance_matrix(
    sampled_appearances: object,
    scenarios: ScenarioSet,
) -> pd.DataFrame:
    if not isinstance(sampled_appearances, pd.DataFrame):
        raise ScenarioValidationError("sampled_appearances must be a pandas DataFrame.")
    appearances = sampled_appearances.copy(deep=True)
    if appearances.shape != scenarios.scenario_points.shape:
        raise ScenarioValidationError(
            "sampled_appearances shape must match the scenario point matrix."
        )
    if tuple(appearances.index.tolist()) != scenarios.scenario_ids:
        raise ScenarioValidationError("sampled_appearances index must equal scenario_ids.")
    if tuple(appearances.columns.tolist()) != tuple(scenarios.scenario_points.columns.tolist()):
        raise ScenarioValidationError(
            "sampled_appearances columns must match scenario player order."
        )
    if bool(appearances.isna().any().any()) or any(
        not is_bool_dtype(dtype) for dtype in appearances.dtypes
    ):
        raise ScenarioValidationError(
            "sampled_appearances must contain complete boolean Bernoulli states; "
            "minutes-derived or nullable values are refused."
        )
    return appearances.astype("bool")


def _digest(value: object, name: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ScenarioValidationError(f"{name} must be a lowercase SHA-256 digest.")
    return value
