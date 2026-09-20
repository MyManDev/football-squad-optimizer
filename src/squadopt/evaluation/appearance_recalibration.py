"""The single preregistered, prior-decision-only appearance recalibration.

This module accepts already verified development rows. It neither loads data nor
changes any production prediction contract.
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression  # type: ignore[import-untyped]

CONTRACT_VERSION = "appearance_recalibration_v1"
DECISION_SEASONS = ("2021-22", "2022-23", "2023-24", "2024-25")
MINIMUM_DECISIONS = 8
MINIMUM_ROWS = 200


@dataclass(frozen=True)
class RecalibrationResult:
    probabilities: pd.Series
    points: pd.Series
    eligible: pd.Series
    training_counts: pd.DataFrame


def recalibrate_appearance(rows: pd.DataFrame) -> RecalibrationResult:
    """Predict a whole decision before admitting any of its observed labels.

    Warm-up, direct-control and blank rows retain their input forecasts exactly.
    The caller's handoff reader verifies full keys and source chronology; this
    boundary additionally refuses reordering, repeated keys and holdout rows.
    """
    required = {
        "season",
        "fold_id",
        "player_id",
        "fixture_count",
        "composition_route",
        "appearance_probability",
        "appearance_target",
        "expected_points_if_appearance",
        "control_expected_points",
    }
    if required - set(rows) or rows.empty or not rows.index.is_unique:
        raise ValueError("Calibration requires nonempty, uniquely indexed contract rows.")
    if not set(rows["season"]).issubset(DECISION_SEASONS):
        raise ValueError("Calibration admits only the four frozen development seasons.")
    if rows.duplicated(["fold_id", "player_id"]).any():
        raise ValueError("Calibration keys must be unique.")
    order = rows["fold_id"].drop_duplicates().tolist()
    if order != sorted(order) or rows["fold_id"].tolist() != sorted(rows["fold_id"].tolist()):
        raise ValueError("Decisions must be contiguous and chronological.")
    if not rows["fold_id"].str[:7].eq(rows["season"]).all():
        raise ValueError("Decision and season identities disagree.")
    if not rows["composition_route"].isin(["component_model", "direct_control"]).all():
        raise ValueError("Calibration admits only the frozen composition routes.")
    fixtures = rows["fixture_count"].astype(float)
    if not np.isfinite(fixtures).all() or fixtures.lt(0).any() or fixtures.mod(1).ne(0).any():
        raise ValueError("Fixture counts must be finite non-negative integers.")
    blank = fixtures.eq(0)
    if not rows.loc[blank, "control_expected_points"].eq(0).all():
        raise ValueError("Blank rows must retain zero forecast points.")
    component = rows["composition_route"].eq("component_model")
    eligible = component & rows["fixture_count"].gt(0)
    numeric = rows.loc[
        eligible,
        [
            "appearance_probability",
            "appearance_target",
            "expected_points_if_appearance",
            "control_expected_points",
        ],
    ].astype(float)
    if (
        not np.isfinite(numeric.to_numpy()).all()
        or not numeric["appearance_probability"].between(0, 1).all()
        or not numeric["appearance_target"].isin([0, 1]).all()
    ):
        raise ValueError("An eligible component row violates its numeric contract.")
    probabilities = rows["appearance_probability"].astype(float).copy()
    points = rows["control_expected_points"].astype(float).copy()
    history_p: list[float] = []
    history_y: list[float] = []
    earlier_decisions = 0
    counts: list[dict[str, object]] = []
    for fold_id in order:
        held = eligible & rows["fold_id"].eq(fold_id)
        fitted = (
            earlier_decisions >= MINIMUM_DECISIONS
            and len(history_p) >= MINIMUM_ROWS
            and len(set(history_y)) == 2
        )
        counts.append(
            {
                "fold_id": fold_id,
                "earlier_decisions": earlier_decisions,
                "earlier_rows": len(history_p),
                "eligible_rows": int(held.sum()),
                "fitted": fitted,
            }
        )
        if fitted and held.any():
            calibrator = IsotonicRegression(y_min=0, y_max=1, out_of_bounds="clip")
            calibrator.fit(history_p, history_y)
            probabilities.loc[held] = calibrator.predict(probabilities.loc[held].to_numpy())
            points.loc[held] = (
                probabilities.loc[held] * rows.loc[held, "expected_points_if_appearance"]
            )
        # Deliberately after prediction, including all players in the current block.
        if held.any():
            history_p.extend(rows.loc[held, "appearance_probability"].astype(float).tolist())
            history_y.extend(rows.loc[held, "appearance_target"].astype(float).tolist())
            earlier_decisions += 1
    return RecalibrationResult(probabilities, points, eligible, pd.DataFrame(counts))


def reliability(probability: pd.Series, target: pd.Series) -> dict[str, object]:
    """Fixed ten bins; empty bins have unavailable means, never invented zeros."""
    if not probability.index.equals(target.index):
        raise ValueError("Reliability observations must share exact indices.")
    if (
        not np.isfinite(probability.to_numpy()).all()
        or not probability.between(0, 1).all()
        or not target.isin([0, 1]).all()
    ):
        raise ValueError("Reliability requires probabilities and observed binary targets.")
    bins = np.minimum((probability * 10).astype(int), 9)
    readings = []
    for number in range(10):
        held = bins == number
        count = int(held.sum())
        readings.append(
            {
                "lower": number / 10,
                "upper": (number + 1) / 10,
                "rows": count,
                "mean_prediction": float(probability[held].mean()) if count else None,
                "observed_appearance": float(target[held].mean()) if count else None,
            }
        )
    return {
        "rows": len(probability),
        "brier": float(((probability - target) ** 2).mean()) if len(probability) else None,
        "bins": readings,
    }
