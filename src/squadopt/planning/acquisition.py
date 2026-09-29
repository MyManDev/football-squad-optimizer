"""CP sale proceeds for known purchases within a planning horizon."""

import pandas as pd
from ortools.sat.python import cp_model

from squadopt.planning.pricing import sell_price_tenths


class AcquisitionSales:
    """Carry the last permanent acquisition week; zero means the supplied old lot.

    Only purchases inside the horizon are known. An old holding's purchase price
    is never inferred from its sale price. Free Hit restores the entering lot.
    """

    def __init__(self, tables: list[pd.DataFrame], fee: float) -> None:
        self.buy_prices = [tuple(int(p) for p in t.buy_price_tenths) for t in tables]
        self.fee = fee
        self.lots: list[cp_model.IntVar | int] = [0] * len(tables[0])

    def add_week(
        self,
        model: cp_model.CpModel,
        week: int,
        players: pd.DataFrame,
        buys: list[cp_model.IntVar],
        sells: list[cp_model.IntVar],
        free_hit: cp_model.IntVar | None,
    ) -> cp_model.LinearExpr:
        proceeds: list[cp_model.LinearExpr] = []
        for index, supplied in enumerate(players.sell_price_tenths):
            previous = self.lots[index]
            choices = [int(supplied)] + [
                sell_price_tenths(
                    self.buy_prices[week][index], self.buy_prices[w][index], sell_on_fee=self.fee
                )
                for w in range(week)
            ]
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
            if week + 1 == len(self.buy_prices):
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
