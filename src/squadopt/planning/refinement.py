"""Opt-in temporal neighborhoods with full-horizon state constraints and incumbent retention."""

from dataclasses import dataclass, replace

from squadopt.contracts.preferences import DecisionPreferences
from squadopt.optimization import OptimizationConfig, SolverStatus
from squadopt.planning.models import (
    ChipAvailability,
    InitialSquadState,
    PlanningHorizon,
    TransferPlanningConfig,
    TransferPlanningValidationError,
    TransferPlanResult,
)
from squadopt.planning.optimizer import optimize_transfer_plan


@dataclass(frozen=True)
class RefinementStep:
    free_gameweeks: tuple[int, ...]
    candidate: TransferPlanResult
    accepted: bool
    objective_before: float
    objective_after: float


@dataclass(frozen=True)
class RefinedPlan:
    baseline: TransferPlanResult
    chosen: TransferPlanResult
    steps: tuple[RefinementStep, ...]

    @property
    def proof_status(self) -> str:
        # A restricted subproblem's bound is never a bound for the full problem.
        return (
            "OPTIMAL_FULL_HORIZON_SCALED_OBJECTIVE"
            if self.baseline.solver_status is SolverStatus.OPTIMAL
            else "FEASIBLE_REFINED_HORIZON"
        )


def optimize_refined_plan(
    horizon: PlanningHorizon,
    initial: InitialSquadState,
    optimization: OptimizationConfig,
    transfer: TransferPlanningConfig | None = None,
    *,
    chips: ChipAvailability | None = None,
    preferences: DecisionPreferences | None = None,
    neighborhood_width: int = 2,
    repair_time_limit_seconds: float = 30,
    repair_deterministic_time_limit: float = 15,
) -> RefinedPlan:
    """Free each adjacent pair or triple once; keep a complete incumbent on a failed/worse search.

    Only squad membership outside the neighborhood is fixed. XI, captain, transfers, bank,
    free transfers and chips are solved together across the ORIGINAL full horizon.
    No bank/FT reset, fabricated terminal value, shortened player pool or learned
    parameter is introduced. This is deterministic forecast optimization, not an MDP
    policy or evidence of realized-point improvement. Defaults remain opt-in.
    """
    forecast = horizon.validated_copy()
    if len(forecast.gameweeks) not in (3, 5):
        raise ValueError("Temporal refinement requires three or five forecast weeks.")
    if (
        isinstance(neighborhood_width, bool)
        or not isinstance(neighborhood_width, int)
        or neighborhood_width not in (2, 3)
    ):
        raise ValueError("Neighborhood width must be 2 or 3.")
    repair = replace(
        optimization,
        solver_time_limit_seconds=repair_time_limit_seconds,
        solver_deterministic_time_limit=repair_deterministic_time_limit,
    )
    baseline = optimize_transfer_plan(
        forecast,
        initial,
        optimization,
        transfer,
        chips=chips,
        preferences=preferences,
        protect_hold=True,
        linearization_level=2,
    )
    if not baseline.has_solution or len(baseline.weeks) != len(forecast.gameweeks):
        raise TransferPlanningValidationError("Refinement requires a complete feasible baseline.")
    if baseline.solver_status is SolverStatus.OPTIMAL:
        return RefinedPlan(baseline, baseline, ())
    incumbent = baseline
    steps = []
    for start in range(len(forecast.gameweeks) - neighborhood_width + 1):
        free_weeks = forecast.gameweeks[start : start + neighborhood_width]
        fixed = {
            w.gameweek: tuple(w.selected_squad.player_id)
            for w in incumbent.weeks
            if w.gameweek not in free_weeks
        }
        candidate = optimize_transfer_plan(
            forecast,
            initial,
            repair,
            transfer,
            chips=chips,
            preferences=preferences,
            linearization_level=2,
            fixed_week_squads=fixed,
        )
        if candidate.solver_status is SolverStatus.INFEASIBLE:
            raise TransferPlanningValidationError(
                "A temporal neighborhood contradicts its known feasible incumbent."
            )
        before = incumbent.objective_value
        assert before is not None
        if candidate.has_solution and len(candidate.weeks) != len(forecast.gameweeks):
            raise TransferPlanningValidationError("Temporal repair returned an incomplete path.")
        accepted = (
            candidate.has_solution
            and candidate.objective_value is not None
            and candidate.objective_value > before + 1e-9
        )
        if accepted:
            incumbent = candidate
        after = incumbent.objective_value
        assert after is not None
        steps.append(RefinementStep(free_weeks, candidate, accepted, before, after))
    if incumbent is not baseline:
        # Consumers of chosen alone must not mistake a neighborhood optimum/bound
        # for global proof. Exact local statuses remain available in the step record.
        diagnostics = dict(incumbent.diagnostics)
        diagnostics.update(
            proof_scope="temporal_refinement",
            solver_status_name="FEASIBLE",
            best_objective_bound=None,
            absolute_optimality_gap=None,
            relative_optimality_gap=None,
        )
        incumbent = replace(incumbent, solver_status=SolverStatus.FEASIBLE, diagnostics=diagnostics)
    return RefinedPlan(baseline, incumbent, tuple(steps))
