"""Validation for the fixture-level table both sources feed.

Fixtures live at their own grain because a gameweek can hold more than one fixture
for the same player, so "the opponent" and "was it home" have no single correct value
at player-gameweek grain. One row per team per fixture does have one, and the
player-gameweek view is derived from it by explicit aggregation rather than by
choosing arbitrarily.

The archive and the live endpoint publish the same fixture columns, so one validated
shape covers both. What differs is provenance: a live capture knows when it was taken
and what deadline it was taken before, and the archive knows neither. Those two fields
are therefore nullable, and only those two — see ``FIXTURE_NULLABLE_COLUMNS``.

Mutual consistency is the check worth naming. Every fixture produces two rows that
describe the same match from opposite sides, and nothing in the storage format forces
them to agree. If they disagree, a team-level feature computed from one side would
silently contradict the same feature computed from the other, so agreement is verified
rather than assumed.
"""

import math
from collections.abc import Mapping, Sequence
from types import MappingProxyType
from typing import Final

import pandas as pd

from squadopt.data.errors import (
    DuplicateRecordsError,
    InvalidValueError,
    MissingColumnsError,
    format_examples,
)
from squadopt.data.schema import (
    FIXTURE_COLUMNS,
    FIXTURE_KEY_COLUMNS,
    FIXTURE_NULLABLE_COLUMNS,
    FIXTURE_SORT_COLUMNS,
    FIXTURE_STATUSES,
    MIN_GAMEWEEK,
)
from squadopt.data.timestamps import normalize_utc_timestamp

_FIXTURE_PAIR_COLUMNS: tuple[str, ...] = ("snapshot_id", "season", "fixture_id")
_INTEGER_COLUMNS: tuple[str, ...] = ("gameweek", "fixture_id", "team_id", "opponent_team_id")


def _require_columns(frame: pd.DataFrame) -> None:
    missing = [column for column in FIXTURE_COLUMNS if column not in frame.columns]
    if missing:
        raise MissingColumnsError(
            f"Fixture table is missing columns {missing!r}; it carries "
            f"{sorted(map(str, frame.columns))!r}."
        )
    unexpected = sorted(str(column) for column in frame.columns if column not in FIXTURE_COLUMNS)
    if unexpected:
        raise InvalidValueError(
            f"Fixture table carries columns the contract does not define: {unexpected!r}. "
            "A derived quantity belongs in the aggregation step, not in the stored table."
        )


def _describe_keys(frame: pd.DataFrame) -> list[str]:
    """Render key columns for an error message, tolerating an empty key value.

    The key itself can be the thing that is missing, so this cannot assume the
    columns it joins are present.
    """

    rendered = frame[list(FIXTURE_KEY_COLUMNS)].astype("string").fillna("<empty>")
    return rendered.agg("/".join, axis=1).tolist()


def _require_complete(frame: pd.DataFrame) -> None:
    for column in FIXTURE_COLUMNS:
        if column in FIXTURE_NULLABLE_COLUMNS:
            continue
        missing = frame.loc[frame[column].isna()]
        if not missing.empty:
            raise InvalidValueError(
                f"Fixture column {column!r} may not be empty; {len(missing)} row(s) are, "
                f"at keys {format_examples(_describe_keys(missing))}."
            )


def _require_integers(frame: pd.DataFrame) -> None:
    for column in _INTEGER_COLUMNS:
        dtype = frame[column].dtype
        # A nullable integer extension dtype also reports kind "i", so the check has
        # to exclude it explicitly rather than by kind alone.
        if isinstance(dtype, pd.api.extensions.ExtensionDtype) or dtype.kind not in "iu":
            raise InvalidValueError(
                f"Fixture column {column!r} must be a non-nullable integer dtype, got "
                f"{dtype!r}. A nullable identifier would survive into a join and match "
                "nothing rather than failing."
            )


def _require_distinct_opponents(frame: pd.DataFrame) -> None:
    self_matches = frame.loc[frame["team_id"] == frame["opponent_team_id"]]
    if not self_matches.empty:
        raise InvalidValueError(
            f"{len(self_matches)} fixture row(s) name the same club as team and opponent: "
            f"{format_examples(self_matches['team_id'].tolist())}."
        )


