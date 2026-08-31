"""Threshold-fill support recovery for the attacking hurdle diagnostic."""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast

import numpy as np
import pandas as pd

from squadopt.experiments.attacking_hurdle import (
    BOOTSTRAP_RESAMPLES,
    BOOTSTRAP_SEED,
    CONFIDENCE_LEVEL,
    IDENTITY_TOLERANCE,
    INCONCLUSIVE,
    MIN_POSITIVE_RETURNS,
    NOT_LOCALIZED,
    OCCURRENCE_CARRIER,
    POSITIVE_SEVERITY_CARRIER,
    SHARED_HURDLE_FAILURE,
    AttackingHurdleError,
)
from squadopt.experiments.attacking_hurdle import (
    build_fold_reading as _build_hurdle_fold_reading,
)
from squadopt.experiments.attacking_hurdle import classify as _classify_hurdle
from squadopt.experiments.attacking_hurdle import summarise as _summarise_hurdle

CONTRACT_VERSION = "phase2_attacking_support_recovery_v1"
FILL_TARGET = MIN_POSITIVE_RETURNS
RETURN_REFERENCE_SIGNAL = "attacking_return_reference_signal"
POSITIVE_SEVERITY_SIGNAL = "attacking_positive_severity_signal"
SHARED_REFERENCE_SEVERITY_SIGNAL = "shared_attacking_reference_severity_signal"
SUPPORT_RECOVERED_NOT_LOCALIZED = "attacking_support_recovered_not_localized"

_REQUIRED_COLUMNS = {
    "fold_id",
    "season",
    "player_id",
    "weight",
    "attacking_points",
    "history_count",
    "history_attacking_mean",
    "history_positive_returns",
    "positive_mean",
    "severity_reference_positive_returns",
    "severity_source",
    "recovery_background_mean",
    "recovery_background_positive_returns",
    "recovery_background_source",
}


