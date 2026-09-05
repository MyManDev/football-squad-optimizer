"""Official realized scoring and frozen A/R/U/S gates for Phase E shadow decisions."""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from math import ceil, isfinite
from statistics import fmean
from typing import Final

import pandas as pd
from scipy.stats import spearmanr

from squadopt.evaluation.scoring import (
    complete_optimization_decision,
    score_frozen_squad_decision,
)
from squadopt.experiments.component_squad_calibration import COMPONENT_SQUAD_CALIBRATION_STATUSES
from squadopt.experiments.config import PromotionPolicy
from squadopt.experiments.statistics import (
    _percentile,
    season_aware_moving_block_indices,
    season_aware_moving_block_interval,
)
from squadopt.optimization import OptimizationResult, SolverStatus
from squadopt.scenarios.components import ComponentScenarioDraw
from squadopt.scenarios.decision_scoring import score_component_scenario_decision
from squadopt.scenarios.selection import (
    PHASE_E_POINTS_SCALE,
    PHASE_E_SCENARIO_COUNT,
    PHASE_E_TAIL_COUNT,
    PHASE_E_WEIGHT_SCALE,
    PhaseESelectionResult,
    PhaseESelectionStatus,
    integer_mean_cvar,
)

PHASE_E_SHADOW_CONTRACT: Final = "phase_e_shadow_evaluation_v1"
PHASE_E_BOOTSTRAP_POLICY: Final = PromotionPolicy(bootstrap_resamples=2000)
PHASE_E_COMPARISON_ID: Final = "phase_e_vs_phase_c"
_UTILITY_DENOMINATOR: Final = (
    PHASE_E_POINTS_SCALE * PHASE_E_SCENARIO_COUNT * PHASE_E_TAIL_COUNT * PHASE_E_WEIGHT_SCALE
)
_FOLD_ID = re.compile(r"^(2021-22|2022-23|2023-24|2024-25)-gw(0[1-9]|[12][0-9]|3[0-8])$")


class PhaseEShadowError(ValueError):
    """Raised when shadow evidence cannot support the preregistered comparison."""


@dataclass(frozen=True, slots=True)
class PhaseEShadowCandidate:
    """A covered candidate's realized score and optional utility difference in points."""

    rank: int
    realized_points: float
    utility_difference: float | None
    utility_int: int | None = None
    squad_ids: tuple[object, ...] = ()
    starting_ids: tuple[object, ...] = ()
    captain_id: object = None


@dataclass(frozen=True, slots=True)
class PhaseEShadowFold:
    """A fold remains in the population even when its decision failed."""

    fold_id: str
    status: str
    candidate_set_complete: bool
    selected_rank: int = 0
    control_points: float | None = None
    selected_points: float | None = None
    squad_changed: bool = False
    eleven_changed: bool = False
    captain_changed: bool = False
    formation_changed: bool = False
    candidates: tuple[PhaseEShadowCandidate, ...] = ()
    generation_seconds: float = 0.0
    scoring_seconds: float = 0.0
    error: str | None = None
    scenario_fingerprint: str | None = None
    component_fingerprint: str | None = None

    @property
    def disagrees(self) -> bool:
        return self.squad_changed or self.eleven_changed or self.captain_changed

    @property
    def difference(self) -> float | None:
        if self.selected_points is None or self.control_points is None:
            return None
        return self.selected_points - self.control_points


