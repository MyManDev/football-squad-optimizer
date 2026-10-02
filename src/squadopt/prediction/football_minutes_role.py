"""Joint starting role and fixture minutes, fitted only on known past labels.

The existing appearance head is retained. Among appearances a separate head learns
starting versus substitute roles; each role has a conditional positive minute-bin
head. Their products form one joint law, not independently clipped probabilities.
Minute representatives use ten same-role/bin observations of pooled prior weight
within each position. The constant is fixed, not selected on evaluation outcomes.
Missing starts never become labels inferred from minutes. If all labels are absent,
the complete existing minute law is returned with explicitly unknown role identity.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass
from typing import Any, Final

import numpy as np
import numpy.typing as npt
import pandas as pd
from sklearn.exceptions import ConvergenceWarning  # type: ignore[import-untyped]
from sklearn.linear_model import LogisticRegression  # type: ignore[import-untyped]
from sklearn.pipeline import make_pipeline  # type: ignore[import-untyped]
from sklearn.preprocessing import StandardScaler  # type: ignore[import-untyped]

from squadopt.prediction.football_features import FEATURES, POS

ROLE_MINUTE_VERSION: Final = "joint_start_cameo_minutes_v1"
MINUTE_PRIOR_ROWS: Final = 10.0
Array = npt.NDArray[np.float64]

ROLE_COMPONENT_COLUMNS: Final = (
    "zero_probability",
    "start_probability",
    "cameo_probability",
    "unknown_role_probability",
    "expected_minutes_if_appearance",
    *(
        f"{role}_minute_{quantity}_{b}"
        for role in ("start", "cameo")
        for quantity in ("probability", "value")
        for b in (1, 2, 3)
    ),
)
ROLE_METADATA_COLUMNS: Final = (
    "minute_role_version",
    "minute_role_status",
    "known_start_label_rows",
    "unknown_start_label_rows",
    "minute_prior_rows",
)


def _matrix(frame: pd.DataFrame) -> Array:
    values = frame.loc[:, list(FEATURES)].to_numpy(float)
    if not np.isfinite(values).all():
        raise ValueError("Role-minute features must be finite.")
    return values


class _CategoricalHead:
    def __init__(self, frame: pd.DataFrame, labels: npt.NDArray[np.int64], classes: int):
        self.classes = classes
        self.constant: Array | None = None
        self.model: Any = None
        if not len(frame):
            # A role of zero fitted mass needs no invented conditional distribution.
            self.constant = np.zeros(classes)
        elif len(np.unique(labels)) == 1:
            self.constant = np.eye(classes)[int(labels[0])]
        else:
            self.model = make_pipeline(
                StandardScaler(), LogisticRegression(C=1, max_iter=1000, random_state=0)
            )
            with warnings.catch_warnings():
                warnings.simplefilter("error", ConvergenceWarning)
                try:
                    self.model.fit(_matrix(frame), labels)
                except ConvergenceWarning as error:
                    raise ValueError("Role-minute fit did not converge.") from error

    def predict(self, frame: pd.DataFrame) -> Array:
        design = _matrix(frame)
        if self.constant is not None:
            return np.tile(self.constant, (len(frame), 1))
        output = np.zeros((len(frame), self.classes))
        output[:, self.model[-1].classes_.astype(int)] = self.model.predict_proba(design)
        return output


@dataclass(frozen=True)
class RoleMinuteDistribution:
    """One joint support: zero then three start and three cameo minute classes.

    Without any known role labels the support is the original four minute classes;
    role fields are unavailable, not zero-probability statements about starting.
    """

    probabilities: Array
    minutes: Array
    bins: npt.NDArray[np.int64]
    supported: bool

    @property
    def appearance(self) -> Array:
        return 1.0 - self.probabilities[:, 0]

    @property
    def expected_minutes(self) -> Array:
        return (self.probabilities * self.minutes).sum(axis=1)

    @property
    def p60(self) -> Array:
        return self.probabilities[:, self.bins >= 2].sum(axis=1)

    def collapsed(self) -> tuple[Array, Array]:
        """Four-bin marginals for existing readers; nonlinear heads use joint support."""
        probabilities = np.zeros((len(self.probabilities), 4))
        minutes = np.zeros_like(probabilities)
        for b in range(4):
            mask = self.bins == b
            probabilities[:, b] = self.probabilities[:, mask].sum(axis=1)
            numerator = (self.probabilities[:, mask] * self.minutes[:, mask]).sum(axis=1)
            # Zero-mass representatives are unused. Retain a legal representative
            # rather than publishing a positive class with a zero-minute value.
            minutes[:, b] = np.divide(
                numerator,
                probabilities[:, b],
                out=np.full(len(probabilities), (0.0, 30.0, 75.0, 90.0)[b]),
                where=probabilities[:, b] > 0,
            )
            # Mixture division can turn an exact 90 into 89.99999999999999.
            # Keep the declared marginal representative inside its actual support;
            # nonlinear scoring still uses the unchanged joint duration points.
            lower, upper = (
                (0.0, 0.0),
                (np.nextafter(0.0, 1.0), np.nextafter(60.0, 0.0)),
                (60.0, np.nextafter(90.0, 0.0)),
                (90.0, 120.0),
            )[b]
            minutes[:, b] = np.clip(minutes[:, b], lower, upper)
        return probabilities, minutes


class JointRoleMinutes:
    """Fit a role-given-appearance head and role-conditional positive minute laws.

    ``train`` has the same causal features as FixtureFootballModel training. ``starts``
    may be missing; other malformed labels are refused rather than reinterpreted.
    Every fitted and pooled statistic comes from the known-label appearance subset.
    """

    def __init__(self, train: pd.DataFrame, *, cutoff: pd.Timestamp):
        if cutoff.tzinfo is None or train.empty:
            raise ValueError("Role minutes need a timezone-aware cutoff and training rows.")
        if (
            not (train.kickoff + pd.Timedelta(hours=3) < cutoff).all()
            or not (train.feature_cutoff <= train.kickoff).all()
        ):
            raise ValueError("Role-minute labels are unavailable at the decision cutoff.")
        if train.duplicated(["season", "fixture", "player_code"]).any():
            raise ValueError("Repeated role-minute player-fixture training row.")
        if not train.position.isin(POS).all() or not train.minutes.between(0, 120).all():
            raise ValueError("Role-minute positions or durations are invalid.")
        labels = train.get("starts", pd.Series(np.nan, index=train.index))
        if (labels.notna() & ~labels.isin((0, 1))).any():
            raise ValueError("Known starts must be binary; missing labels remain unknown.")
        appeared = train.minutes.gt(0)
        if (labels.eq(1) & ~appeared).any():
            raise ValueError("A recorded starter must have positive minutes.")
        bins = np.select(
            [train.minutes.le(0), train.minutes.lt(60), train.minutes.lt(90)],
            [0, 1, 2],
            default=3,
        )
        if not np.array_equal(train.m_bin.to_numpy(), bins):
            raise ValueError("Role-minute bins disagree with observed minutes.")
        known = appeared & labels.notna()
        fitted = train.loc[known].copy()
        fitted["starts"] = labels.loc[known].astype(int)
        self.known_start_label_rows = len(fitted)
        self.unknown_start_label_rows = int((appeared & labels.isna()).sum())
        self.supported = not fitted.empty
        self.role: _CategoricalHead | None = None
        self.conditional: dict[str, _CategoricalHead] = {}
        self.means: dict[tuple[str, str], Array] = {}
        if not self.supported:
            return
        self.role = _CategoricalHead(fitted, fitted.starts.to_numpy(dtype=np.int64), 2)
        for role, label in (("start", 1), ("cameo", 0)):
            role_rows = fitted.loc[fitted.starts.eq(label)]
            self.conditional[role] = _CategoricalHead(
                role_rows, role_rows.m_bin.to_numpy(dtype=np.int64) - 1, 3
            )
            for position in POS:
                means = np.array([30.0, 75.0, 90.0])
                for b in (1, 2, 3):
                    population = role_rows.loc[role_rows.m_bin.eq(b)]
                    if population.empty:
                        continue  # This class has exactly zero probability in the head.
                    prior = float(population.minutes.mean())
                    local = population.loc[population.position.eq(position), "minutes"]
                    means[b - 1] = (float(local.sum()) + MINUTE_PRIOR_ROWS * prior) / (
                        len(local) + MINUTE_PRIOR_ROWS
                    )
                self.means[position, role] = means

    @property
    def metadata(self) -> dict[str, object]:
        return {
            "version": ROLE_MINUTE_VERSION,
            "status": "fitted_known_start_labels"
            if self.supported
            else "unavailable_no_known_start_labels",
            "known_start_label_rows": self.known_start_label_rows,
            "unknown_start_label_rows": self.unknown_start_label_rows,
            "minute_prior_rows": MINUTE_PRIOR_ROWS,
            "mean_population": "position_role_bin_shrunk_to_same_role_bin",
            "appearance_basis": "unchanged_frozen_four_bin_head",
            "role_training_population": "positive_minutes_with_recorded_binary_starts",
            "availability_application": "not_applied",
            "residual_policy": "per_appearance_residual_held_fixed",
            "probability_calibration": "not_independently_verified",
        }

    def predict(
        self, target: pd.DataFrame, *, baseline_probabilities: Array, baseline_minutes: Array
    ) -> RoleMinuteDistribution:
        if not target.position.isin(POS).all():
            raise ValueError("Unknown role-minute target position.")
        p = np.asarray(baseline_probabilities, dtype=float)
        m = np.asarray(baseline_minutes, dtype=float)
        if m.shape == (4,):
            m = np.tile(m, (len(target), 1))
        if (
            p.shape != (len(target), 4)
            or m.shape != p.shape
            or not np.isfinite(p).all()
            or not np.isfinite(m).all()
            or (p < 0).any()
            or (p > 1).any()
            or not np.allclose(p.sum(axis=1), 1.0)
        ):
            raise ValueError("The retained four-bin minute law is invalid.")
        if not self.supported:
            return RoleMinuteDistribution(p.copy(), m.copy(), np.arange(4), False)
        assert self.role is not None
        q = 1.0 - p[:, 0]
        roles = self.role.predict(target)
        probabilities = np.zeros((len(target), 7))
        minutes = np.zeros_like(probabilities)
        probabilities[:, 0] = p[:, 0]
        for offset, role, label in ((1, "start", 1), (4, "cameo", 0)):
            probabilities[:, offset : offset + 3] = (
                q[:, None] * roles[:, label, None] * self.conditional[role].predict(target)
            )
            minutes[:, offset : offset + 3] = np.vstack(
                [self.means[str(position), role] for position in target.position]
            )
        if not np.allclose(probabilities.sum(axis=1), 1.0):
            raise ValueError("Joint role-minute probability mass was not conserved.")
        return RoleMinuteDistribution(probabilities, minutes, np.array([0, 1, 2, 3, 1, 2, 3]), True)

    def fields(self, state: RoleMinuteDistribution, *, index: pd.Index) -> pd.DataFrame:
        """Explicit nullable role outputs; absence of evidence is not a certain role."""
        count = len(state.probabilities)
        result = pd.DataFrame(index=index)
        result["zero_probability"] = state.probabilities[:, 0]
        result["unknown_role_probability"] = 0.0 if state.supported else state.appearance
        for role, offset in (("start", 1), ("cameo", 4)):
            result[role + "_probability"] = (
                state.probabilities[:, offset : offset + 3].sum(axis=1)
                if state.supported
                else pd.Series(pd.NA, index=index, dtype="Float64")
            )
            for b in (1, 2, 3):
                for quantity, values in (
                    ("probability", state.probabilities),
                    ("value", state.minutes),
                ):
                    result[f"{role}_minute_{quantity}_{b}"] = (
                        values[:, offset + b - 1]
                        if state.supported
                        else pd.Series(pd.NA, index=index, dtype="Float64")
                    )
        result["expected_minutes_if_appearance"] = np.divide(
            state.expected_minutes,
            state.appearance,
            out=np.zeros(count),
            where=state.appearance > 0,
        )
        result["minute_role_version"] = ROLE_MINUTE_VERSION
        result["minute_role_status"] = (
            "fitted_known_start_labels" if state.supported else "unavailable_no_known_start_labels"
        )
        result["known_start_label_rows"] = self.known_start_label_rows
        result["unknown_start_label_rows"] = self.unknown_start_label_rows
        result["minute_prior_rows"] = MINUTE_PRIOR_ROWS
        return result
