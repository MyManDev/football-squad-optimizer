"""General experiment designs over a declared factor space, and the one objective shape.

Every search this repository has run so far wrote its own enumeration and its own
objective closure: the screening DoE fixes ``form_window x bench_weight`` in its config,
the policy objectives each carry their own fold vocabulary, and the chip search embeds
its evaluator in the script that ran it. Adding a tactic to search means copying one of
them. This module is the general replacement: a design is a named generator over the
same ``BayesianFactor`` grid the optimizer already speaks, and an objective is one
declared shape — strategy, knobs, population, per-fold evaluator — that screening and
Bayesian search consume alike.

Two rules are structural here:

- **The declared space is the searched space.** A design is built from the factors it
  is given and nothing else; there is no side channel for an extra knob, so "what was
  searched" and "what was declared" cannot drift apart.
- **Fold values are the unit of measurement.** The objective returns a mean, but keeps
  the per-fold vector: paired comparisons across candidates need the folds, and a
  season spread of 46-98 points makes unpaired means close to meaningless.
"""

import hashlib
import json
import math
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from itertools import product
from typing import Final

import numpy as np
from scipy.stats import qmc

from squadopt.bayesopt import BayesianCandidate, BayesianFactor
from squadopt.experiments.config import (
    ExperimentConfigurationError,
    ExperimentExecutionError,
)

EXPERIMENT_DESIGN_CONTRACT_VERSION: Final = "experiment_design_v1"

# Plackett-Burman first rows (Plackett & Burman 1946), cyclically shifted then closed
# with a row of minus ones. Runs must be a multiple of four; these cover every factor
# count the catalogue's knob spaces reach.
_PLACKETT_BURMAN_ROWS: Final[dict[int, tuple[int, ...]]] = {
    8: (1, 1, 1, -1, 1, -1, -1),
    12: (1, 1, -1, 1, 1, 1, -1, -1, -1, 1, -1),
    16: (1, 1, 1, 1, -1, 1, -1, 1, 1, -1, -1, 1, -1, -1, -1),
    20: (1, 1, -1, -1, 1, 1, 1, 1, -1, 1, -1, 1, -1, -1, -1, -1, 1, 1, -1),
}


class DesignKind(StrEnum):
    """Supported design generators."""

    FULL_FACTORIAL = "full_factorial"
    FRACTIONAL_FACTORIAL = "fractional_factorial"
    PLACKETT_BURMAN = "plackett_burman"
    LATIN_HYPERCUBE = "latin_hypercube"
    SOBOL = "sobol"


def _validated_factors(factors: Sequence[BayesianFactor]) -> tuple[BayesianFactor, ...]:
    normalized = tuple(factors)
    if not normalized:
        raise ExperimentConfigurationError("A design needs at least one factor.")
    if any(not isinstance(factor, BayesianFactor) for factor in normalized):
        raise ExperimentConfigurationError("Factors must be BayesianFactor instances.")
    names = [factor.name for factor in normalized]
    if len(names) != len(set(names)):
        raise ExperimentConfigurationError("Factor names must be unique.")
    return normalized


def _two_levels(factor: BayesianFactor) -> tuple[int | float, int | float]:
    levels = factor.levels
    return levels[0], levels[-1]


def _candidates_from_signs(
    factors: tuple[BayesianFactor, ...], rows: Iterable[Sequence[int]]
) -> tuple[BayesianCandidate, ...]:
    candidates = []
    for row in rows:
        values: dict[str, int | float] = {}
        for factor, sign in zip(factors, row, strict=True):
            low, high = _two_levels(factor)
            values[factor.name] = high if sign > 0 else low
        candidates.append(BayesianCandidate(values))
    return _deduplicated(candidates)


def _deduplicated(candidates: Sequence[BayesianCandidate]) -> tuple[BayesianCandidate, ...]:
    """Drop exact repeats, keeping first occurrence and order.

    Snapping continuous samples onto a coarse grid can land two runs on the same cell,
    and a fixed factor collapses both levels of a two-level column. A repeated
    evaluation adds information only when the objective is stochastic, which is the
    replication machinery's business, not the design's; the design yields unique cells
    and reports how many it was asked for versus how many survived.
    """

    seen: set[str] = set()
    unique: list[BayesianCandidate] = []
    for candidate in candidates:
        if candidate.candidate_id not in seen:
            seen.add(candidate.candidate_id)
            unique.append(candidate)
    return tuple(unique)


def _snap(factor: BayesianFactor, fraction: float) -> int | float:
    """Map a unit-interval sample onto the factor's exact grid, nearest level."""

    levels = factor.levels
    index = round(fraction * (len(levels) - 1))
    return levels[max(0, min(index, len(levels) - 1))]


