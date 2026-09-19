"""A level correction by this season's minutes, fitted on earlier decisions only.

The protocol is ``docs/prior_minutes_level_prereg.md``. Stage one of the projection level audit
found the points forecast honest about its own size and blind to how much the player had played
this season. The candidate here is the smallest repair of that: for each bucket of prior
minutes, the ratio of realized to forecast points over every earlier decision, multiplied onto
the forecast. Nothing is searched, and no row's factor can see its own decision or a later one.

This module is the arithmetic and holds no file access.
"""

from typing import Final

import pandas as pd

from squadopt.evaluation.live_projection_audit import PRIOR_MINUTES_BUCKETS
from squadopt.evaluation.projection_level import FIRST_TARGET_GAMEWEEK

PRIOR_MINUTES_LEVEL_CONTRACT_VERSION: Final = "prior_minutes_level_v1"
#: Earlier decisions a factor needs behind it before it is anything but 1.
MINIMUM_EARLIER_DECISIONS: Final = 8
FACTOR_BOUNDS: Final[tuple[float, float]] = (0.0, 2.0)

FACTOR_COLUMNS: Final[tuple[str, ...]] = (
    "fold_id",
    "target_gameweek",
    "player_id",
    "forecast",
    "realized",
    "prior_minutes_per_week",
)


class PriorMinutesLevelError(ValueError):
    """The correction was handed a table it cannot read."""


def prior_bucket(prior: pd.Series) -> pd.Series:
    """The live audit's bucket of each prior; a prior that is absent has no bucket."""

    labels = pd.Series(pd.NA, index=prior.index, dtype="object")
    for label, low, high in PRIOR_MINUTES_BUCKETS:
        held = (prior == 0) if high == 0.0 else (prior > 0) & (prior >= low) & (prior < high)
        labels = labels.mask(held, label)
    return labels


def online_factors(frame: pd.DataFrame, decision_order: list[str]) -> pd.DataFrame:
    """The factor of every (decision, bucket), from the decisions strictly before it.

    ``decision_order`` is every decision in chronological order. A row counts towards later
    factors only if it is from target gameweek ``FIRST_TARGET_GAMEWEEK`` or later, has a
    forecast, and has a bucket. The result has one row per decision and bucket with the
    factor, the sums it came from, and how many earlier decisions stood behind it.
    """

    missing = [column for column in FACTOR_COLUMNS if column not in frame.columns]
    if missing:
        raise PriorMinutesLevelError(f"The factor table lacks {missing!r}.")
    if len(set(decision_order)) != len(decision_order):
        raise PriorMinutesLevelError("A decision is named twice in the order.")
    unknown = set(frame["fold_id"]) - set(decision_order)
    if unknown:
        raise PriorMinutesLevelError(f"Rows name decisions outside the order: {sorted(unknown)!r}.")

    labels = [label for label, _, _ in PRIOR_MINUTES_BUCKETS]
    usable = frame.loc[
        (frame["target_gameweek"] >= FIRST_TARGET_GAMEWEEK) & frame["forecast"].notna()
    ].assign(bucket=lambda rows: prior_bucket(rows["prior_minutes_per_week"]))
    usable = usable.loc[usable["bucket"].notna()]
    sums = (
        usable.groupby(["fold_id", "bucket"])[["forecast", "realized"]]
        .sum()
        .reindex(pd.MultiIndex.from_product([decision_order, labels], names=["fold_id", "bucket"]))
        .fillna(0.0)
    )
    seen = set(usable["fold_id"])
    # Strictly earlier: the running sum up to a decision, less the decision itself.
    earlier = sums.groupby(level="bucket").cumsum() - sums
    forecasts = {key: float(value) for key, value in earlier["forecast"].items()}
    outcomes = {key: float(value) for key, value in earlier["realized"].items()}
    low, high = FACTOR_BOUNDS
    records: list[dict[str, object]] = []
    behind = 0
    for fold in decision_order:
        for bucket in labels:
            forecast = forecasts[(fold, bucket)]
            realized = outcomes[(fold, bucket)]
            ready = behind >= MINIMUM_EARLIER_DECISIONS and forecast > 0
            records.append(
                {
                    "fold_id": fold,
                    "bucket": bucket,
                    "factor": min(max(realized / forecast, low), high) if ready else 1.0,
                    "earlier_decisions": behind,
                    "earlier_forecast_points": forecast,
                    "earlier_realized_points": realized,
                }
            )
        behind += int(fold in seen)
    return pd.DataFrame.from_records(records)


def corrected_forecast(frame: pd.DataFrame, factors: pd.DataFrame) -> pd.Series:
    """Each row's forecast times the factor of its decision and bucket.

    A row before the first gameweek read, a row with no prior, and a row with no forecast keep
    what they had: the first two are outside the correction, and an absent forecast stays
    absent.
    """

    bucket = prior_bucket(frame["prior_minutes_per_week"]).where(
        frame["target_gameweek"] >= FIRST_TARGET_GAMEWEEK
    )
    lookup = factors.set_index(["fold_id", "bucket"])["factor"]
    keys = pd.MultiIndex.from_arrays([frame["fold_id"], bucket])
    factor = pd.Series(lookup.reindex(keys).to_numpy(), index=frame.index).fillna(1.0)
    return frame["forecast"] * factor
