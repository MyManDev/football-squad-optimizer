"""Measure whether completed-appearance returns need projection conditioning."""

from collections.abc import Mapping, Sequence
from typing import Final, cast

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
    _require,
)

CONTRACT_VERSION: Final = "phase2_projection_conditional_returns_v1"
POSITION_FULL: Final = "position_full"
POSITION_EXPECTED_FULL: Final = "position_x_expected_points_full"
POSITION_EXPECTED_RECENT: Final = "position_x_expected_points_recent8"
ARMS: Final = (POSITION_FULL, POSITION_EXPECTED_FULL, POSITION_EXPECTED_RECENT)

PROJECTION_AND_RECENCY: Final = "projection_and_recency_signal"
PROJECTION_CANDIDATE: Final = "projection_conditional_shape_candidate"
RECENCY_CANDIDATE: Final = "recency_weighted_shape_candidate"
NOT_LOCALIZED: Final = "conditional_shape_not_localized"
INCONCLUSIVE: Final = "diagnostic_inconclusive"

EXPECTED_POINTS_EDGES: Final = (3.0, 4.0, 5.0, 6.0)
RETURN_STATES: Final = ("points_le_1", "points_2_3", "points_4_5", "points_ge_6")
MIN_SOURCE_OBSERVATIONS: Final = 30
RECENT_FOLDS: Final = 8
MIN_GROUP_ROWS: Final = 50
MIN_GROUP_PLAYERS: Final = 20
MIN_DIRECT_COVERAGE: Final = 0.80


def expected_points_band(value: float) -> int:
    """Return the fixed expected-points band index for a finite non-negative value."""

    _require(
        bool(np.isfinite(value)) and value >= 0.0,
        "expected points must be finite and non-negative.",
    )
    return int(np.searchsorted(EXPECTED_POINTS_EDGES, value, side="right"))


def return_state(value: float) -> int:
    """Return the fixed four-state index for an integral realized-points value."""

    _require(
        bool(np.isfinite(value)) and float(value).is_integer(),
        "realized points must be finite integers.",
    )
    integer = int(value)
    if integer <= 1:
        return 0
    if integer <= 3:
        return 1
    if integer <= 5:
        return 2
    return 3


def recent_history_fold_ids(history: pd.DataFrame, allowed_ids: Sequence[str]) -> tuple[str, ...]:
    """Return the last eight chronological folds within the caller's allowed history."""

    allowed = {str(value) for value in allowed_ids}
    _require(bool(allowed), "recent history needs declared fold identifiers.")
    selected = history.loc[history["fold_id"].astype(str).isin(allowed)]
    _require(not selected.empty, "recent history is empty.")
    identity = selected.loc[:, ["fold_id", "season", "gameweek"]].drop_duplicates()
    _require(
        bool(identity["fold_id"].astype(str).is_unique)
        and {str(value) for value in identity["fold_id"]} == allowed,
        "each declared history fold must map to one season and gameweek.",
    )
    identity = identity.assign(
        season_start=identity["season"].astype(str).str.slice(0, 4).astype(int),
        gameweek_number=pd.to_numeric(identity["gameweek"], errors="raise").astype(int),
    ).sort_values(["season_start", "gameweek_number", "fold_id"], kind="stable")
    return tuple(identity["fold_id"].astype(str).tail(RECENT_FOLDS))


