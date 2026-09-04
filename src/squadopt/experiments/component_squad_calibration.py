"""Aggregate Phase D fixed-decision readings under the frozen S1/S2 gates."""

from __future__ import annotations

import math
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

from squadopt.scenarios.decision_scoring import (
    COMPONENT_DECISION_LOWER_QUANTILE,
    COMPONENT_DECISION_READOUT_CONTRACT_VERSION,
    COMPONENT_DECISION_SCORING_CONTRACT_VERSION,
    ComponentDecisionDistributionReadout,
)

COMPONENT_SQUAD_CALIBRATION_CONTRACT_VERSION: Final = "component_squad_calibration_report_v1"
COMPONENT_SQUAD_CALIBRATION_STATUSES: Final = (
    "calibrated_internal",
    "failed",
    "abstained",
)
S1_PIT_BOUNDS: Final = (0.43, 0.57)
S2_LOWER_TAIL_BOUNDS: Final = (0.04, 0.16)
MIN_CALIBRATION_FOLDS: Final = 30
FROZEN_SCENARIO_COUNT: Final = 1_000
BOUND_TOLERANCE: Final = 1e-9

_FOLD_ID = re.compile(r"^\d{4}-\d{2}-gw\d{2}$")


class ComponentSquadCalibrationError(ValueError):
    """Raised when calibration evidence violates the frozen input contract."""


@dataclass(frozen=True, slots=True)
class ComponentCalibrationFold:
    """One chronological fold and its unadjusted fixed-decision reading."""

    fold_id: str
    readout: ComponentDecisionDistributionReadout

    def __post_init__(self) -> None:
        if not isinstance(self.fold_id, str) or _FOLD_ID.fullmatch(self.fold_id) is None:
            raise ComponentSquadCalibrationError(
                "fold_id must use the canonical YYYY-YY-gwNN form."
            )
        if not isinstance(self.readout, ComponentDecisionDistributionReadout):
            raise ComponentSquadCalibrationError(
                "readout must be a ComponentDecisionDistributionReadout."
            )


@dataclass(frozen=True, slots=True)
class ComponentSquadCalibrationResult:
    """Structured internal verdict; it is not a member-facing probability report."""

    status: str
    fold_count: int
    expected_fold_count: int
    fold_ids: tuple[str, ...]
    mean_probability_integral_transform: float | None
    realized_below_lower_quantile_count: int | None
    realized_below_lower_quantile_rate: float | None
    s1_passes: bool | None
    s2_passes: bool | None
    abstention_reason: str | None
    contract_version: str = COMPONENT_SQUAD_CALIBRATION_CONTRACT_VERSION

    def __post_init__(self) -> None:
        if self.contract_version != COMPONENT_SQUAD_CALIBRATION_CONTRACT_VERSION:
            raise ComponentSquadCalibrationError("unsupported calibration report contract.")
        if self.status not in COMPONENT_SQUAD_CALIBRATION_STATUSES:
            raise ComponentSquadCalibrationError(
                f"status must be one of {COMPONENT_SQUAD_CALIBRATION_STATUSES!r}."
            )


