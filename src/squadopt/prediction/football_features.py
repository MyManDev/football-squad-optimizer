"""History-only fixture features for the versioned football candidate.

Callers supply immutable, normalized player-fixture history with persistent player/club
IDs. Targets supply identity, position and venue only. No target outcomes are inspected.
Training folds must additionally exclude the target gameweek (not just later kickoffs).
"""

from __future__ import annotations

from typing import cast

import pandas as pd

POS = ("GK", "DEF", "MID", "FWD")
RATE_LABELS = ("goals_scored", "assists", "expected_goals", "expected_assists")
BASE_FEATURES = (
    "past_apps",
    "past_rows",
    "mean_minutes",
    "appearance_rate",
    "long_rate",
    "goals_scored_rate",
    "assists_rate",
    "expected_goals_rate",
    "expected_assists_rate",
    "dc_rate",
    "dc_known_apps",
    "cs_prior",
    "dc_prior",
    "own_gf",
    "own_ga",
    "own_xgf",
    "own_xga",
    "opp_gf",
    "opp_ga",
    "opp_xgf",
    "opp_xga",
    "home",
    "pos_GK",
    "pos_DEF",
    "pos_MID",
    "pos_FWD",
)

RECENT = (
    "recent3_minutes",
    "recent5_minutes",
    "recent3_appear",
    "recent5_appear",
    "recent3_long",
    "recent5_long",
    "last_minutes",
    "recent5_start",
    "days_since_appear",
    "season_rows",
)
FEATURES = BASE_FEATURES + RECENT
TEAM_FEATURES = (
    "own_gf",
    "own_ga",
    "own_xgf",
    "own_xga",
    "opp_gf",
    "opp_ga",
    "opp_xgf",
    "opp_xga",
    "home",
)


def ratio_lookup(
    summary: pd.DataFrame, key: object, numerator: str, denominator: str, default: float = 0.0
) -> float:
    if key not in summary.index or float(cast(float, summary.at[key, denominator])) <= 0:
        return default
    return float(
        cast(float, summary.at[key, numerator]) / cast(float, summary.at[key, denominator])
    )


