"""Public contracts for deterministic Bayesian policy search."""

import hashlib
import json
import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum
from itertools import product
from numbers import Integral, Real
from types import MappingProxyType
from typing import Final

BAYESIAN_OPTIMIZATION_CONTRACT_VERSION: Final = "deterministic_policy_bo_v1"


class BayesianOptimizationError(Exception):
    """Base exception for Bayesian policy search."""


class BayesianOptimizationConfigurationError(BayesianOptimizationError):
    """Raised when the search contract is inconsistent."""


class BayesianOptimizationExecutionError(BayesianOptimizationError):
    """Raised when an objective evaluation or surrogate fit is invalid."""


class FactorKind(StrEnum):
    """Supported finite-grid factor representations."""

    INTEGER = "integer"
    CONTINUOUS = "continuous"


def _finite(value: object, name: str, minimum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise BayesianOptimizationConfigurationError(f"{name} must be a finite number.")
    normalized = float(value)
    if not math.isfinite(normalized) or normalized < minimum:
        raise BayesianOptimizationConfigurationError(f"{name} must be at least {minimum}.")
    return normalized


def _integer(value: object, name: str, minimum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, Integral):
        raise BayesianOptimizationConfigurationError(f"{name} must be an integer.")
    normalized = int(value)
    if normalized < minimum:
        raise BayesianOptimizationConfigurationError(f"{name} must be at least {minimum}.")
    return normalized


def _decimal_token(value: int | float) -> str:
    if isinstance(value, Integral) and not isinstance(value, bool):
        return str(int(value))
    return format(Decimal(str(float(value))).normalize(), "f")


@dataclass(frozen=True, slots=True)
class BayesianFactor:
    """One bounded factor represented by an exact finite quantization grid.

    ``lower_bound == upper_bound`` declares a *fixed* factor: a single level that is
    carried through the search unchanged. This is how a factor a contract requires but
    an evaluator cannot vary — ``risk_aversion`` under a deterministic projection — is
    pinned instead of silently ignored.
    """

    name: str
    lower_bound: int | float
    upper_bound: int | float
    step: int | float
    kind: FactorKind = FactorKind.CONTINUOUS

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise BayesianOptimizationConfigurationError("Factor name must be a non-empty string.")
        normalized_name = self.name.strip()
        if not normalized_name.replace("_", "").isalnum():
            raise BayesianOptimizationConfigurationError(
                "Factor name may contain only letters, digits, and underscores."
            )
        if not isinstance(self.kind, FactorKind):
            try:
                kind = FactorKind(self.kind)
            except (TypeError, ValueError) as error:
                raise BayesianOptimizationConfigurationError("Unsupported factor kind.") from error
        else:
            kind = self.kind

        lower: int | float
        upper: int | float
        step: int | float
        if kind is FactorKind.INTEGER:
            lower = _integer(self.lower_bound, f"{normalized_name}.lower_bound", 0)
            upper = _integer(self.upper_bound, f"{normalized_name}.upper_bound", 0)
            step = _integer(self.step, f"{normalized_name}.step", 1)
            if lower > upper:
                raise BayesianOptimizationConfigurationError(
                    f"{normalized_name} lower_bound must not exceed upper_bound."
                )
            if (upper - lower) % step != 0:
                raise BayesianOptimizationConfigurationError(
                    f"{normalized_name} step must land exactly on upper_bound."
                )
        else:
            for value, label in (
                (self.lower_bound, "lower_bound"),
                (self.upper_bound, "upper_bound"),
                (self.step, "step"),
            ):
                if isinstance(value, bool) or not isinstance(value, Real):
                    raise BayesianOptimizationConfigurationError(
                        f"{normalized_name}.{label} must be a finite number."
                    )
                if not math.isfinite(float(value)):
                    raise BayesianOptimizationConfigurationError(
                        f"{normalized_name}.{label} must be a finite number."
                    )
            lower_decimal = Decimal(str(self.lower_bound))
            upper_decimal = Decimal(str(self.upper_bound))
            step_decimal = Decimal(str(self.step))
            if lower_decimal > upper_decimal or step_decimal <= 0:
                raise BayesianOptimizationConfigurationError(
                    f"{normalized_name} requires lower_bound <= upper_bound and step > 0."
                )
            quotient = (upper_decimal - lower_decimal) / step_decimal
            if quotient != quotient.to_integral_value():
                raise BayesianOptimizationConfigurationError(
                    f"{normalized_name} step must land exactly on upper_bound."
                )
            lower = float(lower_decimal)
            upper = float(upper_decimal)
            step = float(step_decimal)

        object.__setattr__(self, "name", normalized_name)
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "lower_bound", lower)
        object.__setattr__(self, "upper_bound", upper)
        object.__setattr__(self, "step", step)

    @property
    def is_fixed(self) -> bool:
        """True when the factor has one level and is pinned rather than searched.

        A fixed factor keeps a contract's factor set intact while removing the axis
        from the search: the value still appears in every candidate and every trace, so
        a report cannot attribute an effect to a factor that never moved.
        """

        return self.lower_bound == self.upper_bound

    @property
    def levels(self) -> tuple[int | float, ...]:
        """Return every exact candidate level in deterministic order."""

        if self.kind is FactorKind.INTEGER:
            return tuple(
                range(
                    int(self.lower_bound),
                    int(self.upper_bound) + 1,
                    int(self.step),
                )
            )
        lower = Decimal(str(self.lower_bound))
        step = Decimal(str(self.step))
        count = int((Decimal(str(self.upper_bound)) - lower) / step)
        return tuple(float(lower + step * index) for index in range(count + 1))


