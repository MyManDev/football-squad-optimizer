"""Public immutable result contracts for screening and frozen holdout evaluation."""

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from squadopt.evaluation import EvaluationResult
from squadopt.experiments.config import (
    SCREENING_EXPERIMENT_CONTRACT_VERSION,
    ExperimentCandidate,
    FrozenCandidateError,
    ScreeningExperimentConfig,
)


@dataclass(frozen=True, slots=True)
class PairedComparison:
    """Fold-paired challenger response relative to the named control."""

    candidate_id: str
    control_id: str
    comparable_folds: int
    mean_difference: float | None
    confidence_interval_lower: float | None
    confidence_interval_upper: float | None
    season_mean_differences: Mapping[str, float]
    passes_feasibility: bool
    passes_mean_improvement: bool
    passes_confidence_interval: bool
    eligible: bool

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "season_mean_differences",
            MappingProxyType(dict(self.season_mean_differences)),
        )


@dataclass(frozen=True, slots=True)
class CandidateAssessment:
    """One factorial cell, its fold results, and its promotion-gate response."""

    candidate: ExperimentCandidate
    evaluation: EvaluationResult
    coefficient_signature: str
    equivalent_to: str | None
    comparison: PairedComparison


@dataclass(frozen=True, slots=True)
class MainEffect:
    """Marginal response for one factor level in the balanced full factorial."""

    factor: str
    level: str
    marginal_mean: float | None
    effect_from_control_level: float | None


@dataclass(frozen=True, slots=True)
class InteractionEffect:
    """Two-factor cell residual after subtracting both marginal effects."""

    candidate_id: str
    form_window: int
    bench_weight: float
    mean_response: float | None
    interaction_residual: float | None


@dataclass(frozen=True, slots=True)
class ScreeningExperimentResult:
    """Complete development-only DoE result and frozen selection decision."""

    config: ScreeningExperimentConfig
    assessments: tuple[CandidateAssessment, ...]
    main_effects: tuple[MainEffect, ...]
    interactions: tuple[InteractionEffect, ...]
    selected_candidate: ExperimentCandidate
    selection_reason: str
    screening_fingerprint: str
    diagnostics: Mapping[str, object]

    def __post_init__(self) -> None:
        object.__setattr__(self, "diagnostics", MappingProxyType(dict(self.diagnostics)))

    @property
    def selected_is_control(self) -> bool:
        """Return whether development screening retained the baseline."""

        return self.selected_candidate.candidate_id == self.config.control.candidate_id


@dataclass(frozen=True, slots=True)
class FrozenCandidate:
    """Candidate decision sealed before the holdout season is evaluated."""

    candidate: ExperimentCandidate
    control: ExperimentCandidate
    screening_fingerprint: str
    configuration_fingerprint: str
    experiment_contract_version: str = SCREENING_EXPERIMENT_CONTRACT_VERSION

    def __post_init__(self) -> None:
        for name in ("screening_fingerprint", "configuration_fingerprint"):
            value = getattr(self, name)
            if (
                not isinstance(value, str)
                or len(value) != 64
                or any(character not in "0123456789abcdef" for character in value)
            ):
                raise FrozenCandidateError(f"{name} must be a 64-character SHA-256 digest.")
        if self.experiment_contract_version != SCREENING_EXPERIMENT_CONTRACT_VERSION:
            raise FrozenCandidateError(
                "Frozen candidate experiment contract does not match this package version."
            )


@dataclass(frozen=True, slots=True)
class HoldoutEvaluationResult:
    """Locked-holdout comparison performed after candidate freezing."""

    frozen_candidate: FrozenCandidate
    candidate_assessment: CandidateAssessment
    control_assessment: CandidateAssessment
    promoted: bool
    decision_reason: str
    diagnostics: Mapping[str, object]

    def __post_init__(self) -> None:
        object.__setattr__(self, "diagnostics", MappingProxyType(dict(self.diagnostics)))
