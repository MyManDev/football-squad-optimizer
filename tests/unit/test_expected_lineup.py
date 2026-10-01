"""Exact lineup expectations must agree with the existing official rules scorer."""

import math
from itertools import product

import pandas as pd
import pytest

from squadopt.evaluation.models import FrozenSquadDecision
from squadopt.evaluation.scoring import score_frozen_squad_decision
from squadopt.scenarios.expected_lineup import expected_lineup_score, improve_expected_lineup

XI = (1, 3, 4, 5, 8, 9, 10, 11, 13, 14, 15)
BENCH = (2, 6, 7, 12)


@pytest.fixture
def squad():
    return pd.DataFrame(
        {
            "player_id": list(range(1, 16)),
            "position": ["GK"] * 2 + ["DEF"] * 5 + ["MID"] * 5 + ["FWD"] * 3,
            "expected_points": [float(player % 5 + 1) for player in range(1, 16)],
            "appearance_probability": [1.0] * 15,
        }
    )


def with_chances(squad, probabilities):
    table = squad.copy(deep=True)
    for player, chance in probabilities.items():
        mask = table.player_id.eq(player)
        table.loc[mask, "appearance_probability"] = chance
        table.loc[mask, "expected_points"] *= chance
    return table


def official_expectation(squad, xi=XI, bench=BENCH, captain=13, vice=8, chip=None, hits=0):
    frozen = FrozenSquadDecision(squad, xi, bench, captain, vice)
    rows = squad.set_index("player_id")
    uncertain = [p for p in rows.index if 0 < rows.at[p, "appearance_probability"] < 1]
    expected, auto, vice_bonus = 0.0, 0.0, 0.0
    for bits in product((False, True), repeat=len(uncertain)):
        plays = {p: rows.at[p, "appearance_probability"] == 1 for p in rows.index}
        plays.update(zip(uncertain, bits, strict=True))
        probability = math.prod(
            rows.at[p, "appearance_probability"]
            if plays[p]
            else 1 - rows.at[p, "appearance_probability"]
            for p in uncertain
        )
        outcomes = pd.DataFrame(
            {
                "player_id": rows.index,
                "minutes": [int(plays[p]) for p in rows.index],
                "total_points": [
                    rows.at[p, "expected_points"] / rows.at[p, "appearance_probability"]
                    if plays[p]
                    else 0.0
                    for p in rows.index
                ],
            }
        )
        score = score_frozen_squad_decision(frozen, outcomes)
        gross = score.total_points
        if chip == "3xc":
            gross += score.captain_bonus_points
        elif chip == "bboost":
            gross = outcomes.total_points.sum() + score.captain_bonus_points
        expected += probability * (gross - hits)
        auto += probability * (0 if chip == "bboost" else score.autosub_points)
        vice_bonus += probability * (
            score.captain_bonus_points * (2 if chip == "3xc" else 1)
            if score.captain_bonus_player_id == vice
            else 0
        )
    return expected, auto, vice_bonus


@pytest.mark.parametrize(
    "probabilities",
    [
        {1: 0.3, 3: 0.2, 13: 0.5, 2: 0.7, 6: 0.4, 12: 0.8},
        {3: 0.2, 8: 0.6, 13: 0.3, 6: 0.4, 7: 0.7, 12: 0.8},
    ],
)
@pytest.mark.parametrize("chip", [None, "wildcard", "freehit", "3xc", "bboost"])
def test_exact_expectation_matches_official_rules(squad, chip, probabilities):
    table = with_chances(squad, probabilities)
    table.loc[table.player_id.eq(7), "expected_points"] = -2.0
    # Deliberately interleaved positions: XI tuple order must not affect admissions.
    xi = (13, 8, 3, 1, 14, 9, 4, 15, 10, 5, 11)
    bench = (2, 12, 7, 6)
    score = expected_lineup_score(table, xi, bench, 13, 8, chip=chip, hit_points=4)
    official, auto, vice = official_expectation(table, xi, bench, chip=chip, hits=4)
    assert score.expected_net_points == pytest.approx(official, abs=1e-11)
    assert score.autosub_points == pytest.approx(auto, abs=1e-11)
    assert score.vice_bonus_points == pytest.approx(vice, abs=1e-11)
    assert score.expected_net_points == pytest.approx(
        score.starting_points
        + score.autosub_points
        + score.captain_bonus_points
        + score.vice_bonus_points
        + score.bench_boost_points
        - 4,
    )
    assert "independent_player_week_appearances" in score.assumptions