def _validated_history(history: pd.DataFrame) -> pd.DataFrame:
    required = {
        "fold_id",
        "season",
        "gameweek",
        "player_id",
        "position",
        "predicted_points",
        "realized_points",
        "residual",
        "minutes",
    }
    _require(required.issubset(history.columns), "conditional return history is incomplete.")
    selected = history.loc[history["minutes"].astype("float64") >= 60.0].copy()
    _require(not selected.empty, "conditional return history has no completed appearances.")
    predicted = pd.to_numeric(selected["predicted_points"], errors="coerce").to_numpy(
        dtype="float64"
    )
    realized = pd.to_numeric(selected["realized_points"], errors="coerce").to_numpy(dtype="float64")
    residual = pd.to_numeric(selected["residual"], errors="coerce").to_numpy(dtype="float64")
    _require(
        bool(np.isfinite(predicted).all()) and bool((predicted >= 0.0).all()),
        "historical expected points must be finite and non-negative.",
    )
    _require(
        bool(np.isfinite(realized).all()) and bool(np.equal(realized, np.floor(realized)).all()),
        "historical realized points must be finite integers.",
    )
    _require(bool(np.isfinite(residual).all()), "historical residuals must be finite.")
    selected["expected_band"] = [expected_points_band(float(value)) for value in predicted]
    selected["return_state"] = [return_state(float(value)) for value in realized]
    return selected


def _pool(
    history: pd.DataFrame,
    *,
    position: str,
    band: int,
    conditional: bool,
) -> tuple[pd.DataFrame, str, bool]:
    position_rows = history.loc[history["position"].astype(str).eq(position)]
    if conditional:
        exact = position_rows.loc[position_rows["expected_band"].astype(int).eq(band)]
        if len(exact) >= MIN_SOURCE_OBSERVATIONS:
            return exact, "position_band", True
        adjacent_bands = {band}
        if band > 0:
            adjacent_bands.add(band - 1)
        if band < len(EXPECTED_POINTS_EDGES):
            adjacent_bands.add(band + 1)
        adjacent = position_rows.loc[
            position_rows["expected_band"].astype(int).isin(adjacent_bands)
        ]
        if len(adjacent) >= MIN_SOURCE_OBSERVATIONS:
            return adjacent, "position_adjacent_bands", False
    if len(position_rows) >= MIN_SOURCE_OBSERVATIONS:
        return position_rows, "position", False
    _require(
        len(history) >= MIN_SOURCE_OBSERVATIONS,
        "pooled completed-appearance history has insufficient support.",
    )
    return history, "pooled", False


def _probabilities(pool: pd.DataFrame) -> np.ndarray:
    counts = np.bincount(pool["return_state"].to_numpy(dtype="int64"), minlength=len(RETURN_STATES))
    probabilities = counts.astype("float64") / counts.sum()
    _require(bool(np.isfinite(probabilities).all()), "return-state probabilities are non-finite.")
    return probabilities


def compare_fold(
    starters: pd.DataFrame,
    history_with_minutes: pd.DataFrame,
    history_fold_ids: Sequence[str],
) -> pd.DataFrame:
    """Score the three preregistered return-shape arms for one fixed XI."""

    required = {
        "fold_id",
        "season",
        "player_id",
        "position",
        "expected_points",
        "realized_points",
        "realized_residual",
        "minutes",
    }
    _require(required.issubset(starters.columns), "conditional return target rows are incomplete.")
    selected = starters.loc[starters["minutes"].astype("float64") >= 60.0]
    _require(not selected.empty, "a fold has no completed-appearance starter.")
    allowed = tuple(str(value) for value in history_fold_ids)
    _require(len(allowed) == len(set(allowed)), "declared history fold identifiers repeat.")
    target_folds = {str(value) for value in selected["fold_id"]}
    _require(
        target_folds.isdisjoint(allowed),
        "a target fold cannot enter its own conditional return history.",
    )
    history = history_with_minutes.loc[
        history_with_minutes["fold_id"].astype(str).isin(set(allowed))
    ]
    _require(
        {str(value) for value in history["fold_id"]} == set(allowed),
        "declared history is missing a fold.",
    )
    full = _validated_history(history)
    recent_ids = recent_history_fold_ids(history, allowed)
    recent = _validated_history(history.loc[history["fold_id"].astype(str).isin(set(recent_ids))])

    rows: list[dict[str, object]] = []
    for target in selected.itertuples(index=False):
        expected = float(cast(float, target.expected_points))
        realized = float(cast(float, target.realized_points))
        band = expected_points_band(expected)
        state = return_state(realized)
        for arm, arm_history, conditional in (
            (POSITION_FULL, full, False),
            (POSITION_EXPECTED_FULL, full, True),
            (POSITION_EXPECTED_RECENT, recent, True),
        ):
            pool, source, direct = _pool(
                arm_history,
                position=str(target.position),
                band=band,
                conditional=conditional,
            )
            probabilities = _probabilities(pool)
            observed = np.zeros(len(RETURN_STATES), dtype="float64")
            observed[state] = 1.0
            residuals = pool["residual"].to_numpy(dtype="float64")
            threshold = float(np.quantile(residuals, 0.25, method="linear"))
            row: dict[str, object] = {
                "fold_id": str(target.fold_id),
                "season": str(target.season),
                "player_id": target.player_id,
                "expected_points": expected,
                "expected_band": band,
                "expected_group": "high" if expected >= 5.0 else "low",
                "return_state": state,
                "arm": arm,
                "source": source,
                "source_count": len(pool),
                "direct_cell": direct,
                "brier": float(np.square(probabilities - observed).sum()),
                "threshold": threshold,
                "expected_downside_rate": float((residuals < threshold).mean()),
                "realized_downside": float(cast(float, target.realized_residual)) < threshold,
            }
            row.update(
                {
                    f"probability_{name}": float(probabilities[index])
                    for index, name in enumerate(RETURN_STATES)
                }
            )
            rows.append(row)
    return pd.DataFrame(rows)