@dataclass(frozen=True, slots=True)
class ExperimentDesign:
    """One named design over a declared factor space; ``candidates()`` realizes it.

    ``size`` is the requested run count for the sampling designs (Latin hypercube,
    Sobol) and ignored by the factorial constructions, whose size is a property of the
    factor space. ``seed`` makes the sampling designs reproducible; the factorials do
    not consume it. Duplicates created by grid snapping or fixed factors are dropped,
    so the realized design may be smaller than requested — the design says so rather
    than padding.
    """

    kind: DesignKind
    factors: tuple[BayesianFactor, ...]
    size: int = 0
    seed: int = 0
    fraction_generators: tuple[tuple[str, tuple[str, ...]], ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "factors", _validated_factors(self.factors))
        if not isinstance(self.kind, DesignKind):
            try:
                object.__setattr__(self, "kind", DesignKind(self.kind))
            except ValueError as error:
                raise ExperimentConfigurationError("Unsupported design kind.") from error
        if isinstance(self.size, bool) or not isinstance(self.size, int) or self.size < 0:
            raise ExperimentConfigurationError("size must be a non-negative integer.")
        if isinstance(self.seed, bool) or not isinstance(self.seed, int) or self.seed < 0:
            raise ExperimentConfigurationError("seed must be a non-negative integer.")
        if self.kind in {DesignKind.LATIN_HYPERCUBE, DesignKind.SOBOL} and self.size < 1:
            raise ExperimentConfigurationError(f"{self.kind} needs an explicit size.")

    def candidates(self) -> tuple[BayesianCandidate, ...]:
        """Realize the design as unique candidates on the declared grids."""

        if self.kind is DesignKind.FULL_FACTORIAL:
            return self._full_factorial()
        if self.kind is DesignKind.FRACTIONAL_FACTORIAL:
            return self._fractional_factorial()
        if self.kind is DesignKind.PLACKETT_BURMAN:
            return self._plackett_burman()
        if self.kind is DesignKind.LATIN_HYPERCUBE:
            return self._latin_hypercube()
        return self._sobol()

    def _full_factorial(self) -> tuple[BayesianCandidate, ...]:
        return _deduplicated(
            [
                BayesianCandidate(
                    dict(zip((factor.name for factor in self.factors), levels, strict=True))
                )
                for levels in product(*(factor.levels for factor in self.factors))
            ]
        )

    def _fractional_factorial(self) -> tuple[BayesianCandidate, ...]:
        """A 2-level fraction: base factors run full, generated factors are products.

        ``fraction_generators`` names each generated factor and the base factors whose
        signs multiply into it — the standard fractional construction, declared rather
        than inferred so the aliasing structure is readable in the artifact.
        """

        if not self.fraction_generators:
            raise ExperimentConfigurationError(
                "fractional_factorial needs fraction_generators naming each generated factor."
            )
        by_name = {factor.name: factor for factor in self.factors}
        generated = {name for name, _ in self.fraction_generators}
        for name, parents in self.fraction_generators:
            if name not in by_name:
                raise ExperimentConfigurationError(f"Generator names unknown factor {name!r}.")
            missing = [parent for parent in parents if parent not in by_name]
            if missing or not parents:
                raise ExperimentConfigurationError(
                    f"Generator for {name!r} must name existing base factors."
                )
            if any(parent in generated for parent in parents):
                raise ExperimentConfigurationError(
                    f"Generator for {name!r} may only multiply base factors."
                )
        base = tuple(factor for factor in self.factors if factor.name not in generated)
        if not base:
            raise ExperimentConfigurationError("At least one base factor must remain.")
        rows: list[list[int]] = []
        for signs in product((-1, 1), repeat=len(base)):
            sign_of = dict(zip((factor.name for factor in base), signs, strict=True))
            row: list[int] = []
            for factor in self.factors:
                if factor.name in sign_of:
                    row.append(sign_of[factor.name])
                else:
                    parents = next(p for n, p in self.fraction_generators if n == factor.name)
                    value = 1
                    for parent in parents:
                        value *= sign_of[parent]
                    row.append(value)
            rows.append(row)
        return _candidates_from_signs(self.factors, rows)

    def _plackett_burman(self) -> tuple[BayesianCandidate, ...]:
        count = len(self.factors)
        runs = next((n for n in sorted(_PLACKETT_BURMAN_ROWS) if n - 1 >= count), None)
        if runs is None:
            raise ExperimentConfigurationError(
                f"Plackett-Burman here covers at most {max(_PLACKETT_BURMAN_ROWS) - 1} factors."
            )
        first = _PLACKETT_BURMAN_ROWS[runs]
        rows: list[Sequence[int]] = []
        for shift in range(runs - 1):
            row = tuple(first[(index - shift) % (runs - 1)] for index in range(runs - 1))
            rows.append(row[:count])
        rows.append((-1,) * count)
        return _candidates_from_signs(self.factors, rows)

    def _latin_hypercube(self) -> tuple[BayesianCandidate, ...]:
        sampler = qmc.LatinHypercube(d=len(self.factors), seed=self.seed)
        return self._snapped(sampler.random(self.size))

    def _sobol(self) -> tuple[BayesianCandidate, ...]:
        sampler = qmc.Sobol(d=len(self.factors), scramble=True, seed=self.seed)
        # Sobol balance holds at powers of two; round the request up rather than
        # silently sampling an unbalanced prefix, then dedupe as ever.
        exponent = max(0, math.ceil(math.log2(self.size)))
        return self._snapped(sampler.random_base2(m=exponent)[: self.size])

    def _snapped(self, samples: object) -> tuple[BayesianCandidate, ...]:
        candidates = []
        for row in np.asarray(samples, dtype=float):
            values = {
                factor.name: _snap(factor, float(fraction))
                for factor, fraction in zip(self.factors, row, strict=True)
            }
            candidates.append(BayesianCandidate(values))
        return _deduplicated(candidates)

    @property
    def design_fingerprint(self) -> str:
        """Stable identity of the realized design, for artifacts and caches."""

        payload = {
            "contract_version": EXPERIMENT_DESIGN_CONTRACT_VERSION,
            "kind": str(self.kind),
            "seed": self.seed,
            "size": self.size,
            "fraction_generators": [
                [name, list(parents)] for name, parents in self.fraction_generators
            ],
            "factors": [
                {"name": factor.name, "levels": [str(level) for level in factor.levels]}
                for factor in self.factors
            ],
            "candidates": [candidate.candidate_id for candidate in self.candidates()],
        }
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()


