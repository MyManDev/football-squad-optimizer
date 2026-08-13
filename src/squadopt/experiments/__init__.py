"""Versioned Sprint 2 screening DoE and frozen holdout interface."""

from squadopt.experiments.config import (
    DEFAULT_BENCH_WEIGHTS,
    DEFAULT_DEVELOPMENT_SEASONS,
    DEFAULT_FORM_WINDOWS,
    DEFAULT_HOLDOUT_SEASONS,
    SCREENING_EXPERIMENT_CONTRACT_VERSION,
    ExperimentCandidate,
    ExperimentConfigurationError,
    ExperimentError,
    ExperimentExecutionError,
    FrozenCandidateError,
    PromotionPolicy,
    ScreeningExperimentConfig,
)
from squadopt.experiments.models import (
    CandidateAssessment,
    FrozenCandidate,
    HoldoutEvaluationResult,
    InteractionEffect,
    MainEffect,
    PairedComparison,
    ScreeningExperimentResult,
)
from squadopt.experiments.reporting import (
    frozen_candidate_from_dict,
    frozen_candidate_to_dict,
    holdout_result_to_dict,
    holdout_result_to_markdown,
    screening_result_to_dict,
    screening_result_to_markdown,
)
from squadopt.experiments.runner import (
    freeze_screening_candidate,
    run_frozen_holdout,
    run_screening_experiment,
)

__all__ = [
    "DEFAULT_BENCH_WEIGHTS",
    "DEFAULT_DEVELOPMENT_SEASONS",
    "DEFAULT_FORM_WINDOWS",
    "DEFAULT_HOLDOUT_SEASONS",
    "SCREENING_EXPERIMENT_CONTRACT_VERSION",
    "CandidateAssessment",
    "ExperimentCandidate",
    "ExperimentConfigurationError",
    "ExperimentError",
    "ExperimentExecutionError",
    "FrozenCandidate",
    "FrozenCandidateError",
    "HoldoutEvaluationResult",
    "InteractionEffect",
    "MainEffect",
    "PairedComparison",
    "PromotionPolicy",
    "ScreeningExperimentConfig",
    "ScreeningExperimentResult",
    "freeze_screening_candidate",
    "frozen_candidate_from_dict",
    "frozen_candidate_to_dict",
    "holdout_result_to_dict",
    "holdout_result_to_markdown",
    "run_frozen_holdout",
    "run_screening_experiment",
    "screening_result_to_dict",
    "screening_result_to_markdown",
]
