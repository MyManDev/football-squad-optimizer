"""Exhaustive policy-grid evaluation and Bayesian search-efficiency measurement.

A finite candidate grid can be evaluated completely. Doing so once turns the grid into
ground truth: the true optimum, the true rank of every cell, and therefore an exact
measurement of how much of that truth a budgeted Bayesian search recovered. Without
this, "the search worked" is an impression; with it, regret and rank are numbers.
"""

import math
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final

from squadopt.bayesopt import (
    BayesianOptimizationConfig,
    enumerate_candidates,
)
from squadopt.experiments.config import ExperimentExecutionError
from squadopt.experiments.policy_objective import BaselinePolicyObjective

POLICY_GRID_CONTRACT_VERSION: Final = "exhaustive_policy_grid_v1"


@dataclass(frozen=True, slots=True)
class PolicyGridCell:
    """One fully evaluated grid cell with its rank in the complete grid."""

    rank: int
    candidate_id: str
    form_window: int
    bench_weight: float
    mean_realized_squad_points: float

    def __post_init__(self) -> None:
        if self.rank < 1:
            raise ExperimentExecutionError("rank must be a positive integer.")
        if not math.isfinite(self.mean_realized_squad_points):
            raise ExperimentExecutionError("mean_realized_squad_points must be finite.")


@dataclass(frozen=True, slots=True)
class PolicyGridResult:
    """The complete evaluated grid, best cell first."""

    cells: tuple[PolicyGridCell, ...]
    objective_configuration_fingerprint: str
    development_fold_count: int
    contract_version: str = POLICY_GRID_CONTRACT_VERSION

    def __post_init__(self) -> None:
        if self.contract_version != POLICY_GRID_CONTRACT_VERSION:
            raise ExperimentExecutionError("Unsupported policy grid contract_version.")
        if not self.cells:
            raise ExperimentExecutionError("A policy grid result must contain cells.")
        if tuple(cell.rank for cell in self.cells) != tuple(range(1, len(self.cells) + 1)):
            raise ExperimentExecutionError("Grid cells must be ranked consecutively from 1.")
        ordering = [(-cell.mean_realized_squad_points, cell.candidate_id) for cell in self.cells]
        if ordering != sorted(ordering):
            raise ExperimentExecutionError(
                "Grid cells must be sorted by objective, then candidate_id."
            )

    @property
    def best(self) -> PolicyGridCell:
        """Return the true optimum of the complete grid."""

        return self.cells[0]


def evaluate_policy_grid(
    objective: BaselinePolicyObjective,
    search_config: BayesianOptimizationConfig,
) -> PolicyGridResult:
    """Evaluate every canonical candidate of the search space exactly once."""

    if not isinstance(objective, BaselinePolicyObjective):
        raise ExperimentExecutionError("objective must be a BaselinePolicyObjective.")
    if not isinstance(search_config, BayesianOptimizationConfig):
        raise ExperimentExecutionError("search_config must be a BayesianOptimizationConfig.")
    evaluated: list[tuple[float, str, int, float]] = []
    for candidate in enumerate_candidates(search_config):
        value = objective(candidate, objective.development_fold_ids)
        evaluated.append(
            (
                value,
                candidate.candidate_id,
                int(candidate.values["form_window"]),
                float(candidate.values["bench_weight"]),
            )
        )
    ordered = sorted(evaluated, key=lambda item: (-item[0], item[1]))
    cells = tuple(
        PolicyGridCell(
            rank=index + 1,
            candidate_id=candidate_id,
            form_window=form_window,
            bench_weight=bench_weight,
            mean_realized_squad_points=value,
        )
        for index, (value, candidate_id, form_window, bench_weight) in enumerate(ordered)
    )
    return PolicyGridResult(
        cells=cells,
        objective_configuration_fingerprint=objective.config.configuration_fingerprint,
        development_fold_count=len(objective.development_fold_ids),
    )


