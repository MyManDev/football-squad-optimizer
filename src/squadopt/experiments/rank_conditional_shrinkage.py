"""Rank-conditional shrinkage of expected points before the squad decision.

Pre-registered in ``docs/research/rank_conditional_shrinkage_prereg.md`` before this module
was written. The arithmetic of the two candidate arms lives here, pure and without file IO,
so the property tests have something exact to stand on; the runner that feeds it is
``scripts/measure_rank_conditional_shrinkage.py``.

**The residual frame.** Every function reads one frame with the columns ``fold_id``,
``player_id``, ``position``, ``projected`` and ``realized``. ``projected`` is the optimizer's
``expected_points`` as the harness composes it; ``realized`` is the player's official points
in the fold, zero on a blank (:func:`realized_points`). Nothing here knows how either was
produced.

**Arm A** (:func:`fit_rank_debias`, :func:`apply_rank_debias`). Within each history fold the
players are ranked by ``projected`` descending, ties by ``player_id`` ascending, and placed in
the frozen rank buckets. The correction of a bucket is the mean residual (realized minus
projected) of its history rows, pooled across folds. In the target fold the candidate
projection is ``max(0, projected + correction(bucket of the player's rank in that fold))``.

**Arm B** (:func:`fit_position_shrinkage`, :func:`apply_position_shrinkage`). Per position an
ordinary least-squares slope of ``realized`` on ``projected`` over the history rows; the
candidate projection is ``max(0, m + lambda * (projected - m))`` with ``m`` the target fold's
mean projected points in that position.

**Walk-forward only.** A fit reads history rows and nothing else. The frame handed to a fit
is the caller's responsibility, and the tests hold that a target row with an absurd realized
value changes nothing.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final

import numpy as np
import pandas as pd

from squadopt.evaluation.promotion import ExperimentConfigurationError

CONTRACT_VERSION: Final = "rank_conditional_shrinkage_v1"

#: Folds strictly before a target that its fit needs; the first eight folds of the table are
#: burn-in and are never targets.
MIN_HISTORY_FOLDS: Final = 8

#: The upper edge (inclusive) of every bucket but the last; a rank above the last edge is in
#: the open bucket. Frozen by the protocol.
RANK_BUCKET_EDGES: Final[tuple[int, ...]] = (5, 15, 30, 60, 120)
RANK_BUCKET_LABELS: Final[tuple[str, ...]] = (
    "rank_001_005",
    "rank_006_015",
    "rank_016_030",
    "rank_031_060",
    "rank_061_120",
    "rank_121_plus",
)
POSITIONS: Final[tuple[str, ...]] = ("GK", "DEF", "MID", "FWD")
RESIDUAL_COLUMNS: Final[tuple[str, ...]] = (
    "fold_id",
    "player_id",
    "position",
    "projected",
    "realized",
)


class RankShrinkageError(ExperimentConfigurationError):
    """Raised when a frame or a history does not meet the protocol."""


@dataclass(frozen=True, slots=True)
class RankDebiasTable:
    """Arm A's fitted corrections: one additive term per rank bucket."""

    corrections: Mapping[str, float]
    rows_per_bucket: Mapping[str, int]
    history_folds: int
    contract_version: str = CONTRACT_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "corrections", MappingProxyType(dict(self.corrections)))
        object.__setattr__(self, "rows_per_bucket", MappingProxyType(dict(self.rows_per_bucket)))


@dataclass(frozen=True, slots=True)
class PositionShrinkageTable:
    """Arm B's fitted slopes: one least-squares slope and intercept per position."""

    slopes: Mapping[str, float]
    intercepts: Mapping[str, float]
    rows_per_position: Mapping[str, int]
    history_folds: int
    contract_version: str = CONTRACT_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "slopes", MappingProxyType(dict(self.slopes)))
        object.__setattr__(self, "intercepts", MappingProxyType(dict(self.intercepts)))
        object.__setattr__(
            self, "rows_per_position", MappingProxyType(dict(self.rows_per_position))
        )


