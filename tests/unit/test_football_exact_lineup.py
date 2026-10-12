"""Synthetic global enumeration against identity-based official scoring worlds."""

import math
from itertools import combinations, permutations, product

import pandas as pd
import pytest

from squadopt.evaluation.models import FrozenSquadDecision
from squadopt.evaluation.scoring import score_frozen_squad_decision
from squadopt.planning.football_exact_lineup import optimize_football_lineup_exact
from squadopt.scenarios.expected_lineup import expected_lineup_score, improve_expected_lineup

XI = (1, 3, 4, 5, 8, 9, 10, 11, 13, 14, 15)
BENCH = (2, 6, 7, 12)
MINIMUM = {"GK": 1, "DEF": 3, "MID": 2, "FWD": 1}
MAXIMUM = {"GK": 1, "DEF": 5, "MID": 5, "FWD": 3}
FORMATIONS = (
    (3, 4, 3),
    (3, 5, 2),
    (4, 3, 3),
    (4, 4, 2),
    (4, 5, 1),
    (5, 2, 3),
    (5, 3, 2),
    (5, 4, 1),
)


@pytest.fixture
def squad():
    return pd.DataFrame(
        {
            "player_id": list(range(1, 16)),
            "position": ["GK"] * 2 + ["DEF"] * 5 + ["MID"] * 5 + ["FWD"] * 3,
            "expected_points": [float((p * 7) % 17 + 1) for p in range(1, 16)],
            "appearance_probability": [1.0] * 15,
        }
    )


def _chances(squad, changes):
    result = squad.copy(deep=True)
    for player, chance in changes.items():
        result.loc[result.player_id.eq(player), "appearance_probability"] = chance
        result.loc[result.player_id.eq(player), "expected_points"] *= chance
    return result


def _worlds(squad):
    rows = squad.set_index("player_id")
    q = rows.appearance_probability.to_dict()
    mu = rows.expected_points.to_dict()
    uncertain = tuple(p for p in rows.index if 0 < q[p] < 1)
    worlds = []
    for bits in product((False, True), repeat=len(uncertain)):
        playing = {p for p in rows.index if q[p] == 1}
        playing.update(p for p, bit in zip(uncertain, bits, strict=True) if bit)
        weight = math.prod(q[p] if p in playing else 1 - q[p] for p in uncertain)
        points = {p: mu[p] / q[p] if p in playing else 0.0 for p in rows.index}
        worlds.append((weight, playing, points))
    return worlds


def _world_base(positions, xi, bench, playing, points, chip):
    """Greedily replace individual vacant slots, without count convolution."""
    if chip == "bboost":
        return math.fsum(points.values())
    counts = {pos: sum(positions[p] == pos for p in xi) for pos in MINIMUM}
    final = set(xi) & playing
    absent = [p for p in xi if p not in playing and positions[p] != "GK"]
    keeper = next(p for p in xi if positions[p] == "GK")
    backup = next(p for p in bench if positions[p] == "GK")
    if keeper not in playing and backup in playing:
        final.add(backup)
    for incoming in bench:
        if positions[incoming] == "GK" or incoming not in playing:
            continue
        for outgoing in absent:
            proposed = dict(counts)
            proposed[positions[outgoing]] -= 1
            proposed[positions[incoming]] += 1
            if all(MINIMUM[pos] <= proposed[pos] <= MAXIMUM[pos] for pos in proposed):
                final.add(incoming)
                absent.remove(outgoing)
                counts = proposed
                break
    return math.fsum(points[p] for p in final)


def _oracle(squad, chip=None, hits=0.0, not_starting=(), not_captain=()):
    """Enumerate arbitrary 11-of-15 sets, every reserve order and every pair."""
    positions = squad.set_index("player_id").position.to_dict()
    q = squad.set_index("player_id").appearance_probability.to_dict()
    worlds = _worlds(squad)
    best = None
    xis = orders = pairs = 0
    for xi in combinations(positions, 11):
        counts = {pos: sum(positions[p] == pos for p in xi) for pos in MINIMUM}
        if set(xi) & set(not_starting) or not all(
            MINIMUM[pos] <= counts[pos] <= MAXIMUM[pos] for pos in counts
        ):
            continue
        eligible = [p for p in xi if p not in not_captain]
        if len(eligible) < 2:
            continue
        xis += 1
        pair_scores = []
        for captain in eligible:
            for vice in eligible:
                if captain == vice:
                    continue
                pairs += 1
                bonus = math.fsum(
                    weight
                    * (points[captain] if captain in playing else points[vice])
                    * (2 if chip == "3xc" else 1)
                    for weight, playing, points in worlds
                )
                pair_scores.append((bonus, captain, vice))
        bonus, captain, vice = max(pair_scores, key=lambda item: (item[0], -item[1], -item[2]))
        reserve = [p for p in positions if p not in xi]
        keeper = next(p for p in reserve if positions[p] == "GK")
        for field in permutations(p for p in reserve if positions[p] != "GK"):
            orders += 1
            bench = (keeper, *field)
            expected = (
                math.fsum(
                    weight * _world_base(positions, xi, bench, playing, points, chip)
                    for weight, playing, points in worlds
                )
                + bonus
                - hits
            )
            key = (expected, math.fsum(q[p] for p in xi))
            if best is None or key > best[0]:
                best = (key, xi, bench, captain, vice)
    return best, xis, orders, pairs


