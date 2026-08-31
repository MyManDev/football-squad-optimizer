"""Fold-level attacking-blank structure for fixed selected XIs."""

from collections.abc import Mapping, Sequence
from itertools import combinations
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

CONTRACT_VERSION: Final = "phase2_attacking_structure_v1"
MARGINAL_EQUIVALENCE_BOUNDS: Final = (-0.05, 0.05)

MARGINAL_BLANK_EXCESS: Final = "attacking_marginal_blank_excess"
WRONG_DIRECTION: Final = "attacking_structure_wrong_direction"
SHARED_REFERENCE_EXCESS: Final = "shared_attacking_reference_excess"
COMMON_WEEK_REFERENCE_EXCESS: Final = "common_week_attacking_reference_excess"
SAME_TEAM_REFERENCE_EXCESS: Final = "same_team_attacking_reference_excess"
NOT_LOCALIZED: Final = "attacking_structure_not_localized"
INCONCLUSIVE: Final = "diagnostic_inconclusive"

_REQUIRED_COLUMNS: Final = {
    "fold_id",
    "season",
    "player_id",
    "team_id",
    "completed_appearance",
    "attacking_blank",
    "blank_probability",
}
_METRICS: Final = ("G", "O", "U", "K")


def _binary(values: pd.Series, name: str) -> np.ndarray:
    """Return one strict zero/one column as booleans."""

    numeric = pd.to_numeric(values, errors="coerce").to_numpy(dtype="float64")
    _require(
        bool(np.isfinite(numeric).all()) and bool(np.isin(numeric, (0.0, 1.0)).all()),
        f"{name} must contain only zero or one.",
    )
    return numeric.astype("bool")


def build_fold_metrics(player_rows: pd.DataFrame) -> dict[str, object]:
    """Calculate the frozen G/O/U/K diagnostics for one fold.

    Every player is counted once irrespective of captaincy. Non-completed appearances
    remain visible in the fold counts but do not enter a structural metric.
    """

    _require(isinstance(player_rows, pd.DataFrame), "attacking rows must be a DataFrame.")
    missing = sorted(_REQUIRED_COLUMNS - set(player_rows.columns))
    _require(not missing, f"attacking rows are missing columns {missing!r}.")
    _require(not player_rows.empty, "attacking rows are empty.")
    frame = player_rows.loc[:, sorted(_REQUIRED_COLUMNS)].copy(deep=True)
    _require(
        not bool(frame[["fold_id", "season", "player_id", "team_id"]].isna().any().any()),
        "attacking row identities must be complete.",
    )
    _require(
        not bool(frame.duplicated(["fold_id", "player_id"]).any()),
        "a fold repeats a selected player.",
    )
    seasons_per_fold = frame.groupby("fold_id", sort=False)["season"].nunique(dropna=False)
    _require(bool(seasons_per_fold.eq(1).all()), "a fold contains more than one season.")
    _require(frame["fold_id"].nunique() == 1, "build_fold_metrics expects exactly one fold.")

    completed = _binary(frame["completed_appearance"], "completed_appearance")
    blanks = _binary(frame["attacking_blank"], "attacking_blank")
    _require(
        not bool((blanks & ~completed).any()),
        "a non-completed appearance cannot be an attacking blank.",
    )
    probability_series = pd.to_numeric(frame["blank_probability"], errors="coerce")
    probabilities = probability_series.loc[completed].to_numpy(dtype="float64")
    _require(
        bool(np.isfinite(probabilities).all())
        and bool(((probabilities >= 0.0) & (probabilities <= 1.0)).all()),
        "completed-appearance blank_probability must be finite and lie in [0, 1].",
    )
    frame["completed_appearance"] = completed
    frame["attacking_blank"] = blanks
    frame["blank_probability"] = probability_series

    eligible = frame.loc[frame["completed_appearance"].astype(bool)].reset_index(drop=True)
    _require(not eligible.empty, "the fold contains no completed appearance.")
    x = eligible["attacking_blank"].to_numpy(dtype="float64")
    q = eligible["blank_probability"].to_numpy(dtype="float64")
    residual = x - q
    same_products: list[float] = []
    different_products: list[float] = []
    teams = eligible["team_id"].tolist()
    for left, right in combinations(range(len(eligible)), 2):
        product = float(residual[left] * residual[right])
        if teams[left] == teams[right]:
            same_products.append(product)
        else:
            different_products.append(product)
    unrelated = float(np.mean(different_products)) if different_products else float("nan")
    same = float(np.mean(same_products)) if same_products else float("nan")
    return {
        "fold_id": str(eligible["fold_id"].iloc[0]),
        "season": str(eligible["season"].iloc[0]),
        "selected_players": len(frame),
        "eligible_players": len(eligible),
        "blank_count": int(x.sum()),
        "non_blank_count": int(len(x) - x.sum()),
        "same_team_pairs": len(same_products),
        "different_team_pairs": len(different_products),
        "G": float(residual.mean()),
        "O": float((x.sum() - q.sum()) ** 2 - np.sum(q * (1.0 - q))),
        "U": unrelated,
        "K": same - unrelated if same_products and different_products else float("nan"),
    }


