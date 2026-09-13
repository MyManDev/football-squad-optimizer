"""Join recorded paired scores to verified pre-decision projection covariates."""

import math
from collections.abc import Mapping, Sequence
from typing import Any

from squadopt.evaluation.component_decisions import prepare_phase_c_component_folds
from squadopt.evaluation.component_handoff import PhaseCComponentHandoff
from squadopt.evaluation.models import EvaluationFold


def projection_covariates(
    handoff: PhaseCComponentHandoff,
    controls: Sequence[EvaluationFold],
    comparison: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Keep the recorded decision pair fixed; never rerun a time-limited optimizer."""
    source = comparison["source"]
    if (
        source["table_sha256"] != handoff.table_sha256
        or source["roster_sha256"] != handoff.roster_sha256
    ):
        raise ValueError("Comparison and handoff identify different input bytes.")
    if comparison.get("scoring_policy") != "official_autosub_captain_v2":
        raise ValueError("The comparison must use official scoring.")
    recorded = comparison["folds"]
    for row in recorded:
        for key in ("difference", "component_realized_score", "control_realized_score"):
            value = row[key]
            if (
                isinstance(value, bool)
                or not isinstance(value, int | float)
                or not math.isfinite(value)
            ):
                raise ValueError("Comparison scores must be finite numbers.")
    if [row["fold_id"] for row in recorded] != [fold.fold_id for fold in controls]:
        raise ValueError("The complete comparison population and order must match.")
    candidates = prepare_phase_c_component_folds(handoff, controls)
    rows: list[dict[str, Any]] = []
    for candidate, control, expected in zip(candidates, controls, recorded, strict=True):
        if (
            abs(
                expected["component_realized_score"]
                - expected["control_realized_score"]
                - expected["difference"]
            )
            > 1e-9
        ):
            raise ValueError("The recorded paired difference is inconsistent.")
        rows.append(
            {
                "fold_id": candidate.fold_id,
                "difference": expected["difference"],
                "control_projected_pool_total": float(control.projections["expected_points"].sum()),
                "component_projected_pool_mean": float(
                    candidate.projections["expected_points"].mean()
                ),
                "component_projected_pool_total": float(
                    candidate.projections["expected_points"].sum()
                ),
            }
        )
    return rows
