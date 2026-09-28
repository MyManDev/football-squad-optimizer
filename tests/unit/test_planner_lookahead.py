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
