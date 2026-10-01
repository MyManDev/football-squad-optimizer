"""Per-fixture football components: the v1 model's match-by-match forecast for one capture.

``football_fixture_components_v1`` holds, for every scheduled player-fixture in the weeks a
capture's served forecast covers, the outputs ``FixtureFootballModel.predict`` returns for it.
The weekly ``live_football_forecast_v1`` rows are built from these same outputs, and the
components document is bound to the served document of the same producer call by that
document's fingerprint. A consumer that scores shared match worlds reads the model's own
components rather than reconstructing joint match events from weekly totals.

The capture's availability is carried, not applied. The weekly document leaves availability
to its reader, which scales each player by ``apply_availability``; each component row carries
that rule's multiplier for its player, so a consumer applies the same number the reader does.
The model has no separate head for bonus, saves or cards: they sit inside
``residual_if_appearance``.
"""

from __future__ import annotations

from typing import Final

import numpy as np
import pandas as pd

FIXTURE_COMPONENTS_CONTRACT: Final = "football_fixture_components_v1"

#: Which match, which side of it and which player a row describes.
IDENTITY_COLUMNS: Final[tuple[str, ...]] = (
    "GW",
    "fixture",
    "kickoff",
    "club",
    "opponent",
    "home",
    "player_code",
    "position",
)

#: The model's own per-fixture outputs, as ``FixtureFootballModel.predict`` names them.
COMPONENT_COLUMNS: Final[tuple[str, ...]] = (
    "expected_minutes",
    "appearance_probability",
    "p60",
    "team_goal_rate",
    "opponent_goal_rate",
    "goals",
    "goals_share",
    "assists",
    "assists_share",
    "clean_sheet_probability",
    "defcon_probability",
    "defcon_rate90",
    "defcon_dispersion",
    "residual_if_appearance",
    "raw_expected_points",
    "expected_points",
    "minute_probability_0",
    "minute_probability_1",
    "minute_probability_2",
    "minute_probability_3",
    "minute_value_0",
    "minute_value_1",
    "minute_value_2",
    "minute_value_3",
)

#: Components that are probabilities or shares, and so must lie in [0, 1].
UNIT_INTERVAL_COLUMNS: Final[tuple[str, ...]] = (
    "appearance_probability",
    "p60",
    "goals_share",
    "assists_share",
    "clean_sheet_probability",
    "defcon_probability",
    "minute_probability_0",
    "minute_probability_1",
    "minute_probability_2",
    "minute_probability_3",
)


def component_rows(
    components: pd.DataFrame, multipliers: dict[int, float]
) -> list[dict[str, object]]:
    """The declared columns of every player-fixture, with its player's availability multiplier.

    Refuses a frame that lacks a declared column, repeats a player-fixture, holds a nonfinite
    component, a probability outside [0, 1] or a player with no multiplier, rather than
    publishing a row a consumer would read as the model's.
    """

    missing = [name for name in (*IDENTITY_COLUMNS, *COMPONENT_COLUMNS) if name not in components]
    if missing:
        raise ValueError(f"Fixture components lack the declared columns {missing}.")
    if components.duplicated(["fixture", "player_code"]).any():
        raise ValueError("A player-fixture appears twice in the components.")
    frame = components.loc[:, [*IDENTITY_COLUMNS, *COMPONENT_COLUMNS]].sort_values(
        ["GW", "kickoff", "fixture", "player_code"], kind="stable"
    )
    values = frame.loc[:, list(COMPONENT_COLUMNS)].to_numpy(dtype=float)
    if not np.isfinite(values).all():
        raise ValueError("A fixture component is not finite.")
    unit = frame.loc[:, list(UNIT_INTERVAL_COLUMNS)].to_numpy(dtype=float)
    if (unit < 0).any() or (unit > 1).any():
        raise ValueError("A fixture probability or share lies outside [0, 1].")
    rows: list[dict[str, object]] = []
    for record in frame.to_dict("records"):
        player = int(record["player_code"])
        if player not in multipliers:
            raise ValueError(f"Player {player} has no availability multiplier.")
        rows.append(
            {
                "GW": int(record["GW"]),
                "fixture": int(record["fixture"]),
                "kickoff": pd.Timestamp(record["kickoff"]).isoformat(),
                "club": int(record["club"]),
                "opponent": int(record["opponent"]),
                "home": round(float(record["home"])),
                "player_code": player,
                "position": str(record["position"]),
                **{name: float(record[name]) for name in COMPONENT_COLUMNS},
                "availability_multiplier": float(multipliers[player]),
            }
        )
    return rows


__all__: tuple[str, ...] = (
    "COMPONENT_COLUMNS",
    "FIXTURE_COMPONENTS_CONTRACT",
    "IDENTITY_COLUMNS",
    "UNIT_INTERVAL_COLUMNS",
    "component_rows",
)
