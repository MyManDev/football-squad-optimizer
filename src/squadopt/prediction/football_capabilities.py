"""Trusted runtime semantics of known football model versions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from squadopt.prediction.football import (
    JOINT_ROLE_COMPONENT_MODEL_VERSIONS,
    JOINT_ROLE_FLAG_MODEL_VERSION,
)

COMPOSITE_MODEL_VERSION = "football_composite_v1"
COMPOSITE_FEATURE_VERSION = "football_composite_features_v1"
COMPOSITE_REPROJECTION_VERSION = "football_composite_reprojection_v1"
COMPOSITE_AVAILABILITY_POLICY = "final_joint_week_law_once_v1"
COMPOSITE_ACTIVE_HEADS = (
    "retained_flags_minutes",
    "observed_competition_load",
    "pooled_fm_unit_rates",
    "score_state_survival",
    "observed_tactical_recipients",
    "phase_duties",
)


@dataclass(frozen=True, slots=True)
class FootballCapabilities:
    """Properties are code-owned, never accepted from artifact-supplied booleans."""

    role_components: bool = False
    eligibility_included: Literal["none", "first_week", "all_weeks"] = "none"
    clean_sheet_law: Literal["single_rate", "score_process"] = "single_rate"
    requires_ready_bundle: bool = False
    requires_reprojection: bool = False

    def includes_eligibility(self, gameweek: int, first_gameweek: int) -> bool:
        return self.eligibility_included == "all_weeks" or (
            self.eligibility_included == "first_week" and gameweek == first_gameweek
        )


def football_capabilities(model_version: object) -> FootballCapabilities:
    """Describe dispatch semantics; version admission remains each reader's job."""
    if model_version == COMPOSITE_MODEL_VERSION:
        return FootballCapabilities(True, "all_weeks", "score_process", True, True)
    if model_version == JOINT_ROLE_FLAG_MODEL_VERSION:
        return FootballCapabilities(True, "first_week", "single_rate", True, False)
    if model_version in JOINT_ROLE_COMPONENT_MODEL_VERSIONS:
        return FootballCapabilities(True, "none", "single_rate", True, False)
    return FootballCapabilities()
