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
#: ``p_start`` is the pre-registration's own name for the composed probability that a player
#: starts -- ``p_appearance * q_start_given_appearance`` (``docs/participation_model_prereg.md``)
#: -- and not the conditional ``q`` the model fits. Nothing in this repository produces it into
#: a live projection today; declaring it is what lets a consumer be written against it.
OPTIONAL_COLUMNS: tuple[str, ...] = ("p_start",)

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