def test_everyone_plays_has_no_bench_bonus_or_double_appearance_weight(squad):
    score = expected_lineup_score(squad, XI, BENCH, 13, 8)
    points = squad.set_index("player_id").expected_points
    assert score.expected_net_points == sum(points.loc[list(XI)]) + points.loc[13]
    assert score.autosub_points == score.vice_bonus_points == 0
    assert all(score.scoring_multipliers[p] == 0 for p in BENCH)
    assert score.scoring_multipliers[13] == 2


def test_formations_skip_ineligible_first_bench_and_keeper_is_separate(squad):
    table = with_chances(squad, {1: 0, 3: 0})
    score = expected_lineup_score(table, XI, (12, 2, 6, 7), 13, 8)
    assert score.scoring_multipliers[2] == 1
    assert score.scoring_multipliers[12] == 0  # Three-defender minimum still binds.
    assert score.scoring_multipliers[6] == 1
    assert score.scoring_multipliers[7] == 0
    assert score.expected_net_points == pytest.approx(
        official_expectation(table, bench=(12, 2, 6, 7))[0]
    )


@pytest.mark.parametrize("chip,multiplier", [(None, 1), ("3xc", 2), ("bboost", 1)])
def test_vice_fallback_and_chips_use_unconditional_points(squad, chip, multiplier):
    table = with_chances(squad, {13: 0, 8: 0.5})
    score = expected_lineup_score(table, XI, BENCH, 13, 8, chip=chip)
    vice_points = table.loc[table.player_id.eq(8), "expected_points"].iloc[0]
    assert score.captain_bonus_points == 0
    assert score.vice_bonus_points == multiplier * vice_points
    assert score.scoring_multipliers[8] == 1 + multiplier
    if chip == "bboost":
        assert score.autosub_points == 0
        assert all(score.scoring_multipliers[p] == 1 for p in BENCH)


def test_cameos_and_weekly_double_appearance_are_not_start_probabilities(squad):
    table = squad.assign(start_probability=0.0)
    score = expected_lineup_score(table, XI, BENCH, 13, 8)
    assert score.autosub_points == 0  # Every player makes at least a cameo.
    weekly = with_chances(table, {1: 0.75})  # Caller aggregated two fixture appearances.
    score = expected_lineup_score(weekly, XI, BENCH, 13, 8)
    assert score.scoring_multipliers[2] == 0.25
    assert score.scoring_multipliers[1] == 1  # Weekly unconditional points are not reduced again.


def test_linear_multipliers_restate_base_points_on_exact_same_action(squad):
    table = with_chances(squad, {1: 0.2, 3: 0.7, 13: 0.4, 2: 0.6, 6: 0.3, 12: 0.5})
    weighted = table.assign(expected_points=table.expected_points * (1 + table.player_id / 50))
    for chip in (None, "3xc", "bboost"):
        chosen = expected_lineup_score(weighted, XI, BENCH, 13, 8, chip=chip, hit_points=8)
        base = expected_lineup_score(table, XI, BENCH, 13, 8, chip=chip, hit_points=8)
        assert dict(chosen.scoring_multipliers) == dict(base.scoring_multipliers)
        assert math.fsum(
            chosen.scoring_multipliers[row.player_id] * row.expected_points
            for row in table.itertuples()
        ) - 8 == pytest.approx(base.expected_net_points)
        assert chosen.fingerprint != base.fingerprint


@pytest.mark.parametrize(
    "column,value",
    [
        ("appearance_probability", -0.1),
        ("appearance_probability", 1.1),
        ("appearance_probability", float("nan")),
        ("appearance_probability", float("inf")),
        ("appearance_probability", True),
        ("expected_points", float("nan")),
        ("expected_points", float("inf")),
        ("expected_points", True),
    ],
)
def test_bad_numbers_are_refused(squad, column, value):
    table = squad.astype({column: object})
    table.loc[0, column] = value
    with pytest.raises(ValueError):
        expected_lineup_score(table, XI, BENCH, 13, 8)


@pytest.mark.parametrize("points", [-1.0, 1.0])
def test_zero_probability_cannot_carry_points(squad, points):
    table = squad.copy()
    table.loc[0, ["appearance_probability", "expected_points"]] = [0.0, points]
    with pytest.raises(ValueError, match="zero appearance"):
        expected_lineup_score(table, XI, BENCH, 13, 8)


