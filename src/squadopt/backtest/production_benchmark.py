"""Judge the production projection against the pre-registered gates.

This exists because a verdict computed by a throwaway script is not a verdict anybody
else can check. The comparison, the metrics, the residual table and the gate evaluation
all live here so a second person can reproduce the same numbers from the same command.

Three candidates are run over one fold set: the deterministic baseline, which is the
operational control; the Ridge reference, which is a mandatory second comparison and not
a control; and the production projection. Every candidate sees the same folds and the
same optimizer, so a difference between them is a difference in projection alone.

The metrics are imported rather than reimplemented. Two definitions of a mean absolute
error drift apart, and then two candidates' numbers are comparable only by coincidence.

One distinction is deliberate and load-bearing: what this produces is a **development
gate verdict**, not an operational promotion. Clearing these gates makes a candidate
eligible for the locked holdout protocol; it does not by itself put anything into
production, and the wording throughout says so.
"""

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from numbers import Integral, Real
from typing import Final

import pandas as pd

from squadopt.backtest.folds import (
    ProjectionBuilder,
    build_walk_forward_folds,
    make_baseline_projection_builder,
)
from squadopt.backtest.learned import (
    PairedDecisionMetrics,
    PredictionMetrics,
    build_residual_history,
    make_ridge_projection_builder,
    paired_decision_metrics,
    prediction_metrics,
)
from squadopt.backtest.production import (
    PRODUCTION_FEATURE_CONTRACT_VERSION,
    PRODUCTION_MODEL_NAME,
    PRODUCTION_MODEL_VERSION,
    make_production_projection_builder,
)
from squadopt.backtest.splits import BacktestConfigurationError
from squadopt.evaluation import (
    EvaluationConfig,
    EvaluationFold,
    EvaluationResult,
    evaluate_prepared_folds,
)
from squadopt.experiments import season_aware_moving_block_interval
from squadopt.experiments.config import PromotionPolicy
from squadopt.features import CrossSeasonConfig
from squadopt.optimization import OptimizationConfig, SolverStatus
from squadopt.prediction.learned import RidgeProjectionConfig
from squadopt.prediction.production import ProductionProjectionConfig

PRODUCTION_BENCHMARK_CONTRACT_VERSION: Final = "production_vs_baseline_and_ridge_v1"
CANDIDATE_DECLARATION_CONTRACT_VERSION: Final = "candidate_change_declaration_v1"
DEFAULT_BENCHMARK_WALL_TIME_LIMIT_SECONDS: Final = 120.0
DEFAULT_BENCHMARK_DETERMINISTIC_TIME_LIMIT: Final = 0.5

BASELINE_LABEL: Final = "baseline"
RIDGE_LABEL: Final = "ridge"
PRODUCTION_LABEL: Final = "production"

# The seasons the gates are written against. The 2025-26 holdout is absent on purpose and
# is not read by anything here.
DEFAULT_DEVELOPMENT_SEASONS: Final = ("2021-22", "2022-23", "2023-24", "2024-25")

# The Ridge gate's tolerance on the lower bound, and the relative tolerance allowed on
# whichever of MAE or RMSE does not improve. Both are pre-registered in
# docs/production_prediction_spec.md and are constants here so the report cannot quietly
# be run against a different threshold than the one that was declared.
RIDGE_LOWER_BOUND_TOLERANCE: Final = -0.5
PREDICTION_METRIC_TOLERANCE: Final = 0.05

VERDICT_PROMOTABLE: Final = "eligible_for_holdout_evaluation"
VERDICT_RETAIN_CONTROL: Final = "no_promotion_control_retained"


def _canonical_value(value: object) -> object:
    """Return a stable JSON-compatible representation for a frozen contract."""

    if value is None or isinstance(value, str | bool):
        return value
    if isinstance(value, Integral):
        return int(value)
    if isinstance(value, Real):
        return float(value)
    if isinstance(value, Enum):
        return str(value.value)
    if isinstance(value, Mapping):
        return {str(key): _canonical_value(item) for key, item in sorted(value.items())}
    if isinstance(value, tuple | list):
        return [_canonical_value(item) for item in value]
    if hasattr(value, "__dataclass_fields__"):
        fields = value.__dataclass_fields__
        return {name: _canonical_value(getattr(value, name)) for name in sorted(fields)}
    raise BacktestConfigurationError(
        f"Cannot fingerprint contract value of type {type(value).__name__}."
    )


