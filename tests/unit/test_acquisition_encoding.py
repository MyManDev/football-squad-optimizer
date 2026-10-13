"""The reduced sale encodings price every plan as the acquisition-week encoding did.

`AcquisitionSales` drops the lot of a player whose sale price no lot can change, and
under frozen prices with no Free Hit it prices a held player's sale by one Boolean per
week. Both are re-encodings, so the reference below is the class as it stood before
them, kept verbatim. One test asks CP-SAT for any legal sequence of moves the two price
differently. That sees pricing only: a sequence the reduced encoding refuses drops out
of its search. So a second test fixes legal sequences one at a time and requires the
reduced encoding to accept each at the proceeds a numeric replay of the full lot gives.
A third solves small horizons end to end under both, to the same value, and then each
plan's squads again under the other encoding.
"""

import copy
import random
from collections import Counter
from dataclasses import replace

import pandas as pd
import pytest
from ortools.sat.python import cp_model

from squadopt.planning import ChipAvailability, InitialSquadState, PlanningHorizon
from squadopt.planning import optimizer as planning_optimizer
from squadopt.planning.acquisition import AcquisitionSales
from squadopt.planning.models import TransferPlanningConfig
from squadopt.planning.optimizer import optimize_transfer_plan
from squadopt.planning.pricing import sell_price_tenths


class _AcquisitionWeekReference:
    """The encoding before the reductions: every player carries a lot in every week."""

    def __init__(self, tables, fee):
        self.buy_prices = [tuple(int(p) for p in t.buy_price_tenths) for t in tables]
        self.fee = fee
        self.lots = [0] * len(tables[0])

    def add_week(self, model, week, players, buys, sells, free_hit):
        proceeds = []
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
            replace = [buys[index]]
            if free_hit is not None:
                model.add(after == previous).only_enforce_if(free_hit)
                keep.append(free_hit.Not())
                replace.append(free_hit.Not())
            model.add(after == previous).only_enforce_if(keep)
            model.add(after == week + 1).only_enforce_if(replace)
            self.lots[index] = after
        return cp_model.LinearExpr.sum(proceeds)


class _Reference(_AcquisitionWeekReference):
    """The reference behind today's call: it reads the same tables and nothing else."""

    def __init__(self, tables, fee, **_):
        super().__init__(tables, fee)
        self.tables = tables

    def add_week(self, model, week, buys, sells, free_hit):
        return super().add_week(model, week, self.tables[week], buys, sells, free_hit)


def _tables(buy, sell):
    return [
        pd.DataFrame({"buy_price_tenths": b, "sell_price_tenths": s})
        for b, s in zip(buy, sell, strict=True)
    ]


def _path(rng, weeks, held, fee, moving):
    """One player's buy and supplied sale price in each week.

    A held player sells at the game's rule from an unknown purchase, so a risen one sells
    below the price and a fallen one at it. Now and then the supplied price sits lower
    than the rule gives, on a player held or not, or moves while the buy price stays put.
    The horizon refuses a supplied price above the buy price, so none is generated.
    """

    price = rng.randint(40, 70)
    purchase = price + rng.choice((-12, -6, -3, -1, 0, 2, 5))
    odd = rng.random() < 0.2
    drift = rng.random() < 0.25
    path = []
    for week in range(weeks):
        if week and moving:
            price += rng.choice((-1, 0, 1))
        supplied = sell_price_tenths(price, purchase, sell_on_fee=fee) if held else price
        if odd:
            supplied -= rng.choice((1, 3))
        if drift and week:
            supplied = min(price, supplied + rng.choice((-1, 1)))
        path.append((price, max(0, supplied)))
    return path


def _scenario(seed):
    rng = random.Random(seed)
    weeks = rng.randint(2, 5)
    fee = rng.choice((0.0, 0.25, 0.5, 1.0))
    moving = rng.random() < 0.3
    held = [rng.random() < 0.6 for _ in range(rng.randint(1, 4))]
    paths = [_path(rng, weeks, h, fee, moving) for h in held]
    free_hits = set(rng.sample(range(weeks), rng.randint(1, 2))) if rng.random() < 0.4 else set()
    known = held if rng.random() < 0.9 else None
    buy = [[path[week][0] for path in paths] for week in range(weeks)]
    sell = [[path[week][1] for path in paths] for week in range(weeks)]
    return _tables(buy, sell), fee, held, known, free_hits


