"""Score one frozen squad decision across component scenario outcomes."""

from __future__ import annotations

import math
from dataclasses import dataclass
from numbers import Real
from typing import Final

import numpy as np
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
COMPONENT_DECISION_READOUT_CONTRACT_VERSION: Final = "component_decision_readout_v1"
COMPONENT_DECISION_LOWER_QUANTILE: Final = 0.10


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


@dataclass(frozen=True, slots=True)
class ComponentDecisionDistributionReadout:
    """Canonical internal summary of one officially scored component draw."""

    scenario_count: int
    mean_score: float
    score_standard_deviation: float
    lower_quantile_probability: float
    lower_quantile_score: float
    realized_score: float | None
    probability_integral_transform: float | None
    realized_below_lower_quantile: bool | None
    scenario_fingerprint: str
    component_fingerprint: str
    decision_scoring_contract_version: str
    contract_version: str = COMPONENT_DECISION_READOUT_CONTRACT_VERSION


def summarize_component_decision_distribution(
    scored: ComponentDecisionScoringResult,
    *,
    realized_score: float | None = None,
) -> ComponentDecisionDistributionReadout:
    """Summarize scores without shifting, scaling, reweighting or publishing them."""

    if not isinstance(scored, ComponentDecisionScoringResult):
        raise ScenarioValidationError("scored must be a ComponentDecisionScoringResult.")
    values = np.asarray(scored.total_points, dtype="float64")
    if values.size < 1 or not bool(np.isfinite(values).all()):
        raise ScenarioValidationError("Component decision scores must be finite and non-empty.")
    lower = float(np.quantile(values, COMPONENT_DECISION_LOWER_QUANTILE, method="linear"))

    observed: float | None = None
    pit: float | None = None
    below: bool | None = None
    if realized_score is not None:
        if isinstance(realized_score, bool) or not isinstance(realized_score, Real):
            raise ScenarioValidationError("realized_score must be a finite number or None.")
        observed = float(realized_score)
        if not math.isfinite(observed):
            raise ScenarioValidationError("realized_score must be a finite number or None.")
        pit = float((values <= observed).mean())
        below = observed < lower

    return ComponentDecisionDistributionReadout(
        scenario_count=len(values),
        mean_score=float(values.mean()),
        score_standard_deviation=float(values.std(ddof=0)),
        lower_quantile_probability=COMPONENT_DECISION_LOWER_QUANTILE,
        lower_quantile_score=lower,
        realized_score=observed,
        probability_integral_transform=pit,
        realized_below_lower_quantile=below,
        scenario_fingerprint=scored.scenario_fingerprint,
        component_fingerprint=scored.component_fingerprint,
        decision_scoring_contract_version=scored.contract_version,
    )


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
