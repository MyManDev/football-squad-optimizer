"""Per-fixture football components: the v1 model's match-by-match forecast for one capture.

``football_fixture_components_v1`` holds, for every scheduled player-fixture in the weeks a
capture's served forecast covers, the outputs ``FixtureFootballModel.predict`` returns for it.
The weekly ``live_football_forecast_v1`` rows are built from these same outputs, and the
components document is bound to the served document of the same producer call by that
document's fingerprint. A consumer that scores shared match worlds reads the model's own
components rather than reconstructing joint match events from weekly totals. ``club`` and
``opponent`` are FPL team codes, not the served rows' ``team_id``, and ``kickoff`` is ISO 8601
in UTC with a ``+00:00`` offset.

The capture's availability is carried in the header as ``captured_availability`` and applied
to no row. ``read_football_forecast`` scales each player's weekly expected points and weekly
appearance probability by one ``apply_availability`` multiplier, the same in every week. A
consumer that draws match worlds applies it the same way: one eligibility state per player and
week, shared by all of that week's fixtures. Scaling each fixture's appearance probability by
it instead reproduces weekly expected points but not the weekly appearance probability of a
double gameweek. The multiplier stays off the rows because the contextual model's component
rows carry an ``availability_multiplier`` that is already applied to their minutes.
"""

from __future__ import annotations

import math
from collections.abc import Collection, Mapping
from typing import Final

import numpy as np
import pandas as pd

FIXTURE_COMPONENTS_CONTRACT: Final = "football_fixture_components_v1"

#: How ``captured_availability`` is applied: once per player and week, never per fixture.
AVAILABILITY_SCOPE: Final = "one_state_per_player_week"

#: What a consumer must know that the weekly document's own limitations do not say.
COMPONENT_LIMITATIONS: Final[tuple[str, ...]] = (
    "Captured availability is one state per player and week, shared by all of that week's "
    "fixtures; it is carried in captured_availability and applied to no row.",
    "residual_if_appearance holds every scoring item without its own head: bonus, saves, "
    "cards, goals conceded by goalkeepers and defenders, own goals, and penalties saved "
    "or missed.",
)

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

#: Rates and expectations a match-world sampler draws from, and so must not be negative.
NONNEGATIVE_COLUMNS: Final[tuple[str, ...]] = (
    "expected_minutes",
    "team_goal_rate",
    "opponent_goal_rate",
    "goals",
    "assists",
    "defcon_rate90",
)

POSITIONS: Final[tuple[str, ...]] = ("GK", "DEF", "MID", "FWD")

#: The longest minute value a bin may carry, the sampler's own bound.
MINUTE_CEILING: Final = 120.0


def _refuse_inconsistent_sides(frame: pd.DataFrame) -> None:
    """Every fixture has one home and one away club, each the other's opponent and goal rate."""

    for _, match in frame.groupby("fixture", sort=True):
        clubs = sorted({int(club) for club in match.club.tolist()})
        sides = {club: match.loc[match.club.eq(club)] for club in clubs}
        homes = sorted(round(float(side.home.iloc[0])) for side in sides.values())
        if len(sides) != 2 or homes != [0, 1]:
            raise ValueError("A fixture lacks one home and one away side.")
        (first, one), (second, other) = sides.items()
        for side, rival, opponent in ((one, other, second), (other, one, first)):
            if not side.opponent.eq(opponent).all() or side.home.nunique() != 1:
                raise ValueError("A fixture's sides name inconsistent opponents.")
            rate = float(side.team_goal_rate.iloc[0])
            if not np.allclose(side.team_goal_rate, rate) or not np.allclose(
                side.opponent_goal_rate, float(rival.team_goal_rate.iloc[0])
            ):
                raise ValueError("A fixture's sides carry inconsistent goal rates.")


