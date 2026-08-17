"""The transfer decision for a mid-season deadline: from the held squad, not from scratch.

An opening recommendation builds a squad out of nothing. Every later deadline starts
from what the ledger says is held — the squad recorded last week, the bank, the free
transfers banked, the price each player was bought at, the chips already spent — and
decides transfers under the game's rules: a free transfer or a hit per extra move,
sales at the sell price (purchase plus half of any rise), the budget as a bank that may
not go negative, and at most one chip a week inside its published window.

The decision itself is the transfer planner with a one-week horizon: the weekly baseline
the measurements kept as the operational control. Chips are not chosen by the planner
here — the season-long chain showed a one-week horizon burns them at the first
opportunity — but played when the operator names one, inside its window, and refused
otherwise. That is the reservation rule as an operating procedure, and the ledger
records which chip was played so the season's second half knows what is left.
"""

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Final

import pandas as pd

from squadopt.data.errors import DataSourceError
from squadopt.live.errors import LedgerError
from squadopt.live.recommendation import Projection, RecommendationInputs
from squadopt.live.rules import SeasonRules, chip_availability_for
from squadopt.optimization import OptimizationConfig
from squadopt.planning import (
    CHIP_NAMES_V1,
    ChipAvailability,
    InitialSquadState,
    PlanningHorizon,
    TransferPlanningConfig,
    TransferPlanResult,
    optimize_transfer_plan,
    sell_price_tenths,
)

LEDGER_TRANSFERS_CONTRACT_VERSION: Final = "ledger_transfers_v1"
# Free transfers a manager holds for the second deadline: the game grants one after the
# opening gameweek regardless of what was done at it.
FREE_TRANSFERS_AFTER_OPENING: Final = 1


@dataclass(frozen=True, slots=True)
class HeldSquad:
    """What the ledger says is held going into a deadline."""

    season: str
    decided_gameweek: int
    squad_player_ids: tuple[int, ...]
    purchase_prices: Mapping[int, int]
    bank_tenths: int
    free_transfers: int
    chips_used: Mapping[str, tuple[int, ...]]

    def __post_init__(self) -> None:
        squad = tuple(int(value) for value in self.squad_player_ids)
        if len(set(squad)) != len(squad) or not squad:
            raise LedgerError("A held squad must be a non-empty set of distinct players.")
        prices = {int(player): int(price) for player, price in dict(self.purchase_prices).items()}
        missing = sorted(set(squad) - set(prices))
        if missing:
            raise LedgerError(f"Held players without a purchase price: {missing[:5]!r}.")
        if self.bank_tenths < 0:
            raise LedgerError("A held bank may not be negative.")
        if self.free_transfers < 0:
            raise LedgerError("Held free transfers may not be negative.")
        object.__setattr__(self, "squad_player_ids", squad)
        object.__setattr__(
            self, "purchase_prices", MappingProxyType({player: prices[player] for player in squad})
        )
        object.__setattr__(
            self,
            "chips_used",
            MappingProxyType(
                {
                    str(name): tuple(int(week) for week in weeks)
                    for name, weeks in dict(self.chips_used).items()
                }
            ),
        )