def _differs(tables, fee, held, known, free_hits):
    """Whether some legal sequence of moves sells for a different total in some week.

    Every player moves freely: bought when not held, sold when held, and in a Free Hit
    week the next week starts from the holding this week started from. CP-SAT then looks
    for any such sequence on which the two encodings disagree. Both encodings share one
    model, so a sequence the reduced one refuses is never searched: this checks pricing
    only, and `_accepted` checks that no legal sequence is refused.
    """

    model = cp_model.CpModel()
    count = len(tables[0])
    reduced = AcquisitionSales(tables, fee, held=known, free_hit_possible=bool(free_hits))
    reference = _AcquisitionWeekReference(tables, fee)
    holding = [int(h) for h in held]
    disagreements = []
    for week in range(len(tables)):
        buys = [model.new_bool_var(f"buy_{week}_{i}") for i in range(count)]
        sells = [model.new_bool_var(f"sell_{week}_{i}") for i in range(count)]
        free_hit = model.new_bool_var(f"free_hit_{week}") if week in free_hits else None
        starts = []
        for i in range(count):
            model.add(buys[i] + sells[i] <= 1)
            squad = model.new_bool_var(f"squad_{week}_{i}")
            model.add(squad == holding[i] + buys[i] - sells[i])
            if free_hit is None:
                starts.append(squad)
                continue
            start = model.new_bool_var(f"start_{week}_{i}")
            model.add(start == squad).only_enforce_if(free_hit.Not())
            model.add(start == holding[i]).only_enforce_if(free_hit)
            starts.append(start)
        holding = starts
        disagree = model.new_bool_var(f"disagree_{week}")
        model.add(
            reduced.add_week(model, week, buys, sells, free_hit)
            != reference.add_week(model, week, tables[week], buys, sells, free_hit)
        ).only_enforce_if(disagree)
        disagreements.append(disagree)
    model.add_bool_or(disagreements)
    solver = cp_model.CpSolver()
    solver.parameters.num_workers = 1
    status = solver.solve(model)
    assert status in {cp_model.OPTIMAL, cp_model.FEASIBLE, cp_model.INFEASIBLE}
    return status != cp_model.INFEASIBLE, reduced.encoding


def test_no_legal_sequence_of_moves_sells_for_a_different_amount():
    encodings = Counter()
    for seed in range(160):
        differs, encoding = _differs(*_scenario(seed))
        assert not differs, seed
        encodings[encoding] += 1
    # Both encodings are exercised, the Boolean one on frozen prices alone.
    assert min(encodings["original_held"], encodings["acquisition_week"]) >= 40, encodings


def _sequence(held, weeks, free_hits, bits):
    """The legal moves one integer names: a toggle per player and week, then each chip.

    A toggle buys a player not held and sells one held. A played Free Hit leaves the
    next week starting from the holding this week started from.
    """

    count = len(held)
    chips = sorted(free_hits)
    holding = [int(h) for h in held]
    moves = []
    for week in range(weeks):
        toggles = [bits >> (week * count + i) & 1 for i in range(count)]
        played = int(week in free_hits and bits >> (weeks * count + chips.index(week)) & 1)
        buys = [t & (1 - h) for t, h in zip(toggles, holding, strict=True)]
        sells = [t & h for t, h in zip(toggles, holding, strict=True)]
        moves.append((buys, sells, played))
        if not played:
            holding = [h ^ t for h, t in zip(holding, toggles, strict=True)]
    return moves


def _lot_prices(tables, fee):
    """Each week's sale price of each player under each lot, as the full lot reads it."""

    buy = [[int(p) for p in t.buy_price_tenths] for t in tables]
    return [
        [
            [int(supplied)]
            + [sell_price_tenths(buy[week][i], buy[w][i], sell_on_fee=fee) for w in range(week)]
            for i, supplied in enumerate(tables[week].sell_price_tenths)
        ]
        for week in range(len(tables))
    ]


