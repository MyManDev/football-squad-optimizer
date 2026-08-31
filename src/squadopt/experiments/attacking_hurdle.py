"""Exact occurrence/severity attribution for selected-XI attacking surprise."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import cast

import numpy as np
import pandas as pd

from squadopt.experiments.shadow_calibration import bootstrap_interval

CONTRACT_VERSION = "phase2_attacking_hurdle_v1"
OCCURRENCE_CARRIER = "attacking_occurrence_carrier"
POSITIVE_SEVERITY_CARRIER = "attacking_positive_severity_carrier"
SHARED_HURDLE_FAILURE = "shared_attacking_hurdle_failure"
NOT_LOCALIZED = "attacking_hurdle_not_localized"
INCONCLUSIVE = "diagnostic_inconclusive"

BOOTSTRAP_RESAMPLES = 5_000
BOOTSTRAP_SEED = 0
CONFIDENCE_LEVEL = 0.90
MIN_EVALUATION_FOLDS = 30
MIN_POSITIVE_RETURNS = 5
IDENTITY_TOLERANCE = 1e-9

_PARTS = ("occurrence", "severity")
_PLAYER_COLUMNS = {
    "fold_id",
    "season",
    "player_id",
    "weight",
    "attacking_points",
    "history_count",
    "history_attacking_mean",
    "occurrence_probability",
    "positive_mean",
    "history_positive_returns",
    "severity_reference_positive_returns",
}
_FOLD_COLUMNS = {
    "fold_id",
    "season",
    "eligible",
    "identity_error",
    "positive_target_returns",
    "zero_target_returns",
    "control_below_q10",
    "occurrence_surprise",
    "severity_surprise",
    "occurrence_reduction",
    "severity_reduction",
}
_FOLD_PLAYER_COLUMNS = {
    "fold_id",
    "season",
    "player_id",
    "supported",
    "occurrence",
    "severity",
    "attacking_surprise",
    "target_positive",
}


class AttackingHurdleError(ValueError):
    """Raised when an attacking-hurdle measurement violates its frozen contract."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AttackingHurdleError(message)


def _integer_counts(series: pd.Series, name: str) -> pd.Series:
    numeric = pd.to_numeric(series, errors="coerce")
    values = numeric.to_numpy(dtype="float64")
    _require(
        bool(np.isfinite(values).all())
        and bool((values >= 0.0).all())
        and bool(np.equal(values, np.floor(values)).all()),
        f"{name} must contain non-negative integers.",
    )
    return numeric.astype("int64")


