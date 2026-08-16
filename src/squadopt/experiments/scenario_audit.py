"""Calibration audit of the scenario distribution against realized outcomes.

The risk frontier showed that CVaR optimization against the current scenarios worsens
both the mean and the floor. That verdict has two possible readings: risk-aware
selection is worthless here, or the scenarios misrepresent reality and CVaR optimizes
a fiction. This audit separates the two by asking the scenarios direct questions:

- Decision level: for a frozen risk-neutral squad, does the realized score behave like
  one draw from the scenario score distribution? If so, the PIT values (fraction of
  scenario scores at or below the realized score) are uniform across folds, about 10%
  of realized scores fall below the scenario q10, and the scenario-implied bad-week
  probability matches the bad-week frequency.
- Player level: do realized player points land inside the scenarios' central interval
  at the nominal rate, by position?

The audit measures; it does not repair, reweight, or decide.
"""

import hashlib
import math
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final

import numpy as np
import pandas as pd

from squadopt.evaluation import score_realized_squad_points
from squadopt.experiments.config import ExperimentExecutionError
from squadopt.experiments.scenario_policy_objective import (
    ScenarioPolicyObjective,
)
from squadopt.optimization import OptimizationConfig, optimize_squad
from squadopt.prediction import (
    FEATURE_GENERATION_CONTRACT_VERSION,
    PredictionProvenance,
    prepare_optimizer_projection,
)
from squadopt.scenarios import (
    ScenarioConfig,
    ScenarioEvaluationConfig,
    ScenarioTarget,
    evaluate_fixed_decision,
    generate_scenarios,
)

SCENARIO_AUDIT_CONTRACT_VERSION: Final = "scenario_calibration_audit_v1"
_PLAYER_INTERVAL_LOW: Final = 0.05
_PLAYER_INTERVAL_HIGH: Final = 0.95


@dataclass(frozen=True, slots=True)
class ScenarioAuditFoldRow:
    """One fold's frozen decision measured against its scenario distribution."""

    fold_id: str
    realized_score: float
    scenario_mean_score: float
    scenario_lower_quantile_score: float
    probability_below_threshold: float
    probability_integral_transform: float

    def __post_init__(self) -> None:
        values = (
            self.realized_score,
            self.scenario_mean_score,
            self.scenario_lower_quantile_score,
        )
        if any(not math.isfinite(value) for value in values):
            raise ExperimentExecutionError("Audit fold metrics must be finite.")
        for name in ("probability_below_threshold", "probability_integral_transform"):
            value = getattr(self, name)
            if not 0.0 <= value <= 1.0:
                raise ExperimentExecutionError(f"{name} must lie in [0, 1].")


@dataclass(frozen=True, slots=True)
class ScenarioAuditResult:
    """Decision- and player-level calibration summaries over all eligible folds."""

    rows: tuple[ScenarioAuditFoldRow, ...]
    lower_quantile: float
    points_threshold: float
    realized_below_scenario_quantile_rate: float
    mean_pit: float
    pit_below_10_rate: float
    pit_above_90_rate: float
    mean_score_bias: float
    predicted_bad_week_probability: float
    realized_bad_week_frequency: float
    player_interval_coverage: Mapping[str, float]
    player_interval_nominal: float
    diagnostics: Mapping[str, object]
    contract_version: str = SCENARIO_AUDIT_CONTRACT_VERSION

    def __post_init__(self) -> None:
        if self.contract_version != SCENARIO_AUDIT_CONTRACT_VERSION:
            raise ExperimentExecutionError("Unsupported scenario audit contract_version.")
        if not self.rows:
            raise ExperimentExecutionError("An audit needs at least one fold row.")
        object.__setattr__(
            self, "player_interval_coverage", MappingProxyType(dict(self.player_interval_coverage))
        )
        object.__setattr__(self, "diagnostics", MappingProxyType(dict(self.diagnostics)))


