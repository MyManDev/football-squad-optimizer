"""Explicit future evidence can change a short-window decision without fictitious points."""

from dataclasses import replace

import pandas as pd
import pytest

from squadopt.planning import InitialSquadState, PlanningHorizon
from squadopt.planning.lookahead import optimize_with_lookahead
from squadopt.planning.models import TransferPlanningConfig
from squadopt.planning.optimizer import optimize_transfer_plan
from squadopt.planning.recourse_chips import net_week_points


@pytest.mark.parametrize("window", [3, 5])
def test_tail_can_preserve_a_resource_valuable_after_the_window(
    known_optimum_players, small_config, window
):
    players = known_optimum_players.copy()
    parts = []
    for w in range(1, window + 2):
        part = players.assign(gameweek=w, buy_price_tenths=50, sell_price_tenths=50)
        part.loc[part.player_id.eq("FWD_A"), "expected_points"] = 10.0
        part.loc[part.player_id.eq("FWD_B"), "expected_points"] = 10.1 if w <= window else 0.0
        parts.append(part)
    full = PlanningHorizon(pd.concat(parts, ignore_index=True))
    short = PlanningHorizon(full.table.loc[full.table.gameweek.le(window)])
    initial = InitialSquadState(("GK_A", "DEF_A", "MID_A", "FWD_A"), 0, 1)
    config = replace(small_config, bench_weight=0, solver_time_limit_seconds=30)
    transfer = TransferPlanningConfig(free_transfer_accrual=0)
    myopic = optimize_transfer_plan(short, initial, config, transfer, linearization_level=2)
    lookahead = optimize_with_lookahead(full, initial, config, window=window, transfer=transfer)
    assert "FWD_B" in set(myopic.weeks[0].transfers_in.player_id)
    assert lookahead.window[0].transfer_count == 0
    assert lookahead.window[-1].free_transfers_for_next_gameweek == 1
    assert lookahead.window_net_points < sum(net_week_points(w) for w in myopic.weeks)
    assert lookahead.window_net_points + lookahead.tail_net_points == pytest.approx(
        sum(net_week_points(w) for w in lookahead.plan.weeks)
    )
    assert lookahead.decision_weeks == tuple(range(1, window + 1))
    with pytest.raises(ValueError, match="beyond"):
        optimize_with_lookahead(short, initial, config, window=window)
    with pytest.raises(ValueError, match="terminal"):
        optimize_with_lookahead(
            full,
            initial,
            config,
            window=window,
            transfer=TransferPlanningConfig(banked_transfer_value_points=1),
        )


@pytest.mark.parametrize("window", [3, 5])
def test_normal_weekly_ft_accrual_preserves_resources_for_a_fixture_turn(
    known_optimum_players, small_config, window
):
    # Five players make the exact resource tradeoff enumerable. FT accrual/cap/hits
    # retain the normal rules; only the roster and authored point table are small.
    parts = []
    for week in range(1, window + 2):
        frame = known_optimum_players.assign(
            gameweek=week,
            buy_price_tenths=50,
            sell_price_tenths=50,
            expected_points=0.0,
        )
        frame = pd.concat(
            [
                frame,
                frame.iloc[[0]].assign(player_id="GK_C", name="Bench keeper", team_id="T9"),
            ],
            ignore_index=True,
        )
        frame.loc[frame.player_id.isin(["GK_A", "DEF_A", "MID_A"]), "expected_points"] = 5.0
        frame.loc[frame.player_id.eq("FWD_A"), "expected_points"] = 10.0
        frame.loc[frame.player_id.eq("FWD_B"), "expected_points"] = 10.1 if week % 2 else 0.0
        if week > window:
            frame["expected_points"] = 0.0
            frame.loc[
                frame.player_id.isin(["GK_B", "DEF_B", "MID_B", "FWD_A"]),
                "expected_points",
            ] = 25.0
        parts.append(frame)
    forecast = PlanningHorizon(pd.concat(parts, ignore_index=True))
    short = PlanningHorizon(forecast.table.loc[forecast.table.gameweek.le(window)])
    initial = InitialSquadState(("GK_A", "GK_C", "DEF_A", "MID_A", "FWD_A"), 0, 1)
    config = replace(
        small_config,
        budget_tenths=250,
        squad_size=5,
        squad_position_limits={"GK": 2, "DEF": 1, "MID": 1, "FWD": 1},
        starting_size=4,
        bench_weight=0,
        solver_time_limit_seconds=30,
    )
    myopic = optimize_transfer_plan(short, initial, config, linearization_level=2)
    extended = optimize_with_lookahead(forecast, initial, config, window=window)
    last = myopic.weeks[-1]
    continuation = optimize_transfer_plan(
        PlanningHorizon(forecast.table.loc[forecast.table.gameweek.gt(window)]),
        InitialSquadState(
            tuple(last.selected_squad.player_id),
            last.bank_after_tenths,
            last.free_transfers_for_next_gameweek,
        ),
        config,
        linearization_level=2,
    )
    assert myopic.has_solution and extended.plan.has_solution and continuation.has_solution
    assert all(p.solver_status.name == "OPTIMAL" for p in (myopic, extended.plan, continuation))
    assert sum(w.transfer_count for w in myopic.weeks) == window
    assert sum(w.transfer_count for w in extended.window) < window
    assert (
        extended.window[-1].free_transfers_for_next_gameweek > last.free_transfers_for_next_gameweek
    )
    assert extended.plan.total_transfer_hit_points == 0
    assert continuation.total_transfer_hit_points > 0
    assert sum(net_week_points(w) for w in extended.plan.weeks) > sum(
        net_week_points(w) for w in (*myopic.weeks, *continuation.weeks)
    )
