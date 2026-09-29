"""Shortlisting preserves feasible holdings and complete forecast identities."""

import pandas as pd
import pytest

from squadopt.experiments.planning_shortlist import shortlist_horizon
from squadopt.planning import InitialSquadState, PlanningHorizon


def example():
    return PlanningHorizon(
        pd.DataFrame(
            [
                dict(
                    gameweek=w,
                    player_id=i,
                    name=str(i),
                    team_id=i,
                    position="MID",
                    buy_price_tenths=40 + i,
                    sell_price_tenths=40 + i,
                    expected_points=float(20 if i == (3 if w == 1 else 4) else 1),
                )
                for w in (1, 2)
                for i in range(1, 7)
            ]
        )
    )


def test_union_keeps_later_opportunities_cheap_holdings_and_required():
    horizon = example()
    result = shortlist_horizon(
        horizon,
        InitialSquadState((5,), 0, 1),
        required_players=(6,),
        top_per_position=1,
        cheap_per_position=1,
    )
    assert set(result.table.player_id) == {1, 3, 4, 5, 6}
    pd.testing.assert_frame_equal(result.table, horizon.table.loc[horizon.table.player_id.ne(2)])
    assert len(result.table) == 10


def test_row_order_cannot_change_tie_break_or_selected_horizon():
    horizon = example()
    initial = InitialSquadState((5,), 0, 1)
    shuffled = PlanningHorizon(horizon.table.sample(frac=1, random_state=9))
    assert shortlist_horizon(horizon, initial).horizon_fingerprint == (
        shortlist_horizon(shuffled, initial).horizon_fingerprint
    )


@pytest.mark.parametrize("count", [0, -1, True, 1.5])
def test_invalid_counts_refused(count):
    with pytest.raises(ValueError, match="positive integers"):
        shortlist_horizon(example(), InitialSquadState((1,), 0, 1), top_per_position=count)


def test_unknown_required_or_held_id_is_not_silently_lost():
    with pytest.raises(ValueError, match="must exist"):
        shortlist_horizon(example(), InitialSquadState((1,), 0, 1), required_players=(99,))
