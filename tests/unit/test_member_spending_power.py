"""What a member may spend when the game has kept half of a price rise.

The published rule: "The price shown on your transfers page is a player's selling price.
This selling price may be less than the player's current purchase price as a 50% sell-on
fee will be applied on any profits made on that player." The 2026-27 bootstrap states the
same two facts as ``transfers_sell_on_fee`` 0.5 and ``element_sell_at_purchase_price``
false.

The public endpoints publish no purchase price, so no consumer can say what one named
player would raise. They do publish the entry's whole worth at the deadline, and the bank
inside it, so the fifteen together are stated exactly. These tests pin the rule with
literals, the aggregate the parser reads, and the budget a plan is then held to.
"""

from typing import Any

import pytest
import tests.unit.test_live_transfers as world_module
import tests.unit.test_source_fpl_live as payload_module

from squadopt.application.entries import EntryError, EntryPicks, held_squad_from_picks
from squadopt.data.errors import DataSourceError
from squadopt.data.sources.fpl_live import fpl_entry_picks
from squadopt.live.recommendation import project, read_projection_handoff
from squadopt.live.transfers import plan_transfers
from squadopt.planning import sell_price_tenths, spending_power

SEASON = world_module.SEASON
world = world_module._world  # re-register the world fixture in this module

SQUAD = tuple(range(1001, 1016))


# --- the rule itself, in literals -----------------------------------------------------


def test_a_player_whose_price_fell_sells_for_the_market_price_and_pays_no_fee() -> None:
    """A fall is passed on in full: the member takes the whole loss, the game takes none.

    Bought at 8.0, now 7.6, sold for 7.6. The fee applies to profits, and there are none.
    """

    assert sell_price_tenths(76, 80, sell_on_fee=0.5) == 76
    assert sell_price_tenths(80, 80, sell_on_fee=0.5) == 80


def test_a_rise_of_an_odd_number_of_tenths_rounds_the_retained_half_down() -> None:
    """Bought at 5.0, now 5.3: the 0.3 rise is halved to 0.15 and rounded down to 0.1.

    The selling price is 5.1, not 5.15 and not 5.2. The same at 7.0 to 7.7: the 0.7 rise
    leaves 0.3, so 7.3. An even rise has nothing to round: 6.0 to 6.4 sells at 6.2.
    """

    assert sell_price_tenths(53, 50, sell_on_fee=0.5) == 51
    assert sell_price_tenths(77, 70, sell_on_fee=0.5) == 73
    assert sell_price_tenths(64, 60, sell_on_fee=0.5) == 62
    assert sell_price_tenths(51, 50, sell_on_fee=0.5) == 50, "a single tenth is kept whole"


# --- the aggregate the endpoints do publish -------------------------------------------


def test_the_parser_reads_the_squads_selling_value_as_the_worth_less_the_bank() -> None:
    """``entry_history.value`` is squad plus bank, so the squad alone is value minus bank.

    A member worth 100.4 with 1.8 in the bank holds fifteen that would raise 98.6.
    """

    record = fpl_entry_picks(
        payload_module._picks_payload(squad=list(SQUAD), bank=18, value=1_004),
        payload_module._history_payload(),
        entry_id=11,
        season="2026-27",
        gameweek=3,
    )
    assert record.bank_tenths == 18
    assert record.squad_sell_value_tenths == 986
    assert record.purchase_prices_known is False, "the split among the fifteen is not published"


def test_a_worth_smaller_than_its_own_bank_is_refused_rather_than_read_as_a_debt() -> None:
    with pytest.raises(DataSourceError, match="negative selling value"):
        fpl_entry_picks(
            payload_module._picks_payload(squad=list(SQUAD), bank=50, value=40),
            payload_module._history_payload(),
            entry_id=11,
            season="2026-27",
            gameweek=3,
        )


# --- what the member may spend --------------------------------------------------------


def _prices(*, risen_by: int = 0) -> dict[int, int]:
    """Fifteen players at 6.0 each, the first risen by ``risen_by`` tenths since purchase."""

    prices = dict.fromkeys(SQUAD, 60)
    prices[SQUAD[0]] = 60 + risen_by
    return prices


