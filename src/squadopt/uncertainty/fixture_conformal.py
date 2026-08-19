"""Fixture-group conformal calibration: intervals that know a double gameweek is one.

The operational calibration (`projection_uncertainty_v1`) groups residuals by position
and applies one conformal radius per position. Its double gameweeks are undercovered
(0.83 and 0.80 measured against nominal 0.90, [issue38_calibration_decision.md]),
because a conformal interval leans on exchangeability and a player with two fixtures is
not exchangeable with a player with one: the same position multiplier is too narrow
for a double and, by construction, slightly too wide for a single.

This module fits and evaluates the next axis: **position by fixture group** — ``single``
(one fixture) and ``double_plus`` (two or more) — with a pooled fallback per position
where a cell is too small, on a residual table that already carries the calendar
(``fixture_count`` per row, attached by the fixture bridge). Blank rows are zero by
construction and are excluded rather than calibrated. The evaluation is chronological:
folds are ordered by season and gameweek, the earlier share calibrates, the later share
is held out, and both the position-only and the position-by-fixture calibrations are
scored on the same held-out rows, overall and per fixture group. That is the comparison
the decision needs; whether the operational contract moves to this axis is a separate
declaration.
"""

import hashlib
import json
import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from statistics import fmean, pstdev
from types import MappingProxyType
from typing import Final

import pandas as pd

from squadopt.data.schema import POSITIONS
from squadopt.uncertainty.errors import (
    UncertaintyConfigurationError,
    UncertaintyValidationError,
)

FIXTURE_GROUP_CONFORMAL_CONTRACT_VERSION: Final = "fixture_group_conformal_v1"
FIXTURE_GROUPS: Final = ("single", "double_plus")
BLANK_GROUP: Final = "blank"
REQUIRED_COLUMNS: Final = (
    "fold_id",
    "season",
    "gameweek",
    "player_id",
    "position",
    "residual",
    "fixture_count",
)


def fixture_group(count: int) -> str:
    """Name the calendar group of one row: blank, single, or double_plus."""

    if count <= 0:
        return BLANK_GROUP
    return "single" if count == 1 else "double_plus"


@dataclass(frozen=True, slots=True)
class FixtureGroupConformalConfig:
    """Controls for the fixture-group conformal fit and its chronological evaluation."""

    confidence_level: float = 0.90
    calibration_fold_fraction: float = 0.60
    min_group_observations: int = 30
    contract_version: str = FIXTURE_GROUP_CONFORMAL_CONTRACT_VERSION

    def __post_init__(self) -> None:
        for name, value, low, high in (
            ("confidence_level", self.confidence_level, 0.0, 1.0),
            ("calibration_fold_fraction", self.calibration_fold_fraction, 0.0, 1.0),
        ):
            if (
                isinstance(value, bool)
                or not isinstance(value, int | float)
                or not math.isfinite(float(value))
                or not low < float(value) < high
            ):
                raise UncertaintyConfigurationError(
                    f"{name} must be a finite number strictly between {low} and {high}."
                )
            object.__setattr__(self, name, float(value))
        if (
            isinstance(self.min_group_observations, bool)
            or not isinstance(self.min_group_observations, int)
            or self.min_group_observations < 1
        ):
            raise UncertaintyConfigurationError(
                "min_group_observations must be a positive integer."
            )
        if self.contract_version != FIXTURE_GROUP_CONFORMAL_CONTRACT_VERSION:
            raise UncertaintyConfigurationError("contract_version does not match this module.")

    @property
    def configuration_fingerprint(self) -> str:
        payload = {
            "confidence_level": self.confidence_level,
            "calibration_fold_fraction": self.calibration_fold_fraction,
            "min_group_observations": self.min_group_observations,
            "contract_version": self.contract_version,
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class ConformalCell:
    """One calibrated cell: the radius applied to rows of a position (and fixture group)."""

    position: str
    fixture_group: str | None
    source: str
    group_observations: int
    calibration_observations: int
    residual_mean: float
    residual_stddev: float
    interval_radius: float
    conformal_rank: int


@dataclass(frozen=True, slots=True)
class CellMetrics:
    """Held-out coverage and width of one scored population."""

    observations: int
    empirical_coverage: float
    mean_interval_width: float
    mean_absolute_error: float


@dataclass(frozen=True, slots=True)
class FixtureGroupConformalResult:
    """Both calibrations, their held-out scores, and the provenance of the split."""

    config: FixtureGroupConformalConfig
    calibration_folds: tuple[str, ...]
    evaluation_folds: tuple[str, ...]
    position_cells: Mapping[str, ConformalCell]
    fixture_cells: Mapping[tuple[str, str], ConformalCell]
    position_metrics: Mapping[str, CellMetrics]
    fixture_metrics: Mapping[str, CellMetrics]
    """Held-out metrics keyed by population: ``overall``, each fixture group, and
    ``<position>/<group>`` — one mapping per calibration."""
    fingerprint: str
    diagnostics: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "position_cells", MappingProxyType(dict(self.position_cells)))
        object.__setattr__(self, "fixture_cells", MappingProxyType(dict(self.fixture_cells)))
        object.__setattr__(self, "position_metrics", MappingProxyType(dict(self.position_metrics)))
        object.__setattr__(self, "fixture_metrics", MappingProxyType(dict(self.fixture_metrics)))
        object.__setattr__(self, "diagnostics", MappingProxyType(dict(self.diagnostics)))


