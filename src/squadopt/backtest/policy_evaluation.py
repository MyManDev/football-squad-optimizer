"""Prediction-side implementation of the Bayesian search's development-fold seam.

``squadopt.bayesopt.evaluation`` fixes the seam and leaves the builder to this side, for
a reason worth restating: ``form_window`` is a *prediction* factor. It selects which
shifted feature windows a projection reads, through the frozen ``form_window_v1``
mapping, and reinterpreting it here would let a search claim it tuned one thing while
tuning another.

So this module owns exactly that translation and nothing else. It applies
``FormWindowMapping`` unchanged, hands ``bench_weight`` to the optimizer objective, and
scores the frozen chronological development population.

``risk_aversion`` is refused rather than accepted-and-ignored. A deterministic projection
produces one number per player, so there is no distribution for a risk preference to act
on; a nonzero value could not change any decision this evaluator makes. Accepting it
would put a flat axis in the search trace and let a report attribute an effect to a
factor that never had one. The scenario-aware objective is where that axis is real.
"""

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from numbers import Integral
from types import MappingProxyType
from typing import Final

import pandas as pd

from squadopt.backtest.splits import (
    BacktestConfigurationError,
    realized_points_at,
    season_ranks,
    walk_forward_decision_points,
)
from squadopt.bayesopt import (
    BayesianOptimizationExecutionError,
    DeterministicPolicyFactors,
    DevelopmentFoldEvaluation,
)
from squadopt.evaluation import EvaluationConfig, EvaluationFold, evaluate_prepared_folds
from squadopt.features import CrossSeasonConfig, build_feature_dataset
from squadopt.optimization import OptimizationConfig
from squadopt.prediction import FormWindowMapping, build_projection_table

PREDICTION_POLICY_EVALUATION_CONTRACT_VERSION: Final = "prediction_policy_evaluation_v1"
EVALUATION_OBJECTIVE_VERSION: Final = "single_gameweek_realized_squad_points_v1"
FORM_WINDOW_MAPPING_VERSION: Final = "form_window_v1"

# The development population. 2025-26 is the locked holdout and is never a member.
DEFAULT_DEVELOPMENT_SEASONS: Final = ("2021-22", "2022-23", "2023-24", "2024-25")


@dataclass(frozen=True, slots=True)
class PredictionPolicyEvaluatorConfig:
    """Frozen controls every candidate in one search is scored under."""

    development_seasons: tuple[str, ...] = DEFAULT_DEVELOPMENT_SEASONS
    min_prior_gameweeks_in_season: int = 1
    cross_season_config: CrossSeasonConfig = field(default_factory=CrossSeasonConfig)
    optimization_config: OptimizationConfig = field(default_factory=OptimizationConfig)

    def __post_init__(self) -> None:
        seasons = self.development_seasons
        if (
            not isinstance(seasons, tuple)
            or not seasons
            or any(not isinstance(season, str) or not season.strip() for season in seasons)
        ):
            raise BacktestConfigurationError(
                "development_seasons must be a non-empty tuple of season labels."
            )
        normalized = tuple(season.strip() for season in seasons)
        if len(set(normalized)) != len(normalized):
            raise BacktestConfigurationError("development_seasons must be unique.")
        object.__setattr__(self, "development_seasons", normalized)

        minimum = self.min_prior_gameweeks_in_season
        if isinstance(minimum, bool) or not isinstance(minimum, Integral) or int(minimum) < 1:
            raise BacktestConfigurationError(
                "min_prior_gameweeks_in_season must be an integer of at least 1; opening "
                "gameweeks are a separate evidence regime."
            )
        object.__setattr__(self, "min_prior_gameweeks_in_season", int(minimum))

        if not isinstance(self.cross_season_config, CrossSeasonConfig):
            raise BacktestConfigurationError("cross_season_config must be a CrossSeasonConfig.")
        if not isinstance(self.optimization_config, OptimizationConfig):
            raise BacktestConfigurationError("optimization_config must be an OptimizationConfig.")


