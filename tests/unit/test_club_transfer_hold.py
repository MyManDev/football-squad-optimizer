"""Real club moves may leave excess holdings until the next fantasy transfer."""

import pandas as pd
import pytest
from tests.unit.test_transfer_planning import _horizon_table

from squadopt.contracts.preferences import DecisionPreferences, FrozenPlanWeek, WeekRules
from squadopt.optimization import OptimizationConfig, SolverStatus
from squadopt.planning import ChipAvailability, InitialSquadState, PlanningHorizon
from squadopt.planning.optimizer import optimize_transfer_plan


def _case(*, two_excess_clubs=False):
    positions = ("GK", "DEF", "MID", "FWD")
    players = pd.DataFrame.from_records(
        [
            {
                "player_id": index * 4 + offset + 1,
                "name": f"{position} {offset}",
                "team_id": "Excess"
                if offset == 0
                else "OtherExcess"
                if two_excess_clubs and offset == 1
                else f"Club {index}-{offset}",
                "position": position,
                "price_tenths": 50,
                "expected_points": 10.0 if offset < 2 else 1.0,
            }
            for index, position in enumerate(positions)
            for offset in range(4)
        ]
    )
    initial = InitialSquadState((1, 2, 5, 6, 9, 10, 13, 14), 100, 3)
    config = OptimizationConfig(
        budget_tenths=400,
        squad_size=8,
        squad_position_limits=dict.fromkeys(positions, 2),
        starting_size=5,
        starting_position_min={"GK": 1, "DEF": 0, "MID": 0, "FWD": 1},
        starting_position_max={"GK": 1, "DEF": 2, "MID": 2, "FWD": 2},
        max_players_per_team=3,
    )
    return PlanningHorizon(_horizon_table(players, (1, 2, 3))), initial, config


@pytest.mark.parametrize("mode", ["ordinary", "hold", "frozen"])
def test_excess_held_club_can_roll_every_week(mode):
    horizon, initial, config = _case()
    preferences = DecisionPreferences(
        hold_transfers=mode == "hold",
        frozen_weeks=tuple(FrozenPlanWeek(week, (), (), None) for week in (1, 2, 3))
        if mode == "frozen"
        else (),
    )
    result = optimize_transfer_plan(horizon, initial, config, preferences=preferences)
    assert result.solver_status is SolverStatus.OPTIMAL
    assert [week.transfer_count for week in result.weeks] == [0, 0, 0]
    assert all(
        set(week.selected_squad.player_id) == set(initial.squad_player_ids) for week in result.weeks
    )


@pytest.mark.parametrize("corrective", [False, True])
def test_next_transfer_restores_the_cap_even_when_that_transfer_is_free(corrective):
    horizon, initial, config = _case()
    next_rules = (
        DecisionPreferences(buy_players=(7,), avoid_players=(5,))
        if corrective
        else DecisionPreferences(buy_players=(3,), keep_players=(1, 5, 9, 13))
    )
    preferences = DecisionPreferences(
        week_rules=(
            WeekRules(1, DecisionPreferences(hold_transfers=True)),
            WeekRules(2, next_rules),
        )
    )
    result = optimize_transfer_plan(horizon, initial, config, preferences=preferences)
    assert result.solver_status is (SolverStatus.OPTIMAL if corrective else SolverStatus.INFEASIBLE)
    if corrective:
        assert result.weeks[0].transfer_count == 0
        assert result.weeks[1].transfer_count > 0
        assert result.weeks[1].paid_transfer_count == 0
        assert result.weeks[1].selected_squad.groupby("team_id").size().max() <= 3


@pytest.mark.parametrize("chip", ["freehit", "wildcard"])
def test_chip_transfers_restore_the_cap_and_free_hit_restores_the_original_holdings(chip):
    horizon, initial, config = _case()
    preferences = DecisionPreferences(
        week_rules=(
            WeekRules(1, DecisionPreferences(hold_transfers=True)),
            WeekRules(2, DecisionPreferences(buy_players=(3,))),
            WeekRules(3, DecisionPreferences(hold_transfers=True)),
        )
    )
    result = optimize_transfer_plan(
        horizon,
        initial,
        config,
        preferences=preferences,
        chips=ChipAvailability({chip: {2}}, forced={2: chip}),
    )
    assert result.solver_status is SolverStatus.OPTIMAL
    assert result.weeks[0].transfer_count == result.weeks[2].transfer_count == 0
    assert result.weeks[1].transfer_count > 0
    assert result.weeks[1].paid_transfer_count == 0
    assert result.weeks[1].selected_squad.groupby("team_id").size().max() <= 3
    last_ids = set(result.weeks[2].selected_squad.player_id)
    assert (last_ids == set(initial.squad_player_ids)) is (chip == "freehit")


def test_one_transfer_must_fix_every_excess_club():
    horizon, initial, config = _case(two_excess_clubs=True)
    held = optimize_transfer_plan(
        horizon, initial, config, preferences=DecisionPreferences(hold_transfers=True)
    )
    assert held.solver_status is SolverStatus.OPTIMAL
    assert all(week.transfer_count == 0 for week in held.weeks)
    invalid = DecisionPreferences(
        week_rules=(
            WeekRules(1, DecisionPreferences(buy_players=(3,), keep_players=(2, 6, 10, 14))),
        )
    )
    refused = optimize_transfer_plan(horizon, initial, config, preferences=invalid)
    assert refused.solver_status is SolverStatus.INFEASIBLE
    fixed = optimize_transfer_plan(
        horizon,
        initial,
        config,
        preferences=DecisionPreferences(
            week_rules=(WeekRules(1, DecisionPreferences(buy_players=(3, 7))),)
        ),
    )
    assert fixed.solver_status is SolverStatus.OPTIMAL
    assert fixed.weeks[0].selected_squad.groupby("team_id").size().max() <= 3
