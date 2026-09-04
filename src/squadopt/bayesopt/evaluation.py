"""Typed seam between Bayesian policy candidates and the development-fold objective.

`run_bayesian_optimization` deliberately accepts only a narrow callback, so the search
stays independent of prediction and backtest implementation. This module gives that
callback a typed shape: what a policy candidate means as prediction-side factors, what
one development-fold evaluation must report back, and how the two are bound together.

The prediction-side builder that satisfies :class:`DevelopmentFoldPolicyEvaluator` is
owned by the data/prediction side. This module only fixes the seam, so both sides can
implement against the same contract instead of a prose description.
"""

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from numbers import Integral, Real
from types import MappingProxyType
from typing import Final, Protocol

from squadopt.bayesopt.models import (
    BayesianCandidate,
    BayesianOptimizationConfigurationError,
    BayesianOptimizationExecutionError,
)

POLICY_EVALUATION_CONTRACT_VERSION: Final = "deterministic_policy_evaluation_v1"
EVALUATION_OBJECTIVE_VERSION: Final = "single_gameweek_realized_squad_points_v1"
POLICY_FACTOR_NAMES: Final = ("form_window", "bench_weight", "risk_aversion")


@dataclass(frozen=True, slots=True)
class DeterministicPolicyFactors:
    """One candidate expressed in the operational policy's own vocabulary.

    ``form_window`` is passed through unchanged: the prediction side must apply the
    frozen ``form_window_v1`` mapping (window -> minutes/points/per-90 feature windows)
    and may not reinterpret it. ``bench_weight`` and ``risk_aversion`` address the
    optimizer objective and are consumed by the decision side.
    """

    form_window: int
    bench_weight: float
    risk_aversion: float

    def __post_init__(self) -> None:
        window = self.form_window
        if isinstance(window, bool) or not isinstance(window, Integral) or int(window) < 1:
            raise BayesianOptimizationConfigurationError("form_window must be a positive integer.")
        object.__setattr__(self, "form_window", int(window))
        for name, upper_bound in (("bench_weight", 1.0), ("risk_aversion", None)):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, Real):
                raise BayesianOptimizationConfigurationError(f"{name} must be a finite number.")
            number = float(value)
            if not math.isfinite(number) or number < 0.0:
                raise BayesianOptimizationConfigurationError(
                    f"{name} must be finite and non-negative."
                )
            if upper_bound is not None and number > upper_bound:
                raise BayesianOptimizationConfigurationError(
                    f"{name} must not exceed {upper_bound}."
                )
            object.__setattr__(self, name, number)


def policy_factors_from_candidate(candidate: BayesianCandidate) -> DeterministicPolicyFactors:
    """Map one canonical candidate onto the typed policy factors, strictly.

    A candidate that misses a policy factor or carries an unknown one is refused
    instead of being partially applied: silently ignoring a factor would make the
    search trace claim an influence the evaluation never had.
    """

    if not isinstance(candidate, BayesianCandidate):
        raise BayesianOptimizationExecutionError("candidate must be a BayesianCandidate.")
    names = set(candidate.values)
    missing = sorted(set(POLICY_FACTOR_NAMES) - names)
    unexpected = sorted(names - set(POLICY_FACTOR_NAMES))
    if missing or unexpected:
        raise BayesianOptimizationExecutionError(
            f"Candidate factors do not match the policy contract: missing {missing!r}, "
            f"unexpected {unexpected!r}."
        )
    window_value = candidate.values["form_window"]
    if isinstance(window_value, float):
        if not window_value.is_integer():
            raise BayesianOptimizationExecutionError(
                "form_window must be an integer-valued factor."
            )
        window_value = int(window_value)
    return DeterministicPolicyFactors(
        form_window=int(window_value),
        bench_weight=float(candidate.values["bench_weight"]),
        risk_aversion=float(candidate.values["risk_aversion"]),
    )


