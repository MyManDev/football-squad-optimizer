"""Segment boundaries must not create money, transfers, chip rights or global proof."""

from dataclasses import replace
from itertools import product

import pandas as pd
import pytest
from tests.unit.test_planner_incumbent import problem

import squadopt.planning.segmented as module
from squadopt.contracts.preferences import DecisionPreferences
from squadopt.optimization import SolverStatus
from squadopt.planning import (
    ChipAvailability,
    ChipUseWindow,
    InitialSquadState,
    PlanningHorizon,
    TransferPlanningConfig,
    TransferPlanningValidationError,
    optimize_transfer_plan,
)
from squadopt.planning.segmented import plan_in_segments


@pytest.mark.parametrize("fee", [None, 0.0, 0.5, 1.0])
@pytest.mark.parametrize("lengths", [(1, 1, 1, 1, 1), (3, 2)])
@pytest.mark.parametrize("chip", [None, "freehit", "wildcard", "3xc", "bboost"])
def test_full_model_certifies_segmented_state(
    known_optimum_players, small_config, fee, lengths, chip
):
    horizon, initial, config = problem(known_optimum_players, small_config, 5)
    table = horizon.table.copy()
    table.loc[table.player_id.eq("FWD_A"), "buy_price_tenths"] = [50, 52, 55, 53, 50]
    table.loc[table.player_id.eq("FWD_B"), "buy_price_tenths"] = [50, 51, 54, 52, 50]
    table["sell_price_tenths"] = table.buy_price_tenths
    horizon = PlanningHorizon(table)
    initial = replace(initial, bank_tenths=20)
    rights = (
        ChipAvailability()
        if chip is None
        else ChipAvailability(available={chip: frozenset({2})}, forced={2: chip})
    )
    settings = TransferPlanningConfig(acquisition_sell_on_fee=fee, horizon_discount_factor=0.9)
    proposal = plan_in_segments(
        horizon, initial, config, segment_lengths=lengths, transfer=settings, chips=rights
    )
    assert proposal.solver_status is SolverStatus.FEASIBLE
    assert proposal.diagnostics["best_objective_bound"] is None
    # The original unsliced model independently checks every supplied decision/resource.
    checked = optimize_transfer_plan(
        horizon,
        initial,
        config,
        settings,
        chips=rights,
        incumbent_plan=proposal,
        protect_incumbent=True,
    )
    assert checked.has_solution
    assert checked.diagnostics["incumbent_hint"]["claimed_objective_used"] is False
    assert proposal.objective_value == pytest.approx(
        sum(
            0.9**index
            * (
                w.projected_score
                + (w.projected_bench_points if w.chip == "bboost" else 0)
                - w.paid_transfer_count * settings.transfer_hit_cost_points
            )
            for index, w in enumerate(proposal.weeks)
        )
    )
    assert proposal.diagnostics["deterministic_time_used"] <= 5.005


def test_acquisition_lots_survive_sale_repurchase_and_freehit(
    known_optimum_players, small_config, monkeypatch
):
    horizon, initial, config = problem(known_optimum_players, small_config, 5)
    table = horizon.table.copy()
    for player, prices in {"FWD_A": [50, 55, 60, 62, 64], "FWD_B": [50, 52, 54, 56, 58]}.items():
        table.loc[table.player_id.eq(player), "buy_price_tenths"] = prices
    table["sell_price_tenths"] = table.buy_price_tenths
    horizon = PlanningHorizon(table)
    initial = replace(initial, bank_tenths=40)
    settings = TransferPlanningConfig(acquisition_sell_on_fee=0.5)
    chips = ChipAvailability({"freehit": frozenset({2})}, {2: "freehit"})
    wanted = {1: "FWD_B", 2: "FWD_A", 3: "FWD_A", 4: "FWD_B", 5: "FWD_A"}
    actual = module.optimize_transfer_plan

    def prescribed(horizon, *args, **kwargs):
        fixed = {w: ("GK_A", "DEF_A", "MID_A", wanted[w]) for w in horizon.gameweeks}
        return actual(horizon, *args, fixed_week_squads=fixed, **kwargs)

    monkeypatch.setattr(module, "optimize_transfer_plan", prescribed)
    proposal = plan_in_segments(
        horizon, initial, config, segment_lengths=(1,) * 5, transfer=settings, chips=chips
    )
    weeks = proposal.weeks
    assert weeks[1].transfers_out.iloc[0].sell_price_tenths == 51
    assert weeks[2].transfers_out.iloc[0].sell_price_tenths == 52  # FH restores B's old lot.
    assert weeks[2].bank_before_tenths == weeks[0].bank_after_tenths
    assert weeks[3].transfers_out.iloc[0].sell_price_tenths == 61  # A repurchased at 60.
    assert weeks[4].transfers_out.iloc[0].sell_price_tenths == 57  # B repurchased at 56.
    checked = optimize_transfer_plan(
        horizon,
        initial,
        config,
        settings,
        chips=chips,
        incumbent_plan=proposal,
        protect_incumbent=True,
    )
    assert checked.has_solution


