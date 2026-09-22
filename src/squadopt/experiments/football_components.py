"""Research-only factorial decomposition; frozen production heads are never refitted here."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import product
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import nbinom
from sklearn.linear_model import PoissonRegressor  # type: ignore[import-untyped]

from squadopt.prediction.football import FixtureFootballModel, _fit, _matrix, _pipeline
from squadopt.prediction.football_contextual import ContextualFootballModel
from squadopt.prediction.football_features import TEAM_FEATURES
from squadopt.prediction.football_strength import DynamicTeamStrength


@dataclass(frozen=True)
class Components:
    team: bool = False
    roles: bool = False
    uncertain_cs: bool = False
    contextual_dc: bool = False

    @property
    def name(self) -> str:
        return "".join(
            str(int(v)) for v in (self.team, self.roles, self.uncertain_cs, self.contextual_dc)
        )


FACTORIAL = tuple(Components(*values) for values in product((False, True), repeat=4))


def standings_features(history: pd.DataFrame, target: pd.DataFrame) -> pd.DataFrame:
    """Season-local, exposure-shrunk standings at each row's decision, not final rank."""
    matches = history.drop_duplicates(["season", "fixture", "club"]).copy()
    matches["settled"] = matches.kickoff + pd.Timedelta(hours=3)
    matches["points"] = np.select(
        [
            matches.team_goals.gt(matches.team_conceded),
            matches.team_goals.eq(matches.team_conceded),
        ],
        [3.0, 1.0],
        default=0.0,
    )
    matches["gd"] = matches.team_goals - matches.team_conceded
    lookup = {}
    for key, group in matches.groupby(["season", "club"]):
        group = group.sort_values("settled")
        lookup[key] = (
            group.settled.dt.as_unit("ns").astype("int64").to_numpy(),
            np.r_[0, group.points.cumsum().to_numpy()],
            np.r_[0, group.gd.cumsum().to_numpy()],
        )
    output = np.empty((len(target), 4), dtype=float)
    for i, row in enumerate(target.itertuples()):
        cutoff = pd.Timestamp(str(row.feature_cutoff))
        if cutoff.tzinfo is None:
            raise ValueError("Standings decision cutoff must be timezone aware.")
        for j, club in enumerate((row.club, row.opponent)):
            entry = lookup.get((row.season, club))
            n, points, gd = 0, 0.0, 0.0
            if entry is not None:
                times, point_sum, gd_sum = entry
                n = int(np.searchsorted(times, cutoff.value, side="left"))
                points, gd = float(point_sum[n]), float(gd_sum[n])
            output[i, j * 2 : j * 2 + 2] = ((points + 5 * 1.35) / (n + 5), gd / (n + 5))
    return pd.DataFrame(
        output, index=target.index, columns=("own_ppg", "own_gd", "opp_ppg", "opp_gd")
    )


class StandingsHead:
    """A separate predeclared arm; league-table information must earn its place."""

    def __init__(self, train: pd.DataFrame, history: pd.DataFrame):
        team = train.drop_duplicates(["season", "fixture", "club"])
        self.history = history
        extra = standings_features(history, team)
        self.model: Any = _fit(
            _pipeline(PoissonRegressor(alpha=0.1, max_iter=1000)),
            np.column_stack((_matrix(team, TEAM_FEATURES), extra.to_numpy(float))),
            team.team_goals,
        )

    def predict(self, target: pd.DataFrame) -> tuple[np.ndarray[Any, Any], np.ndarray[Any, Any]]:
        extra = standings_features(self.history, target).to_numpy(float)
        own = self.model.predict(np.column_stack((_matrix(target, TEAM_FEATURES), extra)))
        other = target.copy()
        for name in ("gf", "ga", "xgf", "xga"):
            other["own_" + name] = target["opp_" + name].to_numpy()
            other["opp_" + name] = target["own_" + name].to_numpy()
        other["home"] = 1 - target.home.to_numpy()
        opponent = self.model.predict(
            np.column_stack((_matrix(other, TEAM_FEATURES), extra[:, [2, 3, 0, 1]]))
        )
        return np.asarray(own, float), np.asarray(opponent, float)