def _interval(values: Sequence[float]) -> dict[str, float]:
    _require(bool(values), "a structural metric has no eligible folds.")
    low, high = bootstrap_interval(
        values,
        resamples=BOOTSTRAP_RESAMPLES,
        seed=BOOTSTRAP_SEED,
        confidence_level=CONFIDENCE_LEVEL,
    )
    return {"mean": float(np.mean(values)), "bootstrap_low": low, "bootstrap_high": high}


def summarise(metrics: pd.DataFrame) -> dict[str, object]:
    """Return fold-bootstrap summaries and the support that produced them."""

    required = {
        "fold_id",
        "season",
        "eligible_players",
        "blank_count",
        "non_blank_count",
        "same_team_pairs",
        "different_team_pairs",
        *_METRICS,
    }
    _require(isinstance(metrics, pd.DataFrame), "fold metrics must be a DataFrame.")
    missing = sorted(required - set(metrics.columns))
    _require(not missing, f"fold metrics are missing columns {missing!r}.")
    _require(not metrics.empty, "fold metrics are empty.")
    _require(metrics["fold_id"].is_unique, "fold metrics repeat a fold.")

    summaries: dict[str, object] = {}
    support: dict[str, int] = {}
    for metric in _METRICS:
        values = pd.to_numeric(metrics[metric], errors="coerce")
        finite = values[np.isfinite(values.to_numpy(dtype="float64"))]
        support[metric] = len(finite)
        summaries[metric] = _interval([float(value) for value in finite]) if len(finite) else None
    return {
        "metrics": summaries,
        "support": {
            "folds": int(metrics["fold_id"].nunique()),
            "metric_folds": support,
            "eligible_players": int(metrics["eligible_players"].sum()),
            "blank_observations": int(metrics["blank_count"].sum()),
            "non_blank_observations": int(metrics["non_blank_count"].sum()),
            "same_team_pairs": int(metrics["same_team_pairs"].sum()),
            "different_team_pairs": int(metrics["different_team_pairs"].sum()),
        },
    }


def _reading(summary: Mapping[str, object], metric: str) -> Mapping[str, float]:
    metrics = cast(Mapping[str, object], summary["metrics"])
    value = metrics[metric]
    if not isinstance(value, Mapping):
        raise TypeError(f"metric {metric!r} is unavailable")
    return cast(Mapping[str, float], value)


def _adequate_support(summary: Mapping[str, object]) -> bool:
    support = cast(Mapping[str, object], summary["support"])
    metric_folds = cast(Mapping[str, object], support["metric_folds"])
    return bool(
        int(cast(int, metric_folds["G"])) >= MIN_EVALUATION_FOLDS
        and int(cast(int, metric_folds["O"])) >= MIN_EVALUATION_FOLDS
        and int(cast(int, metric_folds["U"])) >= MIN_EVALUATION_FOLDS
        and int(cast(int, metric_folds["K"])) >= MIN_EVALUATION_FOLDS
        and int(cast(int, support["blank_observations"])) > 0
        and int(cast(int, support["non_blank_observations"])) > 0
    )


def classify(validation: Mapping[str, object], sensitivity: Mapping[str, object]) -> str:
    """Apply the pre-registered hierarchy without ranking structural metrics."""

    try:
        if not _adequate_support(validation):
            return INCONCLUSIVE
        g = _reading(validation, "G")
        sensitivity_g = _reading(sensitivity, "G")
        low = float(g["bootstrap_low"])
        high = float(g["bootstrap_high"])
        sensitivity_g_mean = float(sensitivity_g["mean"])
        if low > MARGINAL_EQUIVALENCE_BOUNDS[1] and sensitivity_g_mean >= 0.0:
            return MARGINAL_BLANK_EXCESS
        if high < MARGINAL_EQUIVALENCE_BOUNDS[0] and sensitivity_g_mean <= 0.0:
            return WRONG_DIRECTION
        equivalent = (
            low >= MARGINAL_EQUIVALENCE_BOUNDS[0] and high <= MARGINAL_EQUIVALENCE_BOUNDS[1]
        )
        if not equivalent:
            return INCONCLUSIVE

        o = _reading(validation, "O")
        u = _reading(validation, "U")
        k = _reading(validation, "K")
        sensitivity_o = _reading(sensitivity, "O")
        sensitivity_u = _reading(sensitivity, "U")
        sensitivity_k = _reading(sensitivity, "K")
        common = bool(
            float(o["bootstrap_low"]) > 0.0
            and float(u["bootstrap_low"]) > 0.0
            and float(sensitivity_o["mean"]) >= 0.0
            and float(sensitivity_u["mean"]) >= 0.0
        )
        same_team = bool(float(k["bootstrap_low"]) > 0.0 and float(sensitivity_k["mean"]) >= 0.0)
    except (KeyError, TypeError, ValueError, OverflowError):
        return INCONCLUSIVE
    if common and same_team:
        return SHARED_REFERENCE_EXCESS
    if common:
        return COMMON_WEEK_REFERENCE_EXCESS
    if same_team:
        return SAME_TEAM_REFERENCE_EXCESS
    return NOT_LOCALIZED
