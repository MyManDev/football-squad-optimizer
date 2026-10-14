"""Causal club form for an explicitly selected fixture-football experiment."""

from __future__ import annotations

import numpy as np
import pandas as pd

from squadopt.prediction.football import FixtureFootballModel
from squadopt.prediction.football_features import TEAM_FEATURES, football_features

TEAM_FORM_MODEL_VERSION = "football_team_form_v1"
TEAM_FORM_FEATURE_VERSION = "causal_football_fixture_team_form_features_v1"
FORM_WINDOWS = (3, 5)
SEASON_METRICS = (
    "matches",
    "wins",
    "draws",
    "losses",
    "points_per_match",
    "gf",
    "ga",
    "xgf",
    "xga",
    "clean_sheet_rate",
)
RECENT_METRICS = (
    "matches",
    "points_per_match",
    "win_rate",
    "clean_sheet_rate",
    "gf",
    "ga",
    "xgf",
    "xga",
    "gd",
    "xgd",
)
FORM_METRICS = tuple("form_season_" + name for name in SEASON_METRICS) + tuple(
    f"form_recent{window}_{name}" for window in FORM_WINDOWS for name in RECENT_METRICS
)
FORM_FEATURES = tuple(prefix + "_" + name for prefix in ("own", "opp") for name in FORM_METRICS)
# Counts expose cold starts; rates describe form. The remaining metrics are diagnostics,
# not additional correlated inputs to the fitted team head.
FORM_HEAD_METRICS = (
    "form_season_matches",
    "form_season_points_per_match",
    "form_season_clean_sheet_rate",
    "form_recent5_points_per_match",
    "form_recent5_clean_sheet_rate",
    "form_recent5_gf",
    "form_recent5_ga",
    "form_recent5_xgf",
    "form_recent5_xga",
)
FORM_HEAD_FEATURES = TEAM_FEATURES + tuple(
    prefix + "_" + name for prefix in ("own", "opp") for name in FORM_HEAD_METRICS
)


def team_form_metadata() -> dict[str, object]:
    return {
        "feature_contract_version": TEAM_FORM_FEATURE_VERSION,
        "windows": list(FORM_WINDOWS),
        "population": "target_season_completed_paired_club_fixtures",
        "availability_lag_hours": 3,
        "head_features": list(FORM_HEAD_FEATURES),
        "empty_history": "zero_metrics_with_zero_match_count",
    }


def _gameweeks(frame: pd.DataFrame, label: str) -> pd.Series:
    if "GW" not in frame or frame.GW.isna().any():
        raise ValueError(f"Club form {label} requires complete gameweek identity.")
    weeks = pd.to_numeric(frame.GW, errors="coerce").to_numpy(dtype=float)
    if (
        frame.GW.map(lambda value: isinstance(value, (bool, np.bool_))).any()
        or not np.isfinite(weeks).all()
        or (weeks < 1).any()
        or (weeks > 38).any()
        or not np.equal(weeks, np.floor(weeks)).all()
    ):
        raise ValueError(f"Club form {label} gameweek must be an integer from 1 to 38.")
    return pd.Series(weeks, index=frame.index)


def _matches(history: pd.DataFrame, cutoff: pd.Timestamp) -> pd.DataFrame:
    columns = [
        "season",
        "GW",
        "fixture",
        "club",
        "opponent",
        "home",
        "kickoff",
        "team_goals",
        "team_conceded",
    ]
    if history.empty:
        return pd.DataFrame(columns=[*columns, "gf", "ga", "xgf", "xga", "points", "win", "clean"])
    required = [*columns, "player_code", "expected_goals"]
    if any(name not in history for name in required) or history[required].isna().any().any():
        raise ValueError("Club form requires complete paired fixture history.")
    if history.duplicated(["season", "fixture", "player_code"]).any():
        raise ValueError("Duplicate player-fixture club form history.")
    if any(pd.Timestamp(value).tzinfo is None for value in history.kickoff):
        raise ValueError("Club form kickoff must be timezone-aware.")
    h = history.copy()
    h["GW"] = _gameweeks(history, "history")
    h["kickoff"] = pd.to_datetime(h.kickoff, utc=True)
    if not (h.kickoff + pd.Timedelta(hours=3) < cutoff).all():
        raise ValueError("Club form history contains unavailable match outcomes.")
    goals = h[["team_goals", "team_conceded"]].to_numpy(dtype=float)
    xg = h.expected_goals.to_numpy(dtype=float)
    if (
        not np.isfinite(goals).all()
        or (goals < 0).any()
        or not np.equal(goals, np.floor(goals)).all()
    ):
        raise ValueError("Club form paired scores must be nonnegative integers.")
    if not np.isfinite(xg).all() or (xg < 0).any():
        raise ValueError("Club form player xG must be finite and nonnegative.")
    keys = ["season", "fixture", "club"]
    consistent = h.groupby(keys)[
        ["GW", "opponent", "home", "kickoff", "team_goals", "team_conceded"]
    ].nunique()
    if not consistent.eq(1).all().all():
        raise ValueError("Club form history has inconsistent paired fixture sides.")
    matches = h.groupby(keys, as_index=False).agg(
        GW=("GW", "first"),
        opponent=("opponent", "first"),
        home=("home", "first"),
        kickoff=("kickoff", "first"),
        gf=("team_goals", "first"),
        ga=("team_conceded", "first"),
        xgf=("expected_goals", "sum"),
    )
    for _, pair in matches.groupby(["season", "fixture"]):
        if (
            len(pair) != 2
            or pair.club.nunique() != 2
            or set(pair.home) != {0, 1}
            or set(pair.club) != set(pair.opponent)
            or not pair.club.ne(pair.opponent).all()
            or pair.GW.nunique() != 1
            or pair.kickoff.nunique() != 1
        ):
            raise ValueError("Club form requires two consistent opposing fixture sides.")
        a, b = pair.iloc[0], pair.iloc[1]
        if a.gf != b.ga or a.ga != b.gf:
            raise ValueError("Club form paired scores disagree.")
    opposing = matches[["season", "fixture", "opponent", "xgf"]].rename(
        columns={"opponent": "club", "xgf": "xga"}
    )
    matches = matches.merge(opposing, on=keys, validate="one_to_one")
    matches["win"] = matches.gf.gt(matches.ga).astype(float)
    matches["draw"] = matches.gf.eq(matches.ga).astype(float)
    matches["clean"] = matches.ga.eq(0).astype(float)
    matches["points"] = 3 * matches.win + matches.draw
    return matches.sort_values(["kickoff", "fixture"], kind="stable")