def decompose_player_rows(player_rows: pd.DataFrame) -> pd.DataFrame:
    """Return exact weighted occurrence and positive-severity terms per starter."""

    _require(isinstance(player_rows, pd.DataFrame), "player rows must be a DataFrame.")
    missing = sorted(_PLAYER_COLUMNS - set(player_rows.columns))
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

    weights = pd.to_numeric(frame["weight"], errors="coerce").to_numpy(dtype="float64")
    attacking = pd.to_numeric(frame["attacking_points"], errors="coerce").to_numpy(dtype="float64")
    history_mean = pd.to_numeric(frame["history_attacking_mean"], errors="coerce").to_numpy(
        dtype="float64"
    )
    probability = pd.to_numeric(frame["occurrence_probability"], errors="coerce").to_numpy(
        dtype="float64"
    )
    positive_mean = pd.to_numeric(frame["positive_mean"], errors="coerce").to_numpy(dtype="float64")
    history_positive = _integer_counts(
        frame["history_positive_returns"], "history_positive_returns"
    ).to_numpy(dtype="int64")
    history_count = _integer_counts(frame["history_count"], "history_count").to_numpy(dtype="int64")
    reference_positive = _integer_counts(
        frame["severity_reference_positive_returns"],
        "severity_reference_positive_returns",
    ).to_numpy(dtype="int64")

    _require(
        bool(np.isfinite(weights).all()) and bool(np.isin(weights, (1.0, 2.0)).all()),
        "starter weights must be one or two.",
    )
    _require(
        bool(np.isfinite(attacking).all()) and bool((attacking >= 0.0).all()),
        "attacking points must be finite and non-negative.",
    )
    _require(
        bool(np.isfinite(history_mean).all()) and bool((history_mean >= 0.0).all()),
        "historical attacking means must be finite and non-negative.",
    )
    _require(
        bool(np.isfinite(probability).all())
        and bool(((probability >= 0.0) & (probability <= 1.0)).all()),
        "occurrence probabilities must be finite and lie in [0, 1].",
    )
    _require(
        bool((history_count > 0).all()) and bool((history_positive <= history_count).all()),
        "history counts must be positive and cover every positive return.",
    )
    _require(
        bool(
            np.isclose(
                probability,
                history_positive / history_count,
                rtol=0.0,
                atol=1e-12,
            ).all()
        ),
        "occurrence probability must equal positive returns divided by history count.",
    )
    _require(
        bool(((history_positive == 0) == (probability == 0.0)).all()),
        "zero historical positive support must agree with occurrence probability zero.",
    )
    _require(
        bool(
            (
                reference_positive[history_positive > 0] == history_positive[history_positive > 0]
            ).all()
        ),
        "a positive Phase 2H pool cannot use a different severity reference.",
    )
    zero_history = history_positive == 0
    _require(
        bool(
            np.logical_or(
                reference_positive[zero_history] == 0,
                reference_positive[zero_history] >= MIN_POSITIVE_RETURNS,
            ).all()
        ),
        "a zero-positive Phase 2H pool needs a five-return fallback or no fallback.",
    )
    has_reference = reference_positive > 0
    _require(
        bool(np.isfinite(positive_mean[has_reference]).all())
        and bool((positive_mean[has_reference] > 0.0).all()),
        "a positive severity reference needs a finite positive mean.",
    )
    _require(
        bool(np.isnan(positive_mean[~has_reference]).all()),
        "positive_mean must be missing when no severity reference exists.",
    )

    arithmetic_available = has_reference
    expected_history_mean = probability[arithmetic_available] * positive_mean[arithmetic_available]
    _require(
        bool(
            np.isclose(
                history_mean[arithmetic_available],
                expected_history_mean,
                rtol=0.0,
                atol=IDENTITY_TOLERANCE,
            ).all()
        ),
        "occurrence probability and positive mean do not reproduce the Phase 2H mean.",
    )
    _require(
        bool(np.isclose(history_mean[zero_history], 0.0, rtol=0.0, atol=IDENTITY_TOLERANCE).all()),
        "a zero-positive Phase 2H pool must have historical mean zero.",
    )

    supported = np.logical_or(
        history_positive >= MIN_POSITIVE_RETURNS,
        np.logical_and(zero_history, reference_positive >= MIN_POSITIVE_RETURNS),
    )
    occurred = attacking > 0.0
    occurrence = np.full(len(frame), np.nan, dtype="float64")
    severity = np.full(len(frame), np.nan, dtype="float64")
    occurrence[arithmetic_available] = (
        weights[arithmetic_available]
        * (occurred[arithmetic_available].astype("float64") - probability[arithmetic_available])
        * positive_mean[arithmetic_available]
    )
    severity[arithmetic_available] = (
        weights[arithmetic_available]
        * occurred[arithmetic_available].astype("float64")
        * (attacking[arithmetic_available] - positive_mean[arithmetic_available])
    )
    attacking_surprise = weights * (attacking - history_mean)
    identity_error = occurrence + severity - attacking_surprise
    _require(
        bool(
            np.isclose(
                identity_error[arithmetic_available],
                0.0,
                rtol=0.0,
                atol=IDENTITY_TOLERANCE,
            ).all()
        ),
        "occurrence and severity do not reproduce attacking surprise.",
    )

    frame["return_occurred"] = occurred.astype("int64")
    frame["carrier_supported"] = supported
    frame["occurrence_surprise"] = occurrence
    frame["severity_surprise"] = severity
    frame["attacking_surprise"] = attacking_surprise
    frame["identity_error"] = identity_error
    # These aliases are the deliberately small hand-off to the fold aggregator. Scores
    # are already captain-weighted here; a starter remains one row.
    frame["target_positive"] = frame["return_occurred"]
    frame["supported"] = frame["carrier_supported"]
    frame["occurrence"] = frame["occurrence_surprise"]
    frame["severity"] = frame["severity_surprise"]
    return frame


