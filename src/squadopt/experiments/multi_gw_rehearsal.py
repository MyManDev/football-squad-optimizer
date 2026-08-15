"""Multi-gameweek planning rehearsal against a myopic weekly baseline.

The transfer planner and the `ProjectionHorizon` contract exist, but no prediction-side
builder does yet. This rehearsal builds decision-time horizons from the real panel with
a deliberately naive projection rule and asks the question the planner's existence
poses: does planning several weeks ahead beat re-optimizing one week at a time?

Projection rule (`naive_calendar_scaling_v1`): every horizon gameweek reuses the
decision-time baseline projection, scaled by that team's known fixture count in the
target gameweek (blank -> zero points, double -> doubled). Fixture calendars are known
before the deadline, so the rule is leakage-safe; it is also crude on purpose - the
rehearsal measures the planning mechanism, not projection quality. Home fixture counts
are recorded as zero because the rehearsal grain does not model venue.

Fairness rule: both strategies decide over the same candidate pool and the same
starting squad, both chosen with decision-time information only. The myopic baseline
still holds a real informational edge - it re-projects each week from that week's own
features - so a planner win here is a conservative finding.
"""

import math
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final

import pandas as pd

from squadopt.backtest import (
    DecisionPoint,
    realized_points_at,
    season_ranks,
    walk_forward_decision_points,
)
from squadopt.experiments.config import (
    ExperimentConfigurationError,
    ExperimentExecutionError,
)
from squadopt.features import CrossSeasonConfig, build_feature_dataset
from squadopt.optimization import OptimizationConfig, optimize_squad
from squadopt.planning import (
    InitialSquadState,
    PlanningWeekResult,
    ProjectionHorizon,
    TransferPlanningConfig,
    TransferPlanResult,
    optimize_transfer_plan,
    to_planning_horizon,
)
from squadopt.prediction import (
    FEATURE_GENERATION_CONTRACT_VERSION,
    FormWindowMapping,
    build_projection_table,
)

MULTI_GW_REHEARSAL_CONTRACT_VERSION: Final = "multi_gw_rehearsal_v1"
NAIVE_PROJECTION_RULE: Final = "naive_calendar_scaling_v1"


