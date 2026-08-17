"""Assemble a recommendation and the provenance chain that lets it be rebuilt.

A squad on its own is not a deliverable. What makes it one is the chain: which capture it
was read from, when that capture was taken, which deadline it was taken before, which model
projected it, and what the projection fingerprinted to. Any link missing and the
recommendation cannot be checked after the fact — and a recommendation nobody can check is
indistinguishable from a guess.

The fingerprint covers the projection, not the squad. Two runs that project identically must
agree on the squad because the optimizer is deterministic given identical input, so
fingerprinting the input is the stronger claim: it says the recommendation followed from the
capture rather than that two runs happened to coincide.
"""

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Final

import pandas as pd

from squadopt.data.errors import DataSourceError
from squadopt.live.recommendation import Projection, RecommendationInputs
from squadopt.live.risk import (
    LiveResidualHistory,
    LiveRiskDiagnostics,
    evaluate_live_risk,
    risk_not_requested,
)
from squadopt.live.rules import SeasonRules
from squadopt.live.transfers import HeldSquad, TransferDecision, plan_transfers
from squadopt.optimization import OptimizationConfig, SolverStatus, optimize_squad
from squadopt.optimization.models import OptimizationResult
from squadopt.scenarios import ScenarioConfig, ScenarioEvaluationConfig

REPORT_CONTRACT_VERSION: Final = "live_recommendation_v3"

# Columns a reader needs to act on a recommendation, in reading order.
SQUAD_COLUMNS: Final = ("name", "team_id", "position", "price_tenths", "expected_points")

# Statuses that mean the solver returned a squad it proved optimal. Anything else is
# reported rather than presented as a recommendation, because a squad found before the
# clock ran out is not the best squad for the projection it came from.
PROVEN_STATUSES: Final = (SolverStatus.OPTIMAL,)


@dataclass(frozen=True, slots=True)
class Recommendation:
    """A squad, the decisions inside it, and everything needed to rebuild it."""

    contract_version: str
    snapshot_id: str
    captured_at_utc: str
    season: str
    gameweek: int
    deadline_utc: str
    model_name: str
    model_version: str
    feature_contract_version: str
    prediction_fingerprint: str
    solver_status: str
    squad: pd.DataFrame
    starting_xi: pd.DataFrame
    bench: pd.DataFrame
    captain: pd.Series
    total_cost_tenths: int
    projected_score: float
    diagnostics: Mapping[str, object]
    risk: LiveRiskDiagnostics = field(default_factory=risk_not_requested)
    transfers: TransferDecision | None = None
    """Present for a mid-season decision made from the held squad; absent for the opening
    squad, whose report and ledger entry are unchanged by this field."""

    @property
    def solver_proved_optimal(self) -> bool:
        """Whether the returned squad is the best one for its projection."""

        return self.solver_status == SolverStatus.OPTIMAL.name


def projection_fingerprint(table: pd.DataFrame) -> str:
    """Digest the projection the optimizer was given.

    Serialised through the contract columns in a fixed order so the digest depends on the
    values and not on how the frame happened to be assembled.
    """

    columns = [column for column in ("player_id", *SQUAD_COLUMNS) if column in table.columns]
    ordered = table.loc[:, columns].sort_values("player_id", kind="stable")
    return hashlib.sha256(ordered.to_csv(index=False).encode("utf-8")).hexdigest()


