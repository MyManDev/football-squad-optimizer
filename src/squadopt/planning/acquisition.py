"""CP sale proceeds for known purchases within a planning horizon."""

from collections.abc import Sequence
from typing import Literal

import pandas as pd
from ortools.sat.python import cp_model

from squadopt.planning.pricing import sell_price_tenths


class AcquisitionSales:
    """Carry the last permanent acquisition week; zero means the supplied old lot.

    Only purchases inside the horizon are known. An old holding's purchase price
    is never inferred from its sale price. Free Hit restores the entering lot.

    Two reductions leave every plan's proceeds as they were. A player whose sale
    price no lot can change, in any week, carries no lot at all. When no buy price
    moves inside the horizon and no week can play a Free Hit, a copy bought inside
    the horizon sells at that unchanged price, so the only lot that can sell for
    anything else is the original holding. A held player's lot is then one Boolean
    per week, whether the original holding is still held, and the choice between
    the two encodings is made once, for the whole horizon, before any week is added.
    """

    def __init__(
        self,
        tables: list[pd.DataFrame],
        fee: float,
        *,
        held: Sequence[bool] | None = None,
        free_hit_possible: bool = True,
    ) -> None:
        """``held`` says, in table order, which players the horizon starts holding.

        ``free_hit_possible`` says whether any horizon week can play a Free Hit. Left
        unknown, either one keeps the acquisition-week encoding, which needs neither.
        """

        self.buy_prices = [tuple(int(p) for p in t.buy_price_tenths) for t in tables]
        self.fee = fee
        # A week's sale price under each lot: the supplied old lot, then each earlier
        # week's purchase at its own buy price.
        self.choices = [
            [
                (
                    int(supplied),
                    *(
                        sell_price_tenths(buy[index], self.buy_prices[w][index], sell_on_fee=fee)
                        for w in range(week)
                    ),
                )
                for index, supplied in enumerate(table.sell_price_tenths)
            ]
            for week, (table, buy) in enumerate(zip(tables, self.buy_prices, strict=True))
        ]
        count = len(tables[0])
        # A lot is read only in a week where it can change the sale price. The first
        # week has one lot, the supplied one, so it never reads a lot.
        self.sensitive = [
            any(len(set(week[index])) > 1 for week in self.choices[1:]) for index in range(count)
        ]
        if held is not None and len(held) != count:
            raise ValueError("held must name every player of the horizon once.")
        frozen = all(len(set(prices)) == 1 for prices in zip(*self.buy_prices, strict=True))
        self.encoding: Literal["acquisition_week", "original_held"] = (
            "original_held"
            if held is not None and frozen and not free_hit_possible
            else "acquisition_week"
        )
        self.lots: list[cp_model.IntVar | int] = [0] * count
        # Whether the original holding is still held at the start of the next week.
        self.originals: list[cp_model.IntVar | int] = [int(bool(h)) for h in held or ()]

    def add_week(
        self,
        model: cp_model.CpModel,
        week: int,
        buys: Sequence[cp_model.IntVar],
        sells: Sequence[cp_model.IntVar],
        free_hit: cp_model.IntVar | None,
    ) -> cp_model.LinearExpr:
        if self.encoding == "original_held":
            if free_hit is not None:
                raise ValueError("A Free Hit reached sales declared without one.")
            return self._add_original_week(model, week, sells)
        return self._add_acquisition_week(model, week, buys, sells, free_hit)

    def _add_acquisition_week(
        self,
        model: cp_model.CpModel,
        week: int,
        buys: Sequence[cp_model.IntVar],
        sells: Sequence[cp_model.IntVar],
        free_hit: cp_model.IntVar | None,
    ) -> cp_model.LinearExpr:
        proceeds: list[cp_model.LinearExpr] = []
        for index, choices in enumerate(self.choices[week]):
            previous = self.lots[index]
            if len(set(choices)) == 1:
                proceeds.append(choices[0] * sells[index])
            else:
                price = model.new_int_var(
                    min(choices), max(choices), f"lot_sale_price_{week}_{index}"
                )
                model.add_element(previous, choices, price)
                amount = model.new_int_var(0, max(choices), f"lot_proceeds_{week}_{index}")
                model.add(amount == price).only_enforce_if(sells[index])
                model.add(amount == 0).only_enforce_if(sells[index].Not())
                proceeds.append(amount)
            if week + 1 == len(self.buy_prices) or not self.sensitive[index]:
                continue
            after = model.new_int_var(0, week + 1, f"acquisition_week_{week}_{index}")
            keep = [buys[index].Not()]
            replace: list[cp_model.LiteralT] = [buys[index]]
            if free_hit is not None:
                model.add(after == previous).only_enforce_if(free_hit)
                keep.append(free_hit.Not())
                replace.append(free_hit.Not())
            model.add(after == previous).only_enforce_if(keep)
            model.add(after == week + 1).only_enforce_if(replace)
            self.lots[index] = after
        return cp_model.LinearExpr.sum(proceeds)

    def _add_original_week(
        self,
        model: cp_model.CpModel,
        week: int,
        sells: Sequence[cp_model.IntVar],
    ) -> cp_model.LinearExpr:
        proceeds: list[cp_model.LinearExpr] = []
        for index, choices in enumerate(self.choices[week]):
            if not self.sensitive[index]:
                proceeds.append(choices[0] * sells[index])
                continue
            # A copy bought inside the horizon sells at the unchanged buy price, which is
            # its own purchase price. Only a sale of the original pays the supplied price.
            price = self.buy_prices[week][index]
            original = self.originals[index]
            sold_original: cp_model.LinearExpr | int
            if isinstance(original, int):
                sold_original = original * sells[index]
            else:
                sold_original = model.new_bool_var(f"sold_original_{week}_{index}")
                model.add(sold_original <= sells[index])
                model.add(sold_original <= original)
                model.add(sold_original >= sells[index] + original - 1)
            proceeds.append(price * sells[index] - (price - choices[0]) * sold_original)
            if week + 1 == len(self.buy_prices) or (isinstance(original, int) and not original):
                continue
            still_held = model.new_bool_var(f"original_held_{week + 1}_{index}")
            model.add(still_held == original - sold_original)
            self.originals[index] = still_held
        return cp_model.LinearExpr.sum(proceeds)
