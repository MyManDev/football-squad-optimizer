"""Carrying a player's earlier-season record into a new season.

Rolling features reset at every season boundary, because ``season`` is part of the
grouping key that stops one season's closing gameweeks reaching the next season's
opener. That reset is correct, and it is also strict: a player with six seasons
behind them looks brand new every August.

This module supplies the missing signal without weakening the guard. The grouping
key is untouched. Instead, a separate feature reads **only completed earlier
seasons**, which is the one place a boundary crossing is legitimate — a finished
season lies entirely in the past of every gameweek in the current one.

Because it is the only feature that deliberately crosses the boundary the rest of
the layer defends, it carries its own leakage tests rather than relying on the
existing ones.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from numbers import Integral, Real

import pandas as pd

from squadopt.data.schema import (
    CANONICAL_SORT_COLUMNS,
    REQUIRED_COLUMNS,
    season_rank_map,
)
from squadopt.features.config import (
    MINUTES_PER_FULL_MATCH,
    FeatureConfigurationError,
)

PRIOR_RATE_COLUMN = "prior_seasons_points_per_90"
PRIOR_MINUTES_COLUMN = "prior_seasons_minutes_per_gameweek"
CROSS_SEASON_COLUMNS: tuple[str, ...] = (PRIOR_MINUTES_COLUMN, PRIOR_RATE_COLUMN)


@dataclass(frozen=True, slots=True)
class CrossSeasonConfig:
    """Weighting for a player's earlier-season record.

    ``decay`` discounts each additional season of distance, so last season counts
    for more than the one before it. A player's game changes over time; weighting
    every past season equally would let a strong season from years ago outvote a
    weak recent one.

    ``min_minutes`` is the total playing time a player's earlier seasons must add up
    to before the carry-over is considered usable. Below it the rate is left missing
    rather than reported from a handful of minutes, because a rate derived from two
    substitute appearances is noise wearing the costume of a measurement.

    Distance is counted in **seasons present in the panel**, not in calendar years.
    Deriving calendar distance would mean parsing season labels, and this project
    deliberately treats the ``YYYY-YY`` form as a convention rather than a guarantee.
    In practice a panel holds a contiguous range so the two agree; where they might
    not, ``season_order`` states the intended sequence explicitly.
    """

    decay: float = 0.5
    min_minutes: int = 270

    def __post_init__(self) -> None:
        if isinstance(self.decay, bool) or not isinstance(self.decay, Real):
            raise FeatureConfigurationError(f"decay must be a real number, got {self.decay!r}.")
        decay = float(self.decay)
        if not 0.0 < decay <= 1.0:
            raise FeatureConfigurationError(
                f"decay must be greater than 0 and at most 1, got {decay!r}."
            )
        if isinstance(self.min_minutes, bool) or not isinstance(self.min_minutes, Integral):
            raise FeatureConfigurationError(
                f"min_minutes must be an integer, got {self.min_minutes!r}."
            )
        minutes = int(self.min_minutes)
        if minutes < 0:
            raise FeatureConfigurationError(f"min_minutes must not be negative, got {minutes}.")

        object.__setattr__(self, "decay", decay)
        object.__setattr__(self, "min_minutes", minutes)


DEFAULT_CROSS_SEASON_CONFIG = CrossSeasonConfig()


def _season_totals(panel: pd.DataFrame) -> pd.DataFrame:
    """Aggregate each player's season into totals the carry-over can weight."""

    grouped = panel.groupby(["season", "player_id"], as_index=False, sort=True)
    return grouped.agg(
        season_minutes=("minutes", "sum"),
        season_points=("total_points", "sum"),
        season_gameweeks=("gameweek", "nunique"),
    )