def test_inputs_and_multiplier_map_cannot_be_modified_by_scoring(squad):
    before = squad.copy(deep=True)
    first = expected_lineup_score(squad, XI, BENCH, 13, 8)
    reordered = expected_lineup_score(squad.iloc[::-1], XI, BENCH, 13, 8)
    assert first.fingerprint == reordered.fingerprint
    pd.testing.assert_frame_equal(squad, before)
    with pytest.raises(TypeError):
        first.scoring_multipliers[1] = 100


def test_count_convolution_remains_small_with_fifteen_uncertain_players(squad):
    table = with_chances(squad, dict.fromkeys(range(1, 16), 0.5))
    score = expected_lineup_score(table, XI, BENCH, 13, 8)
    assert 0 < score.states_evaluated <= 640
    assert math.isfinite(score.expected_net_points)


@pytest.mark.parametrize("limit", [1, 2, 8, 128])
def test_bounded_search_retains_incumbent_and_same_fifteen(squad, limit):
    table = squad.copy()
    table.loc[table.player_id.eq(6), "expected_points"] = 40.0
    result = improve_expected_lineup(table, XI, BENCH, 13, 8, max_evaluations=limit)
    assert 1 <= result.evaluations <= limit
    assert result.states_evaluated <= 640 * result.evaluations
    assert result.autosub_cache_hits <= result.evaluations
    assert result.captain_pairs_considered <= 20 * 45
    assert result.best.expected_net_points >= result.incumbent.expected_net_points
    assert set(result.best.starting_xi) | set(result.best.ordered_bench) == set(range(1, 16))
    assert result.proof_scope == "bounded_fixed_squad_neighborhood_only"
    if limit == 1:
        assert result.best == result.incumbent and result.budget_exhausted
    if limit == 128:
        assert result.best.expected_net_points > result.incumbent.expected_net_points
        assert 6 in result.best.starting_xi
    verified = expected_lineup_score(
        table,
        result.best.starting_xi,
        result.best.ordered_bench,
        result.best.captain_id,
        result.best.vice_captain_id,
    )
    assert result.best == verified


def test_search_respects_exclusions_for_starting_captain_and_vice(squad):
    table = squad.copy()
    table.loc[table.player_id.eq(6), "expected_points"] = 100.0
    table.loc[table.player_id.eq(11), "expected_points"] = 90.0
    result = improve_expected_lineup(
        table,
        XI,
        BENCH,
        13,
        8,
        not_starting=(6,),
        not_captain=(11,),
        max_evaluations=128,
    )
    assert 6 not in result.best.starting_xi
    assert result.best.captain_id != 11 and result.best.vice_captain_id != 11
    for kwargs in ({"not_starting": (3,)}, {"not_captain": (13,)}, {"not_captain": (8,)}):
        with pytest.raises(ValueError, match="incumbent"):
            improve_expected_lineup(table, XI, BENCH, 13, 8, **kwargs)


def test_locked_action_freezes_xi_ordered_bench_captain_and_vice(squad):
    result = improve_expected_lineup(squad, XI, (12, 6, 7, 2), 13, 8, locked_first=True)
    assert result.best == result.incumbent
    assert result.best.starting_xi == XI and result.best.ordered_bench == (12, 6, 7, 2)
    assert result.best.captain_id == 13 and result.best.vice_captain_id == 8
    assert result.evaluations == 1 and not result.budget_exhausted


def test_ties_cache_and_identifier_types_are_deterministic(squad):
    table = squad.assign(expected_points=0.0)
    first = improve_expected_lineup(table, XI, BENCH, 13, 8, max_evaluations=1000)
    second = improve_expected_lineup(table.iloc[::-1], XI, BENCH, 13, 8, max_evaluations=1000)
    assert first == second
    assert first.best == first.incumbent
    assert first.cache_hits > 0 and not first.budget_exhausted
    strings = table.assign(player_id=lambda frame: frame.player_id.astype(str))
    result = improve_expected_lineup(
        strings, tuple(map(str, XI)), tuple(map(str, BENCH)), "13", "8", max_evaluations=2
    )
    assert all(isinstance(player, str) for player in result.best.scoring_multipliers)


@pytest.mark.parametrize("limit", [0, -1, True, 1.5, 10001])
def test_invalid_evaluation_budget_is_rejected(squad, limit):
    with pytest.raises(ValueError, match="max_evaluations"):
        improve_expected_lineup(squad, XI, BENCH, 13, 8, max_evaluations=limit)