def _conformal_radius(values: list[float], confidence_level: float) -> tuple[float, int]:
    """Finite-sample split-conformal absolute-residual quantile (same rule as v1)."""

    ordered = sorted(abs(value) for value in values)
    rank = min(len(ordered), math.ceil((len(ordered) + 1) * confidence_level))
    return ordered[rank - 1], rank


def _cell(
    position: str,
    group: str | None,
    values: list[float],
    fallback: list[float],
    source: str,
    fallback_source: str,
    config: FixtureGroupConformalConfig,
) -> ConformalCell:
    if len(values) >= config.min_group_observations:
        effective, used = values, source
    else:
        effective, used = fallback, fallback_source
    if not effective:
        raise UncertaintyValidationError(
            f"No calibration residuals for position {position!r} group {group!r}."
        )
    radius, rank = _conformal_radius(effective, config.confidence_level)
    return ConformalCell(
        position=position,
        fixture_group=group,
        source=used,
        group_observations=len(values),
        calibration_observations=len(effective),
        residual_mean=fmean(effective),
        residual_stddev=pstdev(effective),
        interval_radius=radius,
        conformal_rank=rank,
    )


def validate_residual_table(table: pd.DataFrame) -> pd.DataFrame:
    """Validate the residual-with-calendar table and return a typed, sorted copy."""

    if not isinstance(table, pd.DataFrame):
        raise UncertaintyValidationError("Residual table must be a pandas DataFrame.")
    missing = [column for column in REQUIRED_COLUMNS if column not in table.columns]
    if missing:
        raise UncertaintyValidationError(f"Residual table is missing columns: {missing!r}.")
    frame = table.loc[:, list(REQUIRED_COLUMNS)].copy(deep=True)
    if frame.empty:
        raise UncertaintyValidationError("Residual table has no rows.")
    if bool(frame.isna().any().any()):
        raise UncertaintyValidationError("Residual table contains missing values.")
    bad_positions = sorted({str(value) for value in frame["position"] if value not in POSITIONS})
    if bad_positions:
        raise UncertaintyValidationError(f"Unknown positions {bad_positions!r}.")
    for column in ("gameweek", "fixture_count"):
        values = frame[column].tolist()
        if any(isinstance(v, bool) or int(v) != v or int(v) < 0 for v in values):
            raise UncertaintyValidationError(f"{column} must hold non-negative integers.")
        frame[column] = pd.Series([int(v) for v in values], index=frame.index, dtype="int64")
    residuals = [float(value) for value in frame["residual"].tolist()]
    if any(not math.isfinite(value) for value in residuals):
        raise UncertaintyValidationError("residual must be finite.")
    frame["residual"] = pd.Series(residuals, index=frame.index, dtype="float64")
    frame["position"] = frame["position"].astype("string")
    frame["season"] = frame["season"].astype("string")
    frame["fold_id"] = frame["fold_id"].astype("string")
    frame["fixture_group"] = pd.Series(
        [fixture_group(int(v)) for v in frame["fixture_count"].tolist()],
        index=frame.index,
        dtype="string",
    )
    return frame.sort_values(["season", "gameweek", "player_id"], kind="stable").reset_index(
        drop=True
    )