@dataclass(frozen=True, slots=True)
class StrategyObjective:
    """The one callable shape every screening and search consumes.

    Binds what a search must declare to run at all: which tactic (``strategy_slug``),
    which knobs may move (``factors`` — the same objects the design realizes, so the
    searched space *is* the declared space), which folds measure it
    (``population_id``), and the per-fold evaluator. The objective value is the fold
    mean; the fold vector stays available because paired comparisons need it.
    """

    strategy_slug: str
    factors: tuple[BayesianFactor, ...]
    population_id: str
    evaluate_folds: Callable[[BayesianCandidate], tuple[float, ...]]

    def __post_init__(self) -> None:
        if not isinstance(self.strategy_slug, str) or not self.strategy_slug.strip():
            raise ExperimentConfigurationError("strategy_slug must be a non-empty string.")
        object.__setattr__(self, "factors", _validated_factors(self.factors))
        if not isinstance(self.population_id, str) or not self.population_id.strip():
            raise ExperimentConfigurationError("population_id must be a non-empty string.")
        if not callable(self.evaluate_folds):
            raise ExperimentConfigurationError("evaluate_folds must be callable.")

    def _validated_candidate(self, candidate: BayesianCandidate) -> BayesianCandidate:
        if not isinstance(candidate, BayesianCandidate):
            raise ExperimentExecutionError("candidate must be a BayesianCandidate.")
        declared = {factor.name for factor in self.factors}
        if set(candidate.values) != declared:
            raise ExperimentExecutionError(
                f"Candidate keys {sorted(candidate.values)} do not match the declared "
                f"factors {sorted(declared)}; the searched space must be the declared space."
            )
        return candidate

    def fold_values(self, candidate: BayesianCandidate) -> tuple[float, ...]:
        """Per-fold objective values for one candidate, validated and finite."""

        values = tuple(
            float(value) for value in self.evaluate_folds(self._validated_candidate(candidate))
        )
        if not values:
            raise ExperimentExecutionError(
                f"Evaluator returned no folds for {candidate.candidate_id!r}; an empty "
                "population is a configuration error, not a zero."
            )
        if any(not math.isfinite(value) for value in values):
            raise ExperimentExecutionError(
                f"Evaluator returned a non-finite fold value for {candidate.candidate_id!r}."
            )
        return values

    def __call__(self, candidate: BayesianCandidate) -> float:
        return float(np.mean(self.fold_values(candidate)))

    @property
    def objective_fingerprint(self) -> str:
        """Identity of the declared search, before any evaluation runs."""

        payload = {
            "contract_version": EXPERIMENT_DESIGN_CONTRACT_VERSION,
            "strategy_slug": self.strategy_slug,
            "population_id": self.population_id,
            "factors": [
                {"name": factor.name, "levels": [str(level) for level in factor.levels]}
                for factor in self.factors
            ],
        }
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