def score_phase_e_shadow_fold(
    fold_id: str,
    candidates: Sequence[OptimizationResult],
    selection: PhaseESelectionResult,
    realized_points: pd.DataFrame,
    *,
    candidate_set_complete: bool,
    draw: ComponentScenarioDraw | None = None,
    generation_seconds: float = 0.0,
    scoring_seconds: float = 0.0,
) -> PhaseEShadowFold:
    """Read outcomes only after selection; reuse the official autosub/captain scorer."""

    frozen = tuple(candidates)
    rank = selection.selected_candidate_rank
    if (
        not frozen
        or not 0 <= rank < len(frozen)
        or selection.control_result is not frozen[0]
        or selection.selected_result is not frozen[rank]
    ):
        raise PhaseEShadowError("Selection must refer to these exact frozen candidates.")
    if (
        draw is not None
        and selection.scenario_fingerprint is not None
        and (
            selection.scenario_fingerprint != draw.scenarios.scenario_fingerprint
            or selection.component_fingerprint != draw.component_fingerprint
        )
    ):
        raise PhaseEShadowError("Technical scoring must use the selection's same shared draw.")
    diagnostics = {item.rank: item for item in selection.diagnostics}
    control = diagnostics[0]
    selected = diagnostics[rank]
    readings: list[PhaseEShadowCandidate] = []
    utilities: dict[int, int] = {}
    covered: set[int] = set()
    for index, candidate in enumerate(frozen):
        diagnostic = diagnostics.get(index)
        if diagnostic is None:
            continue
        if diagnostic.covered is True:
            covered.add(index)
        if diagnostic.utility_int is not None:
            utilities[index] = diagnostic.utility_int
        # A failed Phase D gate still permits technical scoring in E3, while the
        # selection remains the uncalibrated fallback. Never fabricate a calibration pin.
        if draw is not None and set(diagnostic.squad_ids) <= set(
            draw.scenarios.scenario_points.columns
        ):
            covered.add(index)
            if index not in utilities:
                scores = score_component_scenario_decision(candidate, draw)
                utilities[index] = integer_mean_cvar(
                    tuple(score.total_points for score in scores.scores)
                ).utility_int
    for index, candidate in enumerate(frozen):
        if index != 0 and index not in covered:
            continue
        score = score_frozen_squad_decision(
            complete_optimization_decision(candidate), realized_points
        ).total_points
        utility = utilities.get(index)
        difference = (
            (utility - utilities[0]) / _UTILITY_DENOMINATOR
            if utility is not None and 0 in utilities
            else None
        )
        diagnostic = diagnostics[index]
        readings.append(
            PhaseEShadowCandidate(
                index,
                score,
                difference,
                utility,
                diagnostic.squad_ids,
                diagnostic.starting_ids,
                diagnostic.captain_id,
            )
        )
    by_rank = {item.rank: item for item in readings}
    record = PhaseEShadowFold(
        fold_id=fold_id,
        status=selection.selection_status.value,
        candidate_set_complete=(
            candidate_set_complete
            and all(item.solver_status is SolverStatus.OPTIMAL for item in frozen)
        ),
        selected_rank=rank,
        control_points=by_rank[0].realized_points,
        selected_points=by_rank[rank].realized_points,
        squad_changed=set(selected.squad_ids) != set(control.squad_ids),
        eleven_changed=set(selected.starting_ids) != set(control.starting_ids),
        captain_changed=selected.captain_id != control.captain_id,
        formation_changed=(
            frozen[rank].starting_xi["position"].value_counts().to_dict()
            != frozen[0].starting_xi["position"].value_counts().to_dict()
        ),
        candidates=tuple(readings),
        generation_seconds=generation_seconds,
        scoring_seconds=scoring_seconds,
        scenario_fingerprint=(
            draw.scenarios.scenario_fingerprint if draw else selection.scenario_fingerprint
        ),
        component_fingerprint=(
            draw.component_fingerprint if draw else selection.component_fingerprint
        ),
    )
    _validate_fold(record)
    return record