def build_fold_reading(
    player_rows: pd.DataFrame,
    control_realized_score: float,
    lower_quantile_score: float,
    control_below_q10: bool,
) -> dict[str, object]:
    """Aggregate one selected XI and read its two fixed counterfactuals."""

    _require(
        np.isfinite(control_realized_score) and np.isfinite(lower_quantile_score),
        "fold scores must be finite.",
    )
    _require(isinstance(control_below_q10, bool), "control_below_q10 must be boolean.")
    _require(isinstance(player_rows, pd.DataFrame), "player rows must be a DataFrame.")
    missing = sorted(_FOLD_PLAYER_COLUMNS - set(player_rows.columns))
    _require(not missing, f"fold player rows are missing columns {missing!r}.")
    parts = player_rows.copy(deep=True)
    _require(
        not bool(parts[["fold_id", "season", "player_id"]].isna().any().any()),
        "fold player identities must be complete.",
    )
    _require(
        not bool(parts.duplicated(["fold_id", "player_id"]).any()),
        "a fold repeats a selected player.",
    )
    _require(parts["fold_id"].nunique() == 1, "a fold reading expects exactly one fold.")
    _require(parts["season"].nunique() == 1, "a fold reading expects exactly one season.")
    _require(len(parts) == 11, "a fold reading requires eleven selected starters.")
    _require(
        control_below_q10 == bool(control_realized_score < lower_quantile_score),
        "control_below_q10 disagrees with the strict q10 event.",
    )
    support = _integer_counts(parts["supported"], "supported")
    _require(bool(support.isin((0, 1)).all()), "supported must contain zero or one.")
    eligible = bool(support.all())
    for column in ("occurrence", "severity", "attacking_surprise"):
        numbers = pd.to_numeric(parts[column], errors="coerce").to_numpy(dtype="float64")
        if eligible or column == "attacking_surprise":
            _require(bool(np.isfinite(numbers).all()), f"{column} must be finite.")
    occurrence = float(parts["occurrence"].sum()) if eligible else float("nan")
    severity = float(parts["severity"].sum()) if eligible else float("nan")
    attacking = float(parts["attacking_surprise"].sum())
    identity_error = occurrence + severity - attacking if eligible else float("nan")
    if eligible:
        _require(
            abs(identity_error) <= IDENTITY_TOLERANCE,
            "the fold occurrence/severity identity does not close.",
        )

    def counterfactual(part: float) -> tuple[float, bool, int]:
        if not eligible:
            return float("nan"), False, 0
        score = control_realized_score - part
        tail = bool(score < lower_quantile_score)
        return score, tail, int(control_below_q10) - int(tail)

    occurrence_score, occurrence_tail, occurrence_reduction = counterfactual(occurrence)
    severity_score, severity_tail, severity_reduction = counterfactual(severity)
    returns = _integer_counts(parts["target_positive"], "target_positive")
    _require(bool(returns.isin((0, 1)).all()), "target_positive must contain zero or one.")
    return {
        "fold_id": str(parts["fold_id"].iloc[0]),
        "season": str(parts["season"].iloc[0]),
        "eligible": eligible,
        "selected_starters": len(parts),
        "supported_starters": int(support.sum()),
        "positive_target_returns": int(returns.sum()),
        "zero_target_returns": int(len(returns) - returns.sum()),
        "control_realized_score": float(control_realized_score),
        "lower_quantile_score": float(lower_quantile_score),
        "control_below_q10": control_below_q10,
        "occurrence_surprise": occurrence,
        "severity_surprise": severity,
        "attacking_surprise": attacking,
        "identity_error": identity_error,
        "occurrence_counterfactual_score": occurrence_score,
        "severity_counterfactual_score": severity_score,
        "occurrence_below_q10": occurrence_tail if eligible else None,
        "severity_below_q10": severity_tail if eligible else None,
        "occurrence_reduction": occurrence_reduction if eligible else None,
        "severity_reduction": severity_reduction if eligible else None,
    }


