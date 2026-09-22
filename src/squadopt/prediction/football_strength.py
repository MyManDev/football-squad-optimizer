"""Sequential, opponent-adjusted Gamma working filter for team scoring strength.

Attack and defensive concession states shrink to one, with a fixed 90-day half-life.
Updates for simultaneous fixtures use the same pre-kickoff state. The product-state
variance is a moment approximation, not an exact joint Bayesian posterior.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class StrengthState:
    attack_shape: float = 8.0
    attack_rate: float = 8.0
    defence_shape: float = 8.0
    defence_rate: float = 8.0
    updated_at: pd.Timestamp | None = None

    def at(self, instant: pd.Timestamp) -> StrengthState:
        if self.updated_at is None:
            return StrengthState(updated_at=instant)
        days = (instant - self.updated_at).total_seconds() / 86400
        if days < 0:
            raise ValueError("Team state cannot travel backwards in time.")
        retain = math.exp(-math.log(2) * days / 90)
        return StrengthState(
            8 + (self.attack_shape - 8) * retain,
            8 + (self.attack_rate - 8) * retain,
            8 + (self.defence_shape - 8) * retain,
            8 + (self.defence_rate - 8) * retain,
            instant,
        )


class DynamicTeamStrength:
    """One observation per team/fixture, independent of roster size or player order."""

    def __init__(self, history: pd.DataFrame, *, cutoff: pd.Timestamp):
        if cutoff.tzinfo is None or history.empty:
            raise ValueError("Team strength requires history and an aware cutoff.")
        if not (history.kickoff + pd.Timedelta(hours=3) < cutoff).all():
            raise ValueError("Team strength history includes unavailable outcomes.")
        keys = ["season", "fixture", "club"]
        labels = ["opponent", "home", "kickoff", "team_goals", "team_conceded"]
        if (history.groupby(keys)[labels].nunique(dropna=False) != 1).any().any():
            raise ValueError("Inconsistent player rows for a team-fixture.")
        teams = history.drop_duplicates(keys).sort_values(["kickoff", "fixture", "club"])
        values = teams[["team_goals", "team_conceded"]].to_numpy(float)
        if (
            not np.isfinite(values).all()
            or (values < 0).any()
            or (values != np.floor(values)).any()
        ):
            raise ValueError("Team goal observations must be nonnegative integer counts.")
        for _, match in teams.groupby(["season", "fixture"]):
            if (
                len(match) != 2
                or set(match.home) != {0, 1}
                or set(match.club) != set(match.opponent)
                or match.kickoff.nunique() != 1
            ):
                raise ValueError("Team history needs two consistent opposing sides.")
            left, right = match.iloc[0], match.iloc[1]
            if left.team_goals != right.team_conceded or right.team_goals != left.team_conceded:
                raise ValueError("Team scores disagree across fixture sides.")
        # These population estimates use only history available at this decision.
        self.base = {
            home: float(
                (teams.loc[teams.home.eq(home), "team_goals"].sum() + 12)
                / (teams.home.eq(home).sum() + 8)
            )
            for home in (0, 1)
        }
        self.states: dict[object, StrengthState] = {}
        self.cutoff = cutoff
        for kickoff, matches in teams.groupby("kickoff", sort=True):
            instant = pd.Timestamp(str(kickoff))
            clubs = set(matches.club) | set(matches.opponent)
            before = {club: self.states.get(club, StrengthState()).at(instant) for club in clubs}
            if matches.club.duplicated().any():
                raise ValueError("A club cannot play simultaneous fixtures.")
            for row in matches.to_dict("records"):
                own, opponent = before[row["club"]], before[row["opponent"]]
                self.states[row["club"]] = StrengthState(
                    own.attack_shape + float(row["team_goals"]),
                    own.attack_rate
                    + self.base[int(row["home"])] * opponent.defence_shape / opponent.defence_rate,
                    own.defence_shape + float(row["team_conceded"]),
                    own.defence_rate
                    + self.base[1 - int(row["home"])]
                    * opponent.attack_shape
                    / opponent.attack_rate,
                    instant,
                )

    def moments(
        self, club: object, opponent: object, home: int, kickoff: pd.Timestamp
    ) -> tuple[float, float]:
        if kickoff.tzinfo is None or kickoff < self.cutoff or home not in (0, 1):
            raise ValueError("Team forecast must name an aware future kickoff and venue.")
        attack = self.states.get(club, StrengthState()).at(kickoff)
        defence = self.states.get(opponent, StrengthState()).at(kickoff)
        mean = (
            self.base[home]
            * attack.attack_shape
            / attack.attack_rate
            * defence.defence_shape
            / defence.defence_rate
        )
        variance = mean**2 * (
            1 / attack.attack_shape
            + 1 / defence.defence_shape
            + 1 / (attack.attack_shape * defence.defence_shape)
        )
        return mean, variance

    def predict(self, target: pd.DataFrame) -> pd.DataFrame:
        rows = []
        for row in target.to_dict("records"):
            own, variance = self.moments(
                row["club"], row["opponent"], int(row["home"]), row["kickoff"]
            )
            other, other_variance = self.moments(
                row["opponent"], row["club"], 1 - int(row["home"]), row["kickoff"]
            )
            rows.append((own, variance, other, other_variance))
        return pd.DataFrame(
            rows,
            index=target.index,
            columns=[
                "team_goal_rate",
                "team_goal_variance",
                "opponent_goal_rate",
                "opponent_goal_variance",
            ],
        )
