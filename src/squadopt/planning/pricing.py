"""The game's selling price for a held player.

A player is bought at the market price of the moment and sold at the purchase price plus
a share of any rise since — the rest is the sell-on fee the game keeps — rounded down
to a tenth; a fall is passed on in full. The rule is stated once here so the live
transfer decision, the season chain, and any later price model agree on it.
"""

import math
from numbers import Integral, Real


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
