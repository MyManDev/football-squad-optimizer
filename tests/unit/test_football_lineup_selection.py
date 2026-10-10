"""Synthetic football role decisions against an independent official scoring oracle."""

import math
from itertools import product

import pandas as pd
import pytest

from squadopt.evaluation.models import FrozenSquadDecision
from squadopt.evaluation.scoring import score_frozen_squad_decision
from squadopt.scenarios.expected_lineup import expected_lineup_score, improve_expected_lineup

XI = (1, 3, 4, 5, 8, 9, 10, 11, 13, 14, 15)
BENCH = (2, 6, 7, 12)
CAPTAIN = 13
VICE = 8


def _squad():
    table = pd.DataFrame(
        {
            "player_id": range(1, 16),
            "position": ["GK"] * 2 + ["DEF"] * 5 + ["MID"] * 5 + ["FWD"] * 3,
            "expected_points": [10.0] * 15,
            "appearance_probability": [1.0] * 15,
        }
    )
    points = {2: 1.0, 5: 5.0, 6: 4.5, 7: 0.5, 8: 14.0, 12: 0.5, 13: 15.0}
    table["expected_points"] = table.player_id.map(points).fillna(table.expected_points)
    return table


def _set(table, player, *, points, appearance=1.0):
    table.loc[table.player_id.eq(player), ["expected_points", "appearance_probability"]] = [
        points,
        appearance,
    ]


def _official_expectation(table, decision):
    """Enumerate tiny synthetic worlds through the existing realized FPL scorer."""
    rows = table.set_index("player_id")
    uncertain = [
        player for player in rows.index if 0 < rows.at[player, "appearance_probability"] < 1
    ]
    frozen = FrozenSquadDecision(
        table,
        decision.starting_xi,
        decision.ordered_bench,
        decision.captain_id,
        decision.vice_captain_id,
    )
    total = 0.0
    for bits in product((False, True), repeat=len(uncertain)):
        plays = {player: rows.at[player, "appearance_probability"] == 1 for player in rows.index}
        plays.update(zip(uncertain, bits, strict=True))
        weight = math.prod(
            rows.at[player, "appearance_probability"]
            if plays[player]
            else 1 - rows.at[player, "appearance_probability"]
            for player in uncertain
        )
        outcomes = pd.DataFrame(
            {
                "player_id": rows.index,
                "minutes": [int(plays[player]) for player in rows.index],
                "total_points": [
                    rows.at[player, "expected_points"] / rows.at[player, "appearance_probability"]
                    if plays[player]
                    else 0.0
                    for player in rows.index
                ],
            }
        )
        total += weight * score_frozen_squad_decision(frozen, outcomes).total_points
    return total


def test_flagged_defender_starts_when_conditional_points_and_cover_beat_certain_starter():
    table = _squad()
    # The supplied 4.5 already includes appearance: conditional points are 6.0.
    _set(table, 6, points=4.5, appearance=0.75)
    before = table.copy(deep=True)
    result = improve_expected_lineup(table, XI, BENCH, CAPTAIN, VICE, max_evaluations=128)

    assert 6 in result.best.starting_xi
    assert 5 in result.best.ordered_bench
    assert result.best.scoring_multipliers[5] == pytest.approx(0.25)
    gain = result.best.expected_net_points - result.incumbent.expected_net_points
    assert gain == pytest.approx(0.75)
    assert result.best.expected_net_points == pytest.approx(
        _official_expectation(table, result.best)
    )
    pd.testing.assert_frame_equal(table, before)


def test_flagged_defender_is_benched_when_appearance_and_cover_do_not_make_him_worth_starting():
    table = _squad()
    _set(table, 6, points=1.5, appearance=0.75)
    starting = tuple(6 if player == 5 else player for player in XI)
    bench = (2, 5, 7, 12)
    result = improve_expected_lineup(table, starting, bench, CAPTAIN, VICE, max_evaluations=128)

    assert 5 in result.best.starting_xi
    assert 6 in result.best.ordered_bench
    gain = result.best.expected_net_points - result.incumbent.expected_net_points
    assert gain == pytest.approx(2.25)
    assert result.best.autosub_points == 0
    assert result.best.expected_net_points == pytest.approx(
        _official_expectation(table, result.best)
    )


