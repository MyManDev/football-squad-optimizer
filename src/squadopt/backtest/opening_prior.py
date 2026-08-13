"""Leakage-safe fit and holdout comparison for the opening-gameweek price prior."""

import math
from dataclasses import dataclass, field

import pandas as pd

from squadopt.backtest.splits import BacktestConfigurationError
from squadopt.data.schema import normalize_position
from squadopt.features import CrossSeasonConfig
from squadopt.features.config import MINUTES_PER_FULL_MATCH
from squadopt.features.cross_season import (
    PRIOR_MINUTES_COLUMN,
    PRIOR_RATE_COLUMN,
    carry_over_as_of,
)
from squadopt.prediction import BaselineProjectionConfig

OPENING_PRIOR_BACKTEST_CONTRACT_VERSION = "opening_price_prior_v1"
DEFAULT_OPENING_PRIOR_TRAINING_SEASONS: tuple[str, ...] = (
    "2020-21",
    "2021-22",
    "2022-23",
    "2023-24",
    "2024-25",
)
DEFAULT_OPENING_PRIOR_HOLDOUT_SEASON = "2025-26"

_REQUIRED_COLUMNS: tuple[str, ...] = (
    "season",
    "gameweek",
    "player_id",
    "position",
    "price_tenths",
    "minutes",
    "total_points",
)


@dataclass(frozen=True, slots=True)
class OpeningPriorMetrics:
    """Player-level error metrics for one opening-gameweek projection rule."""

    mean_absolute_error: float
    root_mean_squared_error: float
    mean_error: float


@dataclass(frozen=True, slots=True)
class OpeningPriorBacktestConfig:
    """Development seasons, locked holdout, and fixed carry-over controls."""

    training_seasons: tuple[str, ...] = DEFAULT_OPENING_PRIOR_TRAINING_SEASONS
    holdout_season: str = DEFAULT_OPENING_PRIOR_HOLDOUT_SEASON
    cross_season_config: CrossSeasonConfig = field(default_factory=CrossSeasonConfig)
    projection_config: BaselineProjectionConfig = field(default_factory=BaselineProjectionConfig)

    def __post_init__(self) -> None:
        if not isinstance(self.training_seasons, tuple) or not self.training_seasons:
            raise BacktestConfigurationError("training_seasons must be a non-empty tuple.")
        invalid_season = any(
            not isinstance(season, str) or not season.strip() for season in self.training_seasons
        )
        if invalid_season:
            raise BacktestConfigurationError("training_seasons entries must be non-empty strings.")
        normalized = tuple(season.strip() for season in self.training_seasons)
        if len(set(normalized)) != len(normalized):
            raise BacktestConfigurationError("training_seasons must not contain duplicates.")
        if not isinstance(self.holdout_season, str) or not self.holdout_season.strip():
            raise BacktestConfigurationError("holdout_season must be a non-empty string.")
        holdout = self.holdout_season.strip()
        if holdout in normalized:
            raise BacktestConfigurationError("holdout_season must not appear in training_seasons.")
        if not isinstance(self.cross_season_config, CrossSeasonConfig):
            raise BacktestConfigurationError(
                "cross_season_config must be a CrossSeasonConfig instance."
            )
        if not isinstance(self.projection_config, BaselineProjectionConfig):
            raise BacktestConfigurationError(
                "projection_config must be a BaselineProjectionConfig instance."
            )

        object.__setattr__(self, "training_seasons", normalized)
        object.__setattr__(self, "holdout_season", holdout)


@dataclass(frozen=True, slots=True)
class OpeningPriorBacktestResult:
    """Structured out-of-sample comparison for opening-gameweek priors."""

    contract_version: str
    fitted_coefficient: float
    training_seasons: tuple[str, ...]
    holdout_season: str
    training_observations: int
    holdout_observations: int
    carry_over_observations: int
    carry_over_coverage: float
    price_only: OpeningPriorMetrics
    carry_over_with_constant: OpeningPriorMetrics
    carry_over_with_price: OpeningPriorMetrics


