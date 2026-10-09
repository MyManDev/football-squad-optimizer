"""Opt-in fixture football candidate; fitting never changes the promoted control.

The v1 head reproduces the measured team-share candidate. Role-transition forecasts
are a separately named v2 ablation. All preprocessing and dispersion use past data.
"""

from __future__ import annotations

import warnings
from typing import Any

import numpy as np
import numpy.typing as npt
import pandas as pd
from scipy.stats import nbinom
from sklearn.exceptions import ConvergenceWarning  # type: ignore[import-untyped]
from sklearn.linear_model import (  # type: ignore[import-untyped]
    LogisticRegression,
    PoissonRegressor,
    Ridge,
)
from sklearn.pipeline import make_pipeline  # type: ignore[import-untyped]
from sklearn.preprocessing import StandardScaler  # type: ignore[import-untyped]

from squadopt.prediction.football_features import FEATURES, TEAM_FEATURES
from squadopt.prediction.football_minutes_role import JointRoleMinutes, RetainedHistoryRoleMinutes

FOOTBALL_MODEL_VERSION = "football_team_share_v1"
ROLE_MODEL_VERSION = "football_team_share_role_transition_v2"
JOINT_ROLE_MODEL_VERSION = "football_joint_role_minutes_v1"
JOINT_ROLE_RETAINED_HISTORY_MODEL_VERSION = "football_joint_role_retained_history_v1"
JOINT_ROLE_MODEL_VERSIONS = (JOINT_ROLE_MODEL_VERSION, JOINT_ROLE_RETAINED_HISTORY_MODEL_VERSION)
Array = npt.NDArray[np.float64]


def _pipeline(estimator: Any) -> Any:
    return make_pipeline(StandardScaler(), estimator)


def _fit(model: Any, x: Array, y: Any, **fit_params: Array) -> Any:
    with warnings.catch_warnings():
        warnings.simplefilter("error", ConvergenceWarning)
        try:
            return model.fit(x, y, **fit_params)
        except ConvergenceWarning as error:
            raise ValueError("Football candidate fit did not converge.") from error


def _matrix(frame: pd.DataFrame, columns: tuple[str, ...]) -> Array:
    values = frame.loc[:, list(columns)].to_numpy(dtype=float)
    if not np.isfinite(values).all():
        raise ValueError("Football features must be complete and finite.")
    return values


def _dispersion(y: Array, mu: Array) -> float:
    denominator = float(np.sum((y - mu) ** 2 - y))
    return float(np.clip(np.sum(mu**2) / denominator, 0.05, 10000)) if denominator > 0 else 10000.0