def build_recommendation(
    inputs: RecommendationInputs,
    projection: Projection,
    *,
    optimization: OptimizationConfig | None = None,
    risk_history: LiveResidualHistory | None = None,
    risk_scenario_config: ScenarioConfig | None = None,
    risk_evaluation_config: ScenarioEvaluationConfig | None = None,
) -> Recommendation:
    """Optimise the projected pool and return the recommendation with its provenance.

    An infeasible solve raises. A squad that could not be built is not a result to report
    quietly: it means the pool, the budget or the constraints disagree, and continuing
    would hand back an empty recommendation dressed as an answer.
    """

    settings = OptimizationConfig() if optimization is None else optimization
    pool = projection.table.loc[
        :, ["player_id", "name", "team_id", "position", "price_tenths", "expected_points"]
    ]
    result: OptimizationResult = optimize_squad(pool, settings)

    # A missing captain, cost or score means the same thing as an empty squad: nothing was
    # solved. Checked together so a partially populated result cannot slip through as an
    # answer — a recommendation without a captain is not a recommendation.
    if (
        result.selected_squad.empty
        or result.captain is None
        or result.total_cost_tenths is None
        or result.projected_score is None
    ):
        raise DataSourceError(
            f"The solver returned {result.solver_status.name} with no squad for "
            f"{inputs.season} gameweek {inputs.deadline.gameweek}. The pool, the budget and "
            "the squad constraints do not admit a solution."
        )
    if result.solver_status not in PROVEN_STATUSES:
        raise DataSourceError(
            f"The solver returned {result.solver_status.name} for {inputs.season} "
            f"gameweek {inputs.deadline.gameweek} but did not prove the squad optimal. "
            "A live recommendation requires an OPTIMAL result."
        )

    risk = (
        risk_not_requested()
        if risk_history is None
        else evaluate_live_risk(
            inputs,
            projection,
            result,
            risk_history,
            scenario_config=risk_scenario_config,
            evaluation_config=risk_evaluation_config,
        )
    )

    return Recommendation(
        contract_version=REPORT_CONTRACT_VERSION,
        snapshot_id=inputs.snapshot_id,
        captured_at_utc=inputs.captured_at_utc,
        season=inputs.season,
        gameweek=inputs.deadline.gameweek,
        deadline_utc=inputs.deadline.deadline_utc,
        model_name=str(projection.diagnostics["model_name"]),
        model_version=str(projection.diagnostics["model_version"]),
        feature_contract_version=str(projection.diagnostics["feature_contract_version"]),
        prediction_fingerprint=projection_fingerprint(projection.table),
        solver_status=result.solver_status.name,
        squad=result.selected_squad,
        starting_xi=result.starting_xi,
        bench=result.bench,
        captain=result.captain,
        total_cost_tenths=int(result.total_cost_tenths),
        projected_score=float(result.projected_score),
        diagnostics={
            **dict(projection.diagnostics),
            **dict(result.diagnostics),
            "unavailable_players_in_pool": len(projection.unavailable_players),
            "budget_tenths": settings.budget_tenths,
            "bench_weight": settings.bench_weight,
        },
        risk=risk,
    )


def build_transfer_recommendation(
    inputs: RecommendationInputs,
    projection: Projection,
    held: HeldSquad,
    rules: SeasonRules,
    *,
    optimization: OptimizationConfig | None = None,
    chip: str | None = None,
) -> Recommendation:
    """Decide a mid-season deadline from the held squad and return it with provenance.

    The squad reported is the squad after the transfers; ``total_cost_tenths`` is what
    it would sell for (the wealth the game shows), not what it cost, and the budget check
    a reader should make is that the bank after is not negative.
    """

    settings = OptimizationConfig() if optimization is None else optimization
    plan, decision, _ = plan_transfers(
        inputs, projection, held, rules, optimization=settings, chip=chip
    )
    if plan.solver_status not in PROVEN_STATUSES:
        raise DataSourceError(
            f"The transfer planner returned {plan.solver_status.name} for {inputs.season} "
            f"gameweek {inputs.deadline.gameweek} but did not prove the plan optimal. "
            "A live decision requires an OPTIMAL result."
        )
    week = plan.weeks[0]
    return Recommendation(
        contract_version=REPORT_CONTRACT_VERSION,
        snapshot_id=inputs.snapshot_id,
        captured_at_utc=inputs.captured_at_utc,
        season=inputs.season,
        gameweek=inputs.deadline.gameweek,
        deadline_utc=inputs.deadline.deadline_utc,
        model_name=str(projection.diagnostics["model_name"]),
        model_version=str(projection.diagnostics["model_version"]),
        feature_contract_version=str(projection.diagnostics["feature_contract_version"]),
        prediction_fingerprint=projection_fingerprint(projection.table),
        solver_status=plan.solver_status.name,
        squad=week.selected_squad,
        starting_xi=week.starting_xi,
        bench=week.bench,
        captain=week.captain,
        total_cost_tenths=int(decision.squad_sell_value_tenths),
        projected_score=float(week.projected_score),
        diagnostics={
            **dict(projection.diagnostics),
            **{f"planner_{key}": value for key, value in dict(plan.diagnostics).items()},
            "unavailable_players_in_pool": len(projection.unavailable_players),
            "budget_tenths": settings.budget_tenths,
            "bench_weight": settings.bench_weight,
            "decision_kind": "transfer",
        },
        risk=risk_not_requested(),
        transfers=decision,
    )


def _frame_lines(frame: pd.DataFrame, title: str) -> list[str]:
    columns = [column for column in SQUAD_COLUMNS if column in frame.columns]
    rendered = frame.loc[:, columns]
    return [f"\n{title}", "-" * len(title), rendered.to_string(index=False)]


