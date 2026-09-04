"""The single shifted-rolling primitive of the project.

Every time-dependent aggregation goes through this module. That is the whole
point: leakage is prevented by construction when exactly one function shifts and
windows a series, and there is exactly one place to audit.

No unshifted aggregation of a match outcome is reachable from the public API, so
the common failure — letting gameweek t's own result into a gameweek t feature —
is not merely discouraged but unavailable.
"""

from collections.abc import Sequence
from typing import Literal, TypeAlias

import pandas as pd

from squadopt.data.schema import (
    PLAYER_GROUP_COLUMNS,
    TEAM_GROUP_COLUMNS,
    is_outcome_column,
)
from squadopt.features.config import FeatureConfigurationError

Aggregation: TypeAlias = Literal["mean", "sum"]


def _require_column(frame: pd.DataFrame, column: str, group_columns: Sequence[str]) -> None:
    if column not in frame.columns:
        raise FeatureConfigurationError(
            f"Column {column!r} is not present; available columns are {sorted(frame.columns)!r}."
        )
    for required in (*group_columns, "gameweek"):
        if required not in frame.columns:
            raise FeatureConfigurationError(
                f"Rolling features need {required!r}, which is missing from the frame."
            )


def _require_outcome_source(column: str) -> None:
    """Confirm the source column is one whose timing demands a shift.

    This is not decoration. ``is_outcome_column`` raises for any column with no
    time-of-knowledge classification, so a newly added canonical column cannot
    quietly acquire a rolling feature before someone decides when it is known.
    Pre-match columns are already available at the target gameweek, so shifting
    them would discard information rather than protect anything.
    """

    if not is_outcome_column(column):
        raise FeatureConfigurationError(
            f"Column {column!r} is known before its gameweek, so a shifted rolling "
            "feature would needlessly discard information; use the value directly."
        )


def _require_one_row_per_gameweek(frame: pd.DataFrame, group_columns: Sequence[str]) -> None:
    """Confirm each group has at most one row per gameweek.

    This is the invariant ``shift(1)`` actually depends on. The shift moves by *row*, not
    by gameweek, so if a group holds two rows for one gameweek the second row's window
    starts at the first row — a value from the very gameweek the feature describes. No
    error, no warning, just a wrong number, which is the most expensive shape a fault can
    take here.

    The ordering check below is not enough on its own: ``is_monotonic_increasing`` is
    non-strict, so ``[1, 1, 2, 2]`` passes it.

    Whether duplicates are possible depends on which key is grouped, which is why this is
    checked rather than reasoned about. Under ``PLAYER_GROUP_COLUMNS`` the canonical key
    ``(season, gameweek, player_id)`` already rejects them. Under ``TEAM_GROUP_COLUMNS``
    they are the *normal shape* of a player panel — eleven players of one club share a
    gameweek — so a caller reaching for the team-grain function with a player-grain frame
    is the case this exists to stop.
    """

    duplicated = frame.duplicated(subset=[*group_columns, "gameweek"])
    if not bool(duplicated.any()):
        return
    offenders = (
        frame.loc[duplicated, [*group_columns, "gameweek"]]
        .drop_duplicates()
        .itertuples(index=False, name=None)
    )
    examples = [tuple(row) for row in offenders][:10]
    raise FeatureConfigurationError(
        f"Rolling features need at most one row per {list(group_columns)!r} per gameweek; "
        f"the shift moves by row, so a repeated gameweek would let a row see its own. "
        f"Offending {[*group_columns, 'gameweek']!r} combinations: {examples!r}."
    )


