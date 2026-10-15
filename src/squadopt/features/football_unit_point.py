"""A declared deterministic XI forecast from complete native starter probabilities.

The point maximizes independent Bernoulli mass subject to exactly one goalkeeper
and ten outfield players. This independence is a modeling assumption. The point
is neither a calibrated joint lineup law nor a replacement for focal minute laws.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

from squadopt.features.football_unit_inputs import (
    ClubUnit,
    UnitPlayer,
    finite_number,
    positive_id,
)

UNIT_POINT_VERSION = "native_starter_constrained_map_point_v1"


@dataclass(frozen=True, slots=True)
class UnitStarterProbability:
    player_id: int
    probability: float

    def __post_init__(self) -> None:
        positive_id(self.player_id, "starter player_id")
        finite_number(self.probability, "starter probability")
        if not 0 <= self.probability <= 1:
            raise ValueError("Starter probability must be between zero and one.")


@dataclass(frozen=True, slots=True)
class UnitPointReceipt:
    unit: ClubUnit
    roster: tuple[UnitPlayer, ...]
    starter_probabilities: tuple[UnitStarterProbability, ...]
    native_basis_sha256: str
    independent_joint_log_mass: float
    version: str = UNIT_POINT_VERSION
    interpretation: str = "deterministic_point_not_calibrated_joint_lineup_probability"
    tie_policy: str = "ascending_persistent_player_id"


def project_unit_point(
    *,
    club: int,
    roster: tuple[UnitPlayer, ...],
    starter_probabilities: tuple[UnitStarterProbability, ...],
    native_basis_sha256: str,
) -> UnitPointReceipt:
    """Select a feasible maximum-mass XI, retaining the caller's complete basis.

    The caller binds the complete current club roster and native artifact hash.
    This pure function validates their shape, not their external provenance.
    Within each position group, Bernoulli odds are monotone in probability, so
    selecting the highest probabilities maximizes mass at fixed group size.
    Structural zeros and ones remain constraints, never numerical floors.
    """
    positive_id(club, "club")
    if not isinstance(native_basis_sha256, str) or not re.fullmatch(
        r"[a-f0-9]{64}", native_basis_sha256
    ):
        raise ValueError("A unit point requires the exact native basis SHA256.")
    if (
        type(roster) is not tuple
        or not roster
        or any(not isinstance(player, UnitPlayer) for player in roster)
    ):
        raise ValueError("A unit point requires an immutable complete typed club roster.")
    if type(starter_probabilities) is not tuple or any(
        not isinstance(row, UnitStarterProbability) for row in starter_probabilities
    ):
        raise ValueError("A unit point requires immutable typed starter probabilities.")
    players = {player.player_id: player for player in roster}
    probabilities = {row.player_id: row.probability for row in starter_probabilities}
    if (
        len(players) != len(roster)
        or len(probabilities) != len(starter_probabilities)
        or players.keys() != probabilities.keys()
    ):
        raise ValueError("Starter probabilities must cover each roster identity exactly once.")

    selected: set[int] = set()
    for goalkeeper, count in ((True, 1), (False, 10)):
        group = [player for player in roster if (player.position == "GK") == goalkeeper]
        if (
            sum(probabilities[player.player_id] == 1 for player in group) > count
            or sum(probabilities[player.player_id] > 0 for player in group) < count
        ):
            raise ValueError("The required XI has zero support under native starter constraints.")
        ordered = sorted(
            group, key=lambda player: (-probabilities[player.player_id], player.player_id)
        )
        selected.update(player.player_id for player in ordered[:count])

    log_mass = math.fsum(
        math.log(probability) if identity in selected else math.log1p(-probability)
        for identity, probability in sorted(probabilities.items())
    )
    if not math.isfinite(log_mass):
        raise ValueError("The selected XI must have finite positive independent joint support.")
    return UnitPointReceipt(
        unit=ClubUnit(club, tuple(players[identity] for identity in sorted(selected))),
        roster=tuple(players[identity] for identity in sorted(players)),
        starter_probabilities=tuple(sorted(starter_probabilities, key=lambda row: row.player_id)),
        native_basis_sha256=native_basis_sha256,
        independent_joint_log_mass=log_mass,
    )
