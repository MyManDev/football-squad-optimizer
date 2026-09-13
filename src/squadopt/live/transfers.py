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
from typing import Final, TypedDict

import pandas as pd

from squadopt.data.errors import DataSourceError
from squadopt.live.errors import LedgerError
from squadopt.live.recommendation import Projection, RecommendationInputs
from squadopt.live.rules import TRANSFER_HIT_POINTS, SeasonRules, chip_availability_for
from squadopt.optimization import OptimizationConfig, SolverStatus
from squadopt.planning import (
    CHIP_NAMES,
    ChipAvailability,
    FirstWeekOverlap,
    InitialSquadState,
    PlanningHorizon,
    ProjectionHorizon,
    TransferPlanningConfig,
    TransferPlanResult,
    optimize_transfer_plan,
    sell_price_tenths,
    spending_power,
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
    squad_sell_value_tenths: int | None = None
    """What the whole squad would raise if sold, when the source states it, in tenths.

    None for our own squad, whose purchase prices are the ledger's own and whose sell
    prices are therefore the rule's exact answer, player by player. It is set for a squad
    read from the public entry endpoints, which publish no purchase price and so leave
    ``purchase_prices`` holding current prices: those overstate every risen player's sale
    by half his rise. The planner takes the difference back out of the budget rather than
    letting a plan spend it (``planning.pricing.spending_power``).
    """

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
        if self.squad_sell_value_tenths is not None and self.squad_sell_value_tenths < 0:
            raise LedgerError("A held squad's selling value may not be negative.")
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
        if self.chip is not None and self.chip not in CHIP_NAMES:
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


class _MemberPlanningPolicy(TypedDict):
    """The planner controls the member path fixes; the values are MEMBER_PLANNING_POLICY."""

    transfer_hit_cost_points: float
    hit_points_charged: float
    banked_transfer_value_points: float
    horizon_discount_factor: float
    chip_holding_value_points: Mapping[str, float]


MEMBER_PLANNING_POLICY_ID: Final = "member_planning_policy_v2"
_MEMBER_PLANNING_POLICY_VALUES: Final[_MemberPlanningPolicy] = {
    "transfer_hit_cost_points": 8.0,
    "hit_points_charged": float(TRANSFER_HIT_POINTS),
    "banked_transfer_value_points": 0.0,
    "horizon_discount_factor": 1.0,
    "chip_holding_value_points": MappingProxyType({}),
}
MEMBER_PLANNING_POLICY: Final[Mapping[str, object]] = MappingProxyType(
    _MEMBER_PLANNING_POLICY_VALUES
)
"""The member path's planning policy, ``member_planning_policy_v2``: the rule values.

Every mid-season member decision plans one week ahead under these five controls; the
rest of ``TransferPlanningConfig`` is the season's rules (the free-transfer cap, a
transfer cap when a caller sets one) and the planner's contract. A banked free transfer
is worth nothing past the week, a single week is not discounted, and no chip carries a
holding value because the member path offers no chip unless the operator names one
(``_chip_availability``), which leaves holding values inert here.

The two hit numbers are the policy's one departure from the dataclass defaults, and they
mean different things. ``hit_points_charged`` is 4.0, the points the game takes off the
sheet (``TRANSFER_HIT_POINTS`` in ``live/rules.py``, the one definition, which the
banking model that derives a member's free transfers checks recorded costs against),
and it is what every reported hit is counted at: the advice payload's
``transfer_hit_points`` (the week's charge, published once beside ``moves`` because it
belongs to the week and not to any one move), ``plan_weeks[].transfer_hit_points``,
``net_expected_points``, the decision the ledger records. ``transfer_hit_cost_points`` is
8.0 and lives only inside the solve, where it makes the planner decline a transfer whose
projected gain is marginal. It is a caution margin on a projection that overstates
transfer gains, not a rule change, and no member ever sees it.

The split also means two solved plans are not ranked the same way by the solve's objective
and by the charge. Every plan a member is *shown* is solved under the margin; the one
place that needs a plan solved at the charge is the rival price tag's anchor, which
compares two solved plans and would otherwise compare maximisers of different objectives
(``application/advice.py``). That is what ``plan_transfers``' ``transfer_hit_cost_points``
override exists for, and it is the only caller.

Because the two differ, ``configuration_fingerprint`` is no longer ``TransferPlanningConfig``'s
default one; the pins recorded under this policy are the ones this docstring's revisit
rule names.

Provenance — what each measurement said about moving them, in date order:

* ``docs/planner_doe.json`` (2026-08-15, #71): one factor at a time around the defaults
  on the windowed rehearsal; the hit cost moved the advantage only below 4, and the
  discount was dead. That removed both as search axes.
* ``docs/transfer_discipline.json`` (2026-08-17): planning hit cost {4, 6, 8} x transfer
  cap x banked-transfer value on the lookahead-1 season chain over the four development
  seasons, chips under the reservation rule. At the rule cell (no cap, banked value 0)
  hit cost 6 was -29 a season against 4 (weekly -0.79, 90% block bootstrap
  [-1.99, +0.25]) and hit cost 8 was -27 (weekly -0.73, [-1.96, +0.69]); the season
  signs disagree (2021-22 -236/-246, 2022-23 +69/+84, 2023-24 +30/+96,
  2024-25 +21/-41). A banked-transfer value was negative wherever its interval left
  zero. The note's reading: keep the rule for the weekly control.
* ``docs/chip_bayesopt.json`` (2026-08-18): the Bayesian search over chip holding
  values and the planning hit cost recommended hit cost 7 (with ``3xc=20,
  wildcard=24``): mean net 2053.8 against the hybrid reference 2035.0, ahead in all
  four seasons, most of it a smaller season spread rather than a mean shift. No
  promotion; the two follow-up searches agreed only on a hit cost of 7-8.
* ``docs/season_chain_tuned.json`` (2026-08-18): that candidate walked as the chain's
  ``tuned`` mode against ``hybrid``: +0.51 a week, 90% block bootstrap [-1.14, +2.13],
  positive-week share 0.43 -- the interval holds zero. The chips were the effect; the
  tuning was not.
* ``docs/member_policy_hit_cost_grid.json`` (2026-09-07): the hit cost measured where
  this policy lives -- {4, 5, 6, 7, 8} on the lookahead-1 chain with chips off, five
  seasons including 2025-26 as declared development data, 184 paired gameweeks. Against
  4: 5 is +1.24 a week [+0.34, +2.18], 6 is +1.08 [-0.13, +2.02], 7 is +2.11
  [+0.83, +3.44], 8 is +2.44 [+1.04, +3.94]; paid transfers fall from 193 to 37 across
  the five seasons. The rule declared before that run -- beat 4 in pooled mean, an
  interval clear of zero, worse in at most one season -- **fires for 5, 7 and 8**. The
  finding disagrees with ``transfer_discipline``, which reserved chips where this
  run turns them off, so it is a reading in the member path's own configuration rather
  than a reversal of that artifact on its terms.
* **The decision (2026-09-07, Ertugrul Soydal, owner):** act on that artifact and set
  the planning hit cost to 8.0, the best of the levels the rule passed. Mean season net
  1861 -> 1951 and season hit points 154 -> 30 across the five seasons; against 4 the
  paired weekly mean is +2.44 with a 90% season-aware block-bootstrap interval of
  [+1.04, +3.94]. What the game charges does not move: ``hit_points_charged`` stays 4.0
  and every number a member is shown, and every comparison between two solved plans, is
  counted at it. 8 is the top of the measured grid, so it sits on an edge rather than at
  an interior optimum; the next measurement should widen the range (4-12) before it is
  read as one.

Revisit rule. These values change only in a pull request that cites a measurement on
the lookahead-1 season chain with 2025-26 included as a season, and that re-pins the
site's pinned fixture under ``web/public/data`` in the same commit, because a changed
policy changes what every member is told. The reading is re-examined at gameweek 19 from
the live scorecard (``docs/weekly_scorecard.md``): the season's own hits and what they
returned are the evidence the development seasons cannot give.

What enforces that rule in the suite, and what does not. The values are pinned literally
in ``test_the_member_planning_policy_is_the_rule_and_its_provenance_exists``
(``tests/unit/test_live_transfers.py``), so a changed or accidentally reverted value fails
loudly there. That a changed value reaches what a member is *told* is
``test_the_member_planning_hit_cost_reaches_the_published_bytes``
(``tests/unit/test_league_views.py``), which publishes one discretionary member's advice
at ``transfer_hit_cost_points`` 4.0 and again at 8.0 and requires the bytes to differ.
``IN_SEASON_MEMBER_ADVICE_SHA256`` in that same file is the member path's *replay* gate --
it notices a changed planner, projection reading, payload or rendering -- but it is not a
gate on this policy and was cited as one until 2026-09-09: its world's held fifteen breaks
the game's three-per-club rule, so both of its transfers are forced repairs and the
published bytes were measured unchanged from a hit cost of 4.0 through 400.0.

A planning hit cost above 4 is a caution margin on projected gains, not a rule
change: the ledger and the settle step charge the game's 4 regardless.
"""


def _transfer_config(
    rules: SeasonRules,
    *,
    transfer_cap: int | None = None,
    transfer_hit_cost_points: float | None = None,
) -> TransferPlanningConfig:
    """The member planning policy under this season's rules.

    ``transfer_cap`` bounds the week's transfers (a wildcard week is exempt, as in the
    planner); ``None`` leaves the count to the objective and the policy's hit cost.
    ``transfer_hit_cost_points`` replaces the policy's caution margin inside the solve;
    ``None`` is the policy, which is what every published plan uses.
    """

    values = _MEMBER_PLANNING_POLICY_VALUES.copy()
    if transfer_hit_cost_points is not None:
        values["transfer_hit_cost_points"] = float(transfer_hit_cost_points)
    return TransferPlanningConfig(
        max_free_transfers=rules.transfers.max_free_transfers,
        max_transfers_per_gameweek=transfer_cap,
        **values,
    )


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
    if chip not in CHIP_NAMES:
        raise DataSourceError(
            f"Chip {chip!r} is not one the live path can play; it plays {CHIP_NAMES!r}."
        )
    offered = chip_availability_for(rules, (gameweek,), used=held.chips_used)
    if gameweek not in offered.gameweeks_for(chip):
        raise DataSourceError(
            f"Chip {chip!r} cannot be played in gameweek {gameweek}: its window is not "
            "open there or it was already played inside this window."
        )
    return ChipAvailability(available={chip: frozenset({gameweek})}, forced={gameweek: chip})


@dataclass(frozen=True, slots=True)
class _PreparedPlanning:
    """Everything a solve needs, built once so a menu of solves shares one setup."""

    horizon: PlanningHorizon
    state: InitialSquadState
    availability: ChipAvailability | None
    settings: OptimizationConfig
    transfer_config: TransferPlanningConfig
    sell_prices: Mapping[int, int]
    current: Mapping[int, int]
    fee: float
    gameweek: int


def _prepare_planning(
    inputs: RecommendationInputs,
    projection: Projection,
    held: HeldSquad,
    rules: SeasonRules,
    *,
    optimization: OptimizationConfig | None,
    chip: str | None,
    transfer_cap: int | None = None,
    transfer_hit_cost_points: float | None = None,
) -> _PreparedPlanning:
    """Validate the held squad against the capture and build the one-week horizon.

    ``transfer_cap`` bounds the week's transfers (a wildcard is exempt, as in the
    planner); ``None`` is the historical planner, which pays for any transfer the
    objective can justify. ``transfer_hit_cost_points`` overrides the policy's caution
    margin for this solve alone; ``None`` is the policy.
    """

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
    budget = spending_power(
        bank_tenths=held.bank_tenths,
        sell_prices_tenths={
            player: sell_price_tenths(
                current[player], held.purchase_prices[player], sell_on_fee=fee
            )
            for player in held.squad_player_ids
        },
        stated_squad_sell_value_tenths=held.squad_sell_value_tenths,
    )
    sell_prices = dict(budget.sell_prices_tenths)
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
    transfer_config = _transfer_config(
        rules,
        transfer_cap=None if transfer_cap is None else int(transfer_cap),
        transfer_hit_cost_points=transfer_hit_cost_points,
    )
    state = InitialSquadState(
        held.squad_player_ids,
        bank_tenths=budget.bank_tenths,
        free_transfers=min(held.free_transfers, transfer_config.max_free_transfers),
    )
    availability = _chip_availability(rules, gameweek, held, chip)
    return _PreparedPlanning(
        horizon=PlanningHorizon(horizon_table),
        state=state,
        availability=availability,
        settings=settings,
        transfer_config=transfer_config,
        sell_prices=sell_prices,
        current=current,
        fee=fee,
        gameweek=gameweek,
    )


def _package_decision(
    plan: TransferPlanResult,
    held: HeldSquad,
    availability: ChipAvailability | None,
    transfer_config: TransferPlanningConfig,
    sell_prices: Mapping[int, int],
    current: Mapping[int, int],
    fee: float,
) -> TransferDecision:
    """Turn the plan's opening week into the decision the ledger records."""

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
        # What the game charges, not what the planner priced a transfer at: this is the
        # per-hit rate the ledger records and the verifier multiplies the paid transfers
        # by. The planning cost is inside ``transfer_config_fingerprint`` above.
        transfer_hit_cost_points=transfer_config.hit_points_charged,
        sell_on_fee=fee,
        diagnostics={
            "held_squad_decided_gameweek": held.decided_gameweek,
            "held_bank_tenths": held.bank_tenths,
            "held_free_transfers": held.free_transfers,
            # What the planner was allowed to raise from the held fifteen, which is the
            # source's own aggregate whenever it stated one, not the sum of their current
            # prices.
            "held_squad_sell_value_tenths": sum(sell_prices.values()),
            "stated_squad_sell_value_tenths": held.squad_sell_value_tenths,
            "chips_used_before": {name: list(weeks) for name, weeks in held.chips_used.items()},
            "planner_relative_gap": plan.diagnostics.get("relative_optimality_gap"),
        },
    )
    return decision


