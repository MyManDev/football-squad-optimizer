"""Read-only football candidate handoff: forecasts, plans, shared worlds and rival utility.

This application service is explicitly opt-in. It does not mutate a promoted model,
owner squad or publication. A caller must supply captured decision-time inputs.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

import pandas as pd

from squadopt.evaluation.models import FrozenSquadDecision
from squadopt.evaluation.scoring import complete_optimization_decision
from squadopt.live.football_horizon import build_football_horizon
from squadopt.optimization import OptimizationConfig, OptimizationResult, SolverStatus
from squadopt.planning import InitialSquadState, PlanningHorizon, TransferPlanResult
from squadopt.planning.horizon import ProjectionHorizon, to_planning_horizon
from squadopt.planning.models import ChipAvailability, PlanningWeekResult, TransferPlanningConfig
from squadopt.planning.optimizer import optimize_transfer_plan
from squadopt.planning.pricing import sell_price_tenths
from squadopt.planning.recourse import ObservationNode, RecourseResult, optimize_observed_recourse
from squadopt.planning.recourse_chips import net_week_points
from squadopt.prediction.football import FixtureFootballModel
from squadopt.prediction.football_contextual import CONTEXTUAL_MODEL_VERSION
from squadopt.scenarios.football import (
    FootballDraws,
    sample_football_events,
    score_football_candidates,
)
from squadopt.scenarios.football_diagnostics import football_mean_diagnostics


@dataclass(frozen=True)
class FootballCandidatePreview:
    projections: ProjectionHorizon
    components: pd.DataFrame
    control: TransferPlanResult
    recourse: RecourseResult | None
    decisions: Mapping[str, FrozenSquadDecision]
    draws: FootballDraws | None
    scenario_scores: pd.DataFrame
    recommendation: str
    # Different objective/horizon, deliberately separate from the expected-total recommendation.
    one_week_rival_recommendation: str | None
    rival_simulation_evaluation: Mapping[str, float] | None
    contract_version: str = "football_candidate_preview_v1"
    scenario_mean_diagnostics: Mapping[str, float] = field(default_factory=dict)
    scenario_selection_evaluation: Mapping[str, float] | None = None


def freeze_planning_week(week: PlanningWeekResult) -> FrozenSquadDecision:
    """Use the same deterministic bench/vice completion as existing squad evaluation."""
    return complete_optimization_decision(
        OptimizationResult(
            SolverStatus.OPTIMAL,
            week.selected_squad,
            week.starting_xi,
            week.bench,
            week.captain,
            int(week.selected_squad.buy_price_tenths.sum()),
            week.projected_score,
            week.discounted_objective_contribution,
            {},
        )
    )


def preview_football_candidate(
    model: FixtureFootballModel,
    history: pd.DataFrame,
    roster: pd.DataFrame,
    fixtures: pd.DataFrame,
    initial: InitialSquadState,
    purchase_prices: Mapping[object, int],
    *,
    gameweeks: Sequence[int],
    season: str,
    source_snapshot_id: str,
    captured_at: pd.Timestamp,
    optimization: OptimizationConfig,
    transfer: TransferPlanningConfig | None = None,
    observations: Sequence[ObservationNode] = (),
    role_transitions: bool = False,
    candidate_count: int = 3,
    samples: int = 256,
    seed: int = 0,
    rival: FrozenSquadDecision | None = None,
    rival_hit_points: float = 0,
    chips: ChipAvailability | None = None,
    scenario_selection: bool = False,
) -> FootballCandidatePreview:
    """Run the complete offline candidate path, with real holding-price accounting.

    Observation probabilities/forecasts are supplied ex ante by the caller; this
    service never derives them from held-out outcomes. Rival utility is P(win) +
    0.5 P(tie) for ONE WEEK on identical draws, not a claim about final Top100 rank.
    """
    if isinstance(samples, bool) or not isinstance(samples, int) or not 1 <= samples <= 10000:
        raise ValueError("samples must be an integer between 1 and 10000.")
    if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0:
        raise ValueError("seed must be a nonnegative integer.")
    if not isinstance(scenario_selection, bool):
        raise ValueError("scenario_selection must be a boolean.")
    if scenario_selection and samples < 2:
        raise ValueError("Scenario selection needs separate selection and evaluation draws.")
    if scenario_selection and (
        optimization.bench_weight != 0
        or (
            transfer is not None
            and (
                transfer.horizon_discount_factor != 1
                or transfer.banked_transfer_value_points != 0
                or transfer.chip_holding_value_points
                or transfer.transfer_hit_cost_points != transfer.hit_points_charged
            )
        )
        or (
            chips is not None
            and any(
                p.holding_value_points not in (None, 0)
                for name in chips.available
                for p in chips.windows_for(name)
            )
        )
    ):
        raise ValueError(
            "Scenario net-point selection requires zero bench/terminal weights "
            "and actual undiscounted hits."
        )
    if rival is not None and set(rival.squad.player_id) - set(roster.player_id):
        raise ValueError("The rival squad must be covered by the captured roster.")
    if rival is not None and samples < 2:
        raise ValueError("Rival selection needs separate selection and evaluation draws.")
    if set(purchase_prices) != set(initial.squad_player_ids):
        raise ValueError("The purchase book must cover exactly the initial squad.")
    projections, components = build_football_horizon(
        model,
        history,
        roster,
        fixtures,
        gameweeks=gameweeks,
        season=season,
        source_snapshot_id=source_snapshot_id,
        captured_at=captured_at,
        role_transitions=role_transitions,
    )
    table = to_planning_horizon(projections).table.copy()
    for index, row in table.iterrows():
        if row.player_id in purchase_prices:
            table.at[index, "sell_price_tenths"] = sell_price_tenths(
                current_tenths=int(row.buy_price_tenths),
                purchase_tenths=purchase_prices[row.player_id],
            )
    horizon = PlanningHorizon(table)
    control = optimize_transfer_plan(
        horizon, initial, optimization, transfer, chips=chips, linearization_level=2
    )
    if control.solver_status is not SolverStatus.OPTIMAL:
        raise ValueError("Candidate preview requires a proved optimal control plan.")
    recourse = None
    decisions = {"control": freeze_planning_week(control.weeks[0])}
    hits = {"control": control.weeks[0].transfer_hit_points}
    chosen_chips = {"control": control.weeks[0].chip}
    recommendation = "control"
    continuations = {"control": sum(net_week_points(w) for w in control.weeks[1:])}
    if observations:
        # Apply the same owner purchase book in every possible observation.
        priced = []
        for node in observations:
            future = node.horizon.validated_copy().table.copy()
            for index, row in future.iterrows():
                if row.player_id in purchase_prices:
                    future.at[index, "sell_price_tenths"] = sell_price_tenths(
                        current_tenths=int(row.buy_price_tenths),
                        purchase_tenths=purchase_prices[row.player_id],
                    )
            priced.append(
                ObservationNode(node.observation_id, node.probability, PlanningHorizon(future))
            )
        recourse = optimize_observed_recourse(
            horizon,
            initial,
            priced,
            optimization,
            transfer,
            candidate_count=candidate_count,
            chips=chips,
        )
        for i, candidate in enumerate(recourse.candidates):
            key = f"recourse_{i}"
            decisions[key] = freeze_planning_week(candidate.first_week)
            hits[key] = candidate.first_week.transfer_hit_points
            chosen_chips[key] = candidate.first_week.chip
            continuations[key] = candidate.expected_net_points - net_week_points(
                candidate.first_week
            )
        recommendation = f"recourse_{recourse.chosen_index}"
    elif scenario_selection:
        if (
            isinstance(candidate_count, bool)
            or not isinstance(candidate_count, int)
            or not 1 <= candidate_count <= 20
        ):
            raise ValueError("candidate_count must be an integer between 1 and 20.")
        excluded = [frozenset(control.weeks[0].selected_squad.player_id)]
        for i in range(1, candidate_count):
            alternative = optimize_transfer_plan(
                horizon,
                initial,
                optimization,
                transfer,
                chips=chips,
                excluded_squads=excluded,
                linearization_level=2,
            )
            if alternative.solver_status is SolverStatus.INFEASIBLE:
                break
            if alternative.solver_status is not SolverStatus.OPTIMAL:
                raise ValueError("Scenario menu requires proved optimal candidate plans.")
            week = alternative.weeks[0]
            key = f"scenario_{i}"
            decisions[key] = freeze_planning_week(week)
            hits[key], chosen_chips[key] = week.transfer_hit_points, week.chip
            continuations[key] = sum(net_week_points(w) for w in alternative.weeks[1:])
            excluded.append(frozenset(week.selected_squad.player_id))
    candidate_names = tuple(decisions)
    if rival is not None:
        decisions["rival"] = rival
        hits["rival"] = rival_hit_points
    current = (
        components.loc[components.GW.eq(projections.target_gameweeks[0])]
        if not components.empty
        else components
    )
    if current.empty:
        # Every player is explicitly blank. No fictitious match needs to be sampled.
        draws = None
        scores = pd.DataFrame(
            {
                "scenario_id": [0] * len(decisions),
                "candidate": list(decisions),
                "net_points": [-hits[k] for k in decisions],
            }
        )
        if rival is not None:
            scores["rival_difference"] = scores.net_points + rival_hit_points
            scores["beat_rival"] = scores.rival_difference.gt(0)
    else:
        draws = sample_football_events(
            current,
            samples=samples,
            seed=seed,
            coherent_lineups=model.model_version == CONTEXTUAL_MODEL_VERSION,
        )
        scores = score_football_candidates(
            draws,
            decisions,
            hits=hits,
            chips=chosen_chips,
            rival="rival" if rival is not None else None,
            blank_player_ids=frozenset(roster.player_id) - frozenset(current.player_code),
        )
    rival_choice = None
    rival_evaluation = None
    selection_evaluation = None
    if rival is not None or scenario_selection:
        scenario_ids = sorted(scores.scenario_id.unique())
        selection_ids = scenario_ids[: max(1, len(scenario_ids) // 2)]
        scores["scenario_partition"] = scores.scenario_id.isin(selection_ids).map(
            {True: "selection", False: "evaluation"}
        )
    if scenario_selection:
        # With observations, compare only candidates with the SAME information tree;
        # the deterministic control is a report-only reference, not an unequal competitor.
        eligible = (
            tuple(k for k in candidate_names if k.startswith("recourse_"))
            if recourse
            else candidate_names
        )
        means = (
            scores.loc[scores.scenario_partition.eq("selection")]
            .groupby("candidate")
            .net_points.mean()
        )
        recommendation = max(eligible, key=lambda k: float(means[k]) + continuations[k])
        evaluated = scores.loc[
            scores.candidate.eq(recommendation) & scores.scenario_partition.eq("evaluation")
        ]
        if not evaluated.empty:
            selection_evaluation = {
                "draws": float(len(evaluated)),
                "first_week_mean_net_points": float(evaluated.net_points.mean()),
                "analytic_continuation_net_points": continuations[recommendation],
                "combined_estimate": float(evaluated.net_points.mean())
                + continuations[recommendation],
            }
    if rival is not None:
        scores["win_utility"] = scores.rival_difference.gt(0).astype(
            float
        ) + 0.5 * scores.rival_difference.eq(0)
        utility = (
            scores.loc[scores.scenario_partition.eq("selection")]
            .groupby("candidate")
            .win_utility.mean()
        )
        rival_choice = max(candidate_names, key=lambda name: float(utility[name]))
        evaluation = scores.loc[
            scores.candidate.eq(rival_choice) & scores.scenario_partition.eq("evaluation")
        ]
        if not evaluation.empty:
            rival_evaluation = {
                "draws": float(len(evaluation)),
                "win_utility": float(evaluation.win_utility.mean()),
                "mean_net_difference": float(evaluation.rival_difference.mean()),
            }
    return FootballCandidatePreview(
        projections,
        components,
        control,
        recourse,
        decisions,
        draws,
        scores,
        recommendation,
        rival_choice,
        rival_evaluation,
        scenario_mean_diagnostics=football_mean_diagnostics(current, draws)
        if draws is not None
        else {},
        scenario_selection_evaluation=selection_evaluation,
    )
