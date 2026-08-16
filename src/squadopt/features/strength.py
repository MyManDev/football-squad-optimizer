"""Opponent strength, estimated from shifted results rather than taken from a rating.

The source publishes its own difficulty rating for every fixture. It is not used, for two
reasons: it is opaque, so nobody here can say what it measures, and its stability within a
season is unverified, so a value read today might not mean what the same value meant in
gameweek one. A strength estimate computed from results we already hold is reproducible
and its timing is ours to control.

The panel carries no goals, so strength is estimated from what it does carry: a club's
fantasy points inside a gameweek, split by the unit that earned them. Midfielders and
forwards stand in for attacking quality; goalkeepers and defenders stand in for defensive
quality, because a defence that keeps clean sheets is paid in exactly those points. It is a
proxy, and calling it one is more honest than dressing it as a goal model.

Measured on 2022-23 through 2024-25, attackers facing the weakest quartile of defences
averaged 3.327 points against 2.688 facing the strongest — a spread of 0.639 points, which
is roughly half the size of the double-gameweek effect. That measurement used season-average
strength, which sees the whole season, so it is a ceiling rather than a promise: the shifted
estimate below knows only what preceded each gameweek.

**The promise has since been measured, and the paragraph above was incomplete in two ways.**
See `docs/opponent_strength_signal.md`.

It reported only the attacking direction. The defensive one is larger: over the 147-fold
development residual population, goalkeepers and defenders facing the weakest quartile of
attacks carry a mean residual of +0.1121 against −0.2097 facing the strongest, a spread of
0.322, where the attacking side spreads 0.162.

And "ceiling" understates what the shifted estimate delivers, because the ceiling was
measured on raw outcomes. Against the operational control's out-of-sample residuals the
effect is *larger* than in the raw outcomes — 1.24x on the attacking side, 1.06x on the
defensive — since players facing the strongest opponents are on average the better players
on the better teams, so squad quality moves against the fixture and dampens the raw spread.
Projecting removes most of that quality term and leaves the opponent effect more exposed.

The attacking side is monotone across all four quartiles; the defensive side is not, its
two weakest quartiles being effectively tied. Neither result is gate evidence, and wiring
this module into a projection remains a change to the expected-points rate that needs its
own declaration and a single run under the frozen gates.
"""

from typing import Final

import pandas as pd

from squadopt.data.schema import TEAM_GROUP_COLUMNS
from squadopt.features.config import FeatureConfigurationError
from squadopt.features.rolling import shifted_team_rolling_mean

# Units a club's points are split into. Attacking and defensive quality move
# independently — a club can create chances and concede freely — so one combined figure
# would describe neither.
ATTACKING_POSITIONS: Final = ("MID", "FWD")
DEFENSIVE_POSITIONS: Final = ("GK", "DEF")

TEAM_ATTACKING_COLUMN: Final = "team_attacking_points"
TEAM_DEFENSIVE_COLUMN: Final = "team_defensive_points"

# Attached to a player row: how good the clubs he faces this gameweek are. A high
# opponent defensive strength is bad news for an attacker, and the names say which side
# of the ball each figure describes rather than folding both into one "difficulty".
OPPONENT_STRENGTH_COLUMNS: Final = (
    "opponent_attack_strength",
    "opponent_defence_strength",
)

_TEAM_CODE_COLUMNS: Final = ("season", "name", "code")


def _require_columns(frame: pd.DataFrame, columns: tuple[str, ...], label: str) -> None:
    missing = [column for column in columns if column not in frame.columns]
    if missing:
        raise FeatureConfigurationError(
            f"{label} is missing columns {missing!r}; it carries "
            f"{sorted(map(str, frame.columns))!r}."
        )


def _bridge(panel: pd.DataFrame, team_codes: pd.DataFrame) -> pd.Series:
    """Resolve the panel's display-name clubs to persistent codes."""

    codes = team_codes.loc[:, list(_TEAM_CODE_COLUMNS)].copy(deep=True)
    keys = pd.MultiIndex.from_arrays(
        [codes["season"].astype("string"), codes["name"].astype("string")]
    )
    lookup = pd.Series(codes["code"].to_numpy(), index=keys)
    if lookup.index.has_duplicates:
        raise FeatureConfigurationError("Team code table maps the same season and name twice.")

    wanted = pd.MultiIndex.from_arrays(
        [panel["season"].astype("string"), panel["team_id"].astype("string")]
    )
    resolved = pd.Series(lookup.reindex(wanted).to_numpy(), index=panel.index)
    if bool(resolved.isna().any()):
        unknown = sorted(set(panel.loc[resolved.isna(), "team_id"].astype("string").tolist()))
        raise FeatureConfigurationError(
            f"Team code table does not name club(s) present in the panel: {unknown!r}."
        )
    return resolved.astype("int64")


