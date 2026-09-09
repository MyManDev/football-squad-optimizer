"""Deterministic top-K complete decisions for the Phase E selector.

The generator proposes and nothing else: candidate 0 is the unchanged ``optimize_squad``
control, and every later candidate is the best decision that remains after the earlier
ones are cut out of the feasible set with ``excluded_decisions``. Candidates therefore
come in non-increasing deterministic objective order, each one proven optimal for the
space it was solved in, and the whole set is decided before any scenario is consulted.
No scenario logic belongs here.
"""

from dataclasses import dataclass
from numbers import Integral

import pandas as pd

from squadopt.optimization.coefficients import sort_players_by_id
from squadopt.optimization.config import OptimizationConfig
from squadopt.optimization.models import (
    InvalidConfigurationError,
    OptimizationResult,
    SolverStatus,
)
from squadopt.optimization.optimizer import optimize_squad

DecisionSignature = tuple[tuple[object, ...], tuple[object, ...], object]
"""``(sorted squad ids, sorted starting-eleven ids, captain id)``: a complete decision."""


@dataclass(frozen=True, slots=True)
class SquadCandidateSet:
    """The control and the proven alternatives generated after it.

    ``complete`` is the generator's own verdict on the set: either ``candidate_count_requested``
    proven candidates were found, or the legal space was exhausted (a solve after the last
    proven candidate was ``INFEASIBLE``). A ``FEASIBLE`` or ``UNKNOWN`` solve stops the search
    early and leaves the set incomplete; that result is not a candidate and is not kept.
    ``termination_status`` is the primary status of the last solve that ran.
    """

    candidates: tuple[OptimizationResult, ...]
    candidate_count_requested: int
    complete: bool
    termination_status: SolverStatus

    def __post_init__(self) -> None:
        if not isinstance(self.candidates, tuple) or not self.candidates:
            raise InvalidConfigurationError("candidates must be a non-empty tuple.")
        if any(not isinstance(candidate, OptimizationResult) for candidate in self.candidates):
            raise InvalidConfigurationError("candidates must contain OptimizationResult values.")
        requested = _candidate_count(self.candidate_count_requested)
        object.__setattr__(self, "candidate_count_requested", requested)
        if len(self.candidates) > requested:
            raise InvalidConfigurationError("candidates cannot exceed the requested count.")
        if not isinstance(self.complete, bool):
            raise InvalidConfigurationError("complete must be a boolean.")
        if not isinstance(self.termination_status, SolverStatus):
            raise InvalidConfigurationError("termination_status must be a SolverStatus.")

    @property
    def control(self) -> OptimizationResult:
        """The unchanged deterministic decision, always the first candidate."""

        return self.candidates[0]


def decision_signature(result: OptimizationResult) -> DecisionSignature:
    """Return the complete identity of a solved decision.

    Squad and eleven use the model's own stable player ordering, so two results that
    select the same players compare equal whatever order their frames happen to be in.
    Bench order and the vice-captain are completions of this identity, not part of it.
    """

    if not isinstance(result, OptimizationResult):
        raise InvalidConfigurationError("result must be an OptimizationResult.")
    if not result.has_solution or result.captain is None:
        raise InvalidConfigurationError(
            "A decision signature needs a solved result with a captain."
        )
    squad = tuple(sort_players_by_id(result.selected_squad)["player_id"].tolist())
    starters = tuple(sort_players_by_id(result.starting_xi)["player_id"].tolist())
    return squad, starters, result.captain["player_id"]


def generate_squad_candidates(
    players: pd.DataFrame,
    config: OptimizationConfig | None = None,
    *,
    candidate_count: int,
    required_player_ids: tuple[int, ...] = (),
) -> SquadCandidateSet:
    """Return the control and up to ``candidate_count - 1`` next-best complete decisions.

    Every solve is the same ``optimize_squad`` call the live path makes, on the same full
    validated pool, with the earlier candidates excluded. The control is returned exactly
    as ``optimize_squad`` returns it. A control that is not proven optimal ends the search
    at once with the set marked incomplete; the control's own status and result are kept
    so the caller's existing handling of an unsolved decision applies unchanged.
    """

    settings = OptimizationConfig() if config is None else config
    if not isinstance(settings, OptimizationConfig):
        raise InvalidConfigurationError("config must be an OptimizationConfig or None.")
    requested = _candidate_count(candidate_count)

    control = optimize_squad(players, settings, required_player_ids=required_player_ids)
    candidates = [control]
    termination = control.solver_status
    if control.solver_status is not SolverStatus.OPTIMAL or control.captain is None:
        return SquadCandidateSet(
            candidates=(control,),
            candidate_count_requested=requested,
            complete=False,
            termination_status=termination,
        )

    complete = True
    while len(candidates) < requested:
        alternative = optimize_squad(
            players,
            settings,
            required_player_ids=required_player_ids,
            excluded_decisions=tuple(candidates),
        )
        termination = alternative.solver_status
        if alternative.solver_status is SolverStatus.OPTIMAL and alternative.captain is not None:
            candidates.append(alternative)
            continue
        # INFEASIBLE after proven candidates means the legal space is exhausted: the set is
        # complete at its current size. FEASIBLE and UNKNOWN are unproven and stop the search
        # without adding anything.
        complete = alternative.solver_status is SolverStatus.INFEASIBLE
        break

    return SquadCandidateSet(
        candidates=tuple(candidates),
        candidate_count_requested=requested,
        complete=complete,
        termination_status=termination,
    )


def _candidate_count(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, Integral):
        raise InvalidConfigurationError(f"candidate_count must be an integer, got {value!r}.")
    count = int(value)
    if count < 1:
        raise InvalidConfigurationError(f"candidate_count must be at least 1, got {count}.")
    return count
