"""Separate PL workload and venue candidate with explicit learned feature heads."""

from __future__ import annotations

from typing import Any, cast

import pandas as pd

from squadopt.prediction.football import FixtureFootballModel
from squadopt.prediction.football_features import (
    FEATURES,
    POS,
    RATE_LABELS,
    TEAM_FEATURES,
    football_features,
)
from squadopt.prediction.football_match_context_features import (
    CONTEXT_FEATURES,
    CONTEXT_TEAM_FEATURES,
    causal_match_context_features,
    match_context_feature_metadata,
)

MATCH_CONTEXT_MODEL_VERSION = "football_match_context_v1"
MATCH_CONTEXT_FEATURE_VERSION = "causal_pl_workload_venue_features_v1"
_BASE_HISTORY_COLUMNS = {
    "season",
    "GW",
    "fixture",
    "player_code",
    "position",
    "club",
    "opponent",
    "home",
    "kickoff",
    "minutes",
    "appeared",
    "long",
    *RATE_LABELS,
    "clean_sheets",
    "defensive_contribution",
    "dc_event",
    "team_goals",
    "team_conceded",
    "starts",
}


def match_context_metadata() -> dict[str, Any]:
    """Exact identity of this experiment, independent of a fitted coefficient value."""
    return {
        "model_version": MATCH_CONTEXT_MODEL_VERSION,
        "feature_contract_version": MATCH_CONTEXT_FEATURE_VERSION,
        "context_features": match_context_feature_metadata(),
        "minute_features": list(FEATURES + CONTEXT_FEATURES),
        "team_features": list(TEAM_FEATURES + CONTEXT_TEAM_FEATURES),
        "residual_features": list(FEATURES),
        "defensive_action_features": list(FEATURES),
        "availability_application": "external_once_per_player_week",
        "future_workload_policy": "completed_at_capture_only_no_future_minutes",
        "role_transition_policy": "unsupported",
    }


def match_context_features(
    history: pd.DataFrame, target: pd.DataFrame, cutoff: pd.Timestamp
) -> pd.DataFrame:
    """Use identical causal inputs for training folds and captured inference."""
    context = causal_match_context_features(history, target, cutoff)
    if target.empty:
        return pd.DataFrame(index=target.index, columns=FEATURES + CONTEXT_FEATURES, dtype=float)
    if history.columns.has_duplicates or not _BASE_HISTORY_COLUMNS.issubset(history.columns):
        raise ValueError(
            "Match context requires normalized football history columns, even if empty."
        )
    if "position" not in target or not target.position.isin(POS).all():
        raise ValueError("Match context targets require recorded football positions.")
    if target.season.nunique() != 1:
        raise ValueError("Match context features require one target season.")
    season = str(target.season.iloc[0])
    settled = history.kickoff + pd.Timedelta(hours=3) < cutoff
    base = pd.DataFrame(index=target.index, columns=FEATURES, dtype=float)
    # Assign by row position, so repeated caller index labels stay in their order.
    for key, positions in target.groupby("GW", sort=False).indices.items():
        week = int(cast(int, key))  # The context builder already validated integer-valued GWs.
        earlier = (history.season < season) | (history.season.eq(season) & history.GW.lt(week))
        part = football_features(history.loc[earlier & settled], target.iloc[positions], cutoff)
        base.iloc[positions] = part.to_numpy(float)
    return pd.concat([base, context], axis=1)


class MatchContextFootballModel(FixtureFootballModel):
    """Learn workload in minutes and venue/rest in club goals without a manual penalty."""

    model_version = MATCH_CONTEXT_MODEL_VERSION
    minute_features = FEATURES + CONTEXT_FEATURES
    team_features = TEAM_FEATURES + CONTEXT_TEAM_FEATURES

    def predict(self, target: pd.DataFrame, *, role_steps: int = 0) -> pd.DataFrame:
        if isinstance(role_steps, bool) or not isinstance(role_steps, int) or role_steps != 0:
            raise ValueError("Match context does not support role transitions.")
        result = super().predict(target, role_steps=0)
        # Captured eligibility is carried in the companion and applied by the reader.
        result["availability_multiplier"] = 1.0
        return result
