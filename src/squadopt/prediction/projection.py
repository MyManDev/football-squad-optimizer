"""Construction of the optimizer-ready projection table.

This is the hand-off point. Everything upstream — raw column names, adapters,
cleaning rules, feature windows — stops here, and the optimizer sees only the six
agreed columns.
"""

import math
from numbers import Integral

import pandas as pd

from squadopt.data.errors import format_examples
from squadopt.data.schema import PROJECTION_REQUIRED_COLUMNS
from squadopt.prediction.baseline import baseline_expected_points
from squadopt.prediction.config import (
    BaselineProjectionConfig,
    PredictionConfigurationError,
)

# Columns copied straight from the target gameweek's row. Each is known at that
# gameweek's deadline, so reading them from row `t` is correct rather than leaky.
# Player price is the case that matters: the optimizer has to spend what is
# actually payable, not a stale figure from the previous gameweek.
_PRE_MATCH_PASSTHROUGH: tuple[str, ...] = (
    "player_id",
    "name",
    "team_id",
    "position",
    "price_tenths",
)


def _select_target_gameweek(features: pd.DataFrame, season: str, gameweek: int) -> pd.DataFrame:
    selected = features.loc[(features["season"] == season) & (features["gameweek"] == gameweek)]
    if not selected.empty:
        return selected

    available_seasons = sorted({str(value) for value in features["season"].tolist()})
    available_gameweeks = sorted({int(value) for value in features["gameweek"].tolist()})
    raise PredictionConfigurationError(
        f"No rows for season={season!r}, gameweek={gameweek!r}; "
        f"available seasons are {format_examples(available_seasons)} "
        f"and gameweeks are {format_examples(available_gameweeks)}."
    )


def _verify_contract(table: pd.DataFrame) -> None:
    """Recheck the agreed contract before handing the table over.

    The optimizer validates its own input, but a violation caught here names the
    projection stage that produced it instead of surfacing as a puzzling rejection
    one module later.
    """

    duplicates = table.loc[table["player_id"].duplicated(), "player_id"].tolist()
    if duplicates:
        raise PredictionConfigurationError(
            f"Projection table has duplicate player_id values: {format_examples(duplicates)}."
        )

    prices = table["price_tenths"].tolist()
    invalid_prices = [
        value for value in prices if isinstance(value, bool) or not isinstance(value, Integral)
    ]
    if invalid_prices:
        raise PredictionConfigurationError(
            "price_tenths must stay integral for the optimizer's budget constraint; "
            f"got {format_examples(invalid_prices)}."
        )

    points = table["expected_points"].tolist()
    invalid_points = [
        value for value in points if not math.isfinite(float(value)) or float(value) < 0
    ]
    if invalid_points:
        raise PredictionConfigurationError(
            "expected_points must be finite and non-negative; "
            f"got {format_examples(invalid_points)}."
        )


def build_projection_table(
    features: pd.DataFrame,
    *,
    season: str,
    gameweek: int,
    config: BaselineProjectionConfig | None = None,
) -> pd.DataFrame:
    """Build the optimizer-ready projection table for one target gameweek.

    Returns exactly the six agreed columns — ``player_id``, ``name``, ``team_id``,
    ``position``, ``price_tenths``, ``expected_points`` — for every player in the
    given season and gameweek, ordered by ``player_id`` with a reset index.

    Identity, team, position, and price come from the target gameweek's own row,
    because all four are fixed at that gameweek's deadline. ``expected_points``
    comes from the baseline, which reads only shifted features and therefore only
    earlier gameweeks.

    This is the prediction-ready dataset's counterpart, not the same thing: the
    historical feature dataset spans every gameweek and carries rolling columns for
    model development, while this table is one gameweek wide and carries nothing
    the optimizer does not need.
    """

    if not isinstance(features, pd.DataFrame):
        raise PredictionConfigurationError("build_projection_table expects a pandas DataFrame.")

    required = ("season", "gameweek", *_PRE_MATCH_PASSTHROUGH)
    missing = [column for column in required if column not in features.columns]
    if missing:
        raise PredictionConfigurationError(
            f"Feature dataset is missing required columns: {missing!r}."
        )

    selected = _select_target_gameweek(features, season, gameweek)
    projected = baseline_expected_points(selected, config=config)

    table = selected.loc[:, list(_PRE_MATCH_PASSTHROUGH)].copy(deep=True)
    table["expected_points"] = projected
    table = table.sort_values("player_id", kind="stable").reset_index(drop=True)
    table = table.loc[:, list(PROJECTION_REQUIRED_COLUMNS)]

    _verify_contract(table)
    return table
