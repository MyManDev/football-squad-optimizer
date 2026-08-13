"""Fixed-decision scoring over a joint scenario matrix."""

import hashlib
import json
import math
from numbers import Integral

import numpy as np

from squadopt.optimization import OptimizationResult
from squadopt.scenarios.models import (
    ScenarioEvaluationConfig,
    ScenarioEvaluationResult,
    ScenarioRiskMetrics,
    ScenarioSet,
    ScenarioValidationError,
)


def _typed_identifier(value: object) -> dict[str, object]:
    if isinstance(value, Integral) and not isinstance(value, bool):
        return {"kind": "integer", "value": int(value)}
    return {"kind": "string", "value": str(value)}


def _decision_fingerprint(result: OptimizationResult) -> str:
    assert result.captain is not None
    payload = {
        "squad": [_typed_identifier(value) for value in result.selected_squad["player_id"]],
        "starting_xi": [_typed_identifier(value) for value in result.starting_xi["player_id"]],
        "captain": _typed_identifier(result.captain["player_id"]),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def evaluate_fixed_decision(
    optimization_result: OptimizationResult,
    scenarios: ScenarioSet,
    config: ScenarioEvaluationConfig | None = None,
) -> ScenarioEvaluationResult:
    """Score one already-frozen starting XI and captain without reoptimization."""

    settings = ScenarioEvaluationConfig() if config is None else config
    if not isinstance(settings, ScenarioEvaluationConfig):
        raise ScenarioValidationError("config must be a ScenarioEvaluationConfig.")
    if not isinstance(optimization_result, OptimizationResult):
        raise ScenarioValidationError("optimization_result must be an OptimizationResult.")
    if not optimization_result.has_solution:
        raise ScenarioValidationError(
            "Scenario evaluation requires an OPTIMAL or FEASIBLE fixed decision."
        )
    if optimization_result.captain is None:
        raise ScenarioValidationError("A feasible fixed decision must contain a captain.")
    if not isinstance(scenarios, ScenarioSet):
        raise ScenarioValidationError("scenarios must be a ScenarioSet.")
    verified = scenarios.validated_copy()
    player_ids = verified.projections.table["player_id"].tolist()
    player_column = {player_id: index for index, player_id in enumerate(player_ids)}
    starter_ids = optimization_result.starting_xi["player_id"].tolist()
    captain_id = optimization_result.captain["player_id"]
    required = list(dict.fromkeys([*starter_ids, captain_id]))
    missing = [player_id for player_id in required if player_id not in player_column]
    if missing:
        raise ScenarioValidationError(
            "Scenario players must cover every selected starter and captain; "
            f"missing={missing[:10]!r}."
        )
    starter_columns = [player_column[player_id] for player_id in starter_ids]
    captain_column = player_column[captain_id]
    matrix = verified.scenario_points.to_numpy(dtype="float64", copy=False)
    scores = matrix[:, starter_columns].sum(axis=1) + matrix[:, captain_column]

    projections = verified.projections.table.set_index("player_id")["expected_points"]
    point_score = float(projections.loc[starter_ids].sum() + projections.loc[captain_id])
    worst_count = max(1, math.ceil(settings.worst_fraction * len(scores)))
    ordered = np.sort(scores)
    lower_quantile = float(np.quantile(scores, settings.lower_quantile, method="linear"))
    metrics = ScenarioRiskMetrics(
        scenario_count=len(scores),
        point_projection_score=point_score,
        mean_score=float(scores.mean()),
        score_standard_deviation=float(scores.std(ddof=0)),
        lower_quantile_probability=settings.lower_quantile,
        lower_quantile_score=lower_quantile,
        worst_fraction=settings.worst_fraction,
        worst_fraction_count=worst_count,
        mean_worst_fraction_score=float(ordered[:worst_count].mean()),
        minimum_score=float(ordered[0]),
        points_threshold=settings.points_threshold,
        probability_below_threshold=float((scores < settings.points_threshold).mean()),
    )
    return ScenarioEvaluationResult(
        scenario_fingerprint=verified.scenario_fingerprint,
        scenario_scores=tuple(float(value) for value in scores),
        metrics=metrics,
        diagnostics={
            "decision_fingerprint": _decision_fingerprint(optimization_result),
            "scoring_policy": "starting_xi_plus_captain_double_v1",
            "bench_points_included": False,
            "decision_reoptimized_per_scenario": False,
            "standard_deviation": "population",
            "quantile_interpolation": "linear",
            "worst_fraction_count_rule": "ceil",
            "threshold_comparison": "strictly_below",
        },
    )
