"""Forecast-only attacking-share sizing; never changes a model or reads outcomes."""

from typing import Any, Protocol, cast

import numpy as np
import pandas as pd

GO_THRESHOLD = 0.2


class ShareSizingBasis(Protocol):
    """Validated input supplied by the command, without importing the live layer."""

    @property
    def served(self) -> dict[str, object]: ...

    @property
    def companion(self) -> dict[str, object]: ...

    @property
    def fixture_rows(self) -> pd.DataFrame: ...


def size_attacking_shares(basis: ShareSizingBasis) -> tuple[dict[str, Any], pd.DataFrame]:
    """Apply the frozen #1009 readings to a validated, unapplied fixture basis."""
    served, companion = basis.served, basis.companion
    if served["season"] != "2026-27":
        raise ValueError("Sizing supports only the declared 2026-27 goal-point rules.")
    frame = basis.fixture_rows
    frame = frame.loc[frame.GW.eq(cast(int, served["gameweek"]))].copy()
    availability = companion["captured_availability"]
    assert isinstance(availability, dict)
    multipliers = {
        entry["player_code"]: entry["multiplier"] for entry in availability["multipliers"]
    }
    frame["multiplier"] = frame.player_code.map(multipliers)
    goal_points = frame.position.map({"GK": 10, "DEF": 6, "MID": 5, "FWD": 4})
    frame["base_attack"] = goal_points * frame.goals + 3 * frame.assists
    frame["lost_attack"] = (1 - frame.multiplier) * frame.base_attack
    candidate_attack = pd.Series(0.0, index=frame.index)
    for channel, points in (("goals", goal_points), ("assists", 3)):
        share = frame[channel + "_share"]
        total = (share * frame.multiplier).groupby([frame.fixture, frame.club]).transform("sum")
        denominator = share + total - frame.multiplier * share
        # With zero weight both the channel expectation and the gain are zero.
        ratio = np.divide(
            1.0,
            denominator.to_numpy(),
            out=np.zeros(len(frame)),
            where=denominator.to_numpy() > 0,
        )
        candidate_attack += points * frame[channel] * ratio
    frame["base_credited_attack"] = frame.multiplier * frame.base_attack
    frame["candidate_credited_attack"] = frame.multiplier * candidate_attack
    frame["gain"] = frame.candidate_credited_attack - frame.base_credited_attack
    available = frame.loc[frame.multiplier.gt(0)].groupby("player_code").gain.sum()
    clubs = frame.groupby("club").lost_attack.sum()
    threshold_count = int(available.ge(GO_THRESHOLD).sum())
    return {
        "snapshot_id": served["source_snapshot_id"],
        "model_version": served["model_version"],
        "season": served["season"],
        "gameweek": served["gameweek"],
        "captured_at_utc": served["captured_at_utc"],
        "forecast_fingerprint": served["fingerprint"],
        "companion_fingerprint": companion["fingerprint"],
        "s1_total": float(frame.lost_attack.sum()),
        "s1_by_club": {str(int(cast(int, club))): float(value) for club, value in clubs.items()},
        "available_players_with_fixtures": len(available),
        "s2_maximum": float(available.max()) if len(available) else 0.0,
        "s2_players_at_threshold": threshold_count,
        "go_threshold": GO_THRESHOLD,
        "go": threshold_count > 0,
    }, frame