def _fingerprint(value: object) -> str:
    encoded = json.dumps(_canonical_value(value), sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class CandidateDeclaration:
    """The single model change frozen before a development gate is run."""

    candidate_id: str
    model_name: str
    model_version: str
    feature_contract_version: str
    changed_component: str
    change_summary: str
    frozen_components: tuple[str, ...]
    evaluation_objective: str = "single_gameweek_realized_squad_points_v1"
    source_reference: str = ""
    contract_version: str = CANDIDATE_DECLARATION_CONTRACT_VERSION

    def __post_init__(self) -> None:
        text_fields = (
            "candidate_id",
            "model_name",
            "model_version",
            "feature_contract_version",
            "changed_component",
            "change_summary",
            "evaluation_objective",
            "contract_version",
        )
        for name in text_fields:
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise BacktestConfigurationError(f"{name} must be non-empty text.")
            object.__setattr__(self, name, value.strip())
        if not isinstance(self.source_reference, str):
            raise BacktestConfigurationError("source_reference must be text.")
        object.__setattr__(self, "source_reference", self.source_reference.strip())
        if not isinstance(self.frozen_components, tuple) or not self.frozen_components:
            raise BacktestConfigurationError("frozen_components must be a non-empty tuple.")
        normalized = tuple(
            item.strip() if isinstance(item, str) else "" for item in self.frozen_components
        )
        if any(not item for item in normalized):
            raise BacktestConfigurationError("frozen_components entries must be non-empty text.")
        if len(set(normalized)) != len(normalized):
            raise BacktestConfigurationError("frozen_components entries must be unique.")
        if self.changed_component in normalized:
            raise BacktestConfigurationError(
                "changed_component cannot also be listed as a frozen component."
            )
        object.__setattr__(self, "frozen_components", normalized)

    @property
    def declaration_fingerprint(self) -> str:
        """Bind reports to the exact declaration reviewed before execution."""

        return _fingerprint(self)


def _default_candidate_declaration() -> CandidateDeclaration:
    return CandidateDeclaration(
        candidate_id="two_stage_calendar_candidate_v1",
        model_name=PRODUCTION_MODEL_NAME,
        model_version=PRODUCTION_MODEL_VERSION,
        feature_contract_version=PRODUCTION_FEATURE_CONTRACT_VERSION,
        changed_component="two_stage_calendar_projection",
        change_summary=(
            "Current scoring rate combined with the frozen appearance, calendar, "
            "cold-start, and availability contracts."
        ),
        frozen_components=(
            "development_fold_set",
            "baseline_control",
            "ridge_reference",
            "optimization_contract",
            "promotion_gates",
        ),
        source_reference="docs/production_prediction_spec.md",
    )


def _default_benchmark_evaluation_config() -> EvaluationConfig:
    """Use deterministic CP-SAT work as the benchmark stopping rule.

    The wall-clock limit remains a generous safety cap. A benchmark run is rejected if
    that cap binds before the deterministic budget, because such a result depends on
    machine load and cannot support a reproducible comparison.
    """

    return EvaluationConfig(
        optimization_config=OptimizationConfig(
            solver_time_limit_seconds=DEFAULT_BENCHMARK_WALL_TIME_LIMIT_SECONDS,
            solver_deterministic_time_limit=DEFAULT_BENCHMARK_DETERMINISTIC_TIME_LIMIT,
        )
    )


@dataclass(frozen=True, slots=True)
class ProductionBenchmarkConfig:
    """Fixed inputs for one judging run."""

    seasons: tuple[str, ...] = DEFAULT_DEVELOPMENT_SEASONS
    min_prior_gameweeks_in_season: int = 1
    production_config: ProductionProjectionConfig = field(
        default_factory=ProductionProjectionConfig
    )
    ridge_config: RidgeProjectionConfig = field(default_factory=RidgeProjectionConfig)
    cross_season_config: CrossSeasonConfig = field(default_factory=CrossSeasonConfig)
    evaluation_config: EvaluationConfig = field(
        default_factory=_default_benchmark_evaluation_config
    )
    policy: PromotionPolicy = field(default_factory=PromotionPolicy)
    candidate_declaration: CandidateDeclaration = field(
        default_factory=_default_candidate_declaration
    )
    run_metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.seasons, tuple) or not self.seasons:
            raise BacktestConfigurationError("seasons must be a non-empty tuple.")
        if any(not isinstance(season, str) or not season.strip() for season in self.seasons):
            raise BacktestConfigurationError("seasons entries must be non-empty strings.")
        seasons = tuple(season.strip() for season in self.seasons)
        if len(set(seasons)) != len(seasons):
            raise BacktestConfigurationError("seasons entries must be unique.")
        for value, expected, name in (
            (self.production_config, ProductionProjectionConfig, "production_config"),
            (self.ridge_config, RidgeProjectionConfig, "ridge_config"),
            (self.cross_season_config, CrossSeasonConfig, "cross_season_config"),
            (self.evaluation_config, EvaluationConfig, "evaluation_config"),
            (self.policy, PromotionPolicy, "policy"),
        ):
            if not isinstance(value, expected):
                raise BacktestConfigurationError(f"{name} must be a {expected.__name__}.")
        if not isinstance(self.candidate_declaration, CandidateDeclaration):
            raise BacktestConfigurationError(
                "candidate_declaration must be a CandidateDeclaration."
            )
        frozen_metadata = EvaluationConfig(
            optimization_config=self.evaluation_config.optimization_config,
            scoring_policy=self.evaluation_config.scoring_policy,
            run_metadata=self.run_metadata,
        ).run_metadata
        object.__setattr__(self, "seasons", seasons)
        object.__setattr__(self, "run_metadata", frozen_metadata)

    @property
    def configuration_fingerprint(self) -> str:
        """Fingerprint every declared input that can change the gate response."""

        return _fingerprint(self)


