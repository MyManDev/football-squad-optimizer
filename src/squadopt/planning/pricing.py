"""The game's selling price for a held player, and what a squad's holder can spend.

A player is bought at the market price of the moment and sold at the purchase price plus
a share of any rise since — the rest is the sell-on fee the game keeps — rounded down
to a tenth; a fall is passed on in full. The rule is stated once here so the live
transfer decision, the season chain, and any later price model agree on it.

``spending_power`` is the same rule read at the level of a whole squad, for the case
where the per-player purchase prices are not published but the squad's selling value is.
"""

import math
from collections.abc import Mapping
from dataclasses import dataclass
from numbers import Integral, Real
from types import MappingProxyType


def sell_price_tenths(
    current_tenths: int, purchase_tenths: int, *, sell_on_fee: float = 0.5
) -> int:
    """Return the sell price in tenths under a ``sell_on_fee`` share of any profit.

    ``sell_on_fee`` is the fraction of a rise the game keeps (0.5 in the published
    rules); zero sells at the market price, one sells at the purchase price when the
    price has risen. The retained profit is rounded down to a whole tenth; the fee is
    read to the nearest whole percent.
    """

    for name, value in (("current_tenths", current_tenths), ("purchase_tenths", purchase_tenths)):
        if isinstance(value, bool) or not isinstance(value, Integral) or int(value) < 0:
            raise ValueError(f"{name} must be a non-negative integer number of tenths.")
    if (
        isinstance(sell_on_fee, bool)
        or not isinstance(sell_on_fee, Real)
        or not math.isfinite(float(sell_on_fee))
        or not 0.0 <= float(sell_on_fee) <= 1.0
    ):
        raise ValueError("sell_on_fee must be a finite fraction between 0 and 1.")
    current = int(current_tenths)
    purchase = int(purchase_tenths)
    if current <= purchase:
        return current
    # Integer arithmetic on the retained share, so 0.5 of a 3-tenth rise is 1 tenth
    # exactly and no binary-fraction rounding can move a boundary case.
    retained_percent = round((1.0 - float(sell_on_fee)) * 100)
    return purchase + ((current - purchase) * retained_percent) // 100


@dataclass(frozen=True, slots=True)
class SpendingPower:
    """What the holder of one squad may spend at a deadline, and on what evidence.

    ``sell_prices_tenths`` is what a plan may credit itself for selling each held player
    and ``bank_tenths`` what it starts with, so ``bank_tenths`` plus any subset of those
    prices is the money that subset of sales releases. Both are the *planning* numbers:
    they are the caller's own sell prices, lowered where those prices credited more than
    the source says the squad is worth.

    ``withheld_from_bank_tenths`` and ``per_player_deduction_tenths`` are how much was
    taken away and where, so a caller can say so rather than quietly plan on a smaller
    budget than the numbers it handed in.
    """

    bank_tenths: int
    sell_prices_tenths: Mapping[int, int]
    stated_squad_sell_value_tenths: int | None
    withheld_from_bank_tenths: int
    per_player_deduction_tenths: int

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "sell_prices_tenths",
            MappingProxyType({int(k): int(v) for k, v in dict(self.sell_prices_tenths).items()}),
        )

    @property
    def spendable_tenths(self) -> int:
        """The bank plus every held player's sell price: a whole-squad rebuild's budget."""

        return int(self.bank_tenths) + sum(self.sell_prices_tenths.values())

    @property
    def squad_sell_value_known(self) -> bool:
        """Whether the source stated what the fifteen are worth to sell."""

        return self.stated_squad_sell_value_tenths is not None


def _non_negative(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, Integral) or int(value) < 0:
        raise ValueError(f"{name} must be a non-negative integer number of tenths.")
    return int(value)


def spending_power(
    *,
    bank_tenths: int,
    sell_prices_tenths: Mapping[int, int],
    stated_squad_sell_value_tenths: int | None,
) -> SpendingPower:
    """Return the budget a plan may spend, given a stated squad selling value.

    ``sell_prices_tenths`` are the sell prices the caller derived per player. Where the
    purchase prices behind them are known those numbers are the rule's own answer and
    nothing here changes them: pass ``stated_squad_sell_value_tenths=None`` and this
    returns them untouched.

    Where the purchase prices are *not* known, a caller has no per-player answer and the
    usual fallback is the current price, which is an upper bound: the game never pays
    more than the market price for a sale and pays less whenever the player has risen.
    The public endpoints do publish the aggregate, though, so the size of that
    overstatement is known exactly even when its division among the fifteen is not:

        shortfall = sum(sell prices handed in) - stated squad selling value

    The shortfall is removed from the budget in the one order that keeps every subset of
    sales honest. Take it from the bank first, because a sale of *any* subset draws on
    the same bank. What the bank cannot cover comes off every held player's sell price,
    each by the whole remainder rather than a share of it: the fee on any single player
    is at most the fee on the squad, so ``price - remainder`` is a floor no sale can
    fall below. A one-player sale then has exactly the budget the aggregate proves; a
    sale of several has a little less, and selling all fifteen has the remainder taken
    fifteen times over. That last case is the price of a budget the planner can only
    express per player and in one bank that may not go below nothing, and it is paid in
    the direction that cannot invent money.

    Nothing here divides the shortfall between players, infers a purchase price, or
    scales a price by a ratio: the shortfall is a measured total and it is spent as one.
    """

    bank = _non_negative(bank_tenths, "bank_tenths")
    prices = {
        int(player): _non_negative(price, f"sell price for player {player}")
        for player, price in dict(sell_prices_tenths).items()
    }
    if stated_squad_sell_value_tenths is None:
        return SpendingPower(
            bank_tenths=bank,
            sell_prices_tenths=prices,
            stated_squad_sell_value_tenths=None,
            withheld_from_bank_tenths=0,
            per_player_deduction_tenths=0,
        )
    stated = _non_negative(stated_squad_sell_value_tenths, "stated_squad_sell_value_tenths")
    # A squad worth more than its own sell prices claim is not an overstatement to
    # correct: the stated value is a fact about a moment, the prices may be a later one,
    # and crediting the difference would spend money nothing in the source proves.
    shortfall = max(0, sum(prices.values()) - stated)
    per_player = max(0, shortfall - bank)
    withheld = shortfall - per_player
    return SpendingPower(
        bank_tenths=bank - withheld,
        sell_prices_tenths={player: max(0, price - per_player) for player, price in prices.items()},
        stated_squad_sell_value_tenths=stated,
        withheld_from_bank_tenths=withheld,
        per_player_deduction_tenths=per_player,
    )
