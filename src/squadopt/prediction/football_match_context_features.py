"""Causal PL workload and venue context from recorded player-fixture history.

Counts describe the supplied PL observations, not an all-competition calendar.
Unknown labels remain unknown; target rows contribute identity and venue only.
"""

from __future__ import annotations

import math
import re
from numbers import Real
from typing import Any, cast

import numpy as np
import pandas as pd

MATCH_CONTEXT_FEATURE_CONTRACT = "football_pl_match_context_features_v1"
WORKLOAD_WINDOWS_DAYS = (7, 14)
_WORKLOAD_SUFFIXES = (
    "minutes",
    "minutes_known_rows",
    "minutes_missing",
    "appearances",
    "appearances_known_rows",
    "appearances_missing",
    "starts",
    "starts_known_rows",
    "starts_missing",
    "observations",
)
_CLUB_SUFFIXES = (
    "pl_7d_fixtures",
    "pl_14d_fixtures",
    "pl_observed_fixtures",
    "pl_days_since_match",
    "pl_match_history_missing",
)
_VENUE_METRICS = ("gf", "ga", "xgf", "xga")
_VENUE_SUFFIXES = (
    "venue_matches",
    *(
        column
        for metric in _VENUE_METRICS
        for column in (
            f"venue_{metric}",
            f"venue_{metric}_known_matches",
            f"venue_{metric}_missing",
        )
    ),
)
CONTEXT_TEAM_FEATURES = tuple(
    f"{side}_{suffix}" for side in ("own", "opp") for suffix in (*_CLUB_SUFFIXES, *_VENUE_SUFFIXES)
)
CONTEXT_FEATURES = (
    tuple(
        f"player_pl_{days}d_{suffix}"
        for days in WORKLOAD_WINDOWS_DAYS
        for suffix in _WORKLOAD_SUFFIXES
    )
    + CONTEXT_TEAM_FEATURES
)
_IDENTITY_COLUMNS = ("season", "GW", "fixture", "player_code", "club", "opponent", "home")
_LABEL_COLUMNS = ("minutes", "starts", "team_goals", "team_conceded", "expected_goals")
_HISTORY_COLUMNS = (*_IDENTITY_COLUMNS, "kickoff", *_LABEL_COLUMNS)
_SEASON = re.compile(r"^\d{4}-\d{2}$")


def match_context_feature_metadata() -> dict[str, object]:
    """Return the exact feature definition, freshly allocated for artifact binding."""
    return {
        "contract": MATCH_CONTEXT_FEATURE_CONTRACT,
        "features": list(CONTEXT_FEATURES),
        "team_features": list(CONTEXT_TEAM_FEATURES),
        "scope": "observed_premier_league_player_fixture_history_only",
        "workload_windows_days": list(WORKLOAD_WINDOWS_DAYS),
        "window_start": "inclusive_kickoff_at_cutoff_minus_calendar_days",
        "settlement_lag_hours": 3,
        "settlement_boundary": "kickoff_plus_lag_strictly_before_cutoff",
        "history_season": "same_target_season_only",
        "gameweek_filter": "history_gameweek_strictly_before_target_gameweek",
        "club_fixture_key": ["season", "fixture", "club"],
        "venue_conditioning": {"own": "target_home", "opp": "opposite_target_home"},
        "starts": "recorded_starts_only_never_inferred_from_minutes",
        "appearances": "positive_recorded_minutes_only",
        "missing_numeric_value": 0.0,
        "player_missing_flag": "no_known_label_or_any_missing_label_in_window",
        "venue_missing_flag": "no_known_metric_or_any_missing_metric_in_venue_sample",
        "club_missing_flag": "no_observed_club_fixture_in_same_season_before_target_week",
        "club_window_zero": "zero_observed_fixtures_not_certified_calendar_coverage",
        "xg": "sum_of_provided_player_rows_only_unknown_if_any_row_label_is_missing",
        "days_since_match": "elapsed_days_from_last_observed_club_kickoff_to_cutoff",
        "target_outcomes": "never_read",
        "future_calendar": "not_used",
        "all_competition_coverage": False,
    }


def _required(frame: pd.DataFrame, columns: tuple[str, ...], kind: str) -> pd.DataFrame:
    if frame.columns.has_duplicates:
        raise ValueError(f"Match context {kind} columns must be unique.")
    missing = [column for column in columns if column not in frame]
    if missing:
        raise ValueError(f"Match context {kind} lacks columns {missing}.")
    return frame.loc[:, list(columns)].copy()


def _integer(value: object, *, field: str, upper: int | None = None) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, Real)
        or not math.isfinite(float(value))
        or float(value) <= 0
        or not float(value).is_integer()
        or (upper is not None and float(value) > upper)
    ):
        raise ValueError(f"Match context {field} requires positive integer identities.")
    return int(cast(Any, value))


