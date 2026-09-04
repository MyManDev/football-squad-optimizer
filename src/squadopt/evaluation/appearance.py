"""Descriptive scoring for private Phase C appearance probabilities."""

import math
from dataclasses import dataclass
from numbers import Integral, Real
from typing import Final

import pandas as pd

from squadopt.evaluation.models import EvaluationValidationError
from squadopt.prediction import ComponentPredictionSnapshot

APPEARANCE_DIAGNOSTICS_VERSION: Final = "appearance_diagnostics_v1"
APPEARANCE_LOG_LOSS_EPSILON: Final = 1e-6
APPEARANCE_RELIABILITY_BIN_COUNT: Final = 10


@dataclass(frozen=True, slots=True)
class AppearanceReliabilityBin:
    """One fixed-width reliability-bin summary."""

    index: int
    lower_bound: float
    upper_bound: float
    observations: int
    mean_probability: float | None
    appearance_rate: float | None


@dataclass(frozen=True, slots=True)
class AppearanceDiagnostics:
    """Descriptive metrics with mutually exclusive exclusion counts.

    ``mean_calibration_bias`` is mean predicted probability minus the observed
    appearance rate, so a positive value means overprediction.
    """

    population_rows: int
    eligible_rows: int
    scored_rows: int
    missing_label_rows: int
    direct_control_rows: int
    blank_rows: int
    blank_appearance_violations: int
    probability_coverage: float | None
    brier_score: float | None
    log_loss: float | None
    mean_probability: float | None
    appearance_rate: float | None
    mean_calibration_bias: float | None
    reliability_bins: tuple[AppearanceReliabilityBin, ...]
    contract_version: str = APPEARANCE_DIAGNOSTICS_VERSION


def _outcomes(value: object, expected_ids: set[object]) -> pd.DataFrame:
    if not isinstance(value, pd.DataFrame):
        raise EvaluationValidationError("outcomes must be a pandas DataFrame.")
    duplicates = value.columns[value.columns.duplicated()].tolist()
    if duplicates:
        raise EvaluationValidationError(f"outcomes has duplicate columns: {duplicates[:10]!r}.")
    missing = [column for column in ("player_id", "minutes") if column not in value]
    if missing:
        raise EvaluationValidationError(f"outcomes is missing columns: {missing!r}.")
    frame = value.loc[:, ["player_id", "minutes"]].copy(deep=True)
    if bool(frame["player_id"].isna().any()):
        raise EvaluationValidationError("outcomes player_id must not be missing.")
    expected_integer_ids = all(
        isinstance(identifier, Integral) and not isinstance(identifier, bool)
        for identifier in expected_ids
    )
    invalid_ids = [
        identifier
        for identifier in frame["player_id"].tolist()
        if (
            isinstance(identifier, bool)
            or (expected_integer_ids and not isinstance(identifier, Integral))
            or (
                not expected_integer_ids
                and (not isinstance(identifier, str) or not identifier.strip())
            )
        )
    ]
    if invalid_ids:
        raise EvaluationValidationError(
            "outcomes player_id values must use the snapshot's ID representation."
        )
    repeated = frame.loc[frame["player_id"].duplicated(), "player_id"].tolist()
    if repeated:
        raise EvaluationValidationError(
            f"outcomes has repeated player_id values: {repeated[:10]!r}."
        )
    actual_ids = set(frame["player_id"].tolist())
    if actual_ids != expected_ids:
        raise EvaluationValidationError(
            "outcomes player_id values must match the component snapshot exactly."
        )
    invalid_minutes = [
        value
        for value in frame["minutes"].tolist()
        if not pd.isna(value) and (isinstance(value, bool) or not isinstance(value, Real))
    ]
    if invalid_minutes:
        raise EvaluationValidationError("outcomes minutes must be finite numbers or missing.")
    numeric = pd.to_numeric(frame["minutes"], errors="raise").astype("float64")
    if bool(numeric.dropna().map(lambda item: not math.isfinite(item)).any()):
        raise EvaluationValidationError("outcomes minutes must be finite numbers or missing.")
    if bool(numeric.dropna().lt(0.0).any()):
        raise EvaluationValidationError("outcomes minutes must not be negative.")
    frame["minutes"] = numeric
    return frame