@pytest.mark.parametrize("window", [3, 5])
@pytest.mark.parametrize("free_transfers", [0, 5])
def test_literal_two_transfer_lots_and_freehit_resource_table(
    known_optimum_players, small_config, monkeypatch, window, free_transfers
):
    horizon, initial, config = problem(known_optimum_players, small_config, window)
    table = horizon.table.loc[
        horizon.table.player_id.isin(("GK_A", "DEF_A", "MID_A", "MID_B", "FWD_A", "FWD_B"))
    ].copy()
    market = {
        "MID_A": (50, 45, 47, 52, 50),
        "FWD_A": (50, 48, 50, 47, 50),
        "MID_B": (46, 49, 51, 50, 55),
        "FWD_B": (51, 49, 54, 48, 47),
    }
    supplied_sales = {
        "MID_A": (48, 44, 46, 45, 48),
        "FWD_A": (49, 47, 49, 46, 49),
        "MID_B": market["MID_B"],
        "FWD_B": market["FWD_B"],
    }
    for player, prices in market.items():
        mask = table.player_id.eq(player)
        table.loc[mask, "buy_price_tenths"] = prices[:window]
        table.loc[mask, "sell_price_tenths"] = supplied_sales[player][:window]
    horizon = PlanningHorizon(table)
    initial = replace(initial, bank_tenths=0, free_transfers=free_transfers)
    settings = TransferPlanningConfig(acquisition_sell_on_fee=0.5)
    rights = ChipAvailability({"freehit": frozenset({2})}, {2: "freehit"})
    incoming = ("B", "A", "A", "B", "A")
    outgoing = ("A", "B", "B", "A", "B")
    squads = {
        week: ("GK_A", "DEF_A", f"MID_{suffix}", f"FWD_{suffix}")
        for week, suffix in enumerate(incoming[:window], 1)
    }
    original = module.optimize_transfer_plan

    def prescribed(part_horizon, *args, **kwargs):
        fixed = {week: squads[week] for week in part_horizon.gameweeks}
        return original(part_horizon, *args, fixed_week_squads=fixed, **kwargs)

    monkeypatch.setattr(module, "optimize_transfer_plan", prescribed)
    seed = plan_in_segments(
        horizon, initial, config, segment_lengths=(1,) * window, transfer=settings, chips=rights
    )
    # Pin the same squads during certification: a later improving search is not the
    # literal path under audit. The unsliced model still checks all resource states.
    certified = optimize_transfer_plan(
        horizon,
        initial,
        config,
        settings,
        chips=rights,
        fixed_week_squads=squads,
        incumbent_plan=seed,
        protect_incumbent=True,
    )
    assert certified.diagnostics["incumbent_hint"]["claimed_objective_used"] is False

    # Independent MID/FWD literals, never read from a solver or production sale helper.
    # GW1 uses original supplied sale prices. FH2 restores B's 46/51 purchase lots
    # and bank 0, despite its temporary A squad costing 45/48 and leaving bank 3.
    # A is then acquired at 47/50; B's later repurchase resets its basis to 50/48.
    sales = ((48, 49), (47, 49), (48, 52), (49, 47), (52, 47))
    buys = ((46, 51), (45, 48), (47, 50), (50, 48), (50, 50))
    bank_before = (0, 0, 0, 3, 1)
    bank_after = (0, 3, 3, 1, 0)
    ft_before, ft_unused, ft_next, paid, hits = {
        0: (
            (0, 1, 1, 1, 1),
            (0, 1, 0, 0, 0),
            (1, 1, 1, 1, 1),
            (2, 0, 1, 1, 1),
            (8, 0, 4, 4, 4),
        ),
        5: (
            (5, 4, 4, 3, 2),
            (3, 4, 2, 1, 0),
            (4, 4, 3, 2, 1),
            (0, 0, 0, 0, 0),
            (0, 0, 0, 0, 0),
        ),
    }[free_transfers]
    for plan in (seed, certified):
        assert plan.has_solution
        assert tuple(week.gameweek for week in plan.weeks) == tuple(range(1, window + 1))
        assert dict(plan.chips_played) == {2: "freehit"}
        assert plan.diagnostics["deterministic_time_used"] <= 5.005  # Each has its own 5-unit cap.
        assert plan.total_transfer_hit_points == sum(hits[:window])
        for index, week in enumerate(plan.weeks):
            assert set(week.selected_squad.player_id) == set(squads[week.gameweek])
            assert week.transfers_out.set_index("player_id").sell_price_tenths.to_dict() == {
                f"MID_{outgoing[index]}": sales[index][0],
                f"FWD_{outgoing[index]}": sales[index][1],
            }
            assert week.transfers_in.set_index("player_id").buy_price_tenths.to_dict() == {
                f"MID_{incoming[index]}": buys[index][0],
                f"FWD_{incoming[index]}": buys[index][1],
            }
            assert (week.bank_before_tenths, week.bank_after_tenths) == (
                bank_before[index],
                bank_after[index],
            )
            assert (week.free_transfers_before, week.free_transfers_unused) == (
                ft_before[index],
                ft_unused[index],
            )
            assert week.free_transfers_for_next_gameweek == ft_next[index]
            assert week.transfer_count == 2
            assert week.paid_transfer_count == paid[index]
            assert week.transfer_hit_points == hits[index]


