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

from squadopt.prediction.football import JOINT_ROLE_MODEL_VERSIONS
from squadopt.prediction.football_minutes_role import (
    ROLE_COMPONENT_COLUMNS,
    ROLE_METADATA_COLUMNS,
    ROLE_MINUTE_VERSION,
)

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


def _role_number(value: object) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float, np.integer, np.floating))
        or not math.isfinite(float(value))
    ):
        raise ValueError("A joint-role component is not a finite number.")
    return float(value)


def role_component_record(record: Mapping[str, object]) -> dict[str, object]:
    """Validate optional joint-role columns without changing frozen v1 records."""
    missing = set((*ROLE_COMPONENT_COLUMNS, *ROLE_METADATA_COLUMNS)) - record.keys()
    if missing:
        raise ValueError("Joint-role components lack their declared minute fields.")
    result: dict[str, object] = {}
    for name in ROLE_COMPONENT_COLUMNS:
        raw = record[name]
        if (
            raw is None
            or raw is pd.NA
            or (isinstance(raw, (float, np.floating)) and math.isnan(float(raw)))
        ):
            result[name] = None
        else:
            result[name] = _role_number(raw)
    for name in ("known_start_label_rows", "unknown_start_label_rows"):
        value = record[name]
        if isinstance(value, bool) or not isinstance(value, (int, np.integer)) or value < 0:
            raise ValueError("Role training counts must be nonnegative integers.")
        result[name] = int(value)
    result.update(
        {
            name: record[name]
            for name in ("minute_role_version", "minute_role_status", "minute_prior_rows")
        }
    )
    if result["minute_role_version"] != ROLE_MINUTE_VERSION or result["minute_prior_rows"] != 10.0:
        raise ValueError("Unknown joint-role minute version or fixed prior.")
    q = _role_number(record["appearance_probability"])
    zero = result["zero_probability"]
    unknown = result["unknown_role_probability"]
    conditional = result["expected_minutes_if_appearance"]
    if zero is None or unknown is None or conditional is None:
        raise ValueError("Joint-role zero, unknown and conditional minutes must be declared.")
    if not np.isclose(_role_number(zero), 1 - q) or not 0 <= _role_number(unknown) <= 1:
        raise ValueError("Joint-role zero or unknown probability is inconsistent.")
    if not np.isclose(q * _role_number(conditional), _role_number(record["expected_minutes"])):
        raise ValueError("Joint-role conditional and expected minutes disagree.")
    role_fields = [name for name in ROLE_COMPONENT_COLUMNS if name.startswith(("start_", "cameo_"))]
    if result["minute_role_status"] == "unavailable_no_known_start_labels":
        if (
            result["known_start_label_rows"] != 0
            or not np.isclose(_role_number(unknown), q)
            or any(result[name] is not None for name in role_fields)
        ):
            raise ValueError("Unknown starting roles must remain null, not inferred from minutes.")
        return result
    if (
        result["minute_role_status"] != "fitted_known_start_labels"
        or result["known_start_label_rows"] == 0
        or unknown != 0
        or any(result[name] is None for name in role_fields)
    ):
        raise ValueError("Joint-role fitted status disagrees with its training or fields.")
    total = 0.0
    expected_minutes = 0.0
    p60 = 0.0
    marginal = np.zeros(3)
    weighted_minutes = np.zeros(3)
    for role in ("start", "cameo"):
        probabilities = np.array(
            [result[f"{role}_minute_probability_{b}"] for b in (1, 2, 3)], float
        )
        minutes = np.array([result[f"{role}_minute_value_{b}"] for b in (1, 2, 3)], float)
        if ((probabilities < 0) | (probabilities > 1)).any() or not (
            0 < minutes[0] < 60 and 60 <= minutes[1] < 90 and 90 <= minutes[2] <= 120
        ):
            raise ValueError("Joint-role probability or minute support is invalid.")
        if not np.isclose(probabilities.sum(), _role_number(result[role + "_probability"])):
            raise ValueError("Starting role mass disagrees with its minute bins.")
        total += float(probabilities.sum())
        expected_minutes += float(probabilities @ minutes)
        p60 += float(probabilities[1:].sum())
        marginal += probabilities
        weighted_minutes += probabilities * minutes
    if (
        not np.isclose(total, q)
        or not np.isclose(expected_minutes, _role_number(record["expected_minutes"]))
        or not np.isclose(p60, _role_number(record["p60"]))
    ):
        raise ValueError("Joint-role marginals disagree with the scoring components.")
    for b in (1, 2, 3):
        probability = _role_number(record[f"minute_probability_{b}"])
        value = _role_number(record[f"minute_value_{b}"])
        if not np.isclose(probability, marginal[b - 1]) or not np.isclose(
            probability * value, weighted_minutes[b - 1]
        ):
            raise ValueError("Collapsed minute bins disagree with the joint support.")
    return result


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
    joint_role = model_version in JOINT_ROLE_MODEL_VERSIONS
    extras = [*ROLE_COMPONENT_COLUMNS, *ROLE_METADATA_COLUMNS] if joint_role else []
    if joint_role and not set(extras) <= set(components):
        raise ValueError("Joint-role components lack their declared minute fields.")
    frame = components.loc[:, [*IDENTITY_COLUMNS, *COMPONENT_COLUMNS, *extras]].sort_values(
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
                **(
                    role_component_record({str(key): value for key, value in record.items()})
                    if joint_role
                    else {}
                ),
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