def test_fixture_adjusted_forward_points_change_first_bench_cover_without_reweighting_appearance():
    # Four starting defenders allow either a forward or a defender to cover player 5.
    starting = (1, 3, 4, 5, 7, 8, 9, 10, 11, 13, 14)
    bench = (2, 15, 12, 6)
    easy_fixture = _squad()
    _set(easy_fixture, 5, points=4.5, appearance=0.75)
    _set(easy_fixture, 6, points=4.0)
    _set(easy_fixture, 7, points=10.0)
    _set(easy_fixture, 12, points=3.0)
    _set(easy_fixture, 15, points=5.5)
    tough_fixture = easy_fixture.copy(deep=True)
    # This is a changed football point forecast, not another opponent multiplier.
    _set(tough_fixture, 15, points=2.0)

    easier = improve_expected_lineup(
        easy_fixture, starting, bench, CAPTAIN, VICE, max_evaluations=128
    )
    tougher = improve_expected_lineup(
        tough_fixture, starting, bench, CAPTAIN, VICE, max_evaluations=128
    )

    assert set(easier.best.starting_xi) == set(tougher.best.starting_xi) == set(starting)
    assert easier.best.ordered_bench[1] == 15
    assert tougher.best.ordered_bench[1] == 6
    assert easier.best.autosub_points == pytest.approx(0.25 * 5.5)
    assert tougher.best.autosub_points == pytest.approx(0.25 * 4.0)
    assert easier.best.scoring_multipliers[5] == tougher.best.scoring_multipliers[5] == 1
    assert easier.best.expected_net_points == pytest.approx(
        _official_expectation(easy_fixture, easier.best)
    )
    assert tougher.best.expected_net_points == pytest.approx(
        _official_expectation(tough_fixture, tougher.best)
    )


def test_three_defender_formation_skips_higher_point_midfielder_for_defensive_cover():
    table = _squad()
    _set(table, 5, points=4.5, appearance=0.75)
    _set(table, 6, points=4.0)
    _set(table, 12, points=8.0)
    score = expected_lineup_score(table, XI, (2, 12, 6, 7), CAPTAIN, VICE)

    assert score.scoring_multipliers[12] == 0
    assert score.scoring_multipliers[6] == pytest.approx(0.25)
    assert score.autosub_points == pytest.approx(1.0)
    assert score.expected_net_points == pytest.approx(_official_expectation(table, score))


@pytest.mark.parametrize("start_probability", [0.0, 0.2, 0.75])
def test_cameo_risk_uses_any_appearance_instead_of_start_probability(start_probability):
    table = _squad().assign(start_probability=1.0)
    _set(table, 5, points=4.5, appearance=0.75)
    _set(table, 6, points=5.0)
    table.loc[table.player_id.eq(5), "start_probability"] = start_probability
    score = expected_lineup_score(table, XI, BENCH, CAPTAIN, VICE)

    assert score.scoring_multipliers[5] == 1
    assert score.scoring_multipliers[6] == pytest.approx(0.25)
    assert score.autosub_points == pytest.approx(1.25)
    assert score.starting_points == pytest.approx(
        table.loc[table.player_id.isin(XI), "expected_points"].sum()
    )
    assert score.expected_net_points == pytest.approx(_official_expectation(table, score))


def _starved_bench_table():
    table = _squad().assign(expected_points=30.0)
    _set(table, 2, points=0.0)
    _set(table, 6, points=0.0)
    _set(table, 7, points=1.0)
    _set(table, 8, points=100.0)
    _set(table, 11, points=20.0, appearance=0.75)
    _set(table, 12, points=15.0)
    return table