@dataclass(frozen=True, slots=True)
class GateCondition:
    """One pre-registered condition, what it required, and what was measured."""

    name: str
    requirement: str
    measured: float
    passed: bool


@dataclass(frozen=True, slots=True)
class PairedComparison:
    """A candidate against a reference, on identical folds."""

    candidate: str
    reference: str
    comparable_folds: int
    mean_difference: float
    median_difference: float
    difference_stdev: float
    confidence_interval_lower: float
    confidence_interval_upper: float
    candidate_wins: int
    ties: int
    candidate_losses: int
    season_mean_differences: Mapping[str, float]


@dataclass(frozen=True, slots=True)
class ProductionBenchmarkResult:
    """Everything the judging run measured, and the verdict it implies."""

    config: ProductionBenchmarkConfig
    metadata: Mapping[str, object]
    fold_count: int
    feasible_folds: Mapping[str, int]
    solver_statuses: Mapping[str, Mapping[str, int]]
    mean_realized_points: Mapping[str, float]
    prediction_metrics: Mapping[str, PredictionMetrics]
    decision_metrics: Mapping[str, PairedDecisionMetrics]
    comparisons: tuple[PairedComparison, ...]
    gates: tuple[GateCondition, ...]
    verdict: str
    residuals: pd.DataFrame
    candidate_declaration: CandidateDeclaration = field(
        default_factory=_default_candidate_declaration
    )

    @property
    def all_gates_passed(self) -> bool:
        return all(gate.passed for gate in self.gates)

    @property
    def truncated_candidates(self) -> tuple[str, ...]:
        """Candidates with a fold whose primary objective was not proved optimal.

        Under the benchmark's deterministic-work stopping rule these incumbents are
        reproducible, but they still add solver-search noise to the realized-score
        comparison. That noise has unknown direction because realized points are not
        the objective CP-SAT maximizes.
        """

        return tuple(
            sorted(
                label
                for label, counts in self.solver_statuses.items()
                if any(status != "OPTIMAL" for status in counts)
            )
        )


def _season_of(fold_id: str) -> str:
    return str(fold_id).rsplit("-gw", 1)[0]


def _realized(result: EvaluationResult) -> dict[str, float]:
    return {
        str(fold.fold_id): float(fold.realized_squad_points)
        for fold in result.folds
        if fold.realized_squad_points is not None
    }


