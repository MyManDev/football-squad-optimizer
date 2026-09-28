"""Paired development losses for sums of frozen player-fixture forecasts."""

from __future__ import annotations

import numpy as np
import pandas as pd

KEYS = ["season", "fixture", "player_code"]


def paired_window_losses(
    control: pd.DataFrame, candidate: pd.DataFrame, actual: pd.DataFrame
) -> dict[str, dict[str, float | int]]:
    """Exclude an incomplete player's entire sum, equally in both arms.

    The caller selects the origin and window. Blank fixtures have no rows here;
    this measures players represented in the frozen fixture forecasts, not an
    invented full roster. Unknown outcomes never become zero points.
    """
    for frame in (control, candidate, actual):
        if frame[KEYS].isna().any().any() or frame.duplicated(KEYS).any():
            raise ValueError("Fixture keys must be known and unique.")
    left = control.set_index(KEYS).sort_index()
    right = candidate.set_index(KEYS).sort_index()
    if left.empty or not left.index.equals(right.index):
        raise ValueError("Both arms must cover the same nonempty fixture keys.")
    if not np.isfinite(left.expected_points).all() or not np.isfinite(right.expected_points).all():
        raise ValueError("Forecasts must be finite; missing forecasts cannot be dropped.")
    observed = actual.set_index(KEYS).total_points.reindex(left.index)
    if not np.isfinite(observed.dropna()).all():
        raise ValueError("Known outcomes must be finite.")
    by_player = ["season", "player_code"]
    complete = observed.notna().groupby(level=by_player).all()
    totals = observed.groupby(level=by_player).sum(min_count=1).loc[complete]
    if totals.empty:
        raise ValueError("No fully observed player sum remains.")
    result = {}
    for name, forecast in (("v1", left), ("contextual", right)):
        predicted = forecast.expected_points.groupby(level=by_player).sum().loc[complete]
        delta = predicted - totals
        fixture_delta = forecast.expected_points - observed
        result[name] = {
            "fixture_rows": len(left),
            "missing_fixture_labels": int(observed.isna().sum()),
            "represented_players": len(complete),
            "complete_players": int(complete.sum()),
            "excluded_incomplete_players": int((~complete).sum()),
            "fixture_mse": float((fixture_delta.dropna() ** 2).mean()),
            "sum_mse": float((delta**2).mean()),
            "sum_mae": float(delta.abs().mean()),
            "sum_bias": float(delta.mean()),
        }
    return result