class FixtureFootballModel:
    """Fit on precomputed causal features; predict each fixture from one information state."""

    model_version = FOOTBALL_MODEL_VERSION
    minute_features: tuple[str, ...] = FEATURES
    team_features: tuple[str, ...] = TEAM_FEATURES

    def __init__(self, train: pd.DataFrame, history: pd.DataFrame, *, cutoff: pd.Timestamp):
        if cutoff.tzinfo is None or train.empty or history.empty:
            raise ValueError("A timezone-aware cutoff and nonempty history/training are required.")
        for frame in (train, history):
            if not (frame.kickoff + pd.Timedelta(hours=3) < cutoff).all():
                raise ValueError("Training contains outcomes unavailable at the decision cutoff.")
            if frame.duplicated(["season", "fixture", "player_code"]).any():
                raise ValueError("Duplicate player-fixture training row.")
            if not frame.minutes.between(0, 120).all():
                raise ValueError("Training minutes are outside the supported football range.")
        if "feature_cutoff" not in train or not (train.feature_cutoff <= train.kickoff).all():
            raise ValueError("Each training row must name its pre-match feature_cutoff.")
        if not train.m_bin.isin(range(4)).all() or train.m_bin.nunique() < 2:
            raise ValueError("Training needs at least two valid minute categories.")
        self.cutoff = cutoff
        self.train_rows = len(train)
        x = _matrix(train, FEATURES)
        self.minutes = _pipeline(LogisticRegression(C=1, max_iter=1000, random_state=0))
        _fit(self.minutes, _matrix(train, self.minute_features), train.m_bin)
        self.minute_means: Array = (
            train.groupby("m_bin")
            .minutes.mean()
            .reindex(range(4))
            .fillna(pd.Series({0: 0, 1: 30, 2: 75, 3: 90}))
            .to_numpy(dtype=float)
        )
        appeared = train.minutes.gt(0)
        self.residual = _fit(
            _pipeline(Ridge(alpha=1)), x[appeared], train.loc[appeared, "residual_target"]
        )
        team = train.drop_duplicates(["season", "fixture", "club"])
        self.team = _fit(
            _pipeline(PoissonRegressor(alpha=0.1, max_iter=1000)),
            _matrix(team, self.team_features),
            team.team_goals,
        )
        known = train.dc_event.notna() & train.position.ne("GK") & appeared
        self.dc_count: Any = None
        self.dispersion = {pos: 10000.0 for pos in ("GK", "DEF", "MID", "FWD")}
        if known.any():
            exposure = train.loc[known, "minutes"].to_numpy(dtype=float) / 90
            y = train.loc[known, "defensive_contribution"].to_numpy(dtype=float)
            self.dc_count = _pipeline(PoissonRegressor(alpha=0.1, max_iter=1000))
            _fit(self.dc_count, x[known], y / exposure, poissonregressor__sample_weight=exposure)
            mu = np.asarray(self.dc_count.predict(x[known]), dtype=float) * exposure
            for pos in ("DEF", "MID", "FWD"):
                mask = train.loc[known, "position"].eq(pos).to_numpy()
                self.dispersion[pos] = _dispersion(y[mask], mu[mask])
        sums = history.groupby(["season", "fixture", "club"]).agg(
            goals=("goals_scored", "sum"),
            assists=("assists", "sum"),
            team_goals=("team_goals", "first"),
        )
        self.scored_fraction = float(
            np.clip((sums.goals.sum() + 20) / (sums.team_goals.sum() + 20), 0, 1)
        )
        self.assist_fraction = float(
            np.clip((sums.assists.sum() + 15) / (sums.goals.sum() + 20), 0, 1)
        )
        # Empirical role transition with a fixed pooled Dirichlet prior. No use of
        # future match labels, season-boundary transitions, or player-specific tuning.
        ordered = history.sort_values(["kickoff", "fixture"], kind="stable").copy()
        ordered["previous_bin"] = ordered.groupby(["season", "player_code"]).m_bin.shift(1)
        valid = ordered.dropna(subset=["previous_bin"])
        pooled: Array = np.ones((4, 4), dtype=float)
        for previous, current in valid[["previous_bin", "m_bin"]].to_numpy(dtype=int):
            pooled[previous, current] += 1
        pooled /= pooled.sum(axis=1, keepdims=True)
        self.transitions: dict[str, Array] = {}
        for pos in self.dispersion:
            counts = 10 * pooled.copy()
            for previous, current in valid.loc[
                valid.position.eq(pos), ["previous_bin", "m_bin"]
            ].to_numpy(dtype=int):
                counts[previous, current] += 1
            self.transitions[pos] = counts / counts.sum(axis=1, keepdims=True)

    def predict(self, target: pd.DataFrame, *, role_steps: int = 0) -> pd.DataFrame:
        """Return fixture components; role_steps counts unseen player fixtures, not blank weeks."""
        if isinstance(role_steps, bool) or not isinstance(role_steps, int) or role_steps < 0:
            raise ValueError("role_steps must be a nonnegative integer.")
        if target.empty:
            raise ValueError("Predict fixtures first; the horizon adapter fills blank weeks.")
        if not target.position.isin(self.dispersion).all() or target.season.nunique() != 1:
            raise ValueError("A forecast requires valid positions and one scoring season.")
        if target.duplicated(["fixture", "player_code"]).any():
            raise ValueError("Duplicate player-fixture target.")
        x = _matrix(target, FEATURES)
        probabilities = np.zeros((len(target), 4), dtype=float)
        probabilities[:, self.minutes[-1].classes_.astype(int)] = self.minutes.predict_proba(
            _matrix(target, self.minute_features)
        )
        if role_steps:
            for pos, transition in self.transitions.items():
                mask = target.position.eq(pos).to_numpy()
                probabilities[mask] = probabilities[mask] @ np.linalg.matrix_power(
                    transition, role_steps
                )
        minutes = probabilities @ self.minute_means
        appeared = 1 - probabilities[:, 0]
        long = probabilities[:, 2:].sum(axis=1)
        own = np.asarray(self.team.predict(_matrix(target, self.team_features)), dtype=float)
        other = target.loc[:, list(self.team_features)].copy()
        for column in self.team_features:
            if column.startswith("own_"):
                opposite = "opp_" + column.removeprefix("own_")
                if opposite not in self.team_features:
                    raise ValueError("Team feature requires its opposing-side counterpart.")
                other[column] = target[opposite].to_numpy()
                other[opposite] = target[column].to_numpy()
        other["home"] = 1 - target.home.to_numpy()
        opponent = np.asarray(self.team.predict(_matrix(other, self.team_features)), dtype=float)
        output: dict[str, Any] = {
            "expected_minutes": minutes,
            "appearance_probability": appeared,
            "p60": long,
            "team_goal_rate": own,
            "opponent_goal_rate": opponent,
        }
        for head, column, fraction in (
            ("goals", "expected_goals_rate", self.scored_fraction),
            ("assists", "expected_assists_rate", self.scored_fraction * self.assist_fraction),
        ):
            weight = np.maximum(target[column].to_numpy(dtype=float), 1e-6) * minutes / 90
            grouping = target[["fixture", "club"]].assign(weight=weight)
            denominator = grouping.groupby(["fixture", "club"]).weight.transform("sum").to_numpy()
            share = np.divide(weight, denominator, out=np.zeros(len(target)), where=denominator > 0)
            output[head] = share * own * fraction
            output[head + "_share"] = share
        output["clean_sheet_probability"] = sum(
            probabilities[:, b] * np.exp(-opponent * self.minute_means[b] / 90) for b in (2, 3)
        )
        count_rate = (
            np.zeros(len(target))
            if self.dc_count is None
            else np.asarray(self.dc_count.predict(x), dtype=float)
        )
        kappa = target.position.map(self.dispersion).to_numpy(dtype=float)
        threshold = np.where(target.position.eq("DEF"), 10, 12)
        dc = np.zeros(len(target), dtype=float)
        for b in (1, 2, 3):
            mu = np.maximum(count_rate * self.minute_means[b] / 90, 1e-12)
            dc += probabilities[:, b] * nbinom.sf(threshold - 1, kappa, kappa / (kappa + mu))
        dc[target.position.eq("GK")] = 0
        output["defcon_probability"] = dc
        output["defcon_rate90"] = count_rate
        output["defcon_dispersion"] = kappa
        output["residual_if_appearance"] = np.asarray(self.residual.predict(x), dtype=float)
        season = str(target.season.iloc[0])
        goal_coeff = target.position.map(
            {"GK": 10 if season >= "2024-25" else 6, "DEF": 6, "MID": 5, "FWD": 4}
        ).to_numpy()
        cs_coeff = target.position.map({"GK": 4, "DEF": 4, "MID": 1, "FWD": 0}).to_numpy()
        raw = (
            appeared
            + long
            + goal_coeff * output["goals"]
            + 3 * output["assists"]
            + cs_coeff * output["clean_sheet_probability"]
        )
        raw += (2 * dc if season >= "2025-26" else 0) + appeared * output["residual_if_appearance"]
        output["raw_expected_points"] = raw
        output["expected_points"] = np.maximum(raw, 0)
        for b in range(4):
            output[f"minute_probability_{b}"] = probabilities[:, b]
            output[f"minute_value_{b}"] = np.repeat(self.minute_means[b], len(target))
        result = pd.DataFrame(output, index=target.index)
        if not np.isfinite(result.to_numpy(dtype=float)).all():
            raise ValueError("Nonfinite football forecast.")
        result["model_version"] = ROLE_MODEL_VERSION if role_steps else self.model_version
        return result