def _summary(matches: pd.DataFrame) -> dict[str, float]:
    result = {name: 0.0 for name in FORM_METRICS}
    if matches.empty:
        return result
    n = len(matches)
    result.update(
        {
            "form_season_matches": float(n),
            "form_season_wins": float(matches.win.sum()),
            "form_season_draws": float(matches.draw.sum()),
            "form_season_losses": float(n - matches.win.sum() - matches.draw.sum()),
            "form_season_points_per_match": float(matches.points.mean()),
            "form_season_clean_sheet_rate": float(matches.clean.mean()),
        }
    )
    for name in ("gf", "ga", "xgf", "xga"):
        result["form_season_" + name] = float(matches[name].mean())
    for window in FORM_WINDOWS:
        recent = matches.tail(window)
        prefix = f"form_recent{window}_"
        result[prefix + "matches"] = float(len(recent))
        result[prefix + "points_per_match"] = float(recent.points.mean())
        result[prefix + "win_rate"] = float(recent.win.mean())
        result[prefix + "clean_sheet_rate"] = float(recent.clean.mean())
        for name in ("gf", "ga", "xgf", "xga"):
            result[prefix + name] = float(recent[name].mean())
        result[prefix + "gd"] = float((recent.gf - recent.ga).mean())
        result[prefix + "xgd"] = float((recent.xgf - recent.xga).mean())
    return result


def team_form_features(
    history: pd.DataFrame, target: pd.DataFrame, cutoff: pd.Timestamp
) -> pd.DataFrame:
    """Target results never enter club form; cold starts carry their zero sample count."""
    if cutoff.tzinfo is None:
        raise ValueError("Club form cutoff must be timezone-aware.")
    if target.empty:
        return pd.DataFrame(index=target.index, columns=FORM_FEATURES, dtype=float)
    if any(name not in target for name in ("season", "GW", "club", "opponent")):
        raise ValueError("Club form targets require season, gameweek, club and opponent identity.")
    if (
        target[["season", "club", "opponent"]].isna().any().any()
        or target.club.eq(target.opponent).any()
    ):
        raise ValueError("Club form targets require distinct complete club identities.")
    target_identity = target[["season", "GW", "club", "opponent"]].copy()
    target_identity["GW"] = _gameweeks(target, "target")
    matches = _matches(history, cutoff)
    if not matches.empty:
        for season, targets in target_identity.groupby("season"):
            if (matches.loc[matches.season.eq(season), "GW"] >= targets.GW.min()).any():
                raise ValueError("Club form history includes the target gameweek or a later week.")
    lookup = {key: _summary(group) for key, group in matches.groupby(["season", "club"])}
    empty = _summary(pd.DataFrame())
    rows = []
    for row in target[["season", "club", "opponent"]].itertuples(index=False):
        record = {}
        for prefix, club in (("own", row.club), ("opp", row.opponent)):
            summary = lookup.get((row.season, club), empty)
            record.update({prefix + "_" + name: summary[name] for name in FORM_METRICS})
        rows.append(record)
    return pd.DataFrame(rows, index=target.index, columns=FORM_FEATURES, dtype=float)


def football_team_form_features(
    history: pd.DataFrame, target: pd.DataFrame, cutoff: pd.Timestamp
) -> pd.DataFrame:
    return pd.concat(
        [football_features(history, target, cutoff), team_form_features(history, target, cutoff)],
        axis=1,
    )


class TeamFormFootballModel(FixtureFootballModel):
    """Use learned club-form coefficients only in the optional team-goal head."""

    model_version = TEAM_FORM_MODEL_VERSION
    team_features = FORM_HEAD_FEATURES

    def predict(self, target: pd.DataFrame, *, role_steps: int = 0) -> pd.DataFrame:
        if role_steps:
            raise ValueError("The team-form variant does not combine role-transition experiments.")
        result = super().predict(target, role_steps=role_steps)
        result["availability_multiplier"] = 1.0
        return result