class AttackingSupportRecoveryError(ValueError):
    """Raised when support-recovery inputs violate the frozen rule."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AttackingSupportRecoveryError(message)


def _counts(series: pd.Series, name: str) -> np.ndarray:
    numeric = pd.to_numeric(series, errors="coerce").to_numpy(dtype="float64")
    _require(
        bool(np.isfinite(numeric).all())
        and bool((numeric >= 0.0).all())
        and bool(np.equal(numeric, np.floor(numeric)).all()),
        f"{name} must contain non-negative integers.",
    )
    return numeric.astype("int64")


def _numbers(frame: pd.DataFrame, column: str) -> np.ndarray:
    return pd.to_numeric(frame[column], errors="coerce").to_numpy(dtype="float64")


def recover_player_rows(player_rows: pd.DataFrame) -> pd.DataFrame:
    """Apply the frozen fill-to-five rule and return exact player-level terms."""

    _require(isinstance(player_rows, pd.DataFrame), "player rows must be a DataFrame.")
    missing = sorted(_REQUIRED_COLUMNS - set(player_rows.columns))
    _require(not missing, f"player rows are missing columns {missing!r}.")
    _require(not player_rows.empty, "player rows are empty.")
    frame = player_rows.copy(deep=True)
    _require(
        not bool(frame[["fold_id", "season", "player_id"]].isna().any().any()),
        "player identities must be complete.",
    )
    _require(
        not bool(frame.duplicated(["fold_id", "player_id"]).any()),
        "a fold repeats a selected player.",
    )

    weight = _numbers(frame, "weight")
    attacking = _numbers(frame, "attacking_points")
    history_count = _counts(frame["history_count"], "history_count")
    history_mean = _numbers(frame, "history_attacking_mean")
    positive_count = _counts(frame["history_positive_returns"], "history_positive_returns")
    phase2j_mean = _numbers(frame, "positive_mean")
    phase2j_reference_count = _counts(
        frame["severity_reference_positive_returns"],
        "severity_reference_positive_returns",
    )
    background_mean = _numbers(frame, "recovery_background_mean")
    background_count = _counts(
        frame["recovery_background_positive_returns"],
        "recovery_background_positive_returns",
    )
    severity_source = frame["severity_source"].astype("string")
    background_source = frame["recovery_background_source"].astype("string")

    _require(
        bool(np.isfinite(weight).all()) and bool(np.isin(weight, (1.0, 2.0)).all()),
        "starter weights must be one or two.",
    )
    _require(
        bool(np.isfinite(attacking).all()) and bool((attacking >= 0.0).all()),
        "attacking points must be finite and non-negative.",
    )
    _require(
        bool((history_count > 0).all()) and bool((positive_count <= history_count).all()),
        "history counts must be positive and cover every positive return.",
    )
    _require(
        bool(np.isfinite(history_mean).all()) and bool((history_mean >= 0.0).all()),
        "historical attacking means must be finite and non-negative.",
    )
    zero = positive_count == 0
    sparse = np.logical_and(positive_count > 0, positive_count < MIN_POSITIVE_RETURNS)
    unchanged = positive_count >= MIN_POSITIVE_RETURNS
    _require(
        bool(np.isclose(history_mean[zero], 0.0, rtol=0.0, atol=IDENTITY_TOLERANCE).all()),
        "a zero-positive history must have mean zero.",
    )

    positive = positive_count > 0
    _require(
        bool(np.isfinite(phase2j_mean[positive]).all())
        and bool((phase2j_mean[positive] > 0.0).all()),
        "a positive Phase 2H pool needs its positive-return mean.",
    )
    _require(
        bool((phase2j_reference_count[positive] == positive_count[positive]).all()),
        "a positive Phase 2H pool cannot change the Phase 2J reference count.",
    )
    positive_sum = history_mean * history_count
    _require(
        bool(
            np.isclose(
                phase2j_mean[positive] * positive_count[positive],
                positive_sum[positive],
                rtol=0.0,
                atol=IDENTITY_TOLERANCE,
            ).all()
        ),
        "the Phase 2J positive mean does not reproduce the Phase 2H history sum.",
    )

    valid_phase2j_zero = np.logical_and(
        zero,
        np.logical_and(
            phase2j_reference_count >= MIN_POSITIVE_RETURNS,
            np.logical_and(np.isfinite(phase2j_mean), phase2j_mean > 0.0),
        ),
    )
    missing_phase2j_zero = np.logical_and(zero, ~valid_phase2j_zero)
    _require(
        bool(severity_source[valid_phase2j_zero].notna().all())
        and bool(severity_source[valid_phase2j_zero].str.len().gt(0).all()),
        "a supported zero-positive Phase 2J fallback needs a source label.",
    )
    _require(
        bool((phase2j_reference_count[missing_phase2j_zero] == 0).all())
        and bool(np.isnan(phase2j_mean[missing_phase2j_zero]).all()),
        "an unsupported zero-positive row must not carry a Phase 2J fallback.",
    )
    _require(
        bool(
            np.logical_or(
                background_count == 0,
                background_count >= MIN_POSITIVE_RETURNS,
            ).all()
        ),
        "a recovery background must have five positive returns or be unavailable.",
    )
    has_background = background_count >= MIN_POSITIVE_RETURNS
    _require(
        bool(np.isfinite(background_mean[has_background]).all())
        and bool((background_mean[has_background] > 0.0).all()),
        "an available recovery background needs a finite positive mean.",
    )
    _require(
        bool(np.isnan(background_mean[~has_background]).all()),
        "an unavailable recovery background must not carry a mean.",
    )
    _require(
        bool(background_source[has_background].notna().all())
        and bool(background_source[has_background].str.len().gt(0).all()),
        "an available recovery background needs a source label.",
    )

    supported = np.logical_or(unchanged, np.logical_or(valid_phase2j_zero, sparse & has_background))
    m_tilde = np.full(len(frame), np.nan, dtype="float64")
    m_tilde[unchanged] = phase2j_mean[unchanged]
    m_tilde[valid_phase2j_zero] = phase2j_mean[valid_phase2j_zero]
    recovered = sparse & has_background
    missing_count = MIN_POSITIVE_RETURNS - positive_count[recovered]
    m_tilde[recovered] = (
        positive_sum[recovered] + missing_count * background_mean[recovered]
    ) / MIN_POSITIVE_RETURNS

    occurred = attacking > 0.0
    reference = np.full(len(frame), np.nan, dtype="float64")
    severity = np.full(len(frame), np.nan, dtype="float64")
    reference[supported] = weight[supported] * (
        occurred[supported].astype("float64") * m_tilde[supported] - history_mean[supported]
    )
    severity[supported] = (
        weight[supported]
        * occurred[supported].astype("float64")
        * (attacking[supported] - m_tilde[supported])
    )
    attacking_surprise = weight * (attacking - history_mean)
    identity_error = reference + severity - attacking_surprise
    _require(
        bool(
            np.isclose(
                identity_error[supported],
                0.0,
                rtol=0.0,
                atol=IDENTITY_TOLERANCE,
            ).all()
        ),
        "reference and severity do not reproduce Phase 2H attacking surprise.",
    )

    fill_fraction = np.where(
        positive_count < MIN_POSITIVE_RETURNS,
        (MIN_POSITIVE_RETURNS - positive_count) / MIN_POSITIVE_RETURNS,
        0.0,
    )
    alignment_gap = np.full(len(frame), np.nan, dtype="float64")
    alignment_gap[supported] = weight[supported] * (
        (positive_count[supported] / history_count[supported]) * m_tilde[supported]
        - history_mean[supported]
    )
    source = np.full(len(frame), "unsupported", dtype="object")
    source[unchanged] = "unchanged"
    source[valid_phase2j_zero] = severity_source[valid_phase2j_zero].astype(str)
    source[recovered] = background_source[recovered].astype(str)
    support_bin = np.select(
        (zero, sparse, unchanged),
        ("zero", "one_to_four", "five_plus"),
        default="invalid",
    )

    frame["m_tilde"] = m_tilde
    frame["fill_fraction"] = fill_fraction
    frame["alignment_gap"] = alignment_gap
    frame["reference"] = reference
    frame["severity"] = severity
    frame["attacking_surprise"] = attacking_surprise
    frame["identity_error"] = identity_error
    frame["target_positive"] = occurred.astype("int64")
    frame["supported"] = supported.astype("int64")
    frame["support_bin"] = support_bin
    frame["reference_source"] = source
    frame["recovered_sparse"] = recovered.astype("int64")
    return frame


def build_fold_reading(
    player_rows: pd.DataFrame,
    control_realized_score: float,
    lower_quantile_score: float,
    control_below_q10: bool,
) -> dict[str, object]:
    """Read recovered reference and severity counterfactuals for one fold."""

    hurdle_rows = player_rows.copy(deep=True)
    hurdle_rows["occurrence"] = hurdle_rows["reference"]
    reading = _build_hurdle_fold_reading(
        hurdle_rows,
        control_realized_score,
        lower_quantile_score,
        control_below_q10,
    )
    return {
        (
            f"reference_{key.removeprefix('occurrence_')}" if key.startswith("occurrence_") else key
        ): value
        for key, value in reading.items()
    }


def summarise(fold_readings: pd.DataFrame) -> dict[str, object]:
    """Reuse the frozen Phase 2J fold bootstrap under reference terminology."""

    hurdle_rows = fold_readings.rename(
        columns={
            "reference_surprise": "occurrence_surprise",
            "reference_reduction": "occurrence_reduction",
        }
    )
    summary = _summarise_hurdle(hurdle_rows)
    parts = cast(Mapping[str, object], summary["parts"])
    return {
        **summary,
        "parts": {"reference": parts["occurrence"], "severity": parts["severity"]},
    }


def _hurdle_summary(summary: Mapping[str, object]) -> dict[str, object]:
    parts = cast(Mapping[str, object], summary["parts"])
    return {
        **summary,
        "parts": {"occurrence": parts["reference"], "severity": parts["severity"]},
    }


def classify(validation: Mapping[str, object], sensitivity: Mapping[str, object]) -> str:
    """Map the frozen Phase 2J tree to the support-recovery labels."""

    try:
        hurdle_result = _classify_hurdle(
            _hurdle_summary(validation),
            _hurdle_summary(sensitivity),
        )
    except (KeyError, TypeError, ValueError, OverflowError):
        return INCONCLUSIVE
    return {
        OCCURRENCE_CARRIER: RETURN_REFERENCE_SIGNAL,
        POSITIVE_SEVERITY_CARRIER: POSITIVE_SEVERITY_SIGNAL,
        SHARED_HURDLE_FAILURE: SHARED_REFERENCE_SEVERITY_SIGNAL,
        NOT_LOCALIZED: SUPPORT_RECOVERED_NOT_LOCALIZED,
        INCONCLUSIVE: INCONCLUSIVE,
    }[hurdle_result]


__all__ = [
    "BOOTSTRAP_RESAMPLES",
    "BOOTSTRAP_SEED",
    "CONFIDENCE_LEVEL",
    "CONTRACT_VERSION",
    "FILL_TARGET",
    "IDENTITY_TOLERANCE",
    "INCONCLUSIVE",
    "MIN_POSITIVE_RETURNS",
    "POSITIVE_SEVERITY_SIGNAL",
    "RETURN_REFERENCE_SIGNAL",
    "SHARED_REFERENCE_SEVERITY_SIGNAL",
    "SUPPORT_RECOVERED_NOT_LOCALIZED",
    "AttackingHurdleError",
    "AttackingSupportRecoveryError",
    "build_fold_reading",
    "classify",
    "recover_player_rows",
    "summarise",
]
