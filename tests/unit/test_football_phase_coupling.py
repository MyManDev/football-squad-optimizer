from __future__ import annotations

import math
from dataclasses import FrozenInstanceError, replace

import pytest

from squadopt.features import football_phase_coupling as coupling_module
from squadopt.features.football_phase_coupling import (
    COUPLING_VERSION,
    MAX_COUPLING_PLAYERS,
    PhaseMinuteMarginal,
    couple_phase_minutes,
)
from squadopt.features.football_phase_inputs import MAX_PHASE_STATES

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


@pytest.mark.parametrize("tiny", [math.nextafter(0.0, 1.0), 1e-17])
def test_tiny_positive_atom_after_nonzero_cursor_is_not_silently_discarded(tiny):
    first = player(1, (0.7, 0.1, 0.2, 0, 0, 0, 0))
    second = player(2, (1.0, 0, 0, 0, 0, tiny, 0))
    result = coupled((first, second), goal_mass=0, assist_mass=0, physical_goal_mass=0)
    weights = [
        state.weight
        for state, roles in zip(result.states, result.role_indices, strict=True)
        if roles[1] == 5
    ]
    assert weights == [tiny]


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
        {"assist_mass": 2},
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


@pytest.mark.parametrize("index,bad_minute", [(1, 60), (2, 59), (3, 89), (4, 60), (5, 59), (6, 89)])
def test_every_start_and_cameo_atom_has_its_own_minute_bin(index, bad_minute):
    minutes = list(MINUTES)
    minutes[index] = bad_minute
    marginal = replace(player(), minutes=tuple(minutes))
    with pytest.raises(ValueError, match="outside its minute bin"):
        coupled((marginal,), goal_mass=0, assist_mass=0, physical_goal_mass=0)


@pytest.mark.parametrize("head", ["goals", "assists"])
def test_each_credited_mass_requires_its_own_active_recipient(head):
    always = player(probabilities=(0, 1, 0, 0, 0, 0, 0))
    marginal = replace(always, **{("goal_weight90" if head == "goals" else "assist_weight90"): 0})
    with pytest.raises(ValueError, match="active allocation recipient"):
        coupled((marginal,), goal_mass=int(head == "goals"), assist_mass=int(head == "assists"))


def test_population_cap_is_derived_from_shared_state_limit_and_enforced():
    assert MAX_COUPLING_PLAYERS == (MAX_PHASE_STATES - 1) // 6 == 170
    absent = tuple(player(code, (1, 0, 0, 0, 0, 0, 0)) for code in range(1, 172))
    assert len(coupled(absent[:170], goal_mass=0, assist_mass=0, physical_goal_mass=0).states) == 1
    with pytest.raises(ValueError, match="bounded immutable full-club population"):
        coupled(absent, goal_mass=0, assist_mass=0, physical_goal_mass=0)


def test_native_normalization_tolerance_is_not_loosened_to_one_part_per_million():
    marginal = player(probabilities=(0.500000005, 0.5, 0, 0, 0, 0, 0))
    with pytest.raises(ValueError, match="normalized native role law"):
        coupled((marginal,), goal_mass=0, assist_mass=0, physical_goal_mass=0)


def test_constructed_marginal_self_check_refuses_small_state_weight_drift(monkeypatch):
    state_type = coupling_module.PhaseState

    def drifted_state(identifier, weight, *arguments):
        return state_type(identifier, weight + 5e-9, *arguments)

    monkeypatch.setattr(coupling_module, "PhaseState", drifted_state)
    marginal = player(probabilities=(0, 1, 0, 0, 0, 0, 0))
    with pytest.raises(ValueError, match="changed a native role marginal"):
        coupled((marginal,))


def test_exact_positive_mass_can_refuse_a_float_normalized_native_law():
    probabilities = (0, 0.1, 0.2, 0.3, 0.4, 0, 0)
    assert math.fsum(probabilities) == 1.0
    with pytest.raises(ValueError, match="Positive phase atoms exceed one"):
        coupled((player(probabilities=probabilities),))


def test_receipt_preserves_supplied_digest_and_literal_mass_policy():
    result = coupled((player(probabilities=(0, 1, 0, 0, 0, 0, 0)),), native_basis_sha256="ab" * 32)
    assert result.native_basis_sha256 == "ab" * 32
    assert result.mass_policy == "fixed_full_club_mass_independent_of_participation_v1"
    assert result.version == "persistent_id_circular_positive_role_intervals_v1"
