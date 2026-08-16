"""Recommending a squad for a real, upcoming deadline.

Everything here reads a captured snapshot rather than a live endpoint: capture is a
deliberate step in a script, and what arrives here is bytes that were written down. That
is what lets a past recommendation be rebuilt exactly, and what keeps every test offline.
"""

from squadopt.live.calibration import (
    HISTORICAL_CAPTAIN_OPTIMISM,
    HISTORICAL_XI_OPTIMISM_PER_STARTER,
    INTERVAL_RULE_VERSION,
    LIVE_CALIBRATION_CONTRACT_VERSION,
    GameweekCalibrationRow,
    LiveCalibrationError,
    LiveCalibrationResult,
    calibration_markdown,
    measure_live_calibration,
)
from squadopt.live.ledger import (
    SEASON_LEDGER_CONTRACT_VERSION,
    LedgerEntry,
    LedgerError,
    extract_event_points,
    ledger_summary,
    load_entry,
    load_ledger,
    record_decision,
    record_outcome,
    summary_markdown,
)
from squadopt.live.recommendation import (
    CONTROL_MODEL_NAME,
    CONTROL_MODEL_VERSION,
    OPENING_FEATURE_CONTRACT_VERSION,
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
from squadopt.live.risk import (
    LIVE_RISK_CONTRACT_VERSION,
    LiveResidualHistory,
    LiveRiskBlocker,
    LiveRiskDiagnostics,
    LiveRiskStatus,
    LiveRiskValidationError,
    evaluate_live_risk,
    risk_not_requested,
)

__all__ = [
    "CONTROL_MODEL_NAME",
    "CONTROL_MODEL_VERSION",
    "HISTORICAL_CAPTAIN_OPTIMISM",
    "HISTORICAL_XI_OPTIMISM_PER_STARTER",
    "INTERVAL_RULE_VERSION",
    "LIVE_CALIBRATION_CONTRACT_VERSION",
    "LIVE_RISK_CONTRACT_VERSION",
    "OPENING_FEATURE_CONTRACT_VERSION",
    "REPORT_CONTRACT_VERSION",
    "SEASON_LEDGER_CONTRACT_VERSION",
    "SQUAD_COLUMNS",
    "SUPPORTED_TARGET_GAMEWEEK",
    "GameweekCalibrationRow",
    "LedgerEntry",
    "LedgerError",
    "LiveCalibrationError",
    "LiveCalibrationResult",
    "LiveResidualHistory",
    "LiveRiskBlocker",
    "LiveRiskDiagnostics",
    "LiveRiskStatus",
    "LiveRiskValidationError",
    "Projection",
    "Recommendation",
    "RecommendationInputs",
    "build_recommendation",
    "calibration_markdown",
    "evaluate_live_risk",
    "extract_event_points",
    "infer_season",
    "ledger_summary",
    "load_entry",
    "load_ledger",
    "measure_live_calibration",
    "project",
    "projection_fingerprint",
    "read_inputs",
    "record_decision",
    "record_outcome",
    "render",
    "risk_not_requested",
    "summary_markdown",
]