def test_chip_periods_renew_without_recreating_used_right(known_optimum_players, small_config):
    args = problem(known_optimum_players, small_config, 5)
    rights = ChipAvailability(
        {"freehit": frozenset(range(1, 6))},
        {2: "freehit", 4: "freehit"},
        {"freehit": (ChipUseWindow(frozenset({1, 2})), ChipUseWindow(frozenset({3, 4, 5})))},
    )
    result = plan_in_segments(*args, segment_lengths=(1,) * 5, chips=rights)
    assert dict(result.chips_played) == {2: "freehit", 4: "freehit"}
    assert optimize_transfer_plan(*args, chips=rights, incumbent_plan=result).has_solution


@pytest.mark.parametrize(("forced_week", "lengths"), [(2, (1, 2)), (2, (1, 1, 1)), (3, (1, 1, 1))])
def test_renewed_freehit_reserves_only_the_week_before_forced_use(
    known_optimum_players, small_config, monkeypatch, forced_week, lengths
):
    horizon, initial, config = problem(known_optimum_players, small_config)
    table = horizon.table.loc[
        horizon.table.player_id.isin((*initial.squad_player_ids, "FWD_B"))
    ].copy()
    table.loc[table.player_id.eq("FWD_B"), "expected_points"] = 0
    table.loc[table.player_id.eq("FWD_B") & table.gameweek.eq(1), "expected_points"] = 30
    horizon = PlanningHorizon(table)
    initial = replace(initial, free_transfers=0)
    rights = ChipAvailability(
        {"freehit": frozenset({1, 2, 3})},
        {forced_week: "freehit"},
        {"freehit": (ChipUseWindow(frozenset({1})), ChipUseWindow(frozenset({2, 3})))},
    )
    actual = module.optimize_transfer_plan
    parts = []
    budgets = []

    def recorded(part_horizon, state, part_config, *args, **kwargs):
        budgets.append(part_config.solver_deterministic_time_limit)
        part = actual(part_horizon, state, part_config, *args, **kwargs)
        parts.append(part)
        return part

    monkeypatch.setattr(module, "optimize_transfer_plan", recorded)
    result = plan_in_segments(horizon, initial, config, segment_lengths=lengths, chips=rights)
    # FH in GW1 saves a strictly positive hit on the temporary high-scoring move.
    # Only the adjacent forced renewal makes that earlier use illegal.
    assert "FWD_B" in set(result.weeks[0].selected_squad.player_id)
    if forced_week == 2:
        assert dict(result.chips_played) == {2: "freehit"}
        assert result.weeks[0].paid_transfer_count == 1
    else:
        assert dict(result.chips_played) == {1: "freehit", 3: "freehit"}
        assert result.weeks[0].paid_transfer_count == 0
    assert tuple(w.gameweek for w in result.weeks) == (1, 2, 3)
    assert result.diagnostics["proof_scope"] == "segmented_feasible_only"
    assert sum(budgets) == pytest.approx(config.solver_deterministic_time_limit)
    assert result.diagnostics["deterministic_time_used"] == pytest.approx(
        sum(part.diagnostics["deterministic_time_used"] for part in parts)
    )
    assert result.diagnostics["deterministic_time_used"] <= 5.005
    # Full-horizon certification independently checks the original dated rights,
    # adjacency, restored permanent holdings, bank and free-transfer transitions.
    checked = optimize_transfer_plan(
        horizon, initial, config, chips=rights, incumbent_plan=result, protect_incumbent=True
    )
    assert checked.has_solution
    assert checked.diagnostics["incumbent_hint"]["claimed_objective_used"] is False
    assert checked.diagnostics["deterministic_time_used"] <= 5.005