def _reliability_bins(scored: pd.DataFrame) -> tuple[AppearanceReliabilityBin, ...]:
    bins: list[AppearanceReliabilityBin] = []
    indices = scored["appearance_probability"].mul(APPEARANCE_RELIABILITY_BIN_COUNT).astype(int)
    indices = indices.clip(upper=APPEARANCE_RELIABILITY_BIN_COUNT - 1)
    for index in range(APPEARANCE_RELIABILITY_BIN_COUNT):
        rows = scored.loc[indices == index]
        observations = len(rows)
        bins.append(
            AppearanceReliabilityBin(
                index=index,
                lower_bound=index / APPEARANCE_RELIABILITY_BIN_COUNT,
                upper_bound=(index + 1) / APPEARANCE_RELIABILITY_BIN_COUNT,
                observations=observations,
                mean_probability=(
                    None if rows.empty else float(rows["appearance_probability"].mean())
                ),
                appearance_rate=None if rows.empty else float(rows["appeared"].mean()),
            )
        )
    return tuple(bins)


def evaluate_appearance_snapshot(
    snapshot: ComponentPredictionSnapshot,
    outcomes: pd.DataFrame,
) -> AppearanceDiagnostics:
    """Score available appearance probabilities without making a promotion decision."""

    if not isinstance(snapshot, ComponentPredictionSnapshot):
        raise EvaluationValidationError("snapshot must be a ComponentPredictionSnapshot.")
    predictions = snapshot.validated_copy().table
    realized = _outcomes(outcomes, set(predictions["player_id"].tolist()))
    frame = predictions.merge(realized, on="player_id", how="inner", validate="one_to_one")

    blank = frame["fixture_count"].eq(0)
    missing_label = frame["minutes"].isna()
    missing_non_blank = ~blank & missing_label
    eligible = ~blank & ~missing_label
    scored_mask = eligible & frame["appearance_probability"].notna()
    direct_control = eligible & frame["composition_route"].eq("direct_control")
    blank_violation = blank & frame["minutes"].fillna(0.0).gt(0.0)
    scored = frame.loc[scored_mask].copy(deep=True)
    scored["appeared"] = scored["minutes"].gt(0.0).astype("float64")

    eligible_count = int(eligible.sum())
    scored_count = len(scored)
    coverage = None if eligible_count == 0 else scored_count / eligible_count
    if scored.empty:
        brier = log_loss = mean_probability = appearance_rate = calibration = None
    else:
        probability = scored["appearance_probability"].astype("float64")
        label = scored["appeared"]
        brier = float(probability.sub(label).pow(2).mean())
        clipped = probability.clip(
            lower=APPEARANCE_LOG_LOSS_EPSILON,
            upper=1.0 - APPEARANCE_LOG_LOSS_EPSILON,
        )
        log_loss = float(
            -(
                label.mul(clipped.map(math.log)) + (1.0 - label).mul((1.0 - clipped).map(math.log))
            ).mean()
        )
        mean_probability = float(probability.mean())
        appearance_rate = float(label.mean())
        calibration = mean_probability - appearance_rate

    return AppearanceDiagnostics(
        population_rows=len(frame),
        eligible_rows=eligible_count,
        scored_rows=scored_count,
        missing_label_rows=int(missing_non_blank.sum()),
        direct_control_rows=int(direct_control.sum()),
        blank_rows=int(blank.sum()),
        blank_appearance_violations=int(blank_violation.sum()),
        probability_coverage=coverage,
        brier_score=brier,
        log_loss=log_loss,
        mean_probability=mean_probability,
        appearance_rate=appearance_rate,
        mean_calibration_bias=calibration,
        reliability_bins=_reliability_bins(scored),
    )


__all__ = [
    "APPEARANCE_DIAGNOSTICS_VERSION",
    "APPEARANCE_LOG_LOSS_EPSILON",
    "APPEARANCE_RELIABILITY_BIN_COUNT",
    "AppearanceDiagnostics",
    "AppearanceReliabilityBin",
    "evaluate_appearance_snapshot",
]