def team_gameweek_points(panel: pd.DataFrame, team_codes: pd.DataFrame) -> pd.DataFrame:
    """Sum each club's gameweek points, split into attacking and defensive units.

    Keyed on the persistent team code so the result joins to the fixture table without a
    per-season translation. A club with no fixture in a gameweek simply has no row, which
    means a rolling window below spans a club's last N *matches* rather than its last N
    calendar gameweeks — the right reading of form, and worth stating because the two
    differ whenever a fixture is postponed.
    """

    _require_columns(
        panel, ("season", "gameweek", "team_id", "position", "total_points"), "Player panel"
    )
    _require_columns(team_codes, _TEAM_CODE_COLUMNS, "Team code table")

    working = panel.loc[:, ["season", "gameweek", "team_id", "position", "total_points"]].copy(
        deep=True
    )
    working["team_id"] = _bridge(working, team_codes)
    working["_unit"] = (
        working["position"]
        .astype("string")
        .map(
            {
                **{position: "attacking" for position in ATTACKING_POSITIONS},
                **{position: "defensive" for position in DEFENSIVE_POSITIONS},
            }
        )
    )
    unclassified = sorted(set(working.loc[working["_unit"].isna(), "position"].tolist()))
    if unclassified:
        raise FeatureConfigurationError(
            f"Positions {unclassified!r} belong to neither unit; every canonical position "
            "must be assigned, otherwise a club's points would be silently understated."
        )

    totals = (
        working.groupby(["season", "team_id", "gameweek", "_unit"], sort=True)["total_points"]
        .sum()
        .unstack("_unit")
        .reset_index()
    )
    for unit, column in (
        ("attacking", TEAM_ATTACKING_COLUMN),
        ("defensive", TEAM_DEFENSIVE_COLUMN),
    ):
        totals[column] = totals[unit].astype("float64") if unit in totals.columns else float("nan")
    ordered = totals.loc[
        :, ["season", "team_id", "gameweek", TEAM_ATTACKING_COLUMN, TEAM_DEFENSIVE_COLUMN]
    ]
    return ordered.sort_values([*TEAM_GROUP_COLUMNS, "gameweek"], kind="stable").reset_index(
        drop=True
    )


def team_strength(panel: pd.DataFrame, team_codes: pd.DataFrame, *, window: int) -> pd.DataFrame:
    """Estimate each club's attacking and defensive strength entering each gameweek.

    Both figures are shifted before their window is applied, through the same primitive
    every other rolling feature uses, so a club's own result in the gameweek being
    described never contributes to describing it.
    """

    totals = team_gameweek_points(panel, team_codes)
    attacking = shifted_team_rolling_mean(totals, TEAM_ATTACKING_COLUMN, window, min_periods=1)
    defensive = shifted_team_rolling_mean(totals, TEAM_DEFENSIVE_COLUMN, window, min_periods=1)
    return totals.assign(
        attack_strength=attacking.to_numpy(),
        defence_strength=defensive.to_numpy(),
    ).loc[:, ["season", "team_id", "gameweek", "attack_strength", "defence_strength"]]


def attach_opponent_strength(
    panel: pd.DataFrame,
    fixtures: pd.DataFrame,
    team_codes: pd.DataFrame,
    *,
    window: int,
) -> pd.DataFrame:
    """Attach the strength of the clubs each player faces this gameweek.

    A club playing twice faces two opponents, so the figures are averaged across the
    gameweek's fixtures — the same treatment fixture difficulty gets, and for the same
    reason: at player-gameweek grain there is no single opponent to name.

    A club with no fixture receives no opponent strength rather than a zero. There is
    nobody to be strong or weak, and a zero would read as the weakest possible opponent.
    """

    _require_columns(panel, ("season", "gameweek", "team_id"), "Player panel")
    _require_columns(fixtures, ("season", "gameweek", "team_id", "opponent_team_id"), "Fixtures")
    collisions = [column for column in OPPONENT_STRENGTH_COLUMNS if column in panel.columns]
    if collisions:
        raise FeatureConfigurationError(
            f"Opponent strength names collide with existing panel columns: {collisions!r}."
        )

    strength = team_strength(panel, team_codes, window=window)
    opponents = fixtures.loc[:, ["season", "gameweek", "team_id", "opponent_team_id"]].copy(
        deep=True
    )
    opponents["season"] = opponents["season"].astype("string")

    joined = opponents.merge(
        strength.rename(
            columns={
                "team_id": "opponent_team_id",
                "attack_strength": "opponent_attack_strength",
                "defence_strength": "opponent_defence_strength",
            }
        ).assign(season=lambda frame: frame["season"].astype("string")),
        on=["season", "gameweek", "opponent_team_id"],
        how="left",
        validate="many_to_one",
    )
    averaged = (
        joined.groupby(["season", "gameweek", "team_id"], sort=True)[
            list(OPPONENT_STRENGTH_COLUMNS)
        ]
        .mean()
        .reset_index()
    )

    result = panel.copy(deep=True)
    result["_team_code"] = _bridge(result, team_codes)
    result["_season_key"] = result["season"].astype("string")
    merged = result.merge(
        averaged.rename(columns={"team_id": "_team_code", "season": "_season_key"}),
        on=["_season_key", "gameweek", "_team_code"],
        how="left",
        validate="many_to_one",
    )
    for column in OPPONENT_STRENGTH_COLUMNS:
        merged[column] = merged[column].astype("float64")
    return merged.drop(columns=["_team_code", "_season_key"])