def _long_features(history: pd.DataFrame, target: pd.DataFrame) -> pd.DataFrame:
    """Only history labels are inspected; target contributes identity/venue/position."""
    h = history.copy()
    numeric = ["minutes", "appeared", "long", *RATE_LABELS]
    h["rows"] = 1.0
    player = h.groupby("player_code")[[*numeric, "rows"]].sum()
    positions = h.groupby("position")[[*numeric, "rows"]].sum()
    eligible_cs = h.loc[h.long.eq(1)]
    cs_player = eligible_cs.groupby("player_code").clean_sheets.agg(["sum", "count"])
    cs_pos = eligible_cs.groupby("position").clean_sheets.mean()
    dc = h.loc[h.defensive_contribution.notna() & h.appeared.eq(1) & h.position.ne("GK")]
    dc_player = dc.groupby("player_code").agg(
        actions=("defensive_contribution", "sum"),
        minutes=("minutes", "sum"),
        event=("dc_event", "sum"),
        apps=("appeared", "sum"),
    )
    dc_pos = dc.groupby("position").agg(
        actions=("defensive_contribution", "sum"),
        minutes=("minutes", "sum"),
        event=("dc_event", "sum"),
        apps=("appeared", "sum"),
    )
    # One club-match, not one player, per observation of team strength.
    teams = h.groupby(["season", "fixture", "club"], as_index=False).agg(
        opponent=("opponent", "first"),
        kickoff=("kickoff", "first"),
        gf=("team_goals", "first"),
        ga=("team_conceded", "first"),
        xgf=("expected_goals", "sum"),
    )
    against = teams[["season", "fixture", "opponent", "xgf"]].rename(
        columns={"opponent": "club", "xgf": "xga"}
    )
    teams = teams.merge(against, on=["season", "fixture", "club"], validate="one_to_one")
    recent = teams.sort_values("kickoff").groupby("club").tail(10)
    strength = recent.groupby("club")[["gf", "ga", "xgf", "xga"]].mean()
    league = teams[["gf", "ga", "xgf", "xga"]].mean().fillna(0)
    rows = []
    for row in target[["player_code", "position", "club", "opponent", "home"]].itertuples(
        index=False
    ):
        pid, pos, club, opp, home = row
        p = player.loc[pid] if pid in player.index else pd.Series(0.0, index=[*numeric, "rows"])
        group = (
            positions.loc[pos]
            if pos in positions.index
            else pd.Series(0.0, index=[*numeric, "rows"])
        )
        apps, n = float(p.appeared), float(p.rows)
        record = {
            "past_apps": apps,
            "past_rows": n,
            "mean_minutes": float(
                (p.minutes + 10 * (group.minutes / max(group.rows, 1))) / (n + 10)
            ),
            "appearance_rate": float(
                (apps + 10 * (group.appeared / max(group.rows, 1))) / (n + 10)
            ),
            "long_rate": float((p.long + 10 * (group.long / max(group.rows, 1))) / (n + 10)),
            "home": float(home),
        }
        for label in RATE_LABELS:
            prior90 = float(group[label] / max(group.minutes, 1) * 90)
            record[label + "_rate"] = float((p[label] + 10 * prior90) / (p.minutes / 90 + 10))
        cs_prior = float(cs_pos.get(pos, 0.0))
        if pid in cs_player.index:
            cs_prior = float(
                (cast(float, cs_player.at[pid, "sum"]) + 10 * cs_prior)
                / (cast(float, cs_player.at[pid, "count"]) + 10)
            )
        record["cs_prior"] = cs_prior
        rate = ratio_lookup(dc_pos, pos, "actions", "minutes") * 90
        prior_dc = ratio_lookup(dc_pos, pos, "event", "apps")
        if pid in dc_player.index:
            rate = float(
                (cast(float, dc_player.at[pid, "actions"]) + 10 * rate)
                / (cast(float, dc_player.at[pid, "minutes"]) / 90 + 10)
            )
            prior_dc = float(
                (cast(float, dc_player.at[pid, "event"]) + 10 * prior_dc)
                / (cast(float, dc_player.at[pid, "apps"]) + 10)
            )
        record.update(
            dc_rate=rate,
            dc_prior=prior_dc,
            dc_known_apps=float(cast(float, dc_player.at[pid, "apps"]))
            if pid in dc_player.index
            else 0.0,
        )
        for prefix, team in (("own", club), ("opp", opp)):
            stats = strength.loc[team] if team in strength.index else league
            record.update({prefix + "_" + c: float(stats[c]) for c in ("gf", "ga", "xgf", "xga")})
        record.update({"pos_" + p: float(pos == p) for p in POS})
        rows.append(record)
    return pd.DataFrame(rows, index=target.index, columns=BASE_FEATURES)


def football_features(
    history: pd.DataFrame, target: pd.DataFrame, cutoff: pd.Timestamp
) -> pd.DataFrame:
    if cutoff.tzinfo is None:
        raise ValueError("Football feature cutoff must be timezone-aware.")
    if not history.empty and not (history.kickoff + pd.Timedelta(hours=3) < cutoff).all():
        raise ValueError("History includes unavailable match outcomes.")
    if target.empty:
        return pd.DataFrame(index=target.index, columns=FEATURES, dtype=float)
    base = _long_features(history, target)
    ordered = history.sort_values(["kickoff", "fixture"], kind="stable")
    lookup = {}
    for w in (3, 5):
        recent = ordered.groupby("player_code", sort=False).tail(w)
        grouped = recent.groupby("player_code")
        for label, col in [("minutes", "minutes"), ("appear", "appeared"), ("long", "long")]:
            lookup[f"recent{w}_{label}"] = grouped[col].mean()
        if w == 5:
            lookup["recent5_start"] = grouped.starts.mean()
    last = ordered.groupby("player_code").tail(1).set_index("player_code")
    lookup["last_minutes"] = last.minutes
    last_app = ordered.loc[ordered.appeared.eq(1)].groupby("player_code").kickoff.max()
    lookup["days_since_appear"] = ((cutoff - last_app).dt.total_seconds() / 86400).clip(0, 365)
    lookup["season_rows"] = (
        history.loc[history.season.eq(str(target.season.iloc[0]))].groupby("player_code").size()
    )
    for col in RECENT:
        base[col] = (
            target.player_code.map(lookup[col])
            .fillna(365 if col == "days_since_appear" else 0)
            .to_numpy(float)
        )
    return base
