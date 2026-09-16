"""Player vocabulary shared by data, prediction, and optimization."""

from numbers import Integral
from typing import Literal, TypeAlias

import pandas as pd

Position: TypeAlias = Literal["GK", "DEF", "MID", "FWD"]
POSITIONS: tuple[Position, ...] = ("GK", "DEF", "MID", "FWD")
REQUIRED_COLUMNS: tuple[str, ...] = (
    "player_id",
    "name",
    "team_id",
    "position",
    "price_tenths",
    "expected_points",
)

#: Recognised names a projection may carry and need not. Absent fields are never fabricated.
#:
#: The tier exists because the alternative breaks a week rather than narrowing it: a required
#: column means every producer must supply it, so a projection without a start probability
#: would stop being a projection and become an error, and a member whose week the model has no
#: opinion about would get no plan instead of the plan they get today. Absent is not zero and
#: absent is not broken.
#:
#: **A consumer that meets an absent optional column applies its existing rule unchanged.**
#: Reading a missing start probability as zero would bench every player nobody modelled, which
#: is a larger behaviour change than supplying the column at all, and in the wrong direction.
#:
#: ``start_probability`` is the probability the player starts, which the pre-registration
#: writes as ``p_start = p_appearance * q_start_given_appearance``
#: (``docs/participation_model_prereg.md``) -- the composition, not the conditional ``q`` the
#: model fits. The name is the one the component prediction contract already uses
#: (``prediction/components.py``), where the column exists and is deliberately left absent:
#: ``start_component_status`` returns ``"unavailable"`` and every component row sets it to
#: ``None``. One quantity keeps one name across the boundary it crosses, so the day that
#: column carries a number it does not have to be renamed to reach the solve.
#:
#: Nothing produces it into a live projection today. ``application/projection_handoff`` narrows
#: the component snapshot to ``player_id`` and ``expected_points`` before it becomes a
#: projection, which is the producer-side half and is left alone here: widening it while every
#: value is ``None`` would add an all-absent column to every live run for no consumer.
OPTIONAL_COLUMNS: tuple[str, ...] = ("start_probability",)

#: Every recognised projection column, required first then optional. The shape ``data/schema``
#: has carried one layer down since it was written, now that the projection needs it too.
CANONICAL_COLUMNS: tuple[str, ...] = (*REQUIRED_COLUMNS, *OPTIONAL_COLUMNS)


def canonical_columns_present(players: pd.DataFrame) -> list[str]:
    """The required columns, then whichever optional ones this frame actually carries.

    What a narrowing point wants: it must not drop an optional column the producer supplied,
    and it must not invent one the producer left out. Column order is the contract's, not the
    frame's, so two frames carrying the same columns narrow to the same shape.
    """

    return [*REQUIRED_COLUMNS, *(name for name in OPTIONAL_COLUMNS if name in players.columns)]


def sort_players_by_id(players: pd.DataFrame) -> pd.DataFrame:
    """Return the stable player ordering used by the model and its fingerprints."""

    player_ids = players["player_id"].tolist()
    if player_ids and isinstance(player_ids[0], Integral):
        order = sorted(range(len(players)), key=lambda index: int(player_ids[index]))
    else:
        order = sorted(range(len(players)), key=lambda index: str(player_ids[index]))
    return players.iloc[order].reset_index(drop=True).copy(deep=True)