def test_with_no_stated_value_the_sell_prices_and_bank_are_returned_untouched() -> None:
    """Our own squad: the purchase prices are the ledger's, so the rule is already exact."""

    power = spending_power(
        bank_tenths=25,
        sell_prices_tenths=_prices(),
        stated_squad_sell_value_tenths=None,
    )
    assert power.bank_tenths == 25
    assert dict(power.sell_prices_tenths) == _prices()
    assert power.withheld_from_bank_tenths == 0
    assert power.per_player_deduction_tenths == 0
    assert power.squad_sell_value_known is False


def test_a_shortfall_the_bank_covers_comes_out_of_the_bank_alone() -> None:
    """Fifteen priced at 90.3 against a stated 90.0: 0.3 of it is the game's, not the
    member's. The bank of 2.0 pays it, and every sell price stands."""

    priced = _prices(risen_by=3)
    assert sum(priced.values()) == 903
    power = spending_power(
        bank_tenths=20,
        sell_prices_tenths=priced,
        stated_squad_sell_value_tenths=900,
    )
    assert power.withheld_from_bank_tenths == 3
    assert power.per_player_deduction_tenths == 0
    assert power.bank_tenths == 17
    assert dict(power.sell_prices_tenths) == priced
    assert power.spendable_tenths == 920, "the stated value plus the bank, exactly"


def test_a_shortfall_larger_than_the_bank_comes_off_every_held_players_sell_price() -> None:
    """With nothing banked there is nothing to take the fee out of but the sales.

    Each player loses the whole remainder rather than a share of it: the fee on any one
    player is at most the fee on the squad, so the lowered price is a floor no single sale
    can fall below. One sale then has exactly the budget the aggregate proves.
    """

    priced = _prices(risen_by=3)
    power = spending_power(
        bank_tenths=1,
        sell_prices_tenths=priced,
        stated_squad_sell_value_tenths=900,
    )
    assert power.withheld_from_bank_tenths == 1
    assert power.per_player_deduction_tenths == 2
    assert power.bank_tenths == 0
    assert power.sell_prices_tenths[SQUAD[0]] == 61, "63 priced, 2 withheld"
    assert power.sell_prices_tenths[SQUAD[1]] == 58
    one_sale = power.bank_tenths + power.sell_prices_tenths[SQUAD[1]]
    assert one_sale == 1 + 60 - 3, "bank plus price, less the whole squad's fee"


def test_a_stated_value_above_the_priced_total_credits_the_member_with_nothing() -> None:
    """A stated value is a fact about a deadline and the prices may be a later one. Where
    it is the larger number the difference is not money: crediting it would spend what the
    source never said the member had."""

    priced = _prices()
    power = spending_power(
        bank_tenths=20,
        sell_prices_tenths=priced,
        stated_squad_sell_value_tenths=980,
    )
    assert power.bank_tenths == 20
    assert dict(power.sell_prices_tenths) == priced
    assert power.spendable_tenths == 920


@pytest.mark.parametrize("bad", [-1, "8"])
def test_a_budget_cannot_be_built_from_a_number_that_is_not_a_count_of_tenths(
    bad: object,
) -> None:
    with pytest.raises(ValueError, match="non-negative integer"):
        spending_power(
            bank_tenths=0,
            sell_prices_tenths=_prices(),
            stated_squad_sell_value_tenths=bad,  # type: ignore[arg-type]
        )


# --- the seam: picks to held squad ----------------------------------------------------


def _picks(**overrides: Any) -> EntryPicks:
    base: dict[str, Any] = {
        "entry_id": 123456,
        "season": "2026-27",
        "gameweek": 3,
        "squad": SQUAD,
        "starting_xi": SQUAD[:11],
        "captain": SQUAD[0],
        "vice_captain": SQUAD[1],
        "bank_tenths": 20,
        "free_transfers": 1,
        "squad_sell_value_tenths": 900,
    }
    base.update(overrides)
    return EntryPicks(**base)


