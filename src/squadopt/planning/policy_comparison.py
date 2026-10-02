"""Arithmetic descriptions of already completed conditional policies; no search."""

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PolicyComparisonInput:
    branch_values: Mapping[str, float]
    transfer_count: int
    chip: str | None
    bank_tenths: int
    free_transfers: int


def compare_completed_policies(
    candidates: Sequence[PolicyComparisonInput], *, basis: str, baseline_index: int = 0
) -> dict[str, Any]:
    """Compare the same scenarios without attaching an information-arrival chance.

    Min/max and dominance refer only to the supplied finite scenarios, not realized
    score bounds. A transfer-free action retains resources but does not acquire an
    invented terminal FT/bank value. The caller supplies either selection utility
    or rebased own points and labels that basis explicitly.
    """
    if not candidates or not 0 <= baseline_index < len(candidates) or not basis:
        raise ValueError("A comparison needs candidates, a baseline and a score basis.")
    ids = tuple(candidates[baseline_index].branch_values)
    if not ids or len(set(ids)) != len(ids):
        raise ValueError("A comparison needs distinct scenario identifiers.")
    for candidate in candidates:
        if set(candidate.branch_values) != set(ids) or any(
            isinstance(v, bool) or not math.isfinite(v) for v in candidate.branch_values.values()
        ):
            raise ValueError("Every policy must complete the same finite scenarios.")
        if any(
            isinstance(v, bool) or not isinstance(v, int) or v < 0
            for v in (candidate.transfer_count, candidate.bank_tenths, candidate.free_transfers)
        ):
            raise ValueError("First-action resources must be non-negative integers.")
    baseline = candidates[baseline_index].branch_values

    def dominates(left: PolicyComparisonInput, right: PolicyComparisonInput) -> bool:
        gaps = [left.branch_values[k] - right.branch_values[k] for k in ids]
        return all(g >= -1e-9 for g in gaps) and any(g > 1e-9 for g in gaps)

    rows = []
    for index, candidate in enumerate(candidates):
        values = list(candidate.branch_values.values())
        gaps = {key: candidate.branch_values[key] - baseline[key] for key in ids}
        rows.append(
            {
                "index": index,
                "action_kind": (
                    "chip" if candidate.chip else "move" if candidate.transfer_count else "hold"
                ),
                "first_state": {
                    "bank_tenths": candidate.bank_tenths,
                    "free_transfers": candidate.free_transfers,
                },
                "scenario_min": min(values),
                "scenario_max": max(values),
                "branch_gaps_vs_baseline": gaps,
                "minimum_gap_vs_baseline": min(gaps.values()),
                "maximum_gap_vs_baseline": max(gaps.values()),
                "dominates_baseline": dominates(candidate, candidates[baseline_index]),
                "dominated_by": [
                    other_index
                    for other_index, other in enumerate(candidates)
                    if other_index != index and dominates(other, candidate)
                ],
            }
        )
    return {
        "version": "completed_policy_comparison_v1",
        "basis": basis,
        "baseline_index": baseline_index,
        "scenario_ids": list(ids),
        "news_arrival_probability": None,
        "scope": "supplied_conditional_scenarios_only",
        "terminal_resource_value_added": False,
        "candidates": rows,
    }