def _identities(frame: pd.DataFrame, kind: str) -> pd.DataFrame:
    result = frame.copy()
    for field in ("GW", "fixture", "player_code", "club", "opponent"):
        result[field] = result[field].map(
            lambda value, field=field: _integer(
                value, field=field, upper=38 if field == "GW" else None
            )
        )
    seasons = result.season.map(
        lambda value: (
            isinstance(value, str)
            and _SEASON.fullmatch(value) is not None
            and int(value[-2:]) == (int(value[:4]) + 1) % 100
        )
    )
    if not seasons.all():
        raise ValueError(f"Match context {kind} seasons require consecutive YYYY-YY identities.")
    if not result.home.map(
        lambda value: (
            not isinstance(value, bool)
            and isinstance(value, Real)
            and math.isfinite(float(value))
            and value in (0, 1)
        )
    ).all():
        raise ValueError(f"Match context {kind} home requires a recorded zero or one.")
    result["home"] = result.home.astype(float)
    if result.club.eq(result.opponent).any():
        raise ValueError(f"Match context {kind} club and opponent must differ.")
    if result.duplicated(["season", "fixture", "player_code"]).any():
        raise ValueError(f"Match context {kind} repeats a player-fixture identity.")
    if kind == "target":
        for _, fixture in result.groupby(["season", "fixture"], sort=False):
            if fixture.GW.nunique() != 1:
                raise ValueError(
                    "Match context target fixture has inconsistent gameweek identities."
                )
            for _, club in fixture.groupby("club", sort=False):
                if club.home.nunique() != 1 or club.opponent.nunique() != 1:
                    raise ValueError("Match context target club-fixture identity is inconsistent.")
            if fixture.club.nunique() > 1:
                sides = fixture.drop_duplicates("club")
                if (
                    len(sides) != 2
                    or sides.home.sum() != 1
                    or set(sides.club) != set(sides.opponent)
                ):
                    raise ValueError("Match context target paired-club identity is inconsistent.")
    return result


def _kickoff(value: object) -> pd.Timestamp:
    try:
        parsed = pd.Timestamp(cast(Any, value))
    except (TypeError, ValueError, OverflowError) as error:
        raise ValueError("Match context kickoff must be a timezone-aware instant.") from error
    if pd.isna(parsed) or parsed.tzinfo is None:
        raise ValueError("Match context kickoff must be a timezone-aware instant.")
    return parsed.tz_convert("UTC")


def _labels(history: pd.DataFrame) -> pd.DataFrame:
    result = history.copy()
    for column in _LABEL_COLUMNS:
        if result[column].map(lambda value: isinstance(value, bool)).any():
            raise ValueError(f"Match context {column} contains a boolean label.")
        try:
            values = pd.to_numeric(result[column], errors="raise").astype(float)
        except (TypeError, ValueError, OverflowError) as error:
            raise ValueError(
                f"Match context {column} must contain recorded numeric labels."
            ) from error
        known = values.dropna()
        if not np.isfinite(known.to_numpy()).all() or known.lt(0).any():
            raise ValueError(f"Match context {column} labels must be finite and nonnegative.")
        if column == "minutes" and known.gt(120).any():
            raise ValueError("Match context minutes are outside the supported range.")
        if column == "starts" and not known.isin((0, 1)).all():
            raise ValueError("Match context starts require recorded zero or one labels.")
        if column in ("team_goals", "team_conceded") and not known.eq(known.round()).all():
            raise ValueError(f"Match context {column} requires recorded integer scores.")
        result[column] = values
    return result


def _shared_score(frame: pd.DataFrame, field: str) -> float:
    recorded = frame[field].dropna().unique()
    if len(recorded) > 1:
        raise ValueError(f"Match context has inconsistent club-fixture {field} scores.")
    return float(recorded[0]) if len(recorded) else float("nan")