def _metrics(residuals: list[float], radii: list[float]) -> CellMetrics:
    if not residuals:
        raise UncertaintyValidationError("Metrics need at least one row.")
    covered = sum(1 for r, radius in zip(residuals, radii, strict=True) if abs(r) <= radius)
    return CellMetrics(
        observations=len(residuals),
        empirical_coverage=covered / len(residuals),
        mean_interval_width=2.0 * fmean(radii),
        mean_absolute_error=fmean(abs(r) for r in residuals),
    )


def _score(
    frame: pd.DataFrame,
    radius_for: Mapping[tuple[str, str], float],
) -> dict[str, CellMetrics]:
    positions = frame["position"].tolist()
    groups = frame["fixture_group"].tolist()
    residuals = [float(v) for v in frame["residual"].tolist()]
    radii = [radius_for[(str(p), str(g))] for p, g in zip(positions, groups, strict=True)]
    out: dict[str, CellMetrics] = {"overall": _metrics(residuals, radii)}
    for group in FIXTURE_GROUPS:
        keep = [i for i, g in enumerate(groups) if g == group]
        if keep:
            out[group] = _metrics([residuals[i] for i in keep], [radii[i] for i in keep])
        for position in POSITIONS:
            both = [i for i in keep if positions[i] == position]
            if both:
                out[f"{position}/{group}"] = _metrics(
                    [residuals[i] for i in both], [radii[i] for i in both]
                )
    return out


