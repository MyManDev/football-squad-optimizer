"""Where the level of the points forecast is off, read over the development folds.

The protocol is ``docs/projection_level_audit_prereg.md``. This module is the arithmetic and
holds no file access: it is handed one table of out-of-fold rows, each with the forecast the
live system would have used, the outcome, the two components the forecast was composed from,
and what the player had been playing before the decision. It returns plain numbers.

A level error has two possible sources and they are repaired differently, so every block says
both: **who plays** (the forecast of an appearance summed against the appearances) and **what
they score when they play** (the conditional forecast against the points of those who appeared).
Intervals resample decisions, never players: players inside one decision share fixtures.
"""

from collections.abc import Callable
from typing import Final

import numpy as np
import pandas as pd

from squadopt.evaluation.live_projection_audit import (
    POSITIONS,
    PRIOR_MINUTES_BUCKETS,
    TOP_PER_POSITION,
)

PROJECTION_LEVEL_AUDIT_CONTRACT_VERSION: Final = "projection_level_audit_v1"

#: Fixed bands of the forecast itself: squad filler, rotation, a starter, a premium pick.
FORECAST_BANDS: Final[tuple[tuple[str, float, float], ...]] = (
    ("under_1.0", 0.0, 1.0),
    ("1.0_to_2.5", 1.0, 2.5),
    ("2.5_to_4.0", 2.5, 4.0),
    ("4.0_and_above", 4.0, float("inf")),
)
#: The first target gameweek read, so that three gameweeks stand behind every prior.
FIRST_TARGET_GAMEWEEK: Final = 4
INTERVAL_LEVEL: Final = 0.90
BOOTSTRAP_RESAMPLES: Final = 2000
BOOTSTRAP_SEED: Final = 0

LEVEL_COLUMNS: Final[tuple[str, ...]] = (
    "season",
    "fold_id",
    "player_id",
    "position",
    "forecast",
    "realized",
    "appearance_forecast",
    "appeared",
    "conditional_forecast",
    "prior_minutes_per_week",
)


class ProjectionLevelAuditError(ValueError):
    """The audit was handed a table it cannot read."""


def _validated(frame: pd.DataFrame) -> pd.DataFrame:
    missing = [column for column in LEVEL_COLUMNS if column not in frame.columns]
    if missing:
        raise ProjectionLevelAuditError(f"The level table lacks {missing!r}.")
    if frame.duplicated(["fold_id", "player_id"]).any():
        raise ProjectionLevelAuditError("A player appears twice in one decision.")
    if frame["forecast"].isna().any() or frame["realized"].isna().any():
        raise ProjectionLevelAuditError("Every row needs a forecast and an outcome.")
    return frame


def _interval(
    per_fold_error: pd.Series, per_fold_rows: pd.Series, folds: np.ndarray
) -> list[float] | None:
    """The bias interval by resampling decisions; a ratio of sums, so big folds weigh more."""

    errors = per_fold_error.reindex(folds, fill_value=0.0).to_numpy(dtype=float)
    rows = per_fold_rows.reindex(folds, fill_value=0).to_numpy(dtype=float)
    if len(folds) < 2 or rows.sum() == 0:
        return None
    generator = np.random.default_rng(BOOTSTRAP_SEED)
    draws = generator.integers(0, len(folds), size=(BOOTSTRAP_RESAMPLES, len(folds)))
    totals = rows[draws].sum(axis=1)
    kept = totals > 0
    if not kept.any():
        return None
    biases = errors[draws].sum(axis=1)[kept] / totals[kept]
    tail = (1.0 - INTERVAL_LEVEL) / 2.0
    low, high = np.quantile(biases, [tail, 1.0 - tail])
    return [float(low), float(high)]


