"""Private categorical-flag weekly hurdle and conditional fixture-minute model.

Raw source labels are categories, never percentages in this model. Zero fitted
coefficients reproduce the unflagged independent native fixture law; that is a
declared ablation, not the legacy served availability-rule control. No empirical
calibration or promotion is implied by fitting this optional model.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import math
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Final

import numpy as np
import numpy.typing as npt
from scipy.optimize import minimize
from scipy.special import expit, logsumexp

from squadopt.features.football_flag_inputs import (
    PlayerWeekInput,
    TrainingWeek,
    input_digest,
    validate_training_week,
    validate_week_input,
)

MODEL_VERSION: Final = "football_flag_minutes_v1"
FEATURE_VERSION: Final = "causal_categorical_flag_minutes_features_v1"
Array = npt.NDArray[np.float64]
_POSITIONS: Final = ("GK", "DEF", "MID", "FWD")
_STATUSES: Final = (None, "a", "d", "i", "s", "u", "n")
_LABELS: Final = (None, 0, 25, 50, 75, 100)
_NEWS: Final = ("never_flagged", "cleared", "flagged", "unknown")
_NUMERIC: Final = ("news_age_hours", "capture_age_hours", "fixture_count")
_FEATURE_NAMES: Final = (
    "intercept",
    *(f"position:{value}" for value in _POSITIONS),
    *(f"status:{value}" for value in _STATUSES),
    *(f"label:{value}" for value in _LABELS),
    *(f"news:{value}" for value in _NEWS),
    "history_covered",
    "label_changed",
    "missing:label_changed",
    *(f"standardized:{value}" for value in _NUMERIC),
    *(f"missing:{value}" for value in _NUMERIC),
)


def _timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("Flag-minute clocks must be timezone aware.")
    return parsed


def _readonly(values: Array) -> Array:
    """Use immutable bytes as storage, so writeability cannot be re-enabled."""
    return np.frombuffer(values.astype(np.float64).tobytes(), dtype=np.float64).reshape(
        values.shape
    )


def _finite(values: Array, name: str) -> None:
    if not np.isfinite(values).all():
        raise ValueError(f"{name} must be finite.")


def _ridge(l2: float) -> float:
    if isinstance(l2, bool) or not isinstance(l2, (int, float)):
        raise ValueError("l2 must be a finite nonnegative number.")
    result = float(l2)
    if not math.isfinite(result) or result < 0:
        raise ValueError("l2 must be a finite nonnegative number.")
    return result


def hurdle_objective_gradient(
    coefficients: Array, design: Array, offsets: Array, labels: Array, l2: float
) -> tuple[float, Array]:
    """Bernoulli offset negative log likelihood plus declared ridge."""
    penalty = _ridge(l2)
    if (
        coefficients.ndim != 1
        or design.ndim != 2
        or design.shape[1] != len(coefficients)
        or offsets.shape != (len(design),)
        or labels.shape != offsets.shape
        or not len(design)
        or not np.isin(labels, (0, 1)).all()
    ):
        raise ValueError("Invalid hurdle training design.")
    for values in (coefficients, design, offsets, labels):
        _finite(values, "Hurdle values")
    logits = offsets + design @ coefficients
    value = float(np.sum(np.logaddexp(0.0, logits) - labels * logits))
    value += penalty * float(coefficients @ coefficients) / 2
    gradient = np.asarray(design.T @ (expit(logits) - labels) + penalty * coefficients)
    _finite(gradient, "Hurdle gradient")
    if not math.isfinite(value):
        raise ValueError("Nonfinite hurdle objective.")
    return value, gradient


def conditional_objective_gradient(
    coefficients: Array,
    designs: Sequence[Array],
    log_baselines: Sequence[Array],
    labels: Sequence[int],
    l2: float,
) -> tuple[float, Array]:
    """One observed whole-week vector per conditional multinomial likelihood."""
    penalty = _ridge(l2)
    if (
        coefficients.ndim != 1
        or not designs
        or not (len(designs) == len(log_baselines) == len(labels))
    ):
        raise ValueError("Invalid conditional training design.")
    _finite(coefficients, "Conditional coefficients")
    value = penalty * float(coefficients @ coefficients) / 2
    gradient = penalty * coefficients.copy()
    for design, baseline, label in zip(designs, log_baselines, labels, strict=True):
        if (
            design.ndim != 2
            or design.shape[1] != len(coefficients)
            or baseline.shape != (len(design),)
            or isinstance(label, bool)
            or not isinstance(label, (int, np.integer))
            or not 0 <= int(label) < len(design)
        ):
            raise ValueError("Invalid conditional state label or design.")
        _finite(design, "Conditional design")
        _finite(baseline, "Conditional native log mass")
        logits = baseline + design @ coefficients
        normalizer = float(logsumexp(logits))
        weights = np.asarray(np.exp(logits - normalizer), dtype=np.float64)
        value += normalizer - float(logits[label])
        gradient += weights @ design - design[label]
    _finite(gradient, "Conditional gradient")
    if not math.isfinite(value):
        raise ValueError("Nonfinite conditional objective.")
    return float(value), gradient


@dataclass(frozen=True)
class WeekMinutePrediction:
    week: PlayerWeekInput
    states: tuple[tuple[int, ...], ...]
    probabilities: tuple[float, ...]
    weekly_appearance: float
    fixture_probabilities: tuple[tuple[float, ...], ...]
    model_sha256: str
    input_sha256: str


@dataclass(frozen=True)
class FlagMinutesMetadata:
    model_version: str
    feature_version: str
    cutoff: str
    target_season: str
    target_gameweeks: tuple[int, ...]
    feature_names: tuple[str, ...]
    numeric_means: tuple[float, ...]
    numeric_scales: tuple[float, ...]
    hurdle_coefficients: tuple[float, ...]
    conditional_coefficients: tuple[float, ...]
    training_receipts: tuple[tuple[str, str, str, str], ...]
    l2: float
    max_iterations: int
    hurdle_iterations: int
    conditional_iterations: int
    model_sha256: str
    metadata_json: str


@dataclass(frozen=True)
class _Fitted:
    metadata: FlagMinutesMetadata
    means: Array
    scales: Array
    beta: Array
    gamma: Array


def _numeric(week: PlayerWeekInput) -> Array:
    values = (week.news_age_hours, week.capture_age_hours, len(week.fixtures))
    return np.asarray([np.nan if value is None else float(value) for value in values])


def _design(week: PlayerWeekInput, means: Array, scales: Array) -> Array:
    numeric = _numeric(week)
    missing = np.isnan(numeric)
    numeric = np.where(missing, means, numeric)
    result = np.asarray(
        [
            1.0,
            *(float(week.position == value) for value in _POSITIONS),
            *(float(week.status == value) for value in _STATUSES),
            *(float(week.label == value) for value in _LABELS),
            *(float(week.news_state == value) for value in _NEWS),
            float(week.history_covered),
            float(week.label_changed) if week.label_changed is not None else 0.0,
            float(week.label_changed is None),
            *((numeric - means) / scales),
            *missing.astype(float),
        ],
        dtype=np.float64,
    )
    _finite(result, "Flag-minute features")
    return result


def _native(week: PlayerWeekInput) -> tuple[tuple[tuple[int, ...], ...], Array, float]:
    if len(week.fixtures) > 3:
        raise ValueError("The declared weekly support permits at most three fixtures.")
    states = tuple(itertools.product(range(7), repeat=len(week.fixtures)))
    fixture_probabilities = tuple(
        tuple(float(p) / math.fsum(fixture.probabilities) for p in fixture.probabilities)
        for fixture in week.fixtures
    )
    probabilities = np.asarray(
        [
            math.prod(fixture_probabilities[f][cell] for f, cell in enumerate(state))
            for state in states
        ],
        dtype=np.float64,
    )
    for state, mass in zip(states, probabilities, strict=True):
        if mass == 0 and all(fixture_probabilities[f][cell] > 0 for f, cell in enumerate(state)):
            raise ValueError("Native weekly state support underflow.")
    total = math.fsum(probabilities)
    if total <= 0 or not math.isfinite(total):
        raise ValueError("Invalid native weekly probability mass.")
    probabilities /= total
    appearance = math.fsum(probabilities[1:]) if week.fixtures else 0.0
    return states, probabilities, appearance


def _conditional_design(states: Sequence[tuple[int, ...]], week_design: Array) -> Array:
    """Six positive role/bin counts cross week features, with absence as reference.

    Summing over fixtures permits conditional DGW participation and role changes
    without multiplying a weekly label into each fixture probability. Native
    fixture offsets retain fixture-specific exposure and role differences.
    """
    return np.asarray(
        [
            np.concatenate(
                [sum(cell == value for cell in state) * week_design for value in range(1, 7)]
            )
            for state in states
        ],
        dtype=np.float64,
    )


def _optimize(
    function: Callable[[Array], tuple[float, Array]], size: int, max_iterations: int
) -> tuple[Array, int, float, float]:
    result = minimize(
        function,
        np.zeros(size, dtype=np.float64),
        method="L-BFGS-B",
        jac=True,
        options={"maxiter": max_iterations, "ftol": 1e-12, "gtol": 1e-8},
    )
    coefficients = np.asarray(result.x, dtype=np.float64)
    value, gradient = function(coefficients)
    if not result.success or not math.isfinite(float(value)) or not np.isfinite(gradient).all():
        raise ValueError("Flag-minute fit did not converge to finite coefficients and gradient.")
    _finite(coefficients, "Fitted flag-minute coefficients")
    return (
        _readonly(coefficients),
        int(result.nit),
        float(value),
        float(np.linalg.norm(gradient, ord=np.inf)),
    )


class FlagMinutesModel:
    """Explicit private learned replacement; fitting does not alter served control."""

    def __init__(
        self,
        train: Sequence[TrainingWeek],
        *,
        fit_cutoff: str,
        target_season: str,
        target_gameweeks: tuple[int, ...],
        l2: float = 1.0,
        max_iterations: int = 1000,
    ):
        self.l2 = _ridge(l2)
        if (
            isinstance(max_iterations, bool)
            or not isinstance(max_iterations, int)
            or max_iterations < 1
        ):
            raise ValueError("max_iterations must be a positive integer.")
        self.max_iterations = max_iterations
        self.fit(
            train,
            fit_cutoff=fit_cutoff,
            target_season=target_season,
            target_gameweeks=target_gameweeks,
        )

    @property
    def metadata(self) -> FlagMinutesMetadata:
        return self._fitted.metadata

    @property
    def metadata_json(self) -> str:
        return self.metadata.metadata_json

    @property
    def model_sha256(self) -> str:
        return self.metadata.model_sha256

    def fit(
        self,
        train: Sequence[TrainingWeek],
        *,
        fit_cutoff: str,
        target_season: str,
        target_gameweeks: tuple[int, ...],
    ) -> FlagMinutesModel:
        """Publish a complete immutable fitted state only after all checks succeed."""
        cutoff = _timestamp(fit_cutoff)
        if (
            target_season == "2025-26"
            or not isinstance(target_season, str)
            or re.fullmatch(r"[0-9]{4}-[0-9]{2}", target_season) is None
            or int(target_season[5:]) != (int(target_season[:4]) + 1) % 100
            or not isinstance(target_gameweeks, tuple)
            or not target_gameweeks
            or any(
                isinstance(gw, bool) or not isinstance(gw, int) or not 1 <= gw <= 38
                for gw in target_gameweeks
            )
            or target_gameweeks != tuple(sorted(set(target_gameweeks)))
        ):
            raise ValueError("Invalid or protected flag-minute target context.")
        rows = tuple(train)
        if not rows:
            raise ValueError("Flag-minute training requires observations.")
        clocks: dict[tuple[str, int], datetime] = {}
        identities: set[tuple[str, int, int]] = set()
        # All source and target headers precede any observed-state access.
        for row in rows:
            week = row.input
            if (
                week.season == "2025-26"
                or (week.season == target_season and week.gameweek >= min(target_gameweeks))
                or week.season > target_season
            ):
                raise ValueError("Protected or target/future gameweek cannot enter training.")
            validate_week_input(week)
            decision = _timestamp(week.decision_at)
            if decision >= cutoff or _timestamp(row.settled_at) >= cutoff:
                raise ValueError("Training source and settlement must precede fit cutoff.")
            key = (week.season, week.gameweek)
            if key in clocks and clocks[key] != decision:
                raise ValueError("One original decision clock is required per historical gameweek.")
            clocks[key] = decision
            identity = (*key, week.player_code)
            if identity in identities:
                raise ValueError("Duplicate historical player-week.")
            identities.add(identity)
        for row in rows:
            validate_training_week(
                row,
                fit_cutoff=fit_cutoff,
                target_season=target_season,
                target_gameweeks=target_gameweeks,
            )
        rows = tuple(
            sorted(
                rows, key=lambda row: (row.input.season, row.input.gameweek, row.input.player_code)
            )
        )
        nonblank = tuple(row for row in rows if row.input.fixtures)
        if not nonblank:
            raise ValueError("Flag-minute training requires nonblank player-weeks.")
        numeric = np.vstack([_numeric(row.input) for row in nonblank])
        means = np.asarray(
            [
                float(np.mean(column[~np.isnan(column)])) if (~np.isnan(column)).any() else 0.0
                for column in numeric.T
            ]
        )
        filled = np.where(np.isnan(numeric), means, numeric)
        scales = np.std(filled, axis=0)
        scales[scales == 0] = 1.0
        design = np.vstack([_design(row.input, means, scales) for row in nonblank])
        offsets: list[float] = []
        appeared: list[float] = []
        conditional_designs: list[Array] = []
        conditional_baselines: list[Array] = []
        conditional_labels: list[int] = []
        for row, features in zip(nonblank, design, strict=True):
            states, probabilities, h0 = _native(row.input)
            if not 0 < h0 < 1:
                raise ValueError(
                    "Learned hurdle requires interior unflagged native weekly support."
                )
            observed = tuple(row.observed_states)
            index = states.index(observed)
            if probabilities[index] <= 0:
                raise ValueError("Observed weekly state has no native support.")
            offsets.append(math.log(h0) - math.log1p(-h0))
            appeared.append(float(any(observed)))
            if any(observed):
                support = np.flatnonzero(probabilities[1:] > 0) + 1
                supported_states = tuple(states[int(i)] for i in support)
                conditional_designs.append(_conditional_design(supported_states, features))
                conditional_baselines.append(np.log(probabilities[support] / h0))
                conditional_labels.append(supported_states.index(observed))
        if not conditional_designs:
            raise ValueError("Conditional role/minute fit requires observed positive weeks.")
        beta, beta_iterations, beta_value, beta_gradient = _optimize(
            lambda theta: hurdle_objective_gradient(
                theta, design, np.asarray(offsets), np.asarray(appeared), self.l2
            ),
            design.shape[1],
            self.max_iterations,
        )
        gamma, gamma_iterations, gamma_value, gamma_gradient = _optimize(
            lambda theta: conditional_objective_gradient(
                theta, conditional_designs, conditional_baselines, conditional_labels, self.l2
            ),
            6 * design.shape[1],
            self.max_iterations,
        )
        receipts = tuple(
            (
                input_digest(row.input),
                row.input.source_sha256,
                row.input.native_basis_sha256,
                row.outcome_sha256,
            )
            for row in rows
        )
        payload = {
            "model_version": MODEL_VERSION,
            "feature_version": FEATURE_VERSION,
            "cutoff": fit_cutoff,
            "target_season": target_season,
            "target_gameweeks": target_gameweeks,
            "feature_names": _FEATURE_NAMES,
            "conditional_feature_rule": "six_positive_role_bin_counts_cross_week_features",
            "numeric_means": means.tolist(),
            "numeric_scales": scales.tolist(),
            "missing_feature_rule": (
                "training_observed_mean_numeric_imputation_with_separate_missing_masks"
            ),
            "hurdle_coefficients": beta.tolist(),
            "conditional_coefficients": gamma.tolist(),
            "training_receipts": receipts,
            "training_settled_at": tuple(row.settled_at for row in rows),
            "l2": self.l2,
            "max_iterations": self.max_iterations,
            "hurdle_iterations": beta_iterations,
            "conditional_iterations": gamma_iterations,
            "optimizer": "deterministic_zero_init_L-BFGS-B",
            "hurdle_objective": beta_value,
            "conditional_objective": gamma_value,
            "hurdle_gradient_infinity_norm": beta_gradient,
            "conditional_gradient_infinity_norm": gamma_gradient,
            "training_nonblank_weeks": len(nonblank),
            "training_positive_weeks": len(conditional_designs),
            "native_control": "unflagged_independent_fixture_law_at_zero_coefficients",
            "calibration": "not_empirically_verified",
            "support": "lexicographic_seven_state_product_up_to_three_fixtures",
            "availability_application": "learned_weekly_hurdle_once_no_raw_label_multiplier",
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
        digest = hashlib.sha256(encoded.encode()).hexdigest()
        metadata = FlagMinutesMetadata(
            MODEL_VERSION,
            FEATURE_VERSION,
            fit_cutoff,
            target_season,
            target_gameweeks,
            _FEATURE_NAMES,
            tuple(means),
            tuple(scales),
            tuple(beta),
            tuple(gamma),
            receipts,
            self.l2,
            self.max_iterations,
            beta_iterations,
            gamma_iterations,
            digest,
            encoded,
        )
        self._fitted = _Fitted(metadata, _readonly(means), _readonly(scales), beta, gamma)
        return self

    def predict(
        self, week: PlayerWeekInput, *, zero_coefficients: bool = False
    ) -> WeekMinutePrediction:
        if not isinstance(zero_coefficients, bool):
            raise ValueError("zero_coefficients must be Boolean.")
        validate_week_input(week)
        fitted = self._fitted
        if (
            week.season != fitted.metadata.target_season
            or week.gameweek not in fitted.metadata.target_gameweeks
            or _timestamp(week.decision_at) < _timestamp(fitted.metadata.cutoff)
        ):
            raise ValueError("Prediction must match the fitted target and original model cutoff.")
        states, native, h0 = _native(week)
        if not week.fixtures:
            probabilities = native
            appearance = 0.0
        elif not 0 < h0 < 1:
            raise ValueError("Learned hurdle requires interior unflagged native weekly support.")
        elif zero_coefficients:
            probabilities = native
            appearance = h0
        else:
            features = _design(week, fitted.means, fitted.scales)
            appearance = float(expit(math.log(h0) - math.log1p(-h0) + features @ fitted.beta))
            if not 0 < appearance < 1:
                raise ValueError("Learned hurdle probability underflow or saturated support.")
            support = np.flatnonzero(native[1:] > 0) + 1
            design = _conditional_design(tuple(states[int(i)] for i in support), features)
            logits = np.log(native[support] / h0) + design @ fitted.gamma
            conditional = np.exp(logits - logsumexp(logits))
            if not np.isfinite(conditional).all() or (conditional <= 0).any():
                raise ValueError("Learned conditional state support underflow.")
            conditional /= math.fsum(conditional)
            probabilities = np.zeros(len(states), dtype=np.float64)
            probabilities[0] = 1 - appearance
            probabilities[support] = appearance * conditional
            if (probabilities[support] <= 0).any():
                raise ValueError("Learned positive weekly state support underflow.")
        marginals = tuple(
            tuple(
                math.fsum(
                    float(p)
                    for state, p in zip(states, probabilities, strict=True)
                    if state[f] == cell
                )
                for cell in range(7)
            )
            for f in range(len(week.fixtures))
        )
        return WeekMinutePrediction(
            week,
            states,
            tuple(probabilities),
            appearance,
            marginals,
            fitted.metadata.model_sha256,
            input_digest(week),
        )