@dataclass(frozen=True, slots=True)
class TransferDecision:
    """The transfer part of a mid-season recommendation, ready for the ledger."""

    previous_gameweek: int
    transfers_in: pd.DataFrame
    transfers_out: pd.DataFrame
    transfer_count: int
    paid_transfer_count: int
    transfer_hit_points: float
    free_transfers_before: int
    free_transfers_after: int
    bank_before_tenths: int
    bank_after_tenths: int
    purchase_prices_after: Mapping[int, int]
    sell_prices: Mapping[int, int]
    squad_sell_value_tenths: int
    chip: str | None
    chips_available: tuple[str, ...]
    planner_solver_status: str
    planner_contract_version: str
    transfer_config_fingerprint: str
    max_free_transfers: int
    transfer_hit_cost_points: float
    sell_on_fee: float
    diagnostics: Mapping[str, object] = field(default_factory=dict)
    contract_version: str = LEDGER_TRANSFERS_CONTRACT_VERSION

    def __post_init__(self) -> None:
        if self.chip is not None and self.chip not in CHIP_NAMES_V1:
            raise DataSourceError(f"Unknown chip {self.chip!r} on a transfer decision.")
        if not math.isfinite(float(self.transfer_hit_points)) or self.transfer_hit_points < 0:
            raise DataSourceError("transfer_hit_points must be finite and non-negative.")
        object.__setattr__(
            self,
            "purchase_prices_after",
            MappingProxyType({int(k): int(v) for k, v in dict(self.purchase_prices_after).items()}),
        )
        object.__setattr__(
            self,
            "sell_prices",
            MappingProxyType({int(k): int(v) for k, v in dict(self.sell_prices).items()}),
        )
        object.__setattr__(self, "diagnostics", MappingProxyType(dict(self.diagnostics)))

    @property
    def transfers_in_ids(self) -> tuple[int, ...]:
        return tuple(int(value) for value in self.transfers_in["player_id"].tolist())

    @property
    def transfers_out_ids(self) -> tuple[int, ...]:
        return tuple(int(value) for value in self.transfers_out["player_id"].tolist())

    def as_record(self) -> dict[str, object]:
        """The block the ledger freezes with the decision."""

        return {
            "contract_version": self.contract_version,
            "previous_gameweek": self.previous_gameweek,
            "transfers_in": list(self.transfers_in_ids),
            "transfers_out": list(self.transfers_out_ids),
            "transfer_count": self.transfer_count,
            "paid_transfer_count": self.paid_transfer_count,
            "transfer_hit_points": float(self.transfer_hit_points),
            "free_transfers_before": self.free_transfers_before,
            "free_transfers_after": self.free_transfers_after,
            "bank_before_tenths": self.bank_before_tenths,
            "bank_after_tenths": self.bank_after_tenths,
            "purchase_prices": {
                str(player): price for player, price in sorted(self.purchase_prices_after.items())
            },
            "sell_prices": {
                str(player): price for player, price in sorted(self.sell_prices.items())
            },
            "squad_sell_value_tenths": self.squad_sell_value_tenths,
            "chip": self.chip,
            "chips_available": list(self.chips_available),
            "planner_solver_status": self.planner_solver_status,
            "planner_contract_version": self.planner_contract_version,
            "transfer_config_fingerprint": self.transfer_config_fingerprint,
            "max_free_transfers": self.max_free_transfers,
            "transfer_hit_cost_points": float(self.transfer_hit_cost_points),
            "sell_on_fee": float(self.sell_on_fee),
        }


def _transfer_config(rules: SeasonRules) -> TransferPlanningConfig:
    return TransferPlanningConfig(max_free_transfers=rules.transfers.max_free_transfers)


def _chip_availability(
    rules: SeasonRules, gameweek: int, held: HeldSquad, chip: str | None
) -> ChipAvailability | None:
    """Offer exactly the named chip, forced, when its window is open and it is unspent.

    ``chip_availability_for`` applies the published windows and drops chips already
    played inside one; a forced chip that is not available there is refused by the
    availability contract itself, which is the refusal wanted here.
    """

    if chip is None:
        return None
    if chip not in CHIP_NAMES_V1:
        raise DataSourceError(
            f"Chip {chip!r} is not one the live path can play; it plays {CHIP_NAMES_V1!r}."
        )
    offered = chip_availability_for(rules, (gameweek,), used=held.chips_used)
    if gameweek not in offered.gameweeks_for(chip):
        raise DataSourceError(
            f"Chip {chip!r} cannot be played in gameweek {gameweek}: its window is not "
            "open there or it was already played inside this window."
        )
    return ChipAvailability(available={chip: frozenset({gameweek})}, forced={gameweek: chip})


