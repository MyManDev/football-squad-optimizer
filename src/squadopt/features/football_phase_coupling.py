"""Explicit circular coupling of supplied native role/minute marginals.

This imposes dependence in persistent identity order. It does not learn teammate
dependence, define legal starting XIs or authenticate the supplied native hash.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from fractions import Fraction
from itertools import pairwise

from squadopt.features.football_phase_inputs import POSITIONS, PhasePlayer, PhaseState

COUPLING_VERSION = "persistent_id_circular_positive_role_intervals_v1"
MASS_POLICY = "fixed_full_club_mass_independent_of_participation_v1"


@dataclass(frozen=True, slots=True)
class PhaseMinuteMarginal:
    """Atom order: absent, start bins 1/2/3, cameo bins 1/2/3."""

    player_code: int
    position: str
    probabilities: tuple[float, ...]
    minutes: tuple[float, ...]
    goal_weight90: float
    assist_weight90: float


@dataclass(frozen=True, slots=True)
class PhaseCouplingReceipt:
    marginals: tuple[PhaseMinuteMarginal, ...]
    native_basis_sha256: str
    states: tuple[PhaseState, ...]
    role_indices: tuple[tuple[int, ...], ...]
    version: str = COUPLING_VERSION
    mass_policy: str = MASS_POLICY


def _number(value: object, *, upper: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("Phase coupling values must be numeric without coercion.")
    try:
        number = float(value)
    except OverflowError as error:
        raise ValueError("Phase coupling values must be finite.") from error
    if not math.isfinite(number) or number < 0 or (upper is not None and number > upper):
        raise ValueError("Phase coupling values exceed finite nonnegative support.")
    return number


def _identity(value: object) -> None:
    if type(value) is not int or not 0 < value <= 2**63 - 1:
        raise ValueError("Phase coupling needs positive persistent player identities.")


def _validate_marginal(player: PhaseMinuteMarginal) -> None:
    if not isinstance(player, PhaseMinuteMarginal):
        raise ValueError("Phase coupling requires typed minute marginals.")
    _identity(player.player_code)
    if player.position not in POSITIONS:
        raise ValueError("Phase coupling needs the native FPL scoring position.")
    if (
        type(player.probabilities) is not tuple
        or type(player.minutes) is not tuple
        or len(player.probabilities) != 7
        or len(player.minutes) != 7
    ):
        raise ValueError("Phase coupling requires seven immutable role/minute atoms.")
    probabilities = [_number(value, upper=1) for value in player.probabilities]
    minutes = [_number(value, upper=120) for value in player.minutes]
    if not math.isclose(math.fsum(probabilities), 1, rel_tol=0, abs_tol=1e-12):
        raise ValueError("Phase coupling requires a normalized native role law.")
    if minutes[0] != 0:
        raise ValueError("The absent phase atom must have zero minutes.")
    for index, minute in enumerate(minutes[1:], 1):
        minute_bin = (index - 1) % 3 + 1
        if not (
            (minute_bin == 1 and 0 < minute < 60)
            or (minute_bin == 2 and 60 <= minute < 90)
            or (minute_bin == 3 and 90 <= minute <= 120)
        ):
            raise ValueError("A phase role atom is outside its minute bin.")
    _number(player.goal_weight90)
    _number(player.assist_weight90)


def couple_phase_minutes(
    marginals: tuple[PhaseMinuteMarginal, ...],
    *,
    roster: tuple[int, ...],
    native_basis_sha256: str,
    goal_mass: float,
    assist_mass: float,
    physical_goal_mass: float,
) -> PhaseCouplingReceipt:
    """Preserve seven atoms using an explicit bounded, imposed joint law.

    The caller supplies and separately binds the complete roster and source.
    Positive atoms are not renormalized. Absence is their complement, checked
    against the supplied atom within 1e-12. Exact binary-float fractions prevent
    tiny intervals from disappearing during endpoint comparisons.
    """
    if type(marginals) is not tuple or not marginals or len(marginals) > 170:
        raise ValueError("Phase coupling needs a bounded immutable full-club population.")
    if type(roster) is not tuple or not roster:
        raise ValueError("Phase coupling needs an explicit immutable complete roster.")
    for identity in roster:
        _identity(identity)
    for player in marginals:
        _validate_marginal(player)
    codes = [player.player_code for player in marginals]
    if (
        len(set(roster)) != len(roster)
        or len(set(codes)) != len(codes)
        or set(codes) != set(roster)
    ):
        raise ValueError("Phase coupling marginals differ from the complete unique roster.")
    if not isinstance(native_basis_sha256, str) or not re.fullmatch(
        r"[0-9a-f]{64}", native_basis_sha256
    ):
        raise ValueError("Phase coupling needs the full native artifact SHA256.")
    goal = _number(goal_mass)
    assist = _number(assist_mass)
    physical = _number(physical_goal_mass)
    if goal > physical or assist > physical:
        raise ValueError("Phase credited mass cannot exceed physical goals.")
    ordered = tuple(sorted(marginals, key=lambda player: player.player_code))
    boundaries = {Fraction(0), Fraction(1)}
    intervals: list[tuple[Fraction, ...]] = []
    cursor = Fraction(0)
    for player in ordered:
        atoms = tuple(Fraction(float(p)) for p in player.probabilities[1:])
        positive = sum(atoms, Fraction(0))
        if positive > 1:
            raise ValueError("Positive phase atoms exceed one; no renormalization is applied.")
        endpoint = [cursor % 1]
        for atom in atoms:
            endpoint.append(endpoint[-1] + atom)
        boundaries.update(value % 1 for value in endpoint)
        intervals.append(tuple(endpoint))
        cursor += positive
    endpoints = sorted(boundaries)
    states: list[PhaseState] = []
    assignments: list[tuple[int, ...]] = []
    for lower, upper in pairwise(endpoints):
        midpoint = (lower + upper) / 2
        indices = []
        for interval in intervals:
            local = midpoint if midpoint >= interval[0] else midpoint + 1
            indices.append(
                next((i for i in range(1, 7) if interval[i - 1] <= local < interval[i]), 0)
            )
        players = tuple(
            PhasePlayer(p.player_code, p.position, p.minutes[i], p.goal_weight90, p.assist_weight90)
            for p, i in zip(ordered, indices, strict=True)
        )
        if physical > 0 and not any(player.minutes > 0 for player in players):
            raise ValueError("Fixed physical mass has an all-absent phase state.")
        for mass, name in ((goal, "goal_weight90"), (assist, "assist_weight90")):
            if mass > 0 and not any(p.minutes > 0 and getattr(p, name) > 0 for p in players):
                raise ValueError("Fixed credited mass lacks an active allocation recipient.")
        weight = float(upper - lower)
        if weight <= 0:
            raise ValueError("A phase interval is below representable positive probability.")
        states.append(
            PhaseState(f"circle-{len(states):04d}", weight, players, goal, assist, physical)
        )
        assignments.append(tuple(indices))
    if len(states) > 6 * len(ordered) + 1:
        raise ValueError("Phase coupling exceeded its exact interval bound.")
    for index, player in enumerate(ordered):
        for atom_index, expected in enumerate(player.probabilities):
            actual = math.fsum(
                state.weight
                for state, indices in zip(states, assignments, strict=True)
                if indices[index] == atom_index
            )
            if not math.isclose(actual, expected, rel_tol=0, abs_tol=1e-12):
                raise ValueError("Phase coupling changed a native role marginal.")
    return PhaseCouplingReceipt(ordered, native_basis_sha256, tuple(states), tuple(assignments))
