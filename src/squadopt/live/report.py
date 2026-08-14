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
from dataclasses import dataclass
from typing import Final

import pandas as pd

from squadopt.data.errors import DataSourceError
from squadopt.live.recommendation import Projection, RecommendationInputs
from squadopt.optimization import OptimizationConfig, SolverStatus, optimize_squad
from squadopt.optimization.models import OptimizationResult

REPORT_CONTRACT_VERSION: Final = "live_recommendation_v1"

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
    prediction_fingerprint: str
    solver_status: str
    squad: pd.DataFrame
    starting_xi: pd.DataFrame
    bench: pd.DataFrame
    captain: pd.Series
    total_cost_tenths: int
    projected_score: float
    diagnostics: Mapping[str, object]

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

    return Recommendation(
        contract_version=REPORT_CONTRACT_VERSION,
        snapshot_id=inputs.snapshot_id,
        captured_at_utc=inputs.captured_at_utc,
        season=inputs.season,
        gameweek=inputs.deadline.gameweek,
        deadline_utc=inputs.deadline.deadline_utc,
        model_name=str(projection.diagnostics["model_name"]),
        model_version=str(projection.diagnostics["model_version"]),
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
        f"  model               {recommendation.model_name}@{recommendation.model_version}",
        f"  projection digest   {recommendation.prediction_fingerprint[:16]}…",
        f"  solver              {recommendation.solver_status}",
        f"  squad cost          {recommendation.total_cost_tenths / 10:.1f}",
        f"  projected score     {recommendation.projected_score:.4f}",
    ]

    if not recommendation.solver_proved_optimal:
        lines += [
            "",
            "  WARNING: the solver did not prove this squad optimal, so it is the best one",
            "  found before the limit rather than the best one for this projection.",
        ]

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