def _document_text(document: Mapping[str, object], name: str) -> str:
    value = document.get(name)
    if not isinstance(value, str) or not value:
        raise ExperimentExecutionError(f"Bayesian search artifact lacks {name!r}.")
    return value


def summarize_search_efficiency(
    grid: PolicyGridResult,
    bayesopt_document: Mapping[str, object],
) -> Mapping[str, object]:
    """Measure a recorded budgeted search against the exhaustive ground truth.

    The two runs must share the objective configuration, and every candidate the
    search evaluated must reproduce its grid value exactly: the evaluations are
    deterministic, so any discrepancy means the runs measured different things and
    no efficiency claim is possible.
    """

    if not isinstance(grid, PolicyGridResult):
        raise ExperimentExecutionError("grid must be a PolicyGridResult.")
    if not isinstance(bayesopt_document, Mapping):
        raise ExperimentExecutionError("bayesopt_document must be a mapping.")
    recorded_fingerprint = _document_text(bayesopt_document, "objective_configuration_fingerprint")
    if recorded_fingerprint != grid.objective_configuration_fingerprint:
        raise ExperimentExecutionError(
            "The search and the grid were run under different objective "
            "configurations; their values are not comparable."
        )
    trace = bayesopt_document.get("trace")
    if not isinstance(trace, list) or not trace:
        raise ExperimentExecutionError("Bayesian search artifact lacks a non-empty trace.")

    by_candidate = {cell.candidate_id: cell for cell in grid.cells}
    trace_entries: list[tuple[int, str, float]] = []
    for entry in trace:
        if not isinstance(entry, Mapping):
            raise ExperimentExecutionError("Trace entries must be mappings.")
        candidate_id = str(entry.get("candidate_id"))
        cell = by_candidate.get(candidate_id)
        if cell is None:
            raise ExperimentExecutionError(
                f"Search candidate {candidate_id!r} is not part of the evaluated grid."
            )
        value = entry.get("mean_realized_squad_points")
        if not isinstance(value, int | float) or isinstance(value, bool):
            raise ExperimentExecutionError("Trace entries must carry numeric objectives.")
        if float(value) != cell.mean_realized_squad_points:
            raise ExperimentExecutionError(
                f"Search value for {candidate_id!r} does not reproduce the grid value; "
                "the runs are not measuring the same deterministic objective."
            )
        trace_entries.append((int(str(entry.get("iteration"))), candidate_id, float(value)))

    best = grid.best
    recommended_id = _document_text(bayesopt_document, "recommended_candidate_id")
    recommended_cell = by_candidate.get(recommended_id)
    if recommended_cell is None:
        raise ExperimentExecutionError(
            f"Recommended candidate {recommended_id!r} is not part of the grid."
        )
    found_iteration = next(
        (
            iteration
            for iteration, candidate_id, _ in trace_entries
            if candidate_id == best.candidate_id
        ),
        None,
    )
    top_five = tuple(cell.candidate_id for cell in grid.cells[:5])
    evaluated_ids = {candidate_id for _, candidate_id, _ in trace_entries}
    return MappingProxyType(
        {
            "grid_size": len(grid.cells),
            "search_evaluations": len(trace_entries),
            "budget_fraction": len(trace_entries) / len(grid.cells),
            "true_best_candidate_id": best.candidate_id,
            "true_best_mean_realized_squad_points": best.mean_realized_squad_points,
            "recommended_candidate_id": recommended_id,
            "recommended_mean_realized_squad_points": (recommended_cell.mean_realized_squad_points),
            "recommendation_regret_points": (
                best.mean_realized_squad_points - recommended_cell.mean_realized_squad_points
            ),
            "recommendation_true_rank": recommended_cell.rank,
            "search_found_true_best": found_iteration is not None,
            "true_best_found_at_iteration": found_iteration,
            "top_five_candidate_ids": top_five,
            "top_five_evaluated_by_search": sum(
                1 for candidate_id in top_five if candidate_id in evaluated_ids
            ),
        }
    )
