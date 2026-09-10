"""Bounded-knob vocabulary shared by the product's strategy catalogue and the laboratory.

A strategy declares its tunable knobs as :class:`BayesianFactor` grids; design of experiments
and Bayesian policy search read those grids directly. The vocabulary is pure: exact
finite-grid arithmetic and validation, no decision, no import of any other ``squadopt``
package. The two exception classes keep their historical names and inheritance so callers
catching the ``squadopt.bayesopt`` imports keep working (same treatment as
``ExperimentError`` in ``evaluation.promotion``).
"""

import math
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from numbers import Integral, Real

__all__ = [
    "BayesianFactor",
    "BayesianOptimizationConfigurationError",
    "BayesianOptimizationError",
    "FactorKind",
]


class BayesianOptimizationError(Exception):
    """Base exception for Bayesian policy search."""


class BayesianOptimizationConfigurationError(BayesianOptimizationError):
    """Raised when the search contract is inconsistent."""


class FactorKind(StrEnum):
    """Supported finite-grid factor representations."""

    INTEGER = "integer"
    CONTINUOUS = "continuous"


def _integer(value: object, name: str, minimum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, Integral):
        raise BayesianOptimizationConfigurationError(f"{name} must be an integer.")
    normalized = int(value)
    if normalized < minimum:
        raise BayesianOptimizationConfigurationError(f"{name} must be at least {minimum}.")
    return normalized


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
