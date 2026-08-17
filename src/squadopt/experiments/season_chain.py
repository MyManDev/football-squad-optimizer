"""Season-long decision chain: one squad carried from the first decision to the last.

The windowed rehearsal (`multi_gw_rehearsal`) measures a planning mechanism over a few
consecutive weeks from a fresh squad. Chips cannot be measured that way: a bench boost
is a once-per-season (or once-per-half) resource, and a window that hands the planner a
free chip every few weeks measures a resource the game does not offer. This module
walks a season the way a manager lives it — one squad, chosen at the first decision
gameweek and carried through every later one, with free transfers banked, hits paid,
prices moving, and each chip spent at most once inside its published window.

Every variant of the chain shares the same protocol; only the controls differ:

* ``lookahead`` — one is the myopic weekly baseline; more re-plans every week over the
  next ``lookahead`` decision gameweeks and applies the first week (the rolling planner).
* ``chip_windows`` — empty means no chips; otherwise each entry offers one play of one
  chip inside one gameweek range, and the planner decides when. Free hit is refused
  here as it is in the planner (`CHIP_NAMES_V1`).

Projection rule, candidate pool rule, and scoring are the rehearsal's (naive calendar
scaling, decision-time pools, starters plus the captain again, no automatic
substitutions), so a chain result is comparable with the windowed measurements. What
the chain adds is the state a season accumulates: the candidate pool is rebuilt every
week from that week's projection and always includes the squad the chain holds, and a
squad member is sold at the game's sell price — purchase price plus half of any rise,
rounded down to a tenth — rather than at the market price the windows use.

Measurement only: the chain never reads the locked holdout unless handed it, and the
runner that drives it refuses to.
"""

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from itertools import takewhile
from types import MappingProxyType
from typing import Final

import pandas as pd

from squadopt.backtest import realized_points_at
from squadopt.experiments.config import (
    ExperimentConfigurationError,
    ExperimentExecutionError,
)
from squadopt.experiments.multi_gw_rehearsal import (
    NAIVE_PROJECTION_RULE,
    PROJECTION_RULES,
    DecisionSeason,
    _relative_gap,
    realize_week,
)
from squadopt.features import CrossSeasonConfig
from squadopt.optimization import OptimizationConfig, optimize_squad
from squadopt.planning import (
    CHIP_NAMES_V1,
    ChipAvailability,
    InitialSquadState,
    PlanningHorizon,
    TransferPlanningConfig,
    optimize_transfer_plan,
    sell_price_tenths,
    to_planning_horizon,
)

SEASON_CHAIN_CONTRACT_VERSION: Final = "season_chain_v1"
CHIP_POLICIES: Final = ("planner", "double_gameweeks_only", "hybrid")


