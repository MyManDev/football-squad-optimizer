"""Real development-fold objective for deterministic Bayesian policy search.

This adapter closes the gap between `run_bayesian_optimization`'s narrow callback and
the existing chronological evaluation machinery: one call evaluates one deterministic
policy configuration (`form_window`, `bench_weight`) on the real development folds and
returns the mean realized squad points under the frozen evaluation objective.

`risk_aversion` is deliberately not a searchable factor here. The deterministic
baseline evaluator has no scenario input, so a nonzero risk aversion could not change
its decisions; searching over it would produce a flat, fake axis in the trace. The
pinned value (the operational control's 0.0) is recorded in every evaluation's
metadata instead.
"""

import hashlib
import json
import math
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from numbers import Integral, Real
from types import MappingProxyType
from typing import Final

import pandas as pd

from squadopt.backtest import (
    realized_points_at,
    season_ranks,
    walk_forward_decision_points,
)
from squadopt.bayesopt import BayesianCandidate
from squadopt.evaluation import EvaluationConfig, EvaluationFold, evaluate_prepared_folds
from squadopt.experiments.config import (
    DEFAULT_DEVELOPMENT_SEASONS,
    ExperimentConfigurationError,
    ExperimentExecutionError,
)
from squadopt.features import CrossSeasonConfig, build_feature_dataset
from squadopt.optimization import OptimizationConfig
from squadopt.prediction import FormWindowMapping, build_projection_table

POLICY_OBJECTIVE_CONTRACT_VERSION: Final = "baseline_policy_objective_v1"
EVALUATION_OBJECTIVE_VERSION: Final = "single_gameweek_realized_squad_points_v1"
POLICY_SEARCH_FACTOR_NAMES: Final = ("form_window", "bench_weight")
PINNED_RISK_AVERSION: Final = 0.0
SHRINKAGE_RULE_VERSION: Final = "position_mean_shrinkage_v1"


def shrink_projections(projections: pd.DataFrame, strength: float) -> pd.DataFrame:
    """Shrink expected points toward each position's within-fold mean.

    The selection-optimism profile showed the projections are unbiased over the
    roster while the *top of the ranking* is systematically optimistic. Proportional
    shrinkage toward the position mean reduces exactly the extreme values the
    optimizer selects, without touching the prediction contract: this is a
    decision-side post-processing (`position_mean_shrinkage_v1`), applied after the
    projection table is built and before the optimizer sees it.
    """

    if not 0.0 <= strength <= 1.0:
        raise ExperimentConfigurationError("shrinkage strength must lie in [0, 1].")
    if strength == 0.0:
        return projections
    table = projections.copy(deep=True)
    position_means = table.groupby("position")["expected_points"].transform("mean")
    table["expected_points"] = (1.0 - strength) * table["expected_points"].astype(
        "float64"
    ) + strength * position_means.astype("float64")
    return table