def test_bench_priority_search_finishes_incumbent_orders_before_xi_neighborhood_spends_budget():
    table = _starved_bench_table()
    result = improve_expected_lineup(table, XI, BENCH, 8, 13, max_evaluations=128)

    assert set(result.best.starting_xi) == set(XI)
    assert result.best.ordered_bench[1] == 12
    assert result.best.autosub_points == pytest.approx(3.75)
    assert result.best.expected_net_points > result.incumbent.expected_net_points
    assert result.evaluations <= 128
    assert result.best.expected_net_points == pytest.approx(
        _official_expectation(table, result.best)
    )


def test_one_evaluation_retains_original_complete_action():
    table = _starved_bench_table()
    result = improve_expected_lineup(table, XI, BENCH, 8, 13, max_evaluations=1)

    assert result.evaluations == 1
    assert result.best == result.incumbent
    assert result.best.starting_xi == XI
    assert result.best.ordered_bench == BENCH
    assert result.best.captain_id == 8
    assert result.best.vice_captain_id == 13


def test_locked_first_action_preserves_xi_captain_vice_and_bench_priority():
    table = _starved_bench_table()
    result = improve_expected_lineup(
        table, XI, BENCH, 8, 13, max_evaluations=128, locked_first=True
    )

    assert result.evaluations == 1
    assert result.locked_first
    assert result.best == result.incumbent
    assert result.best.starting_xi == XI
    assert result.best.ordered_bench == BENCH
    assert result.best.captain_id == 8
    assert result.best.vice_captain_id == 13


@pytest.mark.parametrize("appearance", [0.0, 0.25, 0.5, 0.75])
def test_exact_point_tie_benches_absent_or_doubtful_player_for_more_available_xi(appearance):
    table = _squad()
    # Both defenders have conditional value 5.0, so cover makes the scores identical.
    _set(table, 6, points=5.0 * appearance, appearance=appearance)
    starting = tuple(6 if player == 5 else player for player in XI)
    bench = (2, 5, 7, 12)
    result = improve_expected_lineup(table, starting, bench, CAPTAIN, VICE, max_evaluations=128)

    assert result.best.expected_net_points == result.incumbent.expected_net_points
    assert 5 in result.best.starting_xi
    assert 6 in result.best.ordered_bench
    chance = table.set_index("player_id").appearance_probability
    assert math.fsum(chance.loc[list(result.best.starting_xi)]) > math.fsum(
        chance.loc[list(result.incumbent.starting_xi)]
    )
    assert result.best.expected_net_points == pytest.approx(
        _official_expectation(table, result.best)
    )
    assert result.evaluations <= 128


def test_equal_point_and_appearance_totals_keep_incumbent_complete_action():
    table = _squad()
    _set(table, 6, points=5.0)
    starting = tuple(6 if player == 5 else player for player in XI)
    bench = (2, 5, 7, 12)
    result = improve_expected_lineup(table, starting, bench, CAPTAIN, VICE, max_evaluations=128)

    assert result.best == result.incumbent
    assert result.best.starting_xi == starting
    assert result.best.ordered_bench == bench
    assert result.best.captain_id == CAPTAIN
    assert result.best.vice_captain_id == VICE


def test_more_available_xi_cannot_take_even_a_tiny_expected_point_loss():
    table = _squad()
    _set(table, 6, points=(5.0 + 1e-8) * 0.25, appearance=0.25)
    starting = tuple(6 if player == 5 else player for player in XI)
    bench = (2, 5, 7, 12)
    result = improve_expected_lineup(table, starting, bench, CAPTAIN, VICE, max_evaluations=128)
    more_available = expected_lineup_score(table, XI, BENCH, CAPTAIN, VICE)

    assert more_available.expected_net_points < result.incumbent.expected_net_points
    assert 6 in result.best.starting_xi
    assert result.best.expected_net_points == result.incumbent.expected_net_points
    assert result.best.expected_net_points == pytest.approx(
        _official_expectation(table, result.best)
    )
