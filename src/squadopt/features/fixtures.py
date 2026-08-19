"""Attach a gameweek's fixture context to the player-gameweek panel.

The panel sums a player's minutes and points across every fixture he played inside a
gameweek — 1,937 rows across the six supported seasons exceed ninety minutes, and the
largest is 204. A model that cannot see how many fixtures a gameweek holds therefore
under-projects every double gameweek and over-projects every blank one, and no amount of
history fixes that: the information is not in the player's past, it is in the calendar.

Everything attached here is pre-match. How many fixtures a club plays, at home or away,
and against whom is published before the deadline, so these columns are read from the
target gameweek's own row rather than shifted. That is the same rule price follows, and
the reason is the same: shifting a value already known at the deadline discards
information instead of protecting anything.

The join has to cross an identifier boundary. The panel names a club by the platform's
display name while the fixture table uses its persistent code, so a season-scoped
name-to-code table bridges the two. All six supported seasons reconcile through it
exactly.
"""

from typing import Final

import pandas as pd

from squadopt.data.fixtures import BLANK_GAMEWEEK_FIXTURE_COUNT, aggregate_team_gameweek
from squadopt.features.config import FeatureConfigurationError

# Columns attached to each player-gameweek row. Counts describe the calendar; the
# difficulty summaries describe who is being played.
FIXTURE_FEATURE_COLUMNS: Final = (
    "fixture_count",
    "home_fixture_count",
    "away_fixture_count",
    "mean_fixture_difficulty",
    "minimum_fixture_difficulty",
)

_TEAM_CODE_COLUMNS: Final = ("season", "name", "code")


def _require_frame(value: object, label: str) -> pd.DataFrame:
    if not isinstance(value, pd.DataFrame):
        raise FeatureConfigurationError(f"{label} must be a pandas DataFrame.")
    if value.empty:
        raise FeatureConfigurationError(f"{label} has no rows.")
    return value


def _require_columns(frame: pd.DataFrame, columns: tuple[str, ...], label: str) -> None:
    missing = [column for column in columns if column not in frame.columns]
    if missing:
        raise FeatureConfigurationError(
            f"{label} is missing columns {missing!r}; it carries "
            f"{sorted(map(str, frame.columns))!r}."
        )


def _single_snapshot_per_season(aggregate: pd.DataFrame) -> pd.DataFrame:
    """Reject an aggregate holding two captures of the same season.

    Two captures describe the same gameweek at different times. Joining both would
    duplicate every player-gameweek row, and silently picking one would hide which
    capture a decision was based on — the opposite of what the snapshot exists for.
    """

    counts = aggregate.groupby("season", sort=True)["snapshot_id"].nunique()
    conflicted = counts.loc[counts > 1]
    if not conflicted.empty:
        listed = ", ".join(f"{season} ({count} snapshots)" for season, count in conflicted.items())
        raise FeatureConfigurationError(
            f"Fixture aggregate holds more than one snapshot for: {listed}. Select the "
            "capture a decision is being made from before joining."
        )
    return aggregate


def attach_fixture_features(
    panel: pd.DataFrame,
    fixtures: pd.DataFrame,
    team_codes: pd.DataFrame,
) -> pd.DataFrame:
    """Add a gameweek's fixture context to every player-gameweek row.

    ``fixtures`` is the fixture-level table; it is aggregated to team-gameweek grain
    here rather than by the caller, so a caller cannot accidentally pass a partially
    summarised frame.

    ``team_codes`` maps a season's display names to persistent codes. It is passed in
    rather than derived, because it belongs to whichever source supplied the panel and
    this module knows about neither.

    A club with no fixture in a gameweek receives explicit blank-gameweek values:
    zero counts, and empty difficulty summaries. Zero difficulty would describe the
    club as facing the easiest possible tie rather than facing nobody.

    Returns an independent copy; the input frames are never modified.
    """

    _require_frame(panel, "Player panel")
    _require_frame(fixtures, "Fixture table")
    _require_frame(team_codes, "Team code table")
    _require_columns(panel, ("season", "gameweek", "team_id"), "Player panel")
    _require_columns(team_codes, _TEAM_CODE_COLUMNS, "Team code table")

    collisions = [column for column in FIXTURE_FEATURE_COLUMNS if column in panel.columns]
    if collisions:
        raise FeatureConfigurationError(
            f"Fixture feature names collide with existing panel columns: {collisions!r}."
        )

    aggregate = _single_snapshot_per_season(aggregate_team_gameweek(fixtures))

    codes = team_codes.loc[:, list(_TEAM_CODE_COLUMNS)].copy(deep=True)
    codes["season"] = codes["season"].astype("string")
    codes["name"] = codes["name"].astype("string")
    duplicated = codes.loc[codes.duplicated(subset=["season", "name"]), "name"].tolist()
    if duplicated:
        raise FeatureConfigurationError(
            f"Team code table maps the same season and name twice: {duplicated!r}."
        )

    bridged = panel.copy(deep=True)
    bridged["_season_key"] = bridged["season"].astype("string")
    bridged["_team_key"] = bridged["team_id"].astype("string")

    resolved = bridged.merge(
        codes.rename(columns={"season": "_season_key", "name": "_team_key", "code": "_team_code"}),
        on=["_season_key", "_team_key"],
        how="left",
        validate="many_to_one",
    )
    unresolved = resolved.loc[resolved["_team_code"].isna(), "_team_key"]
    if not unresolved.empty:
        unknown = sorted(set(unresolved.dropna().tolist()))
        raise FeatureConfigurationError(
            f"Team code table does not name {len(unknown)} club(s) present in the panel: "
            f"{unknown!r}. The panel and the fixture table would not join."
        )

    summary = aggregate.loc[:, ["season", "gameweek", "team_id", *FIXTURE_FEATURE_COLUMNS]].rename(
        columns={"team_id": "_team_code"}
    )
    summary["season"] = summary["season"].astype("string")

    joined = resolved.merge(
        summary,
        left_on=["_season_key", "gameweek", "_team_code"],
        right_on=["season", "gameweek", "_team_code"],
        how="left",
        suffixes=("", "_fixture"),
        validate="many_to_one",
    )
    joined = joined.drop(
        columns=[
            column
            for column in ("season_fixture", "_season_key", "_team_key")
            if column in joined.columns
        ]
    )

    # Counts fill to zero because playing no matches is a fact. The difficulty
    # columns are left empty on purpose: a club with no fixture has no difficulty, and
    # zero would describe it as facing the easiest possible tie.
    for column in ("fixture_count", "home_fixture_count", "away_fixture_count"):
        joined[column] = joined[column].fillna(BLANK_GAMEWEEK_FIXTURE_COUNT).astype("int64")
    joined["mean_fixture_difficulty"] = joined["mean_fixture_difficulty"].astype("Float64")
    joined["minimum_fixture_difficulty"] = joined["minimum_fixture_difficulty"].astype("Int64")

    return joined.drop(columns=["_team_code"])