@pytest.mark.parametrize("chip", [None, "3xc", "bboost"])
@pytest.mark.parametrize("signed", [False, True])
def test_global_optimum_matches_independent_world_and_all_pair_enumeration(squad, chip, signed):
    table = _chances(squad, {1: 0.3, 2: 0.6, 4: 0.7, 13: 0.4, 7: 0.0})
    if signed:
        table.loc[table.player_id.eq(12), "expected_points"] = -3.25
    result = optimize_football_lineup_exact(table, XI, BENCH, 13, 8, chip=chip, hit_points=8)
    oracle, xis, orders, pairs = _oracle(table, chip, hits=8)
    assert oracle is not None
    assert result.best.expected_net_points == pytest.approx(oracle[0][0], abs=1e-11)
    assert result.legal_xis == xis == 550
    assert result.reserve_orders_evaluated == orders == 3300
    assert result.captain_pairs_covered == pairs == 60500
    assert result.captain_pair_terms_computed == 210
    assert result.captain_pair_membership_checks == xis * 210
    assert result.captain_pair_scores_evaluated == 3300 * 110
    assert result.role_scores_evaluated == 363000 + result.score_records_built
    assert 1 <= result.score_records_built <= 3301
    assert result.proof_scope == "all_legal_fixed_fifteen_roles_under_independent_appearance"


@pytest.mark.parametrize("formation", FORMATIONS)
def test_identity_oracle_agrees_with_official_scorer_in_every_formation(squad, formation):
    selected = (
        1,
        *range(3, 3 + formation[0]),
        *range(8, 8 + formation[1]),
        *range(13, 13 + formation[2]),
    )
    reserve = tuple(p for p in range(1, 16) if p not in selected)
    table = _chances(squad, {1: 0.0, selected[1]: 0.0, selected[-1]: 0.5})
    positions = table.set_index("player_id").position.to_dict()
    for _, playing, points in _worlds(table):
        # Positive one-minute appearances are deliberately used as cameos.
        outcomes = pd.DataFrame(
            {
                "player_id": list(points),
                "minutes": [int(p in playing) for p in points],
                "total_points": list(points.values()),
            }
        )
        decision = FrozenSquadDecision(table, selected, reserve, selected[-1], selected[-2])
        official = score_frozen_squad_decision(decision, outcomes)
        base = _world_base(positions, selected, reserve, playing, points, None)
        captain = selected[-1] if selected[-1] in playing else selected[-2]
        assert base + points[captain] == pytest.approx(float(official.total_points))


def test_global_search_can_make_two_simultaneous_xi_swaps(squad):
    table = squad.assign(expected_points=1.0)
    for player, points in {3: 0.0, 4: 0.0, 6: 20.0, 7: 30.0, 12: 0.5, 13: 50.0}.items():
        table.loc[table.player_id.eq(player), "expected_points"] = points
    local = improve_expected_lineup(table, XI, BENCH, 13, 8, max_evaluations=10000)
    exact = optimize_football_lineup_exact(table, XI, BENCH, 13, 8)
    assert {6, 7} <= set(exact.best.starting_xi)
    assert not {3, 4} & set(exact.best.starting_xi)
    assert exact.best.expected_net_points > local.best.expected_net_points
    assert set(exact.best.starting_xi) - set(XI) == {6, 7}


def test_all_negative_points_choose_least_costly_legal_roles(squad):
    table = squad.assign(expected_points=-squad.player_id.astype(float))
    result = optimize_football_lineup_exact(table, XI, BENCH, 13, 8, hit_points=4)
    oracle, _, _, _ = _oracle(table, hits=4)
    assert oracle is not None
    assert result.best.expected_net_points == oracle[0][0] < 0
    assert result.best.captain_id == 1


def test_uncertain_captain_beats_larger_mean_through_certain_vice_fallback(squad):
    table = squad.assign(expected_points=1.0)
    table.loc[table.player_id.eq(13), "appearance_probability"] = 0.2
    table.loc[table.player_id.eq(13), "expected_points"] = 10.0
    table.loc[table.player_id.eq(14), "expected_points"] = 11.0
    result = optimize_football_lineup_exact(table, XI, BENCH, 14, 13)
    assert result.best.captain_id == 13
    assert result.best.vice_captain_id == 14
    assert result.best.vice_bonus_points == pytest.approx(8.8)
    assert result.best.expected_net_points == pytest.approx(49.6)