def fit_and_evaluate_fixture_group_conformal(
    table: pd.DataFrame,
    config: FixtureGroupConformalConfig | None = None,
) -> FixtureGroupConformalResult:
    """Fit position-only and position-by-fixture-group conformal radii on the earlier
    folds and score both on the later folds, blank rows excluded throughout."""

    settings = FixtureGroupConformalConfig() if config is None else config
    if not isinstance(settings, FixtureGroupConformalConfig):
        raise UncertaintyValidationError("config must be a FixtureGroupConformalConfig.")
    frame = validate_residual_table(table)
    blank_rows = int((frame["fixture_group"] == BLANK_GROUP).sum())
    frame = frame.loc[frame["fixture_group"] != BLANK_GROUP].reset_index(drop=True)
    if frame.empty:
        raise UncertaintyValidationError("Every row is a blank; nothing to calibrate.")

    folds = (
        frame.loc[:, ["season", "gameweek", "fold_id"]]
        .drop_duplicates()
        .sort_values(["season", "gameweek"], kind="stable")
    )
    fold_ids = [str(v) for v in folds["fold_id"].tolist()]
    split = math.floor(len(fold_ids) * settings.calibration_fold_fraction)
    if split < 1 or split >= len(fold_ids):
        raise UncertaintyValidationError(
            f"The chronological split leaves {split} calibration folds of {len(fold_ids)}; "
            "both sides need at least one fold."
        )
    calibration_folds = tuple(fold_ids[:split])
    evaluation_folds = tuple(fold_ids[split:])
    calibrate = frame.loc[frame["fold_id"].isin(calibration_folds)]
    evaluate = frame.loc[frame["fold_id"].isin(evaluation_folds)]
    if calibrate.empty or evaluate.empty:
        raise UncertaintyValidationError("Both split sides must hold rows.")

    pooled = [float(v) for v in calibrate["residual"].tolist()]
    position_cells: dict[str, ConformalCell] = {}
    fixture_cells: dict[tuple[str, str], ConformalCell] = {}
    for position in POSITIONS:
        by_position = [
            float(v) for v in calibrate.loc[calibrate["position"] == position, "residual"].tolist()
        ]
        position_cells[position] = _cell(
            position, None, by_position, pooled, "position", "pooled_fallback", settings
        )
        for group in FIXTURE_GROUPS:
            mask = (calibrate["position"] == position) & (calibrate["fixture_group"] == group)
            values = [float(v) for v in calibrate.loc[mask, "residual"].tolist()]
            fixture_cells[(position, group)] = _cell(
                position,
                group,
                values,
                by_position if len(by_position) >= settings.min_group_observations else pooled,
                "position_fixture_group",
                "position_fallback"
                if len(by_position) >= settings.min_group_observations
                else "pooled_fallback",
                settings,
            )

    position_radius: dict[tuple[str, str], float] = {
        (str(position), group): position_cells[position].interval_radius
        for position in POSITIONS
        for group in FIXTURE_GROUPS
    }
    fixture_radius: dict[tuple[str, str], float] = {
        key: cell.interval_radius for key, cell in fixture_cells.items()
    }
    position_metrics = _score(evaluate, position_radius)
    fixture_metrics = _score(evaluate, fixture_radius)

    payload = {
        "configuration_fingerprint": settings.configuration_fingerprint,
        "calibration_folds": list(calibration_folds),
        "evaluation_folds": list(evaluation_folds),
        "position_cells": {k: _cell_dict(v) for k, v in position_cells.items()},
        "fixture_cells": {f"{k[0]}/{k[1]}": _cell_dict(v) for k, v in fixture_cells.items()},
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return FixtureGroupConformalResult(
        config=settings,
        calibration_folds=calibration_folds,
        evaluation_folds=evaluation_folds,
        position_cells=position_cells,
        fixture_cells=fixture_cells,
        position_metrics=position_metrics,
        fixture_metrics=fixture_metrics,
        fingerprint=hashlib.sha256(encoded).hexdigest(),
        diagnostics={
            "contract_version": settings.contract_version,
            "rows_total": len(frame) + blank_rows,
            "blank_rows_excluded": blank_rows,
            "calibration_rows": len(calibrate),
            "evaluation_rows": len(evaluate),
            "evaluation_rows_by_group": {
                group: int((evaluate["fixture_group"] == group).sum()) for group in FIXTURE_GROUPS
            },
            "interval_method": "symmetric-split-conformal-absolute-residual",
            "quantile_rank": "ceil((n+1)*confidence_level)-capped-at-n",
            "split": "chronological-by-fold",
        },
    )


def _cell_dict(cell: ConformalCell) -> dict[str, object]:
    return {
        "position": cell.position,
        "fixture_group": cell.fixture_group,
        "source": cell.source,
        "group_observations": cell.group_observations,
        "calibration_observations": cell.calibration_observations,
        "residual_mean": cell.residual_mean,
        "residual_stddev": cell.residual_stddev,
        "interval_radius": cell.interval_radius,
        "conformal_rank": cell.conformal_rank,
    }


def result_to_dict(result: FixtureGroupConformalResult) -> dict[str, object]:
    """Serialise the result for the committed artifact."""

    def metrics(table: Mapping[str, CellMetrics]) -> dict[str, dict[str, float | int]]:
        return {
            key: {
                "observations": value.observations,
                "empirical_coverage": value.empirical_coverage,
                "mean_interval_width": value.mean_interval_width,
                "mean_absolute_error": value.mean_absolute_error,
            }
            for key, value in table.items()
        }

    return {
        "contract_version": result.config.contract_version,
        "configuration_fingerprint": result.config.configuration_fingerprint,
        "fingerprint": result.fingerprint,
        "confidence_level": result.config.confidence_level,
        "calibration_folds": list(result.calibration_folds),
        "evaluation_folds": list(result.evaluation_folds),
        "position_cells": {k: _cell_dict(v) for k, v in result.position_cells.items()},
        "fixture_cells": {f"{k[0]}/{k[1]}": _cell_dict(v) for k, v in result.fixture_cells.items()},
        "held_out": {
            "position_only": metrics(result.position_metrics),
            "position_fixture_group": metrics(result.fixture_metrics),
        },
        "diagnostics": dict(result.diagnostics),
    }