@dataclass(frozen=True, slots=True)
class PolicyObjectiveConfig:
    """Frozen evaluation controls shared by every candidate in one search."""

    development_seasons: tuple[str, ...] = DEFAULT_DEVELOPMENT_SEASONS
    min_prior_gameweeks_in_season: int = 1
    projection_shrinkage: float = 0.0
    cross_season_config: CrossSeasonConfig = field(default_factory=CrossSeasonConfig)
    optimization_config: OptimizationConfig = field(default_factory=OptimizationConfig)

    def __post_init__(self) -> None:
        seasons = self.development_seasons
        if (
            not isinstance(seasons, tuple)
            or not seasons
            or any(not isinstance(season, str) or not season.strip() for season in seasons)
        ):
            raise ExperimentConfigurationError(
                "development_seasons must be a non-empty tuple of season labels."
            )
        normalized = tuple(season.strip() for season in seasons)
        if len(set(normalized)) != len(normalized):
            raise ExperimentConfigurationError("development_seasons must be unique.")
        object.__setattr__(self, "development_seasons", normalized)
        minimum = self.min_prior_gameweeks_in_season
        if isinstance(minimum, bool) or not isinstance(minimum, Integral) or int(minimum) < 1:
            raise ExperimentConfigurationError(
                "min_prior_gameweeks_in_season must be an integer of at least 1; "
                "opening gameweeks are a separate evidence regime."
            )
        object.__setattr__(self, "min_prior_gameweeks_in_season", int(minimum))
        strength = self.projection_shrinkage
        if (
            isinstance(strength, bool)
            or not isinstance(strength, Real)
            or not math.isfinite(float(strength))
            or not 0.0 <= float(strength) <= 1.0
        ):
            raise ExperimentConfigurationError("projection_shrinkage must lie in [0, 1].")
        object.__setattr__(self, "projection_shrinkage", float(strength))
        if not isinstance(self.cross_season_config, CrossSeasonConfig):
            raise ExperimentConfigurationError(
                "cross_season_config must be a CrossSeasonConfig instance."
            )
        if not isinstance(self.optimization_config, OptimizationConfig):
            raise ExperimentConfigurationError(
                "optimization_config must be an OptimizationConfig instance."
            )

    @property
    def configuration_fingerprint(self) -> str:
        """Return a stable digest of every objective-affecting control."""

        optimization = self.optimization_config
        payload = {
            "contract_version": POLICY_OBJECTIVE_CONTRACT_VERSION,
            "evaluation_objective": EVALUATION_OBJECTIVE_VERSION,
            "development_seasons": self.development_seasons,
            "min_prior_gameweeks_in_season": self.min_prior_gameweeks_in_season,
            "pinned_risk_aversion": PINNED_RISK_AVERSION,
            "projection_shrinkage": float(self.projection_shrinkage).hex(),
            "shrinkage_rule": SHRINKAGE_RULE_VERSION,
            "cross_season": {
                "decay": self.cross_season_config.decay,
                "min_minutes": self.cross_season_config.min_minutes,
            },
            "optimization": {
                "budget_tenths": optimization.budget_tenths,
                "squad_size": optimization.squad_size,
                "max_players_per_team": optimization.max_players_per_team,
                "expected_points_scale": optimization.expected_points_scale,
                "deterministic_seed": optimization.deterministic_seed,
            },
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


class BaselinePolicyObjective:
    """Evaluate deterministic policy candidates on real chronological folds.

    The instance satisfies the search's `ObjectiveEvaluator` callback. Projection
    folds are cached per `form_window`, because shifted features for one window are
    identical for every `bench_weight`; only the optimizer objective changes.
    """

    def __init__(
        self,
        panel: pd.DataFrame,
        config: PolicyObjectiveConfig | None = None,
    ) -> None:
        settings = PolicyObjectiveConfig() if config is None else config
        if not isinstance(settings, PolicyObjectiveConfig):
            raise ExperimentExecutionError("config must be a PolicyObjectiveConfig instance.")
        if not isinstance(panel, pd.DataFrame):
            raise ExperimentExecutionError("panel must be a pandas DataFrame.")
        ranks = season_ranks(panel)
        unknown = sorted(set(settings.development_seasons) - set(ranks))
        if unknown:
            raise ExperimentExecutionError(
                f"Development seasons are absent from the panel: {unknown!r}."
            )
        last_rank = max(ranks[season] for season in settings.development_seasons)
        keep = panel["season"].map(lambda season: ranks[str(season)] <= last_rank)
        visible_panel = panel.loc[keep].copy(deep=True)
        decisions = walk_forward_decision_points(
            visible_panel,
            seasons=settings.development_seasons,
            min_prior_gameweeks_in_season=settings.min_prior_gameweeks_in_season,
        )
        if not decisions:
            raise ExperimentExecutionError(
                "No decision points remain for the requested development seasons."
            )
        self._settings = settings
        self._visible_panel = visible_panel
        self._decisions = decisions
        self._fold_ids = tuple(decision.fold_id for decision in decisions)
        self._fold_cache: dict[int, tuple[EvaluationFold, ...]] = {}
        self._records: dict[str, dict[str, object]] = {}

    @property
    def config(self) -> PolicyObjectiveConfig:
        """Return the frozen evaluation controls this objective runs under."""

        return self._settings

    @property
    def development_fold_ids(self) -> tuple[str, ...]:
        """Return the chronological fold identifiers every candidate is scored on."""

        return self._fold_ids

    @property
    def records(self) -> Mapping[str, Mapping[str, object]]:
        """Return per-candidate evaluation records keyed by candidate ID."""

        return MappingProxyType(
            {key: MappingProxyType(dict(value)) for key, value in self._records.items()}
        )

    def _folds(self, form_window: int) -> tuple[EvaluationFold, ...]:
        cached = self._fold_cache.get(form_window)
        if cached is not None:
            return cached
        mapping = FormWindowMapping(form_window=form_window)
        features = build_feature_dataset(
            self._visible_panel,
            config=mapping.feature_config,
            cross_season=self._settings.cross_season_config,
        )
        folds = tuple(
            EvaluationFold(
                fold_id=decision.fold_id,
                projections=shrink_projections(
                    build_projection_table(
                        features,
                        season=decision.season,
                        gameweek=decision.gameweek,
                        config=mapping.projection_config,
                    ),
                    self._settings.projection_shrinkage,
                ),
                realized_points=realized_points_at(self._visible_panel, decision),
                metadata={
                    "season": decision.season,
                    "gameweek": decision.gameweek,
                    "feature_preparation": "full_visible_season_shifted_v1",
                    "projection_shrinkage": self._settings.projection_shrinkage,
                },
            )
            for decision in self._decisions
        )
        self._fold_cache[form_window] = folds
        return folds

    def _factors(self, candidate: BayesianCandidate) -> tuple[int, float]:
        if not isinstance(candidate, BayesianCandidate):
            raise ExperimentExecutionError("candidate must be a BayesianCandidate.")
        names = set(candidate.values)
        missing = sorted(set(POLICY_SEARCH_FACTOR_NAMES) - names)
        unexpected = sorted(names - set(POLICY_SEARCH_FACTOR_NAMES))
        if missing or unexpected:
            raise ExperimentExecutionError(
                "Candidate factors do not match the deterministic policy objective: "
                f"missing {missing!r}, unexpected {unexpected!r}. A factor this "
                "evaluator cannot honor must not appear in the search space."
            )
        window_value = candidate.values["form_window"]
        if isinstance(window_value, float):
            if not window_value.is_integer():
                raise ExperimentExecutionError("form_window must be an integer-valued factor.")
            window_value = int(window_value)
        weight_value = candidate.values["bench_weight"]
        if isinstance(weight_value, bool) or not isinstance(weight_value, Real):
            raise ExperimentExecutionError("bench_weight must be a finite number.")
        weight = float(weight_value)
        if not math.isfinite(weight) or not 0.0 <= weight <= 1.0:
            raise ExperimentExecutionError("bench_weight must lie in [0, 1].")
        return int(window_value), weight

    def __call__(
        self,
        candidate: BayesianCandidate,
        development_fold_ids: tuple[str, ...],
    ) -> float:
        form_window, bench_weight = self._factors(candidate)
        if set(development_fold_ids) != set(self._fold_ids):
            raise ExperimentExecutionError(
                "Requested folds do not match this objective's development folds; "
                "the search and the evaluator must be constructed from the same panel."
            )
        folds = self._folds(form_window)
        evaluation_config = EvaluationConfig(
            optimization_config=replace(
                self._settings.optimization_config,
                bench_weight=bench_weight,
            ),
            run_metadata={
                "policy_objective_contract_version": POLICY_OBJECTIVE_CONTRACT_VERSION,
                "evaluation_objective": EVALUATION_OBJECTIVE_VERSION,
                "candidate_id": candidate.candidate_id,
                "form_window": form_window,
                "bench_weight": bench_weight,
                "risk_aversion": PINNED_RISK_AVERSION,
                "development_seasons": self._settings.development_seasons,
            },
        )
        result = evaluate_prepared_folds(folds, evaluation_config)
        mean_points = result.summary.mean_realized_squad_points
        if result.summary.scored_folds != len(folds) or mean_points is None:
            raise ExperimentExecutionError(
                f"Candidate {candidate.candidate_id} scored "
                f"{result.summary.scored_folds}/{len(folds)} folds; an incomplete "
                "evaluation cannot be compared against complete ones."
            )
        self._records[candidate.candidate_id] = {
            "form_window": form_window,
            "bench_weight": bench_weight,
            "risk_aversion": PINNED_RISK_AVERSION,
            "mean_realized_squad_points": float(mean_points),
            "realized_squad_points_stddev": result.summary.realized_squad_points_stddev,
            "scored_folds": result.summary.scored_folds,
            "median_solver_runtime_seconds": (result.summary.median_solver_runtime_seconds),
        }
        return float(mean_points)
