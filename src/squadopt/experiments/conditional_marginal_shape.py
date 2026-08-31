"""Compare canonical starter marginals with direct empirical residual pools."""

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
    SquadShadowError,
    _require,
)

CONDITIONAL_SHAPE_CONTRACT_VERSION: Final = "phase2_conditional_marginal_shape_v1"
CANONICAL: Final = "canonical"
RAW_UNCONDITIONAL: Final = "raw_unconditional"
RAW_COMPLETED: Final = "raw_completed_appearance"
ARMS: Final = (CANONICAL, RAW_UNCONDITIONAL, RAW_COMPLETED)

APPEARANCE_CANDIDATE: Final = "appearance_conditioning_candidate"
RECOMBINATION_CANDIDATE: Final = "direct_marginal_recombination_candidate"
BOTH_ADEQUATE: Final = "direct_marginals_both_adequate"
UNRESOLVED: Final = "conditional_marginal_shape_unresolved"


def attach_history_minutes(residuals: pd.DataFrame, panel: pd.DataFrame) -> pd.DataFrame:
    """Attach outcome minutes to residual rows without changing their population."""

    keys = ["season", "gameweek", "player_id"]
    outcomes = panel.loc[:, [*keys, "minutes"]]
    _require(
        not bool(outcomes.duplicated(keys).any()),
        "panel outcomes repeat a residual identity.",
    )
    merged = residuals.merge(outcomes, on=keys, how="left", validate="many_to_one")
    _require(not bool(merged["minutes"].isna().any()), "residual history is missing minutes.")
    minutes = pd.to_numeric(merged["minutes"], errors="coerce").to_numpy(dtype="float64")
    _require(
        bool(np.isfinite(minutes).all()) and bool((minutes >= 0.0).all()),
        "residual-history minutes must be finite and non-negative.",
    )
    merged["minutes"] = minutes
    return merged


def _source_pool(
    history: pd.DataFrame,
    *,
    player_id: object,
    position: str,
    min_player_observations: int,
) -> tuple[np.ndarray, str]:
    player = history.loc[history["player_id"] == player_id, "residual"].to_numpy(dtype="float64")
    if len(player) >= min_player_observations:
        values, source = player, "player"
    else:
        position_values = history.loc[history["position"] == position, "residual"].to_numpy(
            dtype="float64"
        )
        if len(position_values):
            values, source = position_values, "position"
        else:
            values = history["residual"].to_numpy(dtype="float64")
            source = "pooled"
    _require(bool(len(values)), "a direct empirical residual pool is empty.")
    _require(bool(np.isfinite(values).all()), "a direct empirical residual pool is non-finite.")
    return values, source


def compare_fold(
    starters: pd.DataFrame,
    residuals_with_minutes: pd.DataFrame,
    history_fold_ids: Sequence[str],
    *,
    min_player_observations: int,
) -> pd.DataFrame:
    """Return three pre-registered marginal readings for each completed-appearance starter."""

    required = {
        "fold_id",
        "season",
        "player_id",
        "position",
        "minutes",
        "realized_residual",
        "downside_threshold",
        "scenario_downside_rate",
        "realized_downside",
    }
    _require(required.issubset(starters.columns), "starter shape rows are incomplete.")
    selected = starters.loc[starters["minutes"] >= 60.0]
    _require(not selected.empty, "a fold has no completed-appearance starter.")
    history = residuals_with_minutes.loc[
        residuals_with_minutes["fold_id"].astype(str).isin(set(history_fold_ids))
    ]
    _require(not history.empty, "a fold has no declared residual history.")
    completed = history.loc[history["minutes"] >= 60.0]
    _require(not completed.empty, "a fold has no completed-appearance residual history.")

    rows: list[dict[str, object]] = []
    for starter in selected.itertuples(index=False):
        base = {
            "fold_id": str(starter.fold_id),
            "season": str(starter.season),
            "player_id": starter.player_id,
        }
        rows.append(
            {
                **base,
                "arm": CANONICAL,
                "source": "canonical_scenarios",
                "threshold": float(cast(float, starter.downside_threshold)),
                "expected_rate": float(cast(float, starter.scenario_downside_rate)),
                "realized_event": bool(starter.realized_downside),
            }
        )
        for arm, source_history in (
            (RAW_UNCONDITIONAL, history),
            (RAW_COMPLETED, completed),
        ):
            pool, source = _source_pool(
                source_history,
                player_id=starter.player_id,
                position=str(starter.position),
                min_player_observations=min_player_observations,
            )
            threshold = float(np.quantile(pool, 0.25, method="linear"))
            rows.append(
                {
                    **base,
                    "arm": arm,
                    "source": source,
                    "threshold": threshold,
                    "expected_rate": float((pool < threshold).mean()),
                    "realized_event": float(cast(float, starter.realized_residual)) < threshold,
                }
            )
    return pd.DataFrame(rows)


