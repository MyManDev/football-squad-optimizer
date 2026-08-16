"""Measure how far a projection drifts as the horizon lengthens.

The projection horizon builder ships a table the transfer planner consumes, and every
record of it carries the same disclaimer: expected minutes for a later gameweek are
computed from what was known at the decision point, so injuries, rotation and suspensions
in between are unseen. That disclaimer has been the only thing standing between a planner
and an unmeasured input. This replaces it with a number.

The measurement needs no captured snapshot. The question is what information at a decision
point implies for a gameweek `k` ahead, and the archive answers it directly for every
chronological development fold: project once at the decision point, then score that same
projection against gameweek `t`, `t+1`, `t+2` and so on.

Two decisions shape what the numbers mean.

**The shipped scaling is applied at every offset, including zero.** The horizon scales
expected points by each gameweek's fixture count, so measuring anything else would measure
a projection nobody ships. At offset zero on a single-fixture row the scaling is the
identity, which is what ties this population back to the ordinary residual history.

**A player missing at `t+k` is dropped and counted, never scored as an error.** A
transferred or delisted player is an absence from the data, not a bad projection, and
silently keeping them would attribute squad churn to the model. The dropped count is
reported at every offset because it grows with `k` and would otherwise quietly change the
population the errors describe.
"""

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Final

import numpy as np
import pandas as pd

from squadopt.backtest.folds import build_walk_forward_folds, make_baseline_projection_builder
from squadopt.backtest.splits import (
    BacktestConfigurationError,
    DecisionPoint,
    realized_points_at,
    season_ranks,
)
from squadopt.data.fixtures import aggregate_team_gameweek
from squadopt.features import CrossSeasonConfig

HORIZON_DECAY_CONTRACT_VERSION: Final = "horizon_decay_v1"

# Matches the rule the horizon builder applies, named so a reader can tell the two are
# the same treatment rather than two implementations that happen to agree today.
FIXTURE_SCALING_RULE_VERSION: Final = "linear_fixture_count_scaling_v1"

FIXTURE_GROUPS: Final = ("blank", "single", "double_plus")


def _fixture_group(count: int) -> str:
    if count == 0:
        return "blank"
    if count == 1:
        return "single"
    return "double_plus"


@dataclass(frozen=True, slots=True)
class OffsetMetrics:
    """Error at one horizon offset, overall and split by that gameweek's calendar."""

    offset: int
    observations: int
    dropped_players: int
    bias: float
    mean_absolute_error: float
    root_mean_squared_error: float
    by_fixture_group: Mapping[str, Mapping[str, float]] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class HorizonDecayResult:
    """The decay curve and the population behind it."""

    contract_version: str
    seasons: tuple[str, ...]
    form_window: int
    max_offset: int
    offsets: tuple[OffsetMetrics, ...]
    residuals: pd.DataFrame


def _metrics(frame: pd.DataFrame) -> tuple[float, float, float]:
    residual = frame["residual"].to_numpy(dtype="float64")
    if residual.size == 0:
        return (float("nan"), float("nan"), float("nan"))
    return (
        float(residual.mean()),
        float(np.abs(residual).mean()),
        float(math.sqrt(float(np.square(residual).mean()))),
    )


def _team_code_bridge(team_codes: pd.DataFrame) -> pd.DataFrame:
    required = ("season", "name", "code")
    missing = [column for column in required if column not in team_codes.columns]
    if missing:
        raise BacktestConfigurationError(f"team_codes is missing columns: {missing!r}.")
    bridge = team_codes.loc[:, list(required)].copy(deep=True)
    bridge["season"] = bridge["season"].astype("string")
    bridge["name"] = bridge["name"].astype("string")
    duplicated = bridge.loc[bridge.duplicated(subset=["season", "name"]), "name"].tolist()
    if duplicated:
        raise BacktestConfigurationError(
            f"team_codes maps the same season and name twice: {duplicated!r}."
        )
    return bridge.rename(columns={"name": "team_id", "code": "team_code"})