def _require_time_ordered(frame: pd.DataFrame, group_columns: Sequence[str]) -> None:
    """Confirm each player's rows ascend in gameweek order.

    Only the order *within* a group matters. ``groupby`` collects a player's rows
    however they are scattered through the frame, and ``shift(1)`` then follows
    their relative order, so the groups themselves need not be contiguous. This
    checks exactly the invariant the window depends on and nothing more.

    Repeated gameweeks are rejected by :func:`_require_one_row_per_gameweek` before this
    runs, which matters because the test used here would not catch them.
    """

    ordered = frame.groupby(list(group_columns), sort=False)["gameweek"].apply(
        lambda values: bool(values.is_monotonic_increasing)
    )
    if bool(ordered.all()):
        return
    offenders = [tuple(key) for key in ordered.index[~ordered.astype(bool)]]
    raise FeatureConfigurationError(
        f"Rows must ascend in gameweek order within each {list(group_columns)!r} group "
        f"before rolling; offending groups: {offenders[:10]!r}."
    )


def _shifted_rolling(
    frame: pd.DataFrame,
    column: str,
    window: int,
    *,
    min_periods: int,
    aggregation: Aggregation,
    group_columns: Sequence[str],
) -> pd.Series:
    _require_column(frame, column, group_columns)
    _require_outcome_source(column)
    if window < 1:
        raise FeatureConfigurationError(f"window must be at least 1, got {window}.")
    if not 1 <= min_periods <= window:
        raise FeatureConfigurationError(
            f"min_periods must be between 1 and window ({window}), got {min_periods}."
        )
    _require_one_row_per_gameweek(frame, group_columns)
    _require_time_ordered(frame, group_columns)

    def _aggregate(values: pd.Series) -> pd.Series:
        # shift(1) first, so the window can never see the current gameweek.
        rolled = values.shift(1).rolling(window, min_periods=min_periods)
        return rolled.mean() if aggregation == "mean" else rolled.sum()

    grouped = frame.groupby(list(group_columns), sort=False)[column]
    return grouped.transform(_aggregate).astype("float64")


def shifted_rolling_mean(
    frame: pd.DataFrame,
    column: str,
    window: int,
    *,
    min_periods: int = 1,
) -> pd.Series:
    """Mean of a column over the gameweeks *before* each row's own gameweek.

    Grouped by ``(season, player_id)`` so a window never spans two seasons, and
    shifted by one gameweek before the window is applied so the row's own result
    is excluded. Rows with fewer than ``min_periods`` prior observations are
    missing, and are never filled from later gameweeks.
    """

    return _shifted_rolling(
        frame,
        column,
        window,
        min_periods=min_periods,
        aggregation="mean",
        group_columns=PLAYER_GROUP_COLUMNS,
    )


def shifted_rolling_sum(
    frame: pd.DataFrame,
    column: str,
    window: int,
    *,
    min_periods: int = 1,
) -> pd.Series:
    """Sum of a column over the gameweeks *before* each row's own gameweek.

    Same timing guarantees as :func:`shifted_rolling_mean`. Sums exist so rate
    features can be built as a ratio of sums, which is the correct aggregate; a
    mean of per-row ratios would weight a 10-minute appearance as heavily as a
    full match and divide by zero whenever a player did not play.
    """

    return _shifted_rolling(
        frame,
        column,
        window,
        min_periods=min_periods,
        aggregation="sum",
        group_columns=PLAYER_GROUP_COLUMNS,
    )


def shifted_team_rolling_mean(
    frame: pd.DataFrame,
    column: str,
    window: int,
    *,
    min_periods: int = 1,
) -> pd.Series:
    """Mean of a team-grain column over the gameweeks *before* each row's own gameweek.

    The same construction as the player-grain functions, one grain up, and grouped by a
    key that is equally frozen. Opponent strength is why this exists: a club's recent
    form is a property of the club, and computing it per player would make every player
    of one club carry a slightly different version of the same number.

    The grouping is not a parameter, here or above. Letting a caller choose it is
    exactly what these frozen keys prevent — a key omitting ``season`` would let one
    season's form leak into the next, which is the failure the player key was frozen to
    stop.
    """

    return _shifted_rolling(
        frame,
        column,
        window,
        min_periods=min_periods,
        aggregation="mean",
        group_columns=TEAM_GROUP_COLUMNS,
    )