def _gap_summary(values: Sequence[float]) -> dict[str, float]:
    _require(bool(values), "a conditional marginal arm has no fold gaps.")
    low, high = bootstrap_interval(
        values,
        resamples=BOOTSTRAP_RESAMPLES,
        seed=BOOTSTRAP_SEED,
        confidence_level=CONFIDENCE_LEVEL,
    )
    return {"mean": float(np.mean(values)), "bootstrap_low": low, "bootstrap_high": high}


def summarise(frame: pd.DataFrame) -> dict[str, object]:
    """Summarise each marginal arm over one declared fold population."""

    _require(not frame.empty, "a conditional marginal summary needs rows.")
    summaries: dict[str, object] = {}
    for arm in ARMS:
        selected = frame.loc[frame["arm"] == arm]
        _require(not selected.empty, f"conditional marginal arm {arm!r} is absent.")
        fold_gaps = (
            selected.assign(
                gap=selected["realized_event"].astype("float64")
                - selected["expected_rate"].astype("float64")
            )
            .groupby("fold_id", sort=False)["gap"]
            .mean()
            .tolist()
        )
        summaries[arm] = {
            "fold_count": int(selected["fold_id"].nunique()),
            "starter_rows": len(selected),
            "source_counts": {
                str(source): int(count)
                for source, count in selected["source"].value_counts(sort=False).items()
            },
            "realized_event_rate": float(selected["realized_event"].mean()),
            "source_expected_event_rate": float(selected["expected_rate"].mean()),
            "gap": _gap_summary([float(value) for value in fold_gaps]),
            "mean_threshold": float(selected["threshold"].mean()),
        }
    return {"arms": summaries}


def classify(summary: Mapping[str, object]) -> str:
    """Apply the pre-registered validation classification."""

    arms = summary.get("arms")
    if not isinstance(arms, Mapping):
        return UNRESOLVED

    def compatible(arm: str) -> bool | None:
        value = arms.get(arm)
        if not isinstance(value, Mapping):
            return None
        fold_count = value.get("fold_count")
        gap = value.get("gap")
        if type(fold_count) is not int or fold_count < MIN_EVALUATION_FOLDS:
            return None
        if not isinstance(gap, Mapping):
            return None
        return float(gap["bootstrap_low"]) <= 0.0 <= float(gap["bootstrap_high"])

    canonical = compatible(CANONICAL)
    unconditional = compatible(RAW_UNCONDITIONAL)
    completed = compatible(RAW_COMPLETED)
    if canonical is not False or unconditional is None or completed is None:
        return UNRESOLVED
    if completed and not unconditional:
        return APPEARANCE_CANDIDATE
    if unconditional and not completed:
        return RECOMBINATION_CANDIDATE
    if unconditional and completed:
        return BOTH_ADEQUATE
    return UNRESOLVED


def reconcile_completed_canonical(
    summary: Mapping[str, object], recorded_bucket: Mapping[str, object]
) -> None:
    """Require the canonical completed-appearance arm to reproduce the prior artifact."""

    arms = summary.get("arms")
    if not isinstance(arms, Mapping) or not isinstance(arms.get(CANONICAL), Mapping):
        raise SquadShadowError("the canonical marginal summary is absent.")
    canonical = arms[CANONICAL]
    assert isinstance(canonical, Mapping)
    comparisons = (
        (canonical["starter_rows"], recorded_bucket["starter_rows"]),
        (canonical["realized_event_rate"], recorded_bucket["realized_downside_rate"]),
        (
            canonical["source_expected_event_rate"],
            recorded_bucket["scenario_expected_downside_rate"],
        ),
    )
    for measured, recorded in comparisons:
        _require(
            abs(float(cast(float, measured)) - float(cast(float, recorded))) <= 1e-12,
            "the canonical completed-appearance arm does not reproduce the prior artifact.",
        )
