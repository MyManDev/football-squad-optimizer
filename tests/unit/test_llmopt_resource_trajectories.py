"""All resource paths on a small transfer market over the GW19 chip renewal."""

from dataclasses import dataclass
from itertools import product

import pandas as pd
import pytest
from ortools.sat.python import cp_model

from squadopt.contracts.preferences import DecisionPreferences
from squadopt.planning import (
    ChipAvailability,
    ChipUseWindow,
    InitialSquadState,
    PlanningHorizon,
    TransferPlanningConfig,
    optimize_transfer_plan,
)
from squadopt.planning.optimizer import _build_model, _validated_week_tables

WEEKS = (19, 20, 21)
CHIPS = ("wildcard", "freehit")
POSITIONS = {1: "GK", 2: "DEF", 3: "DEF", 4: "MID", 5: "MID", 6: "FWD"}
MARKET = (
    {1: 50, 2: 52, 3: 47, 4: 50, 5: 45, 6: 50},
    {1: 50, 2: 53, 3: 54, 4: 49, 5: 49, 6: 50},
    {1: 50, 2: 51, 3: 43, 4: 53, 5: 52, 6: 50},
)
# The supplied sale prices for initial holdings. A later purchase has its own basis.
OPENING_SALES = (
    {1: 50, 2: 49, 4: 47, 6: 50},
    {1: 50, 2: 49, 4: 47, 6: 50},
    {1: 50, 2: 48, 4: 49, 6: 50},
)
OPENING = frozenset({1, 2, 4, 6})
SQUADS = [
    frozenset((1, defender, midfielder, 6)) for defender, midfielder in product((2, 3), (4, 5))
]


@dataclass(frozen=True)
class Week:
    chip: str | None
    squad: frozenset[int]
    bought: frozenset[int]
    sold: frozenset[int]
    count: int
    bank_before: int
    bank_after: int
    bank_carried: int
    free_before: int
    unused: int
    free_next: int
    hit: float


def enumerate_paths(bank, free):
    """Use game rules on ordinary numbers and sets, without planner helpers or a solver."""

    def visit(history, held, purchases, cash, available, used):
        index = len(history)
        if index == len(WEEKS):
            yield history
            return
        market = MARKET[index]
        for chip, squad in product((None, *CHIPS), SQUADS):
            right = (chip, WEEKS[index] >= 20)
            if chip and right in used:
                continue
            if chip == "freehit" and history and history[-1].chip == "freehit":
                continue
            bought, sold = squad - held, held - squad
            proceeds = 0
            for player in sold:
                if player not in purchases:
                    proceeds += OPENING_SALES[index][player]
                else:
                    basis = purchases[player]
                    proceeds += min(market[player], basis) + max(0, market[player] - basis) // 2
            balance = cash + proceeds - sum(market[player] for player in bought)
            if balance < 0:
                continue
            unused = available if chip else max(0, available - len(bought))
            next_free = available if chip else min(5, unused + 1)
            hit = 0 if chip else 4 * max(0, len(bought) - available)
            carried_cash = cash if chip == "freehit" else balance
            row = Week(
                chip,
                squad,
                bought,
                sold,
                len(bought),
                cash,
                balance,
                carried_cash,
                available,
                unused,
                next_free,
                hit,
            )
            next_purchases = {p: price for p, price in purchases.items() if p not in sold}
            next_purchases.update({p: market[p] for p in bought})
            yield from visit(
                (*history, row),
                held if chip == "freehit" else squad,
                purchases if chip == "freehit" else next_purchases,
                carried_cash,
                next_free,
                used | {right} if chip else used,
            )

    return set(visit((), OPENING, {}, bank, free, set()))


def problem(bank, free):
    table = pd.DataFrame(
        [
            dict(
                gameweek=week,
                player_id=p,
                name=str(p),
                team_id=str(p),
                position=position,
                expected_points=float(p),
                buy_price_tenths=MARKET[index][p],
                sell_price_tenths=OPENING_SALES[index].get(p, MARKET[index][p]),
            )
            for index, week in enumerate(WEEKS)
            for p, position in POSITIONS.items()
        ]
    )
    periods = (ChipUseWindow(frozenset({19})), ChipUseWindow(frozenset({20, 21})))
    rights = ChipAvailability(
        {chip: frozenset(WEEKS) for chip in CHIPS}, use_windows={chip: periods for chip in CHIPS}
    )
    return (
        PlanningHorizon(table),
        InitialSquadState(tuple(sorted(OPENING)), bank, free),
        TransferPlanningConfig(acquisition_sell_on_fee=0.5),
        rights,
    )


