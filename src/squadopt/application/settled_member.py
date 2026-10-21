"""A member's captain and transfer contributions from settled, captured FPL picks."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import pandas as pd

from squadopt.data.errors import DataError


@dataclass(frozen=True, slots=True)
class ActualPlayerContribution:
    player_id: int
    name: str
    points: float
    multiplier: int
    counted_points: float


@dataclass(frozen=True, slots=True)
class ActualTransferContribution:
    player_out: str
    player_in: ActualPlayerContribution


@dataclass(frozen=True, slots=True)
class ActualMemberDetails:
    source_snapshot_id: str
    captain: ActualPlayerContribution
    transfers: tuple[ActualTransferContribution, ...]


def settled_member_details(
    outcomes: pd.DataFrame,
    *,
    source_snapshot_id: str,
    picks: Sequence[tuple[int, object]],
    codes: Mapping[int, int],
    names: Mapping[int, str],
    captain: int,
    vice_captain: int,
    transfers: Sequence[tuple[int, int]],
    gross_points: float,
) -> ActualMemberDetails:
    """Read the official multipliers, including autosubs and a vice inheriting the armband.

    Their sum must reproduce the member's settled gross score. An incoming player counts
    once, on their last acquisition in the week; intermediate purchases contribute zero.
    Hits remain a single weekly charge in the existing actual score, never one per move.
    Nothing here solves a plan or treats an unfinished week's running score as final.
    """

    values = dict(zip(outcomes["player_id"], outcomes["total_points"], strict=True))
    if len(values) != len(outcomes):
        raise DataError("The member report has duplicate player outcomes.")
    multipliers: dict[int, int] = {}
    for element, multiplier in picks:
        if type(multiplier) is not int or multiplier not in (0, 1, 2, 3):
            raise DataError("The member report needs the official scoring multipliers.")
        multipliers[element] = multiplier
    if len(multipliers) != 15:
        raise DataError("The member report requires fifteen distinct picks.")

    def player(element: int, *, multiplier: int | None = None) -> ActualPlayerContribution:
        code = codes[element]
        value = float(values[code])
        if not math.isfinite(value) or element not in names:
            raise DataError("The member report requires named, finite player outcomes.")
        factor = multipliers.get(element, 0) if multiplier is None else multiplier
        return ActualPlayerContribution(code, names[element], value, factor, value * factor)

    total = sum(player(element).counted_points for element in multipliers)
    if not math.isclose(total, gross_points, abs_tol=1e-8, rel_tol=0):
        raise DataError("The captured picks do not reproduce the settled member score.")
    scoring_captains = [element for element, factor in multipliers.items() if factor > 1]
    if len(scoring_captains) > 1:
        raise DataError("The captured picks score more than one captain.")
    counted_captain = scoring_captains[0] if scoring_captains else captain
    if counted_captain not in (captain, vice_captain):
        raise DataError("The scoring captain is neither the named captain nor the vice.")
    last_acquisition = {incoming: index for index, (incoming, _) in enumerate(transfers)}
    rows = []
    for index, (element_in, element_out) in enumerate(transfers):
        incoming = player(
            element_in,
            multiplier=multipliers.get(element_in, 0)
            if last_acquisition[element_in] == index
            else 0,
        )
        outgoing = names[element_out]
        rows.append(ActualTransferContribution(outgoing, incoming))
    return ActualMemberDetails(source_snapshot_id, player(counted_captain), tuple(rows))
