"""Rehearse the rank-probability objective on real folds against a template rival.

For each eligible fold the risk-neutral deterministic squad is frozen as the **template
rival** — the squad this model would field — and the rank-probability objective is asked
for the squad most likely to finish ahead of it, at each expected-points budget. What the
optimizer *claims* (its scenario probability of being ahead) is then compared with what
*happened* (whether the chosen squad out-scored the template on realized points), fold by
fold: if the claims are honest, the realized frequency of being ahead matches the mean
claimed probability, and the realized cost matches the expected-points budget paid.

Against its own template a differential is cheap to find and worth little; the point is
the mechanism and its calibration, not the size of the gain. Measurement only.
"""

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Final

import numpy as np
import pandas as pd

from squadopt.evaluation import score_realized_squad_points
from squadopt.experiments.config import ExperimentExecutionError
from squadopt.experiments.scenario_policy_objective import ScenarioPolicyObjective
from squadopt.optimization import OptimizationConfig, optimize_squad
from squadopt.prediction import (
    FEATURE_GENERATION_CONTRACT_VERSION,
    PredictionProvenance,
    prepare_optimizer_projection,
)
from squadopt.scenarios import (
    RankObjectiveConfig,
    RivalSquad,
    ScenarioConfig,
    ScenarioTarget,
    generate_scenarios,
    optimize_rank_probability_squad,
    wilson_interval,
)

RANK_REHEARSAL_CONTRACT_VERSION: Final = "rank_objective_rehearsal_v1"


@dataclass(frozen=True, slots=True)
class RankRehearsalRow:
    fold_id: str
    expected_points_budget: float | None
    claimed_probability_ahead: float
    scenario_mean_score: float
    template_scenario_mean_score: float
    realized_score: float
    template_realized_score: float
    realized_ahead: bool
    starters_changed: int
    captain_changed: bool
    solver_status: str


@dataclass(frozen=True, slots=True)
class RankRehearsalBudgetSummary:
    expected_points_budget: float | None
    folds: int
    mean_claimed_probability: float
    realized_ahead_frequency: float
    realized_ahead_interval: tuple[float, float]
    mean_expected_cost: float
    mean_realized_cost: float
    mean_starters_changed: float
    captain_changed_share: float
    proven_share: float


@dataclass(frozen=True, slots=True)
class RankRehearsalResult:
    rows: tuple[RankRehearsalRow, ...]
    summaries: tuple[RankRehearsalBudgetSummary, ...]
    diagnostics: Mapping[str, object] = field(default_factory=dict)
    contract_version: str = RANK_REHEARSAL_CONTRACT_VERSION

    def __post_init__(self) -> None:
        if not self.rows:
            raise ExperimentExecutionError("A rehearsal needs at least one fold row.")
        object.__setattr__(self, "diagnostics", MappingProxyType(dict(self.diagnostics)))


