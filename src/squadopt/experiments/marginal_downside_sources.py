"""Attribute selected-starter marginal downside to minutes and omitted location."""

from collections.abc import Mapping, Sequence
from typing import Final

import numpy as np
import pandas as pd

from squadopt.experiments.shadow_calibration import (
    BOOTSTRAP_SEED,
    CONFIDENCE_LEVEL,
    bootstrap_interval,
)
from squadopt.experiments.shadow_squad_calibration import (
    BOOTSTRAP_RESAMPLES,
    MIN_EVALUATION_FOLDS,
    SquadShadowError,
    _require,
)

MARGINAL_SOURCES_CONTRACT_VERSION: Final = "phase2_marginal_downside_sources_v1"

NO_APPEARANCE: Final = "minutes_0"
PARTIAL_APPEARANCE: Final = "minutes_1_59"
FULL_APPEARANCE: Final = "minutes_60_plus"
MINUTE_BUCKETS: Final = (NO_APPEARANCE, PARTIAL_APPEARANCE, FULL_APPEARANCE)

APPEARANCE_DOMINANT: Final = "appearance_minutes_dominant"
FULL_APPEARANCE_DOMINANT: Final = "full_appearance_performance_dominant"
MIXED: Final = "marginal_sources_mixed"


def _minute_bucket(minutes: float) -> str:
    if minutes == 0.0:
        return NO_APPEARANCE
    return PARTIAL_APPEARANCE if minutes < 60.0 else FULL_APPEARANCE


def enrich_starters(
    starters: pd.DataFrame,
    panel: pd.DataFrame,
    residuals: pd.DataFrame,
    history_fold_ids: Sequence[str],
) -> pd.DataFrame:
    """Add post-outcome minutes and pre-fold player location to one XI's rows."""

    required = {
        "fold_id",
        "season",
        "gameweek",
        "player_id",
        "expected_points",
        "realized_points",
        "realized_residual",
        "scenario_downside_rate",
        "realized_downside",
    }
    _require(required.issubset(starters.columns), "starter downside rows are incomplete.")
    _require(len(starters) == 11, "one source reading requires eleven starters.")
    season = str(starters["season"].iloc[0])
    gameweek = int(starters["gameweek"].iloc[0])
    _require(
        bool(starters["season"].astype(str).eq(season).all())
        and bool(starters["gameweek"].astype(int).eq(gameweek).all()),
        "starter rows must describe one fold.",
    )

    outcome = panel.loc[
        panel["season"].astype(str).eq(season) & panel["gameweek"].astype(int).eq(gameweek),
        ["player_id", "minutes"],
    ]
    _require(
        bool(outcome["player_id"].is_unique),
        "panel outcomes repeat a player in one gameweek.",
    )
    merged = starters.merge(outcome, on="player_id", how="left", validate="one_to_one")
    _require(not merged["minutes"].isna().any(), "minutes are missing for a selected starter.")
    minutes = pd.to_numeric(merged["minutes"], errors="coerce").to_numpy(dtype="float64")
    _require(
        bool(np.isfinite(minutes).all()) and bool((minutes >= 0.0).all()),
        "starter minutes must be finite and non-negative.",
    )

    history = residuals.loc[residuals["fold_id"].astype(str).isin(set(history_fold_ids))]
    grouped = history.groupby("player_id", sort=False)["residual"]
    means = grouped.mean()
    counts = grouped.size()
    merged["prior_residual_count"] = merged["player_id"].map(counts).fillna(0).astype("int64")
    merged["omitted_player_location"] = merged["player_id"].map(means).astype("float64")
    merged["minutes"] = minutes
    merged["minute_bucket"] = [_minute_bucket(value) for value in minutes]
    merged["downside_excess"] = merged["realized_downside"].astype("float64") - merged[
        "scenario_downside_rate"
    ].astype("float64")
    return merged


def _bootstrap(values: Sequence[float]) -> dict[str, float]:
    _require(bool(values), "a fold summary needs at least one value.")
    low, high = bootstrap_interval(
        values,
        resamples=BOOTSTRAP_RESAMPLES,
        seed=BOOTSTRAP_SEED,
        confidence_level=CONFIDENCE_LEVEL,
    )
    return {"mean": float(np.mean(values)), "bootstrap_low": low, "bootstrap_high": high}