def _replayed(prices, moves):
    """Each week's proceeds under the full lot, replayed with numbers alone."""

    lots = [0] * len(prices[0])
    totals = []
    for week, (buys, sells, played) in enumerate(moves):
        totals.append(sum(sells[i] * prices[week][i][lot] for i, lot in enumerate(lots)))
        lots = [week + 1 if b and not played else lot for b, lot in zip(buys, lots, strict=True)]
    return totals


def _accepted(tables, fee, known, free_hits, sequences):
    """Whether the reduced encoding accepts every sequence at its replayed proceeds.

    Each sequence gets its own copy of one fresh `AcquisitionSales` on moves fixed in
    advance, all in one model, so a single refused sequence makes it infeasible.
    """

    model = cp_model.CpModel()
    count = len(tables[0])
    prices = _lot_prices(tables, fee)
    fresh = AcquisitionSales(tables, fee, held=known, free_hit_possible=bool(free_hits))
    for moves in sequences:
        sales = copy.deepcopy(fresh)
        paid = _replayed(prices, moves)
        for week, (buys, sells, played) in enumerate(moves):
            fixed = []
            for value in (*buys, *sells):
                literal = model.new_bool_var(f"move_{week}_{len(fixed)}")
                model.add(literal == value)
                fixed.append(literal)
            free_hit = None
            if week in free_hits:
                free_hit = model.new_bool_var(f"free_hit_{week}")
                model.add(free_hit == played)
            proceeds = sales.add_week(model, week, fixed[:count], fixed[count:], free_hit)
            model.add(proceeds == paid[week])
    solver = cp_model.CpSolver()
    solver.parameters.num_workers = 1
    return solver.solve(model) == cp_model.OPTIMAL


def test_every_legal_sequence_of_moves_is_accepted_at_its_replayed_proceeds():
    whole = Counter()
    for seed in range(160):
        tables, fee, held, known, free_hits = _scenario(seed)
        bits = len(held) * len(tables) + len(free_hits)
        # Every sequence of a horizon with at most 64, else 16 seeded ones.
        names = range(2**bits) if bits <= 6 else random.Random(seed).sample(range(2**bits), 16)
        whole[bits <= 6] += 1
        sequences = [_sequence(held, len(tables), free_hits, n) for n in names]
        assert _accepted(tables, fee, known, free_hits, sequences), (
            seed,
            next(s for s in sequences if not _accepted(tables, fee, known, free_hits, [s])),
        )
    # Both halves run: whole small horizons and samples of larger ones.
    assert min(whole[True], whole[False]) >= 40, whole


POSITIONS = ("GK", "DEF", "MID", "FWD")
KINDS = ("no_chip", "wildcard", "freehit", "moving")


def _instance(seed):
    """A small horizon: frozen prices unless ``moving``, a Free Hit only in ``freehit``."""

    rng = random.Random(seed)
    kind = KINDS[seed % len(KINDS)]
    weeks = rng.randint(2, 4)
    fee = rng.choice((0.0, 0.25, 0.5, 1.0))
    rows = []
    initial = []
    extra = rng.choice(POSITIONS[1:])
    for position in POSITIONS:
        for number in range(3 if position == extra else 2):
            player_id = f"{position}_{number}"
            if number == 0:
                initial.append(player_id)
            path = _path(rng, weeks, number == 0, fee, kind == "moving")
            for week, (price, supplied) in enumerate(path, 1):
                rows.append(
                    {
                        "gameweek": week,
                        "player_id": player_id,
                        "name": f"Player {player_id}",
                        "team_id": f"T_{player_id}",
                        "position": position,
                        "buy_price_tenths": price,
                        "sell_price_tenths": supplied,
                        "expected_points": round(rng.uniform(0.0, 9.0), 2),
                    }
                )
    available: dict[str, frozenset[int]] = {}
    if kind == "wildcard" or (kind == "moving" and rng.random() < 0.3):
        available["wildcard"] = frozenset({rng.randint(1, weeks)})
    if kind == "freehit" or (kind == "moving" and rng.random() < 0.3):
        available["freehit"] = frozenset({rng.randint(1, weeks)})
    settings = TransferPlanningConfig(
        acquisition_sell_on_fee=fee,
        transfer_hit_cost_points=rng.choice((0.0, 1.0, 4.0)),
    )
    state = InitialSquadState(tuple(initial), rng.randint(0, 8), rng.randint(1, 2))
    expected = "original_held" if kind in {"no_chip", "wildcard"} else "acquisition_week"
    return (
        PlanningHorizon(pd.DataFrame.from_records(rows)),
        state,
        settings,
        ChipAvailability(available=available),
        expected,
    )


