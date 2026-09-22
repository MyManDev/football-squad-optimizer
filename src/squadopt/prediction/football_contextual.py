"""Opt-in contextual extension of the frozen fixture football model.

No generated probabilities or retrospective news are learned here. Captured availability
is an explicit eligibility multiplier, applied before team shares, exactly once. The
four minute categories retain the v1 learned conditional distribution.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from scipy.optimize import minimize_scalar
from scipy.stats import nbinom
from sklearn.linear_model import (  # type: ignore[import-untyped]
    LogisticRegression,
    PoissonRegressor,
)

from squadopt.prediction.football import Array, FixtureFootballModel, _fit, _matrix, _pipeline
from squadopt.prediction.football_features import FEATURES
from squadopt.prediction.football_strength import DynamicTeamStrength

CONTEXTUAL_MODEL_VERSION = "football_contextual_v3"


def defensive_context(frame: pd.DataFrame) -> Array:
    """Interactions describe who faces defensive work, using only causal features."""
    columns = [frame.dc_rate, frame.dc_known_apps, frame.own_xga, frame.opp_xgf, frame.home]
    for position in ("DEF", "MID", "FWD"):
        indicator = frame.position.eq(position).astype(float)
        columns.extend(
            (
                indicator,
                indicator * frame.dc_rate,
                indicator * frame.own_xga,
                indicator * frame.opp_xgf,
            )
        )
    values = np.column_stack([column.to_numpy(float) for column in columns])
    if not np.isfinite(values).all():
        raise ValueError("Defensive context must be finite.")
    return values


def estimate_dispersion(y: Array, mu: Array) -> float:
    """Fit one NB size by held-out count likelihood, never by evaluation point score."""
    if len(y) == 0 or not np.isfinite(y).all() or not np.isfinite(mu).all():
        raise ValueError("Dispersion requires finite held-out observations.")
    result = minimize_scalar(
        lambda log_size: float(
            -nbinom.logpmf(
                y, np.exp(log_size), np.exp(log_size) / (np.exp(log_size) + np.maximum(mu, 1e-12))
            ).sum()
        ),
        bounds=(np.log(0.05), np.log(10000)),
        method="bounded",
    )
    if not result.success or not np.isfinite(result.fun):
        raise ValueError("Held-out defensive dispersion fit did not converge.")
    return float(np.exp(result.x))


class ContextualFootballModel(FixtureFootballModel):
    """Dynamic team strength, current-club roles and uncertain eligible CS exposure."""

    model_version = CONTEXTUAL_MODEL_VERSION

    def __init__(self, train: pd.DataFrame, history: pd.DataFrame, *, cutoff: pd.Timestamp):
        super().__init__(train, history, cutoff=cutoff)
        self.start_model: Any = None
        self.start_prior = float(train.starts.mean())
        if not train.starts.isin((0, 1)).all():
            raise ValueError("Fixture starts must be binary.")
        if train.starts.nunique() == 2:
            self.start_model = _fit(
                _pipeline(LogisticRegression(C=1, max_iter=1000, random_state=0)),
                _matrix(train, FEATURES),
                train.starts,
            )
        self.strength = DynamicTeamStrength(history, cutoff=cutoff)
        self.club_roles = history.groupby(["club", "player_code"]).agg(
            minutes=("minutes", "sum"), xg=("expected_goals", "sum"), xa=("expected_assists", "sum")
        )
        known = train.loc[train.dc_event.notna() & train.position.ne("GK") & train.minutes.gt(0)]
        if not known.empty:
            actions = known.defensive_contribution.to_numpy(float)
            if (actions < 0).any() or (actions != np.floor(actions)).any():
                raise ValueError("Defensive actions must be integer counts.")
        self.context_dc: Any = None
        self.dispersion_calibration_rows = 0
        self.context_dispersion = {pos: 10000.0 for pos in ("GK", "DEF", "MID", "FWD")}
        if not known.empty and known.defensive_contribution.sum() > 0:
            # Hold out entire feature-cutoff groups, keeping a gameweek together.
            origins = sorted(known.feature_cutoff.unique())
            split = origins[max(1, int(len(origins) * 0.8))] if len(origins) >= 5 else None
            if split is not None:
                fitting = known.loc[known.feature_cutoff < split]
                validating = known.loc[known.feature_cutoff >= split]
                if len(fitting) >= 30 and fitting.defensive_contribution.sum() > 0:
                    earlier = self._fit_defence(fitting)
                    mu = np.asarray(earlier.predict(defensive_context(validating)), float)
                    mu *= validating.minutes.to_numpy(float) / 90
                    y = validating.defensive_contribution.to_numpy(float)
                    pooled = estimate_dispersion(y, mu)
                    for pos in ("DEF", "MID", "FWD"):
                        mask = validating.position.eq(pos).to_numpy()
                        self.context_dispersion[pos] = (
                            estimate_dispersion(y[mask], mu[mask]) if mask.sum() >= 30 else pooled
                        )
                    self.dispersion_calibration_rows = len(validating)
            self.context_dc = self._fit_defence(known)

    @staticmethod
    def _fit_defence(frame: pd.DataFrame) -> Any:
        exposure = frame.minutes.to_numpy(float) / 90
        return _fit(
            _pipeline(PoissonRegressor(alpha=0.1, max_iter=1000)),
            defensive_context(frame),
            frame.defensive_contribution.to_numpy(float) / exposure,
            poissonregressor__sample_weight=exposure,
        )

    def predict(self, target: pd.DataFrame, *, role_steps: int = 0) -> pd.DataFrame:
        if role_steps:
            raise ValueError("Contextual football does not use the rejected role transition.")
        result = super().predict(target)
        moments = self.strength.predict(target)
        for col in moments:
            result[col] = moments[col]
        availability = (
            target.availability_probability.to_numpy(float)
            if "availability_probability" in target
            else np.ones(len(target))
        )
        if not np.isfinite(availability).all() or ((availability < 0) | (availability > 1)).any():
            raise ValueError("Captured availability must lie in [0, 1].")
        probabilities = result[[f"minute_probability_{b}" for b in range(4)]].to_numpy(
            float, copy=True
        )
        probabilities[:, 1:] *= availability[:, None]
        probabilities[:, 0] = 1 - probabilities[:, 1:].sum(axis=1)
        if "minutes_limited" in target:
            if not target.minutes_limited.isin((True, False)).all():
                raise ValueError("Minute-limit evidence must be categorical.")
            limited = target.minutes_limited.to_numpy(bool)
            shorter = probabilities[:, 1:3].sum(axis=1)
            if (limited & (shorter <= 0) & (probabilities[:, 3] > 0)).any():
                raise ValueError("No learned sub-90 support for minute-limit evidence.")
            redistribute = np.divide(
                probabilities[:, 3], shorter, out=np.zeros(len(target)), where=shorter > 0
            )
            probabilities[limited, 1:3] *= 1 + redistribute[limited, None]
            probabilities[limited, 3] = 0
        minutes = probabilities @ self.minute_means
        result["expected_minutes"] = minutes
        result["appearance_probability"] = 1 - probabilities[:, 0]
        result["p60"] = probabilities[:, 2:].sum(axis=1)
        result["availability_multiplier"] = availability
        starts = (
            np.full(len(target), self.start_prior)
            if self.start_model is None
            else self.start_model.predict_proba(_matrix(target, FEATURES))[:, 1]
        )
        result["start_probability"] = np.minimum(
            starts * availability, result.appearance_probability.to_numpy(float)
        )
        for b in range(4):
            result[f"minute_probability_{b}"] = probabilities[:, b]
        own = result.team_goal_rate.to_numpy(float)
        for head, prior_col, field, fraction in (
            ("goals", "expected_goals_rate", "xg", self.scored_fraction),
            ("assists", "expected_assists_rate", "xa", self.scored_fraction * self.assist_fraction),
        ):
            # Current-club evidence is shrunk by ten full games toward the pooled player rate.
            rates = []
            for row in target.to_dict("records"):
                key = (row["club"], row["player_code"])
                prior = float(row[prior_col])
                if key in self.club_roles.index:
                    role = self.club_roles.loc[key]
                    rates.append(
                        (float(role[field]) + 10 * prior) / (float(role.minutes) / 90 + 10)
                    )
                else:
                    rates.append(prior)
            weight = np.maximum(rates, 1e-6) * minutes / 90
            groups = target[["fixture", "club"]].assign(weight=weight)
            total = groups.groupby(["fixture", "club"]).weight.transform("sum").to_numpy()
            share = np.divide(weight, total, out=np.zeros(len(target)), where=total > 0)
            result[head + "_share"] = share
            result[head] = share * own * fraction
        # Laplace transform of a moment-matched Gamma opposing goal intensity.
        # Future event times are uniform within the fixture; no goal timestamps invented.
        opponent = result.opponent_goal_rate.to_numpy(float)
        variance = result.opponent_goal_variance.to_numpy(float)
        shape = opponent**2 / variance
        scale = variance / opponent
        result["clean_sheet_probability"] = sum(
            probabilities[:, b] * (1 + scale * self.minute_means[b] / 90) ** (-shape)
            for b in (2, 3)
        )
        rate = (
            np.zeros(len(target))
            if self.context_dc is None
            else np.asarray(self.context_dc.predict(defensive_context(target)), float)
        )
        kappa = target.position.map(self.context_dispersion).to_numpy(float)
        threshold = np.where(target.position.eq("DEF"), 10, 12)
        dc = np.zeros(len(target))
        for b in (1, 2, 3):
            mu = np.maximum(rate * self.minute_means[b] / 90, 1e-12)
            dc += probabilities[:, b] * nbinom.sf(threshold - 1, kappa, kappa / (kappa + mu))
        dc[target.position.eq("GK")] = 0
        result["defcon_probability"] = dc
        result["defcon_rate90"] = rate
        result["defcon_dispersion"] = kappa
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
            points += 2 * dc
        result["raw_expected_points"] = points
        result["expected_points"] = np.maximum(points, 0)
        result["model_version"] = self.model_version
        if not np.isfinite(result.drop(columns="model_version").to_numpy(float)).all():
            raise ValueError("Nonfinite contextual football forecast.")
        return result