def plan_transfer_menu(
    inputs: RecommendationInputs,
    projection: Projection,
    held: HeldSquad,
    rules: SeasonRules,
    *,
    optimization: OptimizationConfig | None = None,
    chip: str | None = None,
    plan_count: int = 5,
) -> tuple[tuple[TransferPlanResult, TransferDecision], ...]:
    """Up to ``plan_count`` proven plans for this deadline, best first.

    The planner returns one answer; a play mode needs alternatives to choose between, or
    every mode returns the same transfers under a different name. Each solve excludes the
    opening-week squads already produced, so entry *k* is the best plan that keeps none of
    the previous *k-1* squads intact — next-best in the objective's own terms, not a
    perturbation.

    The menu holds **proven** plans only. The first entry failing to prove optimality ends
    the menu rather than joining it: an unproven alternative is exactly the machine-load
    nondeterminism the live path refuses everywhere else, and a mode choosing from a menu
    with one arbitrary entry inherits that arbitrariness silently. A shorter menu is an
    honest one.

    The first plan must exist and be proven — the same requirement ``plan_transfers``
    enforces — because a menu with no safe default is not a decision surface.
    """

    if not isinstance(plan_count, int) or isinstance(plan_count, bool) or plan_count < 1:
        raise DataSourceError("plan_count must be a positive integer.")
    prepared = _prepare_planning(
        inputs, projection, held, rules, optimization=optimization, chip=chip
    )
    menu: list[tuple[TransferPlanResult, TransferDecision]] = []
    excluded: list[frozenset[object]] = []
    while len(menu) < plan_count:
        plan = optimize_transfer_plan(
            prepared.horizon,
            prepared.state,
            prepared.settings,
            prepared.transfer_config,
            chips=prepared.availability,
            excluded_squads=tuple(excluded),
        )
        if not plan.has_solution or not plan.weeks:
            break
        if plan.solver_status is not SolverStatus.OPTIMAL:
            break
        decision = _package_decision(
            plan,
            held,
            prepared.availability,
            prepared.transfer_config,
            prepared.sell_prices,
            prepared.current,
            prepared.fee,
        )
        menu.append((plan, decision))
        excluded.append(
            frozenset(int(value) for value in plan.weeks[0].selected_squad["player_id"].tolist())
        )
    if not menu:
        raise DataSourceError(
            f"The transfer planner produced no proven plan for {inputs.season} gameweek "
            f"{prepared.gameweek}."
        )
    return tuple(menu)