@pytest.mark.parametrize("chip", [None, "3xc", "bboost"])
def test_full_float_score_finds_vice_gain_hidden_by_rounded_bonus(squad, chip):
    table = squad.assign(expected_points=0.0)
    for player, points in {
        13: 1.0,
        14: -3.0 if chip == "3xc" else -2.0,
        3: 1e-16,
        4: 1.1e-16,
    }.items():
        table.loc[table.player_id.eq(player), "expected_points"] = points
    table.loc[table.player_id.eq(13), "appearance_probability"] = 0.5
    # Two separately rounded bonus terms cannot distinguish these vice choices.
    bonus = 2 if chip == "3xc" else 1
    assert 1.0 + bonus * 0.5 * 1e-16 == 1.0 + bonus * 0.5 * 1.1e-16
    result = optimize_football_lineup_exact(
        table,
        XI,
        BENCH,
        13,
        3,
        chip=chip,
        not_starting=BENCH,
    )
    exact = expected_lineup_score(table, XI, BENCH, 13, 4, chip=chip)
    exhaustive_scores = [
        expected_lineup_score(table, XI, BENCH, captain, vice, chip=chip).expected_net_points
        for captain in XI
        for vice in XI
        if captain != vice
    ]
    assert result.best.captain_id == 13
    assert result.best.vice_captain_id == 4
    assert result.best.expected_net_points == exact.expected_net_points == max(exhaustive_scores)
    assert result.best.expected_net_points > result.incumbent.expected_net_points
    assert result.role_scores_evaluated == 662
    assert result.captain_pair_scores_evaluated == 660
    assert result.score_records_built == 2


@pytest.mark.parametrize("chip", [None, "wildcard", "freehit", "3xc", "bboost"])
def test_endpoint_appearances_chips_and_hits_are_counted_once(squad, chip):
    table = _chances(squad, {1: 0.0, 3: 0.0, 13: 0.0})
    table.loc[table.player_id.eq(12), "expected_points"] = -2.0
    result = optimize_football_lineup_exact(table, XI, BENCH, 13, 8, chip=chip, hit_points=4)
    best = result.best
    positions = table.set_index("player_id").position.to_dict()
    _, playing, points = _worlds(table)[0]
    base = _world_base(positions, best.starting_xi, best.ordered_bench, playing, points, chip)
    captain = best.captain_id if best.captain_id in playing else best.vice_captain_id
    expected = base + (2 if chip == "3xc" else 1) * points[captain] - 4
    assert best.expected_net_points == pytest.approx(expected)
    assert best.hit_points == 4
    assert best.scoring_multipliers[2] >= 1  # Available keeper starts or covers the absent one.
    if chip == "bboost":
        assert best.autosub_points == 0
        assert all(best.scoring_multipliers[p] >= 1 for p in range(1, 16))


def test_exact_restrictions_cover_xi_captain_and_vice(squad):
    result = optimize_football_lineup_exact(
        squad,
        XI,
        BENCH,
        13,
        8,
        not_starting=(6,),
        not_captain=(1, 12),
    )
    oracle, xis, orders, pairs = _oracle(squad, not_starting=(6,), not_captain=(1, 12))
    assert oracle is not None
    assert result.best.expected_net_points == oracle[0][0]
    assert 6 not in result.best.starting_xi
    assert {result.best.captain_id, result.best.vice_captain_id}.isdisjoint({1, 12})
    assert (result.legal_xis, result.reserve_orders_evaluated, result.captain_pairs_covered) == (
        xis,
        orders,
        pairs,
    )
    assert orders == 6 * xis < 3300


def test_locked_complete_action_preserves_tuple_order_bench_and_pair(squad):
    table = _chances(squad, {1: 0.3, 3: 0.2, 13: 0.4, 6: 0.7})
    xi, bench = tuple(reversed(XI)), (12, 6, 2, 7)
    result = optimize_football_lineup_exact(table, xi, bench, 13, 8, locked_first=True)
    assert result.best is result.incumbent
    assert result.best.starting_xi == xi
    assert result.best.ordered_bench == bench
    assert (result.best.captain_id, result.best.vice_captain_id) == (13, 8)
    assert result.role_scores_evaluated == result.reserve_orders_evaluated == result.legal_xis == 1
    assert result.captain_pairs_covered == 0
    assert result.captain_pair_membership_checks == 0
    assert result.proof_scope == "locked_complete_action_only"