@dataclass(frozen=True, slots=True)
class ChipWindowRule:
    """One play of one chip, available in the closed gameweek range [start, stop]."""

    name: str
    start_gameweek: int
    stop_gameweek: int

    def __post_init__(self) -> None:
        if self.name not in CHIP_NAMES_V1:
            raise ExperimentConfigurationError(
                f"Unknown chip {self.name!r}; the chain models {CHIP_NAMES_V1!r}."
            )
        for name in ("start_gameweek", "stop_gameweek"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ExperimentConfigurationError(f"{name} must be a positive integer.")
        if self.stop_gameweek < self.start_gameweek:
            raise ExperimentConfigurationError("A chip window may not end before it starts.")

    def covers(self, gameweek: int) -> bool:
        return self.start_gameweek <= gameweek <= self.stop_gameweek


@dataclass(frozen=True, slots=True)
class SeasonChainConfig:
    """Frozen controls for one season-long chain."""

    season: str = "2024-25"
    lookahead: int = 1
    start_gameweek: int | None = None
    end_gameweek: int | None = None
    form_window: int = 5
    candidate_pool_per_position: int = 20
    cheap_pool_per_position: int = 8
    chip_windows: tuple[ChipWindowRule, ...] = ()
    chip_policy: str = "planner"
    """``planner``: every open chip is offered in every horizon week and the planner
    decides. ``double_gameweeks_only``: bench boost and triple captain are offered only
    in gameweeks where some team plays twice — the common human reservation rule — and
    the wildcard is offered as under ``planner``. ``hybrid``: only the bench boost is
    reserved for double gameweeks; triple captain and wildcard are offered as under
    ``planner`` (and held by their holding values when the transfer config sets them).
    A finite horizon cannot see that the season continues past its end, so under
    ``planner`` a chip worth anything now is worth playing now; the reservation rule is
    the cheapest stand-in for the option value the horizon cannot price."""
    sell_on_fee_halved: bool = True
    """Sell a squad member at purchase price plus half of any rise, rounded down to a
    tenth (the game's rule); False sells at the market price, as the windowed
    rehearsal does."""
    projection_rule: str = NAIVE_PROJECTION_RULE
    """``naive_calendar_scaling_v1`` scales the decision-time control projection by the
    known fixture count (a double counts twice); ``control_calendar_blind_v1`` is the
    control as evaluated, with no scaling — a double projects like a single."""
    hit_points_charged: float = 4.0
    """What the game charges per paid transfer on the realized sheet. The planner's
    own ``transfer_config.transfer_hit_cost_points`` is a decision control — a higher
    planning cost is a hit threshold — and may differ from what is charged."""
    cross_season_config: CrossSeasonConfig | None = None
    optimization_config: OptimizationConfig | None = None
    transfer_config: TransferPlanningConfig | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.season, str) or not self.season.strip():
            raise ExperimentConfigurationError("season must be a non-empty string.")
        object.__setattr__(self, "season", self.season.strip())
        for name, minimum in (
            ("lookahead", 1),
            ("form_window", 1),
            ("candidate_pool_per_position", 5),
            ("cheap_pool_per_position", 0),
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
                raise ExperimentConfigurationError(
                    f"{name} must be an integer of at least {minimum}."
                )
        for name in ("start_gameweek", "end_gameweek"):
            value = getattr(self, name)
            if value is not None and (
                isinstance(value, bool) or not isinstance(value, int) or value < 1
            ):
                raise ExperimentConfigurationError(f"{name} must be a positive integer or None.")
        if (
            self.start_gameweek is not None
            and self.end_gameweek is not None
            and self.end_gameweek < self.start_gameweek
        ):
            raise ExperimentConfigurationError("end_gameweek may not precede start_gameweek.")
        if not isinstance(self.sell_on_fee_halved, bool):
            raise ExperimentConfigurationError("sell_on_fee_halved must be a boolean.")
        charged = self.hit_points_charged
        if (
            isinstance(charged, bool)
            or not isinstance(charged, int | float)
            or not math.isfinite(float(charged))
            or float(charged) < 0.0
        ):
            raise ExperimentConfigurationError(
                "hit_points_charged must be a finite non-negative number."
            )
        object.__setattr__(self, "hit_points_charged", float(charged))
        if self.projection_rule not in PROJECTION_RULES:
            raise ExperimentConfigurationError(
                f"projection_rule must be one of {PROJECTION_RULES!r}."
            )
        if self.chip_policy not in CHIP_POLICIES:
            raise ExperimentConfigurationError(f"chip_policy must be one of {CHIP_POLICIES!r}.")
        windows = tuple(self.chip_windows)
        if any(not isinstance(window, ChipWindowRule) for window in windows):
            raise ExperimentConfigurationError("chip_windows must hold ChipWindowRule entries.")
        object.__setattr__(self, "chip_windows", windows)
        if self.cross_season_config is None:
            object.__setattr__(self, "cross_season_config", CrossSeasonConfig())
        if self.optimization_config is None:
            object.__setattr__(self, "optimization_config", OptimizationConfig())
        if self.transfer_config is None:
            object.__setattr__(self, "transfer_config", TransferPlanningConfig())

    @property
    def frozen_optimization_config(self) -> OptimizationConfig:
        assert self.optimization_config is not None
        return self.optimization_config

    @property
    def frozen_transfer_config(self) -> TransferPlanningConfig:
        assert self.transfer_config is not None
        return self.transfer_config

    @property
    def chips_enabled(self) -> bool:
        return bool(self.chip_windows)


@dataclass(frozen=True, slots=True)
class SeasonChainWeek:
    """One applied decision of the chain and what it realized."""

    gameweek: int
    realized_points: float
    transfer_hit_points: float
    transfer_count: int
    paid_transfer_count: int
    free_transfers_before: int
    free_transfers_after: int
    chip: str | None
    planned_chips: Mapping[int, str]
    """The horizon's chip plan at this decision (gameweek -> chip), of which only the
    first week's entry is applied; the rest shows what the planner meant to hold."""
    lookahead_gameweeks: int
    solver_status: str
    relative_gap: float | None
    projected_points: float
    captain_realized_points: float
    bench_realized_points: float
    bank_after_tenths: int
    squad_sell_value_tenths: int
    pool_size: int
    carried_blank_rows: int
    carried_unexplained_rows: int
    squad_player_ids: tuple[object, ...] = ()
    """The squad held after this decision, for provenance and for the next week."""

    def __post_init__(self) -> None:
        for name in ("realized_points", "transfer_hit_points", "projected_points"):
            if not math.isfinite(float(getattr(self, name))):
                raise ExperimentExecutionError(f"{name} must be finite.")
        if self.chip is not None and self.chip not in CHIP_NAMES_V1:
            raise ExperimentExecutionError(f"Unknown chip {self.chip!r} on a chain week.")
        object.__setattr__(self, "planned_chips", MappingProxyType(dict(self.planned_chips)))
        object.__setattr__(self, "squad_player_ids", tuple(self.squad_player_ids))

    @property
    def net_points(self) -> float:
        return self.realized_points - self.transfer_hit_points

    def as_record(self) -> dict[str, object]:
        return {
            "gameweek": self.gameweek,
            "realized_points": self.realized_points,
            "transfer_hit_points": self.transfer_hit_points,
            "net_points": self.net_points,
            "transfer_count": self.transfer_count,
            "paid_transfer_count": self.paid_transfer_count,
            "free_transfers_before": self.free_transfers_before,
            "free_transfers_after": self.free_transfers_after,
            "chip": self.chip,
            "planned_chips": {str(week): name for week, name in sorted(self.planned_chips.items())},
            "lookahead_gameweeks": self.lookahead_gameweeks,
            "solver_status": self.solver_status,
            "relative_gap": self.relative_gap,
            "projected_points": self.projected_points,
            "captain_realized_points": self.captain_realized_points,
            "bench_realized_points": self.bench_realized_points,
            "bank_after_tenths": self.bank_after_tenths,
            "squad_sell_value_tenths": self.squad_sell_value_tenths,
            "pool_size": self.pool_size,
            "carried_blank_rows": self.carried_blank_rows,
            "carried_unexplained_rows": self.carried_unexplained_rows,
            "squad_player_ids": [str(player) for player in self.squad_player_ids],
        }


@dataclass(frozen=True, slots=True)
class SeasonChainResult:
    """Every applied decision of one chain, in gameweek order, and its totals."""

    season: str
    lookahead: int
    chips_enabled: bool
    weeks: tuple[SeasonChainWeek, ...]
    opening_squad_ids: tuple[object, ...]
    diagnostics: Mapping[str, object] = field(default_factory=dict)
    contract_version: str = SEASON_CHAIN_CONTRACT_VERSION

    def __post_init__(self) -> None:
        if self.contract_version != SEASON_CHAIN_CONTRACT_VERSION:
            raise ExperimentExecutionError("Unsupported season chain contract_version.")
        if not self.weeks:
            raise ExperimentExecutionError("A chain must hold at least one decision.")
        gameweeks = [week.gameweek for week in self.weeks]
        if gameweeks != sorted(set(gameweeks)):
            raise ExperimentExecutionError("Chain weeks must be distinct and in gameweek order.")
        object.__setattr__(self, "weeks", tuple(self.weeks))
        object.__setattr__(self, "opening_squad_ids", tuple(self.opening_squad_ids))
        object.__setattr__(self, "diagnostics", MappingProxyType(dict(self.diagnostics)))

    @property
    def gameweeks(self) -> tuple[int, ...]:
        return tuple(week.gameweek for week in self.weeks)

    @property
    def realized_points(self) -> float:
        return sum(week.realized_points for week in self.weeks)

    @property
    def transfer_hit_points(self) -> float:
        return sum(week.transfer_hit_points for week in self.weeks)

    @property
    def net_points(self) -> float:
        return self.realized_points - self.transfer_hit_points

    @property
    def transfer_count(self) -> int:
        return sum(week.transfer_count for week in self.weeks)

    @property
    def chips_played(self) -> dict[int, str]:
        return {week.gameweek: week.chip for week in self.weeks if week.chip is not None}

    @property
    def chip_realized_gains(self) -> dict[str, float]:
        """What each played chip was worth on the realized sheet.

        Bench boost: the bench's realized points that week. Triple captain: the
        captain's realized points once more. Wildcard: the hit points the week's
        transfers would have cost without it (transfers beyond the banked free ones at
        the configured hit cost) — the diagnostics carry the hit cost used.
        """

        gains: dict[str, float] = {}
        hit_cost = float(str(self.diagnostics.get("hit_points_charged", 4.0)))
        for week in self.weeks:
            if week.chip == "bboost":
                gains["bboost"] = gains.get("bboost", 0.0) + week.bench_realized_points
            elif week.chip == "3xc":
                gains["3xc"] = gains.get("3xc", 0.0) + week.captain_realized_points
            elif week.chip == "wildcard":
                avoided = max(0, week.transfer_count - week.free_transfers_before) * hit_cost
                gains["wildcard"] = gains.get("wildcard", 0.0) + avoided
        return gains

    @property
    def proven_share(self) -> float:
        return sum(1 for week in self.weeks if week.solver_status == "OPTIMAL") / len(self.weeks)


def _sell_on_fee(halved: bool) -> float:
    return 0.5 if halved else 0.0


@dataclass(frozen=True, slots=True)
class _ChainState:
    squad_ids: tuple[object, ...]
    bank_tenths: int
    free_transfers: int
    purchase_prices: Mapping[object, int]
    used_chips: frozenset[tuple[str, int]]
    """(chip name, chip-window index) pairs already spent."""


class SeasonChain(DecisionSeason):
    """Walk one season with one squad, deciding at every decision gameweek."""

    def __init__(
        self,
        panel: pd.DataFrame,
        fixture_counts: pd.DataFrame,
        config: SeasonChainConfig | None = None,
    ) -> None:
        settings = SeasonChainConfig() if config is None else config
        if not isinstance(settings, SeasonChainConfig):
            raise ExperimentExecutionError("config must be a SeasonChainConfig.")
        super().__init__(
            panel,
            fixture_counts,
            season=settings.season,
            form_window=settings.form_window,
            candidate_pool_per_position=settings.candidate_pool_per_position,
            cheap_pool_per_position=settings.cheap_pool_per_position,
            cross_season_config=settings.cross_season_config,
            projection_rule=settings.projection_rule,
        )
        self._settings = settings
        # Last projection row seen for each squad member, so a member without a row
        # this week (a blank, or a hole) still has an identity, a team, and a price.
        self._last_rows: dict[object, dict[str, object]] = {}

    @property
    def chain_gameweeks(self) -> tuple[int, ...]:
        """The decision gameweeks the chain walks, in order."""

        available = self.available_gameweeks
        start = self._settings.start_gameweek
        end = self._settings.end_gameweek
        chosen = tuple(
            gameweek
            for gameweek in available
            if (start is None or gameweek >= start) and (end is None or gameweek <= end)
        )
        if not chosen:
            raise ExperimentExecutionError(
                f"No decision gameweek of {self._season} lies in the requested range."
            )
        return chosen

    def run(self) -> SeasonChainResult:
        """Decide every chain gameweek in turn and return the realized record."""

        settings = self._settings
        gameweeks = self.chain_gameweeks
        first = gameweeks[0]
        opening_pool = self._candidate_pool(self._projection_at(first))
        opening = optimize_squad(opening_pool, settings.frozen_optimization_config)
        opening_cost = opening.total_cost_tenths
        if not opening.has_solution or opening_cost is None:
            raise ExperimentExecutionError(
                "The opening squad could not be selected from the candidate pool."
            )
        squad_ids = tuple(opening.selected_squad["player_id"].tolist())
        prices = dict(
            zip(
                opening_pool["player_id"].tolist(),
                (int(value) for value in opening_pool["price_tenths"].tolist()),
                strict=True,
            )
        )
        opening_bank = settings.frozen_optimization_config.budget_tenths - int(opening_cost)
        state = _ChainState(
            squad_ids=squad_ids,
            bank_tenths=opening_bank,
            free_transfers=1,
            purchase_prices=MappingProxyType({player: prices[player] for player in squad_ids}),
            used_chips=frozenset(),
        )
        self._remember_rows(opening_pool, squad_ids)

        weeks: list[SeasonChainWeek] = []
        available = self.available_gameweeks
        for gameweek in gameweeks:
            horizon_gameweeks = tuple(
                takewhile(
                    lambda candidate: candidate in available,
                    range(gameweek, gameweek + settings.lookahead),
                )
            )
            week, state = self._decide(gameweek, horizon_gameweeks, state)
            weeks.append(week)

        transfer_config = settings.frozen_transfer_config
        return SeasonChainResult(
            season=settings.season,
            lookahead=settings.lookahead,
            chips_enabled=settings.chips_enabled,
            weeks=tuple(weeks),
            opening_squad_ids=squad_ids,
            diagnostics={
                "projection_rule": settings.projection_rule,
                "form_window": settings.form_window,
                "candidate_pool_per_position": settings.candidate_pool_per_position,
                "cheap_pool_per_position": settings.cheap_pool_per_position,
                "sell_on_fee_halved": settings.sell_on_fee_halved,
                "chip_policy": settings.chip_policy,
                "chip_windows": [
                    {
                        "name": window.name,
                        "start_gameweek": window.start_gameweek,
                        "stop_gameweek": window.stop_gameweek,
                    }
                    for window in settings.chip_windows
                ],
                "hit_points_charged": settings.hit_points_charged,
                "planning_hit_cost_points": transfer_config.transfer_hit_cost_points,
                "max_transfers_per_gameweek": transfer_config.max_transfers_per_gameweek,
                "banked_transfer_value_points": transfer_config.banked_transfer_value_points,
                "max_free_transfers": transfer_config.max_free_transfers,
                "wildcard_preserves_free_transfers": (
                    transfer_config.wildcard_preserves_free_transfers
                ),
                "opening_bank_tenths": opening_bank,
                "final_state": {
                    "bank_tenths": state.bank_tenths,
                    "free_transfers": state.free_transfers,
                    "used_chips": sorted(f"{name}@{index}" for name, index in state.used_chips),
                },
            },
        )

    # -- one decision -----------------------------------------------------------------

    def _remember_rows(self, table: pd.DataFrame, squad_ids: tuple[object, ...]) -> None:
        columns = ["player_id", "name", "team_id", "position", "price_tenths"]
        rows = table.loc[table["player_id"].isin(set(squad_ids)), columns]
        for record in rows.to_dict("records"):
            self._last_rows[record["player_id"]] = {
                str(key): value for key, value in record.items()
            }

    def _week_pool(
        self, gameweek: int, state: _ChainState
    ) -> tuple[pd.DataFrame, frozenset[object], int, int]:
        """This week's candidate pool plus the squad, rows carried where absent.

        Returns the pool, the set of squad members carried without a fresh row (they
        score zero and project zero), and how many of those are blanks versus holes.
        """

        projections = self._projection_at(gameweek)
        pool = self._candidate_pool(projections)
        squad = set(state.squad_ids)
        fresh_squad = projections.loc[projections["player_id"].isin(squad)]
        carried_ids = squad - set(fresh_squad["player_id"].tolist())
        pool = pd.concat(
            [pool, fresh_squad.loc[~fresh_squad["player_id"].isin(set(pool["player_id"]))]],
            ignore_index=True,
        )
        blank = 0
        holes = 0
        carried_rows: list[dict[str, object]] = []
        for player in sorted(carried_ids, key=str):
            last = self._last_rows.get(player)
            if last is None:
                raise ExperimentExecutionError(
                    f"Squad member {player!r} has no projection at gameweek {gameweek} and "
                    "no remembered row to carry."
                )
            row = dict(last)
            row["expected_points"] = 0.0
            carried_rows.append(row)
            if self._fixture_counts.get((gameweek, row["team_id"]), 0) == 0:
                blank += 1
            else:
                holes += 1
        if carried_rows:
            carried = pd.DataFrame(carried_rows, columns=list(pool.columns))
            pool = pd.concat([pool, carried.astype(pool.dtypes.to_dict())], ignore_index=True)
        pool = (
            pool.drop_duplicates(subset="player_id")
            .sort_values("player_id", kind="stable")
            .reset_index(drop=True)
        )
        return pool, frozenset(carried_ids), blank, holes

    def _planning_horizon(
        self,
        pool: pd.DataFrame,
        horizon_gameweeks: tuple[int, ...],
        state: _ChainState,
    ) -> PlanningHorizon:
        planning = to_planning_horizon(self._naive_horizon(pool, horizon_gameweeks))
        table = planning.table.copy(deep=True)
        if self._settings.sell_on_fee_halved:
            purchase = state.purchase_prices
            sell = [
                sell_price_tenths(int(current), purchase[player], sell_on_fee=0.5)
                if player in purchase
                else int(current)
                for player, current in zip(
                    table["player_id"].tolist(), table["buy_price_tenths"].tolist(), strict=True
                )
            ]
            table["sell_price_tenths"] = pd.Series(sell, index=table.index, dtype="int64")
        return PlanningHorizon(table)

    def _chip_availability(
        self, horizon_gameweeks: tuple[int, ...], state: _ChainState
    ) -> ChipAvailability | None:
        if not self._settings.chips_enabled:
            return None
        available: dict[str, set[int]] = {}
        policy = self._settings.chip_policy
        reserved = (
            {"bboost", "3xc"}
            if policy == "double_gameweeks_only"
            else {"bboost"}
            if policy == "hybrid"
            else set()
        )
        for index, window in enumerate(self._settings.chip_windows):
            if (window.name, index) in state.used_chips:
                continue
            weeks = {gameweek for gameweek in horizon_gameweeks if window.covers(gameweek)}
            if window.name in reserved:
                weeks = {gameweek for gameweek in weeks if self._is_double_gameweek(gameweek)}
            if weeks:
                available.setdefault(window.name, set()).update(weeks)
        return ChipAvailability(
            available={name: frozenset(weeks) for name, weeks in available.items()}
        )

    def _is_double_gameweek(self, gameweek: int) -> bool:
        """True when some team has more than one fixture in ``gameweek``."""

        return any(
            count >= 2 for (week, _), count in self._fixture_counts.items() if week == gameweek
        )

    def _spend_chip(
        self, chip: str, gameweek: int, state: _ChainState
    ) -> frozenset[tuple[str, int]]:
        for index, window in enumerate(self._settings.chip_windows):
            if (
                window.name == chip
                and window.covers(gameweek)
                and (chip, index) not in state.used_chips
            ):
                return state.used_chips | {(chip, index)}
        raise ExperimentExecutionError(
            f"The planner played {chip!r} at gameweek {gameweek} outside any open window."
        )

    def _decide(
        self,
        gameweek: int,
        horizon_gameweeks: tuple[int, ...],
        state: _ChainState,
    ) -> tuple[SeasonChainWeek, _ChainState]:
        settings = self._settings
        pool, carried_ids, blank, holes = self._week_pool(gameweek, state)
        horizon = self._planning_horizon(pool, horizon_gameweeks, state)
        chips = self._chip_availability(horizon_gameweeks, state)
        plan = optimize_transfer_plan(
            horizon,
            InitialSquadState(
                state.squad_ids,
                bank_tenths=state.bank_tenths,
                free_transfers=state.free_transfers,
            ),
            settings.frozen_optimization_config,
            settings.frozen_transfer_config,
            chips=chips,
        )
        if not plan.has_solution:
            raise ExperimentExecutionError(
                f"The chain (lookahead {settings.lookahead}) found no feasible decision at "
                f"gameweek {gameweek}."
            )
        week = plan.weeks[0]
        realized = realized_points_at(self._visible_panel, self._decisions[gameweek])
        realization = realize_week(week, realized, carried_ids)

        # Carry the state: squad, bank, free transfers, purchase prices, spent chips.
        new_squad = tuple(week.selected_squad["player_id"].tolist())
        purchase = dict(state.purchase_prices)
        for player in week.transfers_out["player_id"].tolist():
            purchase.pop(player, None)
        buy_prices = dict(
            zip(
                pool["player_id"].tolist(),
                (int(value) for value in pool["price_tenths"].tolist()),
                strict=True,
            )
        )
        for player in week.transfers_in["player_id"].tolist():
            purchase[player] = buy_prices[player]
        used = state.used_chips
        if week.chip is not None:
            used = self._spend_chip(week.chip, gameweek, state)
        new_state = _ChainState(
            squad_ids=new_squad,
            bank_tenths=int(week.bank_after_tenths),
            free_transfers=int(week.free_transfers_for_next_gameweek),
            purchase_prices=MappingProxyType({player: purchase[player] for player in new_squad}),
            used_chips=used,
        )
        self._remember_rows(pool, new_squad)
        sell_value = sum(
            sell_price_tenths(
                buy_prices[player],
                purchase[player],
                sell_on_fee=_sell_on_fee(settings.sell_on_fee_halved),
            )
            for player in new_squad
        )
        record = SeasonChainWeek(
            gameweek=gameweek,
            realized_points=realization.total(week.chip),
            transfer_hit_points=int(week.paid_transfer_count) * settings.hit_points_charged,
            transfer_count=int(week.transfer_count),
            paid_transfer_count=int(week.paid_transfer_count),
            free_transfers_before=int(week.free_transfers_before),
            free_transfers_after=int(week.free_transfers_for_next_gameweek),
            chip=week.chip,
            planned_chips=dict(plan.chips_played),
            lookahead_gameweeks=len(horizon_gameweeks),
            solver_status=plan.solver_status.value,
            relative_gap=_relative_gap(plan.diagnostics),
            projected_points=float(week.projected_score),
            captain_realized_points=realization.captain_points,
            bench_realized_points=realization.bench_points,
            bank_after_tenths=int(week.bank_after_tenths),
            squad_sell_value_tenths=int(sell_value),
            pool_size=len(pool),
            carried_blank_rows=blank,
            carried_unexplained_rows=holes,
            squad_player_ids=new_squad,
        )
        return record, new_state