def test_the_held_squad_carries_the_stated_selling_value_to_the_planner() -> None:
    held = held_squad_from_picks(_picks(), current_prices=_prices(risen_by=3))
    assert held.squad_sell_value_tenths == 900
    assert held.bank_tenths == 20, "the real bank, unchanged; the planner does the withholding"


def test_real_purchase_prices_leave_the_aggregate_out_of_it() -> None:
    """Where what was paid is known the per-player rule is exact and needs no cap."""

    held = held_squad_from_picks(
        _picks(purchase_prices={SQUAD[0]: 55}, purchase_prices_known=True),
        current_prices=_prices(risen_by=3),
    )
    assert held.squad_sell_value_tenths is None
    assert held.purchase_prices[SQUAD[0]] == 55


def test_picks_with_neither_purchase_prices_nor_an_aggregate_are_refused() -> None:
    """Absent is not zero and absent is not the optimistic number. A squad whose budget
    nothing states cannot be planned on: the current prices would hand the member the half
    of every rise the game kept."""

    with pytest.raises(EntryError, match="what it can spend is unknown"):
        held_squad_from_picks(_picks(squad_sell_value_tenths=None), current_prices=_prices())


# --- and the plan a member is actually given ------------------------------------------


def _context(world: dict[str, Any]) -> tuple[Any, Any, Any]:
    from squadopt.data.snapshots import read_snapshot
    from squadopt.live import read_inputs, read_season_rules

    snapshot = read_snapshot(world["snapshot_root"], world["gw2_id"])
    inputs = read_inputs(snapshot, season=SEASON, gameweek=2)
    handoff = read_projection_handoff(world_module._handoff(world))
    return inputs, project(inputs, in_season=handoff), read_season_rules(snapshot, season=SEASON)


def test_a_plan_is_held_to_the_stated_value_not_to_the_sum_of_current_prices(
    world: dict[str, Any],
) -> None:
    """The same member, the same capture, told once that the fifteen are worth their
    priced total and once that they are worth a pound less. The second plan is the one
    the member could actually pay for, and the decision records the smaller number."""

    inputs, projection, rules = _context(world)
    squad = _legal_squad()
    prices = {
        int(str(row["player_id"])): int(str(row["price_tenths"]))
        for _, row in inputs.players.iterrows()
    }
    priced_total = sum(prices[code] for code in squad)

    def decide(sell_value: int) -> Any:
        picks = EntryPicks(
            entry_id=101,
            season=SEASON,
            gameweek=1,
            squad=tuple(squad),
            starting_xi=tuple(squad[:11]),
            captain=squad[0],
            vice_captain=squad[1],
            bank_tenths=10,
            squad_sell_value_tenths=sell_value,
            free_transfers=1,
            free_transfers_known=False,
            source_snapshot_id=world["gw2_id"],
        )
        held = held_squad_from_picks(picks, current_prices=prices)
        _plan, decision, _config = plan_transfers(inputs, projection, held, rules)
        return decision

    no_fee = decide(priced_total)
    fee_paid = decide(priced_total - 10)

    def whole_squad_budget(decision: Any) -> int:
        return int(str(decision.bank_before_tenths)) + int(
            str(decision.diagnostics["held_squad_sell_value_tenths"])
        )

    assert whole_squad_budget(no_fee) == priced_total + 10
    # One pound of the priced total belongs to the game, and the plan never sees it: the
    # bank paid it, so the budget is the stated value plus the bank, to the tenth.
    assert fee_paid.bank_before_tenths == 0
    assert whole_squad_budget(fee_paid) == priced_total - 10 + 10
    assert fee_paid.diagnostics["stated_squad_sell_value_tenths"] == priced_total - 10
    assert no_fee.diagnostics["stated_squad_sell_value_tenths"] == priced_total


def _legal_squad() -> list[int]:
    codes = [1001, 1002]
    codes += [1004, 1005, 1006, 1007, 1008]
    codes += [1012, 1013, 1014, 1015, 1016]
    codes += [1020, 1021, 1022]
    return codes