def _compare(
    candidate: EvaluationResult,
    reference: EvaluationResult,
    *,
    candidate_label: str,
    reference_label: str,
    policy: PromotionPolicy,
) -> PairedComparison:
    """Compare two candidates fold by fold, never mean by mean.

    Subtracting two averages answers a different question than pairing the folds does,
    and the gates are written on the paired one.
    """

    candidate_points = _realized(candidate)
    reference_points = _realized(reference)
    shared = sorted(set(candidate_points) & set(reference_points))
    if not shared:
        raise BacktestConfigurationError(
            f"{candidate_label} and {reference_label} share no scored folds, so no paired "
            "comparison is possible."
        )

    differences = [
        (_season_of(fold_id), candidate_points[fold_id] - reference_points[fold_id])
        for fold_id in shared
    ]
    values = [value for _, value in differences]
    lower, upper = season_aware_moving_block_interval(
        differences, policy=policy, candidate_id=f"{candidate_label}-vs-{reference_label}"
    )

    by_season: dict[str, list[float]] = {}
    for season, value in differences:
        by_season.setdefault(season, []).append(value)

    ordered = sorted(values)
    middle = len(ordered) // 2
    median = ordered[middle] if len(ordered) % 2 else (ordered[middle - 1] + ordered[middle]) / 2.0
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / (len(values) - 1)

    return PairedComparison(
        candidate=candidate_label,
        reference=reference_label,
        comparable_folds=len(values),
        mean_difference=mean,
        median_difference=median,
        difference_stdev=variance**0.5,
        confidence_interval_lower=lower,
        confidence_interval_upper=upper,
        candidate_wins=sum(1 for value in values if value > 0.0),
        ties=sum(1 for value in values if value == 0.0),
        candidate_losses=sum(1 for value in values if value < 0.0),
        season_mean_differences={
            season: sum(entries) / len(entries) for season, entries in sorted(by_season.items())
        },
    )


def _relative_change(candidate: float, reference: float) -> float:
    """Fractional change from reference to candidate; positive means worse."""

    if reference == 0.0:
        return 0.0 if candidate == 0.0 else float("inf")
    return (candidate - reference) / abs(reference)


def _evaluate_gates(
    against_baseline: PairedComparison,
    against_ridge: PairedComparison,
    production: PredictionMetrics,
    ridge: PredictionMetrics,
    *,
    policy: PromotionPolicy,
    feasible: Mapping[str, int],
    fold_count: int,
) -> tuple[GateCondition, ...]:
    """Evaluate every pre-registered condition, reporting each separately.

    Reported one by one rather than as a single verdict because a candidate that fails
    on one condition and a candidate that fails on four are different situations, and a
    boolean hides which.
    """

    mae_change = _relative_change(production.mean_absolute_error, ridge.mean_absolute_error)
    rmse_change = _relative_change(
        production.root_mean_squared_error, ridge.root_mean_squared_error
    )
    improved_either = mae_change < 0.0 or rmse_change < 0.0
    worse_of_the_two = max(mae_change, rmse_change)

    return (
        GateCondition(
            name="baseline_mean_improvement",
            requirement=f">= {policy.min_mean_improvement:+.4f}",
            measured=against_baseline.mean_difference,
            passed=against_baseline.mean_difference >= policy.min_mean_improvement,
        ),
        GateCondition(
            name="baseline_lower_bound",
            requirement=">= +0.0000",
            measured=against_baseline.confidence_interval_lower,
            passed=against_baseline.confidence_interval_lower >= 0.0,
        ),
        GateCondition(
            name="ridge_mean_difference",
            requirement=">= +0.0000",
            measured=against_ridge.mean_difference,
            passed=against_ridge.mean_difference >= 0.0,
        ),
        GateCondition(
            name="ridge_lower_bound",
            requirement=f">= {RIDGE_LOWER_BOUND_TOLERANCE:+.4f}",
            measured=against_ridge.confidence_interval_lower,
            passed=against_ridge.confidence_interval_lower >= RIDGE_LOWER_BOUND_TOLERANCE,
        ),
        GateCondition(
            name="prediction_metric_improved_against_ridge",
            requirement="MAE or RMSE improves",
            measured=min(mae_change, rmse_change),
            passed=improved_either,
        ),
        GateCondition(
            name="other_prediction_metric_tolerance",
            requirement=f"<= {PREDICTION_METRIC_TOLERANCE:+.4f} relative degradation",
            measured=worse_of_the_two,
            passed=worse_of_the_two <= PREDICTION_METRIC_TOLERANCE,
        ),
        GateCondition(
            name="every_fold_feasible",
            requirement=f"= {fold_count} folds",
            measured=float(min(feasible.values())),
            passed=all(count == fold_count for count in feasible.values()),
        ),
    )


def _feasible_folds(result: EvaluationResult) -> int:
    return sum(1 for fold in result.folds if fold.realized_squad_points is not None)


