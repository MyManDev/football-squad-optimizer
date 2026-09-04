"""The gate a tuned strategy knob must pass, and the declaration frozen before it runs.

Five Bayesian searches have found a candidate and none was ever promoted — not because
the candidates were bad, but because nothing could pass a gate that was never written:
``PromotionPolicy``, ``CandidateDeclaration`` and ``run_frozen_holdout`` are all built
for a *prediction-model* candidate, and a tuned knob (a chip holding value, a hit cost,
an overlap band) is not one. The chip search's own artifact says "candidate for the
next chain **and gates**"; this module is those gates.

The order is the point: a ``StrategyDeclaration`` — the tuned point, its baseline, the
objective and design identities, and the pass thresholds — is committed **before** the
confirmation runs. The runner then binds the result to the declaration's fingerprint.
A threshold moved after seeing the numbers is a different declaration with a different
fingerprint, visibly.

The gate itself reuses the one confidence definition the project has:
``season_aware_moving_block_interval`` on fold-paired differences, exactly as the
screening design uses it — a second implementation would leave two definitions of the
same claim.
"""

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from numbers import Real
from statistics import fmean
from types import MappingProxyType
from typing import Final

from squadopt.experiments.config import (
    ExperimentConfigurationError,
    ExperimentExecutionError,
    PromotionPolicy,
)
from squadopt.experiments.statistics import season_aware_moving_block_interval

STRATEGY_DECLARATION_CONTRACT_VERSION: Final = "strategy_declaration_v1"


def _validated_knobs(values: Mapping[str, object], name: str) -> Mapping[str, int | float]:
    normalized: dict[str, int | float] = {}
    for key, value in dict(values).items():
        if not isinstance(key, str) or not key.strip():
            raise ExperimentConfigurationError(f"{name} keys must be non-empty strings.")
        if isinstance(value, bool) or not isinstance(value, Real):
            raise ExperimentConfigurationError(f"{name}[{key!r}] must be a finite number.")
        number = float(value)
        if not math.isfinite(number):
            raise ExperimentConfigurationError(f"{name}[{key!r}] must be a finite number.")
        normalized[key] = int(value) if isinstance(value, int) else number
    if not normalized:
        raise ExperimentConfigurationError(f"{name} must name at least one knob.")
    return MappingProxyType(normalized)


@dataclass(frozen=True, slots=True)
class StrategyDeclaration:
    """One tuned-knob candidate, frozen with its gate before the confirmation run.

    ``knob_values`` is the tuned point exactly as the search produced it;
    ``baseline_knob_values`` is the incumbent it must beat (the declared defaults, or
    the previously gated point). The two must move the same knobs — a candidate that
    changes a knob the baseline does not carry is comparing two different questions.
    ``objective_fingerprint`` and ``design_fingerprint`` bind which objective measured
    it and which design searched it, so a passing verdict cannot be re-attached to a
    different search after the fact.
    """

    declaration_id: str
    strategy_slug: str
    knob_values: Mapping[str, int | float]
    baseline_knob_values: Mapping[str, int | float]
    objective_fingerprint: str
    design_fingerprint: str
    population_id: str
    change_summary: str
    gate: PromotionPolicy = field(default_factory=PromotionPolicy)
    source_reference: str = ""
    contract_version: str = STRATEGY_DECLARATION_CONTRACT_VERSION

    def __post_init__(self) -> None:
        for name in (
            "declaration_id",
            "strategy_slug",
            "objective_fingerprint",
            "design_fingerprint",
            "population_id",
            "change_summary",
            "contract_version",
        ):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ExperimentConfigurationError(f"{name} must be non-empty text.")
            object.__setattr__(self, name, value.strip())
        if self.contract_version != STRATEGY_DECLARATION_CONTRACT_VERSION:
            raise ExperimentConfigurationError("Unsupported declaration contract_version.")
        if not isinstance(self.gate, PromotionPolicy):
            raise ExperimentConfigurationError("gate must be a PromotionPolicy.")
        if not isinstance(self.source_reference, str):
            raise ExperimentConfigurationError("source_reference must be text.")
        object.__setattr__(self, "knob_values", _validated_knobs(self.knob_values, "knob_values"))
        object.__setattr__(
            self,
            "baseline_knob_values",
            _validated_knobs(self.baseline_knob_values, "baseline_knob_values"),
        )
        if set(self.knob_values) != set(self.baseline_knob_values):
            raise ExperimentConfigurationError(
                "knob_values and baseline_knob_values must move the same knobs; anything "
                "else compares two different questions."
            )
        if dict(self.knob_values) == dict(self.baseline_knob_values):
            raise ExperimentConfigurationError(
                "The tuned point equals the baseline; there is nothing to gate."
            )

    @property
    def declaration_fingerprint(self) -> str:
        """Bind the verdict to the exact declaration committed before the run."""

        payload = {
            "contract_version": self.contract_version,
            "declaration_id": self.declaration_id,
            "strategy_slug": self.strategy_slug,
            "knob_values": {k: self.knob_values[k] for k in sorted(self.knob_values)},
            "baseline_knob_values": {
                k: self.baseline_knob_values[k] for k in sorted(self.baseline_knob_values)
            },
            "objective_fingerprint": self.objective_fingerprint,
            "design_fingerprint": self.design_fingerprint,
            "population_id": self.population_id,
            "change_summary": self.change_summary,
            "gate": {
                "min_mean_improvement": self.gate.min_mean_improvement,
                "confidence_level": self.gate.confidence_level,
                "bootstrap_resamples": self.gate.bootstrap_resamples,
                "moving_block_length": self.gate.moving_block_length,
                "deterministic_seed": self.gate.deterministic_seed,
            },
            "source_reference": self.source_reference,
        }
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()


