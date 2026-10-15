from __future__ import annotations

import math
from dataclasses import FrozenInstanceError, replace

import pytest

from squadopt.features.football_phase_coupling import (
    COUPLING_VERSION,
    PhaseMinuteMarginal,
    couple_phase_minutes,
)

MINUTES = (0.0, 40.0, 70.0, 90.0, 15.0, 65.0, 100.0)


def player(code=1, probabilities=(0.25, 0.25, 0.0, 0.5, 0.0, 0.0, 0.0)):
    return PhaseMinuteMarginal(code, "MID", probabilities, MINUTES, 1.0, 2.0)


def coupled(players, **kwargs):
    arguments = dict(
        roster=tuple(p.player_code for p in players),
        native_basis_sha256="a" * 64,
        goal_mass=1.0,
        assist_mass=0.8,
        physical_goal_mass=1.2,
    )
    arguments.update(kwargs)
    return couple_phase_minutes(players, **arguments)


def test_hand_computed_circle_conserves_atoms_and_fixed_club_mass():
    # A appears on [0,.75), B on [.75,1) union [0,.25).
    a = player()
    b = player(2, (0.5, 0.0, 0.0, 0.5, 0.0, 0.0, 0.0))
    result = coupled((a, b))
    assert result.version == COUPLING_VERSION
    assert result.role_indices == ((1, 3), (3, 0), (0, 3))
    assert [state.weight for state in result.states] == [0.25, 0.5, 0.25]
    assert [[p.minutes for p in state.players] for state in result.states] == [
        [40, 90],
        [90, 0],
        [0, 90],
    ]
    for index, marginal in enumerate(result.marginals):
        assert math.fsum(s.weight * s.players[index].minutes for s in result.states) == sum(
            p * m for p, m in zip(marginal.probabilities, marginal.minutes, strict=True)
        )
    assert math.fsum(s.weight * s.goal_mass for s in result.states) == 1
    assert math.fsum(s.weight * s.assist_mass for s in result.states) == 0.8
    assert math.fsum(s.weight * s.physical_goal_mass for s in result.states) == 1.2
    assert coupled((b, a)) == result


def test_every_role_atom_keeps_its_distinct_duration():
    original = player(probabilities=(0, 0.125, 0.25, 0.125, 0.125, 0.25, 0.125))
    result = coupled((original,))
    assert result.role_indices == tuple((atom,) for atom in range(1, 7))
    assert tuple(s.weight for s in result.states) == original.probabilities[1:]
    assert tuple(s.players[0].minutes for s in result.states) == original.minutes[1:]
    with pytest.raises(FrozenInstanceError):
        result.version = "changed"


def test_structural_absence_is_retained_when_club_mass_is_zero():
    absent = player(probabilities=(1, 0, 0, 0, 0, 0, 0))
    result = coupled((absent,), goal_mass=0, assist_mass=0, physical_goal_mass=0)
    assert len(result.states) == 1
    assert result.role_indices == ((0,),)
    assert result.states[0].weight == 1


def test_subnormal_positive_atom_is_not_silently_discarded():
    tiny = math.nextafter(0.0, 1.0)
    original = player(probabilities=(1, tiny, 0, 0, 0, 0, 0))
    result = coupled((original,), goal_mass=0, assist_mass=0, physical_goal_mass=0)
    assert result.states[0].weight == tiny
    assert result.role_indices[0] == (1,)


@pytest.mark.parametrize(
    "mutation",
    [
        {"player_code": True},
        {"player_code": 0},
        {"position": "CB"},
        {"probabilities": [0, 1, 0, 0, 0, 0, 0]},
        {"probabilities": (0, 1, 0)},
        {"probabilities": (0, True, 0, 0, 0, 0, 0)},
        {"probabilities": (0, float("nan"), 0, 0, 0, 0, 0)},
        {"probabilities": (0.2, 0.9, 0, 0, 0, 0, 0)},
        {"probabilities": (0, 1, 1e-13, 0, 0, 0, 0)},
        {"minutes": (1, 40, 70, 90, 15, 65, 100)},
        {"minutes": (0, 60, 70, 90, 15, 65, 100)},
        {"minutes": (0, 40, 59, 90, 15, 65, 100)},
        {"minutes": (0, 40, 70, 89, 15, 65, 100)},
        {"minutes": (0, 40, 70, 90, 15, 65, 121)},
        {"goal_weight90": float("inf")},
        {"assist_weight90": -1},
    ],
)
def test_invalid_native_atoms_refuse(mutation):
    with pytest.raises(ValueError):
        coupled((replace(player(), **mutation),), goal_mass=0, assist_mass=0, physical_goal_mass=0)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"roster": (1, 1)},
        {"roster": (2,)},
        {"roster": [1]},
        {"native_basis_sha256": "A" * 64},
        {"native_basis_sha256": "a" * 63},
        {"goal_mass": True},
        {"assist_mass": float("nan")},
        {"goal_mass": 2},
    ],
)
def test_ambiguous_roster_hash_or_mass_refuses(kwargs):
    with pytest.raises(ValueError):
        coupled((player(probabilities=(0, 1, 0, 0, 0, 0, 0)),), **kwargs)


def test_no_state_is_dropped_to_make_fixed_mass_supported():
    with pytest.raises(ValueError, match="all-absent"):
        coupled((player(),))
    always = player(2, (0, 1, 0, 0, 0, 0, 0))
    with pytest.raises(ValueError, match="recipient"):
        coupled((player(), replace(always, goal_weight90=0)))


def test_complete_40_player_club_preserves_all_marginals_with_bounded_states():
    originals = tuple(
        player(code, (0.5, 0.125, 0.125, 0.125, 0.0625, 0.03125, 0.03125)) for code in range(1, 41)
    )
    result = coupled(originals)
    assert len(result.states) <= 6 * len(originals) + 1 <= 1024
    assert math.fsum(state.weight for state in result.states) == 1
    assert all(sum(p.minutes > 0 for p in state.players) == 20 for state in result.states)
    for index, original in enumerate(originals):
        for atom, expected in enumerate(original.probabilities):
            assert (
                math.fsum(
                    state.weight
                    for state, indices in zip(result.states, result.role_indices, strict=True)
                    if indices[index] == atom
                )
                == expected
            )


def test_population_shape_refuses_before_construction():
    for values in ((), [player()], (player(), player()), ("bad",)):
        with pytest.raises(ValueError):
            couple_phase_minutes(
                values,
                roster=(1,),
                native_basis_sha256="a" * 64,
                goal_mass=0,
                assist_mass=0,
                physical_goal_mass=0,
            )