@pytest.mark.parametrize("chip", ["wildcard", "3xc", "bboost"])
def test_other_renewed_chips_keep_the_date_before_their_forced_use(chip):
    rights = ChipAvailability(
        {chip: frozenset({1, 2, 3}), "freehit": frozenset({1})},
        {2: chip},
        {
            chip: (ChipUseWindow(frozenset({1})), ChipUseWindow(frozenset({2, 3}))),
            "freehit": (ChipUseWindow(frozenset({1})),),
        },
    )
    limited = module._segment_rights(rights, 1)
    assert limited.available == rights.available
    assert limited.use_windows == rights.use_windows
    assert limited.forced == rights.forced


def test_consecutive_forced_freehits_are_not_silently_unforced():
    rights = ChipAvailability(
        {"freehit": frozenset({1, 2, 3})},
        {1: "freehit", 2: "freehit"},
        {"freehit": (ChipUseWindow(frozenset({1})), ChipUseWindow(frozenset({2, 3})))},
    )
    with pytest.raises(TransferPlanningValidationError, match=r"Forced chip.*gameweek 1"):
        module._segment_rights(rights, 1)
    assert dict(rights.forced) == {1: "freehit", 2: "freehit"}


def test_preferences_and_integer_ids_survive_every_segment(known_optimum_players, small_config):
    horizon, initial, config = problem(known_optimum_players, small_config, 5)
    ids = {player: index + 1 for index, player in enumerate(horizon.table.player_id.unique())}
    table = horizon.table.copy()
    table.player_id = table.player_id.map(ids)
    horizon = PlanningHorizon(table)
    initial = InitialSquadState(tuple(ids[p] for p in initial.squad_player_ids))
    prefs = DecisionPreferences(
        keep_players=(ids["MID_A"],), avoid_players=(ids["FWD_B"],), no_hits=True, save_chips=True
    )
    rights = ChipAvailability({"wildcard": frozenset(range(1, 6))})
    result = plan_in_segments(
        horizon, initial, config, segment_lengths=(3, 2), preferences=prefs, chips=rights
    )
    for week in result.weeks:
        assert ids["MID_A"] in set(week.selected_squad.player_id)
        assert ids["FWD_B"] not in set(week.selected_squad.player_id)
        assert week.paid_transfer_count == 0 and week.chip is None
    assert optimize_transfer_plan(
        horizon, initial, config, chips=rights, preferences=prefs, incumbent_plan=result
    ).has_solution


@pytest.mark.parametrize("lengths", [(), (1, 1), (True, 2), (0, 3), (1.0, 2), (-1, 4)])
def test_invalid_partition_refused_before_solving(known_optimum_players, small_config, lengths):
    with pytest.raises(TransferPlanningValidationError, match="partition"):
        plan_in_segments(*problem(known_optimum_players, small_config), segment_lengths=lengths)


def test_no_hidden_budget_or_terminal_resets(known_optimum_players, small_config):
    horizon, initial, config = problem(known_optimum_players, small_config)
    with pytest.raises(TransferPlanningValidationError, match="explicit total"):
        plan_in_segments(
            horizon,
            initial,
            replace(config, solver_deterministic_time_limit=None),
            segment_lengths=(1, 2),
        )
    with pytest.raises(TransferPlanningValidationError, match="unpriced terminal"):
        plan_in_segments(
            horizon,
            initial,
            config,
            segment_lengths=(1, 2),
            transfer=TransferPlanningConfig(banked_transfer_value_points=1),
        )


