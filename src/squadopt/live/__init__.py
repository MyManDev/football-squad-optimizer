"""Recommending a squad for a real, upcoming deadline.

Everything here reads a captured snapshot rather than a live endpoint: capture is a
deliberate step in a script, and what arrives here is bytes that were written down. That
is what lets a past recommendation be rebuilt exactly, and what keeps every test offline.
"""

from squadopt.live.recommendation import (
    CONTROL_MODEL_NAME,
    CONTROL_MODEL_VERSION,
    SUPPORTED_TARGET_GAMEWEEK,
    Projection,
    RecommendationInputs,
    infer_season,
    project,
    read_inputs,
)
from squadopt.live.report import (
    REPORT_CONTRACT_VERSION,
    SQUAD_COLUMNS,
    Recommendation,
    build_recommendation,
    projection_fingerprint,
    render,
)

__all__ = [
    "CONTROL_MODEL_NAME",
    "CONTROL_MODEL_VERSION",
    "REPORT_CONTRACT_VERSION",
    "SQUAD_COLUMNS",
    "SUPPORTED_TARGET_GAMEWEEK",
    "Projection",
    "Recommendation",
    "RecommendationInputs",
    "build_recommendation",
    "infer_season",
    "project",
    "projection_fingerprint",
    "read_inputs",
    "render",
]