def audit_scenario_calibration(
    objective: ScenarioPolicyObjective,
    residual_history: pd.DataFrame,
    *,
    form_window: int,
    bench_weight: float,
    lower_quantile: float = 0.10,
    points_threshold: float = 40.0,
) -> ScenarioAuditResult:
    """Measure scenario calibration on the objective's own folds and pools.

    The frozen decision per fold is the risk-neutral deterministic squad, so the
    audit isolates the scenarios: the decision never depends on them, and every
    comparison is scenario-implied versus realized for one fixed squad.
    """

    if not isinstance(objective, ScenarioPolicyObjective):
        raise ExperimentExecutionError("objective must be a ScenarioPolicyObjective.")
    if not isinstance(residual_history, pd.DataFrame):
        raise ExperimentExecutionError("residual_history must be a pandas DataFrame.")
    if not isinstance(lower_quantile, float) or not 0.0 < lower_quantile < 1.0:
        raise ExperimentExecutionError("lower_quantile must lie strictly in (0, 1).")

    settings = objective.config
    optimization_config = OptimizationConfig(bench_weight=bench_weight)
    scenario_config = ScenarioConfig(
        scenario_count=settings.scenario_count,
        deterministic_seed=settings.deterministic_seed,
        min_history_folds=settings.min_history_folds,
        min_player_observations=settings.min_player_observations,
    )
    evaluation_config = ScenarioEvaluationConfig(
        lower_quantile=lower_quantile,
        worst_fraction=settings.tail_fraction,
        points_threshold=points_threshold,
    )
    contexts = objective.fold_contexts(form_window)
    provenance = PredictionProvenance(
        model_name="deterministic_baseline",
        model_version=f"form_window_{form_window:02d}_v1",
        feature_contract_version=FEATURE_GENERATION_CONTRACT_VERSION,
        training_cutoff="pre_fold_projection",
        training_data_fingerprint=hashlib.sha256(
            ",".join(context.fold_id for context in contexts).encode("utf-8")
        ).hexdigest(),
    )

    rows: list[ScenarioAuditFoldRow] = []
    covered_by_position: dict[str, int] = {}
    total_by_position: dict[str, int] = {}
    for context in contexts:
        history = residual_history.loc[
            residual_history["fold_id"].astype(str).isin(context.prior_fold_ids)
        ]
        decision = optimize_squad(context.projections, optimization_config)
        if not decision.has_solution:
            raise ExperimentExecutionError(
                f"Fold {context.fold_id} has no feasible risk-neutral decision."
            )
        snapshot = prepare_optimizer_projection(
            context.projections.loc[
                :, ["player_id", "name", "team_id", "position", "price_tenths"]
            ],
            context.projections.loc[:, ["player_id", "expected_points"]],
            provenance,
        )
        scenario_set = generate_scenarios(
            snapshot,
            history,
            ScenarioTarget(context.season, context.gameweek),
            scenario_config,
        )
        evaluated = evaluate_fixed_decision(decision, scenario_set, evaluation_config)
        realized_score = score_realized_squad_points(decision, context.realized_points)
        scores = np.asarray(evaluated.scenario_scores, dtype="float64")
        rows.append(
            ScenarioAuditFoldRow(
                fold_id=context.fold_id,
                realized_score=realized_score,
                scenario_mean_score=evaluated.metrics.mean_score,
                scenario_lower_quantile_score=evaluated.metrics.lower_quantile_score,
                probability_below_threshold=(evaluated.metrics.probability_below_threshold),
                probability_integral_transform=float((scores <= realized_score).mean()),
            )
        )

        matrix = scenario_set.scenario_points
        realized_players = context.realized_points.set_index("player_id")["total_points"]
        positions = context.projections.set_index("player_id")["position"]
        low = matrix.quantile(_PLAYER_INTERVAL_LOW, axis=0)
        high = matrix.quantile(_PLAYER_INTERVAL_HIGH, axis=0)
        for player_id in matrix.columns:
            if player_id not in realized_players.index:
                continue
            realized_value = float(realized_players.loc[player_id])
            position = str(positions.loc[player_id])
            total_by_position[position] = total_by_position.get(position, 0) + 1
            if float(low[player_id]) <= realized_value <= float(high[player_id]):
                covered_by_position[position] = covered_by_position.get(position, 0) + 1

    realized = np.asarray([row.realized_score for row in rows], dtype="float64")
    quantiles = np.asarray([row.scenario_lower_quantile_score for row in rows], dtype="float64")
    means = np.asarray([row.scenario_mean_score for row in rows], dtype="float64")
    pits = np.asarray([row.probability_integral_transform for row in rows], dtype="float64")
    predicted_bad = float(np.mean([row.probability_below_threshold for row in rows]))
    coverage = {
        position: covered_by_position.get(position, 0) / count
        for position, count in sorted(total_by_position.items())
    }
    return ScenarioAuditResult(
        rows=tuple(rows),
        lower_quantile=lower_quantile,
        points_threshold=points_threshold,
        realized_below_scenario_quantile_rate=float((realized < quantiles).mean()),
        mean_pit=float(pits.mean()),
        pit_below_10_rate=float((pits < 0.10).mean()),
        pit_above_90_rate=float((pits > 0.90).mean()),
        mean_score_bias=float((means - realized).mean()),
        predicted_bad_week_probability=predicted_bad,
        realized_bad_week_frequency=float((realized < points_threshold).mean()),
        player_interval_coverage=coverage,
        player_interval_nominal=_PLAYER_INTERVAL_HIGH - _PLAYER_INTERVAL_LOW,
        diagnostics={
            "fold_count": len(rows),
            "form_window": form_window,
            "bench_weight": bench_weight,
            "scenario_count": settings.scenario_count,
            "decision_rule": "risk_neutral_deterministic_squad",
            "objective_configuration_fingerprint": settings.configuration_fingerprint,
        },
    )