def _bucket_summary(frame: pd.DataFrame, bucket: str, total_excess: float) -> dict[str, object]:
    selected = frame.loc[frame["minute_bucket"] == bucket]
    fold_ids = tuple(frame["fold_id"].astype(str).drop_duplicates())
    contributions = selected.groupby("fold_id", sort=False)["downside_excess"].sum()
    per_fold = [float(contributions.get(fold_id, 0.0)) for fold_id in fold_ids]
    contribution = float(selected["downside_excess"].sum())
    rows = len(selected)
    return {
        "starter_rows": rows,
        "starter_share": rows / len(frame),
        "realized_downside_count": int(selected["realized_downside"].sum()),
        "scenario_expected_downside_count": float(selected["scenario_downside_rate"].sum()),
        "realized_downside_rate": (float(selected["realized_downside"].mean()) if rows else None),
        "scenario_expected_downside_rate": (
            float(selected["scenario_downside_rate"].mean()) if rows else None
        ),
        "excess_contribution": contribution,
        "positive_excess_share": contribution / total_excess if total_excess > 0.0 else None,
        "mean_excess_per_fold": _bootstrap(per_fold),
        "mean_expected_points": float(selected["expected_points"].mean()) if rows else None,
        "mean_realized_points": float(selected["realized_points"].mean()) if rows else None,
        "mean_realized_residual": float(selected["realized_residual"].mean()) if rows else None,
    }


def _location_summary(frame: pd.DataFrame) -> dict[str, object]:
    measured = frame.dropna(subset=["omitted_player_location"])
    if measured.empty:
        return {"measurable": False, "starter_rows": 0}
    locations = measured["omitted_player_location"].to_numpy(dtype="float64")
    residuals = measured["realized_residual"].to_numpy(dtype="float64")
    correlation = (
        float(np.corrcoef(locations, residuals)[0, 1])
        if locations.std() > 0.0 and residuals.std() > 0.0
        else None
    )

    def group(flag: bool) -> dict[str, float | int | None]:
        selected = measured.loc[measured["realized_downside"].astype(bool) == flag]
        return {
            "starter_rows": len(selected),
            "mean_omitted_location": (
                float(selected["omitted_player_location"].mean()) if len(selected) else None
            ),
        }

    return {
        "measurable": True,
        "starter_rows": len(measured),
        "coverage": len(measured) / len(frame),
        "mean_omitted_location": float(locations.mean()),
        "negative_location_share": float((locations < 0.0).mean()),
        "pearson_correlation_with_realized_residual": correlation,
        "on_realized_downside": group(True),
        "elsewhere": group(False),
    }


def summarise(frame: pd.DataFrame) -> dict[str, object]:
    """Return the pre-registered bucket accounting for one fold population."""

    _require(not frame.empty, "a marginal source summary needs starter rows.")
    _require(
        set(frame["minute_bucket"]).issubset(MINUTE_BUCKETS),
        "starter rows carry an undeclared minute bucket.",
    )
    total_excess = float(frame["downside_excess"].sum())
    return {
        "fold_count": int(frame["fold_id"].nunique()),
        "starter_rows": len(frame),
        "total_downside_excess": total_excess,
        "minute_buckets": {
            bucket: _bucket_summary(frame, bucket, total_excess) for bucket in MINUTE_BUCKETS
        },
        "omitted_player_location": _location_summary(frame),
    }


def classify(summary: Mapping[str, object]) -> str:
    """Classify validation by which minute side contributes more excess downside."""

    fold_count = summary.get("fold_count")
    buckets = summary.get("minute_buckets")
    if type(fold_count) is not int or fold_count < MIN_EVALUATION_FOLDS:
        return MIXED
    if not isinstance(buckets, Mapping) or any(bucket not in buckets for bucket in MINUTE_BUCKETS):
        return MIXED

    def contribution(bucket: str) -> float:
        value = buckets[bucket]
        if not isinstance(value, Mapping):
            raise SquadShadowError(f"minute bucket {bucket!r} has no summary.")
        return float(value["excess_contribution"])

    low_minutes = contribution(NO_APPEARANCE) + contribution(PARTIAL_APPEARANCE)
    full_minutes = contribution(FULL_APPEARANCE)
    if low_minutes > 0.0 and low_minutes > full_minutes:
        return APPEARANCE_DOMINANT
    if full_minutes > 0.0 and full_minutes >= low_minutes:
        return FULL_APPEARANCE_DOMINANT
    return MIXED