def evaluate_component_squad_calibration(
    folds: Sequence[ComponentCalibrationFold],
    *,
    expected_fold_ids: Sequence[str],
    sampler_fidelity_verified: bool,
) -> ComponentSquadCalibrationResult:
    """Evaluate S1/S2, or abstain before reading them when evidence is incomplete.

    The caller must supply the preregistered population explicitly. This keeps a missing fold
    from silently changing the denominator and makes the binding runner responsible for the
    exact 137-fold Phase D population.
    """

    if not isinstance(sampler_fidelity_verified, bool):
        raise ComponentSquadCalibrationError("sampler_fidelity_verified must be a bool.")
    observed = tuple(folds)
    if any(not isinstance(fold, ComponentCalibrationFold) for fold in observed):
        raise ComponentSquadCalibrationError("folds must contain ComponentCalibrationFold values.")
    expected = tuple(expected_fold_ids)
    _validate_fold_ids(expected, "expected_fold_ids")
    if len(expected) < MIN_CALIBRATION_FOLDS:
        raise ComponentSquadCalibrationError(
            f"expected_fold_ids must contain at least {MIN_CALIBRATION_FOLDS} folds."
        )
    _validate_fold_ids(tuple(fold.fold_id for fold in observed), "folds")

    ordered = tuple(sorted(observed, key=lambda fold: fold.fold_id))
    observed_ids = tuple(fold.fold_id for fold in ordered)
    if not sampler_fidelity_verified:
        return _abstained(
            observed_ids,
            len(expected),
            "sampler_fidelity_not_verified",
        )
    if set(observed_ids) != set(expected):
        missing = sorted(set(expected) - set(observed_ids))
        unexpected = sorted(set(observed_ids) - set(expected))
        return _abstained(
            observed_ids,
            len(expected),
            f"population_mismatch: missing={missing!r}; unexpected={unexpected!r}",
        )

    pits: list[float] = []
    lower_tail: list[bool] = []
    for fold in ordered:
        readout = fold.readout
        if readout.contract_version != COMPONENT_DECISION_READOUT_CONTRACT_VERSION:
            raise ComponentSquadCalibrationError(
                f"{fold.fold_id} uses an unsupported readout contract."
            )
        if (
            isinstance(readout.scenario_count, bool)
            or not isinstance(readout.scenario_count, int)
            or readout.scenario_count != FROZEN_SCENARIO_COUNT
        ):
            raise ComponentSquadCalibrationError(
                f"{fold.fold_id} scenario_count must equal the frozen {FROZEN_SCENARIO_COUNT}."
            )
        if readout.lower_quantile_probability != COMPONENT_DECISION_LOWER_QUANTILE:
            raise ComponentSquadCalibrationError(
                f"{fold.fold_id} does not use the frozen q10 reading."
            )
        if readout.decision_scoring_contract_version != COMPONENT_DECISION_SCORING_CONTRACT_VERSION:
            raise ComponentSquadCalibrationError(
                f"{fold.fold_id} uses an unsupported decision-scoring contract."
            )
        pit = readout.probability_integral_transform
        below = readout.realized_below_lower_quantile
        realized = readout.realized_score
        if pit is None or below is None or realized is None:
            return _abstained(observed_ids, len(expected), f"incomplete_readout: {fold.fold_id}")
        if not math.isfinite(pit) or not 0.0 <= pit <= 1.0:
            raise ComponentSquadCalibrationError(f"{fold.fold_id} has a PIT outside [0, 1].")
        if not isinstance(below, bool):
            raise ComponentSquadCalibrationError(
                f"{fold.fold_id} lower-tail indicator must be a bool."
            )
        if not math.isfinite(realized):
            raise ComponentSquadCalibrationError(f"{fold.fold_id} realized score must be finite.")
        if not math.isfinite(readout.lower_quantile_score):
            raise ComponentSquadCalibrationError(
                f"{fold.fold_id} lower-quantile score must be finite."
            )
        if below is not (realized < readout.lower_quantile_score):
            raise ComponentSquadCalibrationError(
                f"{fold.fold_id} lower-tail indicator disagrees with realized < q10."
            )
        pits.append(pit)
        lower_tail.append(below)

    mean_pit = sum(pits) / len(pits)
    tail_count = sum(lower_tail)
    tail_rate = tail_count / len(lower_tail)
    s1_passes = _within(mean_pit, S1_PIT_BOUNDS)
    s2_passes = _within(tail_rate, S2_LOWER_TAIL_BOUNDS)
    return ComponentSquadCalibrationResult(
        status="calibrated_internal" if s1_passes and s2_passes else "failed",
        fold_count=len(ordered),
        expected_fold_count=len(expected),
        fold_ids=observed_ids,
        mean_probability_integral_transform=mean_pit,
        realized_below_lower_quantile_count=tail_count,
        realized_below_lower_quantile_rate=tail_rate,
        s1_passes=s1_passes,
        s2_passes=s2_passes,
        abstention_reason=None,
    )


def _validate_fold_ids(fold_ids: tuple[str, ...], name: str) -> None:
    if len(set(fold_ids)) != len(fold_ids):
        raise ComponentSquadCalibrationError(f"{name} contains duplicate fold identifiers.")
    invalid = [
        fold_id
        for fold_id in fold_ids
        if not isinstance(fold_id, str) or _FOLD_ID.fullmatch(fold_id) is None
    ]
    if invalid:
        raise ComponentSquadCalibrationError(
            f"{name} contains non-canonical fold identifiers: {invalid[:5]!r}."
        )


def _within(value: float, bounds: tuple[float, float]) -> bool:
    low, high = bounds
    return low - BOUND_TOLERANCE <= value <= high + BOUND_TOLERANCE


def _abstained(
    fold_ids: tuple[str, ...],
    expected_fold_count: int,
    reason: str,
) -> ComponentSquadCalibrationResult:
    return ComponentSquadCalibrationResult(
        status="abstained",
        fold_count=len(fold_ids),
        expected_fold_count=expected_fold_count,
        fold_ids=fold_ids,
        mean_probability_integral_transform=None,
        realized_below_lower_quantile_count=None,
        realized_below_lower_quantile_rate=None,
        s1_passes=None,
        s2_passes=None,
        abstention_reason=reason,
    )