def test_failed_part_does_not_return_partial_success(
    known_optimum_players, small_config, monkeypatch
):
    args = problem(known_optimum_players, small_config)
    original = module.optimize_transfer_plan
    calls = []

    def fail_second(*a, **kw):
        calls.append(a[0].gameweeks)
        result = original(*a, **kw)
        if len(calls) == 2:
            return replace(
                result,
                solver_status=SolverStatus.UNKNOWN,
                weeks=(),
                total_projected_score=None,
                total_projected_bench_points=None,
                total_transfer_hit_points=None,
                objective_value=None,
            )
        return result

    monkeypatch.setattr(module, "optimize_transfer_plan", fail_second)
    with pytest.raises(TransferPlanningValidationError, match=r"GW2.*UNKNOWN"):
        plan_in_segments(*args, segment_lengths=(1, 1, 1))
    assert calls == [(1,), (2,)]


def test_input_frames_are_not_modified(known_optimum_players, small_config):
    horizon, initial, config = problem(known_optimum_players, small_config)
    original = horizon.table.copy(deep=True)
    plan_in_segments(
        horizon,
        initial,
        config,
        segment_lengths=(1, 2),
        transfer=TransferPlanningConfig(acquisition_sell_on_fee=0.5),
    )
    pd.testing.assert_frame_equal(horizon.table, original)


def test_forced_future_right_is_not_spent_by_earlier_segment(known_optimum_players, small_config):
    args = problem(known_optimum_players, small_config, 5)
    rights = ChipAvailability({"3xc": frozenset(range(1, 6))}, {5: "3xc"})
    result = plan_in_segments(*args, segment_lengths=(1,) * 5, chips=rights)
    assert dict(result.chips_played) == {5: "3xc"}
    assert optimize_transfer_plan(*args, chips=rights, incumbent_plan=result).has_solution


@pytest.mark.parametrize("window", [3, 5])
@pytest.mark.parametrize("fee", [0.0, 0.5, 1.0])
def test_guarded_segment_seed_matches_exhaustive_small_problem(
    known_optimum_players, small_config, window, fee
):
    horizon, initial, config = problem(known_optimum_players, small_config, window)
    table = horizon.table.loc[
        horizon.table.player_id.isin(("GK_A", "DEF_A", "MID_A", "FWD_A", "FWD_B"))
    ].copy()
    a_points, b_points = [6, 2, 9, 1, 11], [2, 15, 1, 12, 1]
    a_prices, b_prices = [50, 53, 56, 52, 54], [50, 55, 58, 54, 59]
    for week in range(1, window + 1):
        for player, points, prices in (
            ("FWD_A", a_points, a_prices),
            ("FWD_B", b_points, b_prices),
        ):
            mask = table.gameweek.eq(week) & table.player_id.eq(player)
            table.loc[mask, "expected_points"] = points[week - 1]
            table.loc[mask, "buy_price_tenths"] = prices[week - 1]
            table.loc[mask, "sell_price_tenths"] = prices[week - 1]
    for player, value in (("GK_A", 7), ("DEF_A", 4), ("MID_A", 5)):
        table.loc[table.player_id.eq(player), "expected_points"] = value
    horizon = PlanningHorizon(table)
    initial = replace(initial, bank_tenths=10, free_transfers=0)
    settings = TransferPlanningConfig(acquisition_sell_on_fee=fee)
    possible = []
    for path in product((0, 1), repeat=window):
        current, purchase, bank, free, score = 0, None, 10, 0, 0
        for index, chosen in enumerate(path):
            count = int(chosen != current)
            if count:
                market = (a_prices, b_prices)[current][index]
                # Independent integer accounting, including unknown original basis.
                sale = (
                    market
                    if purchase is None or market <= purchase
                    else (purchase + int((market - purchase) * (1 - fee)))
                )
                purchase = (a_prices, b_prices)[chosen][index]
                bank += sale - purchase
            if bank < 0:
                break
            points = (a_points, b_points)[chosen][index]
            score += 12 + points + max(7, points) - 4 * max(0, count - free)
            free = min(5, max(0, free - count) + 1)
            current = chosen
        else:
            possible.append(score)
    seed = plan_in_segments(
        horizon, initial, config, segment_lengths=(1,) * window, transfer=settings
    )
    solved = optimize_transfer_plan(
        horizon, initial, config, settings, incumbent_plan=seed, protect_incumbent=True
    )
    assert solved.solver_status is SolverStatus.OPTIMAL
    assert solved.objective_value == max(possible)
    assert solved.objective_value >= seed.objective_value