def level_block(rows: pd.DataFrame, folds: np.ndarray) -> dict[str, object]:
    """One bucket: the level of the forecast, its interval, and the two components beside it.

    ``folds`` is every decision of the reading, not only those with a row in this bucket: a
    decision that put nobody in the bucket is a decision, and leaving it out of the resampling
    would narrow the interval.
    """

    if rows.empty:
        return {"rows": 0}
    error = rows["realized"] - rows["forecast"]
    block: dict[str, object] = {
        "rows": len(rows),
        "decisions": int(rows["fold_id"].nunique()),
        "forecast_points": float(rows["forecast"].sum()),
        "realized_points": float(rows["realized"].sum()),
        "bias": float(error.mean()),
        "bias_interval": _interval(
            error.groupby(rows["fold_id"]).sum(), rows.groupby("fold_id").size(), folds
        ),
        "mean_absolute_error": float(error.abs().mean()),
    }
    # The components exist on the component route only; a direct-control row has neither,
    # and absent is not zero.
    composed = rows.loc[rows["appearance_forecast"].notna() & rows["appeared"].notna()]
    if composed.empty:
        block["who_plays"] = {"rows": 0}
        block["what_they_score_when_they_play"] = {"rows": 0}
        return block
    gap = composed["appeared"].astype(float) - composed["appearance_forecast"]
    block["who_plays"] = {
        "rows": len(composed),
        "forecast_appearances": float(composed["appearance_forecast"].sum()),
        "appearances": float(composed["appeared"].astype(float).sum()),
        "bias": float(gap.mean()),
        "bias_interval": _interval(
            gap.groupby(composed["fold_id"]).sum(), composed.groupby("fold_id").size(), folds
        ),
    }
    played = composed.loc[(composed["appeared"] == 1) & composed["conditional_forecast"].notna()]
    if played.empty:
        block["what_they_score_when_they_play"] = {"rows": 0}
        return block
    conditional = played["realized"] - played["conditional_forecast"]
    block["what_they_score_when_they_play"] = {
        "rows": len(played),
        "mean_forecast": float(played["conditional_forecast"].mean()),
        "mean_realized": float(played["realized"].mean()),
        "bias": float(conditional.mean()),
        "bias_interval": _interval(
            conditional.groupby(played["fold_id"]).sum(), played.groupby("fold_id").size(), folds
        ),
    }
    return block


def _prior_bucket(low: float, high: float) -> Callable[[pd.Series], pd.Series]:
    if high == 0.0:
        return lambda prior: prior == 0
    return lambda prior: (prior > 0) & (prior >= low) & (prior < high)


def _top(frame: pd.DataFrame) -> pd.DataFrame:
    ranked = frame.sort_values(["forecast", "player_id"], ascending=[False, True])
    return ranked.groupby(["fold_id", "position"], sort=True).head(TOP_PER_POSITION)


def _reading(frame: pd.DataFrame) -> dict[str, object]:
    folds = np.sort(frame["fold_id"].unique())
    known = frame.loc[frame["prior_minutes_per_week"].notna()]
    top = _top(frame)
    return {
        "rows": len(frame),
        "decisions": len(folds),
        "rows_without_a_prior": len(frame) - len(known),
        "all": level_block(frame, folds),
        "by_prior_minutes": {
            label: level_block(
                known.loc[_prior_bucket(low, high)(known["prior_minutes_per_week"])], folds
            )
            for label, low, high in PRIOR_MINUTES_BUCKETS
        },
        "by_forecast_size": {
            label: level_block(
                frame.loc[(frame["forecast"] >= low) & (frame["forecast"] < high)], folds
            )
            for label, low, high in FORECAST_BANDS
        },
        "top_per_position": {
            "all": level_block(top, folds),
            **{
                position: level_block(top.loc[top["position"] == position], folds)
                for position in POSITIONS
            },
        },
    }


def summarise_level(frame: pd.DataFrame) -> dict[str, object]:
    """The protocol's readings, pooled and for each season."""

    table = _validated(frame)
    if table.empty:
        raise ProjectionLevelAuditError("The level table is empty.")
    return {
        "pooled": _reading(table),
        "by_season": {
            str(season): _reading(rows) for season, rows in table.groupby("season", sort=True)
        },
    }


def sign_agreement(summary: dict[str, object], split: str, bucket: str) -> dict[str, object]:
    """What stage two asks of a bucket: a pooled interval off zero, and the seasons' signs."""

    def bias_of(reading: object) -> tuple[float | None, list[float] | None]:
        assert isinstance(reading, dict)
        block = reading[split][bucket]
        if not block.get("rows"):
            return None, None
        return block["bias"], block["bias_interval"]

    pooled_bias, interval = bias_of(summary["pooled"])
    seasons = summary["by_season"]
    assert isinstance(seasons, dict)
    signs = [bias for bias, _ in (bias_of(reading) for reading in seasons.values()) if bias]
    excludes_zero = interval is not None and (interval[0] > 0 or interval[1] < 0)
    same = (
        sum(1 for bias in signs if (bias > 0) == (pooled_bias > 0))
        if pooled_bias is not None
        else 0
    )
    return {
        "pooled_bias": pooled_bias,
        "pooled_interval": interval,
        "pooled_interval_excludes_zero": excludes_zero,
        "seasons_with_the_pooled_sign": same,
        "seasons_read": len(signs),
        "opens_a_candidate": bool(excludes_zero and same >= 3),
    }
