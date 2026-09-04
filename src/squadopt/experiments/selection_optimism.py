"""Profile of the selection-time optimism the deterministic optimizer inherits.

The scenario audit measured a +34.5-point decision-level bias and named the
mechanism as winner's curse. This module maps the mechanism itself: on every real
fold it compares the residuals (realized minus projected) of the players the
optimizer actually selects against the residuals of the whole roster, broken down
by projection rank and by position. The profile decides where a correction must
act — top-ranked players, the captain, a position — before any correction is built.
"""

import math
from collections.abc import Mapping
from dataclasses import dataclass, replace
from types import MappingProxyType
from typing import Final

import pandas as pd

from squadopt.backtest import realized_points_at, season_ranks, walk_forward_decision_points
from squadopt.experiments.config import ExperimentExecutionError
from squadopt.experiments.policy_objective import PolicyObjectiveConfig
from squadopt.features import build_feature_dataset
from squadopt.optimization import optimize_squad
from squadopt.prediction import FormWindowMapping, build_projection_table

SELECTION_OPTIMISM_CONTRACT_VERSION: Final = "selection_optimism_profile_v1"
RANK_BUCKETS: Final = (("top_05", 0, 5), ("rank_06_15", 5, 15), ("rank_16_plus", 15, None))


@dataclass(frozen=True, slots=True)
class SelectionOptimismResult:
    """Aggregate residual gaps between selected players and the full roster."""

    fold_count: int
    form_window: int
    bench_weight: float
    roster_mean_residual: float
    starter_mean_residual: float
    captain_mean_residual: float
    selection_gap_per_starter: float
    mean_projected_xi_score: float
    mean_realized_xi_score: float
    rank_bucket_mean_residuals: Mapping[str, float]
    position_starter_mean_residuals: Mapping[str, float]
    diagnostics: Mapping[str, object]
    contract_version: str = SELECTION_OPTIMISM_CONTRACT_VERSION

    def __post_init__(self) -> None:
        if self.contract_version != SELECTION_OPTIMISM_CONTRACT_VERSION:
            raise ExperimentExecutionError("Unsupported selection optimism contract_version.")
        if self.fold_count < 1:
            raise ExperimentExecutionError("fold_count must be positive.")
        for name in (
            "roster_mean_residual",
            "starter_mean_residual",
            "captain_mean_residual",
            "selection_gap_per_starter",
        ):
            if not math.isfinite(float(getattr(self, name))):
                raise ExperimentExecutionError(f"{name} must be finite.")
        object.__setattr__(
            self,
            "rank_bucket_mean_residuals",
            MappingProxyType(dict(self.rank_bucket_mean_residuals)),
        )
        object.__setattr__(
            self,
            "position_starter_mean_residuals",
            MappingProxyType(dict(self.position_starter_mean_residuals)),
        )
        object.__setattr__(self, "diagnostics", MappingProxyType(dict(self.diagnostics)))


