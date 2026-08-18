"""Attach the published calendar to evaluation folds for the fixture-group contract.

The fixture-group calibration (`projection_uncertainty_v2`) needs a ``fixture_count``
on every projection row, at fit and at apply time. Walk-forward folds carry the club
(``team_id``) and the gameweek (metadata), and the calendar is a table of known
fixture counts per (season, gameweek, team); this joins them. A club absent from the
calendar in a gameweek has no fixture there — a blank — and gets zero, which is what a
blank is, not a guess.
"""

from collections.abc import Iterable

import pandas as pd

from squadopt.evaluation import EvaluationFold
from squadopt.uncertainty.calibration import FIXTURE_COUNT_COLUMN
from squadopt.uncertainty.errors import UncertaintyValidationError

_CALENDAR_COLUMNS = ("season", "gameweek", "team_id", "fixture_count")


def attach_fixture_counts_to_folds(
    folds: Iterable[EvaluationFold],
    fixture_counts: pd.DataFrame,
) -> tuple[EvaluationFold, ...]:
    """Return the folds with ``fixture_count`` on every projection row.

    ``fixture_counts`` holds one row per (season, gameweek, team_id) with the known
    number of fixtures, using the same team labels as the fold projections. Realized
    points and metadata pass through unchanged.
    """

    if not isinstance(fixture_counts, pd.DataFrame):
        raise UncertaintyValidationError("fixture_counts must be a pandas DataFrame.")
    missing = [column for column in _CALENDAR_COLUMNS if column not in fixture_counts.columns]
    if missing:
        raise UncertaintyValidationError(f"fixture_counts is missing columns: {missing!r}.")
    calendar: dict[tuple[str, int, object], int] = {}
    for season, gameweek, team, count in zip(
        fixture_counts["season"].tolist(),
        fixture_counts["gameweek"].tolist(),
        fixture_counts["team_id"].tolist(),
        fixture_counts["fixture_count"].tolist(),
        strict=True,
    ):
        calendar[(str(season), int(gameweek), team)] = int(count)

    attached: list[EvaluationFold] = []
    for fold in folds:
        if not isinstance(fold, EvaluationFold):
            raise UncertaintyValidationError("folds must contain EvaluationFold instances.")
        season = fold.metadata.get("season")
        gameweek = fold.metadata.get("gameweek")
        if (
            not isinstance(season, str)
            or isinstance(gameweek, bool)
            or not isinstance(gameweek, int)
        ):
            raise UncertaintyValidationError(
                f"Fold {fold.fold_id!r} metadata must carry a season string and a gameweek integer."
            )
        if "team_id" not in fold.projections.columns:
            raise UncertaintyValidationError(
                f"Fold {fold.fold_id!r} projections carry no team_id; the calendar cannot be "
                "joined."
            )
        table = fold.projections.copy(deep=True)
        table[FIXTURE_COUNT_COLUMN] = pd.Series(
            [calendar.get((season, gameweek, team), 0) for team in table["team_id"].tolist()],
            index=table.index,
            dtype="int64",
        )
        attached.append(
            EvaluationFold(
                fold_id=fold.fold_id,
                projections=table,
                realized_points=fold.realized_points,
                metadata=dict(fold.metadata),
            )
        )
    return tuple(attached)