class JointRoleFootballModel(FixtureFootballModel):
    """Explicit candidate: one role-minute law drives every existing scoring head.

    The frozen v1 path above is unchanged. Its appearance, team-strength, per-90
    attacking and defensive, and per-appearance residual heads are retained; only
    the conditional exposure distribution changes. Captured eligibility is not
    applied here and remains a single later reader operation, like the v1 model.
    """

    model_version = JOINT_ROLE_MODEL_VERSION
    role_minutes_type = JointRoleMinutes

    def __init__(self, train: pd.DataFrame, history: pd.DataFrame, *, cutoff: pd.Timestamp):
        super().__init__(train, history, cutoff=cutoff)
        self.role_minutes = self.role_minutes_type(train, cutoff=cutoff)

    @property
    def role_metadata(self) -> dict[str, object]:
        return self.role_minutes.metadata

    def predict(self, target: pd.DataFrame, *, role_steps: int = 0) -> pd.DataFrame:
        if role_steps:
            raise ValueError("Joint role minutes do not apply the rejected role transition.")
        result = super().predict(target)
        baseline = result[[f"minute_probability_{b}" for b in range(4)]].to_numpy(float)
        state = self.role_minutes.predict(
            target, baseline_probabilities=baseline, baseline_minutes=self.minute_means
        )
        if state.supported:
            probabilities, means = state.collapsed()
            minutes = state.expected_minutes
            result["expected_minutes"] = minutes
            result["appearance_probability"] = state.appearance
            result["p60"] = state.p60
            for b in range(4):
                result[f"minute_probability_{b}"] = probabilities[:, b]
                result[f"minute_value_{b}"] = means[:, b]
            for head, column, fraction in (
                ("goals", "expected_goals_rate", self.scored_fraction),
                ("assists", "expected_assists_rate", self.scored_fraction * self.assist_fraction),
            ):
                weight = np.maximum(target[column].to_numpy(float), 1e-6) * minutes / 90
                groups = target[["fixture", "club"]].assign(weight=weight)
                total = groups.groupby(["fixture", "club"]).weight.transform("sum").to_numpy()
                share = np.divide(weight, total, out=np.zeros(len(target)), where=total > 0)
                result[head + "_share"] = share
                result[head] = share * result.team_goal_rate.to_numpy(float) * fraction
            # Evaluate nonlinear survival/tail functions over the joint support,
            # never at a start/cameo mixture's mean duration (Jensen's inequality).
            long = state.bins >= 2
            opponent = result.opponent_goal_rate.to_numpy(float)
            result["clean_sheet_probability"] = (
                state.probabilities[:, long]
                * np.exp(-opponent[:, None] * state.minutes[:, long] / 90)
            ).sum(axis=1)
            rate = result.defcon_rate90.to_numpy(float)
            size = result.defcon_dispersion.to_numpy(float)
            threshold = np.where(target.position.eq("DEF"), 10, 12)
            mu = np.maximum(rate[:, None] * state.minutes[:, 1:] / 90, 1e-12)
            dc = (
                state.probabilities[:, 1:]
                * nbinom.sf(
                    threshold[:, None] - 1, size[:, None], size[:, None] / (size[:, None] + mu)
                )
            ).sum(axis=1)
            dc[target.position.eq("GK").to_numpy()] = 0
            result["defcon_probability"] = dc
            season = str(target.season.iloc[0])
            goal = target.position.map(
                {"GK": 10 if season >= "2024-25" else 6, "DEF": 6, "MID": 5, "FWD": 4}
            ).to_numpy(float)
            clean = target.position.map({"GK": 4, "DEF": 4, "MID": 1, "FWD": 0}).to_numpy(float)
            raw = (
                result.appearance_probability
                + result.p60
                + goal * result.goals
                + 3 * result.assists
                + clean * result.clean_sheet_probability
                + result.appearance_probability * result.residual_if_appearance
            )
            if season >= "2025-26":
                raw = raw + 2 * dc
            result["raw_expected_points"] = raw
            result["expected_points"] = np.maximum(raw, 0)
        # This is native, unscaled appearance. One shared eligibility state per
        # player-week is still applied by the reader, including double gameweeks.
        result["availability_multiplier"] = 1.0
        result["model_version"] = self.model_version
        fields = self.role_minutes.fields(state, index=target.index)
        return pd.concat([result, fields], axis=1)


class RetainedHistoryRoleFootballModel(JointRoleFootballModel):
    """Opt-in retained-history role variant; the original joint default is unchanged.

    The inherited constructor fits the existing appearance and component heads
    once, and directly fits this variant's binary role head once. This class does
    not itself enable a CLI, artifact reader, public family or live publication.
    """

    model_version = JOINT_ROLE_RETAINED_HISTORY_MODEL_VERSION
    role_minutes_type = RetainedHistoryRoleMinutes