def _interval(values: Sequence[float]) -> dict[str, float]:
    low, high = bootstrap_interval(
        values,
        resamples=BOOTSTRAP_RESAMPLES,
        seed=BOOTSTRAP_SEED,
        confidence_level=CONFIDENCE_LEVEL,
    )
    return {"mean": float(np.mean(values)), "bootstrap_low": low, "bootstrap_high": high}


def _contrast(values: np.ndarray, tail: np.ndarray) -> dict[str, float]:
    _require(bool(tail.any()) and bool((~tail).any()), "a contrast needs tail and non-tail folds.")
    generator = np.random.default_rng(BOOTSTRAP_SEED)
    draws = generator.integers(0, len(values), size=(BOOTSTRAP_RESAMPLES, len(values)))
    samples: list[float] = []
    for draw in draws:
        sampled_tail = tail[draw]
        if bool(sampled_tail.any()) and bool((~sampled_tail).any()):
            sampled = values[draw]
            samples.append(float(sampled[sampled_tail].mean() - sampled[~sampled_tail].mean()))
    _require(bool(samples), "the contrast bootstrap produced no valid draws.")
    alpha = (1.0 - CONFIDENCE_LEVEL) / 2.0
    low, high = np.quantile(np.asarray(samples), [alpha, 1.0 - alpha])
    return {
        "mean": float(values[tail].mean() - values[~tail].mean()),
        "bootstrap_low": float(low),
        "bootstrap_high": float(high),
    }


def summarise(fold_readings: pd.DataFrame) -> dict[str, object]:
    """Summarise eligible folds without treating starters as independent observations."""

    _require(isinstance(fold_readings, pd.DataFrame), "fold readings must be a DataFrame.")
    missing = sorted(_FOLD_COLUMNS - set(fold_readings.columns))
    _require(not missing, f"fold readings are missing columns {missing!r}.")
    _require(not fold_readings.empty, "fold readings are empty.")
    frame = fold_readings.copy(deep=True)
    _require(frame["fold_id"].is_unique, "fold readings repeat a fold.")
    _require(frame["season"].nunique() == 1, "summarise expects exactly one season.")
    _require(
        bool(frame["eligible"].map(lambda value: isinstance(value, (bool, np.bool_))).all()),
        "eligible must contain booleans.",
    )
    _require(
        bool(
            frame["control_below_q10"].map(lambda value: isinstance(value, (bool, np.bool_))).all()
        ),
        "control_below_q10 must contain booleans.",
    )
    eligible_mask = frame["eligible"].eq(True)
    eligible = frame.loc[eligible_mask].copy()
    identity = pd.to_numeric(eligible["identity_error"], errors="coerce").to_numpy(dtype="float64")
    _require(
        bool(np.isfinite(identity).all()) and bool((np.abs(identity) <= IDENTITY_TOLERANCE).all()),
        "an eligible fold has an invalid decomposition identity.",
    )
    tail = eligible["control_below_q10"].astype(bool).to_numpy()
    has_groups = bool(len(eligible)) and bool(tail.any()) and bool((~tail).any())
    parts: dict[str, object] = {}
    for part in _PARTS:
        surprise = pd.to_numeric(eligible[f"{part}_surprise"], errors="coerce").to_numpy(
            dtype="float64"
        )
        reduction = pd.to_numeric(eligible[f"{part}_reduction"], errors="coerce").to_numpy(
            dtype="float64"
        )
        _require(
            bool(np.isfinite(surprise).all()) and bool(np.isfinite(reduction).all()),
            f"eligible {part} readings must be finite.",
        )
        _require(
            bool(np.isin(reduction, (-1.0, 0.0, 1.0)).all()),
            f"eligible {part} reductions must be minus one, zero or one.",
        )
        parts[part] = (
            {
                "tail_minus_other_surprise": _contrast(surprise, tail),
                "q10_failure_reduction": _interval([float(value) for value in reduction]),
            }
            if has_groups
            else None
        )
    return {
        "parts": parts,
        "support": {
            "folds": int(frame["fold_id"].nunique()),
            "eligible_folds": len(eligible),
            "tail_folds": int(tail.sum()),
            "non_tail_folds": int(len(tail) - tail.sum()),
            "positive_target_returns": int(eligible["positive_target_returns"].sum()),
            "zero_target_returns": int(eligible["zero_target_returns"].sum()),
        },
        "maximum_absolute_identity_error": (
            float(np.abs(identity).max()) if len(identity) else None
        ),
    }


