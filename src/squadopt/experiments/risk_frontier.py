"""Mean-versus-downside frontier measurement over a risk-aversion ladder.

The scenario-aware search showed that risk aversion pays a premium in *mean* realized
points, because the search objective is the mean. Whether that premium buys downside
protection is a different question, and it needs different metrics: the empirical
lower quantile, the worst-tail mean, and the probability of falling below a threshold,
all computed over the same realized fold scores. This module measures that frontier
for one fixed policy anchor, so the trade can be read as numbers instead of argued.
"""

import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final

from squadopt.bayesopt import BayesianCandidate
from squadopt.experiments.config import ExperimentExecutionError
from squadopt.experiments.scenario_policy_objective import ScenarioPolicyObjective

RISK_FRONTIER_CONTRACT_VERSION: Final = "risk_frontier_v1"


def _empirical_lower_quantile(scores: tuple[float, ...], quantile: float) -> float:
    """Return the order statistic at the given lower quantile, conservatively.

    The index rounds down (`ceil(q*n) - 1`), so the reported quantile never claims a
    better floor than the sample supports.
    """

    ordered = sorted(scores)
    index = max(0, math.ceil(quantile * len(ordered)) - 1)
    return ordered[index]


def _worst_tail_mean(scores: tuple[float, ...], fraction: float) -> float:
    ordered = sorted(scores)
    count = max(1, math.ceil(fraction * len(ordered)))
    tail = ordered[:count]
    return sum(tail) / len(tail)


@dataclass(frozen=True, slots=True)
class RiskFrontierPoint:
    """Realized-score summaries for one risk-aversion level of the anchor policy."""

    risk_aversion: float
    mean_realized_squad_points: float
    realized_stddev: float
    lower_quantile_score: float
    worst_tail_mean_score: float
    probability_below_threshold: float
    scored_folds: int

    def __post_init__(self) -> None:
        values = (
            self.mean_realized_squad_points,
            self.realized_stddev,
            self.lower_quantile_score,
            self.worst_tail_mean_score,
            self.probability_below_threshold,
        )
        if any(not math.isfinite(value) for value in values):
            raise ExperimentExecutionError("Frontier metrics must be finite.")
        if self.scored_folds < 1:
            raise ExperimentExecutionError("scored_folds must be positive.")


@dataclass(frozen=True, slots=True)
class RiskFrontierResult:
    """The complete frontier, ordered by ascending risk aversion."""

    points: tuple[RiskFrontierPoint, ...]
    form_window: int
    bench_weight: float
    lower_quantile: float
    worst_fraction: float
    points_threshold: float
    objective_configuration_fingerprint: str
    contract_version: str = RISK_FRONTIER_CONTRACT_VERSION

    def __post_init__(self) -> None:
        if self.contract_version != RISK_FRONTIER_CONTRACT_VERSION:
            raise ExperimentExecutionError("Unsupported risk frontier contract_version.")
        if len(self.points) < 2:
            raise ExperimentExecutionError(
                "A frontier needs at least two risk-aversion levels to compare."
            )
        levels = [point.risk_aversion for point in self.points]
        if levels != sorted(levels) or len(set(levels)) != len(levels):
            raise ExperimentExecutionError(
                "Frontier points must be ordered by unique ascending risk_aversion."
            )
        if not any(point.risk_aversion == 0.0 for point in self.points):
            raise ExperimentExecutionError(
                "The frontier must include the risk-neutral 0.0 level as its baseline."
            )

    @property
    def risk_neutral(self) -> RiskFrontierPoint:
        """Return the risk-neutral baseline every premium is measured against."""

        return next(point for point in self.points if point.risk_aversion == 0.0)


def measure_risk_frontier(
    objective: ScenarioPolicyObjective,
    *,
    form_window: int,
    bench_weight: float,
    risk_aversion_levels: tuple[float, ...],
    lower_quantile: float = 0.10,
    worst_fraction: float = 0.10,
    points_threshold: float = 40.0,
) -> RiskFrontierResult:
    """Evaluate one anchor policy across a risk-aversion ladder.

    Every level is evaluated on identical folds with identical scenarios, so any
    difference between frontier points is attributable to `risk_aversion` alone.
    """

    if not isinstance(objective, ScenarioPolicyObjective):
        raise ExperimentExecutionError("objective must be a ScenarioPolicyObjective.")
    for name, value in (("lower_quantile", lower_quantile), ("worst_fraction", worst_fraction)):
        if not isinstance(value, float) or not 0.0 < value < 1.0:
            raise ExperimentExecutionError(f"{name} must lie strictly in (0, 1).")
    if not isinstance(points_threshold, float) or not math.isfinite(points_threshold):
        raise ExperimentExecutionError("points_threshold must be a finite number.")
    if (
        not isinstance(risk_aversion_levels, tuple)
        or len(risk_aversion_levels) < 2
        or len(set(risk_aversion_levels)) != len(risk_aversion_levels)
    ):
        raise ExperimentExecutionError(
            "risk_aversion_levels must be a tuple of at least two unique levels."
        )
    if 0.0 not in risk_aversion_levels:
        raise ExperimentExecutionError(
            "risk_aversion_levels must include the risk-neutral 0.0 baseline."
        )

    points: list[RiskFrontierPoint] = []
    for level in sorted(risk_aversion_levels):
        candidate = BayesianCandidate(
            {
                "form_window": form_window,
                "bench_weight": bench_weight,
                "risk_aversion": level,
            }
        )
        mean_points = objective(candidate, objective.development_fold_ids)
        record: Mapping[str, object] = objective.records[candidate.candidate_id]
        raw_scores = record["fold_scores"]
        if not isinstance(raw_scores, tuple) or not raw_scores:
            raise ExperimentExecutionError(
                "The objective did not record per-fold scores; the frontier cannot "
                "be measured from means alone."
            )
        scores = tuple(float(score) for score in raw_scores)
        variance = sum((score - mean_points) ** 2 for score in scores) / len(scores)
        points.append(
            RiskFrontierPoint(
                risk_aversion=float(level),
                mean_realized_squad_points=mean_points,
                realized_stddev=math.sqrt(variance),
                lower_quantile_score=_empirical_lower_quantile(scores, lower_quantile),
                worst_tail_mean_score=_worst_tail_mean(scores, worst_fraction),
                probability_below_threshold=(
                    sum(1 for score in scores if score < points_threshold) / len(scores)
                ),
                scored_folds=len(scores),
            )
        )

    return RiskFrontierResult(
        points=tuple(points),
        form_window=form_window,
        bench_weight=bench_weight,
        lower_quantile=lower_quantile,
        worst_fraction=worst_fraction,
        points_threshold=points_threshold,
        objective_configuration_fingerprint=(objective.config.configuration_fingerprint),
    )