class DevelopmentFoldPredictionEvaluator:
    """Score one policy configuration on the frozen chronological development folds.

    Satisfies :class:`squadopt.bayesopt.DevelopmentFoldPolicyEvaluator`, so
    ``bind_policy_evaluator`` accepts an instance directly.

    Folds are cached per ``form_window`` because the shifted features for one window are
    identical whatever the optimizer's bench weight; only the objective changes. That
    makes a search over bench weights cheap and, more importantly, guarantees every
    candidate sharing a window is scored on byte-identical projections.
    """

    def __init__(
        self,
        panel: pd.DataFrame,
        config: PredictionPolicyEvaluatorConfig | None = None,
    ) -> None:
        settings = PredictionPolicyEvaluatorConfig() if config is None else config
        if not isinstance(settings, PredictionPolicyEvaluatorConfig):
            raise BacktestConfigurationError(
                "config must be a PredictionPolicyEvaluatorConfig instance."
            )
        if not isinstance(panel, pd.DataFrame):
            raise BacktestConfigurationError("panel must be a pandas DataFrame.")

        ranks = season_ranks(panel)
        unknown = sorted(set(settings.development_seasons) - set(ranks))
        if unknown:
            raise BacktestConfigurationError(
                f"Development seasons are absent from the panel: {unknown!r}."
            )

        # Everything after the last development season is cut away here rather than
        # filtered later, so a locked-holdout row cannot reach a feature window even as
        # carry-over history.
        last_rank = max(ranks[season] for season in settings.development_seasons)
        visible = panel.loc[panel["season"].map(lambda season: ranks[str(season)] <= last_rank)]

        decisions = walk_forward_decision_points(
            visible,
            seasons=settings.development_seasons,
            min_prior_gameweeks_in_season=settings.min_prior_gameweeks_in_season,
        )
        if not decisions:
            raise BacktestConfigurationError(
                "No decision points remain for the requested development seasons."
            )

        self._settings = settings
        self._panel = visible.copy(deep=True)
        self._decisions = decisions
        self._fold_ids = tuple(decision.fold_id for decision in decisions)
        self._fold_cache: dict[int, tuple[EvaluationFold, ...]] = {}

    @property
    def config(self) -> PredictionPolicyEvaluatorConfig:
        """Return the frozen controls this evaluator scores under."""

        return self._settings

    @property
    def development_fold_ids(self) -> tuple[str, ...]:
        """Return the chronological folds every candidate is scored on."""

        return self._fold_ids

    def _folds(self, form_window: int) -> tuple[EvaluationFold, ...]:
        cached = self._fold_cache.get(form_window)
        if cached is not None:
            return cached

        mapping = FormWindowMapping(form_window=form_window)
        features = build_feature_dataset(
            self._panel,
            config=mapping.feature_config,
            cross_season=self._settings.cross_season_config,
        )
        folds = tuple(
            EvaluationFold(
                fold_id=decision.fold_id,
                projections=build_projection_table(
                    features,
                    season=decision.season,
                    gameweek=decision.gameweek,
                    config=mapping.projection_config,
                ),
                realized_points=realized_points_at(self._panel, decision),
                metadata={
                    "season": decision.season,
                    "gameweek": decision.gameweek,
                    "form_window": form_window,
                    "form_window_mapping_version": FORM_WINDOW_MAPPING_VERSION,
                },
            )
            for decision in self._decisions
        )
        self._fold_cache[form_window] = folds
        return folds

    def _require_declared_population(self, requested: Sequence[str]) -> None:
        if not isinstance(requested, tuple):
            raise BayesianOptimizationExecutionError(
                "development_fold_ids must be a tuple of fold identifiers."
            )
        missing = sorted(set(self._fold_ids) - set(requested))
        extra = sorted(set(requested) - set(self._fold_ids))
        if missing or extra:
            raise BayesianOptimizationExecutionError(
                "Requested folds do not match this evaluator's development population: "
                f"missing {missing!r}, extra {extra!r}. The search and the evaluator must "
                "be built from the same panel and seasons."
            )

    def __call__(
        self,
        factors: DeterministicPolicyFactors,
        development_fold_ids: tuple[str, ...],
    ) -> DevelopmentFoldEvaluation:
        if not isinstance(factors, DeterministicPolicyFactors):
            raise BayesianOptimizationExecutionError(
                "factors must be a DeterministicPolicyFactors instance."
            )
        if factors.risk_aversion != 0.0:
            raise BayesianOptimizationExecutionError(
                f"risk_aversion={factors.risk_aversion!r} cannot be honored by a "
                "deterministic projection: a point estimate carries no distribution for a "
                "risk preference to act on, so the factor would change no decision. Search "
                "risk aversion through the scenario-aware objective, or pin it to 0.0."
            )
        self._require_declared_population(development_fold_ids)

        folds = self._folds(factors.form_window)
        evaluation_config = EvaluationConfig(
            optimization_config=replace(
                self._settings.optimization_config,
                bench_weight=factors.bench_weight,
            ),
            run_metadata={
                "policy_evaluation_contract_version": (
                    PREDICTION_POLICY_EVALUATION_CONTRACT_VERSION
                ),
                "evaluation_objective": EVALUATION_OBJECTIVE_VERSION,
                "form_window": factors.form_window,
                "form_window_mapping_version": FORM_WINDOW_MAPPING_VERSION,
                "bench_weight": factors.bench_weight,
                "risk_aversion": factors.risk_aversion,
                "development_seasons": self._settings.development_seasons,
            },
        )
        result = evaluate_prepared_folds(folds, evaluation_config)

        mean_points = result.summary.mean_realized_squad_points
        if result.summary.scored_folds != len(folds) or mean_points is None:
            raise BayesianOptimizationExecutionError(
                f"Scored {result.summary.scored_folds}/{len(folds)} folds; an incomplete "
                "evaluation cannot be compared against complete ones."
            )
        if not math.isfinite(float(mean_points)):
            raise BayesianOptimizationExecutionError(
                "The development objective is not finite; it cannot rank candidates."
            )

        return DevelopmentFoldEvaluation(
            objective_value=float(mean_points),
            evaluated_fold_ids=tuple(fold.fold_id for fold in folds),
            objective_version=EVALUATION_OBJECTIVE_VERSION,
            provenance=self._provenance(factors, result.summary),
        )

    def _provenance(
        self,
        factors: DeterministicPolicyFactors,
        summary: object,
    ) -> Mapping[str, object]:
        """Record what produced one objective value, including the factor translation."""

        return MappingProxyType(
            {
                "contract_version": PREDICTION_POLICY_EVALUATION_CONTRACT_VERSION,
                "form_window": factors.form_window,
                "form_window_mapping_version": FORM_WINDOW_MAPPING_VERSION,
                "bench_weight": factors.bench_weight,
                "risk_aversion": factors.risk_aversion,
                "development_seasons": self._settings.development_seasons,
                "min_prior_gameweeks_in_season": (self._settings.min_prior_gameweeks_in_season),
                "scored_folds": getattr(summary, "scored_folds", None),
                "realized_squad_points_stddev": getattr(
                    summary, "realized_squad_points_stddev", None
                ),
                "median_solver_runtime_seconds": getattr(
                    summary, "median_solver_runtime_seconds", None
                ),
            }
        )