def _validate_fold(fold: PhaseEShadowFold) -> None:
    if _FOLD_ID.fullmatch(fold.fold_id) is None:
        raise PhaseEShadowError("Shadow folds must be canonical development-season gameweeks.")
    for value in (fold.generation_seconds, fold.scoring_seconds):
        if not isfinite(value) or value < 0:
            raise PhaseEShadowError("Fold runtimes must be finite and non-negative.")
    if fold.error is not None:
        if (
            not fold.error
            or fold.status != "ERROR"
            or fold.control_points is not None
            or fold.selected_points is not None
            or fold.disagrees
            or fold.formation_changed
            or fold.selected_rank != 0
            or fold.candidates
            or fold.candidate_set_complete
        ):
            raise PhaseEShadowError("Error folds must be named and must not invent a paired score.")
        return
    if fold.status not in {item.value for item in PhaseESelectionStatus}:
        raise PhaseEShadowError("Every completed fold must carry a named selector status.")
    if (
        fold.control_points is None
        or fold.selected_points is None
        or not isfinite(fold.control_points)
        or not isfinite(fold.selected_points)
    ):
        raise PhaseEShadowError("Completed folds require finite control and selected scores.")
    if fold.status != PhaseESelectionStatus.SELECTED and (
        fold.selected_rank != 0 or fold.disagrees or fold.difference != 0
    ):
        raise PhaseEShadowError("Every fallback must preserve the control and its zero difference.")
    if (fold.selected_rank != 0) != fold.disagrees:
        raise PhaseEShadowError("Selected rank must agree with the complete-decision identity.")
    ranks = [candidate.rank for candidate in fold.candidates]
    if len(set(ranks)) != len(ranks) or 0 not in ranks or fold.selected_rank not in ranks:
        raise PhaseEShadowError("Realized candidate rows must contain control and selected ranks.")
    for candidate in fold.candidates:
        if not isfinite(candidate.realized_points) or (
            candidate.utility_difference is not None and not isfinite(candidate.utility_difference)
        ):
            raise PhaseEShadowError("Candidate readings must be finite when available.")
        if candidate.rank == 0 and candidate.realized_points != fold.control_points:
            raise PhaseEShadowError("Control candidate score disagrees with its fold.")
        if (
            candidate.rank == fold.selected_rank
            and candidate.realized_points != fold.selected_points
        ):
            raise PhaseEShadowError("Selected candidate score disagrees with its fold.")


def _signal(folds: Sequence[PhaseEShadowFold]) -> float | None:
    pairs = [
        (candidate.utility_difference, candidate.realized_points - fold.control_points)
        for fold in folds
        if fold.control_points is not None
        for candidate in fold.candidates
        if candidate.rank != 0 and candidate.utility_difference is not None
    ]
    if len(pairs) < 2 or any(len({pair[index] for pair in pairs}) < 2 for index in (0, 1)):
        return None
    value = float(spearmanr([pair[0] for pair in pairs], [pair[1] for pair in pairs]).statistic)
    return value if isfinite(value) else None


def _optional_interval(values: list[float | None]) -> tuple[float, float] | None:
    # Do not silently drop undefined bootstrap draws and report a conditional interval.
    if not values or any(value is None for value in values):
        return None
    available = [value for value in values if value is not None]
    alpha = (1 - PHASE_E_BOOTSTRAP_POLICY.confidence_level) / 2
    return _percentile(available, alpha), _percentile(available, 1 - alpha)


