"""Independent Bellman oracle on a complete small legal-squad menu."""

from dataclasses import replace
from functools import lru_cache
from itertools import product

import pandas as pd
import pytest

from squadopt.planning import InitialSquadState, PlanningHorizon
from squadopt.planning.recourse import ObservationNode, optimize_observed_recourse


@pytest.mark.parametrize("window", [3, 5])
def test_complete_legal_menu_matches_independent_bellman_oracle(
    known_optimum_players, small_config, window
):
    players = known_optimum_players
    positions = ("GK", "DEF", "MID", "FWD")
    actions = tuple(
        product(*(tuple(players.loc[players.position.eq(p), "player_id"]) for p in positions))
    )
    # Each action has exactly one player per position, costs 200 and respects
    # the four-player team cap. Prices are fixed so the bank remains zero.
    base = PlanningHorizon(
        pd.concat(
            [
                players.assign(gameweek=w, buy_price_tenths=50, sell_price_tenths=50)
                for w in range(1, window + 1)
            ],
            ignore_index=True,
        )
    )
    nodes = []
    for striker, probability in (("FWD_A", 0.4), ("FWD_B", 0.6)):
        future = base.table.loc[base.table.gameweek.gt(1)].copy()
        future.loc[future.position.eq("FWD"), "expected_points"] = 0.0
        future.loc[future.player_id.eq(striker), "expected_points"] = 25.0
        nodes.append(ObservationNode(striker, probability, PlanningHorizon(future)))
    initial = InitialSquadState(("GK_A", "DEF_B", "MID_B", "FWD_A"), 0, 0)
    config = replace(small_config, bench_weight=0, solver_time_limit_seconds=30)

    def reward(points, action):
        # XI is GK + FWD + better DEF/MID; captain doubles the best starter.
        lineup = (points[action[0]], points[action[3]], max(points[action[1]], points[action[2]]))
        return sum(lineup) + max(lineup)

    @lru_cache(None)
    def value(node_index, week, held, free):
        if week > window:
            return 0.0
        table = nodes[node_index].horizon.table
        points = dict(
            table.loc[table.gameweek.eq(week), ["player_id", "expected_points"]].itertuples(
                index=False, name=None
            )
        )
        candidates = []
        for action in actions:
            transfers = len(set(action) - set(held))
            charge = 4 * max(0, transfers - free)
            next_free = min(5, max(0, free - transfers) + 1)
            candidates.append(
                reward(points, action) - charge + value(node_index, week + 1, action, next_free)
            )
        return max(candidates)

    today = dict(players[["player_id", "expected_points"]].itertuples(index=False, name=None))
    oracle = {}
    for action in actions:
        transfers = len(set(action) - set(initial.squad_player_ids))
        oracle[frozenset(action)] = (
            reward(today, action)
            - 4 * transfers
            + sum(node.probability * value(i, 2, action, 1) for i, node in enumerate(nodes))
        )
    result = optimize_observed_recourse(
        base, initial, nodes, config, candidate_count=16, value_extra_free_transfer=False
    )
    assert len(result.candidates) == len(actions) == 16
    for candidate in result.candidates:
        key = frozenset(candidate.first_week.selected_squad.player_id)
        assert candidate.expected_net_points == pytest.approx(oracle[key])
    assert result.candidates[result.chosen_index].expected_net_points == pytest.approx(
        max(oracle.values())
    )
    assert result.selection_status == "OPTIMAL_RESTRICTED_MENU"
