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
from collections.abc import Mapping, Sequence
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
from squadopt.optimization import (
    OptimizationConfig,
    SolverStatus,
    optimize_squad,
    wall_clock_stopped_the_search,
)
from squadopt.optimization.models import OptimizationResult
from squadopt.prediction.elite_evidence import (
    COMPONENT_ELITE_MODEL_VERSION,
    ELITE_EVIDENCE_MODEL_VERSION,
    ELITE_EVIDENCE_POLICY_VERSION,
)
from squadopt.scenarios import RivalSquad, ScenarioConfig, ScenarioEvaluationConfig

REPORT_CONTRACT_VERSION: Final = "live_recommendation_v3"

# Columns a reader needs to act on a recommendation, in reading order.
SQUAD_COLUMNS: Final = ("name", "team_id", "position", "price_tenths", "expected_points")

# Statuses that mean the solver returned a squad it proved optimal. Anything else is
# reported rather than presented as a recommendation, because a squad found before the
# clock ran out is not the best squad for the projection it came from.
PROVEN_STATUSES: Final = (SolverStatus.OPTIMAL,)

#: The live solve's deterministic budget, in CP-SAT deterministic units. Only a budget
#: that is a function of the inputs may decide where the search stops: the primary proves
#: the objective, and the lexicographic tie-break then picks the canonical member of the
#: primal-optimal set, so a tie-break cut short hands that choice to whatever the machine
#: was doing. Before this constant existed the live path ran with no deterministic budget
#: at all, and the tie-break's only stopping rule was ``solver_time_limit_seconds``.
#:
#: Measured on the recorded opening-gameweek pool (``data/ledger/2026-27/gw01``, 600
#: players) at this configuration: the primary spends 0.641 units, the tie-break 2.871,
#: 3.512 in total, and the tie-break proves its optimum. 60.0 is seventeen times that, so
#: it does not bind on work this pool has been seen to need; when it does bind, it binds
#: at the same place on every machine and ``deterministic_time_budget_exhausted`` says so.
LIVE_DETERMINISTIC_UNITS: Final = 60.0

#: The wall-clock ceiling is a safety stop, never a budget: it exists so a pathological
#: solve ends, not so it decides. The same recorded pool spends its 3.512 deterministic
#: units in 4.40s-4.52s of wall clock over five runs on the development machine, and the
#: whole 60-unit budget projects to roughly 76s at that rate. 300.0 is sixty-six times the
#: measured solve and about four times the budget's projected cost, so the clock cannot
#: reach the search first on work this machine has been seen to do. ``build_recommendation``
#: refuses a solve this ceiling did cut rather than recording it as proven.
LIVE_WALL_CEILING_SECONDS: Final = 300.0


def live_optimization_config() -> OptimizationConfig:
    """The live path's solver settings: a deterministic budget under a wall-clock stop."""

    return OptimizationConfig(
        solver_time_limit_seconds=LIVE_WALL_CEILING_SECONDS,
        solver_deterministic_time_limit=LIVE_DETERMINISTIC_UNITS,
    )


def _refuse_a_clock_stopped_solve(
    inputs: RecommendationInputs,
    status: SolverStatus,
    diagnostics: Mapping[str, object],
    what: str,
) -> None:
    """Refuse a live decision the wall clock, not the deterministic budget, ended.

    ``OPTIMAL`` on its own does not mean the answer replays. The status reports the
    *primary* solve, which proves the objective value; the identity of the squad among
    the plans that reach that value is settled afterwards by the lexicographic tie-break,
    and a tie-break the clock cut off returns whichever member of the optimal set it
    happened to hold. Recording that as ``OPTIMAL`` states a proof the run does not have,
    and the ledger keeps it forever. So the run fails here instead: where a clock stops a
    search is a function of the machine, not of the inputs.
    """

    if not wall_clock_stopped_the_search(status, diagnostics):
        return
    raise DataSourceError(
        f"The {what} returned {status.name} for {inputs.season} gameweek "
        f"{inputs.deadline.gameweek}, but the wall-clock safety cap of "
        f"{diagnostics.get('solver_time_limit_seconds')!r}s stopped the search before its "
        f"deterministic budget of {diagnostics.get('solver_deterministic_time_limit')!r} "
        f"units — {diagnostics.get('deterministic_time_used')!r} units were spent, and the "
        f"tie-break reported {diagnostics.get('tiebreak_status')!r}. Where the clock stops "
        "a search is a function of the machine, not of the inputs, so this squad is not "
        "the squad a second run would find and may not be recorded as proven."
    )


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
    return hashlib.sha256(
        ordered.to_csv(index=False, lineterminator="\n").encode("utf-8")
    ).hexdigest()