@dataclass(frozen=True, slots=True)
class MultiGwRehearsalConfig:
    """Frozen controls for one rehearsal over sampled decision windows."""

    season: str = "2024-25"
    horizon_length: int = 3
    form_window: int = 5
    candidate_pool_per_position: int = 20
    cheap_pool_per_position: int = 8
    cross_season_config: CrossSeasonConfig | None = None
    optimization_config: OptimizationConfig | None = None
    transfer_config: TransferPlanningConfig | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.season, str) or not self.season.strip():
            raise ExperimentConfigurationError("season must be a non-empty string.")
        object.__setattr__(self, "season", self.season.strip())
        for name, minimum in (
            ("horizon_length", 2),
            ("form_window", 1),
            ("candidate_pool_per_position", 5),
            ("cheap_pool_per_position", 0),
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
                raise ExperimentConfigurationError(
                    f"{name} must be an integer of at least {minimum}."
                )
        if self.cross_season_config is None:
            object.__setattr__(self, "cross_season_config", CrossSeasonConfig())
        if self.optimization_config is None:
            object.__setattr__(self, "optimization_config", OptimizationConfig())
        if self.transfer_config is None:
            object.__setattr__(self, "transfer_config", TransferPlanningConfig())

    @property
    def frozen_optimization_config(self) -> OptimizationConfig:
        """Return the optimizer controls, never None after construction."""

        assert self.optimization_config is not None
        return self.optimization_config

    @property
    def frozen_transfer_config(self) -> TransferPlanningConfig:
        """Return the transfer-planning controls, never None after construction."""

        assert self.transfer_config is not None
        return self.transfer_config


@dataclass(frozen=True, slots=True)
class RehearsalWindowResult:
    """Realized outcomes of both strategies over one decision window."""

    season: str
    start_gameweek: int
    gameweeks: tuple[int, ...]
    planned_realized_points: float
    planned_transfer_hit_points: float
    myopic_realized_points: float
    myopic_transfer_hit_points: float
    candidate_pool_size: int
    horizon_fingerprint: str
    diagnostics: Mapping[str, object]

    def __post_init__(self) -> None:
        for name in (
            "planned_realized_points",
            "planned_transfer_hit_points",
            "myopic_realized_points",
            "myopic_transfer_hit_points",
        ):
            if not math.isfinite(float(getattr(self, name))):
                raise ExperimentExecutionError(f"{name} must be finite.")
        object.__setattr__(self, "diagnostics", MappingProxyType(dict(self.diagnostics)))

    @property
    def planned_net_points(self) -> float:
        """Return the planner's realized total after transfer hits."""

        return self.planned_realized_points - self.planned_transfer_hit_points

    @property
    def myopic_net_points(self) -> float:
        """Return the myopic baseline's realized total after transfer hits."""

        return self.myopic_realized_points - self.myopic_transfer_hit_points

    @property
    def planning_advantage_points(self) -> float:
        """Return planner-minus-myopic net realized points for the window."""

        return self.planned_net_points - self.myopic_net_points


def _score_week(week: PlanningWeekResult, realized: pd.DataFrame) -> float:
    points = {
        player_id: float(total)
        for player_id, total in zip(
            realized["player_id"].tolist(), realized["total_points"].tolist(), strict=True
        )
    }
    starters = list(week.starting_xi["player_id"])
    captain = week.captain["player_id"]
    missing = [player for player in [*starters, captain] if player not in points]
    if missing:
        raise ExperimentExecutionError(
            f"Realized points do not cover selected players: {missing[:5]!r}."
        )
    return sum(points[player] for player in starters) + points[captain]


class MultiGwRehearsal:
    """Run planner-versus-myopic comparisons on real decision windows."""

    def __init__(
        self,
        panel: pd.DataFrame,
        fixture_counts: pd.DataFrame,
        config: MultiGwRehearsalConfig | None = None,
    ) -> None:
        """``fixture_counts``: one row per (gameweek, team_id) with the known number
        of fixtures, using the panel's own team labels."""

        settings = MultiGwRehearsalConfig() if config is None else config
        if not isinstance(settings, MultiGwRehearsalConfig):
            raise ExperimentExecutionError("config must be a MultiGwRehearsalConfig.")
        if not isinstance(panel, pd.DataFrame):
            raise ExperimentExecutionError("panel must be a pandas DataFrame.")
        if not isinstance(fixture_counts, pd.DataFrame):
            raise ExperimentExecutionError("fixture_counts must be a pandas DataFrame.")
        missing = [
            column
            for column in ("gameweek", "team_id", "fixture_count")
            if column not in fixture_counts.columns
        ]
        if missing:
            raise ExperimentExecutionError(
                f"fixture_counts is missing required columns: {missing!r}."
            )
        ranks = season_ranks(panel)
        if settings.season not in ranks:
            raise ExperimentExecutionError(f"Season {settings.season!r} is absent from the panel.")
        keep = panel["season"].map(lambda season: ranks[str(season)] <= ranks[settings.season])
        self._settings = settings
        self._visible_panel = panel.loc[keep].copy(deep=True)
        self._fixture_counts = {
            (int(gameweek), team_id): int(count)
            for gameweek, team_id, count in zip(
                fixture_counts["gameweek"].tolist(),
                fixture_counts["team_id"].tolist(),
                fixture_counts["fixture_count"].tolist(),
                strict=True,
            )
        }
        self._decisions: dict[int, DecisionPoint] = {
            decision.gameweek: decision
            for decision in walk_forward_decision_points(
                self._visible_panel,
                seasons=(settings.season,),
                min_prior_gameweeks_in_season=1,
            )
        }
        mapping = FormWindowMapping(form_window=settings.form_window)
        self._mapping = mapping
        self._features = build_feature_dataset(
            self._visible_panel,
            config=mapping.feature_config,
            cross_season=settings.cross_season_config,
        )

    @property
    def available_gameweeks(self) -> tuple[int, ...]:
        """Return the season's decision gameweeks in chronological order."""

        return tuple(sorted(self._decisions))

    def _projection_at(self, gameweek: int) -> pd.DataFrame:
        if gameweek not in self._decisions:
            raise ExperimentExecutionError(
                f"Gameweek {gameweek} has no decision point in {self._settings.season}."
            )
        return build_projection_table(
            self._features,
            season=self._settings.season,
            gameweek=gameweek,
            config=self._mapping.projection_config,
        )

    def _candidate_pool(self, projections: pd.DataFrame) -> pd.DataFrame:
        pieces: list[pd.DataFrame] = []
        for _, group in projections.groupby("position", sort=True):
            top = group.nlargest(
                self._settings.candidate_pool_per_position, "expected_points", keep="first"
            )
            cheap = group.nsmallest(
                self._settings.cheap_pool_per_position, "price_tenths", keep="first"
            )
            pieces.append(pd.concat([top, cheap]).drop_duplicates(subset="player_id"))
        pool = pd.concat(pieces, ignore_index=True).drop_duplicates(subset="player_id")
        return pool.sort_values("player_id", kind="stable", ignore_index=True)

    def _naive_horizon(
        self,
        pool: pd.DataFrame,
        gameweeks: tuple[int, ...],
    ) -> ProjectionHorizon:
        rows: list[dict[str, object]] = []
        columns = ("player_id", "name", "team_id", "position", "price_tenths", "expected_points")
        for gameweek in gameweeks:
            for player_id, name, team_id, position, price, expected in zip(
                *(pool[column].tolist() for column in columns), strict=True
            ):
                count = self._fixture_counts.get((gameweek, team_id), 0)
                rows.append(
                    {
                        "gameweek": gameweek,
                        "player_id": player_id,
                        "name": name,
                        "team_id": team_id,
                        "position": position,
                        "price_tenths": int(price),
                        "expected_points": float(expected) * count,
                        "fixture_count": count,
                        "home_fixture_count": 0,
                    }
                )
        return ProjectionHorizon(
            pd.DataFrame(rows),
            season=self._settings.season,
            source_snapshot_id=f"panel@{self._settings.season}-gw{gameweeks[0]:02d}",
            model_name="deterministic_baseline",
            model_version=f"form_window_{self._settings.form_window:02d}_v1",
            feature_contract_version=FEATURE_GENERATION_CONTRACT_VERSION,
            post_processing_contract_version=NAIVE_PROJECTION_RULE,
        )

    def rehearse_window(self, start_gameweek: int) -> RehearsalWindowResult:
        """Compare the planner against the myopic baseline for one window."""

        settings = self._settings
        gameweeks = tuple(range(start_gameweek, start_gameweek + settings.horizon_length))
        for gameweek in gameweeks:
            if gameweek not in self._decisions:
                raise ExperimentExecutionError(
                    f"Window {gameweeks!r} leaves the season's decision points."
                )
        pool = self._candidate_pool(self._projection_at(start_gameweek))
        pool_ids = set(pool["player_id"].tolist())

        opening = optimize_squad(pool, settings.frozen_optimization_config)
        opening_cost = opening.total_cost_tenths
        if not opening.has_solution or opening_cost is None:
            raise ExperimentExecutionError(
                "The shared opening squad could not be selected from the candidate pool."
            )
        initial_state = InitialSquadState(
            tuple(opening.selected_squad["player_id"].tolist()),
            bank_tenths=(settings.frozen_optimization_config.budget_tenths - int(opening_cost)),
            free_transfers=1,
        )

        horizon = self._naive_horizon(pool, gameweeks)
        plan = optimize_transfer_plan(
            to_planning_horizon(horizon),
            initial_state,
            settings.frozen_optimization_config,
            settings.frozen_transfer_config,
        )
        if not plan.has_solution:
            raise ExperimentExecutionError(
                f"The planner found no feasible plan for window {gameweeks!r}."
            )
        planned_points, planned_hits = self._score_plan(plan, gameweeks)
        myopic_points, myopic_hits = self._score_myopic(pool_ids, initial_state, gameweeks)

        return RehearsalWindowResult(
            season=settings.season,
            start_gameweek=start_gameweek,
            gameweeks=gameweeks,
            planned_realized_points=planned_points,
            planned_transfer_hit_points=planned_hits,
            myopic_realized_points=myopic_points,
            myopic_transfer_hit_points=myopic_hits,
            candidate_pool_size=len(pool),
            horizon_fingerprint=horizon.horizon_fingerprint,
            diagnostics={
                "projection_rule": NAIVE_PROJECTION_RULE,
                "planner_transfers": [week.transfer_count for week in plan.weeks],
            },
        )

    def _score_plan(
        self,
        plan: TransferPlanResult,
        gameweeks: tuple[int, ...],
    ) -> tuple[float, float]:
        if len(plan.weeks) != len(gameweeks):
            raise ExperimentExecutionError("The plan does not cover the whole window.")
        total = 0.0
        hits = 0.0
        for week in plan.weeks:
            realized = realized_points_at(self._visible_panel, self._decisions[int(week.gameweek)])
            total += _score_week(week, realized)
            hits += float(week.transfer_hit_points)
        return total, hits

    def _score_myopic(
        self,
        pool_ids: set[object],
        initial_state: InitialSquadState,
        gameweeks: tuple[int, ...],
    ) -> tuple[float, float]:
        state = initial_state
        total = 0.0
        hits = 0.0
        for gameweek in gameweeks:
            projections = self._projection_at(gameweek)
            week_pool = (
                projections.loc[projections["player_id"].isin(pool_ids)]
                .sort_values("player_id", kind="stable")
                .reset_index(drop=True)
            )
            plan = optimize_transfer_plan(
                to_planning_horizon(self._naive_horizon(week_pool, (gameweek,))),
                state,
                self._settings.frozen_optimization_config,
                self._settings.frozen_transfer_config,
            )
            if not plan.has_solution:
                raise ExperimentExecutionError(
                    f"The myopic baseline found no feasible week at gameweek {gameweek}."
                )
            week = plan.weeks[0]
            realized = realized_points_at(self._visible_panel, self._decisions[gameweek])
            total += _score_week(week, realized)
            hits += float(week.transfer_hit_points)
            state = InitialSquadState(
                tuple(week.selected_squad["player_id"].tolist()),
                bank_tenths=int(week.bank_after_tenths),
                free_transfers=int(week.free_transfers_for_next_gameweek),
            )
        return total, hits