@dataclass(frozen=True, slots=True)
class StrategyGateResult:
    """The verdict, bound to the declaration that pre-registered it."""

    declaration_fingerprint: str
    comparable_folds: int
    mean_improvement: float
    confidence_interval_lower: float
    confidence_interval_upper: float
    passes_mean_improvement: bool
    passes_confidence_interval: bool
    promoted: bool
    season_mean_improvements: Mapping[str, float]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "season_mean_improvements",
            MappingProxyType(dict(self.season_mean_improvements)),
        )


def run_strategy_gate(
    declaration: StrategyDeclaration,
    tuned_folds: Sequence[tuple[str, float]],
    baseline_folds: Sequence[tuple[str, float]],
) -> StrategyGateResult:
    """Judge the tuned point against its baseline on fold-paired values.

    ``tuned_folds`` and ``baseline_folds`` are (season, objective value) per fold, in
    the same fold order — the pairing is positional and the seasons must agree pair by
    pair, because an unpaired comparison under a 46-98 point season spread measures the
    folds, not the knob. The verdict passes only when the mean improvement clears the
    declared floor **and** the season-aware moving-block interval excludes zero from
    below. A failed gate is a result, not a retry: the thresholds travel with the
    declaration's fingerprint, so moving them is visibly a new declaration.
    """

    tuned = list(tuned_folds)
    baseline = list(baseline_folds)
    if not tuned or len(tuned) != len(baseline):
        raise ExperimentExecutionError(
            "tuned and baseline fold values must be non-empty and fold-paired."
        )
    differences: list[tuple[str, float]] = []
    by_season: dict[str, list[float]] = {}
    for (tuned_season, tuned_value), (baseline_season, baseline_value) in zip(
        tuned, baseline, strict=True
    ):
        if tuned_season != baseline_season:
            raise ExperimentExecutionError(
                f"Fold pairing broken: {tuned_season!r} paired with {baseline_season!r}."
            )
        for value in (tuned_value, baseline_value):
            if isinstance(value, bool) or not isinstance(value, Real) or not math.isfinite(value):
                raise ExperimentExecutionError("Fold values must be finite numbers.")
        difference = float(tuned_value) - float(baseline_value)
        differences.append((tuned_season, difference))
        by_season.setdefault(tuned_season, []).append(difference)

    mean_improvement = fmean(difference for _, difference in differences)
    lower, upper = season_aware_moving_block_interval(
        differences,
        policy=declaration.gate,
        candidate_id=declaration.declaration_id,
    )
    passes_mean = mean_improvement >= declaration.gate.min_mean_improvement
    passes_interval = lower > 0.0
    return StrategyGateResult(
        declaration_fingerprint=declaration.declaration_fingerprint,
        comparable_folds=len(differences),
        mean_improvement=mean_improvement,
        confidence_interval_lower=lower,
        confidence_interval_upper=upper,
        passes_mean_improvement=passes_mean,
        passes_confidence_interval=passes_interval,
        promoted=passes_mean and passes_interval,
        season_mean_improvements={
            season: fmean(values) for season, values in sorted(by_season.items())
        },
    )