def plan_transfers(
    inputs: RecommendationInputs,
    projection: Projection,
    held: HeldSquad,
    rules: SeasonRules,
    *,
    optimization: OptimizationConfig | None = None,
    chip: str | None = None,
    transfer_hit_cost_points: float | None = None,
) -> tuple[TransferPlanResult, TransferDecision, TransferPlanningConfig]:
    """Decide this deadline's transfers from the held squad with a one-week horizon.

    ``transfer_hit_cost_points`` replaces ``MEMBER_PLANNING_POLICY``'s caution margin
    inside this solve. It defaults to ``None``, the policy, so every call site that does
    not name it is byte-identical to before; the one caller that does is the price tag's
    anchor in ``application/advice.py``, which needs a plan that maximises what the game
    actually charges rather than what the planner is cautious about.
    """

    prepared = _prepare_planning(
        inputs,
        projection,
        held,
        rules,
        optimization=optimization,
        chip=chip,
        transfer_hit_cost_points=transfer_hit_cost_points,
    )
    plan = optimize_transfer_plan(
        prepared.horizon,
        prepared.state,
        prepared.settings,
        prepared.transfer_config,
        chips=prepared.availability,
    )
    if not plan.has_solution or not plan.weeks:
        raise DataSourceError(
            f"The transfer planner returned {plan.solver_status.name} with no plan for "
            f"{inputs.season} gameweek {prepared.gameweek}."
        )
    decision = _package_decision(
        plan,
        held,
        prepared.availability,
        prepared.transfer_config,
        prepared.sell_prices,
        prepared.current,
        prepared.fee,
    )
    return plan, decision, prepared.transfer_config