def _solver_statuses(result: EvaluationResult) -> Mapping[str, int]:
    """Count how each candidate's folds terminated.

    A non-optimal fold returns the incumbent selected after the declared deterministic
    amount of CP-SAT work. That incumbent is reproducible, but it is still a property of
    search as well as projection, so hiding it would credit or blame the wrong layer.
    """

    counts: dict[str, int] = {}
    for fold in result.folds:
        status = str(getattr(fold.optimization_result, "solver_status", "unknown"))
        counts[status] = counts.get(status, 0) + 1
    return counts


def _non_deterministic_truncations(result: EvaluationResult) -> tuple[str, ...]:
    """Return folds where the wall cap bound before deterministic work was exhausted."""

    violations: list[str] = []
    for fold in result.folds:
        optimization = fold.optimization_result
        tiebreak_incomplete = (
            optimization.diagnostics.get("tiebreak_attempted") is True
            and optimization.diagnostics.get("tiebreak_completed") is not True
        )
        primary_incomplete = optimization.solver_status in {
            SolverStatus.FEASIBLE,
            SolverStatus.UNKNOWN,
        }
        if (primary_incomplete or tiebreak_incomplete) and (
            optimization.diagnostics.get("deterministic_time_budget_exhausted") is not True
        ):
            violations.append(fold.fold_id)
    return tuple(violations)


def _prepare(
    panel: pd.DataFrame,
    builder: ProjectionBuilder,
    settings: ProductionBenchmarkConfig,
) -> tuple[tuple[EvaluationFold, ...], EvaluationResult]:
    folds = build_walk_forward_folds(
        panel,
        seasons=settings.seasons,
        min_prior_gameweeks_in_season=settings.min_prior_gameweeks_in_season,
        projection_builder=builder,
    )
    return folds, evaluate_prepared_folds(folds, settings.evaluation_config)


def _validate_candidate_provenance(
    folds: Sequence[EvaluationFold], declaration: CandidateDeclaration
) -> None:
    """Reject a builder whose snapshots do not match the pre-run declaration."""

    expected = {
        "prediction_model_name": declaration.model_name,
        "prediction_model_version": declaration.model_version,
        "prediction_feature_contract_version": declaration.feature_contract_version,
    }
    for fold in folds:
        missing = [name for name in expected if name not in fold.metadata]
        if missing:
            raise BacktestConfigurationError(
                "A declared candidate must return PredictionSnapshot values with model "
                f"provenance; {fold.fold_id} is missing {missing!r}."
            )
        mismatches = {
            name: {"declared": expected_value, "observed": fold.metadata[name]}
            for name, expected_value in expected.items()
            if fold.metadata[name] != expected_value
        }
        if mismatches:
            raise BacktestConfigurationError(
                f"Candidate provenance does not match its declaration in {fold.fold_id}: "
                f"{mismatches!r}."
            )


def run_declared_candidate_benchmark(
    panel: pd.DataFrame,
    candidate_builder: ProjectionBuilder,
    config: ProductionBenchmarkConfig,
) -> ProductionBenchmarkResult:
    """Judge one pre-declared candidate against the frozen control and Ridge reference.

    The challenger occupies the historical ``production`` report slot for backward
    compatibility. Its real identity is carried by ``candidate_declaration`` and checked
    against every prediction snapshot before any gate evidence is returned.
    """

    if not isinstance(config, ProductionBenchmarkConfig):
        raise BacktestConfigurationError("config must be a ProductionBenchmarkConfig.")
    if not callable(candidate_builder):
        raise BacktestConfigurationError("candidate_builder must be callable.")

    builders: Mapping[str, ProjectionBuilder] = {
        BASELINE_LABEL: make_baseline_projection_builder(
            form_window=config.ridge_config.form_window,
            cross_season=config.cross_season_config,
        ),
        RIDGE_LABEL: make_ridge_projection_builder(
            config=config.ridge_config,
            cross_season=config.cross_season_config,
        ),
        PRODUCTION_LABEL: candidate_builder,
    }

    prepared: dict[str, tuple[tuple[EvaluationFold, ...], EvaluationResult]] = {
        label: _prepare(panel, builder, config) for label, builder in builders.items()
    }
    _validate_candidate_provenance(prepared[PRODUCTION_LABEL][0], config.candidate_declaration)
    return _judge_prepared_candidates(prepared, config)