def render(recommendation: Recommendation) -> str:
    """Render the recommendation as text, provenance first.

    Provenance leads rather than trails, because the first question about a squad is what
    it was built from and the second is whether that is still current.
    """

    lines = [
        f"Recommendation for {recommendation.season} gameweek {recommendation.gameweek}",
        "=" * 60,
        f"  deadline            {recommendation.deadline_utc}",
        f"  snapshot            {recommendation.snapshot_id}",
        f"  captured at         {recommendation.captured_at_utc}",
        f"  report contract     {recommendation.contract_version}",
        f"  model               {recommendation.model_name}@{recommendation.model_version}",
        f"  feature contract    {recommendation.feature_contract_version}",
        f"  projection digest   {recommendation.prediction_fingerprint[:16]}…",
        f"  solver              {recommendation.solver_status}",
        (
            f"  squad cost          {recommendation.total_cost_tenths / 10:.1f}"
            if recommendation.transfers is None
            else f"  squad sell value    {recommendation.total_cost_tenths / 10:.1f}"
        ),
        f"  projected score     {recommendation.projected_score:.4f}",
    ]

    if not recommendation.solver_proved_optimal:
        lines += [
            "",
            "  WARNING: the solver did not prove this squad optimal, so it is the best one",
            "  found before the limit rather than the best one for this projection.",
        ]

    risk = recommendation.risk
    lines += [
        "",
        "Distributional risk",
        "-" * 19,
        f"  status              {risk.status.value}",
    ]
    if risk.is_available:
        assert risk.metrics is not None
        assert risk.scenario_fingerprint is not None
        metrics = risk.metrics
        lines += [
            f"  lower {metrics.lower_quantile_probability:.0%} quantile  "
            f"{metrics.lower_quantile_score:.4f}",
            f"  mean worst {metrics.worst_fraction:.0%}       "
            f"{metrics.mean_worst_fraction_score:.4f}",
            f"  P(score < {metrics.points_threshold:g})    "
            f"{metrics.probability_below_threshold:.4f}",
            f"  scenarios           {metrics.scenario_count}",
            f"  scenario digest     {risk.scenario_fingerprint[:16]}…",
            f"  residual source     {risk.residual_provenance.get('source_id')}",
            "  residual digest     "
            f"{str(risk.residual_provenance.get('residual_fingerprint'))[:16]}…",
        ]
    else:
        blockers = ", ".join(blocker.value for blocker in risk.blockers) or "none"
        lines += [
            f"  reason              {risk.reason}",
            f"  blockers            {blockers}",
            "  No lower-tail number is printed without supporting residual evidence.",
        ]

    transfers = recommendation.transfers
    if transfers is not None:
        lines += [
            "",
            "Transfers",
            "-" * 9,
            f"  from gameweek       {transfers.previous_gameweek} squad",
            f"  transfers           {transfers.transfer_count} "
            f"({transfers.paid_transfer_count} paid, {transfers.transfer_hit_points:.0f} pts)",
            f"  free transfers      {transfers.free_transfers_before} before, "
            f"{transfers.free_transfers_after} after",
            f"  bank                {transfers.bank_before_tenths / 10:.1f} before, "
            f"{transfers.bank_after_tenths / 10:.1f} after",
            f"  squad sell value    {transfers.squad_sell_value_tenths / 10:.1f}",
            f"  chip                {transfers.chip or 'none'}",
        ]
        if not transfers.transfers_in.empty:
            lines += _frame_lines(transfers.transfers_out, "Out")
            lines += _frame_lines(transfers.transfers_in, "In")

    lines += _frame_lines(recommendation.starting_xi, "Starting XI")
    lines += _frame_lines(recommendation.bench, "Bench")
    captain = recommendation.captain
    lines += [
        "",
        "Captain",
        "-" * 7,
        f"  {captain['name']} ({captain['position']}, {captain['team_id']}) "
        f"projected {float(captain['expected_points']):.4f}, counted twice",
    ]

    diagnostics = recommendation.diagnostics
    lines += [
        "",
        "Projection provenance",
        "-" * 21,
        f"  players in pool           {diagnostics.get('players')}",
        f"  projected from history    {diagnostics.get('players_with_prior_record')}",
        f"  priced from the prior     {diagnostics.get('players_priced_from_prior')}",
        f"  ruled out by availability {diagnostics.get('availability_unavailable')}",
        f"  reduced by availability   {diagnostics.get('availability_reduced')}",
        "",
        "  The projection is the operational control, the deterministic baseline. The",
        "  two-stage production candidate was measured against the pre-registered gates",
        "  and did not clear them, so it does not decide a real squad.",
    ]
    return "\n".join(lines) + "\n"