def _require_known_status(frame: pd.DataFrame) -> None:
    unknown = sorted(set(frame["status"].astype("string")) - set(FIXTURE_STATUSES))
    if unknown:
        raise InvalidValueError(
            f"Fixture status must be one of {list(FIXTURE_STATUSES)!r}; got {unknown!r}."
        )


def _require_valid_gameweeks(frame: pd.DataFrame) -> None:
    below = frame.loc[frame["gameweek"] < MIN_GAMEWEEK, "gameweek"]
    if not below.empty:
        raise InvalidValueError(
            f"Fixture gameweeks must be at least {MIN_GAMEWEEK}; got "
            f"{format_examples(below.tolist())}."
        )


def _require_unique_key(frame: pd.DataFrame) -> None:
    duplicated = frame.loc[frame.duplicated(subset=list(FIXTURE_KEY_COLUMNS), keep=False)]
    if not duplicated.empty:
        raise DuplicateRecordsError(
            f"Fixture key {list(FIXTURE_KEY_COLUMNS)!r} must be unique; "
            f"{len(duplicated)} row(s) repeat it at "
            f"{format_examples(sorted(set(_describe_keys(duplicated))))}."
        )


def _is_missing(value: object) -> bool:
    """Report whether one cell value is empty.

    Spelled out rather than delegated, because the columns compared here hold three
    different spellings of absence: ``None``, ``pd.NA`` from the nullable string and
    integer dtypes, and ``float('nan')`` from a float column.
    """

    return value is None or value is pd.NA or (isinstance(value, float) and math.isnan(value))


def _same_value(left: object, right: object) -> bool:
    """Compare two cell values treating two empties as equal.

    A nullable column has to be comparable across a fixture's two sides, and
    ``pd.NA != pd.NA`` is itself ``pd.NA`` rather than a boolean, so a direct
    comparison would raise instead of answering.
    """

    left_missing = _is_missing(left)
    right_missing = _is_missing(right)
    if left_missing or right_missing:
        return left_missing and right_missing
    return bool(left == right)


def _require_consistent_pairs(frame: pd.DataFrame) -> None:
    """Check that both sides of every fixture tell the same story."""

    for key, group in frame.groupby(list(_FIXTURE_PAIR_COLUMNS), sort=True):
        if len(group) != 2:
            raise InvalidValueError(
                f"Fixture {key!r} has {len(group)} row(s); a fixture is stored once per "
                "team, so exactly two rows describe it."
            )
        home = group.loc[group["is_home"].astype("boolean").fillna(False)]
        away = group.loc[~group["is_home"].astype("boolean").fillna(True)]
        if len(home) != 1 or len(away) != 1:
            raise InvalidValueError(
                f"Fixture {key!r} must have exactly one home row and one away row; got "
                f"{len(home)} home and {len(away)} away."
            )
        home_row = home.iloc[0]
        away_row = away.iloc[0]
        if (
            home_row["team_id"] != away_row["opponent_team_id"]
            or away_row["team_id"] != home_row["opponent_team_id"]
        ):
            raise InvalidValueError(
                f"Fixture {key!r} has sides that do not mirror each other: home row is "
                f"{home_row['team_id']} vs {home_row['opponent_team_id']}, away row is "
                f"{away_row['team_id']} vs {away_row['opponent_team_id']}."
            )
        for column in ("gameweek", "kickoff_time_utc", "status"):
            if not _same_value(home_row[column], away_row[column]):
                raise InvalidValueError(
                    f"Fixture {key!r} disagrees on {column!r} between its two sides: "
                    f"{home_row[column]!r} and {away_row[column]!r}."
                )


def _require_utc_timestamps(frame: pd.DataFrame) -> None:
    for column in ("kickoff_time_utc", "captured_at_utc", "deadline_timestamp_utc"):
        for value in frame[column].dropna().unique().tolist():
            normalize_utc_timestamp(value, label=f"Fixture {column}")