def measure_horizon_decay(
    panel: pd.DataFrame,
    fixtures: pd.DataFrame,
    team_codes: pd.DataFrame,
    *,
    seasons: Sequence[str],
    max_offset: int = 3,
    form_window: int = 5,
    min_prior_gameweeks_in_season: int = 1,
) -> HorizonDecayResult:
    """Score one projection per decision point against that gameweek and the next few."""

    if not isinstance(panel, pd.DataFrame):
        raise BacktestConfigurationError("panel must be a pandas DataFrame.")
    if isinstance(max_offset, bool) or not isinstance(max_offset, int) or max_offset < 0:
        raise BacktestConfigurationError("max_offset must be a non-negative integer.")

    requested = tuple(seasons)
    ranks = season_ranks(panel)
    unknown = sorted(set(requested) - set(ranks))
    if unknown:
        raise BacktestConfigurationError(
            f"Development seasons are absent from the panel: {unknown!r}."
        )
    last_rank = max(ranks[season] for season in requested)
    visible = panel.loc[panel["season"].map(lambda season: ranks[str(season)] <= last_rank)]

    calendar = aggregate_team_gameweek(fixtures)
    bridge = _team_code_bridge(team_codes)

    folds = build_walk_forward_folds(
        visible,
        seasons=requested,
        min_prior_gameweeks_in_season=min_prior_gameweeks_in_season,
        projection_builder=make_baseline_projection_builder(
            form_window=form_window, cross_season=CrossSeasonConfig()
        ),
    )

    pieces: list[pd.DataFrame] = []
    dropped: dict[int, int] = dict.fromkeys(range(max_offset + 1), 0)

    for fold in folds:
        season = str(fold.metadata["season"])
        gameweek = int(str(fold.metadata["gameweek"]))
        base = fold.projections.loc[:, ["player_id", "team_id", "position", "expected_points"]]
        season_bridge = bridge.loc[bridge["season"] == season, ["team_id", "team_code"]]
        keyed = base.merge(season_bridge, on="team_id", how="left", validate="many_to_one")

        for offset in range(max_offset + 1):
            target = gameweek + offset
            outcomes = visible.loc[(visible["season"] == season) & (visible["gameweek"] == target)]
            if outcomes.empty:
                # Past the end of the season; not a drop, simply no question to ask.
                continue
            realized = realized_points_at(visible, DecisionPoint(season=season, gameweek=target))

            counts = calendar.loc[
                (calendar["season"].astype("string") == season) & (calendar["gameweek"] == target),
                ["team_id", "fixture_count"],
            ].rename(columns={"team_id": "team_code"})

            scaled = keyed.merge(counts, on="team_code", how="left", validate="many_to_one")
            fixture_count = scaled["fixture_count"].fillna(0).astype("int64")
            scaled["fixture_count"] = fixture_count
            scaled["predicted_points"] = (
                scaled["expected_points"].astype("float64").mul(fixture_count.astype("float64"))
            )

            paired = scaled.merge(
                realized.loc[:, ["player_id", "total_points"]],
                on="player_id",
                how="inner",
                validate="one_to_one",
            )
            dropped[offset] += len(scaled) - len(paired)

            pieces.append(
                pd.DataFrame(
                    {
                        "fold_id": fold.fold_id,
                        "season": season,
                        "decision_gameweek": gameweek,
                        "offset": offset,
                        "target_gameweek": target,
                        "player_id": paired["player_id"],
                        "position": paired["position"],
                        "fixture_count": paired["fixture_count"],
                        "predicted_points": paired["predicted_points"].astype("float64"),
                        "realized_points": paired["total_points"].astype("float64"),
                    }
                )
            )

    if not pieces:
        raise BacktestConfigurationError("No comparable rows were produced.")
    residuals = pd.concat(pieces, ignore_index=True)
    residuals["residual"] = residuals["realized_points"] - residuals["predicted_points"]
    residuals["fixture_group"] = [
        _fixture_group(int(value)) for value in residuals["fixture_count"]
    ]

    offsets: list[OffsetMetrics] = []
    for offset in range(max_offset + 1):
        rows = residuals.loc[residuals["offset"] == offset]
        if rows.empty:
            continue
        bias, mae, rmse = _metrics(rows)
        groups: dict[str, Mapping[str, float]] = {}
        for group in FIXTURE_GROUPS:
            subset = rows.loc[rows["fixture_group"] == group]
            if subset.empty:
                continue
            group_bias, group_mae, group_rmse = _metrics(subset)
            groups[group] = {
                "observations": float(len(subset)),
                "bias": group_bias,
                "mean_absolute_error": group_mae,
                "root_mean_squared_error": group_rmse,
            }
        offsets.append(
            OffsetMetrics(
                offset=offset,
                observations=len(rows),
                dropped_players=dropped[offset],
                bias=bias,
                mean_absolute_error=mae,
                root_mean_squared_error=rmse,
                by_fixture_group=groups,
            )
        )

    return HorizonDecayResult(
        contract_version=HORIZON_DECAY_CONTRACT_VERSION,
        seasons=requested,
        form_window=form_window,
        max_offset=max_offset,
        offsets=tuple(offsets),
        residuals=residuals,
    )
