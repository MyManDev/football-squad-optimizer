"""Development-only direct DEFCON tail; no production model registration."""

from __future__ import annotations

import numpy as np
import pandas as pd

MODEL_ID = "football_defcon_shrinkage_dev_v1"
PRIOR_APPEARANCES = 10.0


def direct_tail(
    history: pd.DataFrame, target: pd.DataFrame, minute_mass: np.ndarray, cutoff: pd.Timestamp
) -> np.ndarray:
    """Estimate P(threshold | minute bin), then integrate forecast minute mass.

    Ten prior appearances shrink each player's bin to its position/bin frequency.
    Beta(1,1) smooths the position frequency, including empty training groups.
    All inputs are from declared development data. Target outcomes are never used.
    """
    cutoff = pd.Timestamp(cutoff)
    mass = np.asarray(minute_mass, dtype=float)
    if cutoff.tzinfo is None or mass.shape != (len(target), 4):
        raise ValueError("Require aware cutoff and four minute probabilities per target.")
    if (
        not np.isfinite(mass).all()
        or (mass < 0).any()
        or not np.allclose(mass.sum(axis=1), 1, atol=1e-8, rtol=0)
    ):
        raise ValueError("Invalid minute probability mass.")
    if len(target[["season", "GW"]].drop_duplicates()) != 1:
        raise ValueError("One decision week is required.")
    if not target.position.isin(["GK", "DEF", "MID", "FWD"]).all():
        raise ValueError("Unknown target position.")
    if history.duplicated(["season", "fixture", "player_code"]).any():
        raise ValueError("Duplicate historical player fixture.")
    season, week = target.iloc[0][["season", "GW"]]
    earlier = history.season.lt(season) | (history.season.eq(season) & history.GW.lt(week))
    past = history.loc[
        earlier & (pd.to_datetime(history.kickoff, utc=True) + pd.Timedelta(hours=3) < cutoff)
    ].copy()
    # Missing labels stay unknown, not failed events. Pre-rule seasons cannot train this head.
    past = past.loc[
        past.season.ge("2025-26")
        & past.minutes.gt(0)
        & past.position.ne("GK")
        & past.dc_event.notna()
    ].copy()
    if not past.dc_event.isin([0, 1]).all():
        raise ValueError("DEFCON labels must be binary or missing.")
    past["bin"] = np.select([past.minutes.lt(60), past.minutes.lt(90)], [1, 2], default=3)
    groups = past.groupby(["position", "bin"]).dc_event.agg(["sum", "count"]).to_dict("index")
    players = (
        past.groupby(["position", "bin", "player_code"])
        .dc_event.agg(["sum", "count"])
        .to_dict("index")
    )
    probability = np.zeros(len(target))
    for i, row in enumerate(target.itertuples()):
        if row.position == "GK":
            continue
        for minute_bin in (1, 2, 3):
            key = (row.position, minute_bin)
            pooled = groups.get(key, {"sum": 0, "count": 0})
            prior = (pooled["sum"] + 1) / (pooled["count"] + 2)
            player_key = (*key, row.player_code)
            own = players.get(player_key, {"sum": 0, "count": 0})
            probability[i] += (
                mass[i, minute_bin]
                * (own["sum"] + PRIOR_APPEARANCES * prior)
                / (own["count"] + PRIOR_APPEARANCES)
            )
    return probability