def plan_transfers_with_overlap(
    inputs: RecommendationInputs,
    projection: Projection,
    held: HeldSquad,
    rules: SeasonRules,
    first_week_overlap: FirstWeekOverlap,
    *,
    optimization: OptimizationConfig | None = None,
    transfer_cap: int | None = None,
) -> tuple[TransferPlanResult, TransferDecision, TransferPlanningConfig]:
    """``plan_transfers`` under a first-week overlap band against a rival's eleven.

    Same preparation, same solver, same decision packaging — the only differences are
    the band handed to ``optimize_transfer_plan`` and, when given, a cap on the week's
    transfers (the free ones, so a band cannot buy itself with hits). Kept as its own
    entry point rather than a parameter on ``plan_transfers`` so the baseline call
    sites cannot change behavior by accident: the saf-puan path stays byte-identical
    by construction.

    As in ``plan_transfers``, an unproven plan is returned rather than raised on: a
    banded plan the solver found but could not prove is publishable **with its status**
    (the member-solver-status rule), and the caller decides. Only no solution at all,
    or a solution with no weeks, is an error. The contrast is with ``plan_menu``, which
    stops at the first non-OPTIMAL plan because a menu entry has to be proven before it
    can be offered.
    """

    prepared = _prepare_planning(
        inputs,
        projection,
        held,
        rules,
        optimization=optimization,
        chip=None,
        transfer_cap=transfer_cap,
    )
    plan = optimize_transfer_plan(
        prepared.horizon,
        prepared.state,
        prepared.settings,
        prepared.transfer_config,
        chips=prepared.availability,
        first_week_overlap=first_week_overlap,
    )
    if not plan.has_solution or not plan.weeks:
        raise DataSourceError(
            f"The banded transfer planner returned {plan.solver_status.name} with no plan "
            f"for {inputs.season} gameweek {prepared.gameweek}."
        )
    decision = _package_decision(
        plan,
        held,
        prepared.availability,
        prepared.transfer_config,
        prepared.sell_prices,
        prepared.current,
        prepared.fee,
    )
    return plan, decision, prepared.transfer_config