def build_recommendation(
    inputs: RecommendationInputs,
    projection: Projection,
    *,
    optimization: OptimizationConfig | None = None,
    risk_history: LiveResidualHistory | None = None,
    risk_scenario_config: ScenarioConfig | None = None,
    risk_evaluation_config: ScenarioEvaluationConfig | None = None,
    risk_fixture_counts: Mapping[int, int] | None = None,
    risk_rivals: Sequence[RivalSquad] = (),
) -> Recommendation:
    """Optimise the projected pool and return the recommendation with its provenance.

    ``risk_fixture_counts`` (player code -> fixtures this gameweek, from the capture's
    calendar) and ``risk_rivals`` pass through to the risk layer when residual history
    is supplied: the calendar widens double-gameweek players' spread under the scenario
    config's ``double_gameweek_scale``, and each rival is scored in the same scenarios.

    An infeasible solve raises. A squad that could not be built is not a result to report
    quietly: it means the pool, the budget or the constraints disagree, and continuing
    would hand back an empty recommendation dressed as an answer.
    """

    settings = live_optimization_config() if optimization is None else optimization
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
    _refuse_a_clock_stopped_solve(inputs, result.solver_status, result.diagnostics, "solver")

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
            fixture_counts=risk_fixture_counts,
            rivals=risk_rivals,
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
    risk_history: LiveResidualHistory | None = None,
    risk_scenario_config: ScenarioConfig | None = None,
    risk_evaluation_config: ScenarioEvaluationConfig | None = None,
    risk_fixture_counts: Mapping[int, int] | None = None,
    risk_rivals: Sequence[RivalSquad] = (),
) -> Recommendation:
    """Decide a mid-season deadline from the held squad and return it with provenance.

    The squad reported is the squad after the transfers; ``total_cost_tenths`` is what
    it would sell for (the wealth the game shows), not what it cost, and the budget check
    a reader should make is that the bank after is not negative.
    """

    settings = live_optimization_config() if optimization is None else optimization
    plan, decision, _ = plan_transfers(
        inputs, projection, held, rules, optimization=settings, chip=chip
    )
    if plan.solver_status not in PROVEN_STATUSES:
        raise DataSourceError(
            f"The transfer planner returned {plan.solver_status.name} for {inputs.season} "
            f"gameweek {inputs.deadline.gameweek} but did not prove the plan optimal. "
            "A live decision requires an OPTIMAL result."
        )
    _refuse_a_clock_stopped_solve(inputs, plan.solver_status, plan.diagnostics, "transfer planner")
    week = plan.weeks[0]
    risk = risk_not_requested()
    if risk_history is not None:
        # The risk layer evaluates a fixed squad; the planner's chosen week is exactly
        # that, packaged in the result container the scenario evaluators expect.
        week_result = OptimizationResult(
            solver_status=plan.solver_status,
            selected_squad=week.selected_squad,
            starting_xi=week.starting_xi,
            bench=week.bench,
            captain=week.captain,
            total_cost_tenths=int(decision.squad_sell_value_tenths),
            projected_score=float(week.projected_score),
            objective_value=None,
            diagnostics={},
        )
        risk = evaluate_live_risk(
            inputs,
            projection,
            week_result,
            risk_history,
            scenario_config=risk_scenario_config,
            evaluation_config=risk_evaluation_config,
            fixture_counts=risk_fixture_counts,
            rivals=risk_rivals,
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
        risk=risk,
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
        interval = risk.diagnostics.get("probability_below_threshold_interval")
        if isinstance(interval, list | tuple) and len(interval) == 2:
            lines.append(
                f"  P(score < {metrics.points_threshold:g}) 90% "
                f"[{float(interval[0]):.2f}, {float(interval[1]):.2f}] (scenario sampling)"
            )
        comparisons = risk.diagnostics.get("rival_comparisons")
        if isinstance(comparisons, list) and comparisons:
            lines.append("  against rivals (same scenarios; shared players cancel)")
            for entry in comparisons:
                if not isinstance(entry, Mapping):
                    continue
                low, high = entry["probability_ahead_interval"]
                quantiles = entry["difference_quantiles"]
                assert isinstance(quantiles, Mapping)
                ahead = float(str(entry["probability_ahead"]))
                median = float(str(quantiles["q50"]))
                lines.append(
                    f"    vs {entry['rival']:<14} P(ahead) {ahead:.2f} "
                    f"[{float(low):.2f}, {float(high):.2f}]  median gap {median:+.1f}  "
                    f"shared starters {entry['shared_starters']}"
                )
        limits = risk.diagnostics.get("stated_limits")
        if isinstance(limits, list | tuple):
            lines += [f"  stated limit        {limit}" for limit in limits]
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
    if recommendation.model_version in (
        ELITE_EVIDENCE_MODEL_VERSION,
        COMPONENT_ELITE_MODEL_VERSION,
    ):
        base = (
            "Phase C component projection"
            if recommendation.model_version == COMPONENT_ELITE_MODEL_VERSION
            else "operational control projection"
        )
        model_explanation = [
            "  This decision uses the bounded Top-100 XI-support adjustment on the",
            f"  {base}. It is an owner-approved evidence rule,",
            "  not a calibrated superiority or probability claim. Live availability is",
            "  applied once after the handoff.",
            f"  policy                     {ELITE_EVIDENCE_POLICY_VERSION}",
        ]
    else:
        model_explanation = [
            "  The projection is the operational control, the deterministic baseline. The",
            "  two-stage production candidate was measured against the pre-registered gates",
            "  and did not clear them, so it does not decide a real squad.",
        ]
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
        *model_explanation,
    ]
    return "\n".join(lines) + "\n"