def validate_fixture_snapshot(frame: pd.DataFrame) -> pd.DataFrame:
    """Validate a fixture table and return it in canonical column and row order.

    Returns an independent copy; the input is never modified.
    """

    if not isinstance(frame, pd.DataFrame):
        raise InvalidValueError("Fixture table must be a pandas DataFrame.")
    if frame.empty:
        raise InvalidValueError("Fixture table has no rows.")

    _require_columns(frame)
    validated = frame.loc[:, list(FIXTURE_COLUMNS)].copy(deep=True)

    _require_complete(validated)
    _require_integers(validated)
    _require_valid_gameweeks(validated)
    _require_distinct_opponents(validated)
    _require_known_status(validated)
    _require_unique_key(validated)
    _require_consistent_pairs(validated)
    _require_utc_timestamps(validated)

    return validated.sort_values(list(FIXTURE_SORT_COLUMNS), kind="stable").reset_index(drop=True)


def fixture_pair_columns() -> Sequence[str]:
    """Columns identifying one match, both of whose sides must agree."""

    return _FIXTURE_PAIR_COLUMNS


def aggregate_team_gameweek(fixtures: pd.DataFrame) -> pd.DataFrame:
    """Summarise a club's fixtures within each gameweek.

    This is the controlled step from fixture grain to something a player-gameweek
    feature can consume. It is deliberately narrow: it reads only the rows belonging
    to the gameweek being summarised, and every quantity it produces is a pre-match
    fact — who is being played, at home or away, and how the source rates the tie.
    None of them require an outcome, so nothing here needs shifting.

    A club playing twice in a gameweek yields ``fixture_count`` 2, which is precisely
    the information the player-gameweek panel cannot express and the reason this table
    exists.

    ``snapshot_id`` stays in the key rather than being collapsed. Two captures of one
    season describe the same gameweek at different times, and summing across them would
    silently double every count.
    """

    validated = validate_fixture_snapshot(fixtures)
    grouped = validated.groupby(
        ["snapshot_id", "season", "gameweek", "team_id"], sort=True, dropna=False
    )

    home = validated["is_home"].astype("boolean").fillna(False)
    counted = validated.assign(
        _home=home.astype("int64"),
        _away=(~home).astype("int64"),
    ).groupby(["snapshot_id", "season", "gameweek", "team_id"], sort=True, dropna=False)

    aggregated = pd.DataFrame(
        {
            "fixture_count": grouped["fixture_id"].size(),
            "home_fixture_count": counted["_home"].sum(),
            "away_fixture_count": counted["_away"].sum(),
            "mean_fixture_difficulty": grouped["fixture_difficulty"].mean(),
            "minimum_fixture_difficulty": grouped["fixture_difficulty"].min(),
        }
    ).reset_index()

    for column in ("fixture_count", "home_fixture_count", "away_fixture_count"):
        aggregated[column] = aggregated[column].astype("int64")
    aggregated["mean_fixture_difficulty"] = aggregated["mean_fixture_difficulty"].astype("Float64")
    aggregated["minimum_fixture_difficulty"] = aggregated["minimum_fixture_difficulty"].astype(
        "Int64"
    )
    return aggregated.sort_values(
        ["snapshot_id", "season", "gameweek", "team_id"], kind="stable"
    ).reset_index(drop=True)


# A club with no fixture plays no matches, and zero states that. Named separately
# from the mapping below because a count is an integer while a missing difficulty is
# not, and a caller filling a count column needs the former without narrowing the
# latter.
BLANK_GAMEWEEK_FIXTURE_COUNT: Final = 0


def blank_gameweek_defaults() -> Mapping[str, object]:
    """Values for a club with no fixture in a gameweek.

    Counts are zero, because "plays no matches" is a fact and zero states it. The
    difficulty columns stay empty on purpose: a club with no fixture has no difficulty,
    and filling zero would describe it as facing the easiest possible tie — which is
    the opposite of the truth for a points projection.
    """

    return MappingProxyType(
        {
            "fixture_count": BLANK_GAMEWEEK_FIXTURE_COUNT,
            "home_fixture_count": BLANK_GAMEWEEK_FIXTURE_COUNT,
            "away_fixture_count": BLANK_GAMEWEEK_FIXTURE_COUNT,
            "mean_fixture_difficulty": pd.NA,
            "minimum_fixture_difficulty": pd.NA,
        }
    )