def plan_transfer_horizon(
    inputs: RecommendationInputs,
    projection_horizon: ProjectionHorizon,
    held: HeldSquad,
    rules: SeasonRules,
    *,
    optimization: OptimizationConfig | None = None,
    transfer_config: TransferPlanningConfig | None = None,
    chips: ChipAvailability | None = None,
    first_week_overlap: FirstWeekOverlap | None = None,
    first_week_transfer_cap: int | None = None,
) -> tuple[TransferPlanResult, TransferPlanningConfig]:
    """Plan several gameweeks from the held squad and one projection horizon.

    The first projected week must be the live decision deadline and every provenance
    boundary must name the same season and capture. Prices are frozen at the captured
    values across the horizon: the projection contract deliberately carries no price
    transition model, so accepting changing prices here would make later sale proceeds
    depend on an unversioned forecast.

    A one-week horizon reuses the uncapped operational transfer policy exactly. Longer
    horizons default to at most one transfer per gameweek. That is the measured rolling
    discipline in ``docs/transfer_discipline_note.md``: the uncapped rolling planner
    churned, while the cap removed the mechanism. Callers may provide another explicit
    policy, whose configuration fingerprint remains in the result.

    Chips are not offered unless the caller names them in ``chips``. A finite horizon
    values a chip inside the horizon only — its option value after the last week is
    unknown to the planner — so a caller who offers chips takes on stating that limit,
    as the member window path does; the system's own horizon path offers none.

    ``first_week_overlap`` and ``first_week_transfer_cap`` are handed straight to
    ``optimize_transfer_plan``: an overlap band against a rival's known players in the
    decided week, and a cap on every week after it. They go together — a rival-strategy
    band constrains the decided week, and the later weeks should not be charged for it —
    but each stands alone. Both default to ``None``, which is this function exactly as it
    was for every caller that does not name them.
    """

    if not isinstance(projection_horizon, ProjectionHorizon):
        raise DataSourceError("projection_horizon must be a ProjectionHorizon.")
    projection_horizon.assert_fingerprint()
    if not isinstance(held, HeldSquad):
        raise DataSourceError("held must be a HeldSquad.")
    first_gameweek = projection_horizon.target_gameweeks[0]
    for name, expected, actual in (
        ("season", inputs.season, projection_horizon.season),
        ("snapshot", inputs.snapshot_id, projection_horizon.source_snapshot_id),
        ("first gameweek", inputs.deadline.gameweek, first_gameweek),
        ("held season", inputs.season, held.season),
        ("rules season", inputs.season, rules.season),
        ("rules snapshot", inputs.snapshot_id, rules.source_snapshot_id),
    ):
        if expected != actual:
            raise DataSourceError(
                f"Transfer horizon {name} is {actual!r}; this decision requires {expected!r}."
            )
    if held.decided_gameweek != first_gameweek - 1:
        raise DataSourceError(
            f"The held squad was decided for GW{held.decided_gameweek}; this horizon "
            f"starts at GW{first_gameweek}."
        )

    table = projection_horizon.table
    price_counts = table.groupby("player_id", sort=False)["price_tenths"].nunique()
    changing = price_counts.loc[price_counts > 1]
    if not changing.empty:
        examples = sorted(changing.index.tolist(), key=str)[:5]
        raise DataSourceError(
            "The live multi-gameweek path has no versioned price-transition model; "
            f"captured prices must stay fixed across the horizon (players: {examples!r})."
        )

    first = table.loc[table["gameweek"] == first_gameweek]
    current = {
        int(player): int(price)
        for player, price in zip(
            first["player_id"].tolist(), first["price_tenths"].tolist(), strict=True
        )
    }
    departed = sorted(set(held.squad_player_ids) - set(current))
    if departed:
        raise DataSourceError(
            f"Held players {departed[:5]!r} are not on the projection horizon; resolve "
            "the removed players before planning."
        )
    fee = float(rules.transfers.sell_on_fee)
    budget = spending_power(
        bank_tenths=held.bank_tenths,
        sell_prices_tenths={
            player: sell_price_tenths(
                current[player], held.purchase_prices[player], sell_on_fee=fee
            )
            for player in held.squad_player_ids
        },
        stated_squad_sell_value_tenths=held.squad_sell_value_tenths,
    )
    held_sell_prices = dict(budget.sell_prices_tenths)

    planning_table = table.loc[
        :, ["gameweek", "player_id", "name", "team_id", "position", "expected_points"]
    ].copy(deep=True)
    planning_table["buy_price_tenths"] = table["price_tenths"].astype("int64")
    planning_table["sell_price_tenths"] = [
        held_sell_prices.get(int(player), int(price))
        for player, price in zip(
            table["player_id"].tolist(), table["price_tenths"].tolist(), strict=True
        )
    ]

    settings = OptimizationConfig() if optimization is None else optimization
    planning_policy = (
        # The same MEMBER_PLANNING_POLICY the one-week path builds from. Spelling the
        # controls out here instead would price a member's window at one hit cost and
        # their week at another the moment the policy moves.
        _transfer_config(
            rules,
            transfer_cap=None if len(projection_horizon.target_gameweeks) == 1 else 1,
        )
        if transfer_config is None
        else transfer_config
    )
    state = InitialSquadState(
        held.squad_player_ids,
        bank_tenths=budget.bank_tenths,
        free_transfers=min(held.free_transfers, planning_policy.max_free_transfers),
    )
    plan = optimize_transfer_plan(
        PlanningHorizon(planning_table),
        state,
        settings,
        planning_policy,
        chips=chips,
        first_week_overlap=first_week_overlap,
        first_week_transfer_cap=first_week_transfer_cap,
    )
    if not plan.has_solution or not plan.weeks:
        used = plan.diagnostics.get("deterministic_time_used")
        relative_gap = plan.diagnostics.get("relative_optimality_gap")
        raise DataSourceError(
            f"The transfer planner produced no {len(projection_horizon.target_gameweeks)}-"
            f"week solution; solver status was {plan.solver_status.name}, "
            f"deterministic time used was {used!r}, relative gap was {relative_gap!r}."
        )
    return plan, planning_policy
