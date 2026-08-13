"""Projections for a season that has not started yet.

Every other projection reads a panel of played gameweeks. A season about to begin has
none: its players arrive as a roster — identities, clubs, positions, and opening
prices — and everything known about how they perform sits in earlier seasons.

So this module joins the two. The roster supplies what is fixed at the opening
deadline; the carried record supplies the expectation. Players with no earlier record
fall to the fitted deadline-price prior.

The join is safe because player identity is the stable cross-season code rather than
a per-season element id — established by inspecting the archive, not assumed.
"""

import math
from collections.abc import Mapping

import pandas as pd

from squadopt.data.errors import InvalidValueError, format_examples
from squadopt.data.schema import (
    POSITIONS,
    PROJECTION_REQUIRED_COLUMNS,
    normalize_position,
)
from squadopt.features.config import MINUTES_PER_FULL_MATCH
from squadopt.features.cross_season import (
    PRIOR_MINUTES_COLUMN,
    PRIOR_RATE_COLUMN,
    CrossSeasonConfig,
    carry_over_as_of,
)
from squadopt.prediction.config import (
    DEFAULT_PROJECTION_CONFIG,
    BaselineProjectionConfig,
    PredictionConfigurationError,
)

# The roster columns this module needs, in canonical terms. A roster already carries
# canonical position labels: translating a platform's numeric encoding is source
# knowledge, so it happens in the source module rather than here.
ROSTER_COLUMN_MAP: Mapping[str, str] = {
    "code": "player_id",
    "web_name": "name",
    "team": "team_id",
    "position": "position",
    "now_cost": "price_tenths",
}


def _require_roster(roster: pd.DataFrame) -> pd.DataFrame:
    if not isinstance(roster, pd.DataFrame):
        raise PredictionConfigurationError("roster must be a pandas DataFrame.")
    missing = [column for column in ROSTER_COLUMN_MAP if column not in roster.columns]
    if missing:
        raise PredictionConfigurationError(f"roster is missing columns: {missing!r}.")
    if roster.empty:
        raise PredictionConfigurationError("roster must contain at least one player.")
    return roster


def _canonical_roster(roster: pd.DataFrame) -> pd.DataFrame:
    """Rename and coerce roster columns into the canonical representation.

    ``now_cost`` is already integer tenths, and it is unambiguous in a way no
    in-season price is: the season has not begun, so nothing can have moved it.
    """

    selected_source = roster.loc[:, list(ROSTER_COLUMN_MAP)]
    for column in ROSTER_COLUMN_MAP:
        missing = selected_source[column].isna()
        if bool(missing.any()):
            raise PredictionConfigurationError(f"roster column {column!r} contains missing values.")

    selected = selected_source.rename(columns=dict(ROSTER_COLUMN_MAP))
    frame = selected.copy(deep=True)

    for column in ("player_id", "team_id", "price_tenths"):
        raw_values = frame[column].tolist()
        if any(isinstance(value, bool) for value in raw_values):
            raise PredictionConfigurationError(
                f"roster column {column!r} must contain integers, not booleans."
            )
        try:
            numeric = pd.to_numeric(frame[column], errors="raise")
            invalid = [
                value
                for value in numeric.tolist()
                if not math.isfinite(float(value)) or float(value) != int(float(value))
            ]
        except (OverflowError, TypeError, ValueError) as error:
            raise PredictionConfigurationError(
                f"roster column {column!r} must be numeric: {error}"
            ) from error
        # Casting straight to int64 would truncate rather than complain, turning a
        # price of 7.5 into 7 — a tenfold error delivered silently. The check is
        # explicit for that reason.
        if invalid:
            raise PredictionConfigurationError(
                f"roster column {column!r} must be integral; got "
                f"{format_examples(invalid)}. Prices are integer tenths: 7.5 is 75."
            )
        try:
            frame[column] = numeric.astype("int64")
        except (OverflowError, TypeError, ValueError) as error:
            raise PredictionConfigurationError(
                f"roster column {column!r} does not fit the integer contract: {error}"
            ) from error

    negative_prices = frame.loc[frame["price_tenths"] < 0, "price_tenths"].tolist()
    if negative_prices:
        raise PredictionConfigurationError(
            f"roster column 'price_tenths' must be non-negative; got "
            f"{format_examples(negative_prices)}."
        )

    frame["name"] = frame["name"].astype("string")
    blank_names = frame["name"].str.strip().eq("")
    if bool(blank_names.any()):
        raise PredictionConfigurationError("roster column 'web_name' contains blank values.")
    try:
        normalized_positions = [normalize_position(value) for value in frame["position"].tolist()]
    except InvalidValueError as error:
        raise PredictionConfigurationError(
            f"roster column 'position' is invalid: {error}"
        ) from error
    frame["position"] = pd.Series(normalized_positions, index=frame.index, dtype="string")

    duplicated = frame.loc[frame["player_id"].duplicated(), "player_id"].tolist()
    if duplicated:
        raise PredictionConfigurationError(
            f"roster has duplicate player identifiers: {format_examples(duplicated)}."
        )
    return frame