def _require_panel(panel: pd.DataFrame) -> pd.DataFrame:
    if not isinstance(panel, pd.DataFrame):
        raise BacktestConfigurationError("opening-prior backtest expects a pandas DataFrame.")
    missing = [column for column in _REQUIRED_COLUMNS if column not in panel.columns]
    if missing:
        raise BacktestConfigurationError(
            f"Historical panel is missing required columns: {missing!r}."
        )
    if panel.empty:
        raise BacktestConfigurationError("Historical panel must contain at least one row.")
    return panel


def _opening_rows(panel: pd.DataFrame, season: str) -> pd.DataFrame:
    season_rows = panel.loc[panel["season"].astype("string").eq(season)]
    if season_rows.empty:
        raise BacktestConfigurationError(f"Historical panel has no rows for season {season!r}.")
    try:
        opening_gameweek = int(pd.to_numeric(season_rows["gameweek"], errors="raise").min())
    except (TypeError, ValueError) as error:
        raise BacktestConfigurationError(
            f"gameweek must be numeric for season {season!r}: {error}"
        ) from error
    opening = season_rows.loc[season_rows["gameweek"].eq(opening_gameweek)].copy(deep=True)
    duplicated = opening.loc[opening["player_id"].duplicated(), "player_id"].tolist()
    if duplicated:
        raise BacktestConfigurationError(
            f"Opening rows for {season!r} contain duplicate player ids: {duplicated[:10]!r}."
        )
    return opening.sort_values("player_id", kind="stable").reset_index(drop=True)


def _numeric(series: pd.Series, name: str) -> pd.Series:
    try:
        values = pd.to_numeric(series, errors="raise").astype("float64")
    except (TypeError, ValueError) as error:
        raise BacktestConfigurationError(f"{name} must be numeric: {error}") from error
    invalid = ~values.map(math.isfinite)
    if bool(invalid.any()):
        raise BacktestConfigurationError(f"{name} must contain only finite values.")
    return values


def fit_opening_price_coefficient(
    panel: pd.DataFrame,
    *,
    seasons: tuple[str, ...],
) -> float:
    """Fit ``points = coefficient * price`` through the origin on past GW1 rows.

    ``price`` is expressed in whole millions (``price_tenths / 10``). The fit is
    constrained to be non-negative because the public projection contract rejects
    negative expected points.
    """

    frame = _require_panel(panel)
    if not isinstance(seasons, tuple) or not seasons:
        raise BacktestConfigurationError("seasons must be a non-empty tuple.")
    if any(not isinstance(season, str) or not season.strip() for season in seasons):
        raise BacktestConfigurationError("seasons entries must be non-empty strings.")

    observations = pd.concat(
        [_opening_rows(frame, season.strip()) for season in seasons], ignore_index=True
    )
    price = _numeric(observations["price_tenths"], "price_tenths").div(10.0)
    if bool(price.lt(0).any()):
        raise BacktestConfigurationError("price_tenths must be non-negative.")
    realized = _numeric(observations["total_points"], "total_points")
    price_values = [float(value) for value in price.tolist()]
    realized_values = [float(value) for value in realized.tolist()]
    denominator = sum(value * value for value in price_values)
    if denominator <= 0:
        raise BacktestConfigurationError("Cannot fit a price coefficient when every price is zero.")
    numerator = sum(
        price_value * realized_value
        for price_value, realized_value in zip(price_values, realized_values, strict=True)
    )
    return max(0.0, numerator / denominator)


def _metrics(projected: pd.Series, realized: pd.Series) -> OpeningPriorMetrics:
    error = projected.astype("float64").sub(realized.astype("float64"))
    errors = [float(value) for value in error.tolist()]
    count = len(errors)
    return OpeningPriorMetrics(
        mean_absolute_error=sum(abs(value) for value in errors) / count,
        root_mean_squared_error=(sum(value * value for value in errors) / count) ** 0.5,
        mean_error=sum(errors) / count,
    )