def cross_season_features(
    panel: pd.DataFrame,
    *,
    config: CrossSeasonConfig | None = None,
    season_order: Sequence[str] | None = None,
) -> pd.DataFrame:
    """Return each row's carry-over from the player's completed earlier seasons.

    The result is indexed like ``panel`` and holds two columns: a decayed
    points-per-90 rate and decayed minutes per gameweek. Both are constant within a
    season for a given player, which is exactly right — they summarise what was known
    before the season began and nothing that has happened since.

    Values are missing for a player's first season, and for a player whose earlier
    seasons add up to less than ``min_minutes``.
    """

    if not isinstance(panel, pd.DataFrame):
        raise FeatureConfigurationError("cross_season_features expects a pandas DataFrame.")
    missing = [column for column in REQUIRED_COLUMNS if column not in panel.columns]
    if missing:
        raise FeatureConfigurationError(f"panel is missing required columns: {missing!r}.")
    if panel.empty:
        raise FeatureConfigurationError("panel must contain at least one row.")

    settings = DEFAULT_CROSS_SEASON_CONFIG if config is None else config
    ranks = season_rank_map(panel["season"].tolist(), season_order=season_order)

    totals = _season_totals(panel)
    totals["rank"] = [ranks[str(season)] for season in totals["season"]]

    # Accumulate each player's earlier seasons into the weighted numbers a target
    # season may use. Done per player over ranked seasons rather than vectorized,
    # because the weight depends on the distance between two seasons and clarity
    # matters more than speed at this size.
    carried: dict[tuple[str, object], tuple[float, float, float]] = {}
    for player_id, group in totals.groupby("player_id", sort=True):
        history = group.sort_values("rank", kind="stable")
        season_labels = [str(value) for value in history["season"].tolist()]
        season_ranks = [int(value) for value in history["rank"].tolist()]
        minutes_totals = [float(value) for value in history["season_minutes"].tolist()]
        points_totals = [float(value) for value in history["season_points"].tolist()]
        gameweek_totals = [float(value) for value in history["season_gameweeks"].tolist()]

        seen: list[tuple[int, float, float, float]] = []
        for position, target_rank in enumerate(season_ranks):
            weighted_minutes = 0.0
            weighted_points = 0.0
            weighted_gameweeks = 0.0
            for prior_rank, minutes, points, gameweeks in seen:
                weight = settings.decay ** (target_rank - prior_rank - 1)
                weighted_minutes += weight * minutes
                weighted_points += weight * points
                weighted_gameweeks += weight * gameweeks
            carried[(season_labels[position], player_id)] = (
                weighted_minutes,
                weighted_points,
                weighted_gameweeks,
            )
            seen.append(
                (
                    target_rank,
                    minutes_totals[position],
                    points_totals[position],
                    gameweek_totals[position],
                )
            )

    rates: list[float] = []
    minutes_per_gameweek: list[float] = []
    for season, player_id in zip(panel["season"], panel["player_id"], strict=True):
        weighted_minutes, weighted_points, weighted_gameweeks = carried.get(
            (str(season), player_id), (0.0, 0.0, 0.0)
        )
        if weighted_minutes < settings.min_minutes or weighted_gameweeks <= 0:
            rates.append(float("nan"))
            minutes_per_gameweek.append(float("nan"))
            continue
        rates.append(weighted_points / weighted_minutes * MINUTES_PER_FULL_MATCH)
        minutes_per_gameweek.append(weighted_minutes / weighted_gameweeks)

    return pd.DataFrame(
        {
            PRIOR_MINUTES_COLUMN: pd.Series(
                minutes_per_gameweek, index=panel.index, dtype="float64"
            ),
            PRIOR_RATE_COLUMN: pd.Series(rates, index=panel.index, dtype="float64"),
        },
        index=panel.index,
    )


def attach_cross_season_features(
    panel: pd.DataFrame,
    *,
    config: CrossSeasonConfig | None = None,
    season_order: Sequence[str] | None = None,
) -> pd.DataFrame:
    """Return an independent copy of the panel with the carry-over columns appended."""

    features = cross_season_features(panel, config=config, season_order=season_order)
    collisions = [column for column in CROSS_SEASON_COLUMNS if column in panel.columns]
    if collisions:
        raise FeatureConfigurationError(
            f"Cross-season columns already present: {collisions!r}; the panel has been "
            "processed once already."
        )
    combined = panel.copy(deep=True).join(features)
    return combined.sort_values(list(CANONICAL_SORT_COLUMNS), kind="stable").reset_index(drop=True)