def _bootstrap(values: Sequence[float]) -> dict[str, float]:
    _require(bool(values), "a projection-conditional comparison has no fold values.")
    low, high = bootstrap_interval(
        values,
        resamples=BOOTSTRAP_RESAMPLES,
        seed=BOOTSTRAP_SEED,
        confidence_level=CONFIDENCE_LEVEL,
    )
    return {"mean": float(np.mean(values)), "bootstrap_low": low, "bootstrap_high": high}


def _arm_summary(frame: pd.DataFrame) -> dict[str, object]:
    fold_brier = frame.groupby("fold_id", sort=True)["brier"].mean()
    fold_gap = (
        frame.assign(
            q25_gap=frame["realized_downside"].astype("float64")
            - frame["expected_downside_rate"].astype("float64")
        )
        .groupby("fold_id", sort=True)["q25_gap"]
        .mean()
    )
    return {
        "fold_count": int(frame["fold_id"].nunique()),
        "target_rows": len(frame),
        "unique_players": int(frame["player_id"].nunique()),
        "mean_brier": float(fold_brier.mean()),
        "direct_cell_coverage": float(frame["direct_cell"].mean()),
        "source_counts": {
            str(key): int(value) for key, value in frame["source"].value_counts(sort=False).items()
        },
        "mean_q25_threshold": float(frame["threshold"].mean()),
        "realized_downside_rate": float(frame["realized_downside"].mean()),
        "source_expected_downside_rate": float(frame["expected_downside_rate"].mean()),
        "mean_absolute_fold_q25_gap": float(fold_gap.abs().mean()),
    }


def _paired(frame: pd.DataFrame, candidate: str, control: str) -> dict[str, object]:
    keys = ["fold_id", "player_id"]
    candidate_rows = frame.loc[frame["arm"].eq(candidate)].set_index(keys).sort_index()
    control_rows = frame.loc[frame["arm"].eq(control)].set_index(keys).sort_index()
    _require(
        candidate_rows.index.equals(control_rows.index),
        "conditional return arms do not share target rows.",
    )
    row_delta = candidate_rows["brier"].astype("float64") - control_rows["brier"].astype("float64")
    brier_by_fold = row_delta.groupby(level="fold_id", sort=True).mean()
    candidate_gap = (
        (
            candidate_rows["realized_downside"].astype("float64")
            - candidate_rows["expected_downside_rate"].astype("float64")
        )
        .groupby(level="fold_id", sort=True)
        .mean()
    )
    control_gap = (
        (
            control_rows["realized_downside"].astype("float64")
            - control_rows["expected_downside_rate"].astype("float64")
        )
        .groupby(level="fold_id", sort=True)
        .mean()
    )
    return {
        "brier_delta": _bootstrap([float(value) for value in brier_by_fold]),
        "absolute_q25_gap_delta": _bootstrap(
            [float(value) for value in candidate_gap.abs() - control_gap.abs()]
        ),
    }


