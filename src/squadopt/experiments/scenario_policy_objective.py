"""Scenario-based development-fold objective with a live risk_aversion axis.

The deterministic policy objective pins `risk_aversion` at 0.0 because it has no
scenario input a nonzero value could act on. This objective supplies that input: each
fold's decision is optimized against joint player-point scenarios generated from the
control regime's own out-of-sample residual history, restricted to folds strictly
before the decision. `risk_aversion` therefore changes real decisions here, and the
three-factor search space becomes meaningful for the first time.

Leakage rule: the residual history visible to one fold's scenario generation contains
only residuals of chronologically earlier folds. Folds without enough prior history
are excluded from the evaluation population - for every candidate equally - rather
than being padded.
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
    DecisionPoint,
    realized_points_at,
    season_ranks,
    walk_forward_decision_points,
)
from squadopt.bayesopt import BayesianCandidate
from squadopt.evaluation import score_realized_squad_points
from squadopt.experiments.config import (
    DEFAULT_DEVELOPMENT_SEASONS,
    ExperimentConfigurationError,
    ExperimentExecutionError,
)
from squadopt.experiments.policy_objective import EVALUATION_OBJECTIVE_VERSION
from squadopt.features import CrossSeasonConfig, build_feature_dataset
from squadopt.optimization import OptimizationConfig
from squadopt.prediction import (
    FEATURE_GENERATION_CONTRACT_VERSION,
    FormWindowMapping,
    PredictionProvenance,
    build_projection_table,
    prepare_optimizer_projection,
)
from squadopt.scenarios import (
    RESIDUAL_HISTORY_COLUMNS,
    ScenarioConfig,
    ScenarioOptimizationConfig,
    ScenarioTarget,
    generate_scenarios,
    optimize_scenario_aware_squad,
)

SCENARIO_POLICY_OBJECTIVE_CONTRACT_VERSION: Final = "scenario_policy_objective_v1"
SCENARIO_POLICY_FACTOR_NAMES: Final = ("form_window", "bench_weight", "risk_aversion")


@dataclass(frozen=True, slots=True)
class ScenarioFoldContext:
    """One eligible fold's decision-time inputs and later outcomes.

    Exposed so measurement code (audits, diagnostics) can reuse exactly the fold
    population, candidate pools, and leakage rule the search evaluates under,
    instead of re-deriving them and silently drifting.
    """

    fold_id: str
    season: str
    gameweek: int
    projections: pd.DataFrame
    realized_points: pd.DataFrame
    prior_fold_ids: frozenset[str]


@dataclass(frozen=True, slots=True)
class ScenarioPolicyObjectiveConfig:
    """Frozen evaluation controls shared by every candidate in one search."""

    development_seasons: tuple[str, ...] = DEFAULT_DEVELOPMENT_SEASONS
    min_prior_gameweeks_in_season: int = 1
    scenario_count: int = 200
    deterministic_seed: int = 0
    min_history_folds: int = 8
    min_player_observations: int = 8
    tail_fraction: float = 0.10
    candidate_pool_per_position: int = 30
    cheap_pool_per_position: int = 10
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
        for name, minimum in (
            ("min_prior_gameweeks_in_season", 1),
            ("scenario_count", 1),
            ("deterministic_seed", 0),
            ("min_history_folds", 2),
            ("min_player_observations", 2),
            ("candidate_pool_per_position", 5),
            ("cheap_pool_per_position", 0),
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, Integral) or int(value) < minimum:
                raise ExperimentConfigurationError(
                    f"{name} must be an integer of at least {minimum}."
                )
            object.__setattr__(self, name, int(value))
        fraction = self.tail_fraction
        if isinstance(fraction, bool) or not isinstance(fraction, Real):
            raise ExperimentConfigurationError("tail_fraction must be a probability.")
        number = float(fraction)
        if not math.isfinite(number) or not 0.0 < number < 1.0:
            raise ExperimentConfigurationError("tail_fraction must lie strictly in (0, 1).")
        object.__setattr__(self, "tail_fraction", number)
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
            "contract_version": SCENARIO_POLICY_OBJECTIVE_CONTRACT_VERSION,
            "evaluation_objective": EVALUATION_OBJECTIVE_VERSION,
            "development_seasons": self.development_seasons,
            "min_prior_gameweeks_in_season": self.min_prior_gameweeks_in_season,
            "scenario_count": self.scenario_count,
            "deterministic_seed": self.deterministic_seed,
            "min_history_folds": self.min_history_folds,
            "min_player_observations": self.min_player_observations,
            "tail_fraction": float(self.tail_fraction).hex(),
            "candidate_pool_per_position": self.candidate_pool_per_position,
            "cheap_pool_per_position": self.cheap_pool_per_position,
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
                "solver_time_limit_seconds": optimization.solver_time_limit_seconds,
                "solver_deterministic_time_limit": (optimization.solver_deterministic_time_limit),
            },
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


class ScenarioPolicyObjective:
    """Evaluate three-factor policy candidates against scenario-aware decisions.

    One call optimizes every eligible development fold under the candidate's
    `risk_aversion` and `bench_weight`, using scenarios drawn from strictly earlier
    residual history, and returns the mean realized squad points of those frozen
    decisions under the unchanged evaluation objective.
    """

    def __init__(
        self,
        panel: pd.DataFrame,
        residual_history: pd.DataFrame,
        config: ScenarioPolicyObjectiveConfig | None = None,
    ) -> None:
        settings = ScenarioPolicyObjectiveConfig() if config is None else config
        if not isinstance(settings, ScenarioPolicyObjectiveConfig):
            raise ExperimentExecutionError(
                "config must be a ScenarioPolicyObjectiveConfig instance."
            )
        if not isinstance(panel, pd.DataFrame):
            raise ExperimentExecutionError("panel must be a pandas DataFrame.")
        if not isinstance(residual_history, pd.DataFrame):
            raise ExperimentExecutionError("residual_history must be a pandas DataFrame.")
        missing = [column for column in RESIDUAL_HISTORY_COLUMNS if column not in residual_history]
        if missing:
            raise ExperimentExecutionError(
                f"Residual history is missing required columns: {missing!r}."
            )
        history = residual_history.loc[:, list(RESIDUAL_HISTORY_COLUMNS)].copy(deep=True)
        if history.empty:
            raise ExperimentExecutionError("Residual history must contain at least one row.")

        ranks = season_ranks(panel)
        unknown = sorted(set(settings.development_seasons) - set(ranks))
        if unknown:
            raise ExperimentExecutionError(
                f"Development seasons are absent from the panel: {unknown!r}."
            )
        last_rank = max(ranks[season] for season in settings.development_seasons)
        keep = panel["season"].map(lambda season: ranks[str(season)] <= last_rank)
        visible_panel = panel.loc[keep].copy(deep=True)
        all_decisions = walk_forward_decision_points(
            visible_panel,
            seasons=None,
            min_prior_gameweeks_in_season=settings.min_prior_gameweeks_in_season,
        )
        decision_order = {decision.fold_id: index for index, decision in enumerate(all_decisions)}
        history_fold_ids = {str(fold_id) for fold_id in history["fold_id"]}
        foreign = sorted(history_fold_ids - set(decision_order))
        if foreign:
            raise ExperimentExecutionError(
                "Residual history names folds outside the panel's decision points: "
                f"{foreign[:5]!r}. History and panel must share one fold policy."
            )

        evaluation: list[tuple[DecisionPoint, frozenset[str]]] = []
        for decision in all_decisions:
            if decision.season not in settings.development_seasons:
                continue
            prior = frozenset(
                fold_id
                for fold_id in history_fold_ids
                if decision_order[fold_id] < decision_order[decision.fold_id]
            )
            if len(prior) >= settings.min_history_folds:
                evaluation.append((decision, prior))
        if not evaluation:
            raise ExperimentExecutionError(
                "No development fold has enough prior residual history for scenario "
                "generation; nothing can be evaluated."
            )
        self._settings = settings
        self._visible_panel = visible_panel
        self._history = history
        self._evaluation = tuple(evaluation)
        self._fold_ids = tuple(decision.fold_id for decision, _ in evaluation)
        self._fold_cache: dict[int, dict[str, tuple[pd.DataFrame, pd.DataFrame]]] = {}
        self._records: dict[str, dict[str, object]] = {}
        panel_identity = json.dumps(
            {
                "seasons": sorted({str(season) for season in visible_panel["season"]}),
                "rows": len(visible_panel),
                "fold_ids": list(self._fold_ids),
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        self._training_data_fingerprint = hashlib.sha256(panel_identity).hexdigest()

    @property
    def config(self) -> ScenarioPolicyObjectiveConfig:
        """Return the frozen evaluation controls this objective runs under."""

        return self._settings

    @property
    def development_fold_ids(self) -> tuple[str, ...]:
        """Return the eligible chronological folds every candidate is scored on."""

        return self._fold_ids

    @property
    def records(self) -> Mapping[str, Mapping[str, object]]:
        """Return per-candidate evaluation records keyed by candidate ID."""

        return MappingProxyType(
            {key: MappingProxyType(dict(value)) for key, value in self._records.items()}
        )

    def fold_contexts(self, form_window: int) -> tuple[ScenarioFoldContext, ...]:
        """Return every eligible fold's pooled projections, outcomes, and history ids."""

        tables = self._fold_tables(form_window)
        return tuple(
            ScenarioFoldContext(
                fold_id=decision.fold_id,
                season=decision.season,
                gameweek=decision.gameweek,
                projections=tables[decision.fold_id][0].copy(deep=True),
                realized_points=tables[decision.fold_id][1].copy(deep=True),
                prior_fold_ids=prior_fold_ids,
            )
            for decision, prior_fold_ids in self._evaluation
        )

    def _fold_tables(self, form_window: int) -> dict[str, tuple[pd.DataFrame, pd.DataFrame]]:
        cached = self._fold_cache.get(form_window)
        if cached is not None:
            return cached
        mapping = FormWindowMapping(form_window=form_window)
        features = build_feature_dataset(
            self._visible_panel,
            config=mapping.feature_config,
            cross_season=self._settings.cross_season_config,
        )
        tables: dict[str, tuple[pd.DataFrame, pd.DataFrame]] = {}
        for decision, _ in self._evaluation:
            projections = build_projection_table(
                features,
                season=decision.season,
                gameweek=decision.gameweek,
                config=mapping.projection_config,
            )
            realized = realized_points_at(self._visible_panel, decision)
            tables[decision.fold_id] = (self._candidate_pool(projections), realized)
        self._fold_cache[form_window] = tables
        return tables

    def _candidate_pool(self, projections: pd.DataFrame) -> pd.DataFrame:
        """Reduce one fold's projection table to a tractable candidate pool.

        The scenario CVaR model grows with players x scenarios, and the full roster
        makes it unsolvable inside a search budget. Per position the pool keeps the
        highest-projected players plus the cheapest ones (budget feasibility), by one
        rule applied identically to every candidate, so comparisons stay fair. The
        measured objective is therefore the pooled decision problem's; the pool
        sizes are part of the configuration fingerprint.
        """

        pieces: list[pd.DataFrame] = []
        for _, group in projections.groupby("position", sort=True):
            top = group.nlargest(
                self._settings.candidate_pool_per_position, "expected_points", keep="first"
            )
            cheap = group.nsmallest(
                self._settings.cheap_pool_per_position, "price_tenths", keep="first"
            )
            pieces.append(pd.concat([top, cheap]).drop_duplicates(subset="player_id"))
        pool = pd.concat(pieces, ignore_index=True).drop_duplicates(subset="player_id")
        return pool.sort_values("player_id", kind="stable", ignore_index=True)

    def _factors(self, candidate: BayesianCandidate) -> tuple[int, float, float]:
        if not isinstance(candidate, BayesianCandidate):
            raise ExperimentExecutionError("candidate must be a BayesianCandidate.")
        names = set(candidate.values)
        missing = sorted(set(SCENARIO_POLICY_FACTOR_NAMES) - names)
        unexpected = sorted(names - set(SCENARIO_POLICY_FACTOR_NAMES))
        if missing or unexpected:
            raise ExperimentExecutionError(
                "Candidate factors do not match the scenario policy objective: "
                f"missing {missing!r}, unexpected {unexpected!r}."
            )
        window_value = candidate.values["form_window"]
        if isinstance(window_value, float):
            if not window_value.is_integer():
                raise ExperimentExecutionError("form_window must be an integer-valued factor.")
            window_value = int(window_value)
        weight = float(candidate.values["bench_weight"])
        aversion = float(candidate.values["risk_aversion"])
        if not math.isfinite(weight) or not 0.0 <= weight <= 1.0:
            raise ExperimentExecutionError("bench_weight must lie in [0, 1].")
        if not math.isfinite(aversion) or not 0.0 <= aversion <= 1.0:
            raise ExperimentExecutionError("risk_aversion must lie in [0, 1].")
        return int(window_value), weight, aversion

    def __call__(
        self,
        candidate: BayesianCandidate,
        development_fold_ids: tuple[str, ...],
    ) -> float:
        form_window, bench_weight, risk_aversion = self._factors(candidate)
        if set(development_fold_ids) != set(self._fold_ids):
            raise ExperimentExecutionError(
                "Requested folds do not match this objective's eligible folds; the "
                "search and the evaluator must be constructed from the same inputs."
            )
        tables = self._fold_tables(form_window)
        optimization_config = replace(
            self._settings.optimization_config,
            bench_weight=bench_weight,
        )
        scenario_config = ScenarioConfig(
            scenario_count=self._settings.scenario_count,
            deterministic_seed=self._settings.deterministic_seed,
            min_history_folds=self._settings.min_history_folds,
            min_player_observations=self._settings.min_player_observations,
        )
        risk_config = ScenarioOptimizationConfig(
            risk_aversion=risk_aversion,
            tail_fraction=self._settings.tail_fraction,
        )
        provenance = PredictionProvenance(
            model_name="deterministic_baseline",
            model_version=f"form_window_{form_window:02d}_v1",
            feature_contract_version=FEATURE_GENERATION_CONTRACT_VERSION,
            training_cutoff="pre_fold_projection",
            training_data_fingerprint=self._training_data_fingerprint,
        )

        scores: list[float] = []
        pool_sizes: list[int] = []
        for decision, prior_fold_ids in self._evaluation:
            fold_id: str = decision.fold_id
            projections, realized = tables[fold_id]
            pool_sizes.append(len(projections))
            history = self._history.loc[self._history["fold_id"].astype(str).isin(prior_fold_ids)]
            snapshot = prepare_optimizer_projection(
                projections.loc[:, ["player_id", "name", "team_id", "position", "price_tenths"]],
                projections.loc[:, ["player_id", "expected_points"]],
                provenance,
            )
            scenario_set = generate_scenarios(
                snapshot,
                history,
                ScenarioTarget(decision.season, decision.gameweek),
                scenario_config,
            )
            result = optimize_scenario_aware_squad(
                scenario_set,
                optimization_config,
                risk_config,
            )
            if not result.optimization_result.has_solution:
                raise ExperimentExecutionError(
                    f"Fold {fold_id} produced no feasible scenario-aware decision for "
                    f"candidate {candidate.candidate_id}; an incomplete evaluation "
                    "cannot be compared against complete ones."
                )
            scores.append(score_realized_squad_points(result.optimization_result, realized))

        mean_points = sum(scores) / len(scores)
        self._records[candidate.candidate_id] = {
            "form_window": form_window,
            "bench_weight": bench_weight,
            "risk_aversion": risk_aversion,
            "mean_realized_squad_points": mean_points,
            "scored_folds": len(scores),
            "scenario_count": self._settings.scenario_count,
            "tail_fraction": self._settings.tail_fraction,
            "mean_candidate_pool_size": sum(pool_sizes) / len(pool_sizes),
            "fold_ids": self._fold_ids,
            "fold_scores": tuple(scores),
        }
        return mean_points