def component_rows(
    components: pd.DataFrame, *, model_version: str, players: Collection[int]
) -> list[dict[str, object]]:
    """The declared columns of every player-fixture, refusing what a consumer would misread.

    Refuses a frame that lacks a declared column, repeats a player-fixture, holds a row of
    another model version, an unknown position, a nonfinite or negative quantity, a
    probability outside [0, 1], minute probabilities that do not sum to one, a minute value
    outside [0, 120], expected points other than the clipped raw points, a fixture without
    two consistent sides, or a player outside ``players``, rather than publishing a row a
    consumer would read as the model's.
    """

    missing = [
        name
        for name in (*IDENTITY_COLUMNS, *COMPONENT_COLUMNS, "model_version")
        if name not in components
    ]
    if missing:
        raise ValueError(f"Fixture components lack the declared columns {missing}.")
    if components.duplicated(["fixture", "player_code"]).any():
        raise ValueError("A player-fixture appears twice in the components.")
    if set(components.model_version.astype(str)) != {model_version}:
        raise ValueError(f"Fixture components hold rows of another model than {model_version}.")
    if not components.position.isin(POSITIONS).all():
        raise ValueError("A fixture component names an unknown position.")
    frame = components.loc[:, [*IDENTITY_COLUMNS, *COMPONENT_COLUMNS]].sort_values(
        ["GW", "kickoff", "fixture", "player_code"], kind="stable"
    )
    values = frame.loc[:, list(COMPONENT_COLUMNS)].to_numpy(dtype=float)
    if not np.isfinite(values).all():
        raise ValueError("A fixture component is not finite.")
    if (frame.loc[:, list(NONNEGATIVE_COLUMNS)].to_numpy(dtype=float) < 0).any() or (
        frame.defcon_dispersion.to_numpy(dtype=float) <= 0
    ).any():
        raise ValueError(
            "A fixture rate or expectation is negative, or its DEFCON dispersion is not positive."
        )
    unit = frame.loc[:, list(UNIT_INTERVAL_COLUMNS)].to_numpy(dtype=float)
    if (unit < 0).any() or (unit > 1).any():
        raise ValueError("A fixture probability or share lies outside [0, 1].")
    bins = frame.loc[:, [f"minute_probability_{b}" for b in range(4)]].to_numpy(dtype=float)
    if not np.allclose(bins.sum(axis=1), 1.0):
        raise ValueError("A fixture's minute probabilities do not sum to one.")
    minutes = frame.loc[:, [f"minute_value_{b}" for b in range(4)]].to_numpy(dtype=float)
    if (minutes < 0).any() or (minutes > MINUTE_CEILING).any():
        raise ValueError("A fixture minute value lies outside [0, 120].")
    if not np.array_equal(
        frame.expected_points.to_numpy(dtype=float),
        np.maximum(frame.raw_expected_points.to_numpy(dtype=float), 0.0),
    ):
        raise ValueError("A fixture's expected points are not its clipped raw points.")
    if not frame.home.isin((0.0, 1.0)).all():
        raise ValueError("A fixture's home flag is neither 0 nor 1.")
    _refuse_inconsistent_sides(frame)
    known = {int(player) for player in players}
    rows: list[dict[str, object]] = []
    for record in frame.to_dict("records"):
        player = int(record["player_code"])
        if player not in known:
            raise ValueError(f"Player {player} has no captured availability.")
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
            }
        )
    return rows


def captured_availability(
    multipliers: Mapping[int, float], rule: Mapping[str, object]
) -> dict[str, object]:
    """The capture's availability as the reader applies it, carried and not applied.

    ``rule`` is the diagnostics ``apply_availability`` returned with ``multipliers``, so the
    header names the rule version and the two settings that produced them.
    """

    entries = []
    for player, value in sorted((int(p), float(v)) for p, v in multipliers.items()):
        if not math.isfinite(value) or not 0.0 <= value <= 1.0:
            raise ValueError(f"Player {player} has an availability multiplier outside [0, 1].")
        entries.append({"player_code": player, "multiplier": value})
    return {
        "application": "not_applied",
        "scope": AVAILABILITY_SCOPE,
        "rule_contract_version": rule["availability_contract_version"],
        "unknown_is_available": rule["availability_unknown_is_available"],
        "multiplier_floor": rule["availability_multiplier_floor"],
        "multipliers": entries,
    }


__all__: tuple[str, ...] = (
    "AVAILABILITY_SCOPE",
    "COMPONENT_COLUMNS",
    "COMPONENT_LIMITATIONS",
    "FIXTURE_COMPONENTS_CONTRACT",
    "IDENTITY_COLUMNS",
    "MINUTE_CEILING",
    "NONNEGATIVE_COLUMNS",
    "POSITIONS",
    "UNIT_INTERVAL_COLUMNS",
    "captured_availability",
    "component_rows",
)