def rank_bucket(rank: int) -> str:
    """The frozen bucket of a one-based projection rank."""

    if isinstance(rank, bool) or int(rank) != rank or rank < 1:
        raise RankShrinkageError(f"A rank is a positive integer; got {rank!r}.")
    for edge, label in zip(RANK_BUCKET_EDGES, RANK_BUCKET_LABELS, strict=False):
        if rank <= edge:
            return label
    return RANK_BUCKET_LABELS[-1]


def realized_points(appearance_target: pd.Series, points_target: pd.Series) -> pd.Series:
    """Official points in a fold: ``points_target`` on an appearance, zero on a blank."""

    appeared = pd.to_numeric(appearance_target, errors="coerce")
    if bool(appeared.isna().any()) or bool((~appeared.isin([0, 1])).any()):
        raise RankShrinkageError("appearance_target must be 0 or 1 on every row.")
    points = pd.to_numeric(points_target, errors="coerce").astype("float64")
    if bool(points[appeared.eq(1)].isna().any()):
        raise RankShrinkageError("points_target is required on every appearance.")
    return points.where(appeared.eq(1), 0.0).astype("float64")


def _validated(frame: pd.DataFrame, *, what: str) -> pd.DataFrame:
    missing = [column for column in RESIDUAL_COLUMNS if column not in frame.columns]
    if missing:
        raise RankShrinkageError(f"The {what} frame is missing columns {missing!r}.")
    if frame.empty:
        raise RankShrinkageError(f"The {what} frame is empty.")
    checked = frame.loc[:, list(RESIDUAL_COLUMNS)].copy(deep=True)
    for column in ("projected", "realized"):
        values = pd.to_numeric(checked[column], errors="coerce").astype("float64")
        if bool(values.isna().any()) or not bool(np.isfinite(values.to_numpy()).all()):
            raise RankShrinkageError(f"The {what} frame has a non-finite {column!r} value.")
        checked[column] = values
    checked["fold_id"] = checked["fold_id"].astype("string")
    checked["position"] = checked["position"].astype("string")
    unknown = sorted(set(checked["position"].dropna().unique()) - set(POSITIONS))
    if unknown or bool(checked["position"].isna().any()):
        raise RankShrinkageError(f"The {what} frame has positions outside {POSITIONS!r}.")
    duplicated = checked.duplicated(["fold_id", "player_id"])
    if bool(duplicated.any()):
        raise RankShrinkageError(f"The {what} frame repeats a player within a fold.")
    return checked


def projection_ranks(frame: pd.DataFrame) -> pd.Series:
    """One-based ranks within each fold: ``projected`` descending, ties by ``player_id``."""

    checked = _validated(frame, what="ranked")
    ordered = checked.sort_values(
        ["fold_id", "projected", "player_id"], ascending=[True, False, True], kind="stable"
    )
    ranks = ordered.groupby("fold_id", sort=False).cumcount() + 1
    return ranks.reindex(frame.index).astype("int64")


def _bucket_labels(ranks: pd.Series) -> pd.Series:
    positions = np.searchsorted(np.asarray(RANK_BUCKET_EDGES), ranks.to_numpy(), side="left")
    return pd.Series(
        [RANK_BUCKET_LABELS[int(index)] for index in positions], index=ranks.index, dtype="string"
    )