def plan_transfers(
    inputs: RecommendationInputs,
    projection: Projection,
    held: HeldSquad,
    rules: SeasonRules,
    *,
    optimization: OptimizationConfig | None = None,
    chip: str | None = None,
) -> tuple[TransferPlanResult, TransferDecision, TransferPlanningConfig]:
    """Decide this deadline's transfers from the held squad with a one-week horizon."""

    settings = OptimizationConfig() if optimization is None else optimization
    gameweek = int(inputs.deadline.gameweek)
    if held.season != inputs.season:
        raise DataSourceError("The held squad belongs to another season.")
    if held.decided_gameweek != gameweek - 1:
        raise DataSourceError(
            f"The held squad was decided for GW{held.decided_gameweek}; this deadline is "
            f"GW{gameweek}."
        )
    table = projection.table.loc[
        :, ["player_id", "name", "team_id", "position", "price_tenths", "expected_points"]
    ].copy(deep=True)
    roster = {int(value) for value in table["player_id"].tolist()}
    departed = sorted(set(held.squad_player_ids) - roster)
    if departed:
        raise DataSourceError(
            f"Held players {departed[:5]!r} are not on the captured roster; the game has "
            "removed them and the squad must be resolved by hand before deciding."
        )
    fee = float(rules.transfers.sell_on_fee)
    current = dict(
        zip(
            (int(value) for value in table["player_id"].tolist()),
            (int(value) for value in table["price_tenths"].tolist()),
            strict=True,
        )
    )
    sell_prices = {
        player: sell_price_tenths(current[player], held.purchase_prices[player], sell_on_fee=fee)
        for player in held.squad_player_ids
    }
    horizon_table = pd.DataFrame(
        {
            "gameweek": gameweek,
            "player_id": table["player_id"].astype("int64"),
            "name": table["name"],
            "team_id": table["team_id"],
            "position": table["position"],
            "buy_price_tenths": table["price_tenths"].astype("int64"),
            "sell_price_tenths": [
                sell_prices.get(int(player), int(price))
                for player, price in zip(
                    table["player_id"].tolist(), table["price_tenths"].tolist(), strict=True
                )
            ],
            "expected_points": table["expected_points"].astype("float64"),
        }
    )
    transfer_config = _transfer_config(rules)
    state = InitialSquadState(
        held.squad_player_ids,
        bank_tenths=held.bank_tenths,
        free_transfers=min(held.free_transfers, transfer_config.max_free_transfers),
    )
    availability = _chip_availability(rules, gameweek, held, chip)
    plan = optimize_transfer_plan(
        PlanningHorizon(horizon_table),
        state,
        settings,
        transfer_config,
        chips=availability,
    )
    if not plan.has_solution or not plan.weeks:
        raise DataSourceError(
            f"The transfer planner returned {plan.solver_status.name} with no plan for "
            f"{inputs.season} gameweek {gameweek}."
        )
    week = plan.weeks[0]
    new_squad = tuple(int(value) for value in week.selected_squad["player_id"].tolist())
    purchase = dict(held.purchase_prices)
    for player in week.transfers_out["player_id"].tolist():
        purchase.pop(int(player), None)
    for player in week.transfers_in["player_id"].tolist():
        purchase[int(player)] = current[int(player)]
    purchase_after = {player: purchase[player] for player in new_squad}
    sell_value = sum(
        sell_price_tenths(current[player], purchase_after[player], sell_on_fee=fee)
        for player in new_squad
    )
    decision = TransferDecision(
        previous_gameweek=held.decided_gameweek,
        transfers_in=week.transfers_in,
        transfers_out=week.transfers_out,
        transfer_count=int(week.transfer_count),
        paid_transfer_count=int(week.paid_transfer_count),
        transfer_hit_points=float(week.transfer_hit_points),
        free_transfers_before=int(week.free_transfers_before),
        free_transfers_after=int(week.free_transfers_for_next_gameweek),
        bank_before_tenths=int(week.bank_before_tenths),
        bank_after_tenths=int(week.bank_after_tenths),
        purchase_prices_after=purchase_after,
        sell_prices=sell_prices,
        squad_sell_value_tenths=int(sell_value),
        chip=week.chip,
        chips_available=tuple(sorted(availability.available)) if availability else (),
        planner_solver_status=plan.solver_status.name,
        planner_contract_version=plan.contract_version,
        transfer_config_fingerprint=transfer_config.configuration_fingerprint,
        max_free_transfers=transfer_config.max_free_transfers,
        transfer_hit_cost_points=transfer_config.transfer_hit_cost_points,
        sell_on_fee=fee,
        diagnostics={
            "held_squad_decided_gameweek": held.decided_gameweek,
            "held_bank_tenths": held.bank_tenths,
            "held_free_transfers": held.free_transfers,
            "held_squad_sell_value_tenths": sum(sell_prices.values()),
            "chips_used_before": {name: list(weeks) for name, weeks in held.chips_used.items()},
            "planner_relative_gap": plan.diagnostics.get("relative_optimality_gap"),
        },
    )
    return plan, decision, transfer_config