def _fallback_for(
    positions: list[str], prices_tenths: list[int], config: BaselineProjectionConfig
) -> list[float]:
    coefficient = config.opening_price_coefficient
    if coefficient is not None:
        return [coefficient * price / 10.0 for price in prices_tenths]

    values: list[float] = []
    for position in positions:
        if position not in POSITIONS:
            raise PredictionConfigurationError(
                f"Cannot project an unknown position {position!r}; expected one of "
                f"{list(POSITIONS)!r}."
            )
        values.append(config.opening_expected_points[position])
    return values


def build_opening_projection_table(
    panel: pd.DataFrame,
    roster: pd.DataFrame,
    *,
    season: str,
    config: BaselineProjectionConfig | None = None,
    cross_season: CrossSeasonConfig | None = None,
) -> pd.DataFrame:
    """Build the optimizer-ready projection table for a season's opening gameweek.

    ``panel`` is the canonical history of completed seasons; ``roster`` is the
    upcoming season's player list. Neither is modified.

    Returns exactly the six agreed columns, ordered by ``player_id`` with a reset
    index, and carries a ``has_prior_record`` column so a caller can see how much of
    the pool is projected from real history rather than from the price prior.

    Every projection is finite and non-negative, and no value depends on a gameweek
    that has not been played — the carried record reads completed seasons only.
    """

    settings = DEFAULT_PROJECTION_CONFIG if config is None else config
    carry_settings = CrossSeasonConfig() if cross_season is None else cross_season

    players = _canonical_roster(_require_roster(roster))
    carried = carry_over_as_of(panel, target_season=season, config=carry_settings)

    merged = players.merge(carried, on="player_id", how="left", validate="one_to_one")

    rate = merged[PRIOR_RATE_COLUMN].astype("float64")
    minutes = merged[PRIOR_MINUTES_COLUMN].astype("float64")
    projected = rate.mul(minutes).div(MINUTES_PER_FULL_MATCH)

    fallback = pd.Series(
        _fallback_for(
            [str(value) for value in merged["position"].tolist()],
            [int(value) for value in merged["price_tenths"].tolist()],
            settings,
        ),
        index=merged.index,
        dtype="float64",
    )
    expected = projected.where(projected.notna(), fallback).clip(lower=0.0).astype("float64")
    non_finite = [value for value in expected.tolist() if not math.isfinite(float(value))]
    if non_finite:
        raise PredictionConfigurationError(
            f"Opening projections contain non-finite values: {format_examples(non_finite)}."
        )

    table = merged.loc[:, ["player_id", "name", "team_id", "position", "price_tenths"]].copy(
        deep=True
    )
    table["expected_points"] = expected
    table["has_prior_record"] = projected.notna().to_numpy()
    table = table.sort_values("player_id", kind="stable").reset_index(drop=True)

    ordered = [*PROJECTION_REQUIRED_COLUMNS, "has_prior_record"]
    result = table.loc[:, ordered]

    if not bool(result["expected_points"].notna().all()):
        raise PredictionConfigurationError("Opening projections contain missing values.")
    return result