@dataclass(frozen=True, slots=True)
class DevelopmentFoldEvaluation:
    """What one chronological development-fold run must report back to the search.

    ``objective_value`` is the scalar decision objective (mean realized squad points
    per gameweek across the evaluated folds under the named objective version).
    ``evaluated_fold_ids`` names the folds that actually produced it, so the binding
    can prove the run covered exactly the requested development population.
    """

    objective_value: float
    evaluated_fold_ids: tuple[str, ...]
    objective_version: str = EVALUATION_OBJECTIVE_VERSION
    provenance: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        value = self.objective_value
        if (
            isinstance(value, bool)
            or not isinstance(value, Real)
            or not math.isfinite(float(value))
        ):
            raise BayesianOptimizationConfigurationError("objective_value must be finite.")
        object.__setattr__(self, "objective_value", float(value))
        folds = self.evaluated_fold_ids
        if (
            not isinstance(folds, tuple)
            or not folds
            or any(not isinstance(fold, str) or not fold.strip() for fold in folds)
        ):
            raise BayesianOptimizationConfigurationError(
                "evaluated_fold_ids must be a non-empty tuple of non-empty strings."
            )
        normalized = tuple(fold.strip() for fold in folds)
        if len(set(normalized)) != len(normalized):
            raise BayesianOptimizationConfigurationError("evaluated_fold_ids must be unique.")
        object.__setattr__(self, "evaluated_fold_ids", normalized)
        if not isinstance(self.objective_version, str) or not self.objective_version.strip():
            raise BayesianOptimizationConfigurationError(
                "objective_version must be non-empty text."
            )
        object.__setattr__(self, "objective_version", self.objective_version.strip())
        object.__setattr__(self, "provenance", MappingProxyType(dict(self.provenance)))


class DevelopmentFoldPolicyEvaluator(Protocol):
    """The prediction-side builder the search binds to.

    One call runs the full chronological development-fold evaluation for one policy
    configuration and reports the scalar objective with its provenance. The
    implementation must be deterministic for identical inputs and must never read
    locked-holdout folds; the binding verifies fold coverage on every call.
    """

    def __call__(
        self,
        factors: DeterministicPolicyFactors,
        development_fold_ids: tuple[str, ...],
    ) -> DevelopmentFoldEvaluation: ...


class BoundPolicyEvaluator:
    """Adapt a typed development-fold evaluator to the narrow search callback.

    The instance is the ``evaluator`` argument for ``run_bayesian_optimization``. It
    keeps every typed evaluation it forwarded, keyed by candidate ID, so a finished
    search can attach per-candidate provenance that the scalar-only callback would
    otherwise discard.
    """

    def __init__(
        self,
        evaluator: DevelopmentFoldPolicyEvaluator,
        *,
        objective_version: str = EVALUATION_OBJECTIVE_VERSION,
    ) -> None:
        if not callable(evaluator):
            raise BayesianOptimizationConfigurationError("evaluator must be callable.")
        if not isinstance(objective_version, str) or not objective_version.strip():
            raise BayesianOptimizationConfigurationError(
                "objective_version must be non-empty text."
            )
        self._evaluator = evaluator
        self._objective_version = objective_version.strip()
        self._records: dict[str, DevelopmentFoldEvaluation] = {}

    def __call__(
        self,
        candidate: BayesianCandidate,
        development_fold_ids: tuple[str, ...],
    ) -> float:
        factors = policy_factors_from_candidate(candidate)
        evaluation = self._evaluator(factors, development_fold_ids)
        if not isinstance(evaluation, DevelopmentFoldEvaluation):
            raise BayesianOptimizationExecutionError(
                "The policy evaluator must return a DevelopmentFoldEvaluation."
            )
        if set(evaluation.evaluated_fold_ids) != set(development_fold_ids):
            missing = sorted(set(development_fold_ids) - set(evaluation.evaluated_fold_ids))
            extra = sorted(set(evaluation.evaluated_fold_ids) - set(development_fold_ids))
            raise BayesianOptimizationExecutionError(
                "Evaluated folds do not cover the requested development folds exactly: "
                f"missing {missing!r}, extra {extra!r}."
            )
        if evaluation.objective_version != self._objective_version:
            raise BayesianOptimizationExecutionError(
                f"Evaluation reports objective {evaluation.objective_version!r}; the search "
                f"was bound to {self._objective_version!r}."
            )
        self._records[candidate.candidate_id] = evaluation
        return evaluation.objective_value

    @property
    def objective_version(self) -> str:
        """Return the objective version every forwarded evaluation must report."""

        return self._objective_version

    @property
    def records(self) -> Mapping[str, DevelopmentFoldEvaluation]:
        """Return every forwarded evaluation keyed by stable candidate ID."""

        return MappingProxyType(dict(self._records))


def bind_policy_evaluator(
    evaluator: DevelopmentFoldPolicyEvaluator,
    *,
    objective_version: str = EVALUATION_OBJECTIVE_VERSION,
) -> BoundPolicyEvaluator:
    """Return the search-facing callback for one typed policy evaluator."""

    return BoundPolicyEvaluator(evaluator, objective_version=objective_version)