def _judge_prepared_candidates(
    prepared: Mapping[str, tuple[tuple[EvaluationFold, ...], EvaluationResult]],
    settings: ProductionBenchmarkConfig,
) -> ProductionBenchmarkResult:
    """Evaluate already-prepared control, reference, and challenger results."""

    results = {label: result for label, (_, result) in prepared.items()}
    wall_limited = {
        label: _non_deterministic_truncations(result) for label, result in results.items()
    }
    invalid = {label: folds for label, folds in wall_limited.items() if folds}
    if invalid:
        examples = {label: folds[:5] for label, folds in invalid.items()}
        raise BacktestConfigurationError(
            "The wall-clock safety cap bound before the deterministic solver budget; "
            f"affected fold examples: {examples!r}. Increase only the safety cap, not the "
            "deterministic comparison budget."
        )
    residuals = {label: build_residual_history(folds) for label, (folds, _) in prepared.items()}
    metrics = {label: prediction_metrics(frame) for label, frame in residuals.items()}

    against_baseline = _compare(
        results[PRODUCTION_LABEL],
        results[BASELINE_LABEL],
        candidate_label=PRODUCTION_LABEL,
        reference_label=BASELINE_LABEL,
        policy=settings.policy,
    )
    against_ridge = _compare(
        results[PRODUCTION_LABEL],
        results[RIDGE_LABEL],
        candidate_label=PRODUCTION_LABEL,
        reference_label=RIDGE_LABEL,
        policy=settings.policy,
    )
    ridge_against_baseline = _compare(
        results[RIDGE_LABEL],
        results[BASELINE_LABEL],
        candidate_label=RIDGE_LABEL,
        reference_label=BASELINE_LABEL,
        policy=settings.policy,
    )

    feasible = {label: _feasible_folds(result) for label, result in results.items()}
    fold_count = against_baseline.comparable_folds
    gates = _evaluate_gates(
        against_baseline,
        against_ridge,
        metrics[PRODUCTION_LABEL],
        metrics[RIDGE_LABEL],
        policy=settings.policy,
        feasible=feasible,
        fold_count=fold_count,
    )

    return ProductionBenchmarkResult(
        config=settings,
        metadata={
            **dict(settings.run_metadata),
            "benchmark_contract_version": PRODUCTION_BENCHMARK_CONTRACT_VERSION,
            "benchmark_configuration_fingerprint": settings.configuration_fingerprint,
            "candidate_declaration_fingerprint": (
                settings.candidate_declaration.declaration_fingerprint
            ),
            "evaluation_seasons": settings.seasons,
            "holdout_untouched": True,
        },
        fold_count=fold_count,
        feasible_folds=feasible,
        solver_statuses={label: _solver_statuses(result) for label, result in results.items()},
        mean_realized_points={
            label: sum(_realized(result).values()) / max(len(_realized(result)), 1)
            for label, result in results.items()
        },
        prediction_metrics=metrics,
        decision_metrics={
            BASELINE_LABEL: paired_decision_metrics(
                results[BASELINE_LABEL], results[PRODUCTION_LABEL]
            ),
            RIDGE_LABEL: paired_decision_metrics(results[RIDGE_LABEL], results[PRODUCTION_LABEL]),
        },
        comparisons=(against_baseline, against_ridge, ridge_against_baseline),
        gates=gates,
        verdict=(
            VERDICT_PROMOTABLE if all(gate.passed for gate in gates) else VERDICT_RETAIN_CONTROL
        ),
        residuals=residuals[PRODUCTION_LABEL],
        candidate_declaration=settings.candidate_declaration,
    )


def run_production_benchmark(
    panel: pd.DataFrame,
    fixtures: pd.DataFrame,
    team_codes: pd.DataFrame,
    config: ProductionBenchmarkConfig | None = None,
) -> ProductionBenchmarkResult:
    """Run the current production candidate over the frozen development gate."""

    settings = ProductionBenchmarkConfig() if config is None else config
    if not isinstance(settings, ProductionBenchmarkConfig):
        raise BacktestConfigurationError("config must be a ProductionBenchmarkConfig.")
    candidate_builder = make_production_projection_builder(
        fixtures=fixtures,
        team_codes=team_codes,
        config=settings.production_config,
        cross_season=settings.cross_season_config,
    )
    return run_declared_candidate_benchmark(panel, candidate_builder, settings)


def candidate_labels() -> Sequence[str]:
    """The three candidates a judging run compares, in report order."""

    return (BASELINE_LABEL, RIDGE_LABEL, PRODUCTION_LABEL)
