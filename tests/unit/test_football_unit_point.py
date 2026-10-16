"""Independent enumeration and boundary checks for the declared XI point rule."""

import math
from dataclasses import replace
from itertools import combinations

import pytest

from squadopt.features.football_unit_inputs import UnitPlayer
from squadopt.features.football_unit_point import (
    UNIT_POINT_VERSION,
    UnitStarterProbability,
    project_unit_point,
)


def inputs():
    roster = tuple(UnitPlayer(i, "GK" if i <= 2 else "MID") for i in range(1, 15))
    probabilities = tuple(
        UnitStarterProbability(player.player_id, 0.1 + (player.player_id * 7 % 17) / 20)
        for player in roster
    )
    return dict(
        club=4, roster=roster, starter_probabilities=probabilities, native_basis_sha256="a" * 64
    )


def test_point_matches_independent_full_enumeration_and_is_order_invariant():
    supplied = inputs()
    result = project_unit_point(**supplied)
    probabilities = {row.player_id: row.probability for row in supplied["starter_probabilities"]}
    worlds = []
    for keeper in (1, 2):
        for field in combinations(range(3, 15), 10):
            picked = (keeper, *field)
            mass = math.prod(p if code in picked else 1 - p for code, p in probabilities.items())
            worlds.append((mass, picked))
    expected_mass, expected_players = sorted(worlds, key=lambda row: (-row[0], row[1]))[0]
    assert tuple(player.player_id for player in result.unit.players) == expected_players
    assert math.exp(result.independent_joint_log_mass) == pytest.approx(expected_mass)
    assert result.version == UNIT_POINT_VERSION
    assert (
        project_unit_point(
            **{
                **supplied,
                "roster": tuple(reversed(supplied["roster"])),
                "starter_probabilities": tuple(reversed(supplied["starter_probabilities"])),
            }
        )
        == result
    )


def test_ties_use_persistent_identity_and_keep_original_probabilities():
    supplied = inputs()
    supplied["roster"] = tuple(reversed(supplied["roster"]))
    supplied["starter_probabilities"] = tuple(UnitStarterProbability(i, 0.5) for i in range(1, 15))
    result = project_unit_point(**supplied)
    assert tuple(player.player_id for player in result.unit.players) == (1, *range(3, 13))
    assert result.starter_probabilities == supplied["starter_probabilities"]
    assert result.native_basis_sha256 == "a" * 64
    assert "not_calibrated" in result.interpretation


def test_structural_zero_and_one_are_preserved_without_floors():
    supplied = inputs()
    picked = {1, *range(3, 13)}
    supplied["starter_probabilities"] = tuple(
        UnitStarterProbability(i, float(i in picked)) for i in range(1, 15)
    )
    result = project_unit_point(**supplied)
    assert {player.player_id for player in result.unit.players} == picked
    assert result.independent_joint_log_mass == 0


@pytest.mark.parametrize(
    "codes,probability",
    [((1, 2), 1.0), ((1, 2), 0.0), (tuple(range(3, 14)), 1.0), (tuple(range(3, 6)), 0.0)],
)
def test_impossible_conditioning_refuses_instead_of_inventing_an_xi(codes, probability):
    supplied = inputs()
    supplied["starter_probabilities"] = tuple(
        replace(row, probability=probability) if row.player_id in codes else row
        for row in supplied["starter_probabilities"]
    )
    with pytest.raises(ValueError, match="zero support"):
        project_unit_point(**supplied)


@pytest.mark.parametrize("probability", [True, -0.1, 1.1, math.inf, math.nan, "0.5"])
def test_invalid_probability_refuses(probability):
    with pytest.raises(ValueError):
        UnitStarterProbability(1, probability)


@pytest.mark.parametrize(
    "mutation", ["missing", "extra", "duplicate", "duplicate_roster", "list", "bad_hash"]
)
def test_complete_basis_shape_is_required(mutation):
    supplied = inputs()
    rows = supplied["starter_probabilities"]
    if mutation == "missing":
        supplied["starter_probabilities"] = rows[:-1]
    elif mutation == "extra":
        supplied["starter_probabilities"] = (*rows, UnitStarterProbability(99, 0.5))
    elif mutation == "duplicate":
        supplied["starter_probabilities"] = (*rows, rows[0])
    elif mutation == "duplicate_roster":
        supplied["roster"] = (*supplied["roster"], supplied["roster"][0])
    elif mutation == "list":
        supplied["starter_probabilities"] = list(rows)
    else:
        supplied["native_basis_sha256"] = "a" * 63
    with pytest.raises(ValueError):
        project_unit_point(**supplied)