def test_exact_point_ties_prefer_available_xi(squad):
    table = squad.assign(expected_points=0.0)
    table.loc[table.player_id.eq(3), "appearance_probability"] = 0.0
    table.loc[table.player_id.eq(8), "appearance_probability"] = 0.25
    table.loc[table.player_id.eq(13), "appearance_probability"] = 0.5
    result = optimize_football_lineup_exact(table, XI, BENCH, 13, 8)
    q = table.set_index("player_id").appearance_probability
    assert math.fsum(q.loc[list(result.best.starting_xi)]) == 11
    assert result.best.expected_net_points == 0


def test_tiny_point_gain_precedes_availability(squad):
    table = squad.assign(expected_points=0.0)
    table.loc[table.player_id.eq(3), "appearance_probability"] = 0.2
    table.loc[table.player_id.eq(3), "expected_points"] = 1e-14
    result = optimize_football_lineup_exact(table, XI, BENCH, 13, 8)
    assert 3 in result.best.starting_xi
    assert result.best.expected_net_points == 2e-14


def test_equal_points_and_availability_retain_original_full_action(squad):
    table = squad.assign(expected_points=0.0)
    xi, bench = tuple(reversed(XI)), (12, 6, 2, 7)
    result = optimize_football_lineup_exact(table, xi, bench, 13, 8)
    assert result.best is result.incumbent
    assert result.best.starting_xi == xi
    assert result.best.ordered_bench == bench
    assert (result.best.captain_id, result.best.vice_captain_id) == (13, 8)


@pytest.mark.parametrize("string_ids", [False, True])
def test_canonical_world_arithmetic_ignores_frame_and_xi_order(squad, string_ids):
    table = _chances(squad, {1: 0.3, 3: 0.2, 13: 0.4, 6: 0.7})
    convert = str if string_ids else int
    table.player_id = table.player_id.map(convert)
    xi, bench = tuple(map(convert, XI)), tuple(map(convert, BENCH))
    first = optimize_football_lineup_exact(table, xi, bench, convert(13), convert(8))
    second = optimize_football_lineup_exact(
        table.iloc[::-1],
        tuple(reversed(xi)),
        bench,
        convert(13),
        convert(8),
    )
    assert first.incumbent.expected_net_points == second.incumbent.expected_net_points
    assert first.best.fingerprint == second.best.fingerprint
    assert first.best.expected_net_points == second.best.expected_net_points
    assert first.states_evaluated == second.states_evaluated


def test_selected_squad_and_multiplier_map_are_immutable(squad):
    before = squad.copy(deep=True)
    result = optimize_football_lineup_exact(squad, XI, BENCH, 13, 8)
    pd.testing.assert_frame_equal(squad, before)
    assert set(result.best.starting_xi) | set(result.best.ordered_bench) == set(squad.player_id)
    with pytest.raises(TypeError):
        result.best.scoring_multipliers[1] = 99


@pytest.mark.parametrize(
    "column,value",
    [
        ("appearance_probability", -0.1),
        ("appearance_probability", 1.1),
        ("appearance_probability", True),
        ("appearance_probability", float("nan")),
        ("expected_points", float("inf")),
        ("expected_points", True),
    ],
)
def test_invalid_forecast_numbers_are_refused(squad, column, value):
    table = squad.astype({column: object})
    table.loc[table.player_id.eq(3), column] = value
    with pytest.raises(ValueError):
        optimize_football_lineup_exact(table, XI, BENCH, 13, 8)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"not_starting": (3,)},
        {"not_captain": (8,)},
        {"not_starting": (99,)},
        {"not_captain": (99,)},
        {"locked_first": 1},
        {"chip": "unknown"},
        {"hit_points": -4},
    ],
)
def test_invalid_or_incumbent_violating_controls_are_refused(squad, kwargs):
    with pytest.raises(ValueError):
        optimize_football_lineup_exact(squad, XI, BENCH, 13, 8, **kwargs)


def test_missing_appearance_and_nonzero_points_at_zero_q_are_refused(squad):
    with pytest.raises(ValueError, match="missing columns"):
        optimize_football_lineup_exact(
            squad.drop(columns="appearance_probability"), XI, BENCH, 13, 8
        )
    table = squad.copy(deep=True)
    table.loc[table.player_id.eq(3), "appearance_probability"] = 0.0
    with pytest.raises(ValueError, match="zero appearance"):
        optimize_football_lineup_exact(table, XI, BENCH, 13, 8)


def test_cameo_input_uses_any_appearance_and_leaves_existing_default_cap_unchanged(squad):
    table = squad.assign(start_probability=0.0)
    exact = optimize_football_lineup_exact(table, XI, BENCH, 13, 8)
    assert exact.best.autosub_points == 0
    assert exact.best.vice_bonus_points == 0
    bounded = improve_expected_lineup(table, XI, BENCH, 13, 8)
    assert bounded.max_evaluations == 128
    assert bounded.evaluations <= 128
    assert bounded.proof_scope == "bounded_fixed_squad_neighborhood_only"
