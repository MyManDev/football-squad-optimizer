"""Descriptive, whole-gameweek statistics for the frozen Top-100 protocol.

No fitting, solver, data access or promotion. A read-out weight is never a policy.
"""

import json
from collections.abc import Mapping
from typing import Any

import numpy as np
import pandas as pd

RESAMPLES = 2000
SEED = 0
MINIMUM_WEEKS = 6
TOP_PER_POSITION = 40


def _interval(numerator: np.ndarray, denominator: np.ndarray) -> list[float] | None:
    if len(numerator) < MINIMUM_WEEKS:
        return None
    rng = np.random.default_rng(SEED)
    indices = rng.integers(0, len(numerator), size=(RESAMPLES, len(numerator)))
    top, bottom = numerator[indices].sum(axis=1), denominator[indices].sum(axis=1)
    # Do not quietly drop unidentified bootstrap draws and narrow the interval.
    if bool((bottom <= 0).any()):
        return None
    return [float(x) for x in np.quantile(top / bottom, [0.05, 0.95])]


def _ratio(top: pd.Series, bottom: pd.Series) -> float | None:
    total = float(bottom.sum())
    return float(top.sum()) / total if total > 0 else None


def _reading(frame: pd.DataFrame) -> dict[str, Any]:
    groups = frame.groupby(["gameweek", "position"], observed=True, sort=True)
    x = frame.m * frame.s
    residual = frame.y - frame.m
    working = frame.assign(x=x, residual=residual)
    centered = working[["x", "residual"]] - working.groupby(
        ["gameweek", "position"], observed=True
    )[["x", "residual"]].transform("mean")
    terms = (
        pd.DataFrame(
            {
                "gameweek": frame.gameweek,
                "numerator": centered.x * centered.residual,
                "denominator": centered.x**2,
            }
        )
        .groupby("gameweek")
        .sum()
    )
    rank_groups = []
    for (week, position), block in groups:
        selected = block.sort_values(
            ["m", "player_id"], ascending=[False, True], kind="stable"
        ).head(TOP_PER_POSITION)
        support = selected.s.rank(method="average")
        errors = (selected.y - selected.m).rank(method="average")
        rho = (
            float(support.corr(errors))
            if len(selected) >= 2 and support.nunique() > 1 and errors.nunique() > 1
            else None
        )
        rank_groups.append(
            {
                "gameweek": int(str(week)),
                "position": str(position),
                "rows": len(selected),
                "rho": rho,
            }
        )
    valid = pd.DataFrame([row for row in rank_groups if row["rho"] is not None])
    if valid.empty:
        rank_mean, rank_interval = None, None
    else:
        rank_terms = valid.groupby("gameweek").rho.agg(["sum", "count"])
        # Include weeks whose ranking is wholly unidentified as zero contributing groups.
        rank_terms = rank_terms.reindex(terms.index, fill_value=0)
        rank_mean = _ratio(rank_terms["sum"], rank_terms["count"])
        rank_interval = _interval(rank_terms["sum"].to_numpy(), rank_terms["count"].to_numpy())
    weeks = len(terms)
    return {
        "rows": len(frame),
        "gameweeks": weeks,
        "weight_slope": _ratio(terms.numerator, terms.denominator),
        "weight_slope_interval90": _interval(
            terms.numerator.to_numpy(), terms.denominator.to_numpy()
        ),
        "rank_mean": rank_mean,
        "rank_interval90": rank_interval,
        "rank_groups": rank_groups,
        "interval_note": (
            "Fewer than six gameweeks: no interval."
            if weeks < MINIMUM_WEEKS
            else f"{weeks} gameweek clusters: a rough interval, not independent player rows."
        ),
    }


def player_reading(frame: pd.DataFrame) -> dict[str, Any]:
    """Read A/B on all and appeared rows; absence from evidence has already become s=0."""
    required = ["gameweek", "player_id", "position", "m", "s", "y", "minutes"]
    if set(required) - set(frame.columns):
        raise ValueError("Missing player reading columns.")
    if frame.duplicated(["gameweek", "player_id"]).any():
        raise ValueError("Repeated player-gameweek.")
    numeric = frame[["m", "s", "y", "minutes"]].to_numpy(dtype=float)
    if not np.isfinite(numeric).all() or (frame.m < 0).any() or (frame.minutes < 0).any():
        raise ValueError("Invalid player reading values.")
    if not frame.s.between(0, 1).all():
        raise ValueError("Support must be in [0, 1].")
    mass = frame.m * frame.s
    total = float(mass.sum())
    return {
        "all": _reading(frame),
        "appeared": _reading(frame.loc[frame.minutes > 0]),
        "support_weighted_mass": total,
        "nonplayer_share": float(mass.loc[frame.minutes == 0].sum()) / total if total > 0 else None,
    }


def plan_changed(base: Mapping[str, Any], weighted: Mapping[str, Any]) -> bool:
    """Pitch order is cosmetic; bench order, vice, chip and actual charge are not."""
    if set(base["starting_xi"]) != set(weighted["starting_xi"]):
        return True
    if any(
        base.get(key) != weighted.get(key)
        for key in ("bench", "captain", "vice_captain", "chip", "transfer_hit_points")
    ):
        return True
    # Recorded moves carry dictionaries; their ordering is not part of the decision.
    return sorted(json.dumps(x, sort_keys=True) for x in base.get("moves", [])) != sorted(
        json.dumps(x, sort_keys=True) for x in weighted.get("moves", [])
    )


def plan_reading(pairs: pd.DataFrame) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for weight, rows in pairs.groupby("weight", sort=True):
        terms = rows.groupby("gameweek").difference.agg(["sum", "count"])
        changed = rows.loc[rows.changed]
        prices = rows.published_cost.dropna()
        result[str(int(str(weight)))] = {
            "pairs": len(rows),
            "changed_pairs": len(changed),
            "gameweeks": len(terms),
            "mean_difference": float(rows.difference.mean()),
            "mean_difference_changed": float(changed.difference.mean()) if len(changed) else None,
            "wins": int((rows.difference > 0).sum()),
            "ties": int((rows.difference == 0).sum()),
            "losses": int((rows.difference < 0).sum()),
            "interval90": _interval(terms["sum"].to_numpy(), terms["count"].to_numpy()),
            "published_cost_missing": len(rows) - len(prices),
            "mean_published_cost_same_pairs": float(prices.mean())
            if len(prices) == len(rows)
            else None,
            "interval_note": (
                "Fewer than six gameweeks: no interval."
                if len(terms) < MINIMUM_WEEKS
                else f"{len(terms)} gameweek clusters: rough, direction only; "
                "cannot resolve tenths of a point."
            ),
        }
    return result