def _part(summary: Mapping[str, object], name: str) -> Mapping[str, object]:
    parts = cast(Mapping[str, object], summary["parts"])
    value = parts[name]
    if not isinstance(value, Mapping):
        raise TypeError(f"part {name!r} is unavailable")
    return cast(Mapping[str, object], value)


def _supported(summary: Mapping[str, object]) -> bool:
    support = cast(Mapping[str, object], summary["support"])
    identity = summary["maximum_absolute_identity_error"]
    return bool(
        int(cast(int, support["eligible_folds"])) >= MIN_EVALUATION_FOLDS
        and int(cast(int, support["tail_folds"])) > 0
        and int(cast(int, support["non_tail_folds"])) > 0
        and int(cast(int, support["positive_target_returns"])) > 0
        and int(cast(int, support["zero_target_returns"])) > 0
        and identity is not None
        and float(cast(float, identity)) <= IDENTITY_TOLERANCE
    )


def classify(validation: Mapping[str, object], sensitivity: Mapping[str, object]) -> str:
    """Apply the frozen occurrence/severity carrier gates."""

    try:
        if not _supported(validation) or not _supported(sensitivity):
            return INCONCLUSIVE

        def passes(name: str) -> bool:
            validation_part = _part(validation, name)
            sensitivity_part = _part(sensitivity, name)
            validation_contrast = cast(
                Mapping[str, float], validation_part["tail_minus_other_surprise"]
            )
            validation_reduction = cast(
                Mapping[str, float], validation_part["q10_failure_reduction"]
            )
            sensitivity_contrast = cast(
                Mapping[str, float], sensitivity_part["tail_minus_other_surprise"]
            )
            sensitivity_reduction = cast(
                Mapping[str, float], sensitivity_part["q10_failure_reduction"]
            )
            readings = (
                float(validation_contrast["bootstrap_high"]),
                float(validation_reduction["bootstrap_low"]),
                float(sensitivity_contrast["mean"]),
                float(sensitivity_reduction["mean"]),
            )
            if not all(np.isfinite(readings)):
                raise ValueError("a carrier gate reading is not finite")
            return bool(
                readings[0] < 0.0
                and readings[1] > 0.0
                and readings[2] <= 0.0
                and readings[3] >= 0.0
            )

        occurrence = passes("occurrence")
        severity = passes("severity")
    except (KeyError, TypeError, ValueError, OverflowError):
        return INCONCLUSIVE
    if occurrence and severity:
        return SHARED_HURDLE_FAILURE
    if occurrence:
        return OCCURRENCE_CARRIER
    if severity:
        return POSITIVE_SEVERITY_CARRIER
    return NOT_LOCALIZED


__all__ = [
    "CONTRACT_VERSION",
    "INCONCLUSIVE",
    "NOT_LOCALIZED",
    "OCCURRENCE_CARRIER",
    "POSITIVE_SEVERITY_CARRIER",
    "SHARED_HURDLE_FAILURE",
    "AttackingHurdleError",
    "build_fold_reading",
    "classify",
    "decompose_player_rows",
    "summarise",
]