def _solved(monkeypatch, sales, horizon, state, config, settings, chips, **kwargs):
    monkeypatch.setattr(planning_optimizer, "AcquisitionSales", sales)
    result = optimize_transfer_plan(horizon, state, config, settings, chips=chips, **kwargs)
    assert result.solver_status.name == "OPTIMAL"
    return result


def _spy(built):
    def build(*args, **kwargs):
        built.append(AcquisitionSales(*args, **kwargs))
        return built[-1]

    return build


@pytest.mark.parametrize("seed", range(12))
def test_small_horizons_solve_to_the_same_value_under_both_encodings(
    small_config, monkeypatch, seed
):
    horizon, state, settings, chips, expected = _instance(seed)
    solve = (horizon, state, replace(small_config, solver_time_limit_seconds=30), settings, chips)
    built = []
    reduced = _solved(monkeypatch, _spy(built), *solve)
    reference = _solved(monkeypatch, _Reference, *solve)
    assert built[0].encoding == expected
    value = reference.diagnostics["scaled_model_objective_value"]
    assert reduced.diagnostics["scaled_model_objective_value"] == value
    assert reduced.objective_value == pytest.approx(reference.objective_value)
    # One value is not one plan. The tie-break's rank sums can tie, and which tied plan
    # comes back depends on the search, which the encoding changes. So each plan's squads,
    # fixed, must reach the same value under the other encoding, whether the plans match
    # or not.
    for sales, other in ((_spy([]), reference), (_Reference, reduced)):
        squads = {week.gameweek: tuple(week.selected_squad.player_id) for week in other.weeks}
        fixed = _solved(monkeypatch, sales, *solve, fixed_week_squads=squads)
        assert fixed.diagnostics["scaled_model_objective_value"] == value


FROZEN = _tables([[60, 50, 70]] * 3, [[52, 50, 66]] * 3)
MOVING = _tables([[60, 50, 70], [61, 50, 70], [61, 50, 70]], [[52, 50, 66]] * 3)
# A price that moves only in the last week: a frozen check that stops early would miss it.
LATE = _tables([[60, 50, 70], [60, 50, 70], [61, 50, 70]], [[52, 50, 66]] * 3)


@pytest.mark.parametrize(
    ("tables", "held", "free_hit_possible", "expected"),
    [
        (FROZEN, [True, True, False], False, "original_held"),
        (FROZEN, [True, True, False], True, "acquisition_week"),
        (FROZEN, None, False, "acquisition_week"),
        (MOVING, [True, True, False], False, "acquisition_week"),
        (LATE, [True, True, False], False, "acquisition_week"),
        (FROZEN[:1], [True, True, False], False, "original_held"),
    ],
)
def test_the_boolean_encoding_needs_frozen_prices_no_free_hit_and_the_held_squad(
    tables, held, free_hit_possible, expected
):
    sales = AcquisitionSales(tables, 0.5, held=held, free_hit_possible=free_hit_possible)
    assert sales.encoding == expected


def test_an_unknown_free_hit_keeps_the_acquisition_week_encoding():
    assert AcquisitionSales(FROZEN, 0.5, held=[True, True, False]).encoding == "acquisition_week"


def test_held_must_name_every_player():
    with pytest.raises(ValueError, match="held"):
        AcquisitionSales(FROZEN, 0.5, held=[True], free_hit_possible=False)


