"""Replay named development decisions to obtain covariates from projections alone."""

import math
from collections.abc import Mapping, Sequence
from typing import Any

from squadopt.evaluation.component_decisions import prepare_phase_c_component_folds
from squadopt.evaluation.component_handoff import PhaseCComponentHandoff
from squadopt.evaluation.models import EvaluationFold
from squadopt.evaluation.scoring import complete_optimization_decision, score_frozen_squad_decision
from squadopt.optimization import OptimizationConfig, optimize_squad


def replay_covariates(
    handoff: PhaseCComponentHandoff,
    controls: Sequence[EvaluationFold],
    comparison: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Require byte-identified inputs and reproduce each recorded score before analysis."""
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
        totals: dict[str, float] = {}
        actual: dict[str, float] = {}
        for name, fold in (("component", candidate), ("control", control)):
            # Only the prediction table enters optimization; target columns never enter it.
            result = optimize_squad(fold.projections, OptimizationConfig())
            if result.solver_status != "OPTIMAL":
                raise ValueError(f"Unproven {name} decision in {fold.fold_id}.")
            frozen = complete_optimization_decision(result)
            score = score_frozen_squad_decision(frozen, candidate.realized_points).total_points
            if abs(score - expected[f"{name}_realized_score"]) > 1e-9:
                raise ValueError(
                    f"{name} replay differs from the recorded score in {fold.fold_id}."
                )
            points = fold.projections.set_index("player_id")["expected_points"]
            totals[f"{name}_projected_xi_captain"] = float(
                points.loc[[int(str(player)) for player in frozen.starting_xi]].sum()
                + points.loc[int(str(frozen.captain_id))]
            )
            actual[name] = score
        if abs(actual["component"] - actual["control"] - expected["difference"]) > 1e-9:
            raise ValueError("The recorded paired difference is inconsistent.")
        rows.append(
            {
                "fold_id": candidate.fold_id,
                "difference": expected["difference"],
                **totals,
                "component_projected_pool_total": float(
                    candidate.projections["expected_points"].sum()
                ),
            }
        )
    return rows