def rehearse_rank_objective(
    objective: ScenarioPolicyObjective,
    residual_history: pd.DataFrame,
    *,
    form_window: int,
    bench_weight: float,
    budgets: Sequence[float | None] = (0.0, 2.0, 4.0, None),
    margin_points: float = 0.0,
    optimization_config: OptimizationConfig | None = None,
) -> RankRehearsalResult:
    """Run the rank objective against the template rival on every eligible fold."""

    if not isinstance(objective, ScenarioPolicyObjective):
        raise ExperimentExecutionError("objective must be a ScenarioPolicyObjective.")
    settings = objective.config
    base_optimization = OptimizationConfig() if optimization_config is None else optimization_config
    reference_config = OptimizationConfig(bench_weight=bench_weight)
    scenario_config = ScenarioConfig(
        scenario_count=settings.scenario_count,
        deterministic_seed=settings.deterministic_seed,
        min_history_folds=settings.min_history_folds,
        min_player_observations=settings.min_player_observations,
        player_location_shrinkage=settings.player_location_shrinkage,
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
    rows: list[RankRehearsalRow] = []
    for context in contexts:
        history = residual_history.loc[
            residual_history["fold_id"].astype(str).isin(context.prior_fold_ids)
        ]
        template = optimize_squad(context.projections, reference_config)
        if not template.has_solution or template.captain is None:
            raise ExperimentExecutionError(f"Fold {context.fold_id} has no template squad.")
        snapshot = prepare_optimizer_projection(
            context.projections.loc[
                :, ["player_id", "name", "team_id", "position", "price_tenths"]
            ],
            context.projections.loc[:, ["player_id", "expected_points"]],
            provenance,
        )
        scenarios = generate_scenarios(
            snapshot, history, ScenarioTarget(context.season, context.gameweek), scenario_config
        )
        template_starters = tuple(template.starting_xi["player_id"].tolist())
        rival = RivalSquad("template", template_starters, template.captain["player_id"])
        matrix = scenarios.scenario_points
        template_mean = float(
            (
                matrix[list(template_starters)].sum(axis=1) + matrix[template.captain["player_id"]]
            ).mean()
        )
        template_realized = float(score_realized_squad_points(template, context.realized_points))
        for budget in budgets:
            result = optimize_rank_probability_squad(
                scenarios,
                rival,
                base_optimization,
                RankObjectiveConfig(margin_points=margin_points, expected_points_budget=budget),
                reference_expected_points=template_mean,
            )
            if not result.has_solution or result.probability_ahead is None:
                continue
            chosen = result.optimization_result
            assert chosen.captain is not None
            realized = float(score_realized_squad_points(chosen, context.realized_points))
            rows.append(
                RankRehearsalRow(
                    fold_id=context.fold_id,
                    expected_points_budget=budget,
                    claimed_probability_ahead=result.probability_ahead,
                    scenario_mean_score=float(result.scenario_mean_score or 0.0),
                    template_scenario_mean_score=template_mean,
                    realized_score=realized,
                    template_realized_score=template_realized,
                    # Built-in bool/int/float, not numpy scalars: the rows are written to JSON.
                    realized_ahead=bool(realized > template_realized),
                    starters_changed=len(
                        set(chosen.starting_xi["player_id"]) - set(template_starters)
                    ),
                    captain_changed=bool(
                        chosen.captain["player_id"] != template.captain["player_id"]
                    ),
                    solver_status=chosen.solver_status.name,
                )
            )

    summaries: list[RankRehearsalBudgetSummary] = []
    for budget in budgets:
        block = [row for row in rows if row.expected_points_budget == budget]
        if not block:
            continue
        ahead = sum(1 for row in block if row.realized_ahead)
        summaries.append(
            RankRehearsalBudgetSummary(
                expected_points_budget=budget,
                folds=len(block),
                mean_claimed_probability=float(
                    np.mean([r.claimed_probability_ahead for r in block])
                ),
                realized_ahead_frequency=ahead / len(block),
                realized_ahead_interval=wilson_interval(ahead, len(block)),
                mean_expected_cost=float(
                    np.mean([r.template_scenario_mean_score - r.scenario_mean_score for r in block])
                ),
                mean_realized_cost=float(
                    np.mean([r.template_realized_score - r.realized_score for r in block])
                ),
                mean_starters_changed=float(np.mean([r.starters_changed for r in block])),
                captain_changed_share=float(np.mean([r.captain_changed for r in block])),
                proven_share=float(np.mean([r.solver_status == "OPTIMAL" for r in block])),
            )
        )
    return RankRehearsalResult(
        rows=tuple(rows),
        summaries=tuple(summaries),
        diagnostics={
            "fold_count": len(contexts),
            "form_window": form_window,
            "bench_weight": bench_weight,
            "scenario_count": settings.scenario_count,
            "budgets": [budget for budget in budgets],
            "margin_points": margin_points,
            "rival": "template: the fold's risk-neutral deterministic squad",
            "solver_time_limit_seconds": base_optimization.solver_time_limit_seconds,
            "solver_deterministic_time_limit": base_optimization.solver_deterministic_time_limit,
            "objective_configuration_fingerprint": settings.configuration_fingerprint,
        },
    )