class ComponentForecast:
    """Cache fitted minute/residual/DC heads; vary only the declared football components.

    Availability/minute-limit evidence is common to every arm, before allocating shares.
    At availability=1 the two factorial endpoints reproduce frozen v1 and contextual v3.
    """

    def __init__(self, model: ContextualFootballModel, history: pd.DataFrame, target: pd.DataFrame):
        self.target = target.copy()
        self.cutoff = model.cutoff
        self.base = FixtureFootballModel.predict(model, target)
        self.context = model.predict(target)
        self.history = history.drop_duplicates(["season", "fixture", "club"])[
            [
                "season",
                "fixture",
                "club",
                "opponent",
                "home",
                "kickoff",
                "team_goals",
                "team_conceded",
            ]
        ].copy()
        self.fractions = (model.scored_fraction, model.scored_fraction * model.assist_fraction)
        keys = pd.MultiIndex.from_frame(target[["club", "player_code"]])
        self.roles = model.club_roles.reindex(keys).fillna(0).reset_index(drop=True)
        self.moments = self.context[
            ["team_goal_rate", "team_goal_variance", "opponent_goal_rate", "opponent_goal_variance"]
        ].copy()

    def predict(
        self,
        switches: Components,
        *,
        half_life_days: float = 90,
        prior: float = 8,
        role_prior: float = 10,
        attack_only: bool = False,
        standings: tuple[np.ndarray[Any, Any], np.ndarray[Any, Any]] | None = None,
    ) -> pd.DataFrame:
        if not np.isfinite(role_prior) or role_prior <= 0:
            raise ValueError("Role prior must be finite and positive.")
        target, result = self.target, self.context.copy()
        moments = self.moments
        if half_life_days != 90 or prior != 8:
            moments = DynamicTeamStrength(
                self.history, cutoff=self.cutoff, half_life_days=half_life_days, prior=prior
            ).predict(target)
        own = (moments if switches.team else self.base).team_goal_rate.to_numpy(float)
        opponent = (
            moments if switches.team and not attack_only else self.base
        ).opponent_goal_rate.to_numpy(float)
        if standings is not None:
            own, opponent = standings
        result["team_goal_rate"], result["opponent_goal_rate"] = own, opponent
        result["team_goal_variance"] = (
            moments.team_goal_variance.to_numpy(float)
            * (own / moments.team_goal_rate.to_numpy(float)) ** 2
        )
        minutes = result.expected_minutes.to_numpy(float)
        for head, field, column, fraction in zip(
            ("goals", "assists"),
            ("xg", "xa"),
            ("expected_goals_rate", "expected_assists_rate"),
            self.fractions,
            strict=True,
        ):
            rate = target[column].to_numpy(float)
            if switches.roles:
                rate = (self.roles[field].to_numpy(float) + role_prior * rate) / (
                    self.roles.minutes.to_numpy(float) / 90 + role_prior
                )
            weight = np.maximum(rate, 1e-6) * minutes / 90
            groups = target[["fixture", "club"]].assign(weight=weight)
            total = groups.groupby(["fixture", "club"]).weight.transform("sum").to_numpy()
            share = np.divide(weight, total, out=np.zeros(len(target)), where=total > 0)
            result[head + "_share"] = share
            result[head] = share * own * fraction
        # With team off, preserve relative Gamma uncertainty while using v1's mean.
        variance = (
            moments.opponent_goal_variance.to_numpy(float)
            * (opponent / moments.opponent_goal_rate.to_numpy(float)) ** 2
        )
        result["opponent_goal_variance"] = variance
        shape, scale = opponent**2 / variance, variance / opponent
        result["clean_sheet_probability"] = sum(
            result[f"minute_probability_{b}"]
            * (
                (1 + scale * result[f"minute_value_{b}"] / 90) ** (-shape)
                if switches.uncertain_cs
                else np.exp(-opponent * result[f"minute_value_{b}"] / 90)
            )
            for b in (2, 3)
        )
        if not switches.contextual_dc:
            rate = self.base.defcon_rate90.to_numpy(float)
            size = self.base.defcon_dispersion.to_numpy(float)
            threshold = np.where(target.position.eq("DEF"), 10, 12)
            dc = np.zeros(len(target))
            for b in (1, 2, 3):
                mu = np.maximum(rate * result[f"minute_value_{b}"].to_numpy(float) / 90, 1e-12)
                dc += result[f"minute_probability_{b}"].to_numpy(float) * nbinom.sf(
                    threshold - 1, size, size / (size + mu)
                )
            dc[target.position.eq("GK")] = 0
            result["defcon_probability"], result["defcon_rate90"], result["defcon_dispersion"] = (
                dc,
                rate,
                size,
            )
        goal = target.position.map(
            {
                "GK": 10 if str(target.season.iloc[0]) >= "2024-25" else 6,
                "DEF": 6,
                "MID": 5,
                "FWD": 4,
            }
        ).to_numpy(float)
        clean = target.position.map({"GK": 4, "DEF": 4, "MID": 1, "FWD": 0}).to_numpy(float)
        points = (
            result.appearance_probability
            + result.p60
            + goal * result.goals
            + 3 * result.assists
            + clean * result.clean_sheet_probability
            + result.appearance_probability * result.residual_if_appearance
        )
        if str(target.season.iloc[0]) >= "2025-26":
            points += 2 * result.defcon_probability
        result["raw_expected_points"], result["expected_points"] = points, np.maximum(points, 0)
        result["model_version"] = "football_component_research"
        if not np.isfinite(result.drop(columns="model_version").to_numpy(float)).all():
            raise ValueError("Nonfinite component forecast.")
        return result