def production_paths(horizon, state, settings, policy, rights):
    tables = _validated_week_tables(horizon, settings)
    a = _build_model(tables, set(state.squad_player_ids), state, settings, policy, rights)
    a.model.clear_objective()
    ids = tuple(tables[0].player_id)
    for index in range(len(WEEKS)):
        for column, player in enumerate(ids):
            # Fix only lineup and armband symmetries. Every squad can use GK, DEF, FWD.
            if POSITIONS[player] == "MID":
                a.model.add(a.starter_vars[index][column] == 0)
        a.model.add(a.captain_vars[index][ids.index(1)] == 1)

    class Collector(cp_model.CpSolverSolutionCallback):
        def __init__(self):
            super().__init__()
            self.paths = set()

        def on_solution_callback(self):
            cash = state.bank_tenths
            path = []
            for i in range(len(WEEKS)):

                def selected(variables):
                    return frozenset(
                        p for p, v in zip(ids, variables, strict=True) if self.value(v)
                    )

                chip = next((c for c, v in a.chip_vars[i].items() if self.value(v)), None)
                carried = self.value(a.base_bank_vars[i])
                path.append(
                    Week(
                        chip,
                        selected(a.squad_vars[i]),
                        selected(a.transfer_in_vars[i]),
                        selected(a.transfer_out_vars[i]),
                        self.value(a.transfer_count_vars[i]),
                        cash,
                        self.value(a.bank_after_vars[i]),
                        carried,
                        self.value(a.free_before_vars[i]),
                        self.value(a.free_unused_vars[i]),
                        self.value(a.free_next_vars[i]),
                        4 * self.value(a.paid_transfer_vars[i]),
                    )
                )
                cash = carried
            self.paths.add(tuple(path))

    answers = Collector()
    solver = cp_model.CpSolver()
    solver.parameters.enumerate_all_solutions = True
    solver.parameters.num_search_workers = 1
    assert solver.solve(a.model, answers) == cp_model.OPTIMAL
    return answers.paths


@pytest.mark.parametrize(("bank", "free"), [(0, 1), (8, 5)])
def test_every_three_week_resource_path_matches_an_independent_market(bank, free, small_config):
    expected = enumerate_paths(bank, free)
    horizon, state, policy, rights = problem(bank, free)
    actual = production_paths(horizon, state, small_config, policy, rights)
    assert actual == expected
    assert any(row.bank_carried != row.bank_after for path in expected for row in path)
    assert any(path[0].chip == path[1].chip == "wildcard" for path in expected)
    assert any(
        path[0].chip == path[2].chip == "freehit" and path[1].chip == "wildcard"
        for path in expected
    )
    if free == 1:
        assert any(row.hit > 0 for path in expected for row in path)
    else:
        assert any(
            row.count == 0 and row.free_before == row.free_next == 5
            for path in expected
            for row in path
        )


@pytest.mark.parametrize(
    "chips",
    [
        ("freehit", "wildcard", "freehit"),
        ("wildcard", "wildcard", None),
        ("wildcard", None, "freehit"),
    ],
)
def test_published_weeks_reproduce_mixed_chip_market_paths(chips, small_config):
    horizon, state, policy, rights = problem(0, 1)
    # Select a reproducible legal path with actual transfers on the named chip dates.
    options = [p for p in enumerate_paths(0, 1) if tuple(row.chip for row in p) == chips]
    path = max(
        options, key=lambda p: (sum(r.count for r in p), tuple(tuple(sorted(r.squad)) for r in p))
    )
    preferences = DecisionPreferences.parse(
        {
            "frozen_weeks": [
                dict(
                    week=i, chip=r.chip, transfers_in=sorted(r.bought), transfers_out=sorted(r.sold)
                )
                for i, r in enumerate(path, 1)
            ]
        }
    )
    result = optimize_transfer_plan(
        horizon, state, small_config, policy, chips=rights, preferences=preferences
    )
    assert result.has_solution
    for actual, expected in zip(result.weeks, path, strict=True):
        assert (
            Week(
                actual.chip,
                frozenset(actual.selected_squad.player_id),
                frozenset(actual.transfers_in.player_id),
                frozenset(actual.transfers_out.player_id),
                actual.transfer_count,
                actual.bank_before_tenths,
                actual.bank_after_tenths,
                actual.bank_before_tenths if actual.chip == "freehit" else actual.bank_after_tenths,
                actual.free_transfers_before,
                actual.free_transfers_unused,
                actual.free_transfers_for_next_gameweek,
                actual.transfer_hit_points,
            )
            == expected
        )
