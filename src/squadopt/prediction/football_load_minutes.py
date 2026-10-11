"""Private whole-week workload tilt over an admitted native minute law.

This model never applies player eligibility. Zero coefficients recover the
normalized supplied joint law, including its structural zeros and dependencies.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any, cast

import numpy as np
from numpy.typing import NDArray
from scipy.optimize import minimize
from scipy.special import logsumexp

from squadopt.features.football_load_inputs import (
    LOAD_FEATURE_NAMES,
    LoadWeek,
    TrainingLoadWeek,
    load_input_digest,
    validate_load_week,
    validate_training_load_week,
)

MODEL_VERSION = "football_all_competition_load_v1"
FEATURE_VERSION = "causal_all_competition_load_minutes_v1"
_POSITIONS = ("GK", "DEF", "MID", "FWD")
_BINS = ("start_short", "start60", "start90", "cameo_short", "cameo60", "cameo90")
_FIXTURE_SUFFIXES = ("club_scheduled_kickoff_gap_hours", "known_prior_non_pl_matches")
_MASS_TOLERANCE = 1e-12
FloatArray = NDArray[np.float64]


@dataclass(frozen=True)
class LoadTrainingExample:
    design: FloatArray
    native_probabilities: FloatArray
    observed_index: int


@dataclass(frozen=True)
class LoadMinutesMetadata:
    model_version: str
    feature_version: str
    cutoff: str
    target_season: str
    target_gameweeks: tuple[int, ...]
    training_seasons: tuple[str, ...]
    feature_names: tuple[str, ...]
    design_names: tuple[str, ...]
    means: tuple[float, ...]
    scales: tuple[float, ...]
    known_counts: tuple[int, ...]
    gap_mean_hours: float
    gap_scale_hours: float
    coefficients: tuple[float, ...]
    training_input_sha256: tuple[str, ...]
    training_outcome_sha256: tuple[str, ...]
    l2: float
    max_iterations: int
    iterations: int
    objective: float
    gradient_max_abs: float
    model_sha256: str


@dataclass(frozen=True)
class WeekLoadPrediction:
    week: LoadWeek
    states: tuple[tuple[int, ...], ...]
    probabilities: tuple[float, ...]
    weekly_appearance: float
    fixture_probabilities: tuple[tuple[float, ...], ...]
    model_sha256: str
    input_sha256: str


@dataclass(frozen=True)
class _Transform:
    names: tuple[str, ...]
    means: tuple[float, ...]
    scales: tuple[float, ...]
    known_counts: tuple[int, ...]
    gap_mean: float
    gap_scale: float


@dataclass(frozen=True)
class _Fitted:
    transform: _Transform
    coefficients: FloatArray
    metadata: LoadMinutesMetadata
    metadata_json: str


@dataclass(frozen=True)
class _PackedExample:
    context: FloatArray
    counts: FloatArray
    trailing: FloatArray
    native: FloatArray
    observed_index: int


def _utc(value: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError("load model clocks must be explicit UTC strings")
    try:
        instant = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("invalid load model UTC clock") from exc
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise ValueError("load model clocks require an explicit UTC offset")
    return instant.astimezone(UTC)


def _season(value: str) -> int:
    if not isinstance(value, str) or re.fullmatch(r"[0-9]{4}-[0-9]{2}", value) is None:
        raise ValueError("invalid load model season")
    year = int(value[:4])
    if int(value[-2:]) != (year + 1) % 100:
        raise ValueError("invalid load model season continuation")
    return year


def _targets(season: str, gameweeks: tuple[int, ...]) -> None:
    _season(season)
    if season == "2025-26":
        raise ValueError("protected season is unavailable to the load experiment")
    if (
        not isinstance(gameweeks, tuple)
        or not gameweeks
        or any(type(gw) is not int or not 1 <= gw <= 38 for gw in gameweeks)
        or tuple(sorted(set(gameweeks))) != gameweeks
    ):
        raise ValueError("target gameweeks must be unique ascending integers from 1 to 38")


def _positive_float(value: float, name: str, *, zero_allowed: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be finite numeric")
    result = float(value)
    if not math.isfinite(result) or result < 0 or (not zero_allowed and result == 0):
        raise ValueError(f"{name} is outside its supported range")
    return result


def _native(week: LoadWeek) -> FloatArray:
    probabilities = np.asarray(week.native_joint_probabilities, dtype=np.float64)
    total = math.fsum(float(p) for p in probabilities)
    if (
        probabilities.ndim != 1
        or len(probabilities) != len(week.native_joint_states)
        or not np.isfinite(probabilities).all()
        or np.any(probabilities < 0)
        or abs(total - 1.0) > _MASS_TOLERANCE
        or total <= 0
    ):
        raise ValueError("native joint probabilities must be coherent")
    return probabilities / total


def _readonly(values: FloatArray) -> FloatArray:
    # Immutable bytes keep setflags(write=True) from changing fitted parameters.
    return np.frombuffer(values.astype(np.float64).tobytes(), dtype=np.float64)


def _transform(weeks: tuple[LoadWeek, ...]) -> _Transform:
    names = tuple(LOAD_FEATURE_NAMES)
    means: list[float] = []
    scales: list[float] = []
    counts: list[int] = []
    for index in range(len(names)):
        known = []
        for week in weeks:
            value = week.features[index]
            if value is not None:
                known.append(float(value))
        counts.append(len(known))
        mean = math.fsum(known) / len(known) if known else 0.0
        scale = math.sqrt(math.fsum((x - mean) ** 2 for x in known) / len(known)) if known else 1.0
        means.append(mean)
        scales.append(scale if scale > 0 else 1.0)
    gaps = [
        (
            _utc(week.fixtures[index].kickoff) - _utc(week.fixtures[index - 1].kickoff)
        ).total_seconds()
        / 3600
        for week in weeks
        for index in range(1, len(week.fixtures))
    ]
    gap_mean = math.fsum(gaps) / len(gaps) if gaps else 0.0
    gap_scale = (
        math.sqrt(math.fsum((gap - gap_mean) ** 2 for gap in gaps) / len(gaps)) if gaps else 1.0
    )
    return _Transform(names, tuple(means), tuple(scales), tuple(counts), gap_mean, gap_scale or 1.0)


def _context(week: LoadWeek, transform: _Transform) -> tuple[FloatArray, tuple[str, ...]]:
    values: list[float] = [1.0]
    names: list[str] = ["intercept"]
    for index, name in enumerate(transform.names):
        if name.startswith("fixture_"):
            continue
        raw = week.features[index]
        if raw is not None and transform.known_counts[index] == 0:
            raise ValueError(f"no training support for observed load feature {name}")
        values.extend(
            [
                0.0 if raw is None else (raw - transform.means[index]) / transform.scales[index],
                float(raw is None),
            ]
        )
        names.extend([name, name + "_missing"])
    values.extend(float(week.position == position) for position in _POSITIONS)
    names.extend("position_" + position for position in _POSITIONS)
    return np.asarray(values, dtype=np.float64), tuple(names)


def _packed_design(
    week: LoadWeek, transform: _Transform
) -> tuple[FloatArray, FloatArray, FloatArray, tuple[str, ...]]:
    context, context_names = _context(week, transform)
    names = [
        prefix + ":" + name for prefix in ("weekly_appearance", *_BINS) for name in context_names
    ]
    names.extend(
        bin_name + ":target_" + suffix + ending
        for bin_name in _BINS
        for suffix in _FIXTURE_SUFFIXES
        for ending in ("", "_missing")
    )
    names.extend(
        bin_name + ":" + suffix
        for bin_name in _BINS
        for suffix in (
            "prior_week_minutes90",
            "prior_fixture_gap_scaled",
            "prior_minutes90_x_gap_scaled",
        )
    )
    counts = np.zeros((len(week.native_joint_states), 7), dtype=np.float64)
    trailing = np.zeros((len(week.native_joint_states), 42), dtype=np.float64)
    for row, state in enumerate(week.native_joint_states):
        counts[row] = [float(any(state)), *(float(state.count(index)) for index in range(1, 7))]
        prior_minutes90 = 0.0
        for index, state_bin in enumerate(state):
            if state_bin:
                for field_index, suffix in enumerate(_FIXTURE_SUFFIXES):
                    feature_index = transform.names.index(f"fixture_{index + 1}_" + suffix)
                    raw = week.features[feature_index]
                    if raw is not None and transform.known_counts[feature_index] == 0:
                        raise ValueError("no training support for target fixture load feature")
                    at = (state_bin - 1) * 4 + field_index * 2
                    trailing[row, at] += (
                        0.0
                        if raw is None
                        else (raw - transform.means[feature_index])
                        / transform.scales[feature_index]
                    )
                    trailing[row, at + 1] += float(raw is None)
                if index:
                    hours = (
                        _utc(week.fixtures[index].kickoff) - _utc(week.fixtures[index - 1].kickoff)
                    ).total_seconds() / 3600
                    gap = (hours - transform.gap_mean) / transform.gap_scale
                    at = 24 + (state_bin - 1) * 3
                    trailing[row, at : at + 3] += np.asarray(
                        [prior_minutes90, gap, prior_minutes90 * gap]
                    )
            prior_minutes90 += week.fixtures[index].minutes[state_bin] / 90
    if not np.isfinite(context).all() or not np.isfinite(trailing).all():
        raise ValueError("nonfinite load design")
    return context, counts, trailing, tuple(names)


def _packed_logits(example: _PackedExample, coefficients: FloatArray) -> FloatArray:
    width = len(example.context)
    if coefficients.shape != (7 * width + 42,):
        raise ValueError("load coefficient shape differs from its design")
    heads = coefficients[: 7 * width].reshape(7, width) @ example.context
    return example.counts @ heads + example.trailing @ coefficients[7 * width :]


def _tilt(native: FloatArray, scores: FloatArray) -> FloatArray:
    support = native > 0
    log_weights = np.log(native[support]) + scores[support]
    log_normalizer = float(logsumexp(log_weights))
    if not math.isfinite(log_normalizer):
        raise ValueError("nonfinite load probability normalizer")
    positive = np.exp(log_weights - log_normalizer)
    if not np.isfinite(positive).all() or np.any(positive <= 0):
        raise ValueError("load tilt underflow would erase native support")
    probabilities = np.zeros_like(native)
    probabilities[support] = positive / math.fsum(float(p) for p in positive)
    return probabilities


def objective_gradient(
    coefficients: FloatArray, examples: Sequence[LoadTrainingExample], l2: float
) -> tuple[float, FloatArray]:
    """Exact summed categorical negative log likelihood plus declared ridge."""
    penalty = _positive_float(l2, "l2", zero_allowed=True)
    if coefficients.ndim != 1 or not np.isfinite(coefficients).all() or not examples:
        raise ValueError("load objective requires finite coefficients and examples")
    objective = 0.5 * penalty * float(coefficients @ coefficients)
    gradient = penalty * coefficients.copy()
    for example in examples:
        matrix = example.design
        native = example.native_probabilities
        observed = example.observed_index
        if (
            matrix.shape != (len(native), len(coefficients))
            or not np.isfinite(matrix).all()
            or not np.isfinite(native).all()
            or np.any(native < 0)
            or type(observed) is not int
            or not 0 <= observed < len(native)
            or native[observed] <= 0
        ):
            raise ValueError("observed minute state has no valid native support")
        support = native > 0
        logits = np.log(native[support]) + matrix[support] @ coefficients
        normalizer = float(logsumexp(logits))
        weights = np.exp(logits - normalizer)
        if not math.isfinite(normalizer) or not np.isfinite(weights).all():
            raise ValueError("nonfinite load objective")
        objective += (
            normalizer - math.log(float(native[observed])) - float(matrix[observed] @ coefficients)
        )
        gradient += weights @ matrix[support] - matrix[observed]
    if not math.isfinite(objective) or not np.isfinite(gradient).all():
        raise ValueError("nonfinite load objective or gradient")
    return float(objective), gradient


def _packed_objective_gradient(
    coefficients: FloatArray, examples: Sequence[_PackedExample], l2: float
) -> tuple[float, FloatArray]:
    objective = 0.5 * l2 * float(coefficients @ coefficients)
    gradient = l2 * coefficients.copy()
    for example in examples:
        scores = _packed_logits(example, coefficients)
        support = example.native > 0
        logits = np.log(example.native[support]) + scores[support]
        normalizer = float(logsumexp(logits))
        probabilities = np.exp(logits - normalizer)
        observed = example.observed_index
        objective += (
            normalizer - math.log(float(example.native[observed])) - float(scores[observed])
        )
        width = len(example.context)
        residual_counts = probabilities @ example.counts[support] - example.counts[observed]
        gradient[: 7 * width] += np.outer(residual_counts, example.context).ravel()
        gradient[7 * width :] += (
            probabilities @ example.trailing[support] - example.trailing[observed]
        )
    if not math.isfinite(objective) or not np.isfinite(gradient).all():
        raise ValueError("nonfinite packed load objective or gradient")
    return float(objective), gradient


def _verify_fitted(fitted: _Fitted) -> None:
    metadata = fitted.metadata
    payload = json.loads(fitted.metadata_json)
    expected = asdict(metadata)
    expected.pop("model_sha256")
    if (
        hashlib.sha256(fitted.metadata_json.encode("utf-8")).hexdigest() != metadata.model_sha256
        or metadata.model_version != MODEL_VERSION
        or metadata.feature_version != FEATURE_VERSION
        or any(
            payload.get(name) != json.loads(json.dumps(value)) for name, value in expected.items()
        )
        or fitted.transform
        != _Transform(
            metadata.feature_names,
            metadata.means,
            metadata.scales,
            metadata.known_counts,
            metadata.gap_mean_hours,
            metadata.gap_scale_hours,
        )
        or tuple(float(value) for value in fitted.coefficients) != metadata.coefficients
    ):
        raise ValueError("fitted load parameters and transforms do not match their receipt")


class LoadMinutesModel:
    def __init__(self) -> None:
        self._fitted: _Fitted | None = None

    @property
    def metadata(self) -> LoadMinutesMetadata:
        if self._fitted is None:
            raise ValueError("load model is not fitted")
        return self._fitted.metadata

    @property
    def metadata_json(self) -> str:
        if self._fitted is None:
            raise ValueError("load model is not fitted")
        return self._fitted.metadata_json

    @property
    def model_sha256(self) -> str:
        return self.metadata.model_sha256

    def fit(
        self,
        training: Sequence[TrainingLoadWeek],
        *,
        cutoff: str,
        target_season: str,
        target_gameweeks: tuple[int, ...],
        l2: float = 1.0,
        max_iterations: int = 1000,
    ) -> LoadMinutesModel:
        _targets(target_season, target_gameweeks)
        fit_clock = _utc(cutoff)
        cutoff = fit_clock.isoformat().replace("+00:00", "Z")
        penalty = _positive_float(l2, "l2", zero_allowed=True)
        if type(max_iterations) is not int or not 1 <= max_iterations <= 1000:
            raise ValueError("max_iterations must be an integer from 1 to 1000")
        rows = tuple(training)
        if not rows:
            raise ValueError("load fit requires training weeks")
        common_clocks: dict[tuple[str, int], datetime] = {}
        identities: set[tuple[str, int, int]] = set()
        # Global metadata preflight precedes any access to observed state labels.
        for row in rows:
            if type(row) is not TrainingLoadWeek:
                raise ValueError("load training rows must be immutable TrainingLoadWeek values")
            week = row.input
            if type(week) is not LoadWeek:
                raise ValueError("load training inputs must be immutable LoadWeek values")
            if (
                week.season == "2025-26"
                or _season(week.season) > _season(target_season)
                or (week.season == target_season and week.gameweek >= min(target_gameweeks))
                or _utc(week.decision_at) >= fit_clock
            ):
                raise ValueError("training week is outside the causal load fit")
            validate_load_week(week)
            key = (week.season, week.gameweek)
            decision_clock = _utc(week.decision_at)
            if key in common_clocks and common_clocks[key] != decision_clock:
                raise ValueError("historical gameweek needs one original decision clock")
            common_clocks[key] = decision_clock
            identity = (*key, week.player_code)
            if identity in identities:
                raise ValueError("duplicate load training player week")
            identities.add(identity)
        for row in rows:
            validate_training_load_week(
                row,
                fit_cutoff=cutoff,
                target_season=target_season,
                target_gameweeks=target_gameweeks,
            )
        weeks = tuple(row.input for row in rows)
        transform = _transform(weeks)
        examples: list[_PackedExample] = []
        design_names: tuple[str, ...] = ()
        for row in rows:
            context, counts, trailing, design_names = _packed_design(row.input, transform)
            native = _native(row.input)
            try:
                observed_index = row.input.native_joint_states.index(row.observed_states)
            except ValueError as exc:
                raise ValueError("observed load state is outside the native calendar") from exc
            if native[observed_index] <= 0:
                raise ValueError("observed minute state has no native support")
            examples.append(_PackedExample(context, counts, trailing, native, observed_index))
        initial = np.zeros(len(design_names), dtype=np.float64)
        result = cast(
            Any,
            minimize(
                lambda parameters: _packed_objective_gradient(parameters, examples, penalty),
                initial,
                method="L-BFGS-B",
                jac=True,
                bounds=[(-20.0, 20.0)] * len(initial),
                options={"maxiter": max_iterations, "ftol": 1e-12, "gtol": 1e-7},
            ),
        )
        coefficients = np.asarray(result.x, dtype=np.float64)
        if (
            not result.success
            or coefficients.shape != initial.shape
            or not np.isfinite(coefficients).all()
        ):
            raise ValueError("load optimizer did not converge to finite parameters")
        objective, gradient = _packed_objective_gradient(coefficients, examples, penalty)
        for example in examples:
            _tilt(example.native, _packed_logits(example, coefficients))
        payload = {
            "model_version": MODEL_VERSION,
            "feature_version": FEATURE_VERSION,
            "cutoff": cutoff,
            "target_season": target_season,
            "target_gameweeks": target_gameweeks,
            "training_seasons": tuple(sorted({week.season for week in weeks})),
            "feature_names": transform.names,
            "design_names": design_names,
            "means": transform.means,
            "scales": transform.scales,
            "known_counts": transform.known_counts,
            "gap_mean_hours": transform.gap_mean,
            "gap_scale_hours": transform.gap_scale,
            "coefficients": tuple(float(value) for value in coefficients),
            "training_input_sha256": tuple(load_input_digest(week) for week in weeks),
            "training_outcome_sha256": tuple(row.outcome_sha256 for row in rows),
            "l2": penalty,
            "max_iterations": max_iterations,
            "iterations": int(result.nit),
            "objective": objective,
            "gradient_max_abs": float(np.max(np.abs(gradient))),
            "native_mass_policy": "normalize_once_after_1e-12_validation_preserve_zeros",
            "eligibility_policy": "not_applied_by_model",
            "prior_minutes_policy": "within_week_supplied_state_FPL_minutes_not_future_cup_minutes",
            "coefficient_bounds": (-20.0, 20.0),
            "optimizer": "deterministic_zero_init_bounded_L-BFGS-B",
        }
        metadata_json = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
        model_sha = hashlib.sha256(metadata_json.encode("utf-8")).hexdigest()
        metadata = LoadMinutesMetadata(
            MODEL_VERSION,
            FEATURE_VERSION,
            cutoff,
            target_season,
            target_gameweeks,
            tuple(sorted({week.season for week in weeks})),
            transform.names,
            design_names,
            transform.means,
            transform.scales,
            transform.known_counts,
            transform.gap_mean,
            transform.gap_scale,
            tuple(float(value) for value in coefficients),
            tuple(load_input_digest(week) for week in weeks),
            tuple(row.outcome_sha256 for row in rows),
            penalty,
            max_iterations,
            int(result.nit),
            objective,
            float(np.max(np.abs(gradient))),
            model_sha,
        )
        # Publish only after every validation, optimization and receipt succeeds.
        self._fitted = _Fitted(transform, _readonly(coefficients), metadata, metadata_json)
        return self

    def predict(self, week: LoadWeek, *, zero_coefficients: bool = False) -> WeekLoadPrediction:
        if type(zero_coefficients) is not bool:
            raise ValueError("zero_coefficients must be Boolean")
        fitted = self._fitted
        if fitted is None:
            raise ValueError("load model is not fitted")
        validate_load_week(week)
        if (
            week.season != fitted.metadata.target_season
            or week.gameweek not in fitted.metadata.target_gameweeks
            or _utc(week.decision_at) < _utc(fitted.metadata.cutoff)
        ):
            raise ValueError("projection is outside the fitted load target")
        _verify_fitted(fitted)
        native = _native(week)
        if zero_coefficients:
            probabilities = native
        else:
            context, counts, trailing, names = _packed_design(week, fitted.transform)
            if names != fitted.metadata.design_names:
                raise ValueError("load design identity changed")
            packed = _PackedExample(context, counts, trailing, native, 0)
            probabilities = _tilt(native, _packed_logits(packed, fitted.coefficients))
        states = week.native_joint_states
        marginal = tuple(
            tuple(
                math.fsum(
                    float(probabilities[row])
                    for row, state in enumerate(states)
                    if state[index] == state_bin
                )
                for state_bin in range(7)
            )
            for index in range(len(week.fixtures))
        )
        appearance = math.fsum(
            float(probabilities[index]) for index, state in enumerate(states) if any(state)
        )
        return WeekLoadPrediction(
            week,
            states,
            tuple(float(value) for value in probabilities),
            appearance,
            marginal,
            fitted.metadata.model_sha256,
            load_input_digest(week),
        )
