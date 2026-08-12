"""Time-ordered splitting of a canonical player-gameweek panel.

Every backtest decision is anchored to a point in time, and this module is the only
place that decides what "before" means. Keeping that in one place is what makes the
guarantee auditable: a random split is not merely discouraged, it cannot be
expressed through this API at all.

Nothing here imports the evaluation or optimization packages. The split is a
property of the data's time axis, not of what a consumer later does with it.
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from numbers import Integral

import pandas as pd

from squadopt.data.errors import DataError, InvalidValueError
from squadopt.data.schema import (
    CANONICAL_SORT_COLUMNS,
    REQUIRED_COLUMNS,
    season_rank_map,
)


class BacktestError(DataError):
    """Base exception for the backtest package."""


class BacktestConfigurationError(BacktestError):
    """Raised when a panel or split request is inconsistent."""


@dataclass(frozen=True, slots=True)
class DecisionPoint:
    """One season and gameweek at which a squad decision is made.

    A decision point is the boundary between what is known and what is not.
    Everything before it may inform the decision; the gameweek's own outcome may
    only be used to score the decision afterwards.
    """

    season: str
    gameweek: int

    def __post_init__(self) -> None:
        if not isinstance(self.season, str) or not self.season.strip():
            raise BacktestConfigurationError(
                f"season must be a non-empty string, got {self.season!r}."
            )
        if isinstance(self.gameweek, bool) or not isinstance(self.gameweek, Integral):
            raise BacktestConfigurationError(f"gameweek must be an integer, got {self.gameweek!r}.")
        if int(self.gameweek) < 1:
            raise BacktestConfigurationError(
                f"gameweek must be at least 1, got {int(self.gameweek)}."
            )
        object.__setattr__(self, "season", self.season.strip())
        object.__setattr__(self, "gameweek", int(self.gameweek))

    @property
    def fold_id(self) -> str:
        """Return a stable, sortable identifier for this decision."""

        return f"{self.season}-gw{self.gameweek:02d}"


def _require_panel(panel: object) -> pd.DataFrame:
    if not isinstance(panel, pd.DataFrame):
        raise BacktestConfigurationError("panel must be a pandas DataFrame.")
    missing = [column for column in REQUIRED_COLUMNS if column not in panel.columns]
    if missing:
        raise BacktestConfigurationError(f"panel is missing required columns: {missing!r}.")
    if panel.empty:
        raise BacktestConfigurationError("panel must contain at least one row.")
    return panel


def season_ranks(
    panel: pd.DataFrame,
    *,
    season_order: Sequence[str] | None = None,
) -> Mapping[str, int]:
    """Return a chronological rank for every season present in the panel.

    Seasons are ordered by their sorted labels unless an explicit order is given.
    Sorting works for the conventional ``YYYY-YY`` label — ``2016-17`` precedes
    ``2017-18`` — but that is a property of the naming convention rather than a
    guarantee, so a caller with unconventional labels supplies ``season_order``
    instead of hoping the default is right.
    """

    frame = _require_panel(panel)
    try:
        return season_rank_map(frame["season"].tolist(), season_order=season_order)
    except InvalidValueError as error:
        # Re-raised in this package's own type so callers can guard the backtest
        # surface with one exception, while the ranking rule stays in one place.
        raise BacktestConfigurationError(str(error)) from error


def _timeline(frame: pd.DataFrame, ranks: Mapping[str, int]) -> pd.Series:
    """Return a sortable chronological key per row: season rank, then gameweek."""

    seasons = [str(value) for value in frame["season"].tolist()]
    unknown = sorted({season for season in seasons if season not in ranks})
    if unknown:
        raise BacktestConfigurationError(f"No chronological rank for seasons {unknown!r}.")
    gameweeks = [int(value) for value in frame["gameweek"].tolist()]
    keys = [(ranks[season], gameweek) for season, gameweek in zip(seasons, gameweeks, strict=True)]
    return pd.Series(keys, index=frame.index, dtype=object)


def walk_forward_decision_points(
    panel: pd.DataFrame,
    *,
    seasons: Iterable[str] | None = None,
    min_prior_gameweeks_in_season: int = 1,
    season_order: Sequence[str] | None = None,
) -> tuple[DecisionPoint, ...]:
    """Return every decision point in the panel, in chronological order.

    ``min_prior_gameweeks_in_season`` skips the opening gameweeks of each season.
    It defaults to 1 because a season-scoped rolling feature has no history at all
    in gameweek 1, so the projection there falls back to a constant and the fold
    measures the fallback rather than the model. Pass 0 to include those gameweeks
    deliberately.

    ``seasons`` restricts which seasons produce decision points, which is how a
    holdout season is kept out of a tuning run. History from earlier seasons is
    still available to the split functions; only the decisions are restricted.
    """

    frame = _require_panel(panel)
    if isinstance(min_prior_gameweeks_in_season, bool) or not isinstance(
        min_prior_gameweeks_in_season, Integral
    ):
        raise BacktestConfigurationError("min_prior_gameweeks_in_season must be an integer.")
    minimum = int(min_prior_gameweeks_in_season)
    if minimum < 0:
        raise BacktestConfigurationError(
            f"min_prior_gameweeks_in_season must not be negative, got {minimum}."
        )

    ranks = season_ranks(frame, season_order=season_order)

    if seasons is None:
        requested = set(ranks)
    else:
        requested = {str(season).strip() for season in seasons}
        unknown = sorted(requested - set(ranks))
        if unknown:
            raise BacktestConfigurationError(
                f"Requested seasons are not present in the panel: {unknown!r}."
            )

    points: list[DecisionPoint] = []
    for season in sorted(requested, key=lambda value: ranks[value]):
        season_gameweeks = sorted(
            {int(value) for value in frame.loc[frame["season"] == season, "gameweek"].tolist()}
        )
        for position, gameweek in enumerate(season_gameweeks):
            # `position` counts the earlier gameweeks that actually exist in the
            # panel, which is stricter than trusting the gameweek number: a panel
            # starting at gameweek 5 has no history at gameweek 5.
            if position >= minimum:
                points.append(DecisionPoint(season=season, gameweek=gameweek))
    return tuple(points)


def rows_before(
    panel: pd.DataFrame,
    decision: DecisionPoint,
    *,
    season_order: Sequence[str] | None = None,
) -> pd.DataFrame:
    """Return rows strictly before the decision point, chronologically ordered.

    This is the training view. Nothing from the decision gameweek itself appears,
    so a model fitted on this frame cannot have seen the outcome it will be asked
    to predict.
    """

    return _slice(panel, decision, season_order=season_order, inclusive=False)


def rows_through(
    panel: pd.DataFrame,
    decision: DecisionPoint,
    *,
    season_order: Sequence[str] | None = None,
) -> pd.DataFrame:
    """Return rows up to and including the decision gameweek.

    This is the projection view, and the inclusion is deliberate rather than
    careless. Building features for gameweek ``t`` needs row ``t`` present for its
    pre-match columns — price, club, and position are fixed at that gameweek's
    deadline — while every rolling aggregation is shifted, so the row's own
    outcome cannot reach its own features. Later gameweeks are absent entirely,
    which makes "the future does not exist" structurally true rather than merely
    tested.
    """

    return _slice(panel, decision, season_order=season_order, inclusive=True)


def _slice(
    panel: pd.DataFrame,
    decision: DecisionPoint,
    *,
    season_order: Sequence[str] | None,
    inclusive: bool,
) -> pd.DataFrame:
    frame = _require_panel(panel)
    if not isinstance(decision, DecisionPoint):
        raise BacktestConfigurationError("decision must be a DecisionPoint.")

    ranks = season_ranks(frame, season_order=season_order)
    if decision.season not in ranks:
        raise BacktestConfigurationError(
            f"Decision season {decision.season!r} is not present in the panel; "
            f"available seasons are {sorted(ranks)!r}."
        )

    boundary = (ranks[decision.season], decision.gameweek)
    timeline = _timeline(frame, ranks)
    keep = timeline <= boundary if inclusive else timeline < boundary

    selected = frame.loc[keep]
    return selected.sort_values(list(CANONICAL_SORT_COLUMNS), kind="stable").reset_index(drop=True)


def realized_points_at(
    panel: pd.DataFrame,
    decision: DecisionPoint,
) -> pd.DataFrame:
    """Return the decision gameweek's realized points, for scoring afterwards.

    Deliberately a separate function from the projection view. Realized outcomes
    are the answer sheet: they are read only after a decision is frozen, and
    giving them their own entry point keeps that separation visible in calling
    code rather than buried in a column selection.
    """

    frame = _require_panel(panel)
    if not isinstance(decision, DecisionPoint):
        raise BacktestConfigurationError("decision must be a DecisionPoint.")

    rows = frame.loc[
        (frame["season"] == decision.season) & (frame["gameweek"] == decision.gameweek)
    ]
    if rows.empty:
        raise BacktestConfigurationError(
            f"No rows for {decision.fold_id}; cannot score a gameweek that is absent."
        )
    outcomes = rows.loc[:, ["player_id", "total_points"]].copy(deep=True)
    return outcomes.sort_values("player_id", kind="stable").reset_index(drop=True)
