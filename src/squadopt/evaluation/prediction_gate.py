"""Read a declared ranking/error/decision gate from already-computed paired summaries.

No fitting, loading, solving or promotion occurs here. Missing evidence never passes.
The caller declares the season/position population before measurement; the gate refuses
extra cells rather than silently changing the comparison's population.
"""

import hashlib
import json
import math
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import Literal

GateState = Literal["passes", "fails", "insufficient"]
Pair = tuple[float, float]  # control, candidate


@dataclass(frozen=True)
class PredictionGatePolicy:
    """A numeric template; the candidate preregistration freezes its fingerprint."""

    minimum_rank_gain: float = 0.01
    maximum_cell_rank_loss: float = 0.01
    maximum_relative_mae_increase: float = 0.05
    minimum_decision_gain: float = 0.5
    maximum_losing_seasons: int = 1
    minimum_seasons: int = 2
    contract_version: str = "prediction_ranking_gate_v1"

    def __post_init__(self) -> None:
        for value in (
            self.minimum_rank_gain,
            self.maximum_cell_rank_loss,
            self.maximum_relative_mae_increase,
            self.minimum_decision_gain,
        ):
            if isinstance(value, bool) or not math.isfinite(value) or value < 0:
                raise ValueError("Gate thresholds must be finite and non-negative.")
        for value in (self.maximum_losing_seasons, self.minimum_seasons):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError("Season thresholds must be non-negative integers.")
        if self.minimum_seasons < 2 or self.maximum_losing_seasons >= self.minimum_seasons:
            raise ValueError("The gate needs at least two seasons and cannot allow all to lose.")
        if self.contract_version != "prediction_ranking_gate_v1":
            raise ValueError("Unsupported prediction gate contract.")

    @property
    def fingerprint(self) -> str:
        encoded = json.dumps(asdict(self), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode()).hexdigest()


@dataclass(frozen=True)
class PredictionGateResult:
    ranking: GateState
    error: GateState
    decision: GateState
    policy_fingerprint: str

    @property
    def verdict(self) -> GateState:
        states = (self.ranking, self.error, self.decision)
        if "fails" in states:
            return "fails"
        return "insufficient" if "insufficient" in states else "passes"


def _state(checks: list[bool], complete: bool) -> GateState:
    if not all(checks):
        return "fails"
    return "passes" if complete else "insufficient"


def _finite(value: float) -> bool:
    return not isinstance(value, bool) and math.isfinite(value)


DEFAULT_PREDICTION_GATE = PredictionGatePolicy()


def evaluate_prediction_gate(
    *,
    seasons: tuple[str, ...],
    positions: tuple[str, ...],
    ranks: Mapping[tuple[str, str], Pair],
    errors: Mapping[str, Pair],
    decision_mean: float | None,
    decision_interval: Pair | None,
    decision_by_season: Mapping[str, float],
    policy: PredictionGatePolicy = DEFAULT_PREDICTION_GATE,
) -> PredictionGateResult:
    """Compare predeclared summaries; pairs are control/candidate, interval is low/high.

    Ranks contain every (season, position) and ("pooled", position). Error contains
    every season and "pooled", for the declared all-row point-error population. The
    rank mean is equally weighted across pooled positions; each seasonal cell also
    guards against a positional regression. Decision intervals are paired 90% intervals
    computed by the preregistered runner, not independent arm intervals.
    """
    if not seasons or len(set(seasons)) != len(seasons) or "pooled" in seasons:
        raise ValueError("Declare distinct non-pooled seasons.")
    if not positions or len(set(positions)) != len(positions):
        raise ValueError("Declare distinct positions.")
    if any(position not in {"GK", "DEF", "MID", "FWD"} for position in positions):
        raise ValueError("Unknown position.")
    expected_ranks = {
        (season, position) for season in (*seasons, "pooled") for position in positions
    }
    expected_errors = {*seasons, "pooled"}
    if set(ranks) - expected_ranks or set(errors) - expected_errors:
        raise ValueError("Evidence contains cells outside the declared population.")
    if set(decision_by_season) - set(seasons):
        raise ValueError("Decision evidence contains an undeclared season.")
    for pair in ranks.values():
        if len(pair) != 2 or any(not _finite(value) or not -1 <= value <= 1 for value in pair):
            raise ValueError("Rank correlations must be finite and in [-1, 1].")
    for pair in errors.values():
        if len(pair) != 2 or any(not _finite(value) or value < 0 for value in pair):
            raise ValueError("MAE must be finite and non-negative.")
    if decision_mean is not None and not _finite(decision_mean):
        raise ValueError("Decision mean must be finite.")
    if decision_interval is not None and (
        len(decision_interval) != 2
        or any(not _finite(value) for value in decision_interval)
        or decision_interval[0] > decision_interval[1]
    ):
        raise ValueError("Decision interval must be finite and ordered.")
    if any(not _finite(value) for value in decision_by_season.values()):
        raise ValueError("Season decision means must be finite.")

    enough_seasons = len(seasons) >= policy.minimum_seasons
    rank_checks = [
        candidate - control >= -policy.maximum_cell_rank_loss
        for control, candidate in ranks.values()
    ]
    if all(("pooled", position) in ranks for position in positions):
        mean_gain = sum(ranks["pooled", p][1] - ranks["pooled", p][0] for p in positions) / len(
            positions
        )
        rank_checks.append(mean_gain >= policy.minimum_rank_gain)
    ranking = _state(rank_checks, enough_seasons and set(ranks) == expected_ranks)
    error = _state(
        [
            candidate <= control * (1 + policy.maximum_relative_mae_increase)
            for control, candidate in errors.values()
        ],
        enough_seasons and set(errors) == expected_errors,
    )
    decision_checks = [
        sum(value < 0 for value in decision_by_season.values()) <= policy.maximum_losing_seasons
    ]
    if decision_mean is not None:
        decision_checks.append(decision_mean >= policy.minimum_decision_gain)
    if decision_interval is not None:
        decision_checks.append(decision_interval[0] > 0)
    decision = _state(
        decision_checks,
        enough_seasons
        and decision_mean is not None
        and decision_interval is not None
        and set(decision_by_season) == set(seasons),
    )
    return PredictionGateResult(ranking, error, decision, policy.fingerprint)