def run_opening_prior_backtest(
    panel: pd.DataFrame,
    config: OpeningPriorBacktestConfig | None = None,
) -> OpeningPriorBacktestResult:
    """Fit on development seasons and compare three rules on one untouched holdout.

    The holdout's realized points are used only after the coefficient and all
    predictions are frozen. Carry-over is built only from the declared training
    seasons, so neither rule can see the holdout outcome it is scored against.
    """

    frame = _require_panel(panel)
    settings = OpeningPriorBacktestConfig() if config is None else config
    if not isinstance(settings, OpeningPriorBacktestConfig):
        raise BacktestConfigurationError("config must be an OpeningPriorBacktestConfig instance.")

    coefficient = fit_opening_price_coefficient(
        frame,
        seasons=settings.training_seasons,
    )
    training_rows = [_opening_rows(frame, season) for season in settings.training_seasons]
    holdout = _opening_rows(frame, settings.holdout_season)
    history = frame.loc[frame["season"].isin(settings.training_seasons)].copy(deep=True)
    carried = carry_over_as_of(
        history,
        target_season=settings.holdout_season,
        config=settings.cross_season_config,
        season_order=(*settings.training_seasons, settings.holdout_season),
    )
    compared = holdout.merge(carried, on="player_id", how="left", validate="one_to_one")

    price = _numeric(compared["price_tenths"], "price_tenths").div(10.0)
    price_projection = price.mul(coefficient).clip(lower=0.0)
    has_carry = compared[PRIOR_RATE_COLUMN].notna() & compared[PRIOR_MINUTES_COLUMN].notna()
    # _numeric deliberately rejects missing values, while a missing carry-over is
    # expected for newcomers. Restore those rows after validating the finite subset.
    carried_projection = pd.Series(float("nan"), index=compared.index, dtype="float64")
    if bool(has_carry.any()):
        rates = _numeric(compared.loc[has_carry, PRIOR_RATE_COLUMN], PRIOR_RATE_COLUMN)
        minutes = _numeric(compared.loc[has_carry, PRIOR_MINUTES_COLUMN], PRIOR_MINUTES_COLUMN)
        carried_projection.loc[has_carry] = (
            rates.mul(minutes).div(MINUTES_PER_FULL_MATCH).clip(lower=0.0)
        )

    constants = [
        settings.projection_config.opening_expected_points[normalize_position(position)]
        for position in compared["position"].tolist()
    ]
    carried_values = [float(value) for value in carried_projection.tolist()]
    price_values = [float(value) for value in price_projection.tolist()]
    has_carry_values = [bool(value) for value in has_carry.tolist()]
    carry_with_constant = pd.Series(
        [
            carried_value if available else constant
            for carried_value, available, constant in zip(
                carried_values, has_carry_values, constants, strict=True
            )
        ],
        index=compared.index,
        dtype="float64",
    )
    carry_with_price = pd.Series(
        [
            carried_value if available else price_value
            for carried_value, available, price_value in zip(
                carried_values, has_carry_values, price_values, strict=True
            )
        ],
        index=compared.index,
        dtype="float64",
    )
    realized = _numeric(compared["total_points"], "total_points")

    carry_count = int(has_carry.sum())
    return OpeningPriorBacktestResult(
        contract_version=OPENING_PRIOR_BACKTEST_CONTRACT_VERSION,
        fitted_coefficient=coefficient,
        training_seasons=settings.training_seasons,
        holdout_season=settings.holdout_season,
        training_observations=sum(len(rows) for rows in training_rows),
        holdout_observations=len(holdout),
        carry_over_observations=carry_count,
        carry_over_coverage=carry_count / len(holdout),
        price_only=_metrics(price_projection, realized),
        carry_over_with_constant=_metrics(carry_with_constant, realized),
        carry_over_with_price=_metrics(carry_with_price, realized),
    )
