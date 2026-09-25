"""Normalize recorded archive and settled single-fixture live outcomes for football v1."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from squadopt.data.errors import (
    DataSourceError,
    DataValidationError,
    DuplicateRecordsError,
    InvalidValueError,
    MissingColumnsError,
    format_examples,
)
from squadopt.data.snapshots import CapturedSnapshot
from squadopt.data.sources.fpl_live import (
    BOOTSTRAP_PAYLOAD,
    FIXTURES_PAYLOAD,
    fpl_live_event_points,
)

POSITIONS = ("GK", "DEF", "MID", "FWD")
ARCHIVE_SEASONS = ("2022-23", "2023-24", "2024-25", "2025-26")

_OUTCOME_FIELDS = (
    "minutes",
    "goals_scored",
    "assists",
    "clean_sheets",
    "expected_goals",
    "expected_assists",
    "starts",
    "total_points",
    "team_goals",
    "team_conceded",
)
_IDENTITY_FIELDS = ("player_code", "club", "opponent", "kickoff")
_KEY_FIELDS = ("season", "fixture", "player_code")


def _numeric(frame: pd.DataFrame, column: str) -> pd.Series:
    try:
        return pd.to_numeric(frame[column], errors="raise")
    except (TypeError, ValueError) as error:
        raise InvalidValueError(
            f"Football history column {column!r} is not numeric: {error}"
        ) from error


def _unhashable(value: object) -> bool:
    try:
        hash(value)
    except TypeError:
        return True
    return False


def _without_repeats(frame: pd.DataFrame) -> pd.DataFrame:
    try:
        return frame.drop_duplicates().copy()
    except TypeError as error:
        columns = [
            column
            for position, column in enumerate(frame.columns)
            if frame.iloc[:, position].map(_unhashable).any()
        ]
        raise InvalidValueError(
            f"Football history columns {format_examples(columns)} hold values that cannot be "
            f"compared: {error}"
        ) from error


def _kickoffs(frame: pd.DataFrame) -> pd.Series:
    try:
        return pd.to_datetime(frame.kickoff, utc=True)
    except (TypeError, ValueError, OverflowError) as error:
        raise InvalidValueError(
            f"Football history column 'kickoff' is not a date: {error}"
        ) from error


def normalize_history(frame: pd.DataFrame) -> pd.DataFrame:
    """Validate and derive the football v1 history, raising the data layer's errors.

    These refusals are ``DataError`` subclasses (``docs/data_contract.md``, section 4):
    an absent column, refused by name rather than surfacing as a KeyError
    (``MissingColumnsError``); two different rows for one season, fixture and player
    code (``DuplicateRecordsError``); and a value that cannot be compared, a kickoff that
    is not a date, or an outcome that is not numeric, missing, not finite, negative or an
    impossible minute and clean-sheet pair (``InvalidValueError``).
    """
    required = (*_KEY_FIELDS, *_OUTCOME_FIELDS, *_IDENTITY_FIELDS, "position")
    absent = [column for column in dict.fromkeys(required) if column not in frame]
    if absent:
        raise MissingColumnsError(f"Football history lacks columns {format_examples(absent)}.")
    frame = _without_repeats(frame)
    conflicting = frame.duplicated(list(_KEY_FIELDS), keep=False)
    if conflicting.any():
        keys = frame.loc[conflicting, list(_KEY_FIELDS)].drop_duplicates()
        raise DuplicateRecordsError(
            "Conflicting football player-fixture rows for (season, fixture, player code) "
            f"{format_examples(list(keys.itertuples(index=False, name=None)))}."
        )
    frame["kickoff"] = _kickoffs(frame)
    fields = list(_OUTCOME_FIELDS)
    for col in fields:
        frame[col] = _numeric(frame, col)
    incomplete = [col for col in [*fields, *_IDENTITY_FIELDS] if frame[col].isna().any()]
    nonfinite = [col for col in fields if not np.isfinite(frame[col].to_numpy(dtype=float)).all()]
    negative = [col for col in fields if col != "total_points" and (frame[col] < 0).any()]
    if incomplete or nonfinite or negative:
        raise InvalidValueError(
            "Incomplete football outcomes or identities: missing in "
            f"{format_examples(incomplete)}; not finite in {format_examples(nonfinite)}; "
            f"negative in {format_examples(negative)}."
        )
    invalid = ~frame.minutes.between(0, 120) | ((frame.minutes < 60) & (frame.clean_sheets > 0))
    if invalid.any():
        raise InvalidValueError(
            "Invalid football minute/clean-sheet outcomes for player codes "
            f"{format_examples(frame.player_code[invalid].tolist())}."
        )
    frame["appeared"] = frame.minutes.gt(0).astype(float)
    frame["long"] = frame.minutes.ge(60).astype(float)
    frame["m_bin"] = np.select(
        [frame.minutes.le(0), frame.minutes.lt(60), frame.minutes.lt(90)], [0, 1, 2], default=3
    )
    if "defensive_contribution" not in frame:
        frame["defensive_contribution"] = np.nan
    dc = _numeric(frame, "defensive_contribution")
    frame["dc_event"] = (
        dc.ge(pd.Series(np.where(frame.position.eq("DEF"), 10, 12), index=frame.index))
        .astype(float)
        .where(dc.notna())
    )
    frame.loc[frame.position.eq("GK"), "dc_event"] = 0.0
    return frame


def archive_history(root: Path) -> pd.DataFrame:
    parts = []
    for season in ARCHIVE_SEASONS:
        base = root / "data" / season
        frame = pd.read_csv(base / "gws/merged_gw.csv", low_memory=False)
        frame = frame.loc[frame.position.isin(POSITIONS)].copy()
        players = pd.read_csv(base / "players_raw.csv").set_index("id")
        teams = pd.read_csv(base / "teams.csv").set_index("id")
        fixtures = pd.read_csv(base / "fixtures.csv").set_index("id")
        home = frame.was_home.astype(str).str.lower().eq("true")
        frame["season"] = season
        frame["player_code"] = frame.element.map(players.code)
        frame["home"] = home.astype(float)
        frame["club"] = (
            frame.fixture.map(fixtures.team_h)
            .where(home, frame.fixture.map(fixtures.team_a))
            .map(teams.code)
        )
        frame["opponent"] = (
            frame.fixture.map(fixtures.team_a)
            .where(home, frame.fixture.map(fixtures.team_h))
            .map(teams.code)
        )
        frame["team_goals"] = frame.team_h_score.where(home, frame.team_a_score)
        frame["team_conceded"] = frame.team_a_score.where(home, frame.team_h_score)
        frame["kickoff"] = frame.kickoff_time
        parts.append(normalize_history(frame))
    return pd.concat(parts, ignore_index=True)


def captured_history_weeks(gameweek: int) -> range:
    """The played gameweeks ``captured_history`` reads for a capture open for ``gameweek``.

    Every one from gameweek 1, not a trailing window: the football model trains on the
    whole season so far. The capture reads its live documents from this same range, so
    the reader and the capture cannot disagree about which weeks a capture must hold.
    """
    return range(1, gameweek)


def captured_history(snapshot: CapturedSnapshot, *, season: str, gameweek: int) -> pd.DataFrame:
    """Do not split aggregated DGW xG/actions into invented fixture observations.

    The current live source provides these fields per week, so reject ambiguous weeks.
    Explicit missing players remain missing observations; they are never zero-filled.
    """
    boot = json.loads(snapshot.payloads[BOOTSTRAP_PAYLOAD])
    fixtures = json.loads(snapshot.payloads[FIXTURES_PAYLOAD])
    players = {p["id"]: p for p in boot["elements"]}
    clubs = {t["id"]: t["code"] for t in boot["teams"]}
    cutoff = pd.Timestamp(snapshot.metadata.captured_at_utc)
    rows: list[dict[str, Any]] = []
    for week in captured_history_weeks(gameweek):
        payload = snapshot.payloads.get(f"event-gw{week:02d}-live.json")
        if payload is None:
            raise DataSourceError(f"Missing captured football history GW{week}.")
        settled = fpl_live_event_points(payload, snapshot.payloads[FIXTURES_PAYLOAD], gameweek=week)
        if not settled.bonus_confirmed:
            raise DataValidationError(
                f"Football history must be fully settled; GW{week}'s bonus is not confirmed."
            )
        matches = [f for f in fixtures if f["event"] == week]
        for item in json.loads(payload)["elements"]:
            player = players.get(item["id"])
            if player is None:
                raise InvalidValueError(
                    f"Unmapped captured football player {item['id']!r} in GW{week}."
                )
            pos = player["element_type"]
            if pos not in (1, 2, 3, 4):
                continue
            mine = [f for f in matches if player["team"] in (f["team_h"], f["team_a"])]
            if not mine:  # a blank is not a player-fixture observation
                continue
            if len(mine) != 1:
                raise DataValidationError(
                    "Live football history needs fixture-level xG for a double gameweek; "
                    f"team {player['team']!r} plays {len(mine)} fixtures in GW{week}."
                )
            match = mine[0]
            if any(e["fixture"] != match["id"] for e in item.get("explain", [])):
                # A transferred player's old club cannot be recovered from current roster.
                continue
            if pd.Timestamp(match["kickoff_time"]) + pd.Timedelta(hours=3) >= cutoff:
                raise DataValidationError(
                    "Captured football history contains an unsettled match: fixture "
                    f"{match['id']!r} in GW{week}."
                )
            home = player["team"] == match["team_h"]
            rows.append(
                {
                    **item["stats"],
                    "season": season,
                    "GW": week,
                    "player_code": player["code"],
                    "position": POSITIONS[pos - 1],
                    "fixture": match["id"],
                    "club": clubs[player["team"]],
                    "opponent": clubs[match["team_a"] if home else match["team_h"]],
                    "home": float(home),
                    "kickoff": match["kickoff_time"],
                    "team_goals": match["team_h_score"] if home else match["team_a_score"],
                    "team_conceded": match["team_a_score"] if home else match["team_h_score"],
                }
            )
    return normalize_history(pd.DataFrame(rows)) if rows else pd.DataFrame()