def evaluate_phase_e_shadow(
    folds: Sequence[PhaseEShadowFold], *, expected_fold_ids: Sequence[str], phase_d_status: str
) -> dict[str, object]:
    """Evaluate the frozen gates without removing fallback or failed folds."""

    if phase_d_status not in COMPONENT_SQUAD_CALIBRATION_STATUSES:
        raise PhaseEShadowError("A recognized binding Phase D verdict is required.")
    expected = tuple(expected_fold_ids)
    ordered = tuple(sorted(folds, key=lambda fold: fold.fold_id))
    if (
        not expected
        or len(set(expected)) != len(expected)
        or tuple(fold.fold_id for fold in ordered) != tuple(sorted(expected))
    ):
        raise PhaseEShadowError("Shadow records must match the entire expected population exactly.")
    for fold in ordered:
        _validate_fold(fold)
    differences = [(fold.fold_id[:7], fold.difference) for fold in ordered]
    complete_scores = all(value is not None for _, value in differences)
    available = [(season, value) for season, value in differences if value is not None]
    interval = (
        season_aware_moving_block_interval(
            available, policy=PHASE_E_BOOTSTRAP_POLICY, candidate_id=PHASE_E_COMPARISON_ID
        )
        if complete_scores
        else None
    )
    disagreement_values = [fold.difference for fold in ordered if fold.disagrees]
    disagreements = [value for value in disagreement_values if value is not None]
    signal = _signal(ordered)
    signal_samples: list[float | None] = []
    disagreement_samples: list[float | None] = []
    for indices in season_aware_moving_block_indices(
        [fold.fold_id[:7] for fold in ordered],
        policy=PHASE_E_BOOTSTRAP_POLICY,
        candidate_id=PHASE_E_COMPARISON_ID,
    ):
        sample = [ordered[index] for index in indices]
        signal_samples.append(_signal(sample) if signal is not None else None)
        selected_differences = [
            fold.difference for fold in sample if fold.disagrees and fold.difference is not None
        ]
        disagreement_samples.append(fmean(selected_differences) if selected_differences else None)
    signal_interval = _optional_interval(signal_samples)
    count = len(ordered)
    complete_count = sum(fold.candidate_set_complete for fold in ordered)
    error_count = sum(fold.error is not None for fold in ordered)
    disagreement_count = sum(fold.disagrees for fold in ordered)
    a_passes = interval[0] > -1.0 if interval is not None else None
    r_passes = complete_count / count >= 0.95 and error_count == 0
    u_passes = disagreement_count / count >= 0.20
    s_passes = (
        signal is not None and signal > 0 and signal_interval is not None and signal_interval[0] > 0
    )
    if phase_d_status != "calibrated_internal" or a_passes is None:
        status = "technical_only"
    elif not a_passes:
        status = "harmful"
    elif not r_passes:
        status = "technical_only"
    elif not u_passes:
        status = "inert"
    else:
        status = "shadow_eligible"
    tail_count = ceil(count * 0.1)
    return {
        "contract_version": PHASE_E_SHADOW_CONTRACT,
        "status": status,
        "phase_d_status": phase_d_status,
        "fold_count": count,
        "gates": {"A": a_passes, "R": r_passes, "U": u_passes, "S": s_passes},
        "signal": s_passes,
        "mean_difference": fmean(value for _, value in available) if complete_scores else None,
        "mean_difference_interval": interval,
        "disagreement_mean": fmean(disagreements) if disagreements else None,
        "disagreement_interval": _optional_interval(disagreement_samples)
        if complete_scores
        else None,
        "spearman": signal,
        "spearman_interval": signal_interval,
        "season_mean_differences": {
            season: fmean(value for label, value in available if label == season)
            for season in sorted({label for label, _ in available})
        }
        if complete_scores
        else None,
        "worst_difference_tail_mean": fmean(sorted(value for _, value in available)[:tail_count])
        if complete_scores
        else None,
        "selected_lower_tail_mean": fmean(
            sorted(fold.selected_points for fold in ordered if fold.selected_points is not None)[
                :tail_count
            ]
        )
        if complete_scores
        else None,
        "control_lower_tail_mean": fmean(
            sorted(fold.control_points for fold in ordered if fold.control_points is not None)[
                :tail_count
            ]
        )
        if complete_scores
        else None,
        "complete_candidate_set_count": complete_count,
        "error_count": error_count,
        "disagreement_count": disagreement_count,
        "change_counts": {
            "squad": sum(fold.squad_changed for fold in ordered),
            "bench_only": sum(
                fold.squad_changed and not fold.eleven_changed and not fold.captain_changed
                for fold in ordered
            ),
            "eleven": sum(fold.eleven_changed for fold in ordered),
            "captain": sum(fold.captain_changed for fold in ordered),
            "formation": sum(fold.formation_changed for fold in ordered),
        },
        "status_counts": dict(sorted(Counter(fold.status for fold in ordered).items())),
        "generation_seconds": sum(fold.generation_seconds for fold in ordered),
        "scoring_seconds": sum(fold.scoring_seconds for fold in ordered),
    }