def measure_selection_optimism(
    panel: pd.DataFrame,
    config: PolicyObjectiveConfig | None = None,
    *,
    form_window: int = 6,
    bench_weight: float = 0.0,
) -> SelectionOptimismResult:
    """Measure selected-versus-roster residual gaps on every development fold."""

    settings = PolicyObjectiveConfig() if config is None else config
    if not isinstance(settings, PolicyObjectiveConfig):
        raise ExperimentExecutionError("config must be a PolicyObjectiveConfig instance.")
    if not isinstance(panel, pd.DataFrame):
        raise ExperimentExecutionError("panel must be a pandas DataFrame.")
    ranks = season_ranks(panel)
    unknown = sorted(set(settings.development_seasons) - set(ranks))
    if unknown:
        raise ExperimentExecutionError(
            f"Development seasons are absent from the panel: {unknown!r}."
        )
    last_rank = max(ranks[season] for season in settings.development_seasons)
    keep = panel["season"].map(lambda season: ranks[str(season)] <= last_rank)
    visible_panel = panel.loc[keep].copy(deep=True)
    decisions = walk_forward_decision_points(
        visible_panel,
        seasons=settings.development_seasons,
        min_prior_gameweeks_in_season=settings.min_prior_gameweeks_in_season,
    )
    if not decisions:
        raise ExperimentExecutionError("No decision points remain for the requested seasons.")
    mapping = FormWindowMapping(form_window=form_window)
    features = build_feature_dataset(
        visible_panel,
        config=mapping.feature_config,
        cross_season=settings.cross_season_config,
    )
    optimization_config = replace(settings.optimization_config, bench_weight=bench_weight)

    roster_residuals: list[float] = []
    starter_residuals: list[float] = []
    captain_residuals: list[float] = []
    projected_scores: list[float] = []
    realized_scores: list[float] = []
    bucket_values: dict[str, list[float]] = {name: [] for name, _, _ in RANK_BUCKETS}
    position_values: dict[str, list[float]] = {}
    for decision in decisions:
        projections = build_projection_table(
            features,
            season=decision.season,
            gameweek=decision.gameweek,
            config=mapping.projection_config,
        )
        realized = realized_points_at(visible_panel, decision)
        merged = projections.merge(realized, on="player_id", how="left")
        if bool(merged["total_points"].isna().any()):
            raise ExperimentExecutionError(
                f"Fold {decision.fold_id} projects players with no realized outcome."
            )
        merged["residual"] = merged["total_points"].astype("float64") - merged[
            "expected_points"
        ].astype("float64")
        roster_residuals.extend(float(value) for value in merged["residual"])

        ordered = merged.sort_values(
            ["expected_points", "player_id"], ascending=[False, True], kind="stable"
        ).reset_index(drop=True)
        for name, start, stop in RANK_BUCKETS:
            chunk = ordered.iloc[start:stop] if stop is not None else ordered.iloc[start:]
            bucket_values[name].extend(float(value) for value in chunk["residual"])

        result = optimize_squad(projections, optimization_config)
        if not result.has_solution or result.captain is None:
            raise ExperimentExecutionError(
                f"Fold {decision.fold_id} has no feasible deterministic decision."
            )
        by_player = merged.set_index("player_id")
        starter_ids = result.starting_xi["player_id"].tolist()
        captain_id = result.captain["player_id"]
        fold_projected = 0.0
        fold_realized = 0.0
        for player_id in starter_ids:
            row = by_player.loc[player_id]
            residual = float(row["residual"])
            starter_residuals.append(residual)
            position_values.setdefault(str(row["position"]), []).append(residual)
            fold_projected += float(row["expected_points"])
            fold_realized += float(row["total_points"])
        captain_row = by_player.loc[captain_id]
        captain_residuals.append(float(captain_row["residual"]))
        fold_projected += float(captain_row["expected_points"])
        fold_realized += float(captain_row["total_points"])
        projected_scores.append(fold_projected)
        realized_scores.append(fold_realized)

    def _mean(values: list[float]) -> float:
        return sum(values) / len(values)

    starter_mean = _mean(starter_residuals)
    roster_mean = _mean(roster_residuals)
    return SelectionOptimismResult(
        fold_count=len(decisions),
        form_window=form_window,
        bench_weight=bench_weight,
        roster_mean_residual=roster_mean,
        starter_mean_residual=starter_mean,
        captain_mean_residual=_mean(captain_residuals),
        selection_gap_per_starter=starter_mean - roster_mean,
        mean_projected_xi_score=_mean(projected_scores),
        mean_realized_xi_score=_mean(realized_scores),
        rank_bucket_mean_residuals={
            name: _mean(values) for name, values in bucket_values.items() if values
        },
        position_starter_mean_residuals={
            position: _mean(values) for position, values in sorted(position_values.items())
        },
        diagnostics={
            "development_seasons": settings.development_seasons,
            "roster_observations": len(roster_residuals),
            "starter_observations": len(starter_residuals),
            "scoring_note": "captain contributes once here; doubling amplifies the "
            "gap in squad scores",
        },
    )