def _localization(frame: pd.DataFrame) -> dict[str, object]:
    control = frame.loc[frame["arm"].eq(POSITION_FULL)].copy()
    ordinary_probability = control[f"probability_{RETURN_STATES[1]}"].astype("float64")
    control["ordinary_gap"] = (
        control["return_state"].astype(int).eq(1).astype("float64") - ordinary_probability
    )
    grouped = (
        control.groupby(["fold_id", "expected_group"], sort=True)["ordinary_gap"]
        .mean()
        .unstack()
        .reindex(columns=["low", "high"])
    )
    paired = grouped.dropna(subset=["low", "high"])
    contrast = paired["high"] - paired["low"]
    groups: dict[str, object] = {}
    for group in ("low", "high"):
        selected = control.loc[control["expected_group"].eq(group)]
        groups[group] = {
            "target_rows": len(selected),
            "unique_players": int(selected["player_id"].nunique()),
            "ordinary_observed_rate": float(selected["return_state"].astype(int).eq(1).mean()),
            "ordinary_predicted_rate": float(selected[f"probability_{RETURN_STATES[1]}"].mean()),
        }
    contrast_summary = _bootstrap([float(value) for value in contrast]) if len(contrast) else None
    return {
        "paired_fold_count": len(paired),
        "high_minus_low_ordinary_gap": contrast_summary,
        "groups": groups,
    }


def _state_table(frame: pd.DataFrame) -> dict[str, object]:
    rows: dict[str, object] = {}
    for band in range(len(EXPECTED_POINTS_EDGES) + 1):
        selected = frame.loc[frame["expected_band"].astype(int).eq(band)]
        band_rows: dict[str, object] = {"target_rows": len(selected)}
        for index, state in enumerate(RETURN_STATES):
            band_rows[state] = {
                "observed_rate": float(selected["return_state"].astype(int).eq(index).mean())
                if len(selected)
                else None,
                "predicted_rate": float(selected[f"probability_{state}"].mean())
                if len(selected)
                else None,
            }
        rows[str(band)] = band_rows
    return rows


def summarise(frame: pd.DataFrame) -> dict[str, object]:
    """Summarise one declared population and apply no model selection."""

    _require(not frame.empty, "a projection-conditional summary needs rows.")
    arms = {arm: _arm_summary(frame.loc[frame["arm"].eq(arm)]) for arm in ARMS}
    target = frame.loc[frame["arm"].eq(POSITION_FULL)]
    player_counts = target.groupby("player_id", sort=False).size()
    top_player = min(
        player_counts.index,
        key=lambda player_id: (-int(player_counts.loc[player_id]), str(player_id)),
    )
    without_top = frame.loc[frame["player_id"] != top_player]
    projection_without_top_mean: float | None = None
    recency_without_top_mean: float | None = None
    if not without_top.empty:
        projection_without_top = _paired(without_top, POSITION_EXPECTED_FULL, POSITION_FULL)
        recency_without_top = _paired(without_top, POSITION_EXPECTED_RECENT, POSITION_EXPECTED_FULL)
        projection_without_top_delta = cast(
            Mapping[str, float], projection_without_top["brier_delta"]
        )
        recency_without_top_delta = cast(Mapping[str, float], recency_without_top["brier_delta"])
        projection_without_top_mean = projection_without_top_delta["mean"]
        recency_without_top_mean = recency_without_top_delta["mean"]
    return {
        "arms": arms,
        "projection_comparison": _paired(frame, POSITION_EXPECTED_FULL, POSITION_FULL),
        "recency_comparison": _paired(frame, POSITION_EXPECTED_RECENT, POSITION_EXPECTED_FULL),
        "recent_vs_position_comparison": _paired(frame, POSITION_EXPECTED_RECENT, POSITION_FULL),
        "projection_localization": _localization(frame),
        "state_tables": {arm: _state_table(frame.loc[frame["arm"].eq(arm)]) for arm in ARMS},
        "top_player_diagnostic": {
            "player_id": str(top_player),
            "row_share": float(player_counts.loc[top_player] / len(target)),
            "projection_brier_delta_without_top": projection_without_top_mean,
            "recency_brier_delta_without_top": recency_without_top_mean,
        },
    }