def _names(tables, fee, **kwargs):
    """The variables one complete horizon declares, the moves themselves left out."""

    model = cp_model.CpModel()
    sales = AcquisitionSales(tables, fee, **kwargs)
    count = len(tables[0])
    free_hit = model.new_bool_var("free_hit") if kwargs.get("free_hit_possible", True) else None
    for week in range(len(tables)):
        buys = [model.new_bool_var(f"buy_{week}_{i}") for i in range(count)]
        sells = [model.new_bool_var(f"sell_{week}_{i}") for i in range(count)]
        sales.add_week(model, week, buys, sells, free_hit)
    moves = ("buy_", "sell_", "free_hit")
    return {v.name for v in model.proto.variables if not v.name.startswith(moves)}


def test_a_player_no_lot_can_reprice_carries_no_lot():
    # Player 0 rises from an unknown purchase, so a later lot sells for more than the
    # supplied price. Player 1 never moves and player 2 only falls: every lot of theirs
    # sells at the week's price, so neither carries one.
    tables = _tables(
        [[60, 50, 50], [62, 50, 48], [64, 50, 46]],
        [[55, 50, 50], [56, 50, 48], [57, 50, 46]],
    )
    assert _names(tables, 0.5) == {
        "acquisition_week_0_0",
        "acquisition_week_1_0",
        "lot_sale_price_1_0",
        "lot_proceeds_1_0",
        "lot_sale_price_2_0",
        "lot_proceeds_2_0",
    }


def test_frozen_prices_give_only_the_held_risen_player_booleans():
    # Player 0 is held and sells below its price, player 1 sells at it, and player 2
    # carries a supplied price below its own but is not held, so no sale ever pays it.
    names = _names(FROZEN, 0.5, held=[True, True, False], free_hit_possible=False)
    assert names == {
        "original_held_1_0",
        "sold_original_1_0",
        "original_held_2_0",
        "sold_original_2_0",
    }


def test_a_free_hit_is_refused_by_sales_declared_without_one():
    model = cp_model.CpModel()
    sales = AcquisitionSales(FROZEN, 0.5, held=[True, True, False], free_hit_possible=False)
    moves = [model.new_bool_var(f"move_{i}") for i in range(3)]
    with pytest.raises(ValueError, match="Free Hit"):
        sales.add_week(model, 0, moves, moves, model.new_bool_var("free_hit"))


@pytest.mark.parametrize("fee", [0.0, 0.005, 0.01, 0.25, 1 / 3, 0.5, 0.995, 1.0])
def test_a_copy_bought_at_the_frozen_price_sells_at_it(fee):
    assert all(sell_price_tenths(p, p, sell_on_fee=fee) == p for p in range(400))


@pytest.mark.parametrize(
    ("available", "expected"),
    [
        ({}, "original_held"),
        ({"wildcard": {2}}, "original_held"),
        ({"freehit": {9}}, "original_held"),
        ({"freehit": {2}}, "acquisition_week"),
        ({"wildcard": {1}, "freehit": {3}}, "acquisition_week"),
    ],
)
def test_the_optimizer_declares_a_free_hit_only_where_the_horizon_can_play_one(
    known_optimum_players, small_config, monkeypatch, available, expected
):
    built = []
    monkeypatch.setattr(planning_optimizer, "AcquisitionSales", _spy(built))
    frames = [
        known_optimum_players.assign(gameweek=w, buy_price_tenths=50, sell_price_tenths=50)
        for w in (1, 2, 3)
    ]
    result = optimize_transfer_plan(
        PlanningHorizon(pd.concat(frames, ignore_index=True)),
        InitialSquadState(("GK_A", "DEF_A", "MID_A", "FWD_A"), 20, 1),
        replace(small_config, solver_time_limit_seconds=30),
        TransferPlanningConfig(acquisition_sell_on_fee=0.5),
        chips=ChipAvailability(available=available),
    )
    assert result.solver_status.name == "OPTIMAL"
    assert [sales.encoding for sales in built] == [expected]