def target_folds(fold_ids: Sequence[str]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Split fold ids into the burn-in and the targets, in fold-id order.

    A fold is a target when at least :data:`MIN_HISTORY_FOLDS` folds come strictly before
    it; the history of every target is every fold before it, burn-in included.
    """

    given = tuple(str(fold_id) for fold_id in fold_ids)
    ordered = tuple(sorted(set(given)))
    if len(ordered) != len(given):
        raise RankShrinkageError("Fold ids repeat.")
    return ordered[:MIN_HISTORY_FOLDS], ordered[MIN_HISTORY_FOLDS:]


def history_rows(frame: pd.DataFrame, target_fold_id: str) -> pd.DataFrame:
    """The rows of every fold strictly before ``target_fold_id`` in fold-id order."""

    checked = _validated(frame, what="residual")
    return checked.loc[checked["fold_id"] < str(target_fold_id)].reset_index(drop=True)


def _require_history(history: pd.DataFrame) -> int:
    folds = int(history["fold_id"].nunique())
    if folds < MIN_HISTORY_FOLDS:
        raise RankShrinkageError(
            f"A fit needs at least {MIN_HISTORY_FOLDS} history folds; got {folds}."
        )
    return folds


def fit_rank_debias(history: pd.DataFrame) -> RankDebiasTable:
    """Arm A: the mean residual of every rank bucket over the history rows."""

    checked = _validated(history, what="history")
    folds = _require_history(checked)
    buckets = _bucket_labels(projection_ranks(checked))
    residual = checked["realized"] - checked["projected"]
    grouped = residual.groupby(buckets, observed=True)
    means = grouped.mean()
    counts = grouped.size()
    corrections = {
        label: float(means[label]) if label in means.index else 0.0 for label in RANK_BUCKET_LABELS
    }
    rows = {
        label: int(counts[label]) if label in counts.index else 0 for label in RANK_BUCKET_LABELS
    }
    return RankDebiasTable(corrections=corrections, rows_per_bucket=rows, history_folds=folds)


def apply_rank_debias(fold: pd.DataFrame, table: RankDebiasTable) -> pd.Series:
    """Arm A on one target fold: ``max(0, projected + correction)``, indexed like ``fold``."""

    checked = _validated(fold, what="target")
    if int(checked["fold_id"].nunique()) != 1:
        raise RankShrinkageError("A target frame holds exactly one fold.")
    buckets = _bucket_labels(projection_ranks(checked))
    correction = buckets.map(dict(table.corrections)).astype("float64")
    adjusted = (checked["projected"] + correction).clip(lower=0.0)
    return adjusted.astype("float64").reindex(fold.index)


def fit_position_shrinkage(history: pd.DataFrame) -> PositionShrinkageTable:
    """Arm B: per position, the least-squares slope of realized on projected."""

    checked = _validated(history, what="history")
    folds = _require_history(checked)
    slopes: dict[str, float] = {}
    intercepts: dict[str, float] = {}
    rows: dict[str, int] = {}
    for position in POSITIONS:
        subset = checked.loc[checked["position"] == position]
        rows[position] = len(subset)
        if subset.empty:
            slopes[position] = 1.0
            intercepts[position] = 0.0
            continue
        projected = subset["projected"].to_numpy(dtype="float64")
        realized = subset["realized"].to_numpy(dtype="float64")
        variance = float(np.var(projected))
        if variance == 0.0:
            slope = 1.0
        else:
            centred = projected - projected.mean()
            slope = float(np.dot(centred, realized - realized.mean()) / np.dot(centred, centred))
        slopes[position] = slope
        intercepts[position] = float(realized.mean() - slope * projected.mean())
    return PositionShrinkageTable(
        slopes=slopes, intercepts=intercepts, rows_per_position=rows, history_folds=folds
    )


def apply_position_shrinkage(fold: pd.DataFrame, table: PositionShrinkageTable) -> pd.Series:
    """Arm B on one target fold: ``max(0, m_pos + lambda_pos * (projected - m_pos))``."""

    checked = _validated(fold, what="target")
    if int(checked["fold_id"].nunique()) != 1:
        raise RankShrinkageError("A target frame holds exactly one fold.")
    means = checked.groupby("position", observed=True)["projected"].transform("mean")
    slope = checked["position"].map(dict(table.slopes)).astype("float64")
    adjusted = (means + slope * (checked["projected"] - means)).clip(lower=0.0)
    return adjusted.astype("float64").reindex(fold.index)


__all__ = [
    "CONTRACT_VERSION",
    "MIN_HISTORY_FOLDS",
    "POSITIONS",
    "RANK_BUCKET_EDGES",
    "RANK_BUCKET_LABELS",
    "RESIDUAL_COLUMNS",
    "PositionShrinkageTable",
    "RankDebiasTable",
    "RankShrinkageError",
    "apply_position_shrinkage",
    "apply_rank_debias",
    "fit_position_shrinkage",
    "fit_rank_debias",
    "history_rows",
    "projection_ranks",
    "rank_bucket",
    "realized_points",
    "target_folds",
]