def _club_matches(history: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for (season, fixture), paired in history.groupby(["season", "fixture"], sort=False):
        clubs = paired.club.unique()
        if len(clubs) != 2 or paired.GW.nunique() != 1 or paired.kickoff.nunique() != 1:
            raise ValueError("Match context needs one consistent paired-club fixture identity.")
        match: list[dict[str, Any]] = []
        for club in clubs:
            players = paired.loc[paired.club.eq(club)]
            other = clubs[0] if club == clubs[1] else clubs[1]
            if players.opponent.nunique() != 1 or players.opponent.iloc[0] != other:
                raise ValueError("Match context paired club/opponent identities are inconsistent.")
            if players.home.nunique() != 1:
                raise ValueError("Match context has inconsistent club-fixture venues.")
            match.append(
                {
                    "season": season,
                    "fixture": fixture,
                    "GW": int(players.GW.iloc[0]),
                    "club": int(club),
                    "opponent": int(other),
                    "home": float(players.home.iloc[0]),
                    "kickoff": players.kickoff.iloc[0],
                    "gf": _shared_score(players, "team_goals"),
                    "ga": _shared_score(players, "team_conceded"),
                    "xgf": float(players.expected_goals.sum())
                    if players.expected_goals.notna().all()
                    else float("nan"),
                }
            )
        left, right = match
        if left["home"] + right["home"] != 1:
            raise ValueError("Match context paired clubs need opposite recorded venues.")
        for ours, theirs in ((left, right), (right, left)):
            if (
                math.isfinite(ours["gf"])
                and math.isfinite(theirs["ga"])
                and ours["gf"] != theirs["ga"]
            ):
                raise ValueError("Match context paired club scores disagree.")
            ours["xga"] = theirs["xgf"]
        rows.extend(match)
    return pd.DataFrame(
        rows,
        columns=("season", "fixture", "GW", "club", "opponent", "home", "kickoff", *_VENUE_METRICS),
    )


def _player_workload(history: pd.DataFrame, player: int, cutoff: pd.Timestamp) -> dict[str, float]:
    result: dict[str, float] = {}
    mine = history.loc[history.player_code.eq(player)]
    for days in WORKLOAD_WINDOWS_DAYS:
        window = mine.loc[mine.kickoff.ge(cutoff - pd.Timedelta(days=days))]
        prefix = f"player_pl_{days}d_"
        result[prefix + "observations"] = float(len(window))
        for metric in ("minutes", "appearances", "starts"):
            recorded = window.starts if metric == "starts" else window.minutes
            known = recorded.dropna()
            value = float(known.gt(0).sum()) if metric == "appearances" else float(known.sum())
            result[prefix + metric] = value
            result[prefix + metric + "_known_rows"] = float(len(known))
            result[prefix + metric + "_missing"] = float(known.empty or recorded.isna().any())
    return result


def _club_context(
    matches: pd.DataFrame, club: int, home: float, side: str, cutoff: pd.Timestamp
) -> dict[str, float]:
    mine = matches.loc[matches.club.eq(club)]
    result = {
        f"{side}_pl_observed_fixtures": float(len(mine)),
        f"{side}_pl_days_since_match": float((cutoff - mine.kickoff.max()).total_seconds() / 86400)
        if not mine.empty
        else 0.0,
        f"{side}_pl_match_history_missing": float(mine.empty),
    }
    for days in WORKLOAD_WINDOWS_DAYS:
        result[f"{side}_pl_{days}d_fixtures"] = float(
            mine.kickoff.ge(cutoff - pd.Timedelta(days=days)).sum()
        )
    venue = mine.loc[mine.home.eq(home)]
    result[f"{side}_venue_matches"] = float(len(venue))
    for metric in _VENUE_METRICS:
        known = venue[metric].dropna()
        result[f"{side}_venue_{metric}"] = float(known.mean()) if not known.empty else 0.0
        result[f"{side}_venue_{metric}_known_matches"] = float(len(known))
        result[f"{side}_venue_{metric}_missing"] = float(known.empty or venue[metric].isna().any())
    return result


def causal_match_context_features(
    history: pd.DataFrame, target: pd.DataFrame, cutoff: pd.Timestamp
) -> pd.DataFrame:
    """Build numeric context after excluding unsettled and target-week outcomes.

    Missing numeric outputs are zero with an explicit missing flag and known count.
    Labels are validated only after causal selection. Empty history gives cold-start
    features; fixture counts certify observed records, never complete PL coverage.
    """
    if not isinstance(cutoff, pd.Timestamp) or pd.isna(cutoff) or cutoff.tzinfo is None:
        raise ValueError("Match context cutoff must be a timezone-aware Timestamp.")
    cutoff = cutoff.tz_convert("UTC")
    if target.empty:
        return pd.DataFrame(index=target.index, columns=CONTEXT_FEATURES, dtype=float)
    identities = _identities(_required(target, _IDENTITY_COLUMNS, "target"), "target")
    if history.empty:
        eligible = pd.DataFrame(columns=_HISTORY_COLUMNS)
    else:
        eligible = _identities(_required(history, _HISTORY_COLUMNS, "history"), "history")
        eligible["kickoff"] = pd.to_datetime(eligible.kickoff.map(_kickoff), utc=True)
        eligible = eligible.loc[eligible.kickoff + pd.Timedelta(hours=3) < cutoff]
        selected = pd.Series(False, index=eligible.index)
        for season, week in identities[["season", "GW"]].drop_duplicates().itertuples(index=False):
            selected |= eligible.season.eq(season) & eligible.GW.lt(week)
        eligible = _labels(eligible.loc[selected])
    matches = _club_matches(eligible)
    rows: list[dict[str, float]] = []
    for row in identities.itertuples(index=False):
        past = eligible.loc[eligible.season.eq(row.season) & eligible.GW.lt(row.GW)]
        games = matches.loc[matches.season.eq(row.season) & matches.GW.lt(row.GW)]
        player = cast(int, row.player_code)
        club, opponent = cast(int, row.club), cast(int, row.opponent)
        home = cast(float, row.home)
        result = _player_workload(past, player, cutoff)
        result.update(_club_context(games, club, home, "own", cutoff))
        result.update(_club_context(games, opponent, 1 - home, "opp", cutoff))
        rows.append(result)
    return pd.DataFrame(rows, index=target.index, columns=CONTEXT_FEATURES, dtype=float)