def _default_factors() -> tuple[BayesianFactor, ...]:
    return (
        BayesianFactor("form_window", 3, 10, 1, FactorKind.INTEGER),
        BayesianFactor("bench_weight", 0.0, 0.30, 0.05),
        BayesianFactor("risk_aversion", 0.0, 1.0, 0.10),
    )


@dataclass(frozen=True, slots=True)
class BayesianOptimizationConfig:
    """Frozen search space, surrogate, acquisition, and budget controls."""

    factors: tuple[BayesianFactor, ...] = field(default_factory=_default_factors)
    evaluation_budget: int = 30
    initial_design_size: int = 8
    deterministic_seed: int = 0
    exploration_xi: float = 0.01
    min_expected_improvement: float = 0.0
    kernel_length_scale: float = 1.0
    matern_nu: float = 2.5
    observation_noise: float = 1.0e-6
    contract_version: str = BAYESIAN_OPTIMIZATION_CONTRACT_VERSION

    def __post_init__(self) -> None:
        if self.contract_version != BAYESIAN_OPTIMIZATION_CONTRACT_VERSION:
            raise BayesianOptimizationConfigurationError(
                "contract_version does not match the implemented Bayesian optimizer."
            )
        if not isinstance(self.factors, tuple) or not self.factors:
            raise BayesianOptimizationConfigurationError("factors must be a non-empty tuple.")
        if any(not isinstance(factor, BayesianFactor) for factor in self.factors):
            raise BayesianOptimizationConfigurationError(
                "Every factors entry must be a BayesianFactor."
            )
        names = tuple(factor.name for factor in self.factors)
        if len(set(names)) != len(names):
            raise BayesianOptimizationConfigurationError("Factor names must be unique.")
        search_size = math.prod(len(factor.levels) for factor in self.factors)
        budget = _integer(self.evaluation_budget, "evaluation_budget", 1)
        initial_size = _integer(self.initial_design_size, "initial_design_size", 1)
        seed = _integer(self.deterministic_seed, "deterministic_seed", 0)
        if budget > search_size:
            raise BayesianOptimizationConfigurationError(
                "evaluation_budget may not exceed the finite search-space size."
            )
        if initial_size > budget:
            raise BayesianOptimizationConfigurationError(
                "initial_design_size may not exceed evaluation_budget."
            )
        xi = _finite(self.exploration_xi, "exploration_xi", 0.0)
        minimum_ei = _finite(
            self.min_expected_improvement,
            "min_expected_improvement",
            0.0,
        )
        length_scale = _finite(self.kernel_length_scale, "kernel_length_scale", 1.0e-12)
        noise = _finite(self.observation_noise, "observation_noise", 1.0e-15)
        nu = _finite(self.matern_nu, "matern_nu", 1.0e-12)
        if nu not in {0.5, 1.5, 2.5}:
            raise BayesianOptimizationConfigurationError("matern_nu must be 0.5, 1.5, or 2.5.")
        object.__setattr__(self, "evaluation_budget", budget)
        object.__setattr__(self, "initial_design_size", initial_size)
        object.__setattr__(self, "deterministic_seed", seed)
        object.__setattr__(self, "exploration_xi", xi)
        object.__setattr__(self, "min_expected_improvement", minimum_ei)
        object.__setattr__(self, "kernel_length_scale", length_scale)
        object.__setattr__(self, "matern_nu", nu)
        object.__setattr__(self, "observation_noise", noise)

    @property
    def search_space_size(self) -> int:
        """Return the finite number of canonical candidates."""

        return math.prod(len(factor.levels) for factor in self.factors)

    @property
    def configuration_fingerprint(self) -> str:
        """Return a stable digest of every search-affecting control."""

        payload = {
            "contract_version": self.contract_version,
            "factors": [
                {
                    "name": factor.name,
                    "kind": factor.kind.value,
                    "levels": [_decimal_token(value) for value in factor.levels],
                }
                for factor in self.factors
            ],
            "evaluation_budget": self.evaluation_budget,
            "initial_design_size": self.initial_design_size,
            "deterministic_seed": self.deterministic_seed,
            "exploration_xi": float(self.exploration_xi).hex(),
            "min_expected_improvement": float(self.min_expected_improvement).hex(),
            "kernel_length_scale": float(self.kernel_length_scale).hex(),
            "matern_nu": float(self.matern_nu).hex(),
            "observation_noise": float(self.observation_noise).hex(),
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class BayesianCandidate:
    """One canonical factor vector."""

    values: Mapping[str, int | float]

    def __post_init__(self) -> None:
        if not isinstance(self.values, Mapping) or not self.values:
            raise BayesianOptimizationExecutionError(
                "Candidate values must be a non-empty mapping."
            )
        normalized: dict[str, int | float] = {}
        for name, value in self.values.items():
            if not isinstance(name, str) or not name:
                raise BayesianOptimizationExecutionError(
                    "Candidate factor names must be non-empty strings."
                )
            if (
                isinstance(value, bool)
                or not isinstance(value, Real)
                or not math.isfinite(float(value))
            ):
                raise BayesianOptimizationExecutionError(
                    "Candidate values must be finite integer or float values."
                )
            normalized[name] = int(value) if isinstance(value, Integral) else float(value)
        object.__setattr__(self, "values", MappingProxyType(normalized))

    @property
    def candidate_id(self) -> str:
        """Return a stable readable identifier for caching and tie-breaking."""

        return "-".join(
            f"{name}={_decimal_token(value)}" for name, value in sorted(self.values.items())
        )


def enumerate_candidates(config: BayesianOptimizationConfig) -> tuple[BayesianCandidate, ...]:
    """Enumerate the complete canonical search space in factor order."""

    return tuple(
        BayesianCandidate(
            dict(zip((factor.name for factor in config.factors), levels, strict=True))
        )
        for levels in product(*(factor.levels for factor in config.factors))
    )


@dataclass(frozen=True, slots=True)
class BayesianEvaluation:
    """One objective call and the acquisition state that selected it."""

    iteration: int
    phase: str
    candidate: BayesianCandidate
    objective_value: float
    predicted_mean: float | None
    predicted_standard_deviation: float | None
    expected_improvement: float | None

    def __post_init__(self) -> None:
        if self.iteration < 0:
            raise BayesianOptimizationExecutionError("Evaluation iteration must be non-negative.")
        if self.phase not in {"initial_design", "expected_improvement"}:
            raise BayesianOptimizationExecutionError("Evaluation phase is unsupported.")
        if not isinstance(self.candidate, BayesianCandidate):
            raise BayesianOptimizationExecutionError(
                "Evaluation candidate must be a BayesianCandidate."
            )
        if not math.isfinite(self.objective_value):
            raise BayesianOptimizationExecutionError("Evaluation objective_value must be finite.")
        optional_values = (
            self.predicted_mean,
            self.predicted_standard_deviation,
            self.expected_improvement,
        )
        if any(value is not None and not math.isfinite(value) for value in optional_values):
            raise BayesianOptimizationExecutionError(
                "Evaluation surrogate and acquisition values must be finite when present."
            )
        if (
            self.predicted_standard_deviation is not None
            and self.predicted_standard_deviation < 0.0
        ):
            raise BayesianOptimizationExecutionError(
                "predicted_standard_deviation must be non-negative."
            )
        if self.expected_improvement is not None and self.expected_improvement < 0.0:
            raise BayesianOptimizationExecutionError("expected_improvement must be non-negative.")
        if self.phase == "initial_design" and any(value is not None for value in optional_values):
            raise BayesianOptimizationExecutionError(
                "Initial-design evaluations may not claim surrogate acquisition values."
            )
        if self.phase == "expected_improvement" and any(value is None for value in optional_values):
            raise BayesianOptimizationExecutionError(
                "Expected-improvement evaluations must carry surrogate acquisition values."
            )


@dataclass(frozen=True, slots=True)
class BayesianOptimizationResult:
    """Complete development-only Bayesian search trace and recommendation."""

    config: BayesianOptimizationConfig
    development_fold_ids: tuple[str, ...]
    locked_holdout_fold_ids: tuple[str, ...]
    evaluations: tuple[BayesianEvaluation, ...]
    recommended_candidate: BayesianCandidate
    best_objective_value: float
    stopped_reason: str
    run_fingerprint: str
    diagnostics: Mapping[str, object]

    def __post_init__(self) -> None:
        if not isinstance(self.config, BayesianOptimizationConfig):
            raise BayesianOptimizationExecutionError("config must be a BayesianOptimizationConfig.")
        if not self.evaluations:
            raise BayesianOptimizationExecutionError("Result must contain at least one evaluation.")
        if len(self.evaluations) > self.config.evaluation_budget:
            raise BayesianOptimizationExecutionError(
                "Evaluation trace may not exceed the configured budget."
            )
        if tuple(item.iteration for item in self.evaluations) != tuple(
            range(len(self.evaluations))
        ):
            raise BayesianOptimizationExecutionError(
                "Evaluation iterations must be consecutive and zero-based."
            )
        candidate_ids = tuple(item.candidate.candidate_id for item in self.evaluations)
        if len(set(candidate_ids)) != len(candidate_ids):
            raise BayesianOptimizationExecutionError(
                "Evaluation trace may not contain duplicate candidates."
            )
        if not self.development_fold_ids or len(set(self.development_fold_ids)) != len(
            self.development_fold_ids
        ):
            raise BayesianOptimizationExecutionError(
                "development_fold_ids must be non-empty and unique."
            )
        if len(set(self.locked_holdout_fold_ids)) != len(self.locked_holdout_fold_ids):
            raise BayesianOptimizationExecutionError("locked_holdout_fold_ids must be unique.")
        if set(self.development_fold_ids) & set(self.locked_holdout_fold_ids):
            raise BayesianOptimizationExecutionError(
                "Development and locked holdout folds must be disjoint."
            )
        if self.recommended_candidate.candidate_id not in {
            item.candidate.candidate_id for item in self.evaluations
        }:
            raise BayesianOptimizationExecutionError(
                "recommended_candidate must be present in evaluations."
            )
        if not math.isfinite(self.best_objective_value):
            raise BayesianOptimizationExecutionError("best_objective_value must be finite.")
        expected = min(
            self.evaluations,
            key=lambda item: (-item.objective_value, item.candidate.candidate_id),
        )
        if (
            self.recommended_candidate.candidate_id != expected.candidate.candidate_id
            or not math.isclose(
                self.best_objective_value,
                expected.objective_value,
                rel_tol=0.0,
                abs_tol=0.0,
            )
        ):
            raise BayesianOptimizationExecutionError(
                "Recommendation and best_objective_value must match the best observed trace item."
            )
        if (
            not isinstance(self.run_fingerprint, str)
            or len(self.run_fingerprint) != 64
            or any(character not in "0123456789abcdef" for character in self.run_fingerprint)
        ):
            raise BayesianOptimizationExecutionError(
                "run_fingerprint must be a lowercase SHA-256 digest."
            )
        object.__setattr__(self, "diagnostics", MappingProxyType(dict(self.diagnostics)))