def classify(summary: Mapping[str, object]) -> str:
    """Apply the single preregistered validation classification."""

    try:
        arms = summary["arms"]
        localization = summary["projection_localization"]
        projection = summary["projection_comparison"]
        recency = summary["recency_comparison"]
        recent_vs_position = summary["recent_vs_position_comparison"]
        assert isinstance(arms, Mapping)
        assert isinstance(localization, Mapping)
        assert isinstance(projection, Mapping)
        assert isinstance(recency, Mapping)
        assert isinstance(recent_vs_position, Mapping)
        groups = localization["groups"]
        assert isinstance(groups, Mapping)
        low = groups["low"]
        high = groups["high"]
        assert isinstance(low, Mapping) and isinstance(high, Mapping)
        full = arms[POSITION_EXPECTED_FULL]
        recent = arms[POSITION_EXPECTED_RECENT]
        assert isinstance(full, Mapping) and isinstance(recent, Mapping)
        support = (
            int(full["fold_count"]) >= MIN_EVALUATION_FOLDS
            and int(localization["paired_fold_count"]) >= MIN_EVALUATION_FOLDS
            and all(
                int(group["target_rows"]) >= MIN_GROUP_ROWS
                and int(group["unique_players"]) >= MIN_GROUP_PLAYERS
                for group in (low, high)
            )
            and float(full["direct_cell_coverage"]) >= MIN_DIRECT_COVERAGE
            and float(recent["direct_cell_coverage"]) >= MIN_DIRECT_COVERAGE
        )
        if not support:
            return INCONCLUSIVE
        localization_gap = cast(Mapping[str, float], localization["high_minus_low_ordinary_gap"])
        projection_brier = cast(Mapping[str, float], projection["brier_delta"])
        recency_brier = cast(Mapping[str, float], recency["brier_delta"])
        recent_total_brier = cast(Mapping[str, float], recent_vs_position["brier_delta"])
        projection_tail = cast(Mapping[str, float], projection["absolute_q25_gap_delta"])
        recent_total_tail = cast(Mapping[str, float], recent_vs_position["absolute_q25_gap_delta"])
        localized = float(localization_gap["bootstrap_low"]) > 0.0
        projection_improves = float(projection_brier["bootstrap_high"]) < 0.0
        recent_improves = float(recency_brier["bootstrap_high"]) < 0.0
        recent_total_improves = float(recent_total_brier["bootstrap_high"]) < 0.0
        projection_tail_ok = float(projection_tail["bootstrap_high"]) <= 0.0
        recent_tail_ok = float(recent_total_tail["bootstrap_high"]) <= 0.0
    except (AssertionError, KeyError, TypeError, ValueError):
        return INCONCLUSIVE
    if (
        localized
        and projection_improves
        and recent_improves
        and recent_total_improves
        and projection_tail_ok
        and recent_tail_ok
    ):
        return PROJECTION_AND_RECENCY
    if localized and projection_improves and projection_tail_ok and not recent_improves:
        return PROJECTION_CANDIDATE
    if not projection_improves and recent_total_improves and recent_tail_ok:
        return RECENCY_CANDIDATE
    return NOT_LOCALIZED
