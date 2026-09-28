"""Offline decision review with explicit information provenance and user-owned weights."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from squadopt.application.top100_weight import Top100Counts, rebased_week, validate_top100_weight
from squadopt.contracts.preferences import DecisionPreferences
from squadopt.optimization import OptimizationConfig
from squadopt.planning import InitialSquadState, PlanningHorizon
from squadopt.planning.models import ChipAvailability, PlanningWeekResult
from squadopt.planning.recourse import ObservationNode, RecourseResult, optimize_observed_recourse
from squadopt.planning.recourse_chips import net_week_points


@dataclass(frozen=True)
class ObservationContext:
    """Declared provenance, not a certificate of probability calibration."""

    source_id: str
    issued_at: datetime
    evidence_cutoff: datetime
    probability_basis: str

    def validate(self, decision_cutoff: datetime) -> None:
        if any(
            not isinstance(s, str) or not s.strip()
            for s in (self.source_id, self.probability_basis)
        ):
            raise ValueError("Observation source and probability basis must be explicit.")
        dates = (self.evidence_cutoff, self.issued_at, decision_cutoff)
        if any(
            not isinstance(t, datetime) or t.tzinfo is None or t.utcoffset() is None for t in dates
        ):
            raise ValueError("Observation timestamps must be timezone-aware.")
        if not self.evidence_cutoff <= self.issued_at <= decision_cutoff:
            raise ValueError("Observation evidence and scenarios must precede the decision cutoff.")


@dataclass(frozen=True)
class PlannerOption:
    top100_weight: int
    rollout: RecourseResult
    base_expected_net: float
    minimum_node_base_net: float
    expected_hit_points: float


@dataclass(frozen=True)
class PlannerReview:
    selected_weight: int
    options: tuple[PlannerOption, ...]
    observations: ObservationContext
    # Selection is never overwritten by a higher weighted objective.
    calibration_verified: bool = False
    contract_version: str = "observed_planner_review_v1"


def _weighted(
    horizon: PlanningHorizon, counts: Top100Counts | None, weight: int
) -> PlanningHorizon:
    table = horizon.validated_copy().table.copy()
    if weight:
        if counts is None:
            raise ValueError("A nonzero Top100 option requires verified lagged counts.")
        support = table.player_id.map(lambda p: counts.counts.get(int(p), 0)).astype(float) / 100
        table["expected_points"] *= 1 + weight / 100 * support
    return PlanningHorizon(table)


def _raw_net(week: PlanningWeekResult, horizon: PlanningHorizon) -> float:
    frame = horizon.table.loc[horizon.table.gameweek.eq(week.gameweek)]
    points = {int(p): float(v) for p, v in zip(frame.player_id, frame.expected_points, strict=True)}
    return net_week_points(rebased_week(week, points))


def review_observed_plans(
    baseline: PlanningHorizon,
    initial: InitialSquadState,
    nodes: Sequence[ObservationNode],
    optimization: OptimizationConfig,
    *,
    context: ObservationContext,
    decision_cutoff: datetime,
    selected_weight: int = 0,
    alternatives: Sequence[int] = (0, 20, 50),
    counts: Top100Counts | None = None,
    preferences: DecisionPreferences | None = None,
    chips: ChipAvailability | None = None,
) -> PlannerReview:
    """Compare declared information policies; do not change a member's selection.

    Counts must come from load_top100_counts for this same capture. Timestamps and
    input hashes must be retained by the caller; a label cannot prove calibration.
    The minimum node is a sensitivity statistic, not a percentile or CVaR estimate.
    This opt-in service performs no publication, network call or model promotion.
    """
    context.validate(decision_cutoff)
    baseline = baseline.validated_copy()
    if len(baseline.gameweeks) not in (3, 5):
        raise ValueError("Planner review requires a three- or five-week window.")
    if len(alternatives) > 3:
        raise ValueError("Offer at most three alternative Top100 settings.")
    weights = tuple(
        dict.fromkeys(
            [
                validate_top100_weight(selected_weight),
                *(validate_top100_weight(w) for w in alternatives),
            ]
        )
    )
    if counts is not None and (
        counts.picks_gameweek != baseline.gameweeks[0] - 1
        or any(
            isinstance(v, bool) or not isinstance(v, int) or not 0 <= v <= 100
            for v in counts.counts.values()
        )
    ):
        raise ValueError("Top100 counts must be valid and from the previous gameweek.")
    if any(weights) and counts is None:
        raise ValueError("Nonzero alternatives require verified Top100 evidence.")
    options = []
    for weight in weights:
        result = optimize_observed_recourse(
            _weighted(baseline, counts, weight),
            initial,
            [
                ObservationNode(
                    n.observation_id, n.probability, _weighted(n.horizon, counts, weight)
                )
                for n in nodes
            ],
            optimization,
            candidate_count=1,
            value_extra_free_transfer=False,
            preferences=preferences,
            chips=chips,
            require_optimal=False,
            observation_proposals=True,
        )
        chosen = result.candidates[result.chosen_index]
        current = _raw_net(chosen.first_week, baseline)
        node_values = [
            current + sum(_raw_net(w, n.horizon) for w in b.plan.weeks)
            for b, n in zip(chosen.continuations, nodes, strict=True)
        ]
        options.append(
            PlannerOption(
                weight,
                result,
                sum(n.probability * v for n, v in zip(nodes, node_values, strict=True)),
                min(node_values),
                chosen.first_week.transfer_hit_points
                + sum(
                    b.probability * float(b.plan.total_transfer_hit_points or 0)
                    for b in chosen.continuations
                ),
            )
        )
    return PlannerReview(selected_weight, tuple(options), context)
